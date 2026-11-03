from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, ForeignKey, Text, Index, CheckConstraint
from sqlalchemy.orm import relationship
from .db import Base, utc_now

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(32), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    avatar = Column(Text, default="🦄")
    
    # Баланс с индексом для быстрого топа игроков
    balance = Column(BigInteger, default=1000, nullable=False, index=True)
    total_clicks = Column(BigInteger, default=0, nullable=False)
    
    # Параметры кликера
    click_power = Column(Integer, default=1, nullable=False)
    auto_rate = Column(Float, default=0.0, nullable=False)
    multiplier = Column(Float, default=1.0, nullable=False)
    
    # Provably Fair и безопасность
    nonce = Column(BigInteger, default=0, nullable=False)
    
    # Бонусы и достижения
    last_bonus = Column(DateTime(timezone=True), nullable=True)
    best_drop_price = Column(BigInteger, default=0, nullable=False)
    best_drop_name = Column(String(64), nullable=True)
    
    # Временные метки с правильной поддержкой часовых поясов
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_passive_tick = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    
    # Relationships для cascade-удаления
    inventory = relationship("InventoryItem", back_populates="user", cascade="all, delete-orphan")
    case_opens = relationship("CaseOpen", back_populates="user", cascade="all, delete-orphan")
    game_history = relationship("GameHistory", back_populates="user", cascade="all, delete-orphan")
    
    # Constraints для защиты от невалидных данных
    __table_args__ = (
        CheckConstraint('balance >= 0', name='check_balance_non_negative'),
        CheckConstraint('click_power >= 1', name='check_click_power_positive'),
        CheckConstraint('auto_rate >= 0', name='check_auto_rate_non_negative'),
        CheckConstraint('multiplier >= 1.0', name='check_multiplier_minimum'),
        CheckConstraint('nonce >= 0', name='check_nonce_non_negative'),
    )

class InventoryItem(Base):
    __tablename__ = "inventory"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    pony_id = Column(String(64), nullable=False, index=True)
    rarity = Column(String(32), nullable=False, index=True)
    price = Column(BigInteger, default=0, nullable=False, index=True)
    color = Column(String(16), default="#ffffff", nullable=False)
    obtained_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    
    # Relationship
    user = relationship("User", back_populates="inventory")
    
    # Индексы для быстрой сортировки и фильтрации
    __table_args__ = (
        Index('ix_inventory_user_price', 'user_id', 'price'),
        Index('ix_inventory_user_rarity', 'user_id', 'rarity'),
    )

class CaseOpen(Base):
    __tablename__ = "case_opens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(String(32), nullable=False, index=True)
    pony_id = Column(String(64), nullable=False)
    rarity = Column(String(32), nullable=False, index=True)
    price = Column(BigInteger, nullable=False)
    
    # Provably Fair данные
    server_seed = Column(String(64), nullable=False)
    client_seed = Column(String(64), nullable=False)
    nonce = Column(BigInteger, nullable=False)
    ticket = Column(Integer, nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    
    # Relationship
    user = relationship("User", back_populates="case_opens")
    
    # Составной индекс для быстрого поиска открытий кейсов пользователем
    __table_args__ = (
        Index('ix_case_opens_user_created', 'user_id', 'created_at'),
    )

class GameHistory(Base):
    __tablename__ = "game_history"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    game_type = Column(String(32), nullable=False, index=True)
    item_name = Column(String(64), nullable=False)
    price = Column(BigInteger, default=0, nullable=False)
    result_text = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    
    # Relationship
    user = relationship("User", back_populates="game_history")
    
    # Составной индекс для моментальной загрузки истории профиля (новые записи сверху)
    __table_args__ = (
        Index('ix_game_history_user_created', 'user_id', 'created_at'),
        Index('ix_game_history_type_created', 'game_type', 'created_at'),
    )
