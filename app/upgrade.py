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
    multiplier: float  # ТЕПЕРЬ ПЕРЕДАЕМ МНОЖИТЕЛЬ, А НЕ ЦЕНУ
    boost: int = 0

@router.post("/play")
async def play_upgrade(data: UpgradeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not data.item_ids:
        raise HTTPException(400, "Выбери хотя бы один предмет")
        
    # Блокируем юзера в БД, чтобы не было двойных списаний
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    items = db.query(InventoryItem).filter(InventoryItem.id.in_(data.item_ids), InventoryItem.user_id == user_db.id).all()
    if len(items) != len(data.item_ids):
        raise HTTPException(404, "Некоторые предметы не найдены")

    total_items_price = sum(i.price for i in items)
    
    # СЕРВЕР САМ СЧИТАЕТ ЦЕНУ
    target_price = int(total_items_price * data.multiplier)
    if target_price <= (total_items_price + data.boost):
        raise HTTPException(400, "Множитель слишком маленький")

    apply_passive(user_db, db)
    if data.boost > 0:
        if user_db.balance < data.boost: 
            raise HTTPException(400, "Недостаточно средств для буста")
        user_db.balance -= data.boost
    
    total_bet_value = total_items_price + data.boost
    chance = (total_bet_value / target_price) * 100
    if chance > 95.0: chance = 95.0

    user_db.nonce += 1
    ticket = roll_ticket(gen_seed(), gen_seed(), user_db.nonce)
    roll_pct = round((ticket % 10000) / 100.0, 2) 
    win = roll_pct <= chance
    
    try:
        for item in items:
            db.delete(item)
            
        if win:
            new_item = InventoryItem(user_id=user_db.id, pony_id=f"Upgraded Pony x{data.multiplier}", rarity="upgraded", price=target_price, color="#facc15")
            db.add(new_item)
            
            if target_price > user_db.best_drop_price:
                user_db.best_drop_price = target_price
                user_db.best_drop_name = f"Upgraded Pony x{data.multiplier}"
            
            db.add(GameHistory(user_id=user_db.id, game_type="Апгрейд", item_name=f"Upgraded Pony", price=target_price, result_text=f"Победа x{round(chance,1)}%"))
            db.commit()
            await broadcast_drop(user_db.username, user_db.avatar, f"Upgraded Pony", target_price, "#facc15", "Апгрейд")
        else:
            db.add(GameHistory(user_id=user_db.id, game_type="Апгрейд", item_name="Сгорело", price=0, result_text=f"Проигрыш x{round(chance,1)}%"))
            db.commit()
            
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Ошибка сервера")

    return {"win": win, "chance": round(chance, 2), "balance": user_db.balance, "target_price": target_price}
