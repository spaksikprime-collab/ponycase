from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
import base64
from .db import get_db
from .models import User, InventoryItem, CaseOpen
from .auth import current_user
from .clicker import apply_passive, public_user
from .games import RARITY_BY_ID

router = APIRouter()

@router.get("/profile")
def get_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    apply_passive(user); db.commit()
    inventory = db.query(InventoryItem).filter(InventoryItem.user_id == user.id).all()
    opened_cases = db.query(CaseOpen).filter(CaseOpen.user_id == user.id).count()
    
    return {
        "user": public_user(user),
        "stats": {"total_clicks": user.total_clicks, "cases_opened": opened_cases},
        "inventory": [{"id": i.id, "name": i.pony_id, "rarity": i.rarity, "price": i.price, "color": RARITY_BY_ID.get(i.rarity, ("","","","","#fff"))[4]} for i in inventory]
    }

@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024: # Максимум 2МБ
        raise HTTPException(400, "Файл слишком большой (макс 2МБ)")
    
    # Сохраняем как base64 строку прямо в БД (чтобы не терялось при перезапуске ZevCloud)
    b64_str = base64.b64encode(contents).decode('utf-8')
    mime_type = file.content_type or "image/jpeg"
    user.avatar = f"data:{mime_type};base64,{b64_str}"
    db.commit()
    return {"success": True, "avatar": user.avatar}
