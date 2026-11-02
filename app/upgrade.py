from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
from .db import get_db
from .models import User, InventoryItem, GameHistory
from .auth import current_user
from .games import gen_seed, roll_ticket
from .clicker import apply_passive
from .ws import broadcast_drop

router = APIRouter()

class UpgradeRequest(BaseModel):
    item_ids: List[int]
    target_price: int
    target_name: str
    boost: int = 0

@router.post("/play")
async def play_upgrade(data: UpgradeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not data.item_ids:
        raise HTTPException(400, "Выбери хотя бы один предмет")
        
    items = db.query(InventoryItem).filter(InventoryItem.id.in_(data.item_ids), InventoryItem.user_id == user.id).all()
    if len(items) != len(data.item_ids):
        raise HTTPException(404, "Некоторые предметы не найдены")

    total_items_price = sum(i.price for i in items)
    
    if data.target_price <= (total_items_price + data.boost):
        raise HTTPException(400, "Целевая цена должна быть выше")

    apply_passive(user, db)
    if data.boost > 0:
        if user.balance < data.boost: 
            raise HTTPException(400, "Недостаточно средств для буста")
        user.balance -= data.boost
    
    total_bet_value = total_items_price + data.boost
    chance = (total_bet_value / data.target_price) * 100
    if chance > 95.0: chance = 95.0

    user.nonce += 1
    ticket = roll_ticket(gen_seed(), gen_seed(), user.nonce)
    roll_pct = round((ticket % 10000) / 100.0, 2) 
    win = roll_pct <= chance
    
    try:
        for item in items:
            db.delete(item)
            
        if win:
            new_item = InventoryItem(user_id=user.id, pony_id=data.target_name, rarity="upgraded", price=data.target_price, color="#facc15")
            db.add(new_item)
            
            if data.target_price > user.best_drop_price:
                user.best_drop_price = data.target_price
                user.best_drop_name = data.target_name
            
            db.add(GameHistory(user_id=user.id, game_type="Апгрейд", item_name=data.target_name, price=data.target_price, result_text=f"Победа x{round(chance,1)}%"))
            db.commit()
            await broadcast_drop(user.username, user.avatar, data.target_name, data.target_price, "#facc15", "Апгрейд")
        else:
            db.add(GameHistory(user_id=user.id, game_type="Апгрейд", item_name="Сгорело", price=0, result_text=f"Проигрыш x{round(chance,1)}%"))
            db.commit()
            
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Ошибка сервера")

    return {"win": win, "chance": round(chance, 2), "balance": user.balance}
