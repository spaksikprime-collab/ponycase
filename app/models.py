import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Boolean, Text, Index
from .db import Base

# Используем lambda для корректного времени
def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(32), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    avatar = Column(Text, default="🦄")
    balance = Column(BigInteger, default=1000, nullable=False, index=True) # ДОБАВЛЕН ИНДЕКС (для Топа)
    total_clicks = Column(BigInteger, default=0)
    click_power = Column(Integer, default=1)
    auto_rate = Column(Float, default=0.0)
    multiplier = Column(Float, default=1.0)
    nonce = Column(BigInteger, default=0)
    last_bonus = Column(DateTime, nullable=True)
    best_drop_price = Column(BigInteger, default=0)
    best_drop_name = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    last_passive_tick = Column(DateTime, default=utc_now)

class InventoryItem(Base):
    __tablename__ = "inventory"
    id = Column(Integer, primary_key=True)
    # ДОБАВЛЕН CASCADE (удаление предметов при удалении юзера)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pony_id = Column(String(64), nullable=False)
    rarity = Column(String(32), nullable=False)
    price = Column(BigInteger, default=0, index=True) # ДОБАВЛЕН ИНДЕКС (для сортировки в профиле)
    color = Column(String(16), default="#fff")
    obtained_at = Column(DateTime, default=utc_now)

class CaseOpen(Base):
    __tablename__ = "case_opens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    case_id = Column(String(32), nullable=False)
    pony_id = Column(String(64), nullable=False)
    rarity = Column(String(32), nullable=False)
    price = Column(BigInteger, nullable=False)
    server_seed = Column(String(64), nullable=False)
    client_seed = Column(String(64), nullable=False)
    nonce = Column(BigInteger, nullable=False)
    ticket = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utc_now)

class GameHistory(Base):
    __tablename__ = "game_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    game_type = Column(String(32), nullable=False) 
    item_name = Column(String(64), nullable=False)
    price = Column(BigInteger, default=0)
    result_text = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True) # ДОБАВЛЕН ИНДЕКС (для истории)

    # Составной индекс для моментальной загрузки истории профиля
    __table_args__ = (
        Index('ix_game_history_user_created', 'user_id', 'created_at'),
    )
