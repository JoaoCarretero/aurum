"""Backfill BTCUSDT OI/LS cache retroactively via Binance endTime pagination.

The Binance /futures/data/openInterestHist and /globalLongShortAccountRatio
endpoints accept endTime and return up to limit=500 observations at/before
that instant. They retain ~30 days of history; older endTimes return empty.

This script steps endTime backward in chunks of (limit-1)*period_ms so each
request fills an adjacent 5.2-day window. Stops when the API returns empty
or overlaps existing cache completely.

Usage:
    python tools/bridgewater_cache_backfill.py --symbols BTCUSDT --period 15m
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.sentiment import (
    fetch_open_interest,
    fetch_long_short_ratio,
    cached_coverage,
    _PERIOD_MS,
    _load_cached_frame,
)


def _earliest_contiguous_ts(kind: str, symbol: str, period: str) -> pd.Timestamp | None:
    """Find the earliest timestamp of the most-recent contiguous block.
    Isolated historical probes (e.g. a single row from 2023) are skipped.
    """
    cols = {
        "open_interest": ["time", "oi", "oi_value"],
        "long_short_ratio": ["time", "ls_ratio", "long_pct", "short_pct"],
    }[kind]
    df = _load_cached_frame(kind, symbol, period, cols)
    if df is None or df.empty:
        return None
    df = df.sort_values("time").reset_index(drop=True)
    df["gap"] = df["time"].diff()
    df["block"] = (df["gap"] > pd.Timedelta("1h")).cumsum()
    last_block = df[df["block"] == df["block"].max()]
    return last_block["time"].min()


def backfill_one(kind: str, symbol: str, period: str, limit: int, max_iterations: int = 20) -> int:
    """Step endTime backward in (limit-1) period steps until the API stops
    returning data or we've iterated max_iterations times.
    Returns the number of successful fetches.
    """
    fetch = fetch_open_interest if kind == "open_interest" else fetch_long_short_ratio
    period_ms = _PERIOD_MS[period]
    step_ms = (limit - 1) * period_ms

    cov0 = cached_coverage(kind, symbol, period)
    rows0 = cov0["rows"] if cov0 else 0
    start_ts = _earliest_contiguous_ts(kind, symbol, period)
    if start_ts is None:
        start_ts = pd.Timestamp.utcnow().tz_localize(None)
    print(f"  [{kind}] {symbol}: start cache = {rows0} rows, earliest_contiguous = {start_ts}")

    # Step endTime backward from (earliest_contiguous - 1 period)
    end_ms = int(start_ts.timestamp() * 1000) - period_ms
    successes = 0
    for i in range(max_iterations):
        df = fetch(symbol, period=period, limit=limit, end_time_ms=end_ms)
        cov = cached_coverage(kind, symbol, period)
        if cov is None:
            print(f"    iter {i}: API returned None at endTime={pd.Timestamp(end_ms, unit='ms')}")
            break
        delta = cov["rows"] - rows0
        if delta == 0:
            print(f"    iter {i}: no new rows (API at historical limit)")
            break
        print(f"    iter {i}: +{delta} rows, earliest now {cov['start']}")
        rows0 = cov["rows"]
        successes += 1
        end_ms -= step_ms
        time.sleep(0.3)
    return successes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="BTCUSDT",
                    help="Comma-separated list (default: BTCUSDT)")
    ap.add_argument("--period", default="15m")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--max-iterations", type=int, default=20)
    ap.add_argument("--kinds", default="open_interest,long_short_ratio")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]

    for sym in symbols:
        for kind in kinds:
            print(f"\n=== {kind} {sym} @{args.period} ===")
            backfill_one(kind, sym, args.period, args.limit, args.max_iterations)

    print("\nFinal coverage:")
    for sym in symbols:
        for kind in kinds:
            cov = cached_coverage(kind, sym, args.period)
            print(f"  {sym} {kind}: {cov}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
