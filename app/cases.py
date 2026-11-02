from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, InventoryItem, CaseOpen
from .auth import current_user
from .games import CASES, gen_seed, roll_ticket, pick_rarity, pick_pony, get_case_preview
from .clicker import apply_passive
from .ws import broadcast_drop

router = APIRouter()

@router.get("/list")
def list_cases():
    return [{"id": k, "name": v["name"], "price": v["price"]} for k, v in CASES.items()]

@router.get("/preview/{case_id}")
def preview_case(case_id: str):
    if case_id not in CASES:
        raise HTTPException(404, "Нет такого кейса")
    return get_case_preview(case_id)

@router.post("/open/{case_id}")
async def open_case(case_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if case_id not in CASES:
        raise HTTPException(404, "Нет такого кейса")
    case = CASES[case_id]
    
    # ИСПРАВЛЕНО: передаем db
    apply_passive(user, db)
    
    if user.balance < case["price"]:
        raise HTTPException(400, "Недостаточно копыт")

    user.balance -= case["price"]
    user.nonce += 1
    nonce = user.nonce

    server_seed = gen_seed()
    client_seed = gen_seed()
    ticket = roll_ticket(server_seed, client_seed, nonce)
    rarity = pick_rarity(case_id, ticket)
    pony_id, price, color = pick_pony(rarity)

    db.add(InventoryItem(user_id=user.id, pony_id=pony_id, rarity=rarity, price=price, color=color))
    db.add(CaseOpen(user_id=user.id, case_id=case_id, pony_id=pony_id,
                    rarity=rarity, price=case["price"], server_seed=server_seed,
                    client_seed=client_seed, nonce=nonce, ticket=ticket))
    db.commit()

    await broadcast_drop(user.username, user.avatar, pony_id, price, color, f"Кейс: {case['name']}")

    return {
        "pony_id": pony_id, "rarity": rarity, "price": price, "color": color,
        "balance": user.balance,
    }
