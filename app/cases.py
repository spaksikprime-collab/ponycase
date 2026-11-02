from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, InventoryItem, CaseOpen
from .auth import current_user
from .games import CASES, gen_seed, roll_ticket, pick_rarity, pick_pony
from .clicker import apply_passive
from .ws import broadcast_drop

router = APIRouter()

@router.get("/list")
def list_cases():
    return [{"id": k, "name": v["name"], "price": v["price"]} for k, v in CASES.items()]

@router.post("/open/{case_id}")
async def open_case(case_id: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if case_id not in CASES:
        raise HTTPException(404, "Нет такого кейса")
    case = CASES[case_id]
    apply_passive(user)
    if user.balance < case["price"]:
        raise HTTPException(400, "Недостаточно копыт")

    user.balance -= case["price"]
    user.nonce += 1
    nonce = user.nonce

    server_seed = gen_seed()
    client_seed = gen_seed()
    ticket = roll_ticket(server_seed, client_seed, nonce)
    rarity = pick_rarity(case_id, ticket)
    pony_id, price = pick_pony(rarity)

    db.add(InventoryItem(user_id=user.id, pony_id=pony_id, rarity=rarity, price=price))
    db.add(CaseOpen(user_id=user.id, case_id=case_id, pony_id=pony_id,
                    rarity=rarity, price=case["price"], server_seed=server_seed,
                    client_seed=client_seed, nonce=nonce, ticket=ticket))
    db.commit()

    await broadcast_drop(user.username, pony_id, rarity, price)

    return {
        "pony_id": pony_id, "rarity": rarity, "price": price,
        "balance": user.balance,
        "fair": {"server_seed": server_seed, "client_seed": client_seed,
                 "nonce": nonce, "ticket": ticket},
    }

@router.post("/sell/{item_id}")
def sell(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(InventoryItem, item_id)
    if not item or item.user_id != user.id:
        raise HTTPException(404, "Предмет не найден")
    apply_passive(user)
    user.balance += item.price
    db.delete(item); db.commit()
    return {"balance": user.balance, "sold_for": item.price}
