import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

# Универсальная переменная окружения. Для продакшена на ZevCloud установи DATABASE_URL на PostgreSQL.
# Пример для PostgreSQL: postgresql://user:password@localhost/ponycase
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

def run_migrations():
    """
    Безопасная миграция схемы БД.
    Автоматически определяет тип базы данных (SQLite или PostgreSQL) 
    и применяет соответствующие команды, чтобы приложение не падало при смене окружения.
    """
    with engine.connect() as conn:
        dialect = engine.dialect.name
        
        try:
            if dialect == "sqlite":
                # Для SQLite проверяем наличие колонок через PRAGMA
                result = conn.execute(text("PRAGMA table_info(users);")).fetchall()
                existing_cols = [row[1] for row in result]
                
                if "best_drop_price" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN best_drop_price BIGINT DEFAULT 0;"))
                if "best_drop_name" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN best_drop_name VARCHAR(64);"))
                if "last_bonus" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_bonus TIMESTAMP;"))
                if "nonce" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN nonce BIGINT DEFAULT 0;"))
                if "last_passive_tick" not in existing_cols:
                    conn.execute(text("ALTER TABLE users ADD COLUMN last_passive_tick TIMESTAMP;"))
                    
            elif dialect == "postgresql":
                # Для PostgreSQL используем безопасный синтаксис ADD COLUMN IF NOT EXISTS
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS best_drop_price BIGINT DEFAULT 0;"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS best_drop_name VARCHAR(64);"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMP;"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS nonce BIGINT DEFAULT 0;"))
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_passive_tick TIMESTAMP;"))
            
            conn.commit()
            print(f"=== ✅ МИГРАЦИЯ БАЗЫ ДАННЫХ ({dialect.upper()}) УСПЕШНА ===")
        except Exception as e:
            print(f"=== ⚠️ ОШИБКА МИГРАЦИИ (возможно, колонки уже существуют): {e} ===")
            conn.rollback()

# Запускаем миграции при импорте модуля
run_migrations()
