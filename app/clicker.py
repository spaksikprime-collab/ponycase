import time
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .db import get_db
from .models import User
from .auth import current_user

router = APIRouter()
logger = logging.getLogger(__name__)

# ==========================================
# КОНФИГУРАЦИЯ RATE LIMITING
# ==========================================
# Максимум кликов в секунду на одного пользователя
CLICK_RATE_LIMIT = 30
# Словарь для хранения временных меток кликов (в памяти)
# ВАЖНО: При нескольких воркерах uvicorn нужен Redis. Для одного воркера работает отлично.
CLICK_BUCKETS = {}
LAST_BUCKET_CLEANUP = time.time()

# ==========================================
# КОНФИГУРАЦИЯ АПГРЕЙДОВ
# ==========================================
UPGRADES = {
    "click_power": {
        "base_cost": 50,
        "scale": 1.18,
        "step": 1.0,
        "max_level": 1000  # Защита от переполнения
    },
    "auto_rate": {
        "base_cost": 100,
        "scale": 1.22,
        "step": 0.5,
        "max_level": 500
    },
    "multiplier": {
        "base_cost": 5000,
        "scale": 1.55,
        "step": 0.25,
        "max_level": 100
    },
}

# Максимальное время AFK для начисления пассива (в секундах)
MAX_AFK_SECONDS = 3600  # 1 час

# ==========================================
# УТИЛИТЫ АПГРЕЙДОВ
# ==========================================
def upgrade_level(user: User, key: str) -> int:
    """Вычисляет текущий уровень апгрейда на основе значений в БД."""
    if key == "click_power":
        return max(0, user.click_power - 1)
    if key == "auto_rate":
        return int(round(user.auto_rate / UPGRADES["auto_rate"]["step"]))
    if key == "multiplier":
        return int(round((user.multiplier - 1) / UPGRADES["multiplier"]["step"]))
    return 0

def upgrade_cost(user: User, key: str) -> int:
    """Рассчитывает стоимость следующего уровня апгрейда."""
    if key not in UPGRADES:
        return 0
    level = upgrade_level(user, key)
    config = UPGRADES[key]
    return int(config["base_cost"] * (config["scale"] ** level))

def apply_passive(user: User, db: Session) -> None:
    """
    Начисляет пассивный доход с момента последнего тика.
    ВАЖНО: Эта функция ТОЛЬКО меняет объект в памяти.
    Коммит делается в вызывающем роуте.
    """
    now = datetime.now(timezone.utc)
    
    if not user.last_passive_tick:
        user.last_passive_tick = now
        return
    
    last_tick = user.last_passive_tick
    if last_tick.tzinfo is None:
        last_tick = last_tick.replace(tzinfo=timezone.utc)
    
    elapsed = (now - last_tick).total_seconds()
    
    if elapsed < 5:
        return
    
    if elapsed > MAX_AFK_SECONDS:
        elapsed = MAX_AFK_SECONDS
    
    if user.auto_rate and user.auto_rate > 0:
        mult = max(user.multiplier or 1.0, 1.0)
        # Используем round() для честного начисления без микро-потерь
        gain = round(elapsed * user.auto_rate * mult)
        if gain > 0:
            user.balance += gain
    
    user.last_passive_tick = now

def public_user(user: User) -> dict:
    """Возвращает публичную информацию о пользователе для API."""
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

def clean_click_buckets():
    """Очищает устаревшие записи из rate limiter (раз в 60 секунд)."""
    global LAST_BUCKET_CLEANUP
    now = time.time()
    
    if now - LAST_BUCKET_CLEANUP > 60:
        stale_keys = [
            uid for uid, bucket in CLICK_BUCKETS.items()
            if not bucket or now - bucket[-1] > 300
        ]
        for uid in stale_keys:
            del CLICK_BUCKETS[uid]
        LAST_BUCKET_CLEANUP = now

# ==========================================
# ЭНДПОИНТЫ
# ==========================================
@router.get("/state")
def state(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Возвращает текущее состояние пользователя с начислением пассива."""
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    db.commit()
    return public_user(user_db)

@router.post("/click")
def click(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Обработка клика с rate limiting и начислением пассива."""
    clean_click_buckets()
    
    now = time.time()
    bucket = CLICK_BUCKETS.setdefault(user.id, [])
    bucket[:] = [t for t in bucket if now - t < 1.0]
    
    if len(bucket) >= CLICK_RATE_LIMIT:
        raise HTTPException(
            status_code=429,
            detail="Слишком много кликов. Подождите секунду."
        )
    bucket.append(now)

    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    power = max(user_db.click_power or 1, 1)
    mult = max(user_db.multiplier or 1.0, 1.0)
    
    # ИСПРАВЛЕНО: round() вместо int() для предотвращения потери монет
    gain = round(power * mult)
    
    user_db.balance += gain
    user_db.total_clicks += 1
    
    db.commit()
    return {"balance": user_db.balance, "gain": gain}

@router.post("/buy/{key}")
def buy(key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Покупка апгрейда с проверкой уровня и баланса."""
    if key not in UPGRADES:
        raise HTTPException(status_code=404, detail="Такого апгрейда не существует")
    
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    current_level = upgrade_level(user_db, key)
    max_level = UPGRADES[key]["max_level"]
    if current_level >= max_level:
        raise HTTPException(
            status_code=400,
            detail=f"Максимальный уровень апгрейда достигнут ({max_level})"
        )
    
    cost = upgrade_cost(user_db, key)
    if user_db.balance < cost:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно средств. Нужно {cost} 🪙"
        )
    
    user_db.balance -= cost
    
    # ИСПРАВЛЕНО: Округление float-значений для предотвращения накопления ошибок (Float Drift)
    if key == "click_power":
        user_db.click_power += 1
    elif key == "auto_rate":
        user_db.auto_rate = round(user_db.auto_rate + UPGRADES[key]["step"], 4)
    elif key == "multiplier":
        user_db.multiplier = round(user_db.multiplier + UPGRADES[key]["step"], 4)
    
    db.commit()
    
    return {
        "user": public_user(user_db),
        "next_cost": upgrade_cost(user_db, key)
    }
