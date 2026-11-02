import os
import asyncio
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
# ДОБАВЛЕНО: Импорт роутера и фоновой задачи для Колеса
from .wheel import router as wheel_router, wheel_game_loop
from .ws import sio

# Создаем все таблицы в базе данных
Base.metadata.create_all(bind=engine)

# Автоматическая миграция (добавляет новые колонки, если их нет)
def run_migrations():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS best_drop_price BIGINT DEFAULT 0;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS best_drop_name VARCHAR(64);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMP;"))
            conn.commit()
            print("=== МИГРАЦИЯ БАЗЫ ДАННЫХ УСПЕШНА ===")
        except Exception as e:
            print(f"=== ОШИБКА МИГРАЦИИ: {e} ===")

run_migrations()

# Инициализация FastAPI
api = FastAPI(title="PonyCase API")

# Раздача статики (картинок, если они будут)
if not os.path.exists("static"): 
    os.makedirs("static")
api.mount("/static", StaticFiles(directory="static"), name="static")

# Глобальный обработчик ошибок (чтобы сервер не падал молча)
@api.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Ошибка: {exc}") # Выводим ошибку в логи ZevCloud
    return JSONResponse(status_code=500, content={"detail": str(exc)})

# Настройка CORS (разрешаем запросы с любых устройств)
api.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ==========================================
# ПОДКЛЮЧЕНИЕ ВСЕХ РОУТЕРОВ
# ==========================================
api.include_router(auth_router,    prefix="/api/auth")
api.include_router(clicker_router, prefix="/api/clicker")
api.include_router(cases_router,   prefix="/api/cases")
api.include_router(user_router,    prefix="/api/user")
api.include_router(upgrade_router, prefix="/api/upgrade")
api.include_router(battles_router, prefix="/api/battles")
api.include_router(mines_router,   prefix="/api/mines")
# ДОБАВЛЕНО: Подключение Колеса
api.include_router(wheel_router,   prefix="/api/wheel")

# Проверка здоровья сервера
@api.get("/api/health")
def health(): 
    return {"ok": True}

# Отдача главной страницы (index.html)
@api.get("/")
def serve_frontend():
    if os.path.exists("index.html"): 
        return FileResponse("index.html")
    return {"error": "index.html not found"}

# ==========================================
# ЗАПУСК ФОНОВЫХ ЗАДАЧ (КОЛЕСО)
# ==========================================
@api.on_event("startup")
async def startup_event():
    # При запуске сервера стартуем бесконечный цикл игры в Колесо
    asyncio.create_task(wheel_game_loop())
    print("=== ФОНОВЫЙ ТАЙМЕР КОЛЕСА ЗАПУЩЕН ===")

# Оборачиваем FastAPI в Socket.IO для работы WebSockets
app = socketio.ASGIApp(sio, other_asgi_app=api)
