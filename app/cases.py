from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from .db import get_db
from .models import User, InventoryItem, CaseOpen
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
    if case_id not in CASES: raise HTTPException(404, "Нет кейса")
    return get_case_preview(case_id)

@router.post("/open_multi/{case_id}")
async def open_multi(case_id: str, data: OpenMulti, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if case_id not in CASES: raise HTTPException(404, "Нет кейса")
    if data.count < 1 or data.count > 10: raise HTTPException(400, "От 1 до 10")
    
    case = CASES[case_id]
    total_price = case["price"] * data.count
    
    apply_passive(user, db)
    if user.balance < total_price: raise HTTPException(400, "Недостаточно копыт")

    user.balance -= total_price
    results = []
    
    # Открываем нужное количество
    for _ in range(data.count):
        user.nonce += 1
        server_seed = gen_seed()
        client_seed = gen_seed()
        ticket = roll_ticket(server_seed, client_seed, user.nonce)
        rarity = pick_rarity(case_id, ticket)
        pony_id, price, color = pick_pony(rarity)

        db.add(InventoryItem(user_id=user.id, pony_id=pony_id, rarity=rarity, price=price, color=color))
        db.add(CaseOpen(user_id=user.id, case_id=case_id, pony_id=pony_id, rarity=rarity, price=case["price"], server_seed=server_seed, client_seed=client_seed, nonce=user.nonce, ticket=ticket))
        
        results.append({"pony_id": pony_id, "rarity": rarity, "price": price, "color": color})
        
        # Отправляем только самый дорогой дроп в Live-ленту, чтобы не спамить
        if price > 5000:
            await broadcast_drop(user.username, user.avatar, pony_id, price, color, f"Кейс: {case['name']}")

    db.commit()
    
    return {"results": results, "balance": user.balance}
