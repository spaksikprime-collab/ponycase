from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .db import get_db
from .models import User, InventoryItem, GameHistory
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
    # 1. Ищем предмет в инвентаре пользователя
    item = db.get(InventoryItem, data.item_id)
    if not item or item.user_id != user.id: 
        raise HTTPException(404, "Предмет не найден в вашем инвентаре")
    
    # 2. Проверяем, что целевая цена больше, чем текущая + буст
    if data.target_price <= (item.price + data.boost):
        raise HTTPException(400, "Целевая цена должна быть выше вашей ставки")

    apply_passive(user, db)
    
    # 3. Списание буста с баланса (если игрок его добавил)
    if data.boost > 0:
        if user.balance < data.boost: 
            raise HTTPException(400, "Недостаточно средств для буста")
        user.balance -= data.boost
    
    # 4. Расчет шанса
    total_bet_value = item.price + data.boost
    chance = (total_bet_value / data.target_price) * 100
    
    # Максимальный шанс 95%, чтобы не было 100% гарантии
    if chance > 95.0: 
        chance = 95.0

    # 5. Честный ролл
    user.nonce += 1
    ticket = roll_ticket(gen_seed(), gen_seed(), user.nonce)
    roll_pct = round((ticket % 10000) / 100.0, 2) 
    
    win = roll_pct <= chance
    
    # 6. Обработка результата
    try:
        if win:
            # УДАЛЯЕМ старый предмет
            db.delete(item)
            
            # СОЗДАЕМ новый улучшенный предмет
            new_item = InventoryItem(
                user_id=user.id, 
                pony_id=data.target_name, 
                rarity="upgraded", 
                price=data.target_price, 
                color="#facc15" # Золотой цвет для апгрейдов
            )
            db.add(new_item)
            
            # Обновляем лучший дроп
            if data.target_price > user.best_drop_price:
                user.best_drop_price = data.target_price
                user.best_drop_name = data.target_name
            
            # Запись в историю (Победа)
            db.add(GameHistory(
                user_id=user.id, 
                game_type="Апгрейд", 
                item_name=data.target_name, 
                price=data.target_price, 
                result_text=f"Победа (Шанс: {chance}%)"
            ))
            
            db.commit()
            
            # Отправляем в Live-ленту
            await broadcast_drop(
                user.username, 
                user.avatar, 
                data.target_name, 
                data.target_price, 
                "#facc15", 
                "Апгрейд"
            )
            
        else:
            # ПРОИГРЫШ: предмет сгорает
            db.delete(item)
            
            # Запись в историю (Проигрыш)
            db.add(GameHistory(
                user_id=user.id, 
                game_type="Апгрейд", 
                item_name=item.pony_id, 
                price=0, 
                result_text=f"Проигрыш (Шанс: {chance}%)"
            ))
            
            db.commit()
            
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Ошибка при апгрейде. Предмет и баланс восстановлены.")

    # 7. Возвращаем результат на фронтенд (чтобы он знал, куда крутить стрелку)
    return {
        "win": win, 
        "chance": round(chance, 2), 
        "balance": user.balance
    }
