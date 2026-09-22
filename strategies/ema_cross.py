import pandas as pd
from typing import Optional, Dict, Any
from backtesting import Strategy
from backtesting.lib import crossover

from strategies.base_strategy import BaseTradingStrategy, calculate_ema

class _EmaCrossBacktest(Strategy):
    fast_period = 9
    slow_period = 21
    sl_pips = 0.0020
    tp_pips = 0.0040

    def init(self):
        price = self.data.Close
        self.ema_fast = self.I(calculate_ema, pd.Series(price), self.fast_period)
        self.ema_slow = self.I(calculate_ema, pd.Series(price), self.slow_period)

    def next(self):
        price = self.data.Close[-1]
        if crossover(self.ema_fast, self.ema_slow):
            if self.position.is_short:
                self.position.close()
            sl = price - self.sl_pips
            tp = price + self.tp_pips
            self.buy(sl=sl, tp=tp)
        elif crossover(self.ema_slow, self.ema_fast):
            if self.position.is_long:
                self.position.close()
            sl = price + self.sl_pips
            tp = price - self.tp_pips
            self.sell(sl=sl, tp=tp)

class EmaCrossStrategy(BaseTradingStrategy):
    name = "EMA Cross Strategy"
    description = "Klasszikus gyors (9) és lassú (21) EMA mozgóátlag kereszteződés trendkövető stratégia."
    default_timeframe = "1m"
    default_symbol = "EURUSD"
    default_volume = 0.1

    @classmethod
    def get_backtest_class(cls) -> type:
        return _EmaCrossBacktest

    @classmethod
    def evaluate_live_signal(
        cls,
        df: pd.DataFrame,
        current_position: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        params = params or {}
        fast_p = params.get("fast_period", 9)
        slow_p = params.get("slow_period", 21)
        sl_pips = params.get("sl_pips", 0.0020)
        tp_pips = params.get("tp_pips", 0.0040)

        if len(df) < slow_p + 2:
            return {"action": "HOLD", "reason": "Nincs elegendő gyertyaadat"}

        close = df["Close"]
        ema_fast = calculate_ema(close, fast_p)
        ema_slow = calculate_ema(close, slow_p)

        curr_fast, prev_fast = ema_fast.iloc[-1], ema_fast.iloc[-2]
        curr_slow, prev_slow = ema_slow.iloc[-1], ema_slow.iloc[-2]
        current_price = close.iloc[-1]

        # Bullish crossover: fast crosses above slow
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if current_position and current_position.get("side") == "SELL":
                return {"action": "CLOSE", "reason": "Fordított jelzés (Short zárása)"}
            if not current_position:
                return {
                    "action": "BUY",
                    "stop_loss": round(current_price - sl_pips, 5),
                    "take_profit": round(current_price + tp_pips, 5),
                    "reason": f"Gyors EMA ({curr_fast:.5f}) felfelé metszette a Lassú EMA-t ({curr_slow:.5f})"
                }

        # Bearish crossover: fast crosses below slow
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            if current_position and current_position.get("side") == "BUY":
                return {"action": "CLOSE", "reason": "Fordított jelzés (Long zárása)"}
            if not current_position:
                return {
                    "action": "SELL",
                    "stop_loss": round(current_price + sl_pips, 5),
                    "take_profit": round(current_price - tp_pips, 5),
                    "reason": f"Gyors EMA ({curr_fast:.5f}) lefelé metszette a Lassú EMA-t ({curr_slow:.5f})"
                }

        return {"action": "HOLD", "reason": "Nincs kereszteződés"}
