import os, random, smtplib
from email.mime.text import MIMEText
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

class VerifyIn(BaseModel):
    email: EmailStr
    code: str

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

# Имитация отправки письма (код виден в логах ZevCloud)
def send_email(to_email, code):
    print(f"=== EMAIL SENT to {to_email}: Code = {code} ===")
    # Если хочешь реальную почту, раскомментируй и вставь свои данные:
    # msg = MIMEText(f"Ваш код для PonyCase: {code}")
    # msg['Subject'] = "Код подтверждения PonyCase"
    # msg['From'] = "your_email@gmail.com"
    # msg['To'] = to_email
    # with smtplib.SMTP('smtp.gmail.com', 587) as server:
    #     server.starttls()
    #     server.login("your_email@gmail.com", "your_app_password")
    #     server.send_message(msg)

@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter((User.username == data.username) | (User.email == data.email)).first():
        raise HTTPException(400, "Ник или Email заняты")
    
    code = str(random.randint(100000, 999999))
    user = User(username=data.username, email=data.email, password_hash=pwd.hash(data.password), verification_code=code)
    db.add(user); db.commit()
    send_email(data.email, code)
    return {"status": "verify_needed", "message": "Код отправлен на почту"}

@router.post("/verify")
def verify_email(data: VerifyIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or user.verification_code != data.code:
        raise HTTPException(400, "Неверный код")
    
    user.is_verified = True
    user.verification_code = None
    db.commit()
    return {"token": create_token(user.id), "user": {"id": user.id, "username": user.username, "balance": user.balance, "avatar": user.avatar}}

@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not user.password_hash or not pwd.verify(data.password, user.password_hash):
        raise HTTPException(401, "Неверные данные")
    if not user.is_verified:
        raise HTTPException(403, "Подтвердите почту")
    return {"token": create_token(user.id), "user": {"id": user.id, "username": user.username, "balance": user.balance, "avatar": user.avatar}}

# --- GOOGLE OAUTH (Заглушка для демонстрации логики) ---
@router.get("/google")
def auth_google():
    # В реальности тут redirect на Google. Мы сделаем имитацию для теста.
    return {"url": "https://accounts.google.com/o/oauth2/v2/auth?client_id=YOUR_CLIENT_ID&redirect_uri=YOUR_REDIRECT_URI&response_type=code&scope=email profile"}
