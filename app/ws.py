import time
import html
import logging
from datetime import datetime, timezone
from jose import jwt, JWTError
import socketio
from .auth import SECRET_KEY, ALGORITHM
from .db import SessionLocal
from .models import User

logger = logging.getLogger(__name__)

# ==========================================
# ИНИЦИАЛИЗАЦИЯ SOCKET.IO СЕРВЕРА
# ==========================================
# cors_allowed_origins="*" — разрешаем подключения с любых доменов
# В продакшене лучше указать конкретные домены: ["https://твой-домен.zevcloud.ru"]
sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
    logger=False,
    engineio_logger=False
)

# ==========================================
# ГЛОБАЛЬНЫЕ СТРУКТУРЫ ДАННЫХ
# ==========================================
# Множество подключенных сессий (для подсчета онлайна)
ONLINE = set()

# Маппинг SID -> информация о пользователе (кэш, чтобы не ходить в БД на каждое сообщение)
SID_TO_USER = {}

# Rate limiter для чата: SID -> timestamp последнего сообщения
LAST_CHAT_TIME = {}

# Rate limiter для подключений: IP -> count (защита от флуда подключениями)
LAST_CONNECT_TIME = {}

# ==========================================
# КОНФИГУРАЦИЯ RATE LIMITING
# ==========================================
# Минимальный интервал между сообщениями в чате (секунды)
CHAT_RATE_LIMIT_SECONDS = 1.5
# Максимальная длина сообщения
CHAT_MAX_LENGTH = 100
# Максимальное количество подключений с одного IP в минуту
MAX_CONNECTS_PER_MINUTE = 10

def sanitize_message(text: str) -> str:
    """
    Очищает сообщение от опасных символов для предотвращения XSS.
    - Экранирует HTML-теги
    - Убирает лишние пробелы
    - Ограничивает длину
    """
    if not text:
        return ""
    
    # Экранируем HTML-теги (<script> -> &lt;script&gt;)
    clean = html.escape(text)
    
    # Убираем control-символы (кроме переносов строк)
    clean = "".join(c for c in clean if c == '\n' or (ord(c) >= 32))
    
    # Заменяем множественные пробелы на один
    clean = " ".join(clean.split())
    
    # Ограничиваем длину
    return clean[:CHAT_MAX_LENGTH]

def get_client_ip(environ: dict) -> str:
    """Извлекает IP-адрес клиента из environ (с учетом прокси)."""
    # Поддержка X-Forwarded-For для работы за прокси/Cloudflare
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
    
    # Защита от флуда подключениями с одного IP
    now = time.time()
    recent_connects = LAST_CONNECT_TIME.get(client_ip, [])
    recent_connects = [t for t in recent_connects if now - t < 60]
    
    if len(recent_connects) >= MAX_CONNECTS_PER_MINUTE:
        logger.warning(f"Rate limit exceeded for IP {client_ip}")
        raise socketio.exceptions.ConnectionRefusedError("Слишком много подключений. Подождите.")
    
    recent_connects.append(now)
    LAST_CONNECT_TIME[client_ip] = recent_connects
    
    # Проверяем JWT токен из auth
    token = (auth or {}).get("token", "")
    if not token:
        logger.warning(f"Connection attempt without token from {client_ip}")
        raise socketio.exceptions.ConnectionRefusedError("Требуется авторизация")
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        
        # Проверяем срок действия токена
        if payload.get("exp") and payload["exp"] < time.time():
            raise socketio.exceptions.ConnectionRefusedError("Токен истек")
            
    except JWTError as e:
        logger.warning(f"Invalid token from {client_ip}: {e}")
        raise socketio.exceptions.ConnectionRefusedError("Неверный токен")
    except (ValueError, TypeError, KeyError) as e:
        logger.warning(f"Malformed token from {client_ip}: {e}")
        raise socketio.exceptions.ConnectionRefusedError("Некорректный токен")
    
    # Загружаем пользователя из БД
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            logger.warning(f"User {user_id} not found in DB")
            raise socketio.exceptions.ConnectionRefusedError("Пользователь не найден")
        
        # Кэшируем информацию о пользователе
        SID_TO_USER[sid] = {
            "id": user.id,
            "username": user.username,
            "avatar": user.avatar,
            "ip": client_ip
        }
    finally:
        db.close()
    
    # Добавляем в онлайн
    ONLINE.add(sid)
    
    # Уведомляем всех о новом онлайне
    await sio.emit("online", {"count": len(ONLINE)})
    
    logger.info(f"✅ Connected: {SID_TO_USER[sid]['username']} (SID: {sid[:8]}...)")

