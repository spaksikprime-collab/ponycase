import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List

from .db import get_db
from .models import User, InventoryItem, GameHistory
from .auth import current_user
from .games import gen_seed, roll_ticket
from .clicker import apply_passive
from .ws import broadcast_drop

router = APIRouter()
logger = logging.getLogger(__name__)

background_tasks = set()

class UpgradeRequest(BaseModel):
    item_ids: List[int] = Field(..., min_length=1, description="ID предметов для апгрейда")
    multiplier: float = Field(..., ge=1.1, le=100.0, description="Множитель апгрейда (от 1.1 до 100)")
    boost: int = Field(default=0, ge=0, description="Дополнительный буст балансом")

@router.post("/play")
async def play_upgrade(data: UpgradeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    items = db.query(InventoryItem).filter(
        InventoryItem.id.in_(data.item_ids), 
        InventoryItem.user_id == user_db.id
    ).all()
    
    if len(items) != len(data.item_ids):
        raise HTTPException(status_code=404, detail="Некоторые предметы не найдены в вашем инвентаре")

    total_items_price = sum(i.price for i in items)
    target_price = int(total_items_price * data.multiplier)
    
    if target_price <= (total_items_price + data.boost):
        raise HTTPException(status_code=400, detail="Целевая цена должна быть выше суммы предметов и буста")

    apply_passive(user_db, db)
    
    if data.boost > 0:
        if user_db.balance < data.boost: 
            raise HTTPException(status_code=400, detail="Недостаточно средств для буста")
        user_db.balance -= data.boost
    
    total_bet_value = total_items_price + data.boost
    chance = (total_bet_value / target_price) * 100
    
    if chance > 95.0: 
        chance = 95.0

    user_db.nonce += 1
    server_seed = gen_seed()
    client_seed = f"{user_db.id}:{user_db.nonce}"
    
    ticket = roll_ticket(server_seed, client_seed, user_db.nonce)
    roll_pct = round((ticket % 10000) / 100.0, 2) 
    win = roll_pct <= chance

    try:
        # ИСПРАВЛЕНО: Убрана проверка db.session
        for item in items:
            db.delete(item)
            
        if win:
            original_name = items[0].pony_id
            new_name = f"{original_name} (Upgraded x{data.multiplier})"
            
            new_item = InventoryItem(
                user_id=user_db.id, 
                pony_id=new_name, 
                rarity="upgraded", 
                price=target_price, 
                color="#facc15"
            )
            db.add(new_item)
            
            if target_price > (user_db.best_drop_price or 0):
                user_db.best_drop_price = target_price
                user_db.best_drop_name = new_name
            
            db.add(GameHistory(
                user_id=user_db.id, 
                game_type="Апгрейд", 
                item_name=new_name, 
                price=target_price, 
                result_text=f"Победа (Шанс: {round(chance, 1)}%)"
            ))
            db.commit()
            
            task = asyncio.create_task(broadcast_drop(user_db.username, user_db.avatar, new_name, target_price, "#facc15", "Апгрейд"))
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
            
        else:
            db.add(GameHistory(
                user_id=user_db.id, 
                game_type="Апгрейд", 
                item_name="Сгорело", 
                price=0, 
                result_text=f"Проигрыш (Шанс: {round(chance, 1)}%)"
            ))
            db.commit()
            
    except Exception as e:
        db.rollback()
        logger.error(f"Upgrade error for {user_db.username}: {e}")
        raise HTTPException(status_code=500, detail="Ошибка сервера при апгрейде")

    return {
        "win": win, 
        "chance": round(chance, 2), 
        "balance": user_db.balance, 
        "target_price": target_price,
        "provably_fair": {
            "server_seed": server_seed,
            "client_seed": client_seed,
            "nonce": user_db.nonce,
            "roll_pct": roll_pct
        }
    }
