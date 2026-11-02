from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import base64
from datetime import datetime
from .db import get_db
from .models import User, InventoryItem, CaseOpen
from .auth import current_user
from .clicker import apply_passive

router = APIRouter()

@router.get("/profile")
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user); db.commit()
    inventory = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    return {
        "user": {"id": user.id, "username": user.username, "balance": user.balance, "avatar": user.avatar},
        "stats": {"total_clicks": user.total_clicks, "cases_opened": opened_cases},
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": i.color} for i in inventory]
    }

@router.post("/bonus")
def claim_bonus(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.last_bonus and (datetime.utcnow() - user.last_bonus).total_seconds() < 3600:
        raise HTTPException(400, "Бонус будет доступен позже!")
    user.balance += 500
    user.last_bonus = datetime.utcnow()
    db.commit()
    return {"success": True, "balance": user.balance}

@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    contents = await file.read()
    b64_str = base64.b64encode(contents).decode('utf-8')
    user.avatar = f"data:{file.content_type};base64,{b64_str}"
    db.commit()
    return {"success": True, "avatar": user.avatar}
