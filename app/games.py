import hmac
import hashlib
import secrets
import random
from typing import Tuple, List, Dict

# ==========================================
# БАЗА ПОНИ ПО РЕДКОСТЯМ
# ==========================================
PONY_DB = {
    "common": ["Applejack", "Fluttershy", "Pinkie Pie", "Rarity", "Rainbow Dash", "Twilight Sparkle"],
    "uncommon": ["Apple Bloom", "Sweetie Belle", "Scootaloo", "Babs Seed", "Silver Spoon", "Diamond Tiara"],
    "rare": ["Princess Cadance", "Shining Armor", "Starlight Glimmer", "Sunset Shimmer", "Trixie", "Discord"],
    "epic": ["Princess Celestia", "Princess Luna", "Queen Chrysalis", "King Sombra", "Cozy Glow", "Lord Tirek"],
    "legendary": ["Nightmare Moon", "Daybreaker", "Flurry Heart", "Grogar", "The Pony of Shadows"],
    "mythic": ["Cosmic Entity", "Golden Hooves", "Shadow Pony", "Eternal Chaos"],
    "celestial": ["The Creator", "Goddess of Sun", "Goddess of Moon", "Alpha Pony"]
}

# ==========================================
# РЕДКОСТИ: (id, базовая_цена, название, множитель_цены, цвет)
# ==========================================
RARITIES = [
    ("common",    500_000, "Обычная",     2, "#9ca3af"), 
    ("uncommon",  250_000, "Необычная",   5, "#4ade80"), 
    ("rare",      150_000, "Редкая",      20, "#60a5fa"), 
    ("epic",       70_000, "Эпическая",   100, "#c084fc"), 
    ("legendary",  25_000, "Легендарная", 500, "#facc15"), 
    ("mythic",      4_500, "Мифическая",  2500, "#f87171"), 
    ("celestial",     500, "Божественная", 10000, "#f43f5e"), 
]
RARITY_BY_ID = {r[0]: r for r in RARITIES}

# ==========================================
# КЕЙСЫ С ВЕСАМИ РЕДКОСТЕЙ
# ==========================================
CASES = {
    "starter":   {"name": "Стартовый",   "price": 50,
                  "weights": {"common": 650, "uncommon": 250, "rare": 80, "epic": 18, "legendary": 2}},
    "barn":      {"name": "Амбар",       "price": 250,
                  "weights": {"common": 400, "uncommon": 300, "rare": 200, "epic": 80, "legendary": 20}},
    "royal":     {"name": "Королевский", "price": 1000,
                  "weights": {"common": 300, "uncommon": 350, "rare": 250, "epic": 80, "legendary": 18, "mythic": 2}},
    "cyber":     {"name": "Кибер-Пони",  "price": 5000,
                  "weights": {"uncommon": 200, "rare": 400, "epic": 300, "legendary": 90, "mythic": 10}},
    "neon":      {"name": "Неон",        "price": 10000,
                  "weights": {"rare": 300, "epic": 400, "legendary": 200, "mythic": 90, "celestial": 10}},
    "magic":     {"name": "Магия",       "price": 15000,
                  "weights": {"rare": 200, "epic": 300, "legendary": 300, "mythic": 150, "celestial": 50}},
    "celestial": {"name": "Небесный",    "price": 25000,
                  "weights": {"rare": 200, "epic": 400, "legendary": 300, "mythic": 95, "celestial": 5}},
    "god":       {"name": "Божественный","price": 50000,
                  "weights": {"epic": 400, "legendary": 300, "mythic": 200, "celestial": 100}},
    "void":      {"name": "Пустота",     "price": 100000,
                  "weights": {"epic": 200, "legendary": 400, "mythic": 300, "celestial": 100}},
}

# ==========================================
# PROVABLY FAIR ФУНКЦИИ
# ==========================================
def gen_seed() -> str:
    """Генерирует криптографически безопасный случайный сид (64 hex символа)."""
    return secrets.token_hex(32)

