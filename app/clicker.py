import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from .db import get_db
from .models import User
from .auth import current_user

router = APIRouter()
CLICK_BUCKETS = {}

UPGRADES = {
    "click_power": {"base_cost": 50,    "scale": 1.18, "step": 1.0},
    "auto_rate":   {"base_cost": 100,   "scale": 1.22, "step": 0.5},
    "multiplier":  {"base_cost": 5000,  "scale": 1.55, "step": 0.25},
}

def upgrade_level(user: User, key: str) -> int:
    if key == "click_power": return user.click_power - 1
    if key == "auto_rate": return int(round(user.auto_rate / UPGRADES["auto_rate"]["step"]))
    if key == "multiplier": return int(round((user.multiplier - 1) / UPGRADES["multiplier"]["step"]))
    return 0

def upgrade_cost(user: User, key: str) -> int:
    return int(UPGRADES[key]["base_cost"] * (UPGRADES[key]["scale"] ** upgrade_level(user, key)))

def apply_passive(user: User, db: Session):
    now = datetime.utcnow()
    elapsed = (now - user.last_passive_tick).total_seconds()
    if elapsed > 5 and user.auto_rate > 0:
        user.balance += int(elapsed * user.auto_rate * user.multiplier)
        user.last_passive_tick = now
        db.commit()
    elif elapsed > 60:
        user.last_passive_tick = now
        db.commit()

def public_user(user: User) -> dict:
    return {"id": user.id, "username": user.username, "avatar": user.avatar, "balance": user.balance, "total_clicks": user.total_clicks}

class ClickIn(BaseModel):
    # Защита от отрицательных значений и читов
    count: int = Field(default=1, ge=1, le=5) 

@router.get("/state")
def state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user, db)
    return public_user(user)

@router.post("/click")
def click(data: ClickIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = time.time()
    bucket = CLICK_BUCKETS.setdefault(user.id, [])
    bucket[:] = [t for t in bucket if now - t < 1.0]
    
    # Защита от автокликеров (макс 15 кликов в секунду)
    if len(bucket) + data.count > 15: 
        raise HTTPException(429, "Слишком быстро! Не читери.")
    bucket.extend([now] * data.count)

    apply_passive(user, db)
    gain = int(user.click_power * user.multiplier) * data.count
    user.balance += gain
    user.total_clicks += data.count
    db.commit()
    return {"balance": user.balance, "gain": gain}

class BuyIn(BaseModel):
    key: str

@router.post("/buy")
def buy(data: BuyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.key not in UPGRADES: raise HTTPException(404, "Нет апгрейда")
    apply_passive(user, db)
    
    cost = upgrade_cost(user, data.key)
    if user.balance < cost: raise HTTPException(400, f"Нужно {cost}")
    
    user.balance -= cost
    if data.key == "click_power": user.click_power += 1
    elif data.key == "auto_rate": user.auto_rate += UPGRADES[data.key]["step"]
    elif data.key == "multiplier": user.multiplier += UPGRADES[data.key]["step"]
    
    db.commit()
    return {"user": public_user(user), "next_cost": upgrade_cost(user, data.key)}
