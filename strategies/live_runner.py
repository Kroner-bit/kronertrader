import os
import sys
import time
import threading
from datetime import datetime
import pandas as pd
from typing import Optional, Dict, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.database import DB_PATH, get_db_connection, get_latest_tick
from core.paper_broker import PaperBroker
from strategies.loader import get_strategy_by_key

class LiveStrategyRunner:
    """
    Executes a strategy in real-time or forward-test replay mode.
    Maintains rolling OHLCV candles, evaluates signals, and executes trades
    via PaperBroker on the specified demo account.
    """
    def __init__(
        self,
        strategy_key: str,
        account_id: str = "demo_main",
        symbol: str = "EURUSD",
        timeframe: str = "1m",
        volume: float = 0.1,
        db_path: str = DB_PATH
    ):
        self.strategy_key = strategy_key
        self.strategy_cls = get_strategy_by_key(strategy_key)
        self.account_id = account_id
        self.symbol = symbol.upper()
        self.timeframe = timeframe
        self.volume = volume
        self.db_path = db_path
        self.broker = PaperBroker(db_path=db_path)

        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.last_evaluated_candle_time: Optional[pd.Timestamp] = None

        # Rolling candle buffer
        self.candles = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        self.current_bar_ticks = []
        self.current_bar_start_ts = None

    def _sync_status_to_db(self, status: str):
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO active_strategies (strategy_id, strategy_name, account_id, symbol, timeframe, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(strategy_id) DO UPDATE SET
            status = excluded.status;
        """, (
            f"{self.strategy_key}_{self.account_id}",
            self.strategy_cls.name,
            self.account_id,
            self.symbol,
            self.timeframe,
            status
        ))
        conn.commit()
        conn.close()

    def load_initial_candles(self, count: int = 100):
        """Loads last N historical candles from DB to prime indicators."""
        from backtesting_engine.runner import load_ticks_as_ohlcv
        try:
            df = load_ticks_as_ohlcv(symbol=self.symbol, timeframe=self.timeframe, db_path=self.db_path)
            self.candles = df.tail(count).copy()
        except Exception:
            self.candles = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    def on_tick(self, tick: Dict[str, Any]):
        """Called whenever a new tick arrives."""
        ts_ms = tick["timestamp"]
        bid = float(tick["bid"])
        ask = float(tick["ask"])
        price = (bid + ask) / 2.0
        vol = float(tick.get("bid_volume", 0)) + float(tick.get("ask_volume", 0))

        # 1. Update PaperBroker open positions with live tick for SL/TP and unrealized PnL
        self.broker.on_tick(tick)

        # 2. Update rolling candle aggregator (1m interval = 60000ms)
        interval_ms = 60000 if self.timeframe == "1m" else 300000 # 5m = 300000ms
        bar_start = (ts_ms // interval_ms) * interval_ms

        if self.current_bar_start_ts is None:
            self.current_bar_start_ts = bar_start
            self.current_bar_ticks = [(ts_ms, price, vol)]
        elif bar_start == self.current_bar_start_ts:
            self.current_bar_ticks.append((ts_ms, price, vol))
        else:
            # Current bar completed! Construct bar
            bar_dt = pd.to_datetime(self.current_bar_start_ts, unit="ms", utc=True)
            prices = [p[1] for p in self.current_bar_ticks]
            volumes = [p[2] for p in self.current_bar_ticks]
            new_bar = pd.DataFrame([{
                "Open": prices[0],
                "High": max(prices),
                "Low": min(prices),
                "Close": prices[-1],
                "Volume": sum(volumes)
            }], index=[bar_dt])

            self.candles = pd.concat([self.candles, new_bar]).tail(150)
            self.current_bar_start_ts = bar_start
            self.current_bar_ticks = [(ts_ms, price, vol)]

            # Evaluate strategy on new completed bar
            self.evaluate()

    def evaluate(self):
        if len(self.candles) < 20:
            return

        # Check existing open position for this strategy and account
        positions = self.broker.get_positions(account_id=self.account_id)
        current_pos = next((p for p in positions if p.get("symbol") == self.symbol), None)

        signal = self.strategy_cls.evaluate_live_signal(self.candles, current_pos)
        action = signal.get("action", "HOLD")

        if action == "BUY":
            print(f"[{self.strategy_key}] BUY SIGNAL on {self.symbol} -> {signal.get('reason')}")
            try:
                self.broker.place_order(
                    account_id=self.account_id,
                    symbol=self.symbol,
                    side="BUY",
                    volume=self.volume,
                    stop_loss=signal.get("stop_loss"),
                    take_profit=signal.get("take_profit"),
                    strategy_id=self.strategy_key
                )
            except Exception as e:
                print(f"Error placing buy order: {e}")

        elif action == "SELL":
            print(f"[{self.strategy_key}] SELL SIGNAL on {self.symbol} -> {signal.get('reason')}")
            try:
                self.broker.place_order(
                    account_id=self.account_id,
                    symbol=self.symbol,
                    side="SELL",
                    volume=self.volume,
                    stop_loss=signal.get("stop_loss"),
                    take_profit=signal.get("take_profit"),
                    strategy_id=self.strategy_key
                )
            except Exception as e:
                print(f"Error placing sell order: {e}")

        elif action == "CLOSE" and current_pos:
            print(f"[{self.strategy_key}] CLOSE SIGNAL on {self.symbol} -> {signal.get('reason')}")
            try:
                self.broker.close_position(current_pos["id"], close_reason="SIGNAL")
            except Exception as e:
                print(f"Error closing position: {e}")

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.load_initial_candles()
        self._sync_status_to_db("RUNNING")
        print(f"Started strategy '{self.strategy_cls.name}' on account '{self.account_id}' for {self.symbol} ({self.timeframe})")

    def stop(self):
        self.is_running = False
        self._sync_status_to_db("STOPPED")
        print(f"Stopped strategy '{self.strategy_cls.name}'")
