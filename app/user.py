from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
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
        "stats": {
            "total_clicks": user.total_clicks,
            "cases_opened": opened_cases
        },
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": RARITY_BY_ID.get(i.rarity, ("","","","","#fff"))[4]} for i in inventory]
    }

@router.post("/inventory/sell/{item_id}")
def sell_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Предмет не найден")
    apply_passive(user)
    user.balance += item.price
    db.delete(item)
    db.commit()
    return {"success": True, "balance": user.balance}

@router.post("/inventory/sell_all")
def sell_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user)
    items = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    total_gained = sum(item.price for item in items)
    user.balance += total_gained
    for item in items:
        db.delete(item)
    db.commit()
    return {"success": True, "balance": user.balance, "gained": total_gained}
