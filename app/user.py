from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
import base64
from datetime import datetime
from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .clicker import apply_passive, public_user
from .games import CASES

router = APIRouter()

@router.get("/profile")
def get_my_profile(page: int = 1, limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user, db)
    
    skip = (page - 1) * limit
    inv_query = db.query(InventoryItem).filter(InventoryItem.user_id == user.id)
    total_items = inv_query.count()
    inventory = inv_query.order_by(InventoryItem.price.desc()).offset(skip).limit(limit).all()
    
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    best_drop = {"name": user.best_drop_name, "price": user.best_drop_price} if user.best_drop_price > 0 else None

    return {
        "user": public_user(user),
        "stats": {"total_clicks": user.total_clicks, "cases_opened": opened_cases},
        "best_drop": best_drop,
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": i.color} for i in inventory],
        "pagination": {"total": total_items, "page": page, "limit": limit, "pages": (total_items + limit - 1) // limit}
    }

@router.get("/history")
def get_history(page: int = 1, limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    skip = (page - 1) * limit
    hist_query = db.query(GameHistory).filter(GameHistory.user_id == user.id)
    total = hist_query.count()
    
    history = hist_query.order_by(GameHistory.created_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "history": [{"game": h.game_type, "item": h.item_name, "price": h.price, "result": h.result_text, "date": h.created_at.strftime("%d.%m %H:%M")} for h in history],
        "pagination": {"total": total, "page": page, "limit": limit, "pages": (total + limit - 1) // limit}
    }

@router.get("/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    top_users = db.query(User).order_by(User.balance.desc()).limit(10).all()
    return [{"rank": i+1, "username": u.username, "avatar": u.avatar, "balance": u.balance} for i, u in enumerate(top_users)]

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
    for item in items:
        db.delete(item)
    db.commit()
    return {"success": True, "balance": user.balance, "gained": total_gained}

@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(400, "Макс 5МБ")
    b64_str = base64.b64encode(contents).decode('utf-8')
    user.avatar = f"data:{file.content_type};base64,{b64_str}"
    db.commit()
    return {"success": True, "avatar": user.avatar}
