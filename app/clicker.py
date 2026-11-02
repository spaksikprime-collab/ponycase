import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .db import get_db
from .models import User
from .auth import current_user

router = APIRouter()

CLICK_RATE_LIMIT = 15
CLICK_BUCKETS: dict[int, list[float]] = {}

UPGRADES = {
    "click_power": {"base_cost": 50,    "scale": 1.18, "step": 1.0,  "label": "+1 к клику"},
    "auto_rate":   {"base_cost": 100,   "scale": 1.22, "step": 0.5,  "label": "+0.5/сек"},
    "multiplier":  {"base_cost": 5000,  "scale": 1.55, "step": 0.25, "label": "×1.25"},
}

def upgrade_level(user: User, key: str) -> int:
    if key == "click_power":
        return user.click_power - 1
    if key == "auto_rate":
        return int(round(user.auto_rate / UPGRADES["auto_rate"]["step"]))
    if key == "multiplier":
        return int(round((user.multiplier - 1) / UPGRADES["multiplier"]["step"]))
    return 0

def upgrade_cost(user: User, key: str) -> int:
    u = UPGRADES[key]
    return int(u["base_cost"] * (u["scale"] ** upgrade_level(user, key)))

def apply_passive(user: User):
    now = datetime.utcnow()
    elapsed = (now - user.last_passive_tick).total_seconds()
    user.last_passive_tick = now
    if elapsed > 0 and user.auto_rate > 0:
        # Убрали prestige из формулы
        user.balance += int(elapsed * user.auto_rate * user.multiplier)

def public_user(user: User) -> dict:
    return {
        "id": user.id, "username": user.username, "avatar": user.avatar,
        "balance": user.balance, "total_clicks": user.total_clicks,
        "click_power": user.click_power, "auto_rate": user.auto_rate,
        "multiplier": user.multiplier
    }

@router.get("/state")
def state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user); db.commit()
    return public_user(user)

@router.post("/click")
def click(user: User = Depends(current_user), db: Session = Depends(get_db)):
    now = time.time()
    bucket = CLICK_BUCKETS.setdefault(user.id, [])
    bucket[:] = [t for t in bucket if now - t < 1.0]
    if len(bucket) >= CLICK_RATE_LIMIT:
        raise HTTPException(429, "Слишком быстро")
    bucket.append(now)

    apply_passive(user)
    gain = int(user.click_power * user.multiplier)
    user.balance += gain
    user.total_clicks += 1
    db.commit()
    return {"balance": user.balance, "gain": gain}

@router.post("/buy/{key}")
def buy(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if key not in UPGRADES:
        raise HTTPException(404, "Нет такого апгрейда")
    apply_passive(user)
    cost = upgrade_cost(user, key)
    if user.balance < cost:
        raise HTTPException(400, f"Нужно {cost} копыт")
    user.balance -= cost
    if key == "click_power":
        user.click_power += 1
    elif key == "auto_rate":
        user.auto_rate += UPGRADES[key]["step"]
    elif key == "multiplier":
        user.multiplier += UPGRADES[key]["step"]
    db.commit()
    return {"user": public_user(user), "next_cost": upgrade_cost(user, key)}
