from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import base64
from datetime import datetime
from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .clicker import apply_passive

router = APIRouter()

@router.get("/profile")
def get_my_profile(page: int = 1, limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Блокируем на время чтения, чтобы пассивный доход корректно начислился
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    skip = (page - 1) * limit
    inv_query = db.query(InventoryItem).filter(InventoryItem.user_id == user_db.id)
    total_items = inv_query.count()
    inventory = inv_query.order_by(InventoryItem.price.desc()).offset(skip).limit(limit).all()
    
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user_db.id).count()
    best_drop = {"name": user_db.best_drop_name, "price": user_db.best_drop_price} if user_db.best_drop_price > 0 else None

    return {
        "user": {
            "id": user_db.id,
            "username": user_db.username,
            "balance": user_db.balance,
            "avatar": user_db.avatar,
            "created_at": user_db.created_at.strftime("%d.%m.%Y") if user_db.created_at else "Неизвестно"
        },
        "stats": {"total_clicks": user_db.total_clicks, "cases_opened": opened_cases},
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
    # Блокировка от спама (защита от двойного клика)
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    if user_db.last_bonus and (datetime.utcnow() - user_db.last_bonus).total_seconds() < 3600:
        raise HTTPException(400, "Бонус будет доступен позже!")
        
    user_db.balance += 500
    user_db.last_bonus = datetime.utcnow()
    db.commit()
    return {"success": True, "balance": user_db.balance}

@router.post("/inventory/sell/{item_id}")
def sell_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Предмет не найден")
        
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    user_db.balance += item.price
    db.delete(item)
    db.commit()
    return {"success": True, "balance": user_db.balance}

@router.post("/inventory/sell_all")
def sell_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    items = db.query(InventoryItem).filter(InventoryItem.user_id == user_db.id).all()
    total_gained = sum(item.price for item in items)
    
    user_db.balance += total_gained
    for item in items:
        db.delete(item)
    db.commit()
    return {"success": True, "balance": user_db.balance, "gained": total_gained}

@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    contents = await file.read()
    
    # СНИЖЕН ЛИМИТ ДО 200 КБ (иначе база данных будет тормозить из-за base64 строк)
    if len(contents) > 200 * 1024:
        raise HTTPException(400, "Максимальный размер фото - 200КБ")
        
    b64_str = base64.b64encode(contents).decode('utf-8')
    
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    user_db.avatar = f"data:{file.content_type};base64,{b64_str}"
    db.commit()
    return {"success": True, "avatar": user_db.avatar}
