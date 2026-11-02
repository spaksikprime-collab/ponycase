from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .db import get_db
from .models import User, InventoryItem
from .auth import current_user
from .games import gen_seed, roll_ticket
from .clicker import apply_passive
from .ws import broadcast_drop

router = APIRouter()

class UpgradeRequest(BaseModel):
    item_id: int
    target_price: int
    target_name: str
    boost: int = 0 # НОВОЕ: сумма для повышения шанса

@router.post("/play")
async def play_upgrade(data: UpgradeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, data.item_id)
    if not item or item.user_id != user.id: raise HTTPException(404, "Предмет не найден")
    
    if data.target_price <= (item.price + data.boost):
        raise HTTPException(400, "Цель должна быть дороже!")

    apply_passive(user, db)
    
    # Списание буста с баланса
    if data.boost > 0:
        if user.balance < data.boost: raise HTTPException(400, "Недостаточно средств для буста")
        user.balance -= data.boost
    
    # Шанс рассчитывается с учетом буста
    total_bet_value = item.price + data.boost
    chance = (total_bet_value / data.target_price) * 100
    if chance > 95: chance = 95.0

    user.nonce += 1
    ticket = roll_ticket(gen_seed(), gen_seed(), user.nonce)
    roll_pct = round((ticket % 10000) / 100.0, 2) 
    
    win = roll_pct <= chance
    
    if win:
        db.delete(item)
        new_item = InventoryItem(user_id=user.id, pony_id=data.target_name, rarity="upgraded", price=data.target_price, color="#facc15")
        db.add(new_item)
        db.commit()
        await broadcast_drop(user.username, user.avatar, data.target_name, data.target_price, "#facc15", "Апгрейд")
    else:
        db.delete(item)
        db.commit()
        
    return {"win": win, "chance": round(chance, 2), "balance": user.balance}
