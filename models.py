# models.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from db import Base


class CaptionRecord(Base):
    __tablename__ = "caption_records"
    id = Column(Integer, primary_key=True, index=True)
    topic = Column(String, nullable=False)
    tone = Column(String, nullable=False)
    channel = Column(String, nullable=False)
    caption = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class License(Base):
    __tablename__ = "licenses"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False)
    license_key = Column(String, unique=True, index=True, nullable=False)
    active_until = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
