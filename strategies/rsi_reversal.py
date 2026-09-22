import pandas as pd
from typing import Optional, Dict, Any
from backtesting import Strategy

from strategies.base_strategy import BaseTradingStrategy, calculate_rsi

class _RsiReversalBacktest(Strategy):
    rsi_period = 14
    oversold = 30
    overbought = 70
    sl_pips = 0.0025
    tp_pips = 0.0050

    def init(self):
        price = self.data.Close
        self.rsi = self.I(calculate_rsi, pd.Series(price), self.rsi_period)

    def next(self):
        price = self.data.Close[-1]
        rsi_curr = self.rsi[-1]
        rsi_prev = self.rsi[-2]

        # Crossing above 30 from below (oversold bounce)
        if rsi_prev <= self.oversold and rsi_curr > self.oversold:
            if self.position.is_short:
                self.position.close()
            sl = price - self.sl_pips
            tp = price + self.tp_pips
            self.buy(sl=sl, tp=tp)
        # Crossing below 70 from above (overbought reversal)
        elif rsi_prev >= self.overbought and rsi_curr < self.overbought:
            if self.position.is_long:
                self.position.close()
            sl = price + self.sl_pips
            tp = price - self.tp_pips
            self.sell(sl=sl, tp=tp)

class RsiReversalStrategy(BaseTradingStrategy):
    name = "RSI Reversal Strategy"
    description = "RSI indikátor (14 periódus) túlvett (70) és túladott (30) sávokból való visszatérését kereskedő stratégia."
    default_timeframe = "1m"
    default_symbol = "EURUSD"
    default_volume = 0.1

    @classmethod
    def get_backtest_class(cls) -> type:
        return _RsiReversalBacktest

    @classmethod
    def evaluate_live_signal(
        cls,
        df: pd.DataFrame,
        current_position: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        params = params or {}
        rsi_p = params.get("rsi_period", 14)
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)
        sl_pips = params.get("sl_pips", 0.0025)
        tp_pips = params.get("tp_pips", 0.0050)

        if len(df) < rsi_p + 2:
            return {"action": "HOLD", "reason": "Nincs elegendő gyertyaadat az RSI számításhoz"}

        close = df["Close"]
        rsi_series = calculate_rsi(close, rsi_p)

        rsi_curr = rsi_series.iloc[-1]
        rsi_prev = rsi_series.iloc[-2]
        current_price = close.iloc[-1]

        # Oversold recovery: RSI was <= 30, now > 30 -> BUY
        if rsi_prev <= oversold and rsi_curr > oversold:
            if current_position and current_position.get("side") == "SELL":
                return {"action": "CLOSE", "reason": "RSI túladott visszafordulás (Short zárása)"}
            if not current_position:
                return {
                    "action": "BUY",
                    "stop_loss": round(current_price - sl_pips, 5),
                    "take_profit": round(current_price + tp_pips, 5),
                    "reason": f"RSI visszapattant 30 felé (Előző: {rsi_prev:.1f}, Most: {rsi_curr:.1f})"
                }

        # Overbought breakdown: RSI was >= 70, now < 70 -> SELL
        if rsi_prev >= overbought and rsi_curr < overbought:
            if current_position and current_position.get("side") == "BUY":
                return {"action": "CLOSE", "reason": "RSI túlvett lefordulás (Long zárása)"}
            if not current_position:
                return {
                    "action": "SELL",
                    "stop_loss": round(current_price + sl_pips, 5),
                    "take_profit": round(current_price - tp_pips, 5),
                    "reason": f"RSI lefordult 70 alá (Előző: {rsi_prev:.1f}, Most: {rsi_curr:.1f})"
                }

        return {"action": "HOLD", "reason": f"RSI normál sávban ({rsi_curr:.1f})"}
