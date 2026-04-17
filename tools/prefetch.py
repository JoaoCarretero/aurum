"""
AURUM Prefetch — warm local OHLCV cache from Binance.

Examples:
    python tools/prefetch.py --basket bluechip --days 3000
    python tools/prefetch.py --basket bluechip_active --days 1800 --interval 15m
    python tools/prefetch.py --spot --basket majors --days 90
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.params import BASKETS, INTERVAL, SYMBOLS, _TF_MINUTES  # noqa: E402
from core import cache, data as data_mod  # noqa: E402


def _resolve_symbols(basket: str) -> list[str]:
    if basket and basket in BASKETS:
        return list(BASKETS[basket])
    return list(SYMBOLS)


def main() -> int:
    ap = argparse.ArgumentParser(description="AURUM prefetch — OHLCV cache warmer")
    ap.add_argument("--basket", default="bluechip",
                    help="Basket name (default: bluechip)")
    ap.add_argument("--symbol", default=None,
                    help="Fetch a single symbol (overrides --basket)")
    ap.add_argument("--days", type=int, default=3000,
                    help="History depth in days (default: 3000)")
    ap.add_argument("--interval", default=INTERVAL,
                    help=f"Timeframe (default: {INTERVAL})")
    ap.add_argument("--spot", action="store_true",
                    help="Use spot klines (default: futures)")
    ap.add_argument("--workers", type=int, default=4,
                    help="Concurrent fetchers (default: 4 — rate-limit safe)")
    args = ap.parse_args()

    futures = not args.spot
    if args.symbol:
        symbols = [args.symbol.strip().upper()]
        target_label = f"symbol={symbols[0]}"
    else:
        symbols = _resolve_symbols(args.basket)
        target_label = f"basket={args.basket}"
    if not symbols:
        print(f"  basket '{args.basket}' unknown. options: {list(BASKETS)}")
        return 2

    tf_min = max(1, _TF_MINUTES.get(args.interval, 15))
    n_candles = int(args.days) * 24 * 60 // tf_min
    market = "SPOT" if args.spot else "FUTURES"

    print()
    print("  +-----------------------------------------------+")
    print("  | AURUM prefetch                                |")
    print("  +-----------------------------------------------+")
    print(f"  target       {target_label} ({len(symbols)} symbols)")
    print(f"  interval     {args.interval}  ({tf_min}m bars)")
    print(f"  depth        {args.days}d  ~{n_candles:,} bars/symbol")
    print(f"  market       {market}")
    print(f"  workers      {args.workers}")
    print(f"  cache_dir    {cache.CACHE_DIR.resolve()}")
    print()

    # Force live fetch during prefetch so we re-hit the API and refresh the
    # cache — reads would otherwise short-circuit on a partial slice.
    os.environ["AURUM_NO_CACHE"] = "1"
    t0 = time.time()
    ok_count = 0
    fail_count = 0
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = {
                ex.submit(data_mod.fetch, s, args.interval, n_candles, futures): s
                for s in symbols
            }
            for idx, fut in enumerate(as_completed(futs), start=1):
                sym = futs[fut]
                try:
                    df = fut.result()
                except Exception as e:
                    df = None
                    print(f"  [{sym:12s}]  FAIL  {e}")
                if df is None or df.empty:
                    fail_count += 1
                    print(f"  [{sym:12s}]  empty  ({idx}/{len(symbols)})")
                    continue
                # Data is back — now persist. Temporarily lift the bypass so
                # cache.write() is allowed; reinstate right after.
                os.environ.pop("AURUM_NO_CACHE", None)
                wrote = cache.write(sym, args.interval, df, futures)
                os.environ["AURUM_NO_CACHE"] = "1"
                span = (f"{df['time'].iloc[0].strftime('%Y-%m-%d')} -> "
                        f"{df['time'].iloc[-1].strftime('%Y-%m-%d')}")
                tag = "OK  " if wrote else "WARN"
                if wrote:
                    ok_count += 1
                else:
                    fail_count += 1
                print(f"  [{sym:12s}]  {tag}  {len(df):>6,} bars  "
                      f"{span}  ({idx}/{len(symbols)})")
    finally:
        os.environ.pop("AURUM_NO_CACHE", None)

    elapsed = time.time() - t0
    summary = cache.info()
    total_mb = summary["total_bytes"] / 1024 / 1024
    print()
    print(f"  done in {elapsed:.1f}s  |  ok={ok_count}  fail={fail_count}")
    print(f"  cache: {summary['n_files']} files  ~{total_mb:.1f} MB")
    print()
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
