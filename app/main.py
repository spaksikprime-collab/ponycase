import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
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

# Глобальный обработчик ошибок (чтобы сайт не ломался, а показывал текст ошибки)
@api.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
    )

# 3. Настройка CORS
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
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "Файл index.html не найден."}

# 7. Оборачиваем FastAPI в Socket.IO
app = socketio.ASGIApp(sio, other_asgi_app=api)
