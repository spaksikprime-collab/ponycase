import time
import html
import logging
import asyncio
from datetime import datetime, timezone
from jose import jwt, JWTError
import socketio
from sqlalchemy import select

from .auth import SECRET_KEY, ALGORITHM
from .db import SessionLocal
from .models import User

logger = logging.getLogger(__name__)

# ==========================================
# ИНИЦИАЛИЗАЦИЯ SOCKET.IO СЕРВЕРА
# ==========================================
# ВНИМАНИЕ: Глобальные словари (ONLINE, SID_TO_USER) работают корректно 
# ТОЛЬКО при запуске Uvicorn с 1 воркером (--workers 1). 
# Для многопоточного продакшена необходимо заменить их на Redis (aioredis).
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*", # В продакшене заменить на ["https://твой-домен.ru"]
    logger=False,
    engineio_logger=False,
    ping_timeout=60,
    ping_interval=25
)

# ==========================================
# ГЛОБАЛЬНЫЕ СТРУКТУРЫ ДАННЫХ (In-Memory)
# ==========================================
ONLINE = set()
SID_TO_USER = {}
LAST_CHAT_TIME = {}
LAST_CONNECT_TIME = {}

# ==========================================
# КОНФИГУРАЦИЯ RATE LIMITING
# ==========================================
CHAT_RATE_LIMIT_SECONDS = 1.5
CHAT_MAX_LENGTH = 150 # Немного увеличено для удобства
MAX_CONNECTS_PER_MINUTE = 15

def sanitize_message(text: str) -> str:
    """Очищает сообщение от опасных символов для предотвращения XSS."""
    if not isinstance(text, str):
        return ""
    
    # Экранируем HTML-теги
    clean = html.escape(text)
    
    # Убираем control-символы (кроме переносов строк и табов)
    clean = "".join(c for c in clean if c in ('\n', '\t') or (ord(c) >= 32))
    
    # Заменяем множественные пробелы на один и обрезаем длину
    return " ".join(clean.split())[:CHAT_MAX_LENGTH]

def get_client_ip(environ: dict) -> str:
    """Извлекает IP-адрес клиента с поддержкой прокси (Cloudflare/Nginx)."""
    forwarded = environ.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return environ.get("REMOTE_ADDR", "unknown")

# ==========================================
# ОБРАБОТЧИКИ СОБЫТИЙ SOCKET.IO
# ==========================================

@sio.event
async def connect(sid, environ, auth):
    """Обработка подключения нового клиента."""
    client_ip = get_client_ip(environ)
    now = time.time()
    
    # 1. Защита от флуда подключениями (IP Rate Limit)
    recent_connects = LAST_CONNECT_TIME.get(client_ip, [])
    # Оставляем только записи за последнюю минуту
    recent_connects = [t for t in recent_connects if now - t < 60]
    
    if len(recent_connects) >= MAX_CONNECTS_PER_MINUTE:
        logger.warning(f"Rate limit exceeded for IP {client_ip}")
        raise socketio.exceptions.ConnectionRefusedError("Слишком много подключений. Подождите.")
    
    recent_connects.append(now)
    LAST_CONNECT_TIME[client_ip] = recent_connects
    
    # 2. Проверка JWT токена
    token = (auth or {}).get("token", "")
    if not token:
        raise socketio.exceptions.ConnectionRefusedError("Требуется авторизация")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        
        if payload.get("exp") and payload["exp"] < now:
            raise socketio.exceptions.ConnectionRefusedError("Токен истек")
    except JWTError as e:
        logger.warning(f"Invalid token from {client_ip}: {e}")
        raise socketio.exceptions.ConnectionRefusedError("Неверный токен")
    except (ValueError, TypeError, KeyError) as e:
        logger.warning(f"Malformed token from {client_ip}: {e}")
        raise socketio.exceptions.ConnectionRefusedError("Некорректный токен")
    
    # 3. Загрузка пользователя из БД (НЕБЛОКИРУЮЩЕ)
    user_info = None
    db = SessionLocal()
    try:
        # Используем asyncio.to_thread, чтобы не блокировать event loop синхронным SQLAlchemy
        user = await asyncio.to_thread(db.get, User, user_id)
        if not user:
            raise socketio.exceptions.ConnectionRefusedError("Пользователь не найден")
        
        user_info = {
            "id": user.id,
            "username": user.username,
            "avatar": user.avatar or "🦄",
            "ip": client_ip
        }
    except Exception as e:
        logger.error(f"DB error during connect for user {user_id}: {e}")
        raise socketio.exceptions.ConnectionRefusedError("Ошибка сервера")
    finally:
        db.close()
    
    # 4. Успешное подключение
    SID_TO_USER[sid] = user_info
    ONLINE.add(sid)
    
    await sio.emit("online", {"count": len(ONLINE)})
    logger.info(f"✅ Connected: {user_info['username']} (SID: {sid[:8]}...)")

@sio.event
async def disconnect(sid):
    """Обработка отключения клиента."""
    user_info = SID_TO_USER.pop(sid, None)
    
    if user_info:
        ONLINE.discard(sid)
        LAST_CHAT_TIME.pop(sid, None)
        logger.info(f"❌ Disconnected: {user_info['username']} (SID: {sid[:8]}...)")
        
        # Уведомляем всех об изменении онлайна
        await sio.emit("online", {"count": len(ONLINE)})

@sio.on("chat")
async def on_chat(sid, data):
    """Обработка сообщения в чате с защитой от спама и XSS."""
    user_info = SID_TO_USER.get(sid)
    if not user_info:
        return
    
    now = time.time()
    last_time = LAST_CHAT_TIME.get(sid, 0)
    
    if now - last_time < CHAT_RATE_LIMIT_SECONDS:
        return # Тихий дроп спама
    
    LAST_CHAT_TIME[sid] = now
    
    if not isinstance(data, dict):
        return
    
    text = data.get("text", "")
    clean_text = sanitize_message(text)
    
    if not clean_text:
        return
    
    # Рассылаем сообщение всем
    await sio.emit("chat", {
        "username": user_info["username"],
        "avatar": user_info["avatar"],
        "text": clean_text,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

# ==========================================
# УТИЛИТЫ ДЛЯ ВЕЩАНИЯ (BROADCAST)
# ==========================================

async def broadcast_drop(username: str, avatar: str, item_name: str, price: int, color: str, source: str):
    """Рассылает уведомление о редком дропе всем подключенным клиентам."""
    try:
        await sio.emit("drop", {
            "username": username,
            "avatar": avatar or "🦄",
            "pony": item_name,
            "price": price,
            "color": color,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
    except Exception as e:
        logger.error(f"Failed to broadcast drop: {e}")

async def broadcast_to_user(user_id: int, event: str, data: dict):
    """Отправляет событие конкретному пользователю по его ID."""
    target_sids = [sid for sid, info in SID_TO_USER.items() if info.get("id") == user_id]
    
    for sid in target_sids:
        try:
            await sio.emit(event, data, to=sid)
        except Exception as e:
            logger.error(f"Failed to send to user {user_id}: {e}")

def get_online_stats() -> dict:
    """Возвращает статистику подключений для админки."""
    return {
        "total_online": len(ONLINE),
        "unique_users": len(set(info["id"] for info in SID_TO_USER.values())),
        "sessions": len(SID_TO_USER)
    }
