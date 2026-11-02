import os, random
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
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

def current_user(cred: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if not cred: raise HTTPException(401, "Нет токена")
    try:
        user_id = int(jwt.decode(cred.credentials, SECRET_KEY, algorithms=[ALGORITHM])["sub"])
    except JWTError: raise HTTPException(401, "Неверный токен")
    user = db.get(User, user_id)
    if not user: raise HTTPException(401, "Юзер не найден")
    return user

@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(400, "Эта почта уже зарегистрирована!")
    if db.query(User).filter(User.username == data.username).first():
        raise HTTPException(400, "Этот никнейм уже занят!")
    
    # Создаем пользователя и сразу ставим галочку "подтвержден"
    user = User(
        username=data.username, 
        email=data.email, 
        password_hash=pwd.hash(data.password), 
        is_verified=True, 
        verification_code=None
    )
    db.add(user); db.commit(); db.refresh(user)
    
    return {
        "token": create_token(user.id), 
        "user": {"id": user.id, "username": user.username, "balance": user.balance, "avatar": user.avatar}
    }

@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash or not pwd.verify(data.password, user.password_hash):
        raise HTTPException(401, "Неверная почта или пароль")
        
    return {
        "token": create_token(user.id), 
        "user": {"id": user.id, "username": user.username, "balance": user.balance, "avatar": user.avatar}
    }
