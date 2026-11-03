import hmac
import hashlib
import secrets
import random
from typing import Tuple, List, Dict

PONY_DB = {
    "common": ["Applejack", "Fluttershy", "Pinkie Pie", "Rarity", "Rainbow Dash", "Twilight Sparkle"],
    "uncommon": ["Apple Bloom", "Sweetie Belle", "Scootaloo", "Babs Seed", "Silver Spoon", "Diamond Tiara"],
    "rare": ["Princess Cadance", "Shining Armor", "Starlight Glimmer", "Sunset Shimmer", "Trixie", "Discord"],
    "epic": ["Princess Celestia", "Princess Luna", "Queen Chrysalis", "King Sombra", "Cozy Glow", "Lord Tirek"],
    "legendary": ["Nightmare Moon", "Daybreaker", "Flurry Heart", "Grogar", "The Pony of Shadows"],
    "mythic": ["Cosmic Entity", "Golden Hooves", "Shadow Pony", "Eternal Chaos"],
    "celestial": ["The Creator", "Goddess of Sun", "Goddess of Moon", "Alpha Pony"]
}

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

def gen_seed() -> str:
    return secrets.token_hex(32)

def roll_ticket(server_seed: str, client_seed: str, nonce: int) -> int:
    msg = f"{client_seed}:{nonce}".encode()
    digest = hmac.new(server_seed.encode(), msg, hashlib.sha256).hexdigest()
    return int(digest[:8], 16) % 1_000_000

def pick_rarity(case_id: str, ticket: int) -> str:
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
    base_mult = RARITY_BY_ID[rarity][3]
    pony_name = random.choice(PONY_DB.get(rarity, ["Unknown Pony"]))
    price = int(100 * base_mult * random.uniform(0.5, 1.5))
    color = RARITY_BY_ID[rarity][4]
    return pony_name, price, color

def get_case_preview(case_id: str) -> List[Dict]:
    weights = CASES[case_id]["weights"]
    total_weight = sum(weights.values())
    preview = []
    
    for rarity, weight in weights.items():
        chance = (weight / total_weight) * 100
        ponies = PONY_DB.get(rarity, ["Unknown"])
        sample_ponies = random.sample(ponies, min(2, len(ponies)))
        
        for p in sample_ponies:
            base_mult = RARITY_BY_ID[rarity][3]
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
            
    return sorted(preview, key=lambda x: x["price"], reverse=True)
