import time
import pandas as pd
from typing import Optional, Dict, Any
from backtesting import Strategy

from strategies.base_strategy import BaseTradingStrategy

class _TimerScalperBacktest(Strategy):
    """
    Backtest implementáció: lépésenként váltakozva nyit Long pozíciót,
    majd a következő gyertyán lezárja azt.
    """
    def init(self):
        pass

    def next(self):
        if self.position:
            self.position.close()
        else:
            self.buy()

class TimerScalperStrategy(BaseTradingStrategy):
    """
    Időzített scalper stratégia:
    - Minden 10 másodpercben egy vételi (Long) piaci megbízást nyit.
    - Pontosan 5 másodperc múlva automatikusan lezárja a nyitott pozíciót.
    """
    name: str = "10s Long / 5s Zárás Időzített Stratégia"
    description: str = "Minden 10 másodpercben Long (vételi) piaci megbízást nyit, majd 5 másodperc múlva automatikusan lezárja a pozíciót."
    default_timeframe: str = "1m"
    default_symbol: str = "EURUSD"
    default_volume: float = 0.1
    is_tick_strategy: bool = True

    @classmethod
    def get_backtest_class(cls) -> type:
        return _TimerScalperBacktest

    @classmethod
    def evaluate_live_signal(
        cls,
        df: pd.DataFrame,
        current_position: Optional[Dict[str, Any]],
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Gyertya alapú fallback kiértékelés (ha nem tick alapon fut)."""
        if current_position:
            return {"action": "CLOSE", "reason": "Időzített pozíció zárása (gyertya mód)"}
        return {"action": "BUY", "reason": "Időzített vételi megbízás (gyertya mód)"}

    @classmethod
    def evaluate_tick_signal(
        cls,
        tick: Dict[str, Any],
        current_position: Optional[Dict[str, Any]],
        state: Dict[str, Any],
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Valós idejű tick szintű másodperces időzített kiértékelés:
        - Ha van nyitott pozíció és eltelt >= hold_sec (alapértelmezett: 5mp) -> CLOSE
        - Ha nincs nyitott pozíció és eltelt >= interval_sec (alapértelmezett: 10mp) -> BUY
        """
        params = params or {}
        interval_sec = float(params.get("interval_sec", 10.0))
        hold_sec = float(params.get("hold_sec", 5.0))

        ts_ms = tick.get("timestamp")
        now_sec = (float(ts_ms) / 1000.0) if ts_ms else time.time()

        # 1. Ha van aktív pozíció, ellenőrizzük a tartási időt (5 mp)
        if current_position is not None:
            last_open = state.get("last_open_time")
            if last_open is not None:
                elapsed_hold = now_sec - last_open
            else:
                open_time_ms = current_position.get("open_time")
                elapsed_hold = (now_sec - (float(open_time_ms) / 1000.0)) if open_time_ms else 0.0

            if elapsed_hold >= hold_sec:
                return {
                    "action": "CLOSE",
                    "reason": f"5mp tartási idő lejárt ({elapsed_hold:.1f}mp után pozíció lezárása)"
                }
            return {
                "action": "HOLD",
                "reason": f"Pozíció nyitva, tartás ({hold_sec - elapsed_hold:.1f}mp van hátra a zárásig)"
            }

        # 2. Nincs aktív pozíció: ellenőrizzük a 10 másodperces ciklust
        last_open_time = state.get("last_open_time")
        if last_open_time is None:
            # Első tick az indítás után: azonnal indítjuk az első vételi ciklust
            state["last_open_time"] = now_sec
            return {
                "action": "BUY",
                "reason": "10mp időzítő első vételi indítás (Long)"
            }

        elapsed_since_open = now_sec - last_open_time
        if elapsed_since_open >= interval_sec:
            state["last_open_time"] = now_sec
            return {
                "action": "BUY",
                "reason": f"10mp ciklus elérve ({elapsed_since_open:.1f}mp telt el) -> Új Long nyitás"
            }

        remaining = interval_sec - elapsed_since_open
        return {
            "action": "HOLD",
            "reason": f"Várakozás a következő nyitási ciklusra ({remaining:.1f}mp hátra)"
        }
