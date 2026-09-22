import os
import sys
import importlib
import inspect
from typing import Dict, Type, List, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from strategies.base_strategy import BaseTradingStrategy
from strategies.ema_cross import EmaCrossStrategy
from strategies.rsi_reversal import RsiReversalStrategy

REGISTRY: Dict[str, Type[BaseTradingStrategy]] = {
    "ema_cross": EmaCrossStrategy,
    "rsi_reversal": RsiReversalStrategy
}

def get_available_strategies() -> List[Dict[str, Any]]:
    """Returns metadata for all registered strategies."""
    results = []
    for key, cls in REGISTRY.items():
        results.append({
            "key": key,
            "name": cls.name,
            "description": cls.description,
            "default_timeframe": cls.default_timeframe,
            "default_symbol": cls.default_symbol,
            "default_volume": cls.default_volume
        })
    return results

def get_strategy_by_key(key: str) -> Type[BaseTradingStrategy]:
    if key not in REGISTRY:
        raise ValueError(f"Stratégia '{key}' nem található. Elérhető: {list(REGISTRY.keys())}")
    return REGISTRY[key]
