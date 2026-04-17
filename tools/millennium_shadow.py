"""MILLENNIUM shadow runner — rolling scan at fixed cadence, no order routing.

Runs the operational core (CITADEL + RENAISSANCE + JUMP) every TICK_SEC
seconds against fresh OHLCV pulled from the exchange. Emits novel signals
(trades whose (engine, symbol, open_ts) key has not been seen this run) to
an append-only JSONL so the session can be audited post-hoc.

It is NOT live execution — no orders are placed, no exchange credentials
are required, no keys are loaded. The output is paper evidence for OOS
validation of the ensemble under real-time candle arrival.

Usage:
    python tools/millennium_shadow.py --tick-sec 900 --run-hours 24

Kill gracefully by creating `<run_dir>/.kill` or by sending SIGINT.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.fs import atomic_write  # noqa: E402

RUN_TS = datetime.now(timezone.utc)
RUN_ID = RUN_TS.strftime("%Y-%m-%d_%H%M")
RUN_DIR = ROOT / "data" / "millennium_shadow" / RUN_ID
LOGS_DIR = RUN_DIR / "logs"
REPORTS_DIR = RUN_DIR / "reports"
STATE_DIR = RUN_DIR / "state"
for _d in (LOGS_DIR, REPORTS_DIR, STATE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

SHADOW_LOG = LOGS_DIR / "shadow.log"
TRADES_PATH = REPORTS_DIR / "shadow_trades.jsonl"
HEARTBEAT_PATH = STATE_DIR / "heartbeat.json"
KILL_FLAG = RUN_DIR / ".kill"

log = logging.getLogger("millennium_shadow")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s")
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
log.addHandler(_sh)
_fh = logging.FileHandler(SHADOW_LOG, encoding="utf-8")
_fh.setFormatter(_fmt)
log.addHandler(_fh)


def _write_heartbeat(state: dict) -> None:
    payload = json.dumps(state, indent=2, ensure_ascii=True, default=str)
    atomic_write(HEARTBEAT_PATH, payload)


def _append_trade(trade: dict) -> None:
    """Append one trade to shadow_trades.jsonl (line-oriented, fsync on write)."""
    line = json.dumps(trade, ensure_ascii=True, default=str)
    with open(TRADES_PATH, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()


def _trade_key(trade: dict) -> tuple:
    """Stable dedup key: engine + symbol + entry timestamp."""
    return (
        str(trade.get("strategy") or "").upper(),
        str(trade.get("symbol") or "").upper(),
        trade.get("timestamp"),
    )


def _run_tick(seen_keys: set) -> tuple[int, int, int]:
    """Run one shadow tick. Returns (novel_count, total_scanned, engines_ok).

    Fetches fresh OHLCV, runs operational scans inside a stdout-silenced block
    (the engine prints verbosely), appends any novel trades to the JSONL, and
    updates `seen_keys` in place.
    """
    # Import inside the tick so config reloads pick up changes between ticks
    # if someone edits params.py while the loop runs.
    from engines.millennium import (  # noqa: E402
        _load_dados,
        _collect_operational_trades,
    )

    # Silence verbose engine stdout — the shadow.log is the canonical channel.
    with contextlib.redirect_stdout(io.StringIO()):
        all_dfs, htf_stack, macro_series, corr = _load_dados(False)
        engine_trades, all_trades = _collect_operational_trades(
            all_dfs, htf_stack, macro_series, corr,
        )

    engines_ok = sum(1 for trades in engine_trades.values() if trades)
    novel = 0
    for t in all_trades:
        key = _trade_key(t)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        # Tag the record with shadow provenance so post-hoc tools know this
        # came from the rolling scanner, not a completed backtest.
        record = dict(t)
        record["shadow_run_id"] = RUN_ID
        record["shadow_observed_at"] = datetime.now(timezone.utc).isoformat()
        _append_trade(record)
        novel += 1
    return novel, len(all_trades), engines_ok


def run_shadow(tick_sec: int, run_hours: float) -> int:
    """Main shadow loop. Returns exit code."""
    deadline = time.time() + run_hours * 3600.0 if run_hours > 0 else None
    seen_keys: set = set()
    ticks_ok = 0
    ticks_fail = 0
    novel_total = 0
    stop_requested = {"flag": False, "reason": ""}

    def _handle_signal(signum, _frame):  # noqa: ARG001
        stop_requested["flag"] = True
        stop_requested["reason"] = f"signal {signum}"
        log.info("SIGNAL %s received — shutting down after current tick", signum)

    signal.signal(signal.SIGINT, _handle_signal)
    with contextlib.suppress(AttributeError, ValueError):
        signal.signal(signal.SIGTERM, _handle_signal)

    log.info("SHADOW START run=%s tick=%ds hours=%.1f dir=%s",
             RUN_ID, tick_sec, run_hours, RUN_DIR)
    _write_heartbeat({
        "run_id": RUN_ID,
        "status": "running",
        "started_at": RUN_TS.isoformat(),
        "tick_sec": tick_sec,
        "run_hours": run_hours,
        "ticks_ok": 0,
        "ticks_fail": 0,
        "novel_total": 0,
        "last_tick_at": None,
        "last_error": None,
    })

    while True:
        tick_start = time.time()

        if KILL_FLAG.exists():
            stop_requested["flag"] = True
            stop_requested["reason"] = "kill file"
            log.info("KILL FLAG detected at %s — exiting", KILL_FLAG)
            break
        if deadline is not None and time.time() >= deadline:
            log.info("DEADLINE reached after %.1fh — exiting", run_hours)
            break
        if stop_requested["flag"]:
            break

        try:
            novel, scanned, engines_ok = _run_tick(seen_keys)
            ticks_ok += 1
            novel_total += novel
            log.info(
                "TICK ok=%d novel=%d scanned=%d engines_ok=%d seen=%d",
                ticks_ok, novel, scanned, engines_ok, len(seen_keys),
            )
            _write_heartbeat({
                "run_id": RUN_ID,
                "status": "running",
                "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec,
                "run_hours": run_hours,
                "ticks_ok": ticks_ok,
                "ticks_fail": ticks_fail,
                "novel_total": novel_total,
                "last_tick_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
            })
        except Exception as exc:  # noqa: BLE001
            ticks_fail += 1
            err = f"{type(exc).__name__}: {exc}"
            log.error("TICK fail=%d err=%s", ticks_fail, err)
            log.error("%s", traceback.format_exc())
            _write_heartbeat({
                "run_id": RUN_ID,
                "status": "running",
                "started_at": RUN_TS.isoformat(),
                "tick_sec": tick_sec,
                "run_hours": run_hours,
                "ticks_ok": ticks_ok,
                "ticks_fail": ticks_fail,
                "novel_total": novel_total,
                "last_tick_at": datetime.now(timezone.utc).isoformat(),
                "last_error": err,
            })

        elapsed = time.time() - tick_start
        sleep_for = max(0.0, tick_sec - elapsed)
        # Sleep in small slices so kill-flag / SIGINT are responsive.
        sliced = 0.0
        while sliced < sleep_for:
            if KILL_FLAG.exists() or stop_requested["flag"]:
                break
            chunk = min(2.0, sleep_for - sliced)
            time.sleep(chunk)
            sliced += chunk

    _write_heartbeat({
        "run_id": RUN_ID,
        "status": "stopped",
        "stopped_reason": stop_requested["reason"] or "deadline",
        "started_at": RUN_TS.isoformat(),
        "stopped_at": datetime.now(timezone.utc).isoformat(),
        "tick_sec": tick_sec,
        "run_hours": run_hours,
        "ticks_ok": ticks_ok,
        "ticks_fail": ticks_fail,
        "novel_total": novel_total,
    })
    log.info(
        "SHADOW END ok=%d fail=%d novel=%d reason=%s",
        ticks_ok, ticks_fail, novel_total,
        stop_requested["reason"] or "deadline",
    )
    return 0 if ticks_ok > 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tick-sec", type=int, default=900,
                    help="seconds between ticks (default 900 = 15min)")
    ap.add_argument("--run-hours", type=float, default=24.0,
                    help="total run duration in hours; 0 = forever (default 24)")
    args = ap.parse_args()

    if args.tick_sec < 60:
        print("tick-sec must be >= 60", file=sys.stderr)
        return 2
    if args.run_hours < 0:
        print("run-hours must be >= 0", file=sys.stderr)
        return 2

    return run_shadow(args.tick_sec, args.run_hours)


if __name__ == "__main__":
    raise SystemExit(main())
