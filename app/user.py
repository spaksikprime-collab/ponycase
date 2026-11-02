from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from .db import get_db
from .models import User, InventoryItem, CaseOpen
from .auth import current_user
from .clicker import apply_passive, public_user
from .games import RARITY_BY_ID

router = APIRouter()

@router.get("/profile")
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user); db.commit()
    inventory = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    return {
        "user": public_user(user),
        "stats": {"total_clicks": user.total_clicks, "cases_opened": opened_cases},
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": RARITY_BY_ID.get(i.rarity, ("","","","","#c084fc"))[4]} for i in inventory]
    }

@router.post("/bonus")
def claim_bonus(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Даем 1000 монет раз в час (для теста)
    if user.last_bonus and (datetime.utcnow() - user.last_bonus).total_seconds() < 3600:
        raise HTTPException(400, "Бонус будет доступен позже!")
    user.balance += 1000
    user.last_bonus = datetime.utcnow()
    db.commit()
    return {"success": True, "balance": user.balance}

# ... (остальные методы sell_item, sell_all, upload_avatar оставляем как были)
