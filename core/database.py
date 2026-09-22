import os
import sqlite3
from typing import Optional, List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "market_data.db")

def get_db_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Returns an optimized SQLite connection."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    return conn

def init_db(db_path: str = DB_PATH):
    """Initializes tables and indexes for the trading platform."""
    conn = get_db_connection(db_path)
    conn.execute("PRAGMA journal_mode = WAL;")
    cursor = conn.cursor()

    # 1. Ticks table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ticks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        symbol TEXT NOT NULL,
        bid REAL NOT NULL,
        ask REAL NOT NULL,
        bid_volume REAL DEFAULT 0,
        ask_volume REAL DEFAULT 0
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticks_sym_ts ON ticks(symbol, timestamp);")

    # 2. Demo accounts
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS demo_accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        currency TEXT DEFAULT 'USD',
        balance REAL NOT NULL,
        equity REAL NOT NULL,
        margin REAL DEFAULT 0,
        free_margin REAL NOT NULL,
        leverage INTEGER DEFAULT 100,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        strategy_id TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        order_type TEXT NOT NULL,
        volume REAL NOT NULL,
        price REAL NOT NULL,
        stop_loss REAL,
        take_profit REAL,
        status TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        FOREIGN KEY (account_id) REFERENCES demo_accounts(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_acc ON orders(account_id);")

    # 4. Open positions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS positions (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        strategy_id TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        volume REAL NOT NULL,
        open_price REAL NOT NULL,
        current_price REAL NOT NULL,
        stop_loss REAL,
        take_profit REAL,
        unrealized_pnl REAL DEFAULT 0,
        open_time INTEGER NOT NULL,
        FOREIGN KEY (account_id) REFERENCES demo_accounts(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pos_acc ON positions(account_id);")

    # 5. Trade history table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_history (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL,
        strategy_id TEXT,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        volume REAL NOT NULL,
        open_price REAL NOT NULL,
        close_price REAL NOT NULL,
        pnl REAL NOT NULL,
        commission REAL DEFAULT 0,
        open_time INTEGER NOT NULL,
        close_time INTEGER NOT NULL,
        close_reason TEXT,
        FOREIGN KEY (account_id) REFERENCES demo_accounts(id)
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_acc ON trade_history(account_id);")

    # 6. Backtest runs
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS backtest_runs (
        id TEXT PRIMARY KEY,
        strategy_name TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        initial_cash REAL NOT NULL,
        final_equity REAL NOT NULL,
        return_pct REAL NOT NULL,
        sharpe_ratio REAL,
        max_drawdown_pct REAL,
        win_rate_pct REAL,
        total_trades INTEGER,
        html_report_path TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 7. Active strategies
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS active_strategies (
        strategy_id TEXT PRIMARY KEY,
        strategy_name TEXT NOT NULL,
        account_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (account_id) REFERENCES demo_accounts(id)
    );
    """)

    # Insert default demo account if none exists
    cursor.execute("SELECT COUNT(*) FROM demo_accounts;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO demo_accounts (id, name, currency, balance, equity, margin, free_margin, leverage)
        VALUES ('demo_main', 'Alapértelmezett Demó Számla', 'USD', 10000.0, 10000.0, 0.0, 10000.0, 100);
        """)

    conn.commit()
    conn.close()

def insert_ticks_batch(ticks: List[tuple], db_path: str = DB_PATH):
    """
    Fast batch insert of tick tuples:
    (timestamp, symbol, bid, ask, bid_volume, ask_volume)
    """
    if not ticks:
        return
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.executemany("""
    INSERT INTO ticks (timestamp, symbol, bid, ask, bid_volume, ask_volume)
    VALUES (?, ?, ?, ?, ?, ?);
    """, ticks)
    conn.commit()
    conn.close()

def get_latest_tick(symbol: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT timestamp, symbol, bid, ask, bid_volume, ask_volume 
    FROM ticks 
    WHERE symbol = ? 
    ORDER BY timestamp DESC LIMIT 1;
    """, (symbol.upper(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None

def get_tick_count(symbol: Optional[str] = None, db_path: str = DB_PATH) -> int:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    if symbol:
        cursor.execute("SELECT COUNT(*) FROM ticks WHERE symbol = ?;", (symbol.upper(),))
    else:
        cursor.execute("SELECT COUNT(*) FROM ticks;")
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_historical_coverage(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """Returns coverage stats for all symbols stored in SQLite."""
    from datetime import datetime
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        symbol,
        COUNT(*) as tick_count,
        MIN(timestamp) as min_ts,
        MAX(timestamp) as max_ts
    FROM ticks
    GROUP BY symbol
    ORDER BY tick_count DESC;
    """)
    rows = cursor.fetchall()
    results = []
    for r in rows:
        sym = r["symbol"]
        min_ts = r["min_ts"]
        max_ts = r["max_ts"]
        count = r["tick_count"]

        from_str = datetime.fromtimestamp(min_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if min_ts else "-"
        to_str = datetime.fromtimestamp(max_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if max_ts else "-"
        days = round((max_ts - min_ts) / (1000 * 86400), 1) if (min_ts and max_ts) else 0

        # Latest tick
        cursor.execute("SELECT bid, ask FROM ticks WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1;", (sym,))
        last_row = cursor.fetchone()
        bid = last_row["bid"] if last_row else None
        ask = last_row["ask"] if last_row else None

        results.append({
            "symbol": sym,
            "tick_count": count,
            "from_date": from_str,
            "to_date": to_str,
            "duration_days": days,
            "latest_bid": bid,
            "latest_ask": ask
        })

    conn.close()
    return results

def delete_symbol_ticks(symbol: str, db_path: str = DB_PATH) -> int:
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ticks WHERE symbol = ?;", (symbol.upper(),))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at:", DB_PATH)

