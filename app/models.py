import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Boolean, Text
from .db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, index=True, nullable=False)
    email = Column(String(128), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=True)
    avatar = Column(Text, default="🦄")
    balance = Column(BigInteger, default=100, nullable=False)
    total_clicks = Column(BigInteger, default=0)
    click_power = Column(Integer, default=1)
    auto_rate = Column(Float, default=0.0)
    multiplier = Column(Float, default=1.0)
    prestige = Column(Integer, default=0)
    nonce = Column(BigInteger, default=0)
    is_admin = Column(Boolean, default=False)
    is_verified = Column(Boolean, default=True) # <--- Всегда True
    verification_code = Column(String(10), nullable=True)
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
    obtained_at = Column(DateTime, default=datetime.datetime.utcnow)

class CaseOpen(Base):
    __tablename__ = "case_opens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    case_id = Column(String(32), nullable=False)
    pony_id = Column(String(64), nullable=False)
    rarity = Column(String(32), nullable=False)
    price = Column(BigInteger, nullable=False)
    server_seed = Column(String(64), nullable=False)
    client_seed = Column(String(64), nullable=False)
    nonce = Column(BigInteger, nullable=False)
    ticket = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
