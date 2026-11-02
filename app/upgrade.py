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
    boost: int = 0

@router.post("/play")
async def play_upgrade(data: UpgradeRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, data.item_id)
    if not item or item.user_id != user.id: 
        raise HTTPException(404, "Предмет не найден в инвентаре")
    
    # Проверка, что цель дороже
    if data.target_price <= (item.price + data.boost):
        raise HTTPException(400, "Целевая цена должна быть выше вашей ставки")

    apply_passive(user, db)
    
    # Списание буста с баланса (если игрок добавил)
    if data.boost > 0:
        if user.balance < data.boost: 
            raise HTTPException(400, "Недостаточно средств для буста")
        user.balance -= data.boost
    
    # Рассчитываем шанс
    total_bet_value = item.price + data.boost
    chance = (total_bet_value / data.target_price) * 100
    if chance > 95: chance = 95.0 # Максимальный шанс 95%

    user.nonce += 1
    ticket = roll_ticket(gen_seed(), gen_seed(), user.nonce)
    roll_pct = round((ticket % 10000) / 100.0, 2) 
    
    win = roll_pct <= chance
    
    try:
        if win:
            db.delete(item)
            # Создаем новый улучшенный предмет
            new_item = InventoryItem(
                user_id=user.id, 
                pony_id=data.target_name, 
                rarity="upgraded", 
                price=data.target_price, 
                color="#facc15"
            )
            db.add(new_item)
            
            # ОБНОВЛЯЕМ ЛУЧШИЙ ДРОП
            if data.target_price > user.best_drop_price:
                user.best_drop_price = data.target_price
                user.best_drop_name = data.target_name
                
            db.commit()
            await broadcast_drop(user.username, user.avatar, data.target_name, data.target_price, "#facc15", "Апгрейд")
            
        else:
            db.delete(item)
            db.commit()
            
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Ошибка при апгрейде. Предмет и баланс восстановлены.")

    return {"win": win, "chance": round(chance, 2), "balance": user.balance}
