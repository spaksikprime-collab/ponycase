import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Boolean, Text
from .db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    avatar = Column(Text, default="🦄")
    balance = Column(BigInteger, default=1000, nullable=False)
    total_clicks = Column(BigInteger, default=0)
    click_power = Column(Integer, default=1)
    auto_rate = Column(Float, default=0.0)
    multiplier = Column(Float, default=1.0)
    nonce = Column(BigInteger, default=0)
    last_bonus = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_passive_tick = Column(DateTime, default=datetime.datetime.utcnow)

class InventoryItem(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    pony_id = Column(String(64), nullable=False)
    rarity = Column(String(32), nullable=False)
    price = Column(BigInteger, default=0)
    color = Column(String(16), default="#fff")
    obtained_at = Column(DateTime, default=datetime.datetime.utcnow)
