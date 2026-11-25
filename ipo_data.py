"""
ipo_data.py
------------
A small searchable catalogue of IPOs/listed symbols, plus deterministic
synthetic price-history and order-flow generators.

NOTE ON DATA SOURCE: this sandbox has no outbound network access, so it
cannot call a real market-data / IPO-listing API. Each symbol below gets a
seeded random walk instead, so results are stable across reruns for the same
symbol (nice for demoing charts) but are NOT real market data. Swapping in a
real feed later just means replacing `generate_price_history()` with a call
to your market-data provider of choice -- the rest of the app (engine,
charts, matching) does not need to change.
"""

import random
import time

IPO_CATALOGUE = [
    {"symbol": "NEXORA", "name": "Nexora Robotics Ltd.", "sector": "Industrial AI", "ipo_price": 420.0},
    {"symbol": "HELIX",  "name": "Helix Genomics Inc.",   "sector": "Biotechnology", "ipo_price": 88.0},
    {"symbol": "QUANTA", "name": "Quanta Compute Corp.",  "sector": "Semiconductors", "ipo_price": 215.0},
    {"symbol": "VERDEN", "name": "Verden Energy PLC",     "sector": "Clean Energy", "ipo_price": 34.5},
    {"symbol": "ORBITX", "name": "OrbitX Aerospace",      "sector": "Aerospace", "ipo_price": 560.0},
    {"symbol": "FINLEY", "name": "Finley Payments Group",  "sector": "Fintech", "ipo_price": 61.0},
    {"symbol": "ATLASM", "name": "Atlas Materials Co.",   "sector": "Mining & Materials", "ipo_price": 47.25},
    {"symbol": "NIMBUS", "name": "Nimbus Cloud Systems",  "sector": "Cloud Infrastructure", "ipo_price": 132.0},
    {"symbol": "CORALQ", "name": "Coral Quant Markets",   "sector": "Financial Services", "ipo_price": 275.0},
    {"symbol": "PULSAR", "name": "Pulsar Mobility Inc.",  "sector": "Electric Vehicles", "ipo_price": 19.75},
]


def search_ipo(query: str):
    q = (query or "").strip().upper()
    if not q:
        return IPO_CATALOGUE
    return [
        row for row in IPO_CATALOGUE
        if q in row["symbol"] or q in row["name"].upper() or q in row["sector"].upper()
    ]


def get_symbol(symbol: str):
    for row in IPO_CATALOGUE:
        if row["symbol"] == symbol:
            return row
    return None


def generate_price_history(symbol: str, points: int = 60):
    """Deterministic seeded random walk around the symbol's IPO price."""
    row = get_symbol(symbol) or {"ipo_price": 100.0}
    rnd = random.Random(sum(ord(c) for c in symbol))  # stable per-symbol seed
    price = row["ipo_price"]
    history = []
    now = time.time()
    for i in range(points):
        drift = rnd.uniform(-0.015, 0.016) * price
        price = max(0.5, price + drift)
        history.append({"t": now - (points - i) * 60, "price": round(price, 2)})
    return history


def generate_synthetic_order_flow(symbol: str, n_orders: int = 40):
    """
    Produces a deterministic-ish stream of (side, type, price, qty) tuples
    around the symbol's current synthetic price, to seed the live order book
    for the demo so there's always visible depth and trade activity.
    """
    row = get_symbol(symbol) or {"ipo_price": 100.0}
    rnd = random.Random(sum(ord(c) for c in symbol) + 7)
    base = row["ipo_price"]
    flow = []
    for _ in range(n_orders):
        side = rnd.choice(["BUY", "SELL"])
        is_market = rnd.random() < 0.12
        offset_pct = rnd.uniform(-0.02, 0.02)
        price = round(max(0.5, base * (1 + offset_pct)), 2)
        qty = rnd.choice([5, 10, 15, 20, 25, 40, 50, 75, 100])
        flow.append({
            "side": side,
            "type": "MARKET" if is_market else "LIMIT",
            "price": None if is_market else price,
            "qty": qty,
        })
    return flow
