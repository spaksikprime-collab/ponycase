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

@router.get("/profile")
def get_my_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user, db)
    inventory = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    
    return {
        "user": public_user(user),
        "stats": {"total_clicks": user.total_clicks, "cases_opened": opened_cases},
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": i.color} for i in inventory]
    }

@router.get("/public/{user_id}")
def get_public_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "Юзер не найден")
    
    # Статистика
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    
    # Лучший дроп (самый дорогой предмет в инвентаре)
    best_drop = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).order_by(InventoryItem.price.desc()).first()
    
    # Любимый кейс (самый частый)
    fav_case_query = db.query(CaseOpen.case_id, func.count(CaseOpen.case_id)).filter(CaseOpen.user_id == user.id).group_by(CaseOpen.case_id).order_by(func.count(CaseOpen.case_id).desc()).first()
    fav_case_name = "Нет"
    if fav_case_query and fav_case_query[0] in CASES:
        fav_case_name = CASES[fav_case_query[0]]["name"]
    
    return {
        "username": user.username,
        "avatar": user.avatar,
        "total_clicks": user.total_clicks,
        "cases_opened": opened_cases,
        "best_drop": {"name": best_drop.pony_id, "price": best_drop.price} if best_drop else None,
        "fav_case": fav_case_name
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
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Предмет не найден")
    apply_passive(user, db)
    user.balance += item.price
    db.delete(item)
    db.commit()
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
