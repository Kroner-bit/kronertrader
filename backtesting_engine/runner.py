import os
import sys
import uuid
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backtesting import Backtest
from core.database import DB_PATH, get_db_connection
from strategies.loader import get_strategy_by_key

REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)

TIMEFRAME_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D"
}

def load_ticks_as_ohlcv(
    symbol: str = "EURUSD",
    timeframe: str = "1m",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db_path: str = DB_PATH
) -> pd.DataFrame:
    """
    Loads ticks from SQLite and resamples them into OHLCV candles
    required by backtesting.py.
    """
    conn = get_db_connection(db_path)
    query = "SELECT timestamp, bid, ask, bid_volume, ask_volume FROM ticks WHERE symbol = ?"
    params = [symbol.upper()]

    if from_date:
        start_ts = int(datetime.strptime(from_date, "%Y-%m-%d").timestamp() * 1000)
        query += " AND timestamp >= ?"
        params.append(start_ts)
    if to_date:
        end_ts = int(datetime.strptime(to_date, "%Y-%m-%d").timestamp() * 1000)
        query += " AND timestamp <= ?"
        params.append(end_ts)

    query += " ORDER BY timestamp ASC;"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        raise ValueError(f"Nem található tick adat az SQLite-ban a megadott feltételekkel ({symbol}, {from_date} - {to_date})")

    # Mid price for OHLC
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("datetime", inplace=True)
    df["price"] = (df["bid"] + df["ask"]) / 2.0
    df["volume"] = df["bid_volume"] + df["ask_volume"]

    rule = TIMEFRAME_MAP.get(timeframe.lower(), "1min")

    ohlcv = df["price"].resample(rule).ohlc()
    volume_resampled = df["volume"].resample(rule).sum()

    ohlcv["Volume"] = volume_resampled
    ohlcv.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close"
    }, inplace=True)

    # Drop bars with no ticks (e.g. market closed)
    ohlcv.dropna(subset=["Open", "Close"], inplace=True)

    return ohlcv

def run_backtest(
    strategy_key: str,
    symbol: str = "EURUSD",
    timeframe: str = "1m",
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    cash: float = 10000.0,
    commission: float = 0.0001,
    generate_plot: bool = True,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Executes a backtest using backtesting.py and saves stats to SQLite.
    """
    strategy_cls = get_strategy_by_key(strategy_key)
    bt_class = strategy_cls.get_backtest_class()

    df = load_ticks_as_ohlcv(
        symbol=symbol,
        timeframe=timeframe,
        from_date=from_date,
        to_date=to_date,
        db_path=db_path
    )

    if len(df) < 20:
        raise ValueError(f"Túl kevés gyertya ({len(df)}) képződött a visszateszthez. Kérlek válassz hosszabb időszakot.")

    bt = Backtest(df, bt_class, cash=cash, commission=commission, exclusive_orders=True)
    stats = bt.run()

    run_id = str(uuid.uuid4())[:8]
    html_report_name = f"backtest_{strategy_key}_{symbol}_{run_id}.html"
    html_report_path = os.path.join(REPORTS_DIR, html_report_name)

    if generate_plot:
        try:
            bt.plot(filename=html_report_path, open_browser=False)
        except Exception as e:
            print(f"Warning: could not generate bokeh plot: {e}")
            html_report_path = None

    start_str = str(df.index[0].strftime("%Y-%m-%d %H:%M"))
    end_str = str(df.index[-1].strftime("%Y-%m-%d %H:%M"))

    def safe_float(val, default=0.0):
        if pd.isna(val) or np.isneginf(val) or np.isposinf(val):
            return default
        return round(float(val), 2)

    return_pct = safe_float(stats.get("Return [%]"))
    final_equity = safe_float(stats.get("Equity Final [$]"), cash)
    sharpe = safe_float(stats.get("Sharpe Ratio"))
    max_dd = safe_float(stats.get("Max. Drawdown [%]"))
    win_rate = safe_float(stats.get("Win Rate [%]"))
    trades_count = int(stats.get("# Trades", 0))

    # Save to SQLite
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO backtest_runs (
        id, strategy_name, symbol, timeframe, start_date, end_date,
        initial_cash, final_equity, return_pct, sharpe_ratio,
        max_drawdown_pct, win_rate_pct, total_trades, html_report_path
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, (
        run_id, strategy_key, symbol.upper(), timeframe, start_str, end_str,
        cash, final_equity, return_pct, sharpe, max_dd, win_rate, trades_count,
        html_report_name if html_report_path else None
    ))
    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "strategy_key": strategy_key,
        "strategy_name": strategy_cls.name,
        "symbol": symbol.upper(),
        "timeframe": timeframe,
        "start_date": start_str,
        "end_date": end_str,
        "candles_count": len(df),
        "initial_cash": cash,
        "final_equity": final_equity,
        "return_pct": return_pct,
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": max_dd,
        "win_rate_pct": win_rate,
        "total_trades": trades_count,
        "report_file": html_report_name if html_report_path else None,
        "stats_raw": {k: str(v) for k, v in stats.items() if not k.startswith("_")}
    }

def list_backtest_runs(db_path: str = DB_PATH) -> list:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM backtest_runs ORDER BY created_at DESC;")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run backtest on SQLite tick data")
    parser.add_argument("--strategy", type=str, default="ema_cross", help="Strategy key (e.g. ema_cross, rsi_reversal)")
    parser.add_argument("--symbol", type=str, default="EURUSD", help="Symbol")
    parser.add_argument("--timeframe", type=str, default="1m", help="Timeframe (1m, 5m, 1h)")
    parser.add_argument("--cash", type=float, default=10000.0, help="Initial capital")
    args = parser.parse_args()

    res = run_backtest(
        strategy_key=args.strategy,
        symbol=args.symbol,
        timeframe=args.timeframe,
        cash=args.cash
    )
    print("\n=== Backtest Eredmények ===")
    print(f"Stratégia: {res['strategy_name']}")
    print(f"Időszak: {res['start_date']} -> {res['end_date']} ({res['candles_count']} gyertya)")
    print(f"Kezdőtőke: ${res['initial_cash']:,.2f} -> Záró tőke: ${res['final_equity']:,.2f}")
    print(f"Hozam: {res['return_pct']}% | Sharpe: {res['sharpe_ratio']} | Max DD: {res['max_drawdown_pct']}%")
    print(f"Kötések száma: {res['total_trades']} | Win Rate: {res['win_rate_pct']}%")
    if res['report_file']:
        print(f"Riport: {res['report_file']}")
