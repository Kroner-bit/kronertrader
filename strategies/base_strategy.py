import os
import sys
import pandas as pd
import numpy as np
from typing import Optional, Dict, Any, List
from backtesting import Strategy

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

class BaseTradingStrategy:
    """
    Metadata and execution interface for strategies.
    Each strategy implementation provides:
    - Backtest strategy class (inheriting from backtesting.Strategy)
    - Forward test signal generator
    """
    name: str = "BaseStrategy"
    description: str = "Base trading strategy"
    default_timeframe: str = "1m"
    default_symbol: str = "EURUSD"
    default_volume: float = 0.1

    @classmethod
    def get_backtest_class(cls) -> type:
        raise NotImplementedError

    @classmethod
    def evaluate_live_signal(
        cls,
        df: pd.DataFrame,
        current_position: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Evaluates the latest candles and returns an action:
        {
            'action': 'BUY' | 'SELL' | 'CLOSE' | 'HOLD',
            'stop_loss': Optional[float],
            'take_profit': Optional[float],
            'reason': str
        }
        """
        raise NotImplementedError
