import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import socketio
from sqlalchemy import text

from .db import engine, Base
from . import models
from .auth import router as auth_router
from .clicker import router as clicker_router
from .cases import router as cases_router
from .user import router as user_router
from .upgrade import router as upgrade_router
from .battles import router as battles_router
from .mines import router as mines_router
from .wheel import router as wheel_router, wheel_game_loop
from .ws import sio

# Создаем все таблицы в базе данных
Base.metadata.create_all(bind=engine)

# ИСПРАВЛЕНО: Миграция для SQLite (он не поддерживает IF NOT EXISTS)
def run_migrations():
    with engine.connect() as conn:
        try:
            # Получаем список существующих колонок в таблице users
            result = conn.execute(text("PRAGMA table_info(users);")).fetchall()
            existing_cols = [row[1] for row in result]
            
            if "best_drop_price" not in existing_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN best_drop_price BIGINT DEFAULT 0;"))
            if "best_drop_name" not in existing_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN best_drop_name VARCHAR(64);"))
            if "last_bonus" not in existing_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN last_bonus TIMESTAMP;"))
                
            conn.commit()
            print("=== МИГРАЦИЯ БАЗЫ ДАННЫХ УСПЕШНА ===")
        except Exception as e:
            print(f"=== ОШИБКА МИГРАЦИИ: {e} ===")

run_migrations()

# Фоновая задача для Колеса
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запуск при старте сервера
    asyncio.create_task(wheel_game_loop())
    print("=== ФОНОВЫЙ ТАЙМЕР КОЛЕСА ЗАПУЩЕН ===")
    yield
    # Тут можно добавить код при выключении сервера
    print("=== СЕРВЕР ОСТАНОВЛЕН ===")

# Инициализация FastAPI
api = FastAPI(title="PonyCase API", lifespan=lifespan)

if not os.path.exists("static"): 
    os.makedirs("static")
api.mount("/static", StaticFiles(directory="static"), name="static")

# ИСПРАВЛЕНО: Глобальный обработчик ошибок (не палим детали хакерам)
@api.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Ошибку пишем в консоль сервера (видно в ZevCloud)
    print(f"CRITICAL ERROR: {exc}") 
    # Клиенту отдаем абстрактный текст
    return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка сервера"})

api.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ПОДКЛЮЧЕНИЕ ВСЕХ РОУТЕРОВ
api.include_router(auth_router,    prefix="/api/auth")
api.include_router(clicker_router, prefix="/api/clicker")
api.include_router(cases_router,   prefix="/api/cases")
api.include_router(user_router,    prefix="/api/user")
api.include_router(upgrade_router, prefix="/api/upgrade")
api.include_router(battles_router, prefix="/api/battles")
api.include_router(mines_router,   prefix="/api/mines")
api.include_router(wheel_router,   prefix="/api/wheel")

@api.get("/api/health")
def health(): 
    return {"ok": True}

@api.get("/")
def serve_frontend():
    if os.path.exists("index.html"): 
        return FileResponse("index.html")
    return {"error": "index.html not found"}

# Оборачиваем FastAPI в Socket.IO
app = socketio.ASGIApp(sio, other_asgi_app=api)
