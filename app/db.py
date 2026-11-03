import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Универсальная переменная окружения. 
# Для продакшена на ZevCloud установи DATABASE_URL на PostgreSQL.
# Пример: postgresql://user:password@localhost:5432/ponycase
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ponycase.db")

# Настройки подключения: check_same_thread нужен только для SQLite
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Оптимизированный пул соединений для стабильной работы под нагрузкой
engine = create_engine(
    DATABASE_URL, 
    connect_args=connect_args, 
    pool_pre_ping=True,      # Проверяет "живость" соединения перед использованием (спасает от разрывов)
    pool_size=20,            # Базовый размер пула
    max_overflow=10          # Дополнительные соединения при пиковых нагрузках
)

# ВКЛЮЧАЕМ WAL РЕЖИМ ТОЛЬКО ДЛЯ SQLITE (Критически важно для скорости и конкурентного доступа!)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")       # Позволяет читать и писать одновременно
        cursor.execute("PRAGMA synchronous=NORMAL;")     # Ускоряет запись без потери надежности
        cursor.execute("PRAGMA cache_size=-64000;")      # Выделяем 64МБ кэша в оперативной памяти
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def get_db():
    """Зависимость FastAPI для получения сессии БД с гарантированным закрытием."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def utc_now():
    """Современный и безопасный способ получения текущего времени в UTC."""
    return datetime.now(timezone.utc)

def init_db():
    """
    Безопасная инициализация и миграция БД.
    ВЫЗЫВАТЬ ОДИН РАЗ при старте приложения (в main.py через lifespan или on_event).
    """
    # 1. Сначала создаем все таблицы, если их нет (на основе моделей)
    # Это предотвратит ошибку "no such table" при выполнении ALTER TABLE
    Base.metadata.create_all(bind=engine)
    
    # 2. Кастомные миграции для добавления колонок в существующую таблицу Users
    # Импортируем модель здесь, чтобы избежать циклических зависимостей при старте
    from .models import User 
    table_name = User.__tablename__
    
    with engine.connect() as conn:
        dialect = engine.dialect.name
        
        try:
            if dialect == "sqlite":
                # Для SQLite проверяем наличие колонок через PRAGMA
                result = conn.execute(text(f"PRAGMA table_info({table_name});")).fetchall()
                existing_cols = [row[1] for row in result]
                
                if "best_drop_price" not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN best_drop_price BIGINT DEFAULT 0;"))
                if "best_drop_name" not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN best_drop_name VARCHAR(64);"))
                if "last_bonus" not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN last_bonus TIMESTAMP;"))
                if "nonce" not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN nonce BIGINT DEFAULT 0;"))
                if "last_passive_tick" not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN last_passive_tick TIMESTAMP;"))
                    
            elif dialect == "postgresql":
                # Для PostgreSQL используем безопасный синтаксис ADD COLUMN IF NOT EXISTS
                # и TIMESTAMPTZ для корректной работы с timezone-aware datetime
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS best_drop_price BIGINT DEFAULT 0;"))
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS best_drop_name VARCHAR(64);"))
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMPTZ;"))
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS nonce BIGINT DEFAULT 0;"))
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS last_passive_tick TIMESTAMPTZ;"))
            
            conn.commit()
            print(f"=== ✅ ИНИЦИАЛИЗАЦИЯ И МИГРАЦИЯ БД ({dialect.upper()}) УСПЕШНА ===")
        except Exception as e:
            print(f"=== ⚠️ ОШИБКА МИГРАЦИИ (возможно, колонки уже существуют или нет прав): {e} ===")
            conn.rollback()

# ВАЖНО: Мы НЕ вызываем init_db() здесь автоматически.
# Это должно быть сделано в main.py при запуске приложения.
