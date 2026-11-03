import os
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import socketio

# Импортируем инициализацию БД и модели
from .db import init_db
from . import models  # Необходимо для регистрации моделей в Base.metadata перед init_db()

# Импортируем роутеры
from .auth import router as auth_router
from .clicker import router as clicker_router
from .cases import router as cases_router
from .user import router as user_router
from .upgrade import router as upgrade_router
from .battles import router as battles_router
from .mines import router as mines_router
from .wheel import router as wheel_router, wheel_game_loop

# Импортируем Socket.IO сервер
from .ws import sio

# ==========================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==========================================
# УПРАВЛЕНИЕ ЖИЗНЕННЫМ ЦИКЛОМ (LIFESPAN)
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Выполняется один раз при запуске приложения.
    Гарантирует безопасную инициализацию БД и фоновых задач.
    """
    logger.info("=== 🚀 ЗАПУСК СЕРВЕРА PONYCASE ===")
    
    # 1. Безопасная инициализация и миграция БД (выполняется 1 раз)
    init_db()
    
    # 2. Запуск фоновых задач (Колесо Фортуны)
    try:
        asyncio.create_task(wheel_game_loop())
        logger.info("=== ⚙️ ФОНОВЫЙ ТАЙМЕР КОЛЕСА ЗАПУЩЕН ===")
    except Exception as e:
        logger.error(f"Не удалось запустить фоновую задачу колеса: {e}")
    
    yield  # Приложение работает и обрабатывает запросы
    
    # 3. Выполняется при корректном завершении работы сервера
    logger.info("=== 🛑 СЕРВЕР ОСТАНОВЛЕН ===")

# ==========================================
# ИНИЦИАЛИЗАЦИЯ FASTAPI
# ==========================================
fastapi_app = FastAPI(
    title="PonyCase API", 
    description="Premium Case Opening & Mini-games Platform",
    version="1.0.0",
    lifespan=lifespan
)

# Создание папки static, если её нет
if not os.path.exists("static"): 
    os.makedirs("static", exist_ok=True)

fastapi_app.mount("/static", StaticFiles(directory="static"), name="static")

# ==========================================
# ГЛОБАЛЬНЫЙ ОБРАБОТЧИК ОШИБОК
# ==========================================
@fastapi_app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Перехватывает все необработанные исключения, логирует их и отдает клиенту безопасный ответ."""
    logger.error(f"CRITICAL ERROR on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500, 
        content={"detail": "Внутренняя ошибка сервера. Попробуйте позже."}
    )

# ==========================================
# MIDDLEWARE (CORS)
# ==========================================
# ВНИМАНИЕ: Для продакшена замените ["*"] на конкретный домен фронтенда, 
# например: allow_origins=["https://ponycase.zevcloud.ru"]
fastapi_app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

# ==========================================
# ПОДКЛЮЧЕНИЕ РОУТЕРОВ
# ==========================================
fastapi_app.include_router(auth_router,    prefix="/api/auth", tags=["Auth"])
fastapi_app.include_router(clicker_router, prefix="/api/clicker", tags=["Clicker"])
fastapi_app.include_router(cases_router,   prefix="/api/cases", tags=["Cases"])
fastapi_app.include_router(user_router,    prefix="/api/user", tags=["User"])
fastapi_app.include_router(upgrade_router, prefix="/api/upgrade", tags=["Upgrade"])
fastapi_app.include_router(battles_router, prefix="/api/battles", tags=["Battles"])
fastapi_app.include_router(mines_router,   prefix="/api/mines", tags=["Mines"])
fastapi_app.include_router(wheel_router,   prefix="/api/wheel", tags=["Wheel"])

# ==========================================
# БАЗОВЫЕ ЭНДПОИНТЫ
# ==========================================
@fastapi_app.get("/api/health", tags=["System"])
def health_check(): 
    return {"status": "ok", "message": "PonyCase API is running"}

@fastapi_app.get("/", include_in_schema=False)
def serve_frontend():
    """Отдает index.html для SPA-фронтенда."""
    if os.path.exists("index.html"): 
        return FileResponse("index.html")
    return JSONResponse(status_code=404, content={"detail": "index.html not found"})

# ==========================================
# ИНТЕГРАЦИЯ SOCKET.IO
# ==========================================
# Оборачиваем FastAPI в Socket.IO ASGI App для одновременной работы REST и WebSockets
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)
