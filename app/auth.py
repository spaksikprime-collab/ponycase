import os
import re
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .db import get_db
from .models import User

SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_pony_key_123")
ALGORITHM = "HS256"
router = APIRouter()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

# Добавил жесткую валидацию данных
class AuthIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, description="Никнейм")
    # Ограничиваем пароль, чтобы bcrypt не падал с ошибкой (лимит 72 байта)
    password: str = Field(..., min_length=4, max_length=72, description="Пароль")

    # Автоматически убираем пробелы по краям у ника
    @field_validator('username')
    def clean_username(cls, v):
        v = v.strip()
        if not re.match("^[a-zA-Z0-9_]+$", v):
            raise ValueError("Никнейм может содержать только буквы, цифры и _")
        return v

def create_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": datetime.utcnow() + timedelta(days=30)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred: 
        raise HTTPException(401, "Нет токена авторизации")
    try:
        user_id = int(jwt.decode(cred.credentials, SECRET_KEY, algorithms=[ALGORITHM])["sub"])
    except JWTError: 
        raise HTTPException(401, "Токен недействителен или истек")
    
    user = db.get(User, user_id)
    if not user: 
        raise HTTPException(401, "Пользователь не найден в базе")
    return user

@router.post("/register")
def register(data: AuthIn, db: Session = Depends(get_db)):
    clean_username = data.username.strip()
    
    # Проверка на существующий ник
    if db.query(User).filter(User.username == clean_username).first():
        raise HTTPException(400, "Этот никнейм уже занят, выбери другой!")
    
    # Генерируем фейковую почту
    fake_email = f"{clean_username.lower()}@ponycase.local"
    
    # Проверка на всякий случай (если вдруг почта совпадет)
    if db.query(User).filter(User.email == fake_email).first():
        raise HTTPException(400, "Ошибка базы данных, попробуй другой ник.")

    try:
        user = User(
            username=clean_username, 
            email=fake_email, 
            password_hash=pwd.hash(data.password)
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        print(f"Ошибка при регистрации: {e}")
        raise HTTPException(500, "Ошибка сервера при создании аккаунта. Попробуйте позже.")

    return {
        "token": create_token(user.id), 
        "user": {
            "id": user.id, 
            "username": user.username, 
            "balance": user.balance, 
            "avatar": user.avatar
        }
    }

@router.post("/login")
def login(data: AuthIn, db: Session = Depends(get_db)):
    clean_username = data.username.strip()
    user = db.query(User).filter(User.username == clean_username).first()
    
    # Проверяем пароль
    try:
        is_valid = user and pwd.verify(data.password, user.password_hash)
    except Exception:
        is_valid = False

    if not is_valid:
        raise HTTPException(401, "Неверный логин или пароль")
        
    return {
        "token": create_token(user.id), 
        "user": {
            "id": user.id, 
            "username": user.username, 
            "balance": user.balance, 
            "avatar": user.avatar
        }
    }
