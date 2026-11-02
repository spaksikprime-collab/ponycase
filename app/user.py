from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
import base64
from datetime import datetime
from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .clicker import apply_passive, public_user
from .games import RARITY_BY_ID, CASES

router = APIRouter()

# Вспомогательная функция для получения любимого кейса
def get_favorite_case(user_id: int, db: Session) -> str:
    favorite = db.query(CaseOpen.case_id, func.count(CaseOpen.case_id)) \
        .filter(CaseOpen.user_id == user_id) \
        .group_by(CaseOpen.case_id) \
        .order_by(func.count(CaseOpen.case_id).desc()) \
        .first()
    
    if favorite and favorite[0] in CASES:
        return CASES[favorite[0]]["name"]
    return "Нет"

# 1. ПОЛУЧЕНИЕ СВОЕГО ПРОФИЛЯ
@router.get("/profile")
def get_my_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user, db)
    
    inventory = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    
    best_drop_data = None
    if user.best_drop_price > 0:
        best_drop_data = {
            "name": user.best_drop_name,
            "price": user.best_drop_price
        }

    inventory_list = []
    for item in inventory:
        inventory_list.append({
            "id": item.id,
            "name": item.pony_id,
            "rarity": item.rarity,
            "price": item.price,
            "color": item.color
        })

    return {
        "user": public_user(user),
        "stats": {
            "total_clicks": user.total_clicks,
            "cases_opened": opened_cases
        },
        "best_drop": best_drop_data,
        "fav_case": get_favorite_case(user.id, db),
        "inventory": inventory_list
    }

# 2. ИСТОРИЯ ИГР (КЕЙСЫ И АПГРЕЙДЫ)
@router.get("/history")
def get_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    history = db.query(GameHistory) \
        .filter(GameHistory.user_id == user.id) \
        .order_by(GameHistory.created_at.desc()) \
        .limit(50) \
        .all()
    
    result = []
    for h in history:
        result.append({
            "game": h.game_type, 
            "item": h.item_name,
            "price": h.price,
            "result": h.result_text,
            "date": h.created_at.strftime("%d.%m %H:%M")
        })
    return result

# 3. ПУБЛИЧНЫЙ ПРОФИЛЬ (ДЛЯ ЧАТА И ЛЕНТЫ)
@router.get("/public/by_name/{username}")
def get_public_by_name(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(404, "Игрок не найден")
    
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    
    best_drop_data = None
    if user.best_drop_price > 0:
        best_drop_data = {
            "name": user.best_drop_name,
            "price": user.best_drop_price
        }
    
    return {
        "username": user.username,
        "avatar": user.avatar,
        "total_clicks": user.total_clicks,
        "cases_opened": opened_cases,
        "best_drop": best_drop_data,
        "fav_case": get_favorite_case(user.id, db)
    }

# 4. ТОП ИГРОКОВ ПО БАЛАНСУ
@router.get("/leaderboard")
def get_leaderboard(db: Session = Depends(get_db)):
    top_users = db.query(User).order_by(User.balance.desc()).limit(10).all()
    
    result = []
    for index, u in enumerate(top_users):
        result.append({
            "rank": index + 1,
            "username": u.username,
            "avatar": u.avatar,
            "balance": u.balance
        })
    return result

# 5. ЕЖЕЧАСНОЙ БОНУС
@router.post("/bonus")
def claim_bonus(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.last_bonus and (datetime.utcnow() - user.last_bonus).total_seconds() < 3600:
        raise HTTPException(400, "Бонус будет доступен позже!")
    
    user.balance += 500
    user.last_bonus = datetime.utcnow()
    db.commit()
    
    return {"success": True, "balance": user.balance}

# 6. ПРОДАЖА ОДНОГО ПРЕДМЕТА
@router.post("/inventory/sell/{item_id}")
def sell_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Предмет не найден")
    
    apply_passive(user, db)
    user.balance += item.price
    
    db.delete(item)
    db.commit()
    
    return {"success": True, "balance": user.balance}

# 7. ПРОДАЖА ВСЕГО ИНВЕНТАРЯ (ИСПРАВЛЕНО)
@router.post("/inventory/sell_all")
def sell_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user, db)
    
    # Получаем все предметы игрока
    items = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    
    if not items:
        return {"success": True, "balance": user.balance, "gained": 0}
        
    total_gained = sum(item.price for item in items)
    user.balance += total_gained
    
    # Жесткое удаление всех предметов из базы
    for item in items:
        db.delete(item)
        
    db.commit()
    
    return {"success": True, "balance": user.balance, "gained": total_gained}

# 8. ЗАГРУЗКА АВАТАРКИ
@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise HTTPException(400, "Файл слишком большой (макс 5МБ)")
    
    b64_str = base64.b64encode(contents).decode('utf-8')
    user.avatar = f"data:{file.content_type};base64,{b64_str}"
    
    db.commit()
    
    return {"success": True, "avatar": user.avatar}
