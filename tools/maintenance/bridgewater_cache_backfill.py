"""Backfill BTCUSDT OI/LS cache retroactively via Binance endTime pagination."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.sentiment import (  # noqa: E402
    _PERIOD_MS,
    _load_cached_frame,
    cached_coverage,
    fetch_long_short_ratio,
    fetch_open_interest,
)


def earliest_contiguous_ts(
    kind: str,
    symbol: str,
    period: str,
    *,
    load_cached_frame=_load_cached_frame,
) -> pd.Timestamp | None:
    cols = {
        "open_interest": ["time", "oi", "oi_value"],
        "long_short_ratio": ["time", "ls_ratio", "long_pct", "short_pct"],
    }[kind]
    df = load_cached_frame(kind, symbol, period, cols)
    if df is None or df.empty:
        return None
    df = df.sort_values("time").reset_index(drop=True)
    df["gap"] = df["time"].diff()
    df["block"] = (df["gap"] > pd.Timedelta("1h")).cumsum()
    last_block = df[df["block"] == df["block"].max()]
    return last_block["time"].min()


def backfill_one(
    kind: str,
    symbol: str,
    period: str,
    limit: int,
    max_iterations: int = 20,
    *,
    fetch_open_interest_fn=fetch_open_interest,
    fetch_long_short_ratio_fn=fetch_long_short_ratio,
    cached_coverage_fn=cached_coverage,
    earliest_contiguous_ts_fn=earliest_contiguous_ts,
    sleep_fn=time.sleep,
) -> int:
    fetch = fetch_open_interest_fn if kind == "open_interest" else fetch_long_short_ratio_fn
    period_ms = _PERIOD_MS[period]
    step_ms = (limit - 1) * period_ms

    coverage = cached_coverage_fn(kind, symbol, period)
    rows_before = coverage["rows"] if coverage else 0
    start_ts = earliest_contiguous_ts_fn(kind, symbol, period)
    if start_ts is None:
        start_ts = pd.Timestamp.utcnow().tz_localize(None)
    print(f"  [{kind}] {symbol}: start cache = {rows_before} rows, earliest_contiguous = {start_ts}")

    end_ms = int(start_ts.timestamp() * 1000) - period_ms
    successes = 0
    for idx in range(max_iterations):
        fetch(symbol, period=period, limit=limit, end_time_ms=end_ms)
        coverage = cached_coverage_fn(kind, symbol, period)
        if coverage is None:
            print(f"    iter {idx}: API returned None at endTime={pd.Timestamp(end_ms, unit='ms')}")
            break
        delta = coverage["rows"] - rows_before
        if delta == 0:
            print(f"    iter {idx}: no new rows (API at historical limit)")
            break
        print(f"    iter {idx}: +{delta} rows, earliest now {coverage['start']}")
        rows_before = coverage["rows"]
        successes += 1
        end_ms -= step_ms
        sleep_fn(0.3)
    return successes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default="BTCUSDT", help="Comma-separated list (default: BTCUSDT)")
    parser.add_argument("--period", default="15m")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--max-iterations", type=int, default=20)
    parser.add_argument("--kinds", default="open_interest,long_short_ratio")
    args = parser.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]

    for symbol in symbols:
        for kind in kinds:
            print(f"\n=== {kind} {symbol} @{args.period} ===")
            backfill_one(kind, symbol, args.period, args.limit, args.max_iterations)

    print("\nFinal coverage:")
    for symbol in symbols:
        for kind in kinds:
            print(f"  {symbol} {kind}: {cached_coverage(kind, symbol, args.period)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
