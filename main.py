# main.py
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
from openai import AzureOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db, engine
from models import Base, CaptionRecord, License
from fastapi import Header

# 1. Загрузка .env
load_dotenv()

# 2. Инициализация AzureOpenAI
endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
api_ver = os.getenv("AZURE_OPENAI_API_VERSION")
deployment = os.getenv("AZURE_OPENAI_API_DEPLOYMENT_NAME")
client = AzureOpenAI(
    azure_endpoint=endpoint,
    api_key=api_key,
    api_version=api_ver,
)

app = FastAPI(title="AI Social Caption Generator")


# 3. При старте создаём таблицы, если нет
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class GenerateRequest(BaseModel):
    topic: str
    tone: str
    channel: str


@app.get("/")
async def root():
    return {"message": "Service is up!"}


@app.post("/generate")
async def generate(
    req: GenerateRequest,
    license_key: str = Header(..., convert_underscores=False),  # требует X-License-Key
    db: AsyncSession = Depends(get_db),
):
    # 1) Проверяем лицензию
    now = datetime.utcnow()
    q = await db.execute(
        License.__table__.select().where(License.license_key == license_key)
    )
    lic = q.scalar_one_or_none()
    if not lic or lic.active_until < now:
        raise HTTPException(status_code=403, detail="License expired or not found")

    # 2) Формируем промпт и зовём OpenAI
    prompt = (
        f"Generate a social media caption for {req.channel} "
        f'on the topic "{req.topic}" in a {req.tone} tone. '
        "Include relevant hashtags."
    )
    try:
        resp = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )
        text = resp.choices[0].message.content.strip()

        # 3) Сохраняем в БД
        record = CaptionRecord(
            topic=req.topic,
            tone=req.tone,
            channel=req.channel,
            caption=text,
        )
        db.add(record)
        await db.commit()

        return {"caption": text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook")
async def gumroad_webhook(req: Request, db: AsyncSession = Depends(get_db)):
    """
    Обработка webhook от Gumroad (sale и subscription_cancelled).
    Gumroad присылает form-urlencoded payload.
    """
    form = await req.form()
    event = form.get("event_name")  # sale, subscription_cancelled и т.д.
    email = form.get("email")
    license_key = form.get("license_key")  # приходит для digital goods

    if not all([event, email, license_key]):
        raise HTTPException(status_code=400, detail="Missing fields in Gumroad payload")

    now = datetime.utcnow()

    if event == "sale":
        # для подписочных товаров Gumroad присылает next_charge_date
        next_date = form.get("next_charge_date")
        if next_date:
            # формат ISO 8601: "2025-06-19T00:00:00Z"
            active_until = datetime.fromisoformat(next_date.replace("Z", "+00:00"))
        else:
            active_until = now + timedelta(days=30)

        # создаём или обновляем лицензию
        q = await db.execute(
            License.__table__.select().where(License.license_key == license_key)
        )
        lic = q.scalar_one_or_none()
        if lic:
            lic.active_until = active_until
        else:
            lic = License(
                email=email, license_key=license_key, active_until=active_until
            )
            db.add(lic)
        await db.commit()
        return {"status": "ok", "active_until": active_until.isoformat()}

    elif event == "subscription_cancelled":
        # помечаем подписку как истёкшую
        q = await db.execute(
            License.__table__.select().where(License.license_key == license_key)
        )
        lic = q.scalar_one_or_none()
        if lic:
            lic.active_until = now
            await db.commit()
        return {"status": "cancelled"}

    else:
        # игнорируем другие события
        return {"status": f"ignored event {event}"}
