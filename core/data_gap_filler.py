import os
import glob
import time
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
import threading

from core.database import (
    DB_PATH, get_db_connection, get_symbol_date_ranges, get_tick_count
)
from core.instruments import get_instrument_by_symbol
from core.dukascopy_downloader import import_csv_file_to_sqlite

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def analyze_symbol_gaps(
    symbol: str,
    target_days: int = 365,
    db_path: str = DB_PATH
) -> Dict[str, Any]:
    """
    Analyzes existing tick data in SQLite for `symbol` going backwards `target_days` from today.
    Identifies all missing date intervals (gaps) that need to be fetched.
    """
    sym = symbol.upper().strip()
    now = datetime.now()
    target_end = now.date()
    target_start = target_end - timedelta(days=target_days)

    # 1. Fetch all distinct dates present in SQLite for this symbol
    present_ranges = get_symbol_date_ranges(sym, db_path=db_path)
    present_dates = {r["date"] for r in present_ranges}
    total_ticks = get_tick_count(sym, db_path=db_path)

    # 2. Iterate day by day from target_start to target_end
    # Track missing date ranges (gaps)
    gaps: List[Dict[str, Any]] = []
    current_gap_start: Optional[datetime.date] = None
    missing_trading_days = 0
    total_calendar_days = (target_end - target_start).days

    curr = target_start
    while curr <= target_end:
        date_str = curr.strftime("%Y-%m-%d")
        # In FX, Saturday (weekday == 5) has no market quotes
        is_fx_weekend = (curr.weekday() == 5)

        if date_str not in present_dates:
            if not is_fx_weekend:
                missing_trading_days += 1
            if current_gap_start is None:
                current_gap_start = curr
        else:
            # Found data: close current gap if open
            if current_gap_start is not None:
                gap_days = (curr - current_gap_start).days
                if gap_days > 0:
                    gaps.append({
                        "from_date": current_gap_start.strftime("%Y-%m-%d"),
                        "to_date": curr.strftime("%Y-%m-%d"),
                        "days": gap_days
                    })
                current_gap_start = None

        curr += timedelta(days=1)

    # Close trailing gap if still open
    if current_gap_start is not None:
        gap_days = (target_end - current_gap_start).days + 1
        if gap_days > 0:
            gaps.append({
                "from_date": current_gap_start.strftime("%Y-%m-%d"),
                "to_date": target_end.strftime("%Y-%m-%d"),
                "days": gap_days
            })

    # Coverage percentage
    covered_days = max(0, total_calendar_days - missing_trading_days)
    coverage_pct = round(min(100.0, (covered_days / max(1, total_calendar_days)) * 100.0), 1)

    # Has full year: missing trading days <= 5 (allowing minor holiday closures)
    has_one_year = (missing_trading_days <= 5 and total_ticks >= 1000)

    # Earliest & latest ticks
    conn = get_db_connection(db_path)
    c = conn.cursor()
    c.execute("SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM ticks WHERE symbol = ?;", (sym,))
    ts_row = c.fetchone()
    conn.close()

    min_ts_str = "-"
    max_ts_str = "-"
    actual_span_days = 0.0
    if ts_row and ts_row["min_ts"] and ts_row["max_ts"]:
        min_ts = ts_row["min_ts"]
        max_ts = ts_row["max_ts"]
        min_ts_str = datetime.fromtimestamp(min_ts / 1000).strftime("%Y-%m-%d %H:%M")
        max_ts_str = datetime.fromtimestamp(max_ts / 1000).strftime("%Y-%m-%d %H:%M")
        actual_span_days = round((max_ts - min_ts) / (1000 * 86400), 1)

    return {
        "symbol": sym,
        "target_start": target_start.strftime("%Y-%m-%d"),
        "target_end": target_end.strftime("%Y-%m-%d"),
        "target_days": total_calendar_days,
        "present_days_count": len(present_dates),
        "missing_days_count": missing_trading_days,
        "coverage_pct": coverage_pct,
        "has_one_year": has_one_year,
        "gaps": gaps,
        "total_gaps": len(gaps),
        "total_ticks": total_ticks,
        "min_date": min_ts_str,
        "max_date": max_ts_str,
        "actual_span_days": actual_span_days
    }


