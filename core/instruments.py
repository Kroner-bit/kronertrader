import os
import json
from typing import List, Dict, Any, Optional

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTRUMENTS_FILE = os.path.join(PROJECT_ROOT, "data", "instruments.json")

_CACHE: Optional[List[Dict[str, Any]]] = None

def get_all_instruments() -> List[Dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    if os.path.exists(INSTRUMENTS_FILE):
        with open(INSTRUMENTS_FILE, "r", encoding="utf-8") as f:
            _CACHE = json.load(f)
            return _CACHE

    return [
        {"id": "eurusd", "symbol": "EURUSD", "name": "EUR/USD", "description": "Euro vs US Dollar", "category": "Forex Főpárok"},
        {"id": "gbpusd", "symbol": "GBPUSD", "name": "GBP/USD", "description": "British Pound vs US Dollar", "category": "Forex Főpárok"},
        {"id": "usdjpy", "symbol": "USDJPY", "name": "USD/JPY", "description": "US Dollar vs Japanese Yen", "category": "Forex Főpárok"},
        {"id": "btcusd", "symbol": "BTCUSD", "name": "BTC/USD", "description": "Bitcoin vs US Dollar", "category": "Kriptovaluták"},
        {"id": "xauusd", "symbol": "XAUUSD", "name": "XAU/USD", "description": "Gold vs US Dollar", "category": "Nyersanyagok & Fémek"}
    ]

def get_instrument_by_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    instruments = get_all_instruments()
    s = symbol.lower()
    for inst in instruments:
        if inst["id"] == s or inst["symbol"].lower() == s:
            return inst
    return None

REFERENCE_PRICES: Dict[str, float] = {
    # Major Indices
    "USATECHIDXUSD": 30510.0,
    "USA500IDXUSD": 7772.0,
    "USA30IDXUSD": 43500.0,
    "DEUIDXEUR": 19500.0,
    "GBRIDXGBP": 8300.0,
    "JPNIDXJPY": 38500.0,
    "FRAIDXEUR": 7500.0,
    "EUIDXEUR": 4900.0,
    # Crypto
    "BTCUSD": 85900.0,
    "ETHUSD": 3200.0,
    "LTCUSD": 110.0,
    # Metals & Commodities
    "XAUUSD": 4322.0,
    "XAGUSD": 32.50,
    "BRENTCMDUSD": 74.50,
    "LIGHTCMDUSD": 70.80,
    # Major & Cross Forex
    "EURUSD": 1.1525,
    "GBPUSD": 1.3050,
    "USDJPY": 154.20,
    "USDCHF": 0.8850,
    "USDCAD": 1.3850,
    "AUDUSD": 0.6550,
    "NZDUSD": 0.5850,
    "EURGBP": 0.8820,
    "EURJPY": 168.50,
    "GBPJPY": 195.20,
    "EURCHF": 0.9400,
    "AUDJPY": 101.00,
    "NZDJPY": 90.00,
    "CADJPY": 111.00,
    "CHFJPY": 174.00,
}

def get_symbol_spec(symbol: str) -> Dict[str, Any]:
    s = symbol.upper().strip()
    ref_price = REFERENCE_PRICES.get(s)
    meta = get_instrument_by_symbol(s)
    cat = (meta.get("category") or "").lower() if meta else ""

    # 1. Indices (US 500, US Tech 100, DAX, FTSE, Nikkei, etc.)
    if "IDX" in s or "index" in cat:
        return {
            "type": "index",
            "digits": 2,
            "pip_step": 0.5,
            "spread_points": 0.8,
            "unit": "pt",
            "mult": 1.0,
            "default_price": ref_price or 5000.0
        }

    # 2. Crypto
    if "BTC" in s:
        return {
            "type": "crypto",
            "digits": 1,
            "pip_step": 2.0,
            "spread_points": 5.0,
            "unit": "USD",
            "mult": 1.0,
            "default_price": ref_price or 85900.0
        }
    if "ETH" in s:
        return {
            "type": "crypto",
            "digits": 2,
            "pip_step": 0.5,
            "spread_points": 1.0,
            "unit": "USD",
            "mult": 1.0,
            "default_price": ref_price or 3200.0
        }
    if any(k in s for k in ["LTC", "XRP", "SOL", "ADA", "DOGE"]) or "kripto" in cat or "crypto" in cat:
        return {
            "type": "crypto",
            "digits": 2,
            "pip_step": 0.1,
            "spread_points": 0.2,
            "unit": "USD",
            "mult": 1.0,
            "default_price": ref_price or 100.0
        }

    # 3. Metals
    if "XAU" in s or "GOLD" in s:
        return {
            "type": "metal",
            "digits": 2,
            "pip_step": 0.1,
            "spread_points": 0.35,
            "unit": "USD",
            "mult": 1.0,
            "default_price": ref_price or 4322.0
        }
    if "XAG" in s or "SILVER" in s:
        return {
            "type": "metal",
            "digits": 3,
            "pip_step": 0.01,
            "spread_points": 0.02,
            "unit": "USD",
            "mult": 1.0,
            "default_price": ref_price or 32.50
        }

    # 4. Commodities
    if any(k in s for k in ["CMD", "OIL", "BRENT", "LIGHT"]) or "nyersanyag" in cat:
        return {
            "type": "commodity",
            "digits": 2,
            "pip_step": 0.02,
            "spread_points": 0.05,
            "unit": "USD",
            "mult": 1.0,
            "default_price": ref_price or 75.0
        }

    # 5. JPY Forex Pairs
    if "JPY" in s:
        return {
            "type": "forex_jpy",
            "digits": 3,
            "pip_step": 0.01,
            "spread_points": 1.5,
            "unit": "pip",
            "mult": 100.0,
            "default_price": ref_price or 154.20
        }

    # 6. Standard Forex Pairs
    return {
        "type": "forex",
        "digits": 5,
        "pip_step": 0.0001,
        "spread_points": 1.2,
        "unit": "pip",
        "mult": 10000.0,
        "default_price": ref_price or 1.1525
    }

