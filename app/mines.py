import asyncio
import logging
import math
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .db import get_db
from .models import User, GameHistory
from .auth import current_user
from .clicker import apply_passive
from .games import gen_seed

router = APIRouter()
logger = logging.getLogger(__name__)

# ==========================================
# ГЛОБАЛЬНОЕ СОСТОЯНИЕ ИГР
# ==========================================
MINES_GAMES = {}
# Фоновая задача для очистки старых игр (защита от утечки памяти)
CLEANUP_TASK = None

class StartMines(BaseModel):
    bet: int
    mines: int

class ClickCell(BaseModel):
    game_id: str
    cell: int

class Cashout(BaseModel):
    game_id: str

# ==========================================
# ФОНОВАЯ ОЧИСТКА (ЗАЩИТА ОТ MEMORY LEAK)
# ==========================================
async def cleanup_mines_games():
    """Удаляет завершенные игры старше 15 минут."""
    while True:
        await asyncio.sleep(300)  # Проверка каждые 5 минут
        
        now = time.time()
        expired_games = [
            gid for gid, game in MINES_GAMES.items()
            if not game["active"] and (now - game.get("last_activity", now)) > 900
        ]
        
        for gid in expired_games:
            del MINES_GAMES[gid]
        
        if expired_games:
            logger.info(f" Cleaned up {len(expired_games)} expired mines games")

# Запускаем задачу очистки при старте модуля
# В реальном продакшене лучше делать это через lifespan в main.py
CLEANUP_TASK = asyncio.create_task(cleanup_mines_games())

# ==========================================
# ЭНДПОИНТЫ ИГРЫ
# ==========================================
@router.post("/start")
def start_mines(data: StartMines, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.bet < 10: 
        raise HTTPException(400, "Минимальная ставка 10 ")
    if data.mines not in [3, 5, 10]: 
        raise HTTPException(400, "Неверное количество мин (доступно: 3, 5, 10)")
    
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    if user_db.balance < data.bet: 
        raise HTTPException(400, "Недостаточно средств")
        
    user_db.balance -= data.bet
    db.commit()
    
    game_id = gen_seed()[:8]
    
    # ИСПРАВЛЕНО: Криптостойкая генерация позиций мин
    secure_rng = secrets.SystemRandom()
    mines_positions = set(secure_rng.sample(range(25), data.mines))
    
    MINES_GAMES[game_id] = {
        "id": game_id, 
        "user_id": user_db.id, 
        "bet": data.bet, 
        "mines_pos": mines_positions, 
        "opened": set(), 
        "active": True, 
        "mines_count": data.mines,
        "created_at": time.time(),
        "last_activity": time.time()
    }
    
    logger.info(f"💣 Mines game started: {user_db.username} (bet: {data.bet}, mines: {data.mines})")
    
    return {"game_id": game_id, "balance": user_db.balance}

@router.post("/click")
def click_cell(data: ClickCell, user: User = Depends(current_user), db: Session = Depends(get_db)):
    game = MINES_GAMES.get(data.game_id)
    
    if not game or not game["active"] or game["user_id"] != user.id: 
        raise HTTPException(400, "Игра не найдена или уже завершена")
    
    # ИСПРАВЛЕНО: Атомарная проверка и установка флага ячейки
    if data.cell in game["opened"]: 
        raise HTTPException(400, "Эта ячейка уже открыта")
    
    # Сразу помечаем ячейку как открытую (защита от race condition)
    game["opened"].add(data.cell)
    game["last_activity"] = time.time()
    
    if data.cell in game["mines_pos"]:
        # ВЗРЫВ
        game["active"] = False
        game["last_activity"] = time.time()
        
        db.add(GameHistory(
            user_id=user.id, 
            game_type="Мины", 
            item_name="Бомба 💥", 
            price=0, 
            result_text=f"Проигрыш (Ставка: {game['bet']})"
        ))
        db.commit()
        
        return {"status": "boom", "mines": list(game["mines_pos"])}
    else:
        # БЕЗОПАСНАЯ ЯЧЕЙКА
        opened_count = len(game["opened"])
        total_safe = 25 - game["mines_count"]
        
        # Расчет множителя через комбинаторику
        try:
            # Вероятность вытащить N безопасных ячеек подряд без возврата
            prob = math.comb(total_safe, opened_count) / math.comb(25, opened_count)
            multiplier = round((1 / prob) * 0.95, 2)  # House edge 5%
        except Exception:
            multiplier = 1.0
            
        win_amount = round(game["bet"] * multiplier)
        
        # Если открыты все безопасные ячейки — автоматический выигрыш
        if opened_count == total_safe:
            game["active"] = False
            game["last_activity"] = time.time()
            
            user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
            user_db.balance += win_amount
            
            db.add(GameHistory(
                user_id=user.id, 
                game_type="Мины", 
                item_name="Джекпот 💎", 
                price=win_amount, 
                result_text=f"Выигрыш x{multiplier}"
            ))
            db.commit()
            
            return {"status": "win", "amount": win_amount, "balance": user_db.balance}
            
        return {
            "status": "ok", 
            "multiplier": multiplier, 
            "next_win": win_amount,
            "opened": list(game["opened"])
        }

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
        
    win_amount = round(game["bet"] * multiplier)
    
    game["active"] = False
    game["last_activity"] = time.time()
    
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    user_db.balance += win_amount
    
    db.add(GameHistory(
        user_id=user.id, 
        game_type="Мины", 
        item_name="Забрал 💰", 
        price=win_amount, 
        result_text=f"Выигрыш x{multiplier}"
    ))
    db.commit()
    
    logger.info(f"💰 {user_db.username} cashed out mines for {win_amount}🪙 (x{multiplier})")
    
    return {"status": "cashout", "amount": win_amount, "balance": user_db.balance}
