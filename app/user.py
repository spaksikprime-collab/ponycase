from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
import base64
from datetime import datetime
from .db import get_db
from .models import User, InventoryItem, CaseOpen
from .auth import current_user
from .clicker import apply_passive, public_user
from .games import RARITY_BY_ID, CASES

router = APIRouter()

def get_fav_case(user_id: int, db: Session):
    fav = db.query(CaseOpen.case_id, func.count(CaseOpen.case_id)).filter(CaseOpen.user_id == user_id).group_by(CaseOpen.case_id).order_by(func.count(CaseOpen.case_id).desc()).first()
    if fav and fav[0] in CASES: return CASES[fav[0]]["name"]
    return "Нет"

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
        "fav_case": get_fav_case(user.id, db),
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": i.color} for i in inventory]
    }

@router.get("/public/by_name/{username}")
def get_public_by_name(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user: raise HTTPException(404, "Игрок не найден")
    
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    best_drop = {"name": user.best_drop_name, "price": user.best_drop_price} if user.best_drop_price > 0 else None
    
    return {
        "username": user.username,
        "avatar": user.avatar,
        "total_clicks": user.total_clicks,
        "cases_opened": opened_cases,
        "best_drop": best_drop,
        "fav_case": get_fav_case(user.id, db)
    }

@router.post("/bonus")
def claim_bonus(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.last_bonus and (datetime.utcnow() - user.last_bonus).total_seconds() < 3600:
        raise HTTPException(400, "Бонус будет доступен позже!")
    user.balance += 500
    user.last_bonus = datetime.utcnow()
    db.commit()
    return {"success": True, "balance": user.balance}

@router.post("/inventory/sell/{item_id}")
def sell_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item or item.user_id != user.id: raise HTTPException(404, "Не найден")
    apply_passive(user, db)
    user.balance += item.price
    db.delete(item); db.commit()
    return {"success": True, "balance": user.balance}

@router.post("/inventory/sell_all")
def sell_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user, db)
    items = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    total_gained = sum(item.price for item in items)
    user.balance += total_gained
    for item in items: db.delete(item)
    db.commit()
    return {"success": True, "balance": user.balance, "gained": total_gained}

@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024: raise HTTPException(400, "Макс 5МБ")
    b64_str = base64.b64encode(contents).decode('utf-8')
    user.avatar = f"data:{file.content_type};base64,{b64_str}"
    db.commit()
    return {"success": True, "avatar": user.avatar}
