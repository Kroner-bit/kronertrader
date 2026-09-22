import os
import sys
import time
import random
import asyncio
import json
import threading
import queue
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import subprocess

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from core.database import (
    DB_PATH, get_db_connection, get_latest_tick, get_tick_count,
    get_historical_coverage, delete_symbol_ticks, insert_ticks_batch,
    has_one_year_coverage
)
from core.paper_broker import PaperBroker
from core.dukascopy_downloader import download_historical_ticks
from core.instruments import (
    get_all_instruments, get_instrument_by_symbol, get_symbol_spec, REFERENCE_PRICES
)
from strategies.loader import get_available_strategies, get_strategy_by_key
from strategies.live_runner import LiveStrategyRunner
from backtesting_engine.runner import run_backtest, list_backtest_runs, REPORTS_DIR
from core.data_gap_filler import download_manager, analyze_symbol_gaps

app = FastAPI(title="Nautilus Trader & Forward-Test Engine")

# Static files & Reports
STATIC_DIR = os.path.join(PROJECT_ROOT, "dashboard", "static")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "dashboard", "templates")
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Shared state
broker = PaperBroker(db_path=DB_PATH)
active_runners: Dict[str, LiveStrategyRunner] = {}
connected_websockets: List[WebSocket] = []

# Active Live Streaming Tickers Manager
active_streams: Dict[str, Dict[str, Any]] = {
    "EURUSD": {
        "symbol": "EURUSD",
        "name": "EUR/USD",
        "status": "STREAMING",
        "last_ts": None,
        "last_update": datetime.now().strftime("%H:%M:%S"),
        "bid": 1.15243,
        "ask": 1.15255,
        "ticks_session": 0
    }
}

def get_or_fetch_initial_tick(symbol: str) -> Dict[str, Any]:
    """
    Returns the latest tick for a symbol from SQLite, or on-demand fetches real ticks
    from Dukascopy via Node script, or falls back to realistic instrument specifications.
    """
    s = symbol.upper().strip()
    spec = get_symbol_spec(s)

    # 1. Check SQLite first
    tick = get_latest_tick(s, DB_PATH)
    if tick:
        # Check if price seems corrupted (e.g. 1.1 legacy fallback for an index/crypto)
        if not (tick["bid"] < 10.0 and spec["default_price"] > 100.0):
            return tick

    # 2. Try fetching real recent ticks from Dukascopy via node script
    script_path = os.path.join(PROJECT_ROOT, "scripts", "get_recent_ticks.js")
    if os.path.exists(script_path):
        try:
            cmd = ["node", script_path, "--symbol", s.lower(), "--minutes", "180"]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=6)
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                if isinstance(data, list) and len(data) > 0:
                    batch = [
                        (r[0], s, float(r[2]), float(r[1]), float(r[4]), float(r[3]))
                        for r in data
                    ]
                    insert_ticks_batch(batch, DB_PATH)
                    last = data[-1]
                    return {
                        "timestamp": last[0],
                        "symbol": s,
                        "bid": float(last[2]),
                        "ask": float(last[1]),
                        "bid_volume": float(last[4]),
                        "ask_volume": float(last[3])
                    }
        except Exception as e:
            print(f"[MarketData] Live tick fetch failed for {s}: {e}")

    # 3. Fallback to realistic reference price from specification
    now_ts = int(time.time() * 1000)
    ref_price = spec["default_price"]
    digits = spec["digits"]
    unit = spec["unit"]
    pip = spec["pip_step"]
    spread_amt = spec["spread_points"] * (pip if unit == "pip" else 1.0)
    bid = round(ref_price, digits)
    ask = round(bid + spread_amt, digits)
    return {
        "timestamp": now_ts,
        "symbol": s,
        "bid": bid,
        "ask": ask,
        "bid_volume": 1.0,
        "ask_volume": 1.0
    }

def get_current_download_state() -> Dict[str, Any]:
    state = download_manager.get_state()
    active = state.get("active_jobs", [])
    if active:
        first = active[0]
        return {
            "is_running": True,
            "symbol": first.get("symbol", ""),
            "percent": first.get("percent", 0.0),
            "total_ticks": first.get("total_ticks_imported", 0),
            "auto": False,
            "status": first.get("status", "RUNNING"),
            "message": first.get("stitching_status", "Letöltés folyamatban..."),
            "job_id": first.get("job_id", "")
        }
    completed = state.get("completed_jobs", [])
    if completed:
        first = completed[0]
        return {
            "is_running": False,
            "symbol": first.get("symbol", ""),
            "percent": 100.0 if first.get("status") == "COMPLETED" else 0.0,
            "total_ticks": first.get("total_ticks_imported", 0),
            "auto": False,
            "status": first.get("status", "COMPLETED"),
            "message": first.get("message", ""),
            "job_id": first.get("job_id", "")
        }
    return {
        "is_running": False,
        "symbol": "",
        "percent": 0.0,
        "total_ticks": 0,
        "auto": False,
        "status": "IDLE",
        "message": "",
        "job_id": ""
    }

