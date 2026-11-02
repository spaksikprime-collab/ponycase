from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .db import get_db
from .models import User
from .auth import current_user
from .clicker import apply_passive
from .games import gen_seed

router = APIRouter()

# Активные игры (в памяти)
MINES_GAMES = {}

class StartMines(BaseModel):
    bet: int
    mines: int # 3, 5, 10

class ClickCell(BaseModel):
    game_id: str
    cell: int # 0-24

@router.post("/start")
def start_mines(data: StartMines, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.bet < 10: raise HTTPException(400, "Мин. ставка 10")
    if data.mines not in [3, 5, 10]: raise HTTPException(400, "Неверное кол-во мин")
    
    apply_passive(user)
    if user.balance < data.bet: raise HTTPException(400, "Мало денег")
    user.balance -= data.bet; db.commit()
    
    game_id = gen_seed()[:8]
    import random
    mines_pos = set(random.sample(range(25), data.mines))
    
    MINES_GAMES[game_id] = {
        "id": game_id, "user_id": user.id, "bet": data.bet, 
        "mines_pos": mines_pos, "opened": set(), "active": True
    }
    
    return {"game_id": game_id, "balance": user.balance}

@router.post("/click")
def click_cell(data: ClickCell, user: User = Depends(current_user), db: Session = Depends(get_db)):
    game = MINES_GAMES.get(data.game_id)
    if not game or not game["active"] or game["user_id"] != user.id:
        raise HTTPException(400, "Игра не найдена")
        
    if data.cell in game["opened"]: raise HTTPException(400, "Уже открыто")
    
    if data.cell in game["mines_pos"]:
        game["active"] = False
        return {"status": "boom", "mines": list(game["mines_pos"])}
    else:
        game["opened"].add(data.cell)
        opened_count = len(game["opened"])
        total_safe = 25 - len(game["mines_pos"])
        multiplier = 1 + (opened_count / total_safe) * (25 / total_safe)
        win_amount = int(game["bet"] * multiplier)
        
        if opened_count == total_safe:
            game["active"] = False
            user.balance += win_amount; db.commit()
            return {"status": "win", "amount": win_amount, "balance": user.balance}
            
        return {"status": "ok", "multiplier": round(multiplier, 2), "next_win": win_amount}

@router.post("/cashout")
def cashout(data: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    game_id = data.get("game_id")
    game = MINES_GAMES.get(game_id)
    if not game or not game["active"] or game["user_id"] != user.id:
        raise HTTPException(400, "Игра не найдена")
        
    opened_count = len(game["opened"])
    if opened_count == 0: raise HTTPException(400, "Открой хотя бы одну клетку")
    
    total_safe = 25 - len(game["mines_pos"])
    multiplier = 1 + (opened_count / total_safe) * (25 / total_safe)
    win_amount = int(game["bet"] * multiplier)
    
    game["active"] = False
    user.balance += win_amount
    db.commit()
    
    return {"status": "cashout", "amount": win_amount, "balance": user.balance}