def roll_ticket(server_seed: str, client_seed: str, nonce: int) -> int:
    """
    Генерирует детерминированный тикет на основе HMAC-SHA256.
    Возвращает число от 0 до 999,999.
    """
    msg = f"{client_seed}:{nonce}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).hexdigest()
    return int(digest[:8], 16) % 1_000_000

def pick_rarity(case_id: str, ticket: int) -> str:
    """Выбирает редкость на основе тикета и весов кейса."""
    weights = CASES[case_id]["weights"]
    total = sum(weights.values())
    x = ticket % total
    acc = 0
    for rarity, w in weights.items():
        acc += w
        if x < acc:
            return rarity
    return next(iter(weights))

def pick_pony(rarity: str) -> Tuple[str, int, str]:
    """
    Выбирает случайного пони из редкости и рассчитывает цену с разбросом.
    Цена варьируется от 50% до 150% от базовой (множитель * 100).
    """
    base_mult = RARITY_BY_ID[rarity][3]
    pony_name = random.choice(PONY_DB.get(rarity, ["Unknown Pony"]))
    # Разброс цены: от 50% до 150% от базовой
    price = int(100 * base_mult * random.uniform(0.5, 1.5))
    color = RARITY_BY_ID[rarity][4]
    return pony_name, price, color

# ==========================================
# ПРЕВЬЮ КЕЙСОВ (ИСПРАВЛЕНО: детерминированные цены)
# ==========================================
def get_case_preview(case_id: str) -> List[Dict]:
    """
    Возвращает стабильное превью кейса с фиксированными ценами.
    Цены не меняются при каждом запросе (в отличие от оригинала).
    Показывает по 2 примера пони из каждой редкости.
    """
    if case_id not in CASES:
        return []
        
    weights = CASES[case_id]["weights"]
    total_weight = sum(weights.values())
    preview = []
    
    for rarity, weight in weights.items():
        chance = (weight / total_weight) * 100
        ponies = PONY_DB.get(rarity, ["Unknown"])
        
        # Берем первые 2 пони из списка (детерминированно, без random)
        sample_ponies = ponies[:2] if len(ponies) >= 2 else ponies
        
        for p in sample_ponies:
            base_mult = RARITY_BY_ID[rarity][3]
            # Фиксированная цена = базовая (множитель 1.0)
            # Это среднее значение между мин (0.5) и макс (1.5)
            price = int(100 * base_mult * 1.0)
            color = RARITY_BY_ID[rarity][4]
            item_chance = chance / len(sample_ponies)
            
            preview.append({
                "name": p,
                "price": price,
                "rarity": rarity,
                "color": color,
                "chance": item_chance
            })
    
    # Сортируем по цене (дорогие сверху)
    return sorted(preview, key=lambda x: x["price"], reverse=True)

# ==========================================
# УТИЛИТЫ
# ==========================================
def get_rarity_info(rarity: str) -> Dict:
    """Возвращает полную информацию о редкости."""
    r = RARITY_BY_ID.get(rarity)
    if not r:
        return {"id": rarity, "name": "Неизвестная", "base_price": 0, "mult": 1, "color": "#fff"}
    return {
        "id": r[0],
        "name": r[2],
        "base_price": r[1],
        "mult": r[3],
        "color": r[4]
    }

def calculate_expected_value(case_id: str) -> float:
    """
    Рассчитывает математическое ожидание выигрыша для кейса.
    Полезно для баланса экономики.
    """
    if case_id not in CASES:
        return 0.0
    
    weights = CASES[case_id]["weights"]
    total_weight = sum(weights.values())
    case_price = CASES[case_id]["price"]
    
    expected_value = 0.0
    for rarity, weight in weights.items():
        rarity_chance = weight / total_weight
        base_mult = RARITY_BY_ID[rarity][3]
        # Средняя цена = базовая * 100 (среднее между 0.5 и 1.5)
        avg_price = 100 * base_mult
        expected_value += rarity_chance * avg_price
    
    # Возвращаем процент возврата (RTP - Return To Player)
    rtp = (expected_value / case_price) * 100 if case_price > 0 else 0
    return rtp
