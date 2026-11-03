import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./ponycase.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# pool_pre_ping=True проверяет соединение перед использованием
engine = create_engine(
    DATABASE_URL, 
    connect_args=connect_args, 
    pool_pre_ping=True,
    pool_size=20,          # Держим пул соединений
    max_overflow=10        # Позволяем временные всплески
)

# ВКЛЮЧАЕМ WAL РЕЖИМ ДЛЯ SQLITE (Критически важно для скорости!)
if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;") # Позволяет читать и писать одновременно
        cursor.execute("PRAGMA synchronous=NORMAL;") # Ускоряет запись
        cursor.execute("PRAGMA cache_size=-64000;") # Выделяем 64МБ кэша под базу
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
