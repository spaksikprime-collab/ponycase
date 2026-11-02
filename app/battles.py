from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import random
from .db import get_db
from .models import User, InventoryItem
from .auth import current_user
from .games import CASES, pick_pony, pick_rarity, gen_seed, roll_ticket
from .clicker import apply_passive
from .ws import sio, broadcast_drop

router = APIRouter()

# Храним активные батлы в памяти для простоты
ACTIVE_BATTLES = {}

class CreateBattle(BaseModel):
    case_id: str
    max_players: int

class JoinBattle(BaseModel):
    battle_id: str

@router.get("/active")
def get_active():
    return [{"id": k, "case_id": v["case_id"], "status": v["status"], "players": len(v["players"]), "max": v["max"], "total_value": sum(p["value"] for p in v["players"])} for k, v in ACTIVE_BATTLES.items() if v["status"] != "finished"]

@router.post("/create")
async def create_battle(data: CreateBattle, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.case_id not in CASES:
        raise HTTPException(400, "Нет кейса")
    
    price = CASES[data.case_id]["price"]
    apply_passive(user)
    if user.balance < price: raise HTTPException(400, "Мало денег")
    
    user.balance -= price; db.commit()
    
    battle_id = gen_seed()[:8]
    ACTIVE_BATTLES[battle_id] = {
        "id": battle_id, "case_id": data.case_id, "max": data.max_players,
        "status": "waiting", "players": [{"id": user.id, "username": user.username, "avatar": user.avatar, "value": price, "items": []}]
    }
    await sio.emit("battle_update", ACTIVE_BATTLES[battle_id])
    return {"id": battle_id, "balance": user.balance}

@router.post("/join")
async def join_battle(data: JoinBattle, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = ACTIVE_BATTLES.get(data.battle_id)
    if not b or b["status"] != "waiting": raise HTTPException(400, "Нельзя войти")
    if len(b["players"]) >= b["max"]: raise HTTPException(400, "Полон")
    if any(p["id"] == user.id for p in b["players"]): raise HTTPException(400, "Ты уже тут")
    
    price = CASES[b["case_id"]]["price"]
    apply_passive(user)
    if user.balance < price: raise HTTPException(400, "Мало денег")
    
    user.balance -= price; db.commit()
    b["players"].append({"id": user.id, "username": user.username, "avatar": user.avatar, "value": price, "items": []})
    
    await sio.emit("battle_update", b)
    return {"balance": user.balance}

@router.post("/start/{battle_id}")
async def start_battle(battle_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    b = ACTIVE_BATTLES.get(battle_id)
    if not b or b["players"][0]["id"] != user.id: raise HTTPException(400, "Не твой батл")
    if len(b["players"]) < 2: raise HTTPException(400, "Нужно минимум 2 игрока")
    
    b["status"] = "playing"
    await sio.emit("battle_update", b)
    
    # Ролл предметов
    total_value = sum(p["value"] for p in b["players"])
    weights = [p["value"] / total_value for p in b["players"]]
    
    # Случайный выбор победителя с учетом веса
    winner_index = random.choices(range(len(b["players"])), weights=weights, k=1)[0]
    winner = b["players"][winner_index]
    
    # Генерируем дропы для каждого (для визуала)
    for p in b["players"]:
        rarity = random.choices(["common", "uncommon", "rare", "epic", "legendary"], weights=[60, 25, 10, 4, 1])[0]
        name, price, color = pick_pony(rarity)
        p["items"].append({"name": name, "price": price, "color": color})
        
        # Сохраняем в БД победителю
        if p["id"] == winner["id"]:
            db.add(InventoryItem(user_id=p["id"], pony_id=f"BATTLE WIN: {name}", rarity=rarity, price=int(total_value)))
            u = db.get(User, p["id"])
            u.balance += int(total_value)
    
    b["winner"] = winner
    b["status"] = "finished"
    db.commit()
    
    await sio.emit("battle_finish", b)
    await broadcast_drop(winner["username"], winner["avatar"], "БАТЛ ВЫИГРАН!", "mythic", int(total_value), "#f87171", f"Батл {b['case_id']}")
    
    return {"status": "ok"}
