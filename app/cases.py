import asyncio
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .games import CASES, gen_seed, roll_ticket, pick_rarity, pick_pony, get_case_preview
from .clicker import apply_passive
from .ws import broadcast_drop

router = APIRouter()
logger = logging.getLogger(__name__)

# ==========================================
# КОНФИГУРАЦИЯ
# ==========================================
# Порог цены для broadcast дропа (только дорогие дропы показываются в ленте)
BROADCAST_PRICE_THRESHOLD = 5000

# Максимальное количество кейсов за одно открытие
MAX_CASES_PER_OPEN = 10

# Set для хранения фоновых задач (предотвращает garbage collection)
background_tasks = set()

# ==========================================
# МОДЕЛИ ЗАПРОСОВ
# ==========================================
class OpenMulti(BaseModel):
    count: int = Field(..., ge=1, le=MAX_CASES_PER_OPEN, description="Количество кейсов для открытия")
    client_seed: str = Field(
        default="",
        max_length=64,
        description="Клиентский сид для Provably Fair (опционально)"
    )

# ==========================================
# РОУТЫ
# ==========================================

@router.get("/list")
def list_cases():
    """Возвращает список всех доступных кейсов."""
    return [
        {
            "id": k,
            "name": v["name"],
            "price": v["price"]
        }
        for k, v in CASES.items()
    ]

@router.get("/preview/{case_id}")
def preview_case(case_id: str):
    """Возвращает стабильное превью содержимого кейса."""
    if case_id not in CASES:
        raise HTTPException(status_code=404, detail="Кейс не найден")
    return get_case_preview(case_id)

@router.post("/open_multi/{case_id}")
async def open_multi(
    case_id: str,
    data: OpenMulti,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    """
    Открывает несколько кейсов с настоящей Provably Fair системой.
    
    Provably Fair логика:
    - server_seed генерируется сервером
    - client_seed передается клиентом (или генерируется сервером, если не передан)
    - nonce инкрементируется для каждого открытия
    - Результат можно верифицировать через HMAC-SHA256
    """
    if case_id not in CASES:
        raise HTTPException(status_code=404, detail="Кейс не найден")
    
    # Блокируем пользователя для предотвращения race condition
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    case = CASES[case_id]
    total_price = case["price"] * data.count
    
    # Начисляем пассивный доход перед проверкой баланса
    apply_passive(user_db, db)
    
    if user_db.balance < total_price:
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно копыт. Нужно {total_price} 🪙, у вас {user_db.balance} 🪙"
        )

    # Списываем стоимость
    user_db.balance -= total_price
    
    results = []
    expensive_drops = []  # Дропы для broadcast (дорогие)
    
    try:
        for i in range(data.count):
            # Инкрементируем nonce атомарно
            user_db.nonce += 1
            
            # Генерируем server_seed
            server_seed = gen_seed()
            
            # Используем client_seed от клиента или генерируем свой
            # Это делает систему настоящей Provably Fair
            client_seed = data.client_seed if data.client_seed else gen_seed()
            
            # Рассчитываем тикет через HMAC-SHA256
            ticket = roll_ticket(server_seed, client_seed, user_db.nonce)
            
            # Выбираем редкость на основе тикета
            rarity = pick_rarity(case_id, ticket)
            
            # Выбираем конкретного пони и рассчитываем цену
            pony_id, price, color = pick_pony(rarity)

            # Создаем предмет в инвентаре
            item = InventoryItem(
                user_id=user_db.id,
                pony_id=pony_id,
                rarity=rarity,
                price=price,
                color=color
            )
            db.add(item)
            db.flush()  # Получаем ID предмета
            
            # Сохраняем данные для Provably Fair верификации
            db.add(CaseOpen(
                user_id=user_db.id,
                case_id=case_id,
                pony_id=pony_id,
                rarity=rarity,
                price=case["price"],
                server_seed=server_seed,
                client_seed=client_seed,
                nonce=user_db.nonce,
                ticket=ticket
            ))

            # Записываем в историю игр
            db.add(GameHistory(
                user_id=user_db.id,
                game_type="Кейс",
                item_name=pony_id,
                price=price,
                result_text=f"Открыл {case['name']}"
            ))
            
            # Обновляем лучший дроп
            if price > user_db.best_drop_price:
                user_db.best_drop_price = price
                user_db.best_drop_name = pony_id
            
            # Добавляем в результаты
            results.append({
                "id": item.id,
                "pony_id": pony_id,
                "rarity": rarity,
                "price": price,
                "color": color,
                "server_seed": server_seed,  # Для верификации
                "client_seed": client_seed,
                "nonce": user_db.nonce,
                "ticket": ticket
            })
            
            # Собираем дорогие дропы для broadcast
            if price >= BROADCAST_PRICE_THRESHOLD:
                expensive_drops.append({
                    "username": user_db.username,
                    "avatar": user_db.avatar,
                    "pony_id": pony_id,
                    "price": price,
                    "color": color,
                    "source": f"Кейс: {case['name']}"
                })

        # Коммитим все изменения атомарно
        db.commit()
        
        # Запускаем broadcast для дорогих дропов в фоне
        for drop in expensive_drops:
            task = asyncio.create_task(
                broadcast_drop(
                    drop["username"],
                    drop["avatar"],
                    drop["pony_id"],
                    drop["price"],
                    drop["color"],
                    drop["source"]
                )
            )
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        
        logger.info(
            f"📦 {user_db.username} opened {data.count}x {case['name']} "
            f"(total: {total_price}🪙, expensive drops: {len(expensive_drops)})"
        )
        
        return {
            "results": results,
            "balance": user_db.balance,
            "provably_fair": {
                "server_seed": server_seed,
                "client_seed": client_seed,
                "nonce": user_db.nonce
            }
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error opening cases for {user_db.username}: {e}")
        raise HTTPException(
            status_code=500,
            detail="Ошибка при открытии кейсов. Деньги возвращены."
        )

# ==========================================
# УТИЛИТЫ
# ==========================================

@router.get("/verify/{case_open_id}")
def verify_case_open(case_open_id: int, db: Session = Depends(get_db)):
    """
    Публичная верификация открытия кейса для Provably Fair.
    Любой игрок может проверить, что результат был честным.
    """
    case_open = db.get(CaseOpen, case_open_id)
    if not case_open:
        raise HTTPException(status_code=404, detail="Открытие кейса не найдено")
    
    # Пересчитываем тикет для верификации
    recalculated_ticket = roll_ticket(
        case_open.server_seed,
        case_open.client_seed,
        case_open.nonce
    )
    
    # Проверяем, что тикет совпадает
    is_valid = recalculated_ticket == case_open.ticket
    
    return {
        "valid": is_valid,
        "case_open": {
            "id": case_open.id,
            "user_id": case_open.user_id,
            "case_id": case_open.case_id,
            "pony_id": case_open.pony_id,
            "rarity": case_open.rarity,
            "price": case_open.price,
            "server_seed": case_open.server_seed,
            "client_seed": case_open.client_seed,
            "nonce": case_open.nonce,
            "ticket": case_open.ticket,
            "recalculated_ticket": recalculated_ticket,
            "created_at": case_open.created_at.isoformat()
        }
    }
