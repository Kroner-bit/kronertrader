import os
import sys
import argparse
import uvicorn

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


from core.database import init_db, get_tick_count, DB_PATH
from core.dukascopy_downloader import download_historical_ticks
from backtesting_engine.runner import run_backtest
from strategies.run_strategy import main as run_strategy_cli

def main():
    parser = argparse.ArgumentParser(description="Nautilus Trader Platform & Forward-Test Engine")
    subparsers = parser.add_subparsers(dest="command", help="Végrehajtandó parancs")

    # Command: server (Default: Web Dashboard & API)
    server_parser = subparsers.add_parser("server", help="Központi Web Dashboard és API szerver indítása")
    server_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host cím")
    server_parser.add_argument("--port", type=int, default=8000, help="Port")

    # Command: download (Dukascopy historical tick download)
    dl_parser = subparsers.add_parser("download", help="Történeti tick adatok letöltése Dukascopy-ról SQLite-ba")
    dl_parser.add_argument("--symbol", type=str, default="EURUSD", help="Szimbólum (pl. EURUSD)")
    dl_parser.add_argument("--from-date", type=str, default="2025-03-01", help="Kezdő dátum (YYYY-MM-DD)")
    dl_parser.add_argument("--to-date", type=str, default="2026-03-01", help="Záró dátum (YYYY-MM-DD)")
    dl_parser.add_argument("--chunk-days", type=int, default=7, help="Darabolási napok száma")

    # Command: backtest (backtesting.py runner)
    bt_parser = subparsers.add_parser("backtest", help="Visszateszt futtatása a letöltött tick adatokon")
    bt_parser.add_argument("--strategy", type=str, default="ema_cross", help="Stratégia azonosítója (pl. ema_cross, rsi_reversal)")
    bt_parser.add_argument("--symbol", type=str, default="EURUSD", help="Szimbólum")
    bt_parser.add_argument("--timeframe", type=str, default="5m", help="Gyertya idősík (1m, 5m, 1h)")
    bt_parser.add_argument("--cash", type=float, default=10000.0, help="Kezdőtőke ($)")

    # Command: strategy (Standalone Forward Test CLI)
    strat_parser = subparsers.add_parser("strategy", help="Stratégia futtatása terminálból (Forward test)")
    strat_parser.add_argument("--strategy", type=str, default="ema_cross", help="Stratégia kulcsa")
    strat_parser.add_argument("--account", type=str, default="demo_main", help="Demó számla azonosítója")
    strat_parser.add_argument("--symbol", type=str, default="EURUSD", help="Szimbólum")
    strat_parser.add_argument("--timeframe", type=str, default="1m", help="Idősík")
    strat_parser.add_argument("--volume", type=float, default=0.1, help="Kötési méret")

    args = parser.parse_args()

    # Always ensure DB is initialized
    init_db(DB_PATH)

    if args.command == "download":
        print(f"Letöltés indítása: {args.symbol} ({args.from_date} -> {args.to_date})...")
        download_historical_ticks(
            symbol=args.symbol,
            from_date=args.from_date,
            to_date=args.to_date,
            chunk_days=args.chunk_days,
            db_path=DB_PATH
        )
    elif args.command == "backtest":
        print(f"Visszateszt indítása: {args.strategy} on {args.symbol} ({args.timeframe})...")
        res = run_backtest(
            strategy_key=args.strategy,
            symbol=args.symbol,
            timeframe=args.timeframe,
            cash=args.cash,
            db_path=DB_PATH
        )
        print("\n=== Eredmények ===")
        print(f"Hozam: {res['return_pct']}% | Sharpe: {res['sharpe_ratio']} | Win Rate: {res['win_rate_pct']}%")
        if res['report_file']:
            print(f"Interaktív Bokeh riport: reports/{res['report_file']}")
    elif args.command == "strategy":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        run_strategy_cli()
    else:
        # Default: Start server
        print("\n========================================================")
        print("🚀 NAUTILUS TRADING ENGINE & KÖZPONTI DASHBOARD INDÍTÁSA")
        print("========================================================")
        ticks = get_tick_count("EURUSD", DB_PATH)
        print(f"📊 SQLite adatbázis: {DB_PATH}")
        print(f"📈 Elérhető EURUSD tickek: {ticks:,} db")
        print(f"🌐 Dashboard URL: http://127.0.0.1:8000")
        print(f"📚 Swagger API dokumentáció: http://127.0.0.1:8000/docs")
        print("========================================================\n")
        uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
