import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import csv
import glob
import time
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Optional, Callable, Dict, Any

from core.database import DB_PATH, get_db_connection


def import_csv_file_to_sqlite(csv_path: str, symbol: str, db_path: str = DB_PATH, batch_size: int = 50000) -> int:
    """Reads a dukascopy-node generated CSV and inserts ticks into SQLite."""
    if not os.path.exists(csv_path):
        return 0

    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    count = 0
    batch = []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None) # skip header: timestamp,askPrice,bidPrice,askVolume,bidVolume
        for row in reader:
            if not row or len(row) < 5:
                continue
            try:
                ts = int(row[0])
                ask = float(row[1])
                bid = float(row[2])
                ask_vol = float(row[3])
                bid_vol = float(row[4])
                batch.append((ts, symbol.upper(), bid, ask, bid_vol, ask_vol))
                count += 1
                if len(batch) >= batch_size:
                    cursor.executemany(
                        "INSERT INTO ticks (timestamp, symbol, bid, ask, bid_volume, ask_volume) VALUES (?, ?, ?, ?, ?, ?);",
                        batch
                    )
                    conn.commit()
                    batch = []
            except (ValueError, IndexError):
                continue

    if batch:
        cursor.executemany(
            "INSERT INTO ticks (timestamp, symbol, bid, ask, bid_volume, ask_volume) VALUES (?, ?, ?, ?, ?, ?);",
            batch
        )
        conn.commit()

    conn.close()
    return count

def download_historical_ticks(
    symbol: str = "EURUSD",
    from_date: str = "2025-03-01",
    to_date: str = "2026-03-01",
    chunk_days: int = 7,
    db_path: str = DB_PATH,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    proc_holder: Optional[List[Any]] = None
) -> int:
    """
    Downloads historical ticks in manageable day chunks using dukascopy-node
    and imports them immediately into SQLite. Supports early cancellation.
    """
    start_dt = datetime.strptime(from_date, "%Y-%m-%d")
    end_dt = datetime.strptime(to_date, "%Y-%m-%d")
    total_days = (end_dt - start_dt).days
    if total_days <= 0:
        raise ValueError("to_date must be after from_date")

    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp_dl")
    os.makedirs(temp_dir, exist_ok=True)

    current_start = start_dt
    total_ticks_imported = 0
    days_processed = 0

    print(f"=== Starting Dukascopy download for {symbol.upper()} from {from_date} to {to_date} ({total_days} days) ===")

    while current_start < end_dt:
        if cancel_check and cancel_check():
            print(f"[DukascopyDownloader] Cancellation detected before chunk. Halting.")
            break

        current_end = min(current_start + timedelta(days=chunk_days), end_dt)
        chunk_from_str = current_start.strftime("%Y-%m-%d")
        chunk_to_str = current_end.strftime("%Y-%m-%d")

        print(f"\n[Chunk] Downloading {symbol.upper()} from {chunk_from_str} to {chunk_to_str}...")

        from core.instruments import get_instrument_by_symbol
        meta = get_instrument_by_symbol(symbol)
        inst_id = meta["id"] if meta and "id" in meta else symbol.lower()

        # Run dukascopy-node CLI
        cmd = [
            "npx", "-y", "dukascopy-node",
            "-i", inst_id,
            "-from", chunk_from_str,
            "-to", chunk_to_str,
            "-t", "tick",
            "-f", "csv",
            "-v",
            "-dir", temp_dir,
            "-s"
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
            if proc_holder is not None:
                proc_holder[0] = proc

            while proc.poll() is None:
                if cancel_check and cancel_check():
                    print(f"[DukascopyDownloader] Cancellation detected during chunk execution. Killing process.")
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                time.sleep(0.3)

            if proc_holder is not None:
                proc_holder[0] = None

            if cancel_check and cancel_check():
                break

        except Exception as e:
            print(f"Error running dukascopy-node: {e}")

        # Find generated CSV
        csv_files = glob.glob(os.path.join(temp_dir, f"*{inst_id}*.csv"))
        if not csv_files:
            csv_files = glob.glob(os.path.join(temp_dir, f"*{symbol.lower()}*.csv"))
        if not csv_files:
            csv_files = glob.glob(os.path.join(temp_dir, "*.csv"))

        chunk_ticks = 0
        for csv_file in csv_files:
            imported = import_csv_file_to_sqlite(csv_file, symbol=symbol.upper(), db_path=db_path)
            chunk_ticks += imported
            try:
                os.remove(csv_file)
            except OSError:
                pass

        total_ticks_imported += chunk_ticks
        chunk_span = (current_end - current_start).days
        days_processed += chunk_span
        pct = min(100.0, (days_processed / total_days) * 100.0)

        print(f"-> Imported {chunk_ticks:,} ticks for chunk. Total so far: {total_ticks_imported:,} ({pct:.1f}%)")

        if progress_callback:
            progress_callback({
                "symbol": symbol.upper(),
                "chunk_from": chunk_from_str,
                "chunk_to": chunk_to_str,
                "chunk_ticks": chunk_ticks,
                "total_ticks": total_ticks_imported,
                "percent": pct
            })

        current_start = current_end

    # Clean up temp directory
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

    print(f"\n=== Download complete! Total ticks stored: {total_ticks_imported:,} ===")
    return total_ticks_imported

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Download Dukascopy historical ticks into SQLite")
    parser.add_argument("--symbol", type=str, default="EURUSD", help="Symbol (e.g. EURUSD)")
    parser.add_argument("--from-date", type=str, default="2026-03-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--to-date", type=str, default="2026-03-05", help="End date (YYYY-MM-DD)")
    parser.add_argument("--chunk-days", type=int, default=7, help="Days per chunk")
    args = parser.parse_args()

    download_historical_ticks(
        symbol=args.symbol,
        from_date=args.from_date,
        to_date=args.to_date,
        chunk_days=args.chunk_days
    )
