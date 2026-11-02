import socketio
from jose import jwt, JWTError
from .auth import SECRET_KEY, ALGORITHM

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
ONLINE = set()

@sio.event
async def connect(sid, environ, auth):
    token = (auth or {}).get("token", "")
    try: jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError: raise socketio.exceptions.ConnectionRefusedError("auth failed")
    ONLINE.add(sid)
    await sio.emit("online", {"count": len(ONLINE)})

@sio.event
async def disconnect(sid):
    ONLINE.discard(sid)
    await sio.emit("online", {"count": len(ONLINE)})

@sio.on("chat")
async def on_chat(sid, data):
    await sio.emit("chat", {"username": data.get("username", "Anon"), "text": data.get("text", "")[:100]})

async def broadcast_drop(username: str, avatar: str, pony_id: str, price: int, color: str, source: str):
    await sio.emit("drop", {"username": username, "avatar": avatar, "pony": pony_id, "price": price, "color": color, "source": source})
