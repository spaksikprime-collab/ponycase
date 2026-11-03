import os
import re
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .db import get_db
from .models import User

# Секретный ключ для JWT. В продакшене ОБЯЗАТЕЛЬНО установи через переменную окружения!
SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_pony_key_123_CHANGE_ME_IN_PRODUCTION")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30

router = APIRouter()
pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)

class AuthIn(BaseModel):
    username: str = Field(..., min_length=3, max_length=32)
    password: str = Field(..., min_length=4, max_length=72)

def create_token(user_id: int) -> str:
    """Создает JWT токен с современным подходом к времени (timezone-aware)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,  # Issued at
        "exp": now + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS),  # Expiration
        "type": "access"  # Тип токена для дополнительной проверки
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def current_user(
    cred: HTTPAuthorizationCredentials = Depends(bearer), 
    db: Session = Depends(get_db)
) -> User:
    """Зависимость для получения текущего авторизованного пользователя."""
    if not cred:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    
    try:
        # Декодируем токен с проверкой срока действия
        payload = jwt.decode(cred.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        
        # Дополнительная проверка типа токена
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Неверный тип токена")
            
    except JWTError as e:
        # Различаем типы ошибок для более понятных сообщений
        if "expired" in str(e).lower():
            raise HTTPException(status_code=401, detail="Токен истек. Войдите снова.")
        raise HTTPException(status_code=401, detail="Неверный токен")
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Некорректный формат токена")
    
    # Получаем пользователя из БД
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    
    return user

def validate_username(username: str) -> str:
    """Валидирует и очищает username от опасных символов."""
    # Убираем пробелы по краям
    clean_name = username.strip()
    
    # Проверяем длину
    if len(clean_name) < 3:
        raise HTTPException(status_code=400, detail="Никнейм должен быть от 3 символов")
    if len(clean_name) > 32:
        raise HTTPException(status_code=400, detail="Никнейм слишком длинный (макс 32 символа)")
    
    # Разрешаем только буквы, цифры, подчеркивания и дефисы
    # Это защищает от XSS и инъекций в чате/профиле
    if not re.match(r'^[a-zA-Zа-яА-Я0-9_\-]+$', clean_name):
        raise HTTPException(
            status_code=400, 
            detail="Никнейм может содержать только буквы, цифры, _ и -"
        )
    
    return clean_name

@router.post("/register")
def register(data: AuthIn, db: Session = Depends(get_db)):
    """Регистрация нового пользователя."""
    clean_name = validate_username(data.username)
    
    # Проверка длины пароля в байтах (bcrypt лимит 72 байта)
    password_bytes = data.password.encode('utf-8')
    if len(password_bytes) > 72:
        raise HTTPException(status_code=400, detail="Пароль слишком длинный (макс 72 символа)")
    
    # Проверяем уникальность никнейма
    existing_user = db.query(User).filter(User.username == clean_name).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Этот никнейм уже занят")
    
    # Хэшируем пароль с защитой от ошибок bcrypt
    try:
        hashed_pw = pwd.hash(data.password)
    except Exception as e:
        print(f"BCrypt error: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Ошибка шифрования пароля. Попробуйте другой пароль."
        )
    
    # Создаем пользователя
    user = User(username=clean_name, password_hash=hashed_pw)
    db.add(user)
    
    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        print(f"Database error during registration: {e}")
        raise HTTPException(
            status_code=500, 
            detail="Ошибка при создании пользователя. Попробуйте позже."
        )
    
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
    """Вход в систему. Защита от timing attacks через константное время проверки."""
    clean_name = data.username.strip()
    
    # Ищем пользователя
    user = db.query(User).filter(User.username == clean_name).first()
    
    # Константная проверка пароля для защиты от timing attacks
    # Даже если пользователь не найден, мы все равно выполняем verify
    # с фиктивным хэшем, чтобы время ответа было одинаковым
    if not user:
        # Фиктивная проверка для защиты от timing attacks
        pwd.verify(data.password, "$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36Lf.9ddBSOUTjj.sKZ/1VC")
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    # Проверяем пароль
    if not pwd.verify(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    
    return {
        "token": create_token(user.id),
        "user": {
            "id": user.id,
            "username": user.username,
            "balance": user.balance,
            "avatar": user.avatar
        }
    }
