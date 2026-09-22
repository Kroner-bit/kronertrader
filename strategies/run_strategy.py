import os
import sys
import time
import argparse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from strategies.live_runner import LiveStrategyRunner
from core.database import get_latest_tick

def main():
    parser = argparse.ArgumentParser(description="Run a trading strategy in live forward-test mode")
    parser.add_argument("--strategy", type=str, default="ema_cross", help="Strategy key (ema_cross, rsi_reversal)")
    parser.add_argument("--account", type=str, default="demo_main", help="Demo account ID")
    parser.add_argument("--symbol", type=str, default="EURUSD", help="Trading pair")
    parser.add_argument("--timeframe", type=str, default="1m", help="Candle timeframe")
    parser.add_argument("--volume", type=float, default=0.1, help="Lot volume")
    args = parser.parse_args()

    runner = LiveStrategyRunner(
        strategy_key=args.strategy,
        account_id=args.account,
        symbol=args.symbol,
        timeframe=args.timeframe,
        volume=args.volume
    )
    runner.start()

    print(f"=== Strategy Runner started for {args.strategy} on {args.account} ===")
    print("Press Ctrl+C to stop.")

    last_ts = 0
    try:
        while True:
            tick = get_latest_tick(args.symbol)
            if tick and tick["timestamp"] != last_ts:
                last_ts = tick["timestamp"]
                runner.on_tick(tick)
            time.sleep(1.0)
    except KeyboardInterrupt:
        runner.stop()
        print("Strategy Runner stopped.")

if __name__ == "__main__":
    main()
