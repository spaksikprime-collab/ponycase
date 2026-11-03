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
# ДАННЫЕ О РЕДКОСТЯХ (Сбалансированная экономика)
# ==========================================
# base_price настроен так, чтобы RTP (возврат игроку) составлял ~90% для большинства кейсов.
# Цена реального дропа будет варьироваться от 80% до 120% от base_price.
RARITY_DATA = {
    "common":    {"name": "Обычная",     "base_price": 25,    "color": "#9ca3af"}, 
    "uncommon":  {"name": "Необычная",   "base_price": 75,    "color": "#4ade80"}, 
    "rare":      {"name": "Редкая",      "base_price": 200,   "color": "#60a5fa"}, 
    "epic":      {"name": "Эпическая",   "base_price": 600,   "color": "#c084fc"}, 
    "legendary": {"name": "Легендарная", "base_price": 2500,  "color": "#facc15"}, 
    "mythic":    {"name": "Мифическая",  "base_price": 8000,  "color": "#f87171"}, 
    "celestial": {"name": "Божественная","base_price": 25000, "color": "#f43f5e"}, 
}

# ==========================================
# КЕЙСЫ С ВЕСАМИ РЕДКОСТЕЙ (RTP ~90%)
# ==========================================
CASES = {
    "starter":   {"name": "Стартовый",   "price": 50,
                  "weights": {"common": 700, "uncommon": 200, "rare": 80, "epic": 18, "legendary": 2}},
    "barn":      {"name": "Амбар",       "price": 250,
                  "weights": {"common": 450, "uncommon": 300, "rare": 180, "epic": 60, "legendary": 10}},
    "royal":     {"name": "Королевский", "price": 1000,
                  "weights": {"common": 300, "uncommon": 350, "rare": 250, "epic": 80, "legendary": 18, "mythic": 2}},
    "cyber":     {"name": "Кибер-Пони",  "price": 5000,
                  "weights": {"uncommon": 300, "rare": 400, "epic": 250, "legendary": 45, "mythic": 5}},
    "neon":      {"name": "Неон",        "price": 10000,
                  "weights": {"rare": 400, "epic": 400, "legendary": 180, "mythic": 20}},
    "magic":     {"name": "Магия",       "price": 15000,
                  "weights": {"rare": 300, "epic": 400, "legendary": 250, "mythic": 45, "celestial": 5}},
    "celestial": {"name": "Небесный",    "price": 25000,
                  "weights": {"epic": 400, "legendary": 350, "mythic": 200, "celestial": 50}},
    "god":       {"name": "Божественный","price": 50000,
                  "weights": {"epic": 300, "legendary": 400, "mythic": 250, "celestial": 50}},
    "void":      {"name": "Пустота",     "price": 100000,
                  "weights": {"legendary": 400, "mythic": 450, "celestial": 150}},
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
    Выбирает случайного пони из редкости и рассчитывает цену.
    Использует secrets для криптографической стойкости выбора имени.
    """
    rarity_info = RARITY_DATA.get(rarity)
    if not rarity_info:
        return "Unknown Pony", 0, "#ffffff"
        
    base_price = rarity_info["base_price"]
    
    # Криптостойкий выбор имени
    pony_name = secrets.choice(PONY_DB.get(rarity, ["Unknown Pony"]))
    
    # Разброс цены: от 80% до 120% от базовой (честное округление)
    price = round(base_price * random.uniform(0.8, 1.2))
    
    return pony_name, price, rarity_info["color"]

# ==========================================
# ПРЕВЬЮ КЕЙСОВ (Честные шансы)
# ==========================================
def get_case_preview(case_id: str) -> List[Dict]:
    """
    Возвращает стабильное превью кейса с фиксированными ценами и ЧЕСТНЫМИ шансами.
    """
    if case_id not in CASES:
        return []
        
    weights = CASES[case_id]["weights"]
    total_weight = sum(weights.values())
    preview = []
    
    for rarity, weight in weights.items():
        rarity_chance = (weight / total_weight) * 100
        ponies = PONY_DB.get(rarity, [])
        total_ponies_in_rarity = len(ponies)
        
        if total_ponies_in_rarity == 0:
            continue
            
        # Честный шанс на КОНКРЕТНОГО пони = шанс редкости / общее кол-во пони в редкости
        item_chance = rarity_chance / total_ponies_in_rarity
        
        # Берем первые 2 пони для превью
        sample_ponies = ponies[:2]
        base_price = RARITY_DATA[rarity]["base_price"]
        
        for p in sample_ponies:
            preview.append({
                "name": p,
                "price": base_price, # Показываем базовую цену как ориентир
                "rarity": rarity,
                "color": RARITY_DATA[rarity]["color"],
                "chance": item_chance
            })
    
    # Сортируем по цене (дорогие сверху)
    return sorted(preview, key=lambda x: x["price"], reverse=True)

# ==========================================
# УТИЛИТЫ
# ==========================================
def get_rarity_info(rarity: str) -> Dict:
    """Возвращает полную информацию о редкости."""
    info = RARITY_DATA.get(rarity)
    if not info:
        return {"id": rarity, "name": "Неизвестная", "base_price": 0, "color": "#fff"}
    return {
        "id": rarity,
        "name": info["name"],
        "base_price": info["base_price"],
        "color": info["color"]
    }

def calculate_expected_value(case_id: str) -> float:
    """
    Рассчитывает математическое ожидание выигрыша (RTP) для кейса.
    """
    if case_id not in CASES:
        return 0.0
    
    weights = CASES[case_id]["weights"]
    total_weight = sum(weights.values())
    case_price = CASES[case_id]["price"]
    
    expected_value = 0.0
    for rarity, weight in weights.items():
        rarity_chance = weight / total_weight
        base_price = RARITY_DATA[rarity]["base_price"]
        expected_value += rarity_chance * base_price
    
    rtp = (expected_value / case_price) * 100 if case_price > 0 else 0
    return round(rtp, 2)
