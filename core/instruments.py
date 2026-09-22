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
