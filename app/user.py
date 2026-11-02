from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
import base64
from datetime import datetime
from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .clicker import apply_passive, public_user
from .games import RARITY_BY_ID, CASES

router = APIRouter()

@router.get("/profile")
def get_my_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user, db)
    inventory = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    
    best_drop = {"name": user.best_drop_name, "price": user.best_drop_price} if user.best_drop_price > 0 else None

    return {
        "user": public_user(user),
        "stats": {"total_clicks": user.total_clicks, "cases_opened": opened_cases},
        "best_drop": best_drop,
        "fav_case": "Нет",
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": i.color} for i in inventory]
    }

@router.get("/history")
def get_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    hist = db.query(GameHistory).filter(GameHistory.user_id == user.id).order_by(GameHistory.created_at.desc()).limit(50).all()
    return [{"game": h.game_type, "item": h.item_name, "price": h.price, "result": h.result_text, "date": h.created_at.strftime("%d.%m %H:%M")} for h in hist]

@router.get("/public/by_name/{username}")
def get_public_by_name(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user: raise HTTPException(404, "Игрок не найден")
    
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    best_drop = {"name": user.best_drop_name, "price": user.best_drop_price} if user.best_drop_price > 0 else None
    
    return {
        "username": user.username, "avatar": user.avatar, "total_clicks": user.total_clicks,
        "cases_opened": opened_cases, "best_drop": best_drop, "fav_case": "Нет"
    }

# ... (остальные функции bonus, sell, avatar без изменений) ...
