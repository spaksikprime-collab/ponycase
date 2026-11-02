import os
import re
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .db import get_db
from .models import User

# Конфигурация безопасности
SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_pony_key_123")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30 # Токен живет 30 дней

router = APIRouter()

# Контекст для хеширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Схема авторизации
bearer_scheme = HTTPBearer(auto_error=False)


# ==========================================
# PYDANTIC МОДЕЛИ (Валидация входящих данных)
# ==========================================
class AuthIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=4, max_length=72) # 72 байта - лимит bcrypt

    @field_validator('username')
    def validate_username(cls, value):
        # Разрешаем только буквы, цифры и нижнее подчеркивание
        if not re.match(r"^[a-zA-Z0-9_]+$", value):
            raise ValueError("Никнейм может содержать только латинские буквы, цифры и _")
        return value.strip()


# ==========================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================
def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode = {"sub": str(user_id), "exp": expire}
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme), 
    db: Session = Depends(get_db)
) -> User:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация"
        )
    
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный токен"
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден"
        )
    return user


# ==========================================
# ЭНДПОИНТЫ АВТОРИЗАЦИИ
# ==========================================
@router.post("/register", summary="Регистрация нового пользователя")
def register(data: AuthIn, db: Session = Depends(get_db)):
    # 1. Проверяем, не занят ли ник
    existing_user = db.query(User).filter(User.username == data.username).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Этот никнейм уже занят!"
        )
    
    # 2. Хешируем пароль
    hashed_password = pwd_context.hash(data.password)
    
    # 3. Создаем пользователя (почту не передаем, так как мы ее убрали из БД)
    new_user = User(
        username=data.username,
        password_hash=hashed_password
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
    except Exception as e:
        db.rollback()
        print(f"DB Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ошибка базы данных при создании профиля"
        )
    
    # 4. Генерируем токен и отдаем данные
    token = create_access_token(new_user.id)
    return {
        "token": token,
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "balance": new_user.balance,
            "avatar": new_user.avatar
        }
    }


@router.post("/login", summary="Вход в аккаунт")
def login(data: AuthIn, db: Session = Depends(get_db)):
    # 1. Ищем пользователя
    user = db.query(User).filter(User.username == data.username).first()
    
    # 2. Проверяем пароль
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль"
        )
        
    try:
        is_password_valid = pwd_context.verify(data.password, user.password_hash)
    except Exception:
        is_password_valid = False
        
    if not is_password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль"
        )
        
    # 3. Генерируем токен и отдаем данные
    token = create_access_token(user.id)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "balance": user.balance,
            "avatar": user.avatar
        }
    }
