from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import random
from .db import get_db
from .models import User
from .auth import current_user
from .games import gen_seed
from .clicker import apply_passive
from .ws import sio, broadcast_drop

router = APIRouter()
JACKPOTS = {} # Активные джекпоты

class BetIn(BaseModel):
    amount: int

@router.get("/active")
def get_active():
    return [{"id": k, "status": v["status"], "total": v["total"], "players_count": len(v["players"]), "players": v["players"]} for k, v in JACKPOTS.items() if v["status"] == "waiting"]

@router.post("/create")
async def create_jackpot(user: User = Depends(current_user)):
    j_id = gen_seed()[:6]
    JACKPOTS[j_id] = {"id": j_id, "status": "waiting", "total": 0, "players": []}
    await sio.emit("jackpot_update", JACKPOTS[j_id])
    return {"id": j_id}

@router.post("/bet/{j_id}")
async def place_bet(j_id: str, data: BetIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = JACKPOTS.get(j_id)
    if not j or j["status"] != "waiting": raise HTTPException(400, "Джекпот недоступен")
    if data.amount < 100: raise HTTPException(400, "Мин. ставка 100")
    
    apply_passive(user)
    if user.balance < data.amount: raise HTTPException(400, "Мало денег")
    user.balance -= data.amount; db.commit()
    
    # Обновляем или добавляем игрока
    player = next((p for p in j["players"] if p["id"] == user.id), None)
    if player: player["amount"] += data.amount
    else: j["players"].append({"id": user.id, "username": user.username, "avatar": user.avatar, "amount": data.amount})
    
    j["total"] += data.amount
    await sio.emit("jackpot_update", j)
    return {"balance": user.balance}

@router.post("/start/{j_id}")
async def start_jackpot(j_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    j = JACKPOTS.get(j_id)
    if not j or len(j["players"]) < 2: raise HTTPException(400, "Нужно 2+ игрока")
    
    j["status"] = "playing"
    await sio.emit("jackpot_update", j)
    
    # Розыгрыш (шанс пропорционален ставке)
    total = j["total"]
    weights = [p["amount"] / total for p in j["players"]]
    winner_idx = random.choices(range(len(j["players"])), weights=weights, k=1)[0]
    winner = j["players"][winner_idx]
    
    # Начисляем выигрыш
    w_user = db.get(User, winner["id"])
    w_user.balance += int(total * 0.95) # 5% комиссия казино
    db.commit()
    
    j["status"] = "finished"
    j["winner"] = winner
    await sio.emit("jackpot_finish", j)
    await broadcast_drop(winner["username"], winner["avatar"], "ДЖЕКПОТ!", int(total*0.95), "#facc15", "Джекпот")
    
    return {"status": "ok"}
