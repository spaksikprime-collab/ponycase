from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import random
import asyncio
import time

from .db import get_db, SessionLocal
from .models import User, InventoryItem
from .auth import current_user
from .games import CASES, pick_pony, gen_seed
from .clicker import apply_passive
from .ws import sio, broadcast_drop

router = APIRouter()

# --- ДЖЕКПОТ (Общий банк с таймером) ---
JACKPOTS = {
    "global_jp": {"id": "global_jp", "status": "waiting", "total": 0, "players": [], "end_time": 0}
}

class BetIn(BaseModel):
    amount: int

@router.get("/active")
def get_active():
    return [JACKPOTS["global_jp"]]

@router.post("/bet")
async def place_bet(data: BetIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = JACKPOTS["global_jp"]
    
    if j["status"] not in ["waiting", "countdown"]:
        raise HTTPException(400, "Джекпот уже крутится, подождите!")
        
    if data.amount < 100:
        raise HTTPException(400, "Минимальная ставка 100 🪙")
        
    apply_passive(user)
    if user.balance < data.amount:
        raise HTTPException(400, "Недостаточно средств")
        
    user.balance -= data.amount
    db.commit()
    
    # Обновляем или добавляем игрока
    player = next((p for p in j["players"] if p["id"] == user.id), None)
    if player:
        player["amount"] += data.amount
    else:
        j["players"].append({"id": user.id, "username": user.username, "avatar": user.avatar, "amount": data.amount})
        
    j["total"] += data.amount
    
    # Если это второй игрок - запускаем таймер
    if j["status"] == "waiting" and len(j["players"]) >= 2:
        j["status"] = "countdown"
        j["end_time"] = time.time() + 15
        asyncio.create_task(run_jackpot_timer())
        
    await sio.emit("jackpot_update", j)
    return {"balance": user.balance, "jackpot": j}

async def run_jackpot_timer():
    j = JACKPOTS["global_jp"]
    while time.time() < j["end_time"]:
        await asyncio.sleep(1)
        
    # Таймер вышел - крутим!
    j["status"] = "spinning"
    await sio.emit("jackpot_update", j)
    
    # Задержка на анимацию прокрутки
    await asyncio.sleep(5) 
    
    # Выбираем победителя
    total = j["total"]
    weights = [p["amount"] / total for p in j["players"]]
    winner_idx = random.choices(range(len(j["players"])), weights=weights, k=1)[0]
    winner = j["players"][winner_idx]
    
    j["status"] = "finished"
    j["winner"] = winner
    
    # Начисляем бабки победителю
    db = SessionLocal()
    try:
        w_user = db.get(User, winner["id"])
        if w_user:
            # Оставляем 5% комиссии казино
            win_amount = int(total * 0.95)
            w_user.balance += win_amount
            
            # Записываем предмет в инвентарь
            new_item = InventoryItem(
                user_id=w_user.id, 
                pony_id=f"Jackpot Win ({winner['username']})", 
                rarity="legendary", 
                price=win_amount, 
                color="#facc15"
            )
            db.add(new_item)
            db.commit()
    finally:
        db.close()
    
    await sio.emit("jackpot_finish", j)
    await broadcast_drop(winner["username"], winner["avatar"], "ДЖЕКПОТ!", int(total*0.95), "#facc15", "Джекпот")
    
    # Ждем 5 секунд и сбрасываем
    await asyncio.sleep(5)
    JACKPOTS["global_jp"] = {"id": "global_jp", "status": "waiting", "total": 0, "players": [], "end_time": 0}
    await sio.emit("jackpot_update", JACKPOTS["global_jp"])


# --- КЕЙС-БАТЛ 1 на 1 ---
CASE_BATTLES = {}
class Create1v1(BaseModel):
    case_id: str

@router.get("/1v1/active")
def get_1v1():
    return [{"id": k, "case_id": v["case_id"], "creator": v["players"][0]["username"], "status": v["status"]} for k, v in CASE_BATTLES.items() if v["status"] == "waiting"]

@router.post("/1v1/create")
async def create_1v1(data: Create1v1, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.case_id not in CASES: raise HTTPException(400, "Нет кейса")
    price = CASES[data.case_id]["price"]
    apply_passive(user)
    if user.balance < price: raise HTTPException(400, "Мало денег")
    
    user.balance -= price; db.commit()
    b_id = gen_seed()[:6]
    CASE_BATTLES[b_id] = {"id": b_id, "case_id": data.case_id, "status": "waiting", "players": [{"id": user.id, "username": user.username, "avatar": user.avatar}]}
    await sio.emit("case_battle_update", CASE_BATTLES[b_id])
    return {"id": b_id, "balance": user.balance}

@router.post("/1v1/join/{b_id}")
async def join_1v1(b_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = CASE_BATTLES.get(b_id)
    if not b or b["status"] != "waiting": raise HTTPException(400, "Недоступно")
    if b["players"][0]["id"] == user.id: raise HTTPException(400, "Вы создатель лобби")
    
    price = CASES[b["case_id"]]["price"]
    apply_passive(user)
    if user.balance < price: raise HTTPException(400, "Мало денег")
    
    user.balance -= price; db.commit()
    b["players"].append({"id": user.id, "username": user.username, "avatar": user.avatar})
    b["status"] = "playing"
    await sio.emit("case_battle_start", b)
    
    # Генерируем дропы
    results = []
    total_val = 0
    for p in b["players"]:
        rarity = random.choices(["common", "uncommon", "rare", "epic", "legendary"], weights=[50, 25, 15, 8, 2])[0]
        name, price_drop, color = pick_pony(rarity)
        results.append({"player": p, "item": name, "price": price_drop, "color": color})
        total_val += price_drop
    
    # Победитель
    winner_res = max(results, key=lambda x: x["price"])
    winner = winner_res["player"]
    
    # Начисляем
    w_user = db.get(User, winner["id"])
    w_user.balance += total_val
    db.add(InventoryItem(user_id=winner["id"], pony_id=f"BATTLE WIN: {winner_res['item']}", rarity="epic", price=total_val, color=winner_res["color"]))
    db.commit()
    
    b["status"] = "finished"
    b["results"] = results
    b["winner"] = winner
    await sio.emit("case_battle_finish", b)
    await broadcast_drop(winner["username"], winner["avatar"], winner_res["item"], total_val, winner_res["color"], "Батл 1v1")
    
    return {"status": "ok"}
