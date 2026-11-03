import asyncio
import logging
import secrets
import time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from .db import get_db, SessionLocal
from .models import User, InventoryItem, GameHistory
from .auth import current_user
from .games import CASES, pick_rarity, pick_pony, gen_seed
from .clicker import apply_passive
from .ws import sio, broadcast_drop

router = APIRouter()
logger = logging.getLogger(__name__)

# ==========================================
# БЛОКИРОВКИ (ЗАЩИТА ОТ RACE CONDITION)
# ==========================================
jackpot_lock = asyncio.Lock()
battle_lock = asyncio.Lock()

# ==========================================
# 1. ЛОГИКА ДЖЕКПОТА
# ==========================================
JACKPOTS = {
    "global_jp": {
        "id": "global_jp", 
        "status": "waiting", 
        "total": 0, 
        "players": [], 
        "end_time": 0
    }
}

class BetIn(BaseModel):
    amount: int

@router.get("/active")
def get_active_jackpot():
    return [JACKPOTS["global_jp"]]

@router.post("/bet")
async def place_bet(data: BetIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = JACKPOTS["global_jp"]
    
    # Атомарная проверка и обновление состояния джекпота
    async with jackpot_lock:
        if j["status"] not in ["waiting", "countdown"]:
            raise HTTPException(400, "Джекпот уже крутится, подождите!")
            
        if data.amount < 100:
            raise HTTPException(400, "Минимальная ставка 100 🪙")
            
        user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
        apply_passive(user_db, db)
        
        if user_db.balance < data.amount:
            raise HTTPException(400, "Недостаточно средств")
            
        user_db.balance -= data.amount
        db.commit()
        
        player = next((p for p in j["players"] if p["id"] == user_db.id), None)
        if player:
            player["amount"] += data.amount
        else:
            j["players"].append({
                "id": user_db.id, 
                "username": user_db.username, 
                "avatar": user_db.avatar, 
                "amount": data.amount
            })
            
        j["total"] += data.amount
        
        # Запуск таймера только если статус меняется на countdown
        should_start_timer = False
        if j["status"] == "waiting" and len(j["players"]) >= 2:
            j["status"] = "countdown"
            j["end_time"] = time.time() + 15
            should_start_timer = True
            
    await sio.emit("jackpot_update", j)
    
    if should_start_timer:
        asyncio.create_task(run_jackpot_timer())
        
    return {"balance": user_db.balance, "jackpot": j}

async def run_jackpot_timer():
    j = JACKPOTS["global_jp"]
    
    # Оптимизировано: один sleep вместо цикла
    await asyncio.sleep(15) 
    
    async with jackpot_lock:
        # Проверяем, что статус все еще countdown (могли быть изменения)
        if j["status"] != "countdown":
            return
            
        j["status"] = "spinning"
        
    await sio.emit("jackpot_update", j)
    await asyncio.sleep(5) # Время на анимацию кручения
    
    # Выбор победителя (Криптостойкий ГСЧ)
    total = j["total"]
    weights = [p["amount"] / total for p in j["players"]]
    secure_rng = secrets.SystemRandom()
    winner_idx = secure_rng.choices(range(len(j["players"])), weights=weights, k=1)[0]
    winner = j["players"][winner_idx]
    
    j["status"] = "finished"
    j["winner"] = winner
    
    # Выплата призов в отдельном потоке, чтобы не блокировать event loop
    def process_payout():
        db = SessionLocal()
        try:
            w_user = db.query(User).filter(User.id == winner["id"]).with_for_update().first()
            if w_user:
                win_amount = int(total * 0.95) # House edge 5%
                w_user.balance += win_amount
                
                db.add(InventoryItem(
                    user_id=w_user.id, 
                    pony_id=f"Jackpot Win", 
                    rarity="legendary", 
                    price=win_amount, 
                    color="#facc15"
                ))
                db.add(GameHistory(
                    user_id=w_user.id, 
                    game_type="Джекпот", 
                    item_name="Победа", 
                    price=win_amount, 
                    result_text=f"Забрал банк {total}"
                ))
                db.commit()
        except Exception as e:
            logger.error(f"Jackpot payout error: {e}")
            db.rollback()
        finally: 
            db.close()

    await asyncio.to_thread(process_payout)
    
    await sio.emit("jackpot_finish", j)
    await broadcast_drop(winner["username"], winner["avatar"], "ДЖЕКПОТ!", int(total*0.95), "#facc15", "Джекпот")
    
    await asyncio.sleep(5)
    
    async with jackpot_lock:
        # СБРОС ДЖЕКПОТА
        JACKPOTS["global_jp"] = {
            "id": "global_jp", "status": "waiting", "total": 0, "players": [], "end_time": 0
        }
    await sio.emit("jackpot_update", JACKPOTS["global_jp"])


# ==========================================
# 2. ЛОГИКА БАТЛОВ 1 НА 1
# ==========================================
CASE_BATTLES = {}

class Create1v1(BaseModel):
    case_id: str

@router.get("/1v1/active")
def get_1v1_list():
    return [
        {
            "id": k, 
            "case_id": v["case_id"], 
            "creator": v["players"][0]["username"], 
            "status": v["status"]
        } for k, v in CASE_BATTLES.items() if v["status"] == "waiting"
    ]

@router.post("/1v1/create")
async def create_1v1(data: Create1v1, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.case_id not in CASES: 
        raise HTTPException(400, "Такого кейса не существует")
        
    price = CASES[data.case_id]["price"]
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    if user_db.balance < price: 
        raise HTTPException(400, "Недостаточно средств")
    
    user_db.balance -= price
    db.commit()
    
    # Надежный ID батла
    b_id = secrets.token_hex(4)
    CASE_BATTLES[b_id] = {
        "id": b_id, 
        "case_id": data.case_id, 
        "status": "waiting", 
        "players": [{"id": user_db.id, "username": user_db.username, "avatar": user_db.avatar}]
    }
    
    await sio.emit("case_battle_update", CASE_BATTLES[b_id])
    return {"id": b_id, "balance": user_db.balance}

@router.post("/1v1/join/{b_id}")
async def join_1v1(b_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    async with battle_lock:
        b = CASE_BATTLES.get(b_id)
        
        if not b or b["status"] != "waiting": 
            raise HTTPException(400, "Лобби недоступно или уже началось")
            
        if b["players"][0]["id"] == user.id: 
            raise HTTPException(400, "Вы не можете играть сами с собой")
        
        price = CASES[b["case_id"]]["price"]
        user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
        apply_passive(user_db, db)
        
        if user_db.balance < price: 
            raise HTTPException(400, "Недостаточно средств")
        
        user_db.balance -= price
        db.commit()
        
        b["players"].append({"id": user_db.id, "username": user_db.username, "avatar": user_db.avatar})
        b["status"] = "playing"
        
    await sio.emit("case_battle_start", b)
    
    # Генерация дропов с использованием РЕАЛЬНЫХ весов кейса
    results = []
    total_val = 0
    
    for p in b["players"]:
        # Используем функции из games.py для честного дропа
        ticket = secrets.randbelow(1_000_000)
        rarity = pick_rarity(b["case_id"], ticket)
        name, price_drop, color = pick_pony(rarity)
        
        results.append({"player": p, "item": name, "price": price_drop, "color": color})
        total_val += price_drop
    
    winner_res = max(results, key=lambda x: x["price"])
    winner = winner_res["player"]
    
    def process_battle_win():
        db = SessionLocal()
        try:
            w_user = db.query(User).filter(User.id == winner["id"]).with_for_update().first()
            w_user.balance += total_val
            
            db.add(InventoryItem(
                user_id=winner["id"], 
                pony_id=f"БАТЛ: {winner_res['item']}", 
                rarity="epic", 
                price=total_val, 
                color=winner_res["color"]
            ))
            
            db.add(GameHistory(
                user_id=winner["id"], 
                game_type="Батл 1v1", 
                item_name=winner_res["item"], 
                price=total_val, 
                result_text="Победа в батле"
            ))
            db.commit()
        except Exception as e:
            logger.error(f"Battle payout error: {e}")
            db.rollback()
        finally:
            db.close()

    await asyncio.to_thread(process_battle_win)
    
    b["status"] = "finished"
    b["results"] = results
    b["winner"] = winner
    
    await sio.emit("case_battle_finish", b)
    await broadcast_drop(winner["username"], winner["avatar"], winner_res["item"], total_val, winner_res["color"], "Батл 1v1")
    
    # ОЧИСТКА ПАМЯТИ
    asyncio.create_task(cleanup_battle(b_id))
    
    return {"status": "ok", "winner": winner["username"], "balance": user_db.balance}

async def cleanup_battle(b_id: str):
    await asyncio.sleep(10)
    if b_id in CASE_BATTLES:
        del CASE_BATTLES[b_id]
