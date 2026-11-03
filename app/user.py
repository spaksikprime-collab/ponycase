import base64
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy import func

from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .clicker import apply_passive

router = APIRouter()
logger = logging.getLogger(__name__)

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
MAX_AVATAR_SIZE = 200 * 1024  # 200 КБ
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_PAGINATION_LIMIT = 100
BONUS_AMOUNT = 500
BONUS_COOLDOWN_SECONDS = 3600  # 1 час

# ==========================================
# ПРОФИЛЬ И СТАТИСТИКА
# ==========================================
@router.get("/profile")
def get_my_profile(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=MAX_PAGINATION_LIMIT),
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Возвращает полный профиль пользователя с инвентарем и статистикой."""
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    db.commit()
    
    skip = (page - 1) * limit
    inv_query = db.query(InventoryItem).filter(InventoryItem.user_id == user_db.id)
    total_items = inv_query.count()
    
    inventory = inv_query.order_by(InventoryItem.price.desc()).offset(skip).limit(limit).all()
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user_db.id).count()
    
    best_drop = None
    if user_db.best_drop_price > 0 and user_db.best_drop_name:
        best_drop = {"name": user_db.best_drop_name, "price": user_db.best_drop_price}
    
    created_at_str = "Неизвестно"
    if user_db.created_at:
        try:
            created_at_str = user_db.created_at.strftime("%d.%m.%Y")
        except Exception:
            pass
    
    return {
        "user": {
            "id": user_db.id,
            "username": user_db.username,
            "balance": user_db.balance,
            "avatar": user_db.avatar,
            "created_at": created_at_str
        },
        "stats": {
            "total_clicks": user_db.total_clicks,
            "cases_opened": opened_cases
        },
        "best_drop": best_drop,
        "inventory": [
            {
                "id": i.id,
                "name": i.pony_id,
                "rarity": i.rarity,
                "price": i.price,
                "color": i.color
            }
            for i in inventory
        ],
        "pagination": {
            "total": total_items,
            "page": page,
            "limit": limit,
            "pages": max(1, (total_items + limit - 1) // limit)
        }
    }

# ==========================================
# ИСТОРИЯ ИГР
# ==========================================
@router.get("/history")
def get_history(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=MAX_PAGINATION_LIMIT),
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Возвращает историю игр пользователя с пагинацией."""
    skip = (page - 1) * limit
    hist_query = db.query(GameHistory).filter(GameHistory.user_id == user.id)
    total = hist_query.count()
    
    history = hist_query.order_by(GameHistory.created_at.desc()).offset(skip).limit(limit).all()
    
    return {
        "history": [
            {
                "game": h.game_type,
                "item": h.item_name,
                "price": h.price,
                "result": h.result_text or "",
                "date": h.created_at.strftime("%d.%m %H:%M") if h.created_at else ""
            }
            for h in history
        ],
        "pagination": {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": max(1, (total + limit - 1) // limit)
        }
    }