@sio.event
async def disconnect(sid):
    """Обработка отключения клиента."""
    user_info = SID_TO_USER.get(sid)
    
    if user_info:
        logger.info(f"❌ Disconnected: {user_info['username']} (SID: {sid[:8]}...)")
    
    # Удаляем из всех структур
    ONLINE.discard(sid)
    SID_TO_USER.pop(sid, None)
    LAST_CHAT_TIME.pop(sid, None)
    
    # Уведомляем всех об изменении онлайна
    await sio.emit("online", {"count": len(ONLINE)})

@sio.on("chat")
async def on_chat(sid, data):
    """
    Обработка сообщения в чате.
    Защита от спама, XSS и флуда.
    """
    user_info = SID_TO_USER.get(sid)
    if not user_info:
        return
    
    # Rate limiting: не чаще 1 сообщения в CHAT_RATE_LIMIT_SECONDS
    now = time.time()
    last_time = LAST_CHAT_TIME.get(sid, 0)
    
    if now - last_time < CHAT_RATE_LIMIT_SECONDS:
        # Тихо игнорируем спам (не отправляем ошибку, чтобы не флудить клиента)
        return
    
    LAST_CHAT_TIME[sid] = now
    
    # Валидация данных
    if not isinstance(data, dict):
        return
    
    text = data.get("text", "")
    if not isinstance(text, str):
        return
    
    # Очищаем сообщение от XSS и ограничиваем длину
    clean_text = sanitize_message(text)
    if not clean_text:
        return
    
    # Логируем сообщение
    logger.debug(f"💬 Chat: {user_info['username']}: {clean_text[:50]}...")
    
    # Рассылаем сообщение всем подключенным клиентам
    await sio.emit("chat", {
        "username": user_info["username"],
        "avatar": user_info["avatar"],
        "text": clean_text,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

# ==========================================
# УТИЛИТЫ ДЛЯ ВЕЩАНИЯ (BROADCAST)
# ==========================================

async def broadcast_drop(
    username: str, 
    avatar: str, 
    item_name: str, 
    price: int, 
    color: str, 
    source: str
):
    """
    Рассылает уведомление о редком дропе всем подключенным клиентам.
    Используется в кейсах, апгрейдах, джекпоте и батлах.
    """
    try:
        await sio.emit("drop", {
            "username": username,
            "avatar": avatar,
            "pony": item_name,
            "price": price,
            "color": color,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        logger.info(f"🎁 Drop broadcast: {username} won {item_name} ({price}🪙) from {source}")
    except Exception as e:
        logger.error(f"Failed to broadcast drop: {e}")

async def broadcast_online_count():
    """Рассылает текущее количество онлайн-пользователей."""
    await sio.emit("online", {"count": len(ONLINE)})

async def broadcast_to_user(user_id: int, event: str, data: dict):
    """
    Отправляет событие конкретному пользователю по его ID.
    Полезно для уведомлений о выплатах, достижениях и т.д.
    """
    # Находим все сессии этого пользователя
    target_sids = [
        sid for sid, info in SID_TO_USER.items()
        if info.get("id") == user_id
    ]
    
    for sid in target_sids:
        try:
            await sio.emit(event, data, to=sid)
        except Exception as e:
            logger.error(f"Failed to send to user {user_id}: {e}")

# ==========================================
# СТАТИСТИКА И МОНИТОРИНГ
# ==========================================

def get_online_stats() -> dict:
    """Возвращает статистику подключений для админки."""
    return {
        "total_online": len(ONLINE),
        "unique_users": len(set(info["id"] for info in SID_TO_USER.values())),
        "sessions": len(SID_TO_USER)
    }
