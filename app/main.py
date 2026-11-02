import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio

from .db import engine, Base
from . import models  # noqa
from .auth import router as auth_router
from .clicker import router as clicker_router
from .cases import router as cases_router
from .ws import sio

Base.metadata.create_all(bind=engine)

api = FastAPI(title="PonyCase")

origins = os.getenv("CORS_ORIGINS", "").split(",")
api.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api.include_router(auth_router,    prefix="/api/auth",    tags=["auth"])
api.include_router(clicker_router, prefix="/api/clicker", tags=["clicker"])
api.include_router(cases_router,   prefix="/api/cases",   tags=["cases"])

@api.get("/api/health")
def health():
    return {"ok": True}

app = socketio.ASGIApp(sio, other_asgi_app=api)
