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

WHEEL_SEGMENTS = [
    "red", "green", "red", "blue", "red", "green", "red", "yellow", 
    "red", "green", "red", "blue", "red", "green", "red", "blue",
    "red", "green", "red", "green"
]

WHEEL_COLORS = {
    "red":    {"name": "Красный", "mult": 2,  "hex": "#ef4444"},
    "green":  {"name": "Зеленый", "mult": 3,  "hex": "#22c55e"},
    "blue":   {"name": "Синий",   "mult": 4,  "hex": "#3b82f6"},
    "yellow": {"name": "Желтый",  "mult": 35, "hex": "#eab308"}
}

GAME_STATE = {
    "status": "waiting", 
    "end_time": 0,
    "server_time": 0,    
    "bets": [],
    "winning_color": None,
    "winning_index": 0,
    "history": []
}

class BetRequest(BaseModel):
    color: str
    amount: int

@router.get("/state")
def get_wheel_state():
    global GAME_STATE
    GAME_STATE["server_time"] = time.time() 
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

    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    if user_db.balance < data.amount:
        raise HTTPException(400, "Недостаточно средств")

    user_db.balance -= data.amount
    db.commit()

    bet_info = {
        "user_id": user_db.id,
        "username": user_db.username,
        "avatar": user_db.avatar,
        "color": data.color,
        "amount": data.amount
    }
    GAME_STATE["bets"].append(bet_info)
    GAME_STATE["server_time"] = time.time()
    await sio.emit("wheel_state_update", GAME_STATE)
    return {"balance": user_db.balance}

async def wheel_game_loop():
    global GAME_STATE
    
    await asyncio.sleep(5)
    
    while True:
        # --- ФАЗА 1: Ожидание (15 секунд) ---
        GAME_STATE["status"] = "waiting"
        GAME_STATE["bets"] = []
        GAME_STATE["winning_color"] = None
        GAME_STATE["winning_index"] = 0
        GAME_STATE["end_time"] = time.time() + 15
        GAME_STATE["server_time"] = time.time()
        
        await sio.emit("wheel_state_update", GAME_STATE)
        await asyncio.sleep(15)
        
        # --- ФАЗА 2: Кручение (8 секунд) ---
        GAME_STATE["status"] = "spinning"
        
        winning_index = random.randint(0, 19)
        winning_color = WHEEL_SEGMENTS[winning_index]
        
        GAME_STATE["winning_color"] = winning_color
        GAME_STATE["winning_index"] = winning_index
        GAME_STATE["server_time"] = time.time()
        
        await sio.emit("wheel_state_update", GAME_STATE)
        await asyncio.sleep(8) 
        
        # --- ФАЗА 3: Выдача призов ---
        db = SessionLocal()
        try:
            for bet in GAME_STATE["bets"]:
                if bet["color"] == winning_color:
                    win_amount = int(bet["amount"] * WHEEL_COLORS[winning_color]["mult"])
                    w_user = db.query(User).filter(User.id == bet["user_id"]).with_for_update().first()
                    if w_user:
                        w_user.balance += win_amount
                        db.add(GameHistory(
                            user_id=w_user.id, 
                            game_type="Колесо", 
                            item_name=WHEEL_COLORS[winning_color]["name"],
                            price=win_amount, 
                            result_text=f"x{WHEEL_COLORS[winning_color]['mult']}"
                        ))
                        await sio.emit("wheel_payout", {"amount": win_amount, "color": winning_color})
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Ошибка выплаты: {e}")
        finally:
            db.close()

        GAME_STATE["history"].insert(0, winning_color)
        if len(GAME_STATE["history"]) > 50:
            GAME_STATE["history"].pop()
            
        # --- ФАЗА 4: Результат (3 секунды) ---
        GAME_STATE["status"] = "finished"
        GAME_STATE["server_time"] = time.time()
        await sio.emit("wheel_state_update", GAME_STATE)
        await asyncio.sleep(3)
