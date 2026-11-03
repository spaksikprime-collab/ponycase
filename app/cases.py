from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
import asyncio
from .db import get_db
from .models import User, InventoryItem, CaseOpen, GameHistory
from .auth import current_user
from .games import CASES, gen_seed, roll_ticket, pick_rarity, pick_pony, get_case_preview
from .clicker import apply_passive
from .ws import broadcast_drop

router = APIRouter()

class OpenMulti(BaseModel):
    count: int

@router.get("/list")
def list_cases():
    return [{"id": k, "name": v["name"], "price": v["price"]} for k, v in CASES.items()]

@router.get("/preview/{case_id}")
def preview_case(case_id: str):
    if case_id not in CASES: 
        raise HTTPException(404, "Кейс не найден")
    return get_case_preview(case_id)

@router.post("/open_multi/{case_id}")
async def open_multi(case_id: str, data: OpenMulti, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if case_id not in CASES: 
        raise HTTPException(404, "Кейс не найден")
    
    if data.count < 1 or data.count > 10: 
        raise HTTPException(400, "Можно открывать от 1 до 10 кейсов за раз")
    
    # Блокируем юзера, чтобы не было двойных списаний при спаме
    user_db = db.query(User).filter(User.id == user.id).with_for_update().first()
    
    case = CASES[case_id]
    total_price = case["price"] * data.count
    
    apply_passive(user_db, db)
    
    if user_db.balance < total_price: 
        raise HTTPException(400, "Недостаточно копыт для открытия")

    user_db.balance -= total_price
    results = []
    
    try:
        for _ in range(data.count):
            user_db.nonce += 1
            server_seed = gen_seed()
            client_seed = gen_seed()
            ticket = roll_ticket(server_seed, client_seed, user_db.nonce)
            rarity = pick_rarity(case_id, ticket)
            pony_id, price, color = pick_pony(rarity)

            item = InventoryItem(
                user_id=user_db.id, 
                pony_id=pony_id, 
                rarity=rarity, 
                price=price, 
                color=color
            )
            db.add(item)
            db.flush() 
            
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

            db.add(GameHistory(
                user_id=user_db.id, 
                game_type="Кейс", 
                item_name=pony_id, 
                price=price, 
                result_text=f"Открыл {case['name']}"
            ))
            
            if price > user_db.best_drop_price:
                user_db.best_drop_price = price
                user_db.best_drop_name = pony_id
            
            results.append({
                "id": item.id, 
                "pony_id": pony_id, 
                "rarity": rarity, 
                "price": price, 
                "color": color
            })
            
            if price > 5000:
                # Отправляем асинхронно, не блокируя ответ игроку
                asyncio.create_task(broadcast_drop(
                    user_db.username, 
                    user_db.avatar, 
                    pony_id, 
                    price, 
                    color, 
                    f"Кейс: {case['name']}"
                ))

        db.commit()
        return {"results": results, "balance": user_db.balance}
        
    except Exception as e:
        db.rollback()
        raise HTTPException(500, "Ошибка при открытии. Деньги возвращены.")