# ==========================================
# ТОП ИГРОКОВ
# ==========================================
@router.get("/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    """Возвращает топ-10 игроков по балансу."""
    top_users = db.query(User).order_by(User.balance.desc()).limit(10).all()
    return [
        {
            "rank": i + 1,
            "username": u.username,
            "avatar": u.avatar,
            "balance": u.balance
        }
        for i, u in enumerate(top_users)
    ]

# ==========================================
# ПУБЛИЧНЫЙ ПРОФИЛЬ
# ==========================================
@router.get("/public/by_name/{username}")
def get_public_profile(username: str, db: Session = Depends(get_db)):
    """Публичный профиль любого пользователя по никнейму."""
    user = db.query(User).filter(User.username == username.lower()).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    best_drop = None
    if user.best_drop_price > 0 and user.best_drop_name:
        best_drop = {"name": user.best_drop_name, "price": user.best_drop_price}
    
    return {
        "username": user.username,
        "avatar": user.avatar,
        "total_clicks": user.total_clicks,
        "cases_opened": opened_cases,
        "best_drop": best_drop,
        "created_at": user.created_at.strftime("%d.%m.%Y") if user.created_at else "Неизвестно"
    }

# ==========================================
# БОНУСЫ
# ==========================================
@router.post("/bonus")
def claim_bonus(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Ежедневный бонус с кулдауном 1 час."""
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    now = datetime.now(timezone.utc)
    if user_db.last_bonus:
        last_bonus = user_db.last_bonus
        if last_bonus.tzinfo is None:
            last_bonus = last_bonus.replace(tzinfo=timezone.utc)
        
        elapsed = (now - last_bonus).total_seconds()
        if elapsed < BONUS_COOLDOWN_SECONDS:
            remaining = int(BONUS_COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=400,
                detail=f"Бонус будет доступен через {remaining // 60}м {remaining % 60}с"
            )
    
    user_db.balance += BONUS_AMOUNT
    user_db.last_bonus = now
    db.commit()
    
    logger.info(f"🎁 {user_db.username} claimed bonus (+{BONUS_AMOUNT}🪙)")
    return {"success": True, "balance": user_db.balance, "bonus": BONUS_AMOUNT}

# ==========================================
# ИНВЕНТАРЬ: ПРОДАЖА
# ==========================================
@router.post("/inventory/sell/{item_id}")
def sell_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Продает один предмет из инвентаря."""
    item = db.get(InventoryItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Предмет не найден в вашем инвентаре")
    
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    user_db.balance += item.price
    db.delete(item)
    db.commit()
    
    logger.info(f"💰 {user_db.username} sold {item.pony_id} for {item.price}🪙")
    return {"success": True, "balance": user_db.balance}

@router.post("/inventory/sell_all")
def sell_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Продает ВСЕ предметы из инвентаря (Оптимизировано через bulk-операции)."""
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    # Считаем общую сумму одним эффективным запросом
    total_gained = db.query(func.coalesce(func.sum(InventoryItem.price), 0)).filter(
        InventoryItem.user_id == user_db.id
    ).scalar()
    
    if total_gained == 0:
        raise HTTPException(status_code=400, detail="Инвентарь пуст")
    
    user_db.balance += total_gained
    
    # BULK DELETE — один запрос вместо N
    deleted_count = db.query(InventoryItem).filter(
        InventoryItem.user_id == user_db.id
    ).delete(synchronize_session=False)
    
    db.commit()
    
    logger.info(f"💰 {user_db.username} sold ALL inventory ({deleted_count} items, {total_gained}🪙)")
    return {"success": True, "balance": user_db.balance, "gained": total_gained, "items_sold": deleted_count}

# ==========================================
# АВАТАР
# ==========================================
@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """Загружает новую аватарку пользователя с проверкой магических байтов."""
    if not file.content_type or file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=400, detail=f"Недопустимый формат. Разрешены: {', '.join(ALLOWED_AVATAR_TYPES)}")
    
    contents = await file.read()
    
    if len(contents) > MAX_AVATAR_SIZE:
        raise HTTPException(status_code=400, detail=f"Максимальный размер фото — {MAX_AVATAR_SIZE // 1024}КБ")
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Файл пустой")
    
    # Проверка магических байтов (защита от подделки MIME и загрузки скриптов)
    magic_bytes = contents[:4]
    valid_magic = (
        magic_bytes.startswith(b'\xff\xd8\xff') or  # JPEG
        magic_bytes.startswith(b'\x89PNG') or       # PNG
        magic_bytes.startswith(b'GIF8') or          # GIF
        magic_bytes.startswith(b'RIFF')             # WEBP
    )
    if not valid_magic:
        raise HTTPException(status_code=400, detail="Файл поврежден или не является изображением")
    
    b64_str = base64.b64encode(contents).decode('utf-8')
    avatar_data = f"data:{file.content_type};base64,{b64_str}"
    
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    user_db.avatar = avatar_data
    db.commit()
    
    logger.info(f"🖼️ {user_db.username} updated avatar ({len(contents)} bytes)")
    return {"success": True, "avatar": avatar_data, "size": len(contents)}
