import os
import re
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .db import get_db
from .models import User

# ==========================================
# НАСТРОЙКИ БЕЗОПАСНОСТИ
# ==========================================
# В продакшене ОБЯЗАТЕЛЬНО установи SECRET_KEY через переменную окружения!
# Например: openssl rand -hex 32
SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_pony_key_123_CHANGE_ME_IN_PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

router = APIRouter()
logger = logging.getLogger(__name__)

# Настройка хеширования паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

# Фиктивный хеш для защиты от Timing Attacks (стандартный bcrypt хеш)
DUMMY_HASH = "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36Lf.9ddBSOUTjj.sKZ/1VC"

# ==========================================
# МОДЕЛИ ДАННЫХ
# ==========================================
class AuthIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, description="Никнейм пользователя")
    password: str = Field(..., min_length=4, max_length=72, description="Пароль пользователя")

# ==========================================
# УТИЛИТЫ JWT И АВТОРИЗАЦИИ
# ==========================================
def create_token(user_id: int) -> str:
    """Создает JWT токен с современным подходом к времени (timezone-aware)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),
        "type": "access"
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer), 
    db: Session = Depends(get_db)
) -> User:
    """Зависимость FastAPI для получения текущего авторизованного пользователя."""
    if not cred:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    try:
        payload = jwt.decode(cred.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Неверный тип токена")
            
    except JWTError as e:
        error_msg = str(e).lower()
        if "expired" in error_msg:
            raise HTTPException(status_code=401, detail="Токен истек. Войдите снова.")
        logger.warning(f"JWT Decode Error: {e}")
        raise HTTPException(status_code=401, detail="Неверный токен")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Некорректный формат токена")
    
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    
    return user

def validate_username(username: str) -> str:
    """Валидирует и очищает username от опасных символов и пробелов."""
    clean_name = username.strip().lower() # Приводим к нижнему регистру для защиты от спуфинга
    
    if len(clean_name) < 3:
        raise HTTPException(status_code=400, detail="Никнейм должен быть от 3 символов")
    if len(clean_name) > 32:
        raise HTTPException(status_code=400, detail="Никнейм слишком длинный (макс 32 символа)")
    
    # Разрешаем только буквы (латиница/кириллица), цифры, подчеркивания и дефисы
    # Если хочешь запретить кириллицу полностью (максимальная защита от гомоглифов), 
    # замени regex на: r'^[a-zA-Z0-9_\-]+$'
    if not re.match(r'^[a-zA-Zа-яё0-9_\-]+$', clean_name):
        raise HTTPException(
            status_code=400, 
            detail="Никнейм может содержать только буквы, цифры, _ и -"
        )
    
    return clean_name

# ==========================================
# ЭНДПОИНТЫ АВТОРИЗАЦИИ
# ==========================================
@router.post("/register")
def register(data: AuthIn, db: Session = Depends(get_db)):
    """Регистрация нового пользователя."""
    clean_name = validate_username(data.username)
    
    # Проверка длины пароля в байтах (bcrypt лимит 72 байта)
    if len(data.password.encode('utf-8')) > 72:
        raise HTTPException(status_code=400, detail="Пароль слишком длинный (макс 72 символа)")
    
    existing_user = db.query(User).filter(User.username == clean_name).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Этот никнейм уже занят")
    
    try:
        hashed_pw = pwd_context.hash(data.password)
    except Exception as e:
        logger.error(f"BCrypt hashing error during registration: {e}")
        raise HTTPException(status_code=500, detail="Ошибка шифрования пароля")
    
    user = User(username=clean_name, password_hash=hashed_pw)
    db.add(user)
    
    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        logger.error(f"Database error during registration: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при создании пользователя")
    
    logger.info(f"✅ New user registered: {clean_name} (ID: {user.id})")
    
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
    """Вход в систему. Полная защита от Timing Attacks."""
    clean_name = data.username.strip().lower()
    
    user = db.query(User).filter(User.username == clean_name).first()
    
    # Константная проверка пароля для защиты от атак по времени (Timing Attacks)
    # Если пользователь не найден, мы все равно выполняем verify с фиктивным хэшем
    if not user:
        pwd_context.verify(data.password, DUMMY_HASH)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    if not pwd_context.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    logger.info(f"🔑 User logged in: {clean_name} (ID: {user.id})")
    
    return {
        "token": create_token(user.id),
        "user": {
            "id": user.id,
            "username": user.username,
            "balance": user.balance,
            "avatar": user.avatar
        }
    }
