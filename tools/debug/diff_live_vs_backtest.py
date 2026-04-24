"""Diagnose divergence between a live signal and the backtest-side scan.

Fetches OHLCV for the engine's native TF+basket, truncates the DF so the
signal candle sits inside both the `live_mode=True` and `live_mode=False`
scan windows, runs both paths, and prints a diff.

Use when a live runner (paper/shadow) opened a trade that the backtest
replay disagrees with (either rejects or never emits), to see which
filter drew the line differently.

Example:
    python tools/debug/diff_live_vs_backtest.py \\
        --engine renaissance --symbol RENDERUSDT \\
        --ts "2026-04-24 09:00:00" --entry 1.79399660758

Historical origin: 2026-04-24 RENAISSANCE LONG RENDERUSDT passed paper
(entry 1.794) but backtest replay rejected it on `hermes_entropy_random`
with norm=0.94. The live path must have observed norm<=0.92 at scan time
— but without persisting the raw value we couldn't reconstruct exactly
which close prices shifted the bucketing.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.params import BASKETS, ENGINE_BASKETS, ENGINE_INTERVALS, MACRO_SYMBOL  # noqa: E402
from core.data import fetch_all, validate  # noqa: E402
from core.portfolio import build_corr_matrix, detect_macro  # noqa: E402

ENGINE_SCAN_FN = {
    "citadel": ("engines.citadel", "azoth_scan"),
    "renaissance": ("core.harmonics", "scan_hermes"),
    "jump": ("engines.jump", "scan_mercurio"),
}


def _resolve_scan(engine: str):
    module_name, fn_name = ENGINE_SCAN_FN[engine.lower()]
    import importlib
    mod = importlib.import_module(module_name)
    return getattr(mod, fn_name)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", required=True,
                    choices=sorted(ENGINE_SCAN_FN.keys()),
                    help="Engine whose scanner to replay.")
    ap.add_argument("--symbol", required=True,
                    help="Target symbol, e.g. RENDERUSDT.")
    ap.add_argument("--ts", required=True,
                    help="Candle timestamp 'YYYY-MM-DD HH:MM:SS' UTC "
                         "(the bar that was D in the live signal).")
    ap.add_argument("--entry", type=float, default=None,
                    help="Optional live entry price for comparison.")
    ap.add_argument("--stop", type=float, default=None,
                    help="Optional live stop price for comparison.")
    ap.add_argument("--target", type=float, default=None,
                    help="Optional live target price for comparison.")
    ap.add_argument("--n-candles", type=int, default=8640,
                    help="Bars to fetch (default 8640 = 90d × 15m).")
    args = ap.parse_args()

    engine = args.engine.lower()
    engine_upper = engine.upper()
    scan_fn = _resolve_scan(engine)

    tf = ENGINE_INTERVALS.get(engine_upper, "15m")
    basket_name = ENGINE_BASKETS.get(engine_upper, "default")
    basket = BASKETS.get(basket_name, ["BTCUSDT", args.symbol])
    symbols = list(basket)
    if args.symbol not in symbols:
        symbols.append(args.symbol)
    if MACRO_SYMBOL and MACRO_SYMBOL not in symbols:
        symbols.insert(0, MACRO_SYMBOL)

    print(f"engine={engine_upper}  tf={tf}  basket_size={len(basket)}  "
          f"symbols={len(symbols)}")
    print(f"target: {args.symbol} @ {args.ts} UTC")
    if args.entry is not None:
        print(f"  live entry={args.entry}  stop={args.stop}  target={args.target}")
    print()

    with contextlib.redirect_stdout(io.StringIO()):
        all_dfs = fetch_all(symbols, interval=tf, n_candles=args.n_candles)
        for sym, df in all_dfs.items():
            validate(df, sym)
        macro_series = detect_macro(all_dfs)
        corr = build_corr_matrix(all_dfs)

    target_df = all_dfs.get(args.symbol)
    if target_df is None:
        print(f"FAIL: no data for {args.symbol}")
        return 1

    import pandas as pd
    signal_ts = pd.Timestamp(args.ts)
    signal_idx_rows = target_df[target_df["time"] == signal_ts].index
    if len(signal_idx_rows) == 0:
        print(f"FAIL: candle {args.ts} not found. First {target_df.iloc[0]['time']}  "
              f"last {target_df.iloc[-1]['time']}")
        return 1
    signal_i = int(signal_idx_rows[0])

    print(f"signal_bar_idx={signal_i}  last_bar_idx={len(target_df) - 1}")
    print()
    print(f"{args.symbol} OHLC around signal:")
    for i in range(max(0, signal_i - 2), min(len(target_df), signal_i + 5)):
        row = target_df.iloc[i]
        marker = " <-- D" if i == signal_i else ""
        print(f"  i={i}  t={row['time']}  o={row['open']:.8f}  "
              f"h={row['high']:.8f}  l={row['low']:.8f}  c={row['close']:.8f}{marker}")
    print()

    # Scan with live_mode=True on a df truncated to signal_i + 1 (= the bar
    # right after D, used for entry). This is the state the live runner
    # saw when it scanned ~23min after the candle close.
    cutoff_live = signal_i + 2
    df_live = {s: d.iloc[:cutoff_live].reset_index(drop=True) for s, d in all_dfs.items()}
    with contextlib.redirect_stdout(io.StringIO()):
        macro_live = detect_macro(df_live)
        corr_live = build_corr_matrix(df_live)
        trades_live, vetos_live = scan_fn(
            df_live[args.symbol], args.symbol, macro_live, corr_live, None,
            live_mode=True,
        )
    print(f"[LIVE scan  live_mode=True  cutoff=signal+2]")
    print(f"  trades={len(trades_live)}  vetos={dict(vetos_live) if vetos_live else {}}")
    for t in trades_live:
        ts = str(t.get("timestamp"))[:19]
        print(f"  ts={ts}  dir={t.get('direction'):<8}  entry={t.get('entry')}  "
              f"stop={t.get('stop')}  target={t.get('target')}")
        if "entropy_norm" in t:
            print(f"    entropy={t.get('entropy')}  "
                  f"entropy_norm={t.get('entropy_norm')}  "
                  f"hurst={t.get('hurst')}  score={t.get('score')}")
    print()

    # Scan with live_mode=False on full df (or all we have + fwd buffer).
    with contextlib.redirect_stdout(io.StringIO()):
        trades_bt, vetos_bt = scan_fn(
            target_df, args.symbol, macro_series, corr, None,
            live_mode=False,
        )
    print(f"[BACKTEST scan  live_mode=False  full df]")
    print(f"  trades={len(trades_bt)}  vetos={dict(vetos_bt) if vetos_bt else {}}")
    matches = [
        t for t in trades_bt
        if t.get("symbol") == args.symbol
        and args.ts in str(t.get("timestamp", ""))
    ]
    if not matches:
        print(f"  no trade matching ts={args.ts} in the backtest scan output.")
    for t in matches:
        ts = str(t.get("timestamp"))[:19]
        print(f"  ts={ts}  dir={t.get('direction'):<8}  entry={t.get('entry')}  "
              f"stop={t.get('stop')}  target={t.get('target')}  "
              f"result={t.get('result')}  pnl={t.get('pnl')}")
        if "entropy_norm" in t:
            print(f"    entropy={t.get('entropy')}  "
                  f"entropy_norm={t.get('entropy_norm')}  "
                  f"hurst={t.get('hurst')}  score={t.get('score')}")

    # Compare live vs backtest if both found the signal
    if trades_live and matches:
        tl, tb = trades_live[0], matches[0]
        print()
        print("=== diff (live vs backtest) ===")
        for key in ("entry", "stop", "target", "direction", "entropy",
                    "entropy_norm", "hurst", "score"):
            if key in tl or key in tb:
                vl, vb = tl.get(key), tb.get(key)
                marker = "" if vl == vb else "  ***"
                print(f"  {key:<14}  live={vl}  bt={vb}{marker}")
    elif trades_live and not matches:
        print()
        print("=== divergence: LIVE opened, BACKTEST rejected ===")
        print(f"  live trade: {trades_live[0]}")
        print(f"  bt vetos:   {dict(vetos_bt) if vetos_bt else {}}")
    elif matches and not trades_live:
        print()
        print("=== divergence: BACKTEST emitted, LIVE rejected ===")
        print(f"  bt trade:    {matches[0]}")
        print(f"  live vetos:  {dict(vetos_live) if vetos_live else {}}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
