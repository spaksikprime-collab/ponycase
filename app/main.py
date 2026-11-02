import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import socketio

from .db import engine, Base
from . import models
from .auth import router as auth_router
from .clicker import router as clicker_router
from .cases import router as cases_router
from .user import router as user_router
from .upgrade import router as upgrade_router
from .ws import sio

Base.metadata.create_all(bind=engine)

api = FastAPI(title="PonyCase API")

@api.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": str(exc)})

cors_origins = os.getenv("CORS_ORIGINS", "*")
origins_list = ["*"] if cors_origins == "*" else [o.strip() for o in cors_origins.split(",")]

api.add_middleware(
    CORSMiddleware,
    allow_origins=origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api.include_router(auth_router,    prefix="/api/auth",    tags=["auth"])
api.include_router(clicker_router, prefix="/api/clicker", tags=["clicker"])
api.include_router(cases_router,   prefix="/api/cases",   tags=["cases"])
api.include_router(user_router,    prefix="/api/user",    tags=["user"])
api.include_router(upgrade_router, prefix="/api/upgrade", tags=["upgrade"])

@api.get("/api/health", tags=["system"])
def health():
    return {"ok": True}

@api.get("/", include_in_schema=False)
def serve_frontend():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"error": "index.html missing"}

app = socketio.ASGIApp(sio, other_asgi_app=api)