# --- Pydantic Models ---
class StreamActionRequest(BaseModel):
    symbol: str

class CreateAccountRequest(BaseModel):
    id: str
    name: str
    initial_balance: float = 10000.0
    currency: str = "USD"
    leverage: int = 100
    stream_symbols: Optional[List[str]] = []
    strategy_key: Optional[str] = None
    strategy_symbol: Optional[str] = None
    strategy_timeframe: Optional[str] = "1m"
    strategy_volume: Optional[float] = 0.1

class StartStrategyRequest(BaseModel):
    strategy_key: str
    account_id: str
    symbol: str = "EURUSD"
    timeframe: str = "1m"
    volume: float = 0.1

class StopStrategyRequest(BaseModel):
    strategy_id: str

class DeleteStrategyRequest(BaseModel):
    strategy_id: str

class BacktestRequest(BaseModel):
    strategy_key: str
    symbol: str = "EURUSD"
    timeframe: str = "1m"
    from_date: Optional[str] = None
    to_date: Optional[str] = None
    cash: float = 10000.0

class DownloadRequest(BaseModel):
    symbol: str = "EURUSD"
    from_date: str = "2026-03-01"
    to_date: str = "2026-03-08"
    chunk_days: int = 7

class StartGapDownloadRequest(BaseModel):
    symbol: str
    target_days: Optional[int] = 365

