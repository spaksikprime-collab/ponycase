import hmac, hashlib, secrets, random

RARITIES = [
    ("common",    500_000, "Обычная",     1),
    ("uncommon",  250_000, "Необычная",   3),
    ("rare",      150_000, "Редкая",      10),
    ("epic",       70_000, "Эпическая",   50),
    ("legendary",  25_000, "Легендарная", 250),
    ("mythic",      4_500, "Мифическая",  2000),
    ("celestial",     500, "Божественная", 50_000),
]
RARITY_BY_ID = {r[0]: r for r in RARITIES}

CASES = {
    "starter":   {"name": "Стартовый",   "price": 100,
                  "weights": {"common": 650, "uncommon": 250, "rare": 80, "epic": 18, "legendary": 2}},
    "royal":     {"name": "Королевский", "price": 1000,
                  "weights": {"common": 300, "uncommon": 350, "rare": 250, "epic": 80, "legendary": 18, "mythic": 2}},
    "celestial": {"name": "Небесный",    "price": 25_000,
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

def pick_pony(rarity: str) -> tuple[str, int]:
    base_mult = RARITY_BY_ID[rarity][3]
    idx = random.randint(1, 999)
    price = int(100 * base_mult * random.uniform(0.8, 1.2))
    return f"{rarity}_{idx}", price
