import os
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .db import get_db
from .models import User

SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
ALGORITHM = "HS256"

router = APIRouter()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

class RegisterIn(BaseModel):
    username: str
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

def create_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    if not cred:
        raise HTTPException(401, "Токен не передан")
    try:
        user_id = int(jwt.decode(cred.credentials, SECRET_KEY, algorithms=[ALGORITHM])["sub"])
    except JWTError:
        raise HTTPException(401, "Неверный токен")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, "Пользователь не найден")
    return user

@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if len(data.username) < 3 or len(data.username) > 32:
        raise HTTPException(400, "Ник от 3 до 32 символов")
    exists = db.query(User).filter(
        (User.username == data.username) | (User.email == data.email)
    ).first()
    if exists:
        raise HTTPException(400, "Ник или email заняты")
    user = User(username=data.username, email=data.email,
                password_hash=pwd.hash(data.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"token": create_token(user.id),
            "user": {"id": user.id, "username": user.username, "balance": user.balance}}

@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not pwd.verify(data.password, user.password_hash):
        raise HTTPException(401, "Неверные данные")
    return {"token": create_token(user.id),
            "user": {"id": user.id, "username": user.username, "balance": user.balance}}