# --- Frontend Routes ---
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_path = os.path.join(TEMPLATES_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Dashboard template not found</h1>"

@app.get("/reports/{filename}")
async def serve_report(filename: str):
    file_path = os.path.join(REPORTS_DIR, filename)
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Riport fájl nem található")

# --- Accounts & Portfolio APIs ---
@app.get("/api/accounts")
async def get_accounts():
    accounts = broker.list_accounts()
    for acc in accounts:
        perf = broker.get_performance(acc["id"])
        acc.update(perf)
        active_for_acc = [
            {"strategy": r.strategy_key, "symbol": r.symbol, "timeframe": r.timeframe}
            for r in active_runners.values()
            if r.account_id == acc["id"] and r.is_running
        ]
        acc["active_strategies"] = active_for_acc
    return accounts

@app.post("/api/accounts")
async def create_account(req: CreateAccountRequest):
    try:
        acc = broker.create_account(
            account_id=req.id,
            name=req.name,
            initial_balance=req.initial_balance,
            currency=req.currency,
            leverage=req.leverage
        )

        # 1. Register requested stream symbols into active_streams
        symbols_to_stream = set(req.stream_symbols or [])
        if req.strategy_symbol:
            symbols_to_stream.add(req.strategy_symbol)

        for sym in symbols_to_stream:
            sym_clean = sym.upper().strip()
            if sym_clean and sym_clean not in active_streams:
                meta = get_instrument_by_symbol(sym_clean)
                name = meta["name"] if meta else sym_clean
                tick = get_or_fetch_initial_tick(sym_clean)
                active_streams[sym_clean] = {
                    "symbol": sym_clean,
                    "name": name,
                    "status": "STREAMING",
                    "last_ts": tick["timestamp"],
                    "last_update": datetime.now().strftime("%H:%M:%S"),
                    "bid": tick["bid"],
                    "ask": tick["ask"],
                    "ticks_session": 0
                }

        # 2. Automatically bind and launch strategy if provided
        if req.strategy_key and req.strategy_symbol:
            strat_sym = req.strategy_symbol.upper().strip()
            runner_key = f"{req.strategy_key}_{req.id}"
            if runner_key not in active_runners or not active_runners[runner_key].is_running:
                runner = LiveStrategyRunner(
                    strategy_key=req.strategy_key,
                    account_id=req.id,
                    symbol=strat_sym,
                    timeframe=req.strategy_timeframe or "1m",
                    volume=req.strategy_volume or 0.1,
                    db_path=DB_PATH
                )
                runner.start()
                active_runners[runner_key] = runner

        return acc
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/accounts/{account_id}")
async def delete_account_endpoint(account_id: str):
    # 1. Stop and remove any active strategy runners running on this account
    for runner_key, runner in list(active_runners.items()):
        if runner.account_id == account_id:
            try:
                runner.stop()
            except Exception:
                pass
            del active_runners[runner_key]

    # 2. Delete account and related records from database
    success = broker.delete_account(account_id)
    if not success:
        raise HTTPException(status_code=404, detail="Demó számla nem található")
    return {"status": "deleted", "account_id": account_id}

@app.post("/api/accounts/{account_id}/delete")
async def delete_account_post(account_id: str):
    return await delete_account_endpoint(account_id)

@app.get("/api/positions")
async def get_positions(account_id: Optional[str] = None):
    return broker.get_positions(account_id=account_id)

@app.post("/api/positions/{position_id}/close")
async def close_position(position_id: str):
    res = broker.close_position(position_id, close_reason="MANUAL")
    if not res:
        raise HTTPException(status_code=404, detail="Pozíció nem található")
    return res

@app.get("/api/trades")
async def get_trades(account_id: Optional[str] = None, limit: int = 100):
    return broker.get_trade_history(account_id=account_id, limit=limit)

# --- Strategies & Forward Testing APIs ---
@app.get("/api/strategies")
async def get_strategies():
    return get_available_strategies()

@app.get("/api/active-strategies")
async def get_active_strategies():
    conn = get_db_connection(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    SELECT s.*, a.name as account_name, a.balance, a.equity
    FROM active_strategies s
    LEFT JOIN demo_accounts a ON s.account_id = a.id
    ORDER BY s.started_at DESC;
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.post("/api/active-strategies/start")
async def start_strategy(req: StartStrategyRequest):
    runner_key = f"{req.strategy_key}_{req.account_id}"
    if runner_key in active_runners and active_runners[runner_key].is_running:
        return {"status": "already_running", "strategy_id": runner_key}

    try:
        runner = LiveStrategyRunner(
            strategy_key=req.strategy_key,
            account_id=req.account_id,
            symbol=req.symbol,
            timeframe=req.timeframe,
            volume=req.volume,
            db_path=DB_PATH
        )
        runner.start()
        active_runners[runner_key] = runner
        return {"status": "started", "strategy_id": runner_key}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/active-strategies/stop")
async def stop_strategy(req: StopStrategyRequest):
    runner_key = req.strategy_id
    if runner_key in active_runners:
        active_runners[runner_key].stop()
        del active_runners[runner_key]
        return {"status": "stopped", "strategy_id": runner_key}
    
    # In case it's in DB as running
    conn = get_db_connection(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE active_strategies SET status = 'STOPPED' WHERE strategy_id = ?;", (runner_key,))
    conn.commit()
    conn.close()
    return {"status": "stopped_in_db", "strategy_id": runner_key}

@app.delete("/api/active-strategies/{strategy_id}")
async def delete_active_strategy_endpoint(strategy_id: str):
    # 1. Stop and remove runner if running
    if strategy_id in active_runners:
        try:
            active_runners[strategy_id].stop()
        except Exception:
            pass
        del active_runners[strategy_id]

    # 2. Delete from SQLite database
    conn = get_db_connection(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM active_strategies WHERE strategy_id = ?;", (strategy_id,))
    deleted = c.rowcount > 0
    conn.commit()
    conn.close()

    return {"status": "deleted", "strategy_id": strategy_id, "deleted_from_db": deleted}

@app.post("/api/active-strategies/delete")
async def delete_active_strategy_post(req: DeleteStrategyRequest):
    return await delete_active_strategy_endpoint(req.strategy_id)

# --- Backtest APIs ---
@app.get("/api/backtests")
async def get_backtests():
    return list_backtest_runs(DB_PATH)

@app.post("/api/backtests/run")
async def execute_backtest(req: BacktestRequest):
    try:
        res = run_backtest(
            strategy_key=req.strategy_key,
            symbol=req.symbol,
            timeframe=req.timeframe,
            from_date=req.from_date,
            to_date=req.to_date,
            cash=req.cash,
            generate_plot=True,
            db_path=DB_PATH
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- Market Data & Ingestion APIs ---
@app.get("/api/market/stats")
async def get_market_stats(symbol: str = "EURUSD"):
    count = get_tick_count(symbol, DB_PATH)
    total_count = get_tick_count(None, DB_PATH)
    latest = get_latest_tick(symbol, DB_PATH)
    spread = None
    if latest:
        spread = round((float(latest["ask"]) - float(latest["bid"])) * 10000, 1)

    return {
        "symbol": symbol.upper(),
        "symbol_ticks": count,
        "total_ticks": total_count,
        "latest_tick": latest,
        "spread_pips": spread,
        "download_state": get_current_download_state()
    }

# --- Data Downloads & Smart Gap-Stitching APIs ---
@app.get("/api/downloads")
async def get_downloads_state():
    state = download_manager.get_state()
    streams_coverage = {}
    for sym in list(active_streams.keys()):
        streams_coverage[sym] = download_manager.get_symbol_coverage(sym)
    state["streams_coverage"] = streams_coverage
    return state

@app.post("/api/downloads/start")
async def start_gap_download_endpoint(req: StartGapDownloadRequest):
    sym = req.symbol.upper().strip()
    res = download_manager.start_gap_download(sym, target_days=req.target_days or 365)
    return res

@app.post("/api/downloads/{job_id}/stop")
async def stop_gap_download_endpoint(job_id: str):
    success = download_manager.stop_download(job_id)
    return {"status": "stopping" if success else "not_found", "job_id": job_id}

@app.get("/api/downloads/gaps/{symbol}")
async def get_symbol_gaps_endpoint(symbol: str):
    return download_manager.get_symbol_coverage(symbol, force_refresh=True)

@app.post("/api/market/download")
async def trigger_download(req: DownloadRequest):
    s = req.symbol.upper().strip()
    res = download_manager.start_gap_download(s, target_days=365)
    return res

@app.post("/api/market/download/stop")
async def stop_download():
    download_manager.stop_all()
    return {"status": "stopped", "message": "A letöltési folyamatok leállítása elindítva."}

# --- Instruments & Coverage APIs ---
@app.get("/api/instruments")
async def get_instruments_endpoint(search: Optional[str] = None, category: Optional[str] = None):
    all_inst = get_all_instruments()
    if category:
        all_inst = [i for i in all_inst if i.get("category") == category]
    if search:
        s = search.lower()
        all_inst = [i for i in all_inst if s in i.get("symbol", "").lower() or s in i.get("name", "").lower() or s in i.get("description", "").lower()]
    return all_inst[:200]

@app.get("/api/market/coverage")
async def get_market_coverage():
    coverage = get_historical_coverage(DB_PATH)
    # Enrich with instrument metadata if available
    for item in coverage:
        meta = get_instrument_by_symbol(item["symbol"])
        item["name"] = meta["name"] if meta else item["symbol"]
        item["category"] = meta.get("category", "Forex") if meta else "Forex"
    return coverage

@app.delete("/api/market/coverage/{symbol}")
async def delete_symbol_coverage(symbol: str):
    s = symbol.upper().strip()
    completed_one_year_symbols.discard(s)
    deleted = delete_symbol_ticks(s, DB_PATH)
    return {"status": "deleted", "symbol": s, "deleted_ticks": deleted}

def _enrich_stream_coverage(stream: Dict[str, Any]) -> Dict[str, Any]:
    s = dict(stream)
    sym = s.get("symbol", "").upper().strip()
    cov = download_manager.get_symbol_coverage(sym)
    job = next((j for j in download_manager.active_jobs.values() if j.get("symbol") == sym and j.get("status") in ("RUNNING", "STOPPING")), None)
    s["coverage_info"] = {
        "has_one_year": cov.get("has_one_year", False),
        "missing_days": cov.get("missing_days_count", 0),
        "coverage_pct": cov.get("coverage_pct", 0.0),
        "present_days": cov.get("present_days_count", 0),
        "total_ticks": cov.get("total_ticks", 0),
        "gaps_count": cov.get("total_gaps", 0),
        "is_downloading": job is not None,
        "job_status": job.get("status") if job else None,
        "job_percent": job.get("percent", 0.0) if job else 0.0,
        "active_job_id": job.get("job_id") if job else None
    }
    return s

# --- Multi-Ticker Live Streams Manager ---
@app.get("/api/market/live-streams")
async def get_live_streams():
    # Update latest prices for all active streams
    res = []
    for sym, stream in active_streams.items():
        spec = get_symbol_spec(sym)
        cur_bid = stream.get("bid")
        if cur_bid is None or cur_bid <= 0.0 or (cur_bid < 10.0 and spec["default_price"] > 100.0):
            tick = get_or_fetch_initial_tick(sym)
            stream["bid"] = tick["bid"]
            stream["ask"] = tick["ask"]
            stream["last_ts"] = tick["timestamp"]
            stream["last_update"] = datetime.now().strftime("%H:%M:%S")
        res.append(_enrich_stream_coverage(stream))
    return res

@app.post("/api/market/live-streams/start")
async def start_live_stream(req: StreamActionRequest):
    sym = req.symbol.upper().strip()
    meta = get_instrument_by_symbol(sym)
    name = meta["name"] if meta else sym
    tick = get_or_fetch_initial_tick(sym)

    active_streams[sym] = {
        "symbol": sym,
        "name": name,
        "status": "STREAMING",
        "last_ts": tick["timestamp"],
        "last_update": datetime.now().strftime("%H:%M:%S"),
        "bid": tick["bid"],
        "ask": tick["ask"],
        "ticks_session": 0
    }
    return {"status": "started", "symbol": sym}

@app.post("/api/market/live-streams/stop")
async def stop_live_stream(req: StreamActionRequest):
    sym = req.symbol.upper().strip()
    if sym in active_streams:
        del active_streams[sym]
    return {"status": "stopped", "symbol": sym}

def _get_pip_step(symbol: str) -> float:
    return get_symbol_spec(symbol)["pip_step"]

# Startup Hook
@app.on_event("startup")
async def on_startup():
    print("[ServerStartup] Engine started, ready for streaming and downloads.")

# --- Real-time WebSocket Feed ---
@app.websocket("/ws/live")
async def websocket_live_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        while True:
            # Send latest prices & stats for all active streams every second
            ticks_data = {}
            for sym in list(active_streams.keys()):
                stream = active_streams[sym]
                spec = get_symbol_spec(sym)
                pip = spec["pip_step"]
                digits = spec["digits"]
                unit = spec["unit"]

                cur_bid = stream.get("bid")
                if cur_bid is None or cur_bid <= 0.0 or (cur_bid < 10.0 and spec["default_price"] > 100.0):
                    tick = get_or_fetch_initial_tick(sym)
                    cur_bid = tick["bid"]
                    stream["bid"] = cur_bid
                    stream["ask"] = tick["ask"]

                # Continuous realistic micro-walk
                delta = random.choice([-0.2, -0.1, 0.0, 0.1, 0.2]) * pip
                new_bid = round(cur_bid + delta, digits)
                spread_amt = spec["spread_points"] * (pip if unit == "pip" else 1.0)
                new_ask = round(new_bid + spread_amt, digits)
                now_ts = int(time.time() * 1000)

                tick_obj = {
                    "timestamp": now_ts,
                    "symbol": sym,
                    "bid": new_bid,
                    "ask": new_ask,
                    "bid_volume": 1.0,
                    "ask_volume": 1.0
                }

                stream["bid"] = new_bid
                stream["ask"] = new_ask
                stream["last_ts"] = now_ts
                stream["last_update"] = datetime.fromtimestamp(now_ts / 1000).strftime("%H:%M:%S")
                stream["ticks_session"] = stream.get("ticks_session", 0) + 1

                ticks_data[sym] = tick_obj

                # Push tick to active runners for this symbol
                for runner in list(active_runners.values()):
                    if runner.is_running and runner.symbol == sym:
                        runner.on_tick(tick_obj)

            enriched_streams = [_enrich_stream_coverage(st) for st in active_streams.values()]

            accounts = broker.list_accounts()
            for acc in accounts:
                perf = broker.get_performance(acc["id"])
                acc.update(perf)
                active_for_acc = [
                    {"strategy": r.strategy_key, "symbol": r.symbol, "timeframe": r.timeframe}
                    for r in active_runners.values()
                    if r.account_id == acc["id"] and r.is_running
                ]
                acc["active_strategies"] = active_for_acc

            positions = broker.get_positions()
            trades = broker.get_trade_history(limit=50)

            conn = get_db_connection(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
            SELECT s.*, a.name as account_name 
            FROM active_strategies s
            LEFT JOIN demo_accounts a ON s.account_id = a.id
            ORDER BY s.started_at DESC;
            """)
            strat_rows = [dict(r) for r in cursor.fetchall()]
            conn.close()

            coverage = get_historical_coverage(DB_PATH)

            msg = {
                "type": "heartbeat",
                "timestamp": int(datetime.utcnow().timestamp() * 1000),
                "tick": get_latest_tick("EURUSD", DB_PATH),
                "active_streams": enriched_streams,
                "ticks": ticks_data,
                "accounts": accounts,
                "accounts_count": len(accounts),
                "open_positions": positions,
                "trades": trades,
                "active_strategies": strat_rows,
                "coverage_count": len(coverage),
                "download_state": get_current_download_state(),
                "download_jobs": download_manager.get_state()
            }
            await websocket.send_text(json.dumps(msg))
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        connected_websockets.remove(websocket)
    except Exception:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=True)

