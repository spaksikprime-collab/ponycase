from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .db import get_db
from .models import User, InventoryItem
from .auth import current_user
from .games import gen_seed, roll_ticket, pick_pony
from .clicker import apply_passive

router = APIRouter()

class UpgradeRequest(BaseModel):
    item_id: int
    target_price: int
    target_name: str

@router.post("/play")
def play_upgrade(data: UpgradeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, data.item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Предмет не найден")
    
    if data.target_price <= item.price:
        raise HTTPException(400, "Цель должна быть дороже вашего предмета!")

    chance = (item.price / data.target_price) * 100
    if chance > 95: chance = 95.0

    apply_passive(user)
    user.nonce += 1
    
    ticket = roll_ticket(gen_seed(), gen_seed(), user.nonce)
    roll_pct = round((ticket % 10000) / 100.0, 2) 
    
    win = roll_pct <= chance
    
    if win:
        db.delete(item)
        # Выдаем предмет с новой ценой
        new_item = InventoryItem(
            user_id=user.id, 
            pony_id=data.target_name, 
            rarity="upgraded", 
            price=data.target_price, 
            color="#facc15" # Золотой цвет за апгрейд
        )
        db.add(new_item)
    else:
        db.delete(item)
        
    db.commit()
    return {"win": win, "chance": round(chance, 2), "roll_pct": roll_pct}
