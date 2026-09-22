import os
import sys
import uuid
import time
from typing import Optional, List, Dict, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.database import DB_PATH, get_db_connection, get_latest_tick

# Standard contract sizes (Forex = 100,000 units per standard lot)
CONTRACT_SIZES = {
    "EURUSD": 100000,
    "GBPUSD": 100000,
    "USDJPY": 100000,
    "AUDUSD": 100000,
    "USDCAD": 100000,
    "USDCHF": 100000,
    "NZDUSD": 100000,
    "BTCUSD": 1
}

def get_contract_size(symbol: str) -> float:
    return CONTRACT_SIZES.get(symbol.upper(), 100000)

class PaperBroker:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._latest_ticks: Dict[str, Dict[str, Any]] = {}

    def get_account(self, account_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM demo_accounts WHERE id = ?;", (account_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def list_accounts(self) -> List[Dict[str, Any]]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM demo_accounts ORDER BY created_at ASC;")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def create_account(
        self,
        account_id: str,
        name: str,
        initial_balance: float = 10000.0,
        currency: str = "USD",
        leverage: int = 100
    ) -> Dict[str, Any]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO demo_accounts (id, name, currency, balance, equity, margin, free_margin, leverage)
        VALUES (?, ?, ?, ?, ?, 0.0, ?, ?);
        """, (account_id, name, currency, initial_balance, initial_balance, initial_balance, leverage))
        conn.commit()
        conn.close()
        return self.get_account(account_id)

    def delete_account(self, account_id: str) -> bool:
        conn = get_db_connection(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM demo_accounts WHERE id = ?;", (account_id,))
            if not cursor.fetchone():
                return False

            with conn:
                cursor.execute("DELETE FROM positions WHERE account_id = ?;", (account_id,))
                cursor.execute("DELETE FROM trade_history WHERE account_id = ?;", (account_id,))
                cursor.execute("DELETE FROM active_strategies WHERE account_id = ?;", (account_id,))
                cursor.execute("DELETE FROM demo_accounts WHERE id = ?;", (account_id,))
            return True
        finally:
            conn.close()

    def place_order(
        self,
        account_id: str,
        symbol: str,
        side: str,
        volume: float,
        order_type: str = "MARKET",
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        strategy_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a paper order against current market bid/ask prices.
        side: 'BUY' or 'SELL'
        volume: lot size (e.g. 0.1, 1.0)
        """
        symbol = symbol.upper()
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError("Side must be 'BUY' or 'SELL'")

        account = self.get_account(account_id)
        if not account:
            raise ValueError(f"Account '{account_id}' not found")

        tick = self._latest_ticks.get(symbol) or get_latest_tick(symbol, self.db_path)
        if not tick:
            raise ValueError(f"No market data available for '{symbol}' to execute order")

        # In FX: BUY enters at ASK, SELL enters at BID
        open_price = float(tick["ask"]) if side == "BUY" else float(tick["bid"])
        now_ts = int(tick.get("timestamp") or (time.time() * 1000))

        contract_size = get_contract_size(symbol)
        position_value = volume * contract_size * open_price
        required_margin = position_value / account["leverage"]

        if account["free_margin"] < required_margin:
            raise ValueError(f"Insufficient free margin. Required: {required_margin:.2f}, Available: {account['free_margin']:.2f}")

        order_id = str(uuid.uuid4())
        position_id = str(uuid.uuid4())

        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()

        # 1. Insert order record
        cursor.execute("""
        INSERT INTO orders (id, account_id, strategy_id, symbol, side, order_type, volume, price, stop_loss, take_profit, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'FILLED', ?);
        """, (order_id, account_id, strategy_id, symbol, side, order_type, volume, open_price, stop_loss, take_profit, now_ts))

        # 2. Insert position record
        cursor.execute("""
        INSERT INTO positions (id, account_id, strategy_id, symbol, side, volume, open_price, current_price, stop_loss, take_profit, unrealized_pnl, open_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?);
        """, (position_id, account_id, strategy_id, symbol, side, volume, open_price, open_price, stop_loss, take_profit, now_ts))

        # 3. Update account margin
        new_margin = account["margin"] + required_margin
        new_free_margin = account["equity"] - new_margin
        cursor.execute("""
        UPDATE demo_accounts SET margin = ?, free_margin = ? WHERE id = ?;
        """, (new_margin, new_free_margin, account_id))

        conn.commit()
        conn.close()

        return {
            "order_id": order_id,
            "position_id": position_id,
            "account_id": account_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "price": open_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "timestamp": now_ts
        }

    def close_position(self, position_id: str, close_reason: str = "MANUAL", close_price: Optional[float] = None) -> Optional[Dict[str, Any]]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE id = ?;", (position_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None

        pos = dict(row)
        symbol = pos["symbol"]
        side = pos["side"]
        volume = float(pos["volume"])
        open_price = float(pos["open_price"])
        account_id = pos["account_id"]
        contract_size = get_contract_size(symbol)

        if close_price is None:
            tick = self._latest_ticks.get(symbol) or get_latest_tick(symbol, self.db_path)
            if tick:
                # BUY closes at BID, SELL closes at ASK
                close_price = float(tick["bid"]) if side == "BUY" else float(tick["ask"])
            elif pos.get("current_price") is not None and float(pos["current_price"]) > 0:
                close_price = float(pos["current_price"])
            else:
                close_price = open_price

        # Calculate realized PnL
        if side == "BUY":
            pnl = (close_price - open_price) * volume * contract_size
        else:
            pnl = (open_price - close_price) * volume * contract_size

        tick_now = self._latest_ticks.get(symbol)
        now_ts = int((tick_now.get("timestamp") if tick_now else None) or (time.time() * 1000))
        trade_id = str(uuid.uuid4())

        # 1. Insert trade history
        cursor.execute("""
        INSERT INTO trade_history (id, account_id, strategy_id, symbol, side, volume, open_price, close_price, pnl, commission, open_time, close_time, close_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?, ?);
        """, (trade_id, account_id, pos.get("strategy_id"), symbol, side, volume, open_price, close_price, pnl, pos["open_time"], now_ts, close_reason))

        # 2. Delete position
        cursor.execute("DELETE FROM positions WHERE id = ?;", (position_id,))

        # 3. Recalculate account balance, margin, equity
        cursor.execute("SELECT * FROM demo_accounts WHERE id = ?;", (account_id,))
        acc = dict(cursor.fetchone())

        new_balance = acc["balance"] + pnl

        # Calculate remaining margin for all other open positions
        cursor.execute("SELECT * FROM positions WHERE account_id = ?;", (account_id,))
        remaining_positions = cursor.fetchall()

        total_margin = 0.0
        total_unrealized_pnl = 0.0
        for p in remaining_positions:
            p_dict = dict(p)
            p_val = float(p_dict["volume"]) * get_contract_size(p_dict["symbol"]) * float(p_dict["open_price"])
            total_margin += p_val / acc["leverage"]
            total_unrealized_pnl += float(p_dict["unrealized_pnl"])

        new_equity = new_balance + total_unrealized_pnl
        new_free_margin = new_equity - total_margin

        cursor.execute("""
        UPDATE demo_accounts 
        SET balance = ?, equity = ?, margin = ?, free_margin = ? 
        WHERE id = ?;
        """, (new_balance, new_equity, total_margin, new_free_margin, account_id))

        conn.commit()
        conn.close()

        return {
            "trade_id": trade_id,
            "position_id": position_id,
            "account_id": account_id,
            "symbol": symbol,
            "side": side,
            "volume": volume,
            "open_price": open_price,
            "close_price": close_price,
            "pnl": round(pnl, 2),
            "close_reason": close_reason,
            "close_time": now_ts
        }

    def on_tick(self, tick: Dict[str, Any]):
        """
        Processes an incoming market tick:
        - Updates unrealized PnL of open positions.
        - Evaluates Stop Loss & Take Profit limits.
        - Updates account equity.
        """
        symbol = tick["symbol"].upper()
        self._latest_ticks[symbol] = tick
        bid = float(tick["bid"])
        ask = float(tick["ask"])
        contract_size = get_contract_size(symbol)

        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE symbol = ?;", (symbol,))
        positions = [dict(r) for r in cursor.fetchall()]
        conn.close()

        accounts_to_update = set()

        for pos in positions:
            pos_id = pos["id"]
            side = pos["side"]
            open_price = float(pos["open_price"])
            volume = float(pos["volume"])
            sl = float(pos["stop_loss"]) if pos["stop_loss"] is not None else None
            tp = float(pos["take_profit"]) if pos["take_profit"] is not None else None
            account_id = pos["account_id"]
            accounts_to_update.add(account_id)

            if side == "BUY":
                current_price = bid
                pnl = (current_price - open_price) * volume * contract_size
                # Check SL
                if sl is not None and bid <= sl:
                    self.close_position(pos_id, close_reason="SL", close_price=bid)
                    continue
                # Check TP
                if tp is not None and bid >= tp:
                    self.close_position(pos_id, close_reason="TP", close_price=bid)
                    continue
            else: # SELL
                current_price = ask
                pnl = (open_price - current_price) * volume * contract_size
                # Check SL
                if sl is not None and ask >= sl:
                    self.close_position(pos_id, close_reason="SL", close_price=ask)
                    continue
                # Check TP
                if tp is not None and ask <= tp:
                    self.close_position(pos_id, close_reason="TP", close_price=ask)
                    continue

            # Update position price & pnl
            conn = get_db_connection(self.db_path)
            c = conn.cursor()
            c.execute("""
            UPDATE positions SET current_price = ?, unrealized_pnl = ? WHERE id = ?;
            """, (current_price, pnl, pos_id))
            conn.commit()
            conn.close()

        # Update accounts equity
        for acc_id in accounts_to_update:
            conn = get_db_connection(self.db_path)
            c = conn.cursor()
            c.execute("SELECT balance, margin FROM demo_accounts WHERE id = ?;", (acc_id,))
            acc_row = c.fetchone()
            if acc_row:
                bal = float(acc_row["balance"])
                margin = float(acc_row["margin"])
                c.execute("SELECT COALESCE(SUM(unrealized_pnl), 0) FROM positions WHERE account_id = ?;", (acc_id,))
                unrealized = float(c.fetchone()[0])
                equity = bal + unrealized
                free_margin = equity - margin
                c.execute("UPDATE demo_accounts SET equity = ?, free_margin = ? WHERE id = ?;", (equity, free_margin, acc_id))
                conn.commit()
            conn.close()

    def get_positions(self, account_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        if account_id:
            cursor.execute("SELECT * FROM positions WHERE account_id = ? ORDER BY open_time DESC;", (account_id,))
        else:
            cursor.execute("SELECT * FROM positions ORDER BY open_time DESC;")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_trade_history(self, account_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        if account_id:
            cursor.execute("SELECT * FROM trade_history WHERE account_id = ? ORDER BY close_time DESC LIMIT ?;", (account_id, limit))
        else:
            cursor.execute("SELECT * FROM trade_history ORDER BY close_time DESC LIMIT ?;", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_performance(self, account_id: str) -> Dict[str, Any]:
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trade_history WHERE account_id = ? ORDER BY close_time ASC;", (account_id,))
        trades = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM demo_accounts WHERE id = ?;", (account_id,))
        acc_row = cursor.fetchone()
        conn.close()

        if not acc_row:
            return {}

        acc = dict(acc_row)
        total_trades = len(trades)
        winning_trades = [t for t in trades if t["pnl"] > 0]
        losing_trades = [t for t in trades if t["pnl"] < 0]

        win_rate = (len(winning_trades) / total_trades * 100.0) if total_trades > 0 else 0.0
        total_profit = sum(t["pnl"] for t in winning_trades)
        total_loss = abs(sum(t["pnl"] for t in losing_trades))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (total_profit if total_profit > 0 else 1.0)
        net_pnl = sum(t["pnl"] for t in trades)

        return {
            "account_id": account_id,
            "name": acc["name"],
            "balance": acc["balance"],
            "equity": acc["equity"],
            "margin": acc["margin"],
            "free_margin": acc["free_margin"],
            "total_trades": total_trades,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "net_pnl": round(net_pnl, 2),
            "currency": acc["currency"]
        }
