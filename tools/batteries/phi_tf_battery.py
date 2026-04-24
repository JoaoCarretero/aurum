"""Compare PHI v2 timeframe stacks with disciplined batteries.

Runs a small set of native-vs-fractal hypotheses on the same symbol basket
and window so we can decide which stack deserves longer validation.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

from config.params import ACCOUNT_SIZE, BASKETS
from engines.phi import PHI_PRESETS, PhiParams, run_backtest

log = logging.getLogger("phi_tf_battery")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _edge_score(summary: dict, min_trades: int) -> float:
    n = int(summary.get("total_trades", 0) or 0)
    if n == 0:
        return -999.0
    if n < min_trades:
        return -200.0 + n
    sharpe = float(summary.get("sharpe", 0.0) or 0.0)
    pf = float(summary.get("profit_factor", 0.0) or 0.0)
    dd = float(summary.get("max_drawdown", 0.0) or 0.0)
    pnl = float(summary.get("total_pnl", 0.0) or 0.0)
    return sharpe * max(0.25, min(pf, 4.0)) * max(0.0, 1.0 - dd) + pnl / 1000.0


def _variants() -> list[tuple[str, dict]]:
    return [
        ("native_stack", dict(PHI_PRESETS["native_stack"])),
        (
            "native_stack_loose",
            dict(PHI_PRESETS["native_stack"]) | {
                "cluster_min_confluences": 1,
                "volume_mult": 1.0,
            },
        ),
        ("fractal_stack", dict(PHI_PRESETS["fractal_stack"])),
        (
            "fractal_stack_loose",
            dict(PHI_PRESETS["fractal_stack"]) | {
                "cluster_min_confluences": 1,
                "volume_mult": 1.0,
            },
        ),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basket", default="bluechip_active", help="Basket name from config.params.BASKETS")
    ap.add_argument("--symbols", default="", help="Optional comma-separated symbols; overrides --basket")
    ap.add_argument("--days", type=int, default=60, help="Lookback window in days")
    ap.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD")
    ap.add_argument("--min-trades", type=int, default=30, help="Trade floor for ranking")
    ap.add_argument("--out", default="data/phi/tf_battery", help="Output directory")
    ap.add_argument("--variants", default="", help="Optional comma-separated subset of variant names")
    args = ap.parse_args()

    if args.symbols.strip():
        symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    else:
        symbols = list(BASKETS.get(args.basket, []))
    if not symbols:
        raise SystemExit(f"Unknown or empty basket: {args.basket}")

    all_variants = _variants()
    if args.variants.strip():
        wanted = {item.strip() for item in args.variants.split(",") if item.strip()}
        variants = [(name, overrides) for name, overrides in all_variants if name in wanted]
    else:
        variants = all_variants
    if not variants:
        raise SystemExit("No matching variants selected")

    results = []
    for idx, (name, overrides) in enumerate(variants, 1):
        params = replace(PhiParams(), **overrides)
        start = time.time()
        trades, summary, per_symbol = run_backtest(
            symbols=symbols,
            params=params,
            initial_equity=ACCOUNT_SIZE,
            days=args.days,
            end=args.end,
            profile=True,
        )
        elapsed = time.time() - start
        score = _edge_score(summary, args.min_trades)
        results.append(
            {
                "variant": name,
                "overrides": overrides,
                "summary": summary,
                "score": score,
                "elapsed_s": round(elapsed, 2),
                "per_symbol_trades": {sym: data["total_trades"] for sym, data in per_symbol.items()},
                "n_trades_collected": len(trades),
            }
        )
        log.info(
            "[%d/%d] %s -> trades=%d sharpe=%.3f pf=%.3f dd=%.2f%% pnl=%+.2f score=%.2f",
            idx,
            len(variants),
            name,
            summary["total_trades"],
            float(summary.get("sharpe", 0.0) or 0.0),
            float(summary.get("profit_factor", 0.0) or 0.0),
            float(summary.get("max_drawdown", 0.0) or 0.0) * 100.0,
            float(summary.get("total_pnl", 0.0) or 0.0),
            score,
        )

    results.sort(key=lambda item: item["score"], reverse=True)

    print("\n" + "=" * 132)
    print(f"  PHI TF BATTERY - basket={args.basket} days={args.days} end={args.end or 'now'} symbols={len(symbols)}")
    print("=" * 132)
    print(f"  {'variant':<20} {'trades':>7} {'wr%':>6} {'sharpe':>8} {'pf':>7} {'maxdd%':>8} {'pnl':>12} {'score':>8}")
    print("  " + "-" * 130)
    for row in results:
        s = row["summary"]
        print(
            f"  {row['variant']:<20} {s['total_trades']:>7} {s['win_rate']*100:>5.1f} "
            f"{float(s.get('sharpe', 0.0) or 0.0):>8.3f} {float(s.get('profit_factor', 0.0) or 0.0):>7.3f} "
            f"{float(s.get('max_drawdown', 0.0) or 0.0)*100:>7.2f} {float(s.get('total_pnl', 0.0) or 0.0):>+12.2f} "
            f"{row['score']:>8.2f}"
        )
    print("=" * 132)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"phi_tf_battery_{ts}.json"
    out_path.write_text(
        json.dumps(
            {
                "basket": args.basket,
                "days": args.days,
                "end": args.end,
                "symbols": symbols,
                "results": results,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
