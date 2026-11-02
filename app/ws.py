import socketio
from jose import jwt, JWTError
from .auth import SECRET_KEY, ALGORITHM

# Инициализируем сервер Socket.IO
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# Храним ID подключенных клиентов
ONLINE = set()

@sio.event
async def connect(sid, environ, auth):
    # Получаем токен из данных авторизации
    token = (auth or {}).get("token", "")
    
    try:
        # Проверяем валидность токена
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        # Если токен неверный - отклоняем подключение
        raise socketio.exceptions.ConnectionRefusedError("auth failed")
    
    ONLINE.add(sid)
    
    # Отправляем всем новый счетчик онлайна
    await sio.emit("online", {"count": len(ONLINE)})

@sio.event
async def disconnect(sid):
    ONLINE.discard(sid)
    await sio.emit("online", {"count": len(ONLINE)})

# Обработка сообщений в чате
@sio.on("chat")
async def on_chat(sid, data):
    username = data.get("username", "Anon")
    avatar = data.get("avatar", "🦄")
    text = data.get("text", "")[:100].strip()
    
    if not text:
        return
        
    # Отправляем сообщение всем подключенным клиентам
    await sio.emit("chat", {
        "username": username, 
        "avatar": avatar, 
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
