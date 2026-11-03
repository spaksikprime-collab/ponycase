import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .db import get_db
from .models import User
from .auth import current_user

router = APIRouter()

# Увеличили лимит, чтобы не было лагов при быстром клике
CLICK_RATE_LIMIT = 30 
CLICK_BUCKETS = {}
LAST_BUCKET_CLEANUP = time.time()

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

# ИЗМЕНЕНО: Теперь функция НЕ делает коммит, а просто меняет объект в памяти
def apply_passive(user: User, db: Session):
    now = datetime.utcnow()
    
    if not user.last_passive_tick:
        user.last_passive_tick = now
        return
        
    elapsed = (now - user.last_passive_tick).total_seconds()
    
    if elapsed > 5 and user.auto_rate and user.auto_rate > 0:
        user.balance += int(elapsed * user.auto_rate * (user.multiplier or 1))
        user.last_passive_tick = now
    elif elapsed > 60:
        user.last_passive_tick = now

def public_user(user: User) -> dict:
    return {
        "id": user.id, 
        "username": user.username, 
        "avatar": user.avatar, 
        "balance": user.balance, 
        "total_clicks": user.total_clicks,
        "click_power": user.click_power,
        "auto_rate": user.auto_rate,
        "multiplier": user.multiplier
    }

# ОЧИСТКА ПАМЯТИ ОТ СТАРЫХ ЮЗЕРОВ
def clean_click_buckets():
    global LAST_BUCKET_CLEANUP
    now = time.time()
    if now - LAST_BUCKET_CLEANUP > 60: # Раз в минуту
        # Удаляем юзеров, которые не кликали последние 5 минут
        for uid in list(CLICK_BUCKETS.keys()):
            if not CLICK_BUCKETS[uid] or now - CLICK_BUCKETS[uid][-1] > 300:
                del CLICK_BUCKETS[uid]
        LAST_BUCKET_CLEANUP = now

@router.get("/state")
def state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    db.commit() # Один коммит на весь запрос
    return public_user(user_db)

@router.post("/click")
def click(user: User = Depends(current_user), db: Session = Depends(get_db)):
    clean_click_buckets() # Чистим память
    
    now = time.time()
    bucket = CLICK_BUCKETS.setdefault(user.id, [])
    bucket[:] = [t for t in bucket if now - t < 1.0]
    if len(bucket) >= CLICK_RATE_LIMIT: 
        raise HTTPException(429, "Слишком быстро")
    bucket.append(now)

    # Блокируем строку юзера
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    apply_passive(user_db, db)
    gain = int(user_db.click_power * (user_db.multiplier or 1))
    user_db.balance += gain
    user_db.total_clicks += 1
    
    db.commit() # Один коммит
    return {"balance": user_db.balance, "gain": gain}

@router.post("/buy/{key}")
def buy(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if key not in UPGRADES: 
        raise HTTPException(404, "Нет апгрейда")
        
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    cost = upgrade_cost(user_db, key)
    if user_db.balance < cost: 
        raise HTTPException(400, f"Нужно {cost}")
        
    user_db.balance -= cost
    
    if key == "click_power": 
        user_db.click_power += 1
    elif key == "auto_rate": 
        user_db.auto_rate += UPGRADES[key]["step"]
    elif key == "multiplier": 
        user_db.multiplier += UPGRADES[key]["step"]
    
    db.commit()
    return {"user": public_user(user_db), "next_cost": upgrade_cost(user_db, key)}
