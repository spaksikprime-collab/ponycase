import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import socketio
from sqlalchemy import text

from .db import engine, Base
from . import models
from .auth import router as auth_router
from .clicker import router as clicker_router
from .cases import router as cases_router
from .user import router as user_router
from .upgrade import router as upgrade_router
from .battles import router as battles_router
from .mines import router as mines_router
from .ws import sio

Base.metadata.create_all(bind=engine)

def run_migrations():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar VARCHAR DEFAULT '🦄';"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR(10);"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus TIMESTAMP;"))
            conn.commit()
        except Exception as e:
            print(f"Ошибка миграции: {e}")

run_migrations()

api = FastAPI(title="PonyCase API")

@api.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": str(exc)})

api.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

api.include_router(auth_router,    prefix="/api/auth")
api.include_router(clicker_router, prefix="/api/clicker")
api.include_router(cases_router,   prefix="/api/cases")
api.include_router(user_router,    prefix="/api/user")
api.include_router(upgrade_router, prefix="/api/upgrade")
api.include_router(battles_router, prefix="/api/battles")
api.include_router(mines_router,   prefix="/api/mines")

@api.get("/api/health")
def health(): return {"ok": True}

@api.get("/")
def serve_frontend():
    if os.path.exists("index.html"): return FileResponse("index.html")
    return {"error": "no index"}

app = socketio.ASGIApp(sio, other_asgi_app=api)
