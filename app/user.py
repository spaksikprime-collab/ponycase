import base64
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import Field, BaseModel
from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .clicker import apply_passive

router = APIRouter()
logger = logging.getLogger(__name__)

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
# Максимальный размер аватарки (200 КБ)
MAX_AVATAR_SIZE = 200 * 1024
# Разрешенные MIME-типы для аватарок
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
# Максимальный лимит пагинации (защита от DoS)
MAX_PAGINATION_LIMIT = 100
# Сумма бонуса
BONUS_AMOUNT = 500
# Кулдаун бонуса в секундах (1 час)
BONUS_COOLDOWN_SECONDS = 3600

# ==========================================
# МОДЕЛИ ЗАПРОСОВ
# ==========================================
class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1, description="Номер страницы")
    limit: int = Field(default=10, ge=1, le=MAX_PAGINATION_LIMIT, description="Размер страницы")

# ==========================================
# ПРОФИЛЬ И СТАТИСТИКА
# ==========================================

@router.get("/profile")
def get_my_profile(
    page: int = 1,
    limit: int = 10,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Возвращает полный профиль пользователя с инвентарем и статистикой.
    Инвентарь сортируется по цене (дорогие сверху).
    """
    # Валидация пагинации
    if page < 1:
        page = 1
    if limit < 1 or limit > MAX_PAGINATION_LIMIT:
        limit = min(max(limit, 1), MAX_PAGINATION_LIMIT)
    
    # Блокируем пользователя для корректного начисления пассива
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    db.commit()  # Сохраняем начисленный пассив
    
    # Пагинация инвентаря
    skip = (page - 1) * limit
    inv_query = db.query(InventoryItem).filter(InventoryItem.user_id == user_db.id)
    total_items = inv_query.count()
    
    # Сортируем по цене (самые дорогие сверху)
    inventory = inv_query.order_by(InventoryItem.price.desc()).offset(skip).limit(limit).all()
    
    # Считаем открытые кейсы
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user_db.id).count()
    
    # Лучший дроп
    best_drop = None
    if user_db.best_drop_price > 0 and user_db.best_drop_name:
        best_drop = {
            "name": user_db.best_drop_name,
            "price": user_db.best_drop_price
        }
    
    # Форматируем дату регистрации
    created_at_str = "Неизвестно"
    if user_db.created_at:
        try:
            created_at_str = user_db.created_at.strftime("%d.%m.%Y")
        except Exception:
            created_at_str = "Неизвестно"
    
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
    page: int = 1,
    limit: int = 10,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Возвращает историю игр пользователя с пагинацией.
    Сортировка: новые записи сверху.
    """
    # Валидация пагинации
    if page < 1:
        page = 1
    if limit < 1 or limit > MAX_PAGINATION_LIMIT:
        limit = min(max(limit, 1), MAX_PAGINATION_LIMIT)
    
    skip = (page - 1) * limit
    hist_query = db.query(GameHistory).filter(GameHistory.user_id == user.id)
    total = hist_query.count()
    
    # Сортируем по дате (сначала новые)
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
    """
    Возвращает топ-10 игроков по балансу.
    Благодаря индексу на balance работает моментально.
    """
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
    """
    Публичный профиль любого пользователя по никнейму.
    Не показывает баланс и приватные данные.
    """
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    
    best_drop = None
    if user.best_drop_price > 0 and user.best_drop_name:
        best_drop = {
            "name": user.best_drop_name,
            "price": user.best_drop_price
        }
    
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
    """
    Ежедневный бонус +500 🪙 с кулдауном 1 час.
    Защита от спама через with_for_update().
    """
    # Блокируем пользователя
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    # Проверяем кулдаун
    now = datetime.now(timezone.utc)
    if user_db.last_bonus:
        last_bonus = user_db.last_bonus
        # Приводим к timezone-aware, если нужно
        if last_bonus.tzinfo is None:
            last_bonus = last_bonus.replace(tzinfo=timezone.utc)
        
        elapsed = (now - last_bonus).total_seconds()
        if elapsed < BONUS_COOLDOWN_SECONDS:
            remaining = int(BONUS_COOLDOWN_SECONDS - elapsed)
            minutes = remaining // 60
            seconds = remaining % 60
            raise HTTPException(
                status_code=400,
                detail=f"Бонус будет доступен через {minutes}м {seconds}с"
            )
    
    # Начисляем бонус
    user_db.balance += BONUS_AMOUNT
    user_db.last_bonus = now
    db.commit()
    
    logger.info(f"🎁 {user_db.username} claimed bonus (+{BONUS_AMOUNT}🪙)")
    
    return {
        "success": True,
        "balance": user_db.balance,
        "bonus": BONUS_AMOUNT,
        "message": f"Получено {BONUS_AMOUNT} 🪙!"
    }

# ==========================================
# ИНВЕНТАРЬ: ПРОДАЖА
# ==========================================

@router.post("/inventory/sell/{item_id}")
def sell_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Продает один предмет из инвентаря."""
    # Ищем предмет и проверяем владельца
    item = db.get(InventoryItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Предмет не найдено в вашем инвентаре")
    
    # Блокируем пользователя
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    # Начисляем деньги и удаляем предмет
    user_db.balance += item.price
    db.delete(item)
    db.commit()
    
    logger.info(f"💰 {user_db.username} sold {item.pony_id} for {item.price}🪙")
    
    return {
        "success": True,
        "balance": user_db.balance,
        "sold": {
            "name": item.pony_id,
            "price": item.price
        }
    }

@router.post("/inventory/sell_all")
def sell_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """
    Продает ВСЕ предметы из инвентаря.
    ОПТИМИЗИРОВАНО: Использует bulk-операции вместо цикла.
    """
    # Блокируем пользователя
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    apply_passive(user_db, db)
    
    # Считаем общую сумму (один запрос)
    total_gained = db.query(InventoryItem).filter(
        InventoryItem.user_id == user_db.id
    ).with_entities(
        db.query(InventoryItem.price).filter(InventoryItem.user_id == user_db.id)
    ).scalar() or 0
    
    # Более эффективный способ подсчета суммы
    from sqlalchemy import func
    total_gained = db.query(func.coalesce(func.sum(InventoryItem.price), 0)).filter(
        InventoryItem.user_id == user_db.id
    ).scalar()
    
    if total_gained == 0:
        raise HTTPException(status_code=400, detail="Инвентарь пуст")
    
    # Начисляем деньги
    user_db.balance += total_gained
    
    # BULK DELETE — один запрос вместо N (КРИТИЧЕСКИ ВАЖНО для производительности!)
    deleted_count = db.query(InventoryItem).filter(
        InventoryItem.user_id == user_db.id
    ).delete(synchronize_session=False)
    
    db.commit()
    
    logger.info(f"💰 {user_db.username} sold ALL inventory ({deleted_count} items, {total_gained}🪙)")
    
    return {
        "success": True,
        "balance": user_db.balance,
        "gained": total_gained,
        "items_sold": deleted_count
    }

# ==========================================
# АВАТАР
# ==========================================

@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Загружает новую аватарку пользователя.
    Защита: проверка MIME-типа, размера и конвертация в base64.
    """
    # Проверка MIME-типа (защита от загрузки скриптов)
    if not file.content_type or file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Недопустимый формат. Разрешены: {', '.join(ALLOWED_AVATAR_TYPES)}"
        )
    
    # Читаем содержимое
    contents = await file.read()
    
    # Проверка размера
    if len(contents) > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Максимальный размер фото — {MAX_AVATAR_SIZE // 1024}КБ"
        )
    
    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Файл пустой")
    
    # Проверяем магические байты (дополнительная защита от подделки MIME)
    magic_bytes = contents[:4]
    valid_magic = (
        magic_bytes.startswith(b'\xff\xd8\xff') or  # JPEG
        magic_bytes.startswith(b'\x89PNG') or       # PNG
        magic_bytes.startswith(b'GIF8') or          # GIF
        magic_bytes.startswith(b'RIFF')             # WEBP
    )
    if not valid_magic:
        raise HTTPException(
            status_code=400,
            detail="Файл поврежден или не является изображением"
        )
    
    # Кодируем в base64
    b64_str = base64.b64encode(contents).decode('utf-8')
    avatar_data = f"data:{file.content_type};base64,{b64_str}"
    
    # Сохраняем в БД
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    user_db.avatar = avatar_data
    db.commit()
    
    logger.info(f"🖼️ {user_db.username} updated avatar ({len(contents)} bytes)")
    
    return {
        "success": True,
        "avatar": avatar_data,
        "size": len(contents)
    }
