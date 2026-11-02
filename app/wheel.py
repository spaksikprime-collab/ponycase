from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import asyncio
import time
import random
from .db import SessionLocal, get_db
from .models import User, GameHistory
from .auth import current_user
from .clicker import apply_passive
from .ws import sio

router = APIRouter()

# Настройки цветов и их множителей
# Сумма шансов должна быть равна 100
WHEEL_COLORS = {
    "red":    {"name": "Красный", "mult": 2,  "chance": 50, "hex": "#ef4444"},
    "green":  {"name": "Зеленый", "mult": 3,  "chance": 30, "hex": "#22c55e"},
    "blue":   {"name": "Синий",   "mult": 4,  "chance": 18, "hex": "#3b82f6"},
    "yellow": {"name": "Желтый",  "mult": 35, "chance": 2,  "hex": "#eab308"}
}

# Глобальное состояние игры (хранится в памяти сервера)
GAME_STATE = {
    "status": "waiting", # waiting, spinning, finished
    "end_time": 0,
    "bets": [], # Список всех ставок за раунд: {"user_id": int, "username": str, "avatar": str, "color": str, "amount": int}
    "winning_color": None,
    "history": [] # Последние 50 выигрышных цветов
}

class BetRequest(BaseModel):
    color: str
    amount: int

@router.get("/state")
def get_wheel_state():
    return GAME_STATE

@router.post("/bet")
async def place_bet(data: BetRequest, user: User = Depends(current_user), db: Session = Depends(get_db)):
    global GAME_STATE
    
    if GAME_STATE["status"] != "waiting":
        raise HTTPException(400, "Ставки на этот раунд закрыты")
    
    if data.color not in WHEEL_COLORS:
        raise HTTPException(400, "Неверный цвет")
        
    if data.amount < 10:
        raise HTTPException(400, "Минимальная ставка 10 🪙")

    apply_passive(user, db)
    
    if user.balance < data.amount:
        raise HTTPException(400, "Недостаточно средств")

    # Списываем баланс
    user.balance -= data.amount
    db.commit()

    # Добавляем ставку в общий пул
    bet_info = {
        "user_id": user.id,
        "username": user.username,
        "avatar": user.avatar,
        "color": data.color,
        "amount": data.amount
    }
    GAME_STATE["bets"].append(bet_info)

    # Отправляем обновление всем в сокет (чтобы у всех обновился список ставок)
    await sio.emit("wheel_state_update", GAME_STATE)
    
    return {"balance": user.balance}

# ==========================================
# ФОНОВАЯ ЗАДАЧА (Запускается из main.py)
# ==========================================
async def wheel_game_loop():
    global GAME_STATE
    
    # Небольшая задержка при старте сервера, чтобы все прогрузилось
    await asyncio.sleep(5)
    
    while True:
        # --- ФАЗА 1: Ожидание ставок (10 секунд) ---
        GAME_STATE["status"] = "waiting"
        GAME_STATE["bets"] = []
        GAME_STATE["winning_color"] = None
        GAME_STATE["end_time"] = time.time() + 10
        
        await sio.emit("wheel_state_update", GAME_STATE)
        
        # Ждем 10 секунд
        await asyncio.sleep(10)
        
        # --- ФАЗА 2: Кручение (5 секунд) ---
        GAME_STATE["status"] = "spinning"
        
        # Выбираем победителя на основе шансов
        colors = list(WHEEL_COLORS.keys())
        weights = [WHEEL_COLORS[c]["chance"] for c in colors]
        winning_color = random.choices(colors, weights=weights, k=1)[0]
        
        GAME_STATE["winning_color"] = winning_color
        
        await sio.emit("wheel_state_update", GAME_STATE)
        
        # Ждем 5 секунд, пока на фронтенде крутится анимация
        await asyncio.sleep(5)
        
        # --- ФАЗА 3: Выдача выигрышей ---
        db = SessionLocal()
        try:
            for bet in GAME_STATE["bets"]:
                if bet["color"] == winning_color:
                    # Игрок выиграл
                    win_amount = int(bet["amount"] * WHEEL_COLORS[winning_color]["mult"])
                    w_user = db.get(User, bet["user_id"])
                    
                    if w_user:
                        w_user.balance += win_amount
                        
                        # Пишем в историю
                        db.add(GameHistory(
                            user_id=w_user.id,
                            game_type="Колесо",
                            item_name=WHEEL_COLORS[winning_color]["name"],
                            price=win_amount,
                            result_text=f"Ставка: {bet['amount']} (x{WHEEL_COLORS[winning_color]['mult']})"
                        ))
                        
                        # Отправляем персональное уведомление (на фронте можно поймать)
                        await sio.emit("wheel_payout", {"amount": win_amount, "color": winning_color})
            
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Ошибка при выдаче выигрышей в Колесе: {e}")
        finally:
            db.close()

        # Обновляем историю (максимум 50 записей)
        GAME_STATE["history"].insert(0, winning_color)
        if len(GAME_STATE["history"]) > 50:
            GAME_STATE["history"].pop()
            
        # --- ФАЗА 4: Конец раунда (висит 3 секунды, чтобы все увидели победителя) ---
        GAME_STATE["status"] = "finished"
        await sio.emit("wheel_state_update", GAME_STATE)
        
        await asyncio.sleep(3) 
