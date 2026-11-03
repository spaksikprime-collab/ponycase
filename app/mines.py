from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import random
import math
from .db import get_db
from .models import User, GameHistory
from .auth import current_user
from .clicker import apply_passive
from .games import gen_seed

router = APIRouter()

MINES_GAMES = {}

class StartMines(BaseModel):
    bet: int
    mines: int

class ClickCell(BaseModel):
    game_id: str
    cell: int

class Cashout(BaseModel):
    game_id: str

@router.post("/start")
def start_mines(data: StartMines, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.bet < 10: 
        raise HTTPException(400, "Минимальная ставка 10 🪙")
    if data.mines not in [3, 5, 10]: 
        raise HTTPException(400, "Неверное количество мин")
    
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    if user_db.balance < data.bet: 
        raise HTTPException(400, "Недостаточно средств")
        
    user_db.balance -= data.bet
    db.commit()
    
    game_id = gen_seed()[:8]
    mines_positions = set(random.sample(range(25), data.mines))
    
    MINES_GAMES[game_id] = {
        "id": game_id, "user_id": user_db.id, "bet": data.bet, "mines_pos": mines_positions, "opened": set(), "active": True, "mines_count": data.mines
    }
    
    return {"game_id": game_id, "balance": user_db.balance}

@router.post("/click")
def click_cell(data: ClickCell, user: User = Depends(current_user), db: Session = Depends(get_db)):
    game = MINES_GAMES.get(data.game_id)
    
    if not game or not game["active"] or game["user_id"] != user.id: 
        raise HTTPException(400, "Игра не найдена или уже завершена")
    if data.cell in game["opened"]: 
        raise HTTPException(400, "Эта ячейка уже открыта")
    
    if data.cell in game["mines_pos"]:
        game["active"] = False
        db.add(GameHistory(user_id=user.id, game_type="Мины", item_name="Бомба 💥", price=0, result_text=f"Проигрыш (Ставка: {game['bet']})"))
        db.commit()
        return {"status": "boom", "mines": list(game["mines_pos"])}
    else:
        game["opened"].add(data.cell)
        opened_count = len(game["opened"])
        total_safe = 25 - game["mines_count"]
        
        try:
            prob = math.comb(total_safe, opened_count) / math.comb(25, opened_count)
            multiplier = round((1 / prob) * 0.95, 2)
        except Exception:
            multiplier = 1.0
            
        win_amount = int(game["bet"] * multiplier)
        
        if opened_count == total_safe:
            game["active"] = False
            user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
            user_db.balance += win_amount
            db.add(GameHistory(user_id=user.id, game_type="Мины", item_name="Джекпот 💎", price=win_amount, result_text=f"Выигрыш x{multiplier}"))
            db.commit()
            return {"status": "win", "amount": win_amount, "balance": user_db.balance}
            
        return {"status": "ok", "multiplier": multiplier, "next_win": win_amount}

@router.post("/cashout")
def cashout(data: Cashout, user: User = Depends(current_user), db: Session = Depends(get_db)):
    game = MINES_GAMES.get(data.game_id)
    
    if not game or not game["active"] or game["user_id"] != user.id: 
        raise HTTPException(400, "Игра не найдена или уже завершена")
        
    opened_count = len(game["opened"])
    if opened_count == 0: 
        raise HTTPException(400, "Вы должны открыть хотя бы одну ячейку")
    
    total_safe = 25 - game["mines_count"]
    
    try:
        prob = math.comb(total_safe, opened_count) / math.comb(25, opened_count)
        multiplier = round((1 / prob) * 0.95, 2)
    except Exception:
        multiplier = 1.0
        
    win_amount = int(game["bet"] * multiplier)
    
    game["active"] = False
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    user_db.balance += win_amount
    
    db.add(GameHistory(user_id=user.id, game_type="Мины", item_name="Забрал 💰", price=win_amount, result_text=f"Выигрыш x{multiplier}"))
    db.commit()
    
    return {"status": "cashout", "amount": win_amount, "balance": user_db.balance}
