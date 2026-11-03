import socketio
import time
from jose import jwt, JWTError
from .auth import SECRET_KEY, ALGORITHM
from .db import SessionLocal
from .models import User

# Инициализируем сервер Socket.IO
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# Храним ID подключенных клиентов и их данные
ONLINE = set()
SID_TO_USER = {}  # Связка: ID соединения -> данные юзера (id, username, avatar)
LAST_CHAT_TIME = {} # Для анти-спама

@sio.event
async def connect(sid, environ, auth):
    # Получаем токен из данных авторизации
    token = (auth or {}).get("token", "")
    
    try:
        # Проверяем валидность токена
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        # Если токен неверный - отклоняем подключение
        raise socketio.exceptions.ConnectionRefusedError("auth failed")
    
    # Достаем юзера из БД (один раз при подключении, чтобы не грузить базу в чате)
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            raise socketio.exceptions.ConnectionRefusedError("user not found")
            
        SID_TO_USER[sid] = {
            "id": user.id,
            "username": user.username,
            "avatar": user.avatar
        }
    finally:
        db.close()
    
    ONLINE.add(sid)
    
    # Отправляем всем новый счетчик онлайна
    await sio.emit("online", {"count": len(ONLINE)})

@sio.event
async def disconnect(sid):
    ONLINE.discard(sid)
    SID_TO_USER.pop(sid, None)
    LAST_CHAT_TIME.pop(sid, None)
    await sio.emit("online", {"count": len(ONLINE)})

# Обработка сообщений в чате
@sio.on("chat")
async def on_chat(sid, data):
    # 1. Проверяем, авторизован ли вообще этот сокет
    user_info = SID_TO_USER.get(sid)
    if not user_info:
        return
        
    # 2. Анти-спам (не чаще 1 сообщения в 1.5 секунды)
    now = time.time()
    last_time = LAST_CHAT_TIME.get(sid, 0)
    if now - last_time < 1.5:
        return # Игнорируем сообщение, если спамит
    LAST_CHAT_TIME[sid] = now
    
    # 3. Проверяем само сообщение
    if not isinstance(data, dict):
        return
        
    text = str(data.get("text", "")).strip()[:100] # Обрезаем до 100 символов
    
    if not text:
        return
        
    # 4. Отправляем сообщение всем. Берем ник и аву ИЗ БАЗЫ (SID_TO_USER), а не от клиента!
    await sio.emit("chat", {
        "username": user_info["username"], 
        "avatar": user_info["avatar"], 
        "text": text
    })

# Функция для отправки дропов в Live-ленту (вызывается из cases, upgrade, battles, wheel)
async def broadcast_drop(username: str, avatar: str, item_name: str, price: int, color: str, source: str):
    await sio.emit("drop", {
        "username": username, 
        "avatar": avatar, 
        "pony": item_name, 
        "price": price, 
        "color": color, 
        "source": source
    })
