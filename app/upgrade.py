from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .db import get_db
from .models import User, InventoryItem
from .auth import current_user
from .games import gen_seed, roll_ticket
from .clicker import apply_passive

router = APIRouter()

class UpgradeRequest(BaseModel):
    item_id: int
    target_price: int

@router.post("/play")
def play_upgrade(data: UpgradeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, data.item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Предмет не найден")
    if data.target_price <= item.price:
        raise HTTPException(400, "Цель должна быть дороже")
    
    chance = (item.price / data.target_price) * 100
    if chance > 90: chance = 90.0 # Максимум 90%

    apply_passive(user)
    user.nonce += 1
    ticket = roll_ticket(gen_seed(), gen_seed(), user.nonce)
    roll_pct = (ticket % 10000) / 100.0 
    win = roll_pct <= chance
    
    if win:
        db.delete(item)
        new_item = InventoryItem(user_id=user.id, pony_id="Upgraded Pony", rarity="epic", price=data.target_price)
        db.add(new_item)
    else:
        db.delete(item)
    db.commit()
    return {"win": win, "chance": round(chance, 2), "roll_pct": roll_pct}
