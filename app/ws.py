import socketio
import time
from jose import jwt, JWTError
from .auth import SECRET_KEY, ALGORITHM
from .db import SessionLocal
from .models import User

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

ONLINE = set()
SID_TO_USER = {}
LAST_CHAT_TIME = {}

@sio.event
async def connect(sid, environ, auth):
    token = (auth or {}).get("token", "")
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise socketio.exceptions.ConnectionRefusedError("auth failed")
    
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
    await sio.emit("online", {"count": len(ONLINE)})

@sio.event
async def disconnect(sid):
    ONLINE.discard(sid)
    SID_TO_USER.pop(sid, None)
    LAST_CHAT_TIME.pop(sid, None)
    await sio.emit("online", {"count": len(ONLINE)})

@sio.on("chat")
async def on_chat(sid, data):
    user_info = SID_TO_USER.get(sid)
    if not user_info: return
        
    # Анти-спам (1 сообщение в 1.5 сек)
    now = time.time()
    if now - LAST_CHAT_TIME.get(sid, 0) < 1.5: return
    LAST_CHAT_TIME[sid] = now
    
    if not isinstance(data, dict): return
    text = str(data.get("text", "")).strip()[:100]
    if not text: return
        
    await sio.emit("chat", {
        "username": user_info["username"], 
        "avatar": user_info["avatar"], 
        "text": text
    })

async def broadcast_drop(username: str, avatar: str, item_name: str, price: int, color: str, source: str):
    await sio.emit("drop", {
        "username": username, 
        "avatar": avatar, 
        "pony": item_name, 
        "price": price, 
        "color": color, 
        "source": source
    })
