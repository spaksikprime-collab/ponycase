import hmac, hashlib, secrets, random

# База пони для превью
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
    ("common",    500_000, "Обычная",     1, "#9ca3af"), 
    ("uncommon",  250_000, "Необычная",   3, "#4ade80"), 
    ("rare",      150_000, "Редкая",      10, "#60a5fa"), 
    ("epic",       70_000, "Эпическая",   50, "#c084fc"), 
    ("legendary",  25_000, "Легендарная", 250, "#facc15"), 
    ("mythic",      4_500, "Мифическая",  2000, "#f87171"), 
    ("celestial",     500, "Божественная", 50000, "#f43f5e"), 
]
RARITY_BY_ID = {r[0]: r for r in RARITIES}

CASES = {
    "starter":   {"name": "Стартовый",   "price": 100,
                  "weights": {"common": 650, "uncommon": 250, "rare": 80, "epic": 18, "legendary": 2}},
    "royal":     {"name": "Королевский", "price": 1000,
                  "weights": {"common": 300, "uncommon": 350, "rare": 250, "epic": 80, "legendary": 18, "mythic": 2}},
    "celestial": {"name": "Небесный",    "price": 25000,
                  "weights": {"rare": 200, "epic": 400, "legendary": 300, "mythic": 95, "celestial": 5}},
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

def pick_pony(rarity: str) -> tuple[str, int, str]:
    base_mult = RARITY_BY_ID[rarity][3]
    pony_name = random.choice(PONY_DB.get(rarity, ["Unknown Pony"]))
    price = int(100 * base_mult * random.uniform(0.8, 1.2))
    color = RARITY_BY_ID[rarity][4]
    return pony_name, price, color

# Функция для генерации превью кейса
def get_case_preview(case_id: str) -> list:
    weights = CASES[case_id]["weights"]
    preview = []
    for rarity, weight in weights.items():
        # Берем пару случайных пони из этой редкости для превью
        ponies = random.sample(PONY_DB.get(rarity, ["Unknown"]), min(2, len(PONY_DB.get(rarity, []))))
        for p in ponies:
            base_mult = RARITY_BY_ID[rarity][3]
            price = int(100 * base_mult * random.uniform(0.8, 1.2))
            color = RARITY_BY_ID[rarity][4]
            preview.append({"name": p, "price": price, "rarity": rarity, "color": color})
    # Сортируем по цене
    return sorted(preview, key=lambda x: x["price"], reverse=True)