def download_and_stitch_gaps(
    job_id: str,
    symbol: str,
    gaps: List[Dict[str, Any]],
    chunk_days: int = 14,
    db_path: str = DB_PATH,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    proc_holder: Optional[List[Any]] = None
) -> Dict[str, Any]:
    """
    Downloads exclusively the missing gaps in chunks, inserting them with INSERT OR IGNORE
    to seamlessly stitch into SQLite without duplicates.
    Provides real-time cancellation and integrity validation.
    """
    sym = symbol.upper().strip()
    meta = get_instrument_by_symbol(sym)
    inst_id = meta["id"] if meta and "id" in meta else sym.lower()

    temp_dir = os.path.join(PROJECT_ROOT, f"temp_stitch_{sym.lower()}_{job_id[:8]}")
    os.makedirs(temp_dir, exist_ok=True)

    total_gap_days = sum(g["days"] for g in gaps)
    if total_gap_days == 0:
        return {
            "job_id": job_id,
            "symbol": sym,
            "status": "COMPLETED",
            "total_ticks_imported": 0,
            "message": "Nincsenek hiányzó lyukak, a szimbólum lefedettsége teljes!"
        }

    total_ticks_imported = 0
    days_processed = 0
    was_cancelled = False

    print(f"[{job_id}] Indul az adatfoltozás: {sym} -> {len(gaps)} lyuk, összesen {total_gap_days} hiányzó nap.")

    for gap_idx, gap in enumerate(gaps):
        if cancel_check and cancel_check():
            was_cancelled = True
            break

        g_start = datetime.strptime(gap["from_date"], "%Y-%m-%d")
        g_end = datetime.strptime(gap["to_date"], "%Y-%m-%d")

        curr_start = g_start
        while curr_start < g_end:
            if cancel_check and cancel_check():
                was_cancelled = True
                break

            curr_end = min(curr_start + timedelta(days=chunk_days), g_end)
            chunk_from_str = curr_start.strftime("%Y-%m-%d")
            chunk_to_str = curr_end.strftime("%Y-%m-%d")

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
                        was_cancelled = True
                        try:
                            proc.kill()
                        except Exception:
                            pass
                        break
                    time.sleep(0.3)

                if proc_holder is not None:
                    proc_holder[0] = None

                if was_cancelled:
                    break

            except Exception as e:
                print(f"[{job_id}] Hiba a dukascopy-node futtatásakor: {e}")

            # Stitch & Import newly created CSVs into SQLite
            csv_files = glob.glob(os.path.join(temp_dir, f"*{inst_id}*.csv"))
            if not csv_files:
                csv_files = glob.glob(os.path.join(temp_dir, f"*{sym.lower()}*.csv"))
            if not csv_files:
                csv_files = glob.glob(os.path.join(temp_dir, "*.csv"))

            chunk_ticks = 0
            for csv_file in csv_files:
                imported = import_csv_file_to_sqlite(csv_file, symbol=sym, db_path=db_path)
                chunk_ticks += imported
                try:
                    os.remove(csv_file)
                except OSError:
                    pass

            total_ticks_imported += chunk_ticks
            chunk_span = (curr_end - curr_start).days
            days_processed += chunk_span
            pct = min(100.0, (days_processed / total_gap_days) * 100.0)

            print(f"[{job_id}] Beillesztve: {chunk_from_str} - {chunk_to_str} ({chunk_ticks:,} tick). Összesen: {total_ticks_imported:,} ({pct:.1f}%)")

            if progress_callback:
                progress_callback({
                    "job_id": job_id,
                    "symbol": sym,
                    "current_gap_index": gap_idx + 1,
                    "total_gaps": len(gaps),
                    "chunk_from": chunk_from_str,
                    "chunk_to": chunk_to_str,
                    "chunk_ticks": chunk_ticks,
                    "total_ticks_imported": total_ticks_imported,
                    "percent": round(pct, 1),
                    "stitching_status": f"Lyuk {gap_idx + 1}/{len(gaps)} foltozása: {chunk_from_str} -> {chunk_to_str}"
                })

            curr_start = curr_end

    # Clean temp dir
    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

    # Post-stitching integrity verification
    conn = get_db_connection(db_path)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as count, MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM ticks WHERE symbol = ?;", (sym,))
    v_row = c.fetchone()
    conn.close()

    final_ticks = v_row["count"] if v_row else 0
    min_ts = v_row["min_ts"] if v_row else None
    max_ts = v_row["max_ts"] if v_row else None

    from_str = datetime.fromtimestamp(min_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if min_ts else "-"
    to_str = datetime.fromtimestamp(max_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if max_ts else "-"
    days_span = round((max_ts - min_ts) / (1000 * 86400), 1) if (min_ts and max_ts) else 0.0

    return {
        "job_id": job_id,
        "symbol": sym,
        "status": "STOPPED" if was_cancelled else "COMPLETED",
        "total_ticks_imported": total_ticks_imported,
        "total_ticks_in_db": final_ticks,
        "from_date": from_str,
        "to_date": to_str,
        "duration_days": days_span,
        "stitching_verified": True,
        "message": "Adatfoltozás és illesztés leállítva (részleges adatok perzisztálva)." if was_cancelled else f"Sikeres adatfoltozás! {total_ticks_imported:,} új tick illesztve a meglévőkhöz."
    }


class DownloadManager:
    """
    Thread-safe manager for background data-gap filling and historical downloads.
    Tracks active jobs, allows per-job cancellation, stores history, and provides coverage status.
    """
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.active_jobs: Dict[str, Dict[str, Any]] = {}
        self.completed_jobs: List[Dict[str, Any]] = []
        self._cancel_events: Dict[str, threading.Event] = {}
        self._proc_holders: Dict[str, List[Any]] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._coverage_cache: Dict[str, Dict[str, Any]] = {}

    def get_symbol_coverage(self, symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        with self._lock:
            cached = self._coverage_cache.get(sym)
            if cached and not force_refresh and (time.time() - cached.get("_cached_at", 0) < 5.0):
                return dict(cached["data"])
        
        info = analyze_symbol_gaps(sym, target_days=365, db_path=self.db_path)
        with self._lock:
            self._coverage_cache[sym] = {
                "_cached_at": time.time(),
                "data": info
            }
        return info

    def start_gap_download(self, symbol: str, target_days: int = 365, chunk_days: int = 14) -> Dict[str, Any]:
        sym = symbol.upper().strip()
        with self._lock:
            # Check if there is already an active job for this symbol
            for j_id, j in self.active_jobs.items():
                if j.get("symbol") == sym and j.get("status") == "RUNNING":
                    return {
                        "status": "already_running",
                        "job_id": j_id,
                        "symbol": sym,
                        "message": f"A(z) {sym} letöltése már folyamatban van."
                    }

            job_id = f"job_{sym}_{int(time.time())}"
            cancel_ev = threading.Event()
            proc_h = [None]
            self._cancel_events[job_id] = cancel_ev
            self._proc_holders[job_id] = proc_h

            # Perform gap analysis first
            gaps_info = analyze_symbol_gaps(sym, target_days=target_days, db_path=self.db_path)

            job_record = {
                "job_id": job_id,
                "symbol": sym,
                "status": "RUNNING",
                "percent": 0.0,
                "total_ticks_imported": 0,
                "gaps": gaps_info["gaps"],
                "total_gaps": len(gaps_info["gaps"]),
                "current_gap_index": 1 if gaps_info["gaps"] else 0,
                "chunk_from": gaps_info["gaps"][0]["from_date"] if gaps_info["gaps"] else "-",
                "chunk_to": gaps_info["gaps"][0]["to_date"] if gaps_info["gaps"] else "-",
                "stitching_status": "Előkészítés és lyukak elemzése...",
                "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "missing_days_count": gaps_info["missing_days_count"],
                "coverage_pct": gaps_info["coverage_pct"]
            }
            self.active_jobs[job_id] = job_record

        def _worker():
            try:
                def _on_progress(p):
                    with self._lock:
                        if job_id in self.active_jobs:
                            self.active_jobs[job_id].update({
                                "percent": p.get("percent", 0.0),
                                "total_ticks_imported": p.get("total_ticks_imported", 0),
                                "current_gap_index": p.get("current_gap_index", 0),
                                "chunk_from": p.get("chunk_from", "-"),
                                "chunk_to": p.get("chunk_to", "-"),
                                "stitching_status": p.get("stitching_status", "")
                            })

                result = download_and_stitch_gaps(
                    job_id=job_id,
                    symbol=sym,
                    gaps=gaps_info["gaps"],
                    chunk_days=chunk_days,
                    db_path=self.db_path,
                    progress_callback=_on_progress,
                    cancel_check=lambda: cancel_ev.is_set(),
                    proc_holder=proc_h
                )

                with self._lock:
                    if job_id in self.active_jobs:
                        del self.active_jobs[job_id]
                    self._cancel_events.pop(job_id, None)
                    self._proc_holders.pop(job_id, None)
                    self._threads.pop(job_id, None)
                    self._coverage_cache.pop(sym, None)  # invalidate cache

                    self.completed_jobs.insert(0, {
                        "job_id": job_id,
                        "symbol": sym,
                        "status": result.get("status", "COMPLETED"),
                        "total_ticks_imported": result.get("total_ticks_imported", 0),
                        "total_ticks_in_db": result.get("total_ticks_in_db", 0),
                        "duration_days": result.get("duration_days", 0),
                        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "message": result.get("message", "")
                    })
                    self.completed_jobs = self.completed_jobs[:30]
            except Exception as e:
                print(f"[DownloadManager] Exception in worker {job_id}: {e}")
                with self._lock:
                    if job_id in self.active_jobs:
                        del self.active_jobs[job_id]
                    self._cancel_events.pop(job_id, None)
                    self._proc_holders.pop(job_id, None)
                    self._threads.pop(job_id, None)
                    self._coverage_cache.pop(sym, None)
                    self.completed_jobs.insert(0, {
                        "job_id": job_id,
                        "symbol": sym,
                        "status": "ERROR",
                        "total_ticks_imported": 0,
                        "completed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "message": f"Hiba: {str(e)}"
                    })

        t = threading.Thread(target=_worker, daemon=True, name=f"Downloader_{sym}")
        self._threads[job_id] = t
        t.start()

        return {
            "status": "started",
            "job_id": job_id,
            "symbol": sym,
            "gaps_count": len(gaps_info["gaps"]),
            "missing_days": gaps_info["missing_days_count"],
            "coverage_pct": gaps_info["coverage_pct"]
        }

    def stop_download(self, job_id: str) -> bool:
        with self._lock:
            target_id = job_id
            cancel_ev = self._cancel_events.get(target_id)
            proc_h = self._proc_holders.get(target_id)
            if not cancel_ev:
                # Check by symbol
                for j_id, j in list(self.active_jobs.items()):
                    if j.get("symbol") == job_id.upper().strip():
                        target_id = j_id
                        cancel_ev = self._cancel_events.get(target_id)
                        proc_h = self._proc_holders.get(target_id)
                        break

            if cancel_ev:
                cancel_ev.set()
                if proc_h and proc_h[0] is not None:
                    try:
                        proc_h[0].kill()
                    except Exception:
                        pass
                if target_id in self.active_jobs:
                    self.active_jobs[target_id]["status"] = "STOPPING"
                    self.active_jobs[target_id]["stitching_status"] = "Leállítás folyamatban és perzisztálás..."
                return True
            return False

    def stop_all(self):
        with self._lock:
            for j_id in list(self.active_jobs.keys()):
                ev = self._cancel_events.get(j_id)
                if ev:
                    ev.set()
                ph = self._proc_holders.get(j_id)
                if ph and ph[0] is not None:
                    try:
                        ph[0].kill()
                    except Exception:
                        pass

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active_jobs": list(self.active_jobs.values()),
                "completed_jobs": list(self.completed_jobs),
                "has_active": len(self.active_jobs) > 0
            }


download_manager = DownloadManager(db_path=DB_PATH)

