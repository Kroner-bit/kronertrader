import os
import sys
import asyncio
import json
import threading
from datetime import datetime
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


from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

from core.database import DB_PATH, get_db_connection, get_latest_tick, get_tick_count, get_historical_coverage, delete_symbol_ticks
from core.paper_broker import PaperBroker
from core.dukascopy_downloader import download_historical_ticks
from core.instruments import get_all_instruments, get_instrument_by_symbol
from strategies.loader import get_available_strategies, get_strategy_by_key
from strategies.live_runner import LiveStrategyRunner
from backtesting_engine.runner import run_backtest, list_backtest_runs, REPORTS_DIR

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
        "ask": 1.15246,
        "ticks_session": 0
    }
}

# Background download state
download_state = {
    "is_running": False,
    "symbol": "",
    "percent": 0.0,
    "total_ticks": 0,
    "message": "Nincs aktív letöltés"
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

class StartStrategyRequest(BaseModel):
    strategy_key: str
    account_id: str
    symbol: str = "EURUSD"
    timeframe: str = "1m"
    volume: float = 0.1

class StopStrategyRequest(BaseModel):
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
        return acc
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

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
        "download_state": download_state
    }

def _bg_download_task(symbol: str, from_date: str, to_date: str, chunk_days: int):
    global download_state
    download_state["is_running"] = True
    download_state["symbol"] = symbol
    download_state["percent"] = 0.0
    download_state["message"] = f"Letöltés indítása: {symbol} ({from_date} - {to_date})..."

    def on_progress(p):
        download_state["percent"] = round(p["percent"], 1)
        download_state["total_ticks"] = p["total_ticks"]
        download_state["message"] = f"Letöltve: {p['chunk_from']} - {p['chunk_to']} ({p['chunk_ticks']:,} tick)"

    try:
        total = download_historical_ticks(
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            chunk_days=chunk_days,
            db_path=DB_PATH,
            progress_callback=on_progress
        )
        download_state["is_running"] = False
        download_state["percent"] = 100.0
        download_state["total_ticks"] = total
        download_state["message"] = f"Sikeres letöltés! Összesen {total:,} tick hozzáadva."
    except Exception as e:
        download_state["is_running"] = False
        download_state["message"] = f"Hiba a letöltés során: {str(e)}"

@app.post("/api/market/download")
async def trigger_download(req: DownloadRequest, background_tasks: BackgroundTasks):
    global download_state
    if download_state["is_running"]:
        raise HTTPException(status_code=400, detail="Már fut egy letöltési folyamat a háttérben.")

    background_tasks.add_task(_bg_download_task, req.symbol, req.from_date, req.to_date, req.chunk_days)
    return {"status": "started", "message": "Letöltés elindítva a háttérben."}

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
    deleted = delete_symbol_ticks(symbol, DB_PATH)
    return {"status": "deleted", "symbol": symbol.upper(), "deleted_ticks": deleted}

# --- Multi-Ticker Live Streams Manager ---
@app.get("/api/market/live-streams")
async def get_live_streams():
    # Update latest prices for all active streams from SQLite
    res = []
    for sym, stream in active_streams.items():
        tick = get_latest_tick(sym, DB_PATH)
        if tick:
            stream["bid"] = tick["bid"]
            stream["ask"] = tick["ask"]
            stream["last_ts"] = tick["timestamp"]
            stream["last_update"] = datetime.fromtimestamp(tick["timestamp"] / 1000).strftime("%H:%M:%S")
        res.append(stream)
    return res

@app.post("/api/market/live-streams/start")
async def start_live_stream(req: StreamActionRequest):
    sym = req.symbol.upper()
    meta = get_instrument_by_symbol(sym)
    name = meta["name"] if meta else sym
    tick = get_latest_tick(sym, DB_PATH)

    active_streams[sym] = {
        "symbol": sym,
        "name": name,
        "status": "STREAMING",
        "last_ts": tick["timestamp"] if tick else None,
        "last_update": datetime.now().strftime("%H:%M:%S"),
        "bid": tick["bid"] if tick else 0.0,
        "ask": tick["ask"] if tick else 0.0,
        "ticks_session": 0
    }
    return {"status": "started", "symbol": sym}

@app.post("/api/market/live-streams/stop")
async def stop_live_stream(req: StreamActionRequest):
    sym = req.symbol.upper()
    if sym in active_streams:
        del active_streams[sym]
    return {"status": "stopped", "symbol": sym}

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
                tick = get_latest_tick(sym, DB_PATH)
                if tick:
                    ticks_data[sym] = tick
                    active_streams[sym]["bid"] = tick["bid"]
                    active_streams[sym]["ask"] = tick["ask"]
                    active_streams[sym]["last_ts"] = tick["timestamp"]
                    active_streams[sym]["last_update"] = datetime.fromtimestamp(tick["timestamp"] / 1000).strftime("%H:%M:%S")

                    # Push tick to active runners for this symbol
                    for runner in list(active_runners.values()):
                        if runner.is_running and runner.symbol == sym:
                            runner.on_tick(tick)

            accounts = broker.list_accounts()
            positions = broker.get_positions()
            coverage = get_historical_coverage(DB_PATH)

            msg = {
                "type": "heartbeat",
                "timestamp": int(datetime.utcnow().timestamp() * 1000),
                "tick": get_latest_tick("EURUSD", DB_PATH),
                "active_streams": list(active_streams.values()),
                "ticks": ticks_data,
                "accounts_count": len(accounts),
                "open_positions": positions[:10],
                "coverage_count": len(coverage),
                "download_state": download_state
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

