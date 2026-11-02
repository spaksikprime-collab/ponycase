import socketio
from jose import jwt, JWTError
from .auth import SECRET_KEY, ALGORITHM

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

ONLINE: set[str] = set()
CHAT_HISTORY: list[dict] = []

@sio.event
async def connect(sid, environ, auth):
    token = (auth or {}).get("token", "")
    try:
        jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise socketio.exceptions.ConnectionRefusedError("auth failed")
    ONLINE.add(sid)
    await sio.emit("online", {"count": len(ONLINE)})
    await sio.emit("chat_history", CHAT_HISTORY[-50:], to=sid)

@sio.event
async def disconnect(sid):
    ONLINE.discard(sid)
    await sio.emit("online", {"count": len(ONLINE)})

@sio.on("chat")
async def on_chat(sid, data):
    username = str(data.get("username", "anon"))[:32]
    text = str(data.get("text", ""))[:200].strip()
    if not text:
        return
    msg = {"username": username, "text": text}
    CHAT_HISTORY.append(msg)
    if len(CHAT_HISTORY) > 200:
        CHAT_HISTORY.pop(0)
    await sio.emit("chat", msg)

async def broadcast_drop(username: str, pony_id: str, rarity: str, price: int):
    await sio.emit("drop", {"username": username, "pony": pony_id,
                            "rarity": rarity, "price": price})
