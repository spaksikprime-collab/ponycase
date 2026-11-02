import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import socketio

from .db import engine, Base
from . import models  # noqa: F401
from .auth import router as auth_router
from .clicker import router as clicker_router
from .cases import router as cases_router
from .ws import sio

# 1. Создаем таблицы в БД (если их еще нет)
Base.metadata.create_all(bind=engine)

# 2. Инициализируем FastAPI
api = FastAPI(
    title="PonyCase API",
    description="Бэкенд для игры PonyCase с кликером и кейсами",
    version="1.0.0"
)

# 3. Настройка CORS (чтобы браузер не блокировал запросы)
# Если в переменных окружения CORS_ORIGINS="*", разрешаем всё.
cors_origins = os.getenv("CORS_ORIGINS", "*")
origins_list = ["*"] if cors_origins == "*" else [o.strip() for o in cors_origins.split(",")]

api.add_middleware(
    CORSMiddleware,
    allow_origins=origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 4. Подключаем API роутеры
api.include_router(auth_router,    prefix="/api/auth",    tags=["auth"])
api.include_router(clicker_router, prefix="/api/clicker", tags=["clicker"])
api.include_router(cases_router,   prefix="/api/cases",   tags=["cases"])

# 5. Эндпоинт для проверки работоспособности сервера
@api.get("/api/health", tags=["system"])
def health():
    return {"ok": True, "status": "running"}

# 6. Раздача главной страницы сайта (index.html)
@api.get("/", include_in_schema=False)
def serve_frontend():
    # Проверяем, существует ли файл в корне репозитория
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "Файл index.html не найден. Загрузите его в корень репозитория."}

# 7. Оборачиваем FastAPI в Socket.IO (для работы чата и дропов в реальном времени)
app = socketio.ASGIApp(sio, other_asgi_app=api)
