"""Focused PHI battery for fast terminal iteration on majors.

Runs a small hypothesis set on a short window while caching prepared
frames once per symbol. Intended for disciplined PHI iteration, not broad
search.
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
from engines.phi import (
    PHI_PRESETS,
    PhiParams,
    check_golden_trigger,
    check_regime_gates,
    compute_scoring,
    compute_summary,
    detect_cluster,
    prefetch_symbol_universe,
    prepare_symbol_frames,
    scan_symbol,
)

log = logging.getLogger("phi_focus")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def _strip_downstream_cols(df: pd.DataFrame) -> pd.DataFrame:
    drop_prefixes = ("cluster_", "regime_ok", "trigger_", "phi_score", "omega_phi", "trend_alignment")
    keep = [c for c in df.columns if not any(c == p or c.startswith(p) for p in drop_prefixes)]
    return df[keep].copy()


def _edge_score(summary: dict, min_trades: int = 30) -> float:
    n = int(summary.get("total_trades", 0) or 0)
    if n == 0:
        return -999.0
    if not summary.get("metrics_reliable", False):
        return -100.0 + n
    sharpe = float(summary.get("sharpe", 0.0) or 0.0)
    dd = float(summary.get("max_drawdown", 0.0) or 0.0)
    return sharpe * (n / min_trades) ** 0.5 * max(0.0, 1.0 - dd)


def _run_combo(base_frames: dict[str, pd.DataFrame], params: PhiParams, initial_equity: float, days: int) -> tuple[dict, dict]:
    all_trades: list[dict] = []
    per_symbol: dict[str, dict] = {}
    for sym, base in base_frames.items():
        df = _strip_downstream_cols(base)
        df = detect_cluster(df, params)
        df = check_regime_gates(df, params)
        df = check_golden_trigger(df, params)
        df = compute_scoring(df, params)
        trades, vetos = scan_symbol(df, sym, params, initial_equity)
        sym_summary = compute_summary(trades, initial_equity, n_days=days)
        sym_summary["vetos"] = vetos
        per_symbol[sym] = sym_summary
        all_trades.extend(trades)
    summary = compute_summary(all_trades, initial_equity, n_days=days)
    return summary, per_symbol


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--basket", default="bluechip_active", help="Basket name from config.params.BASKETS")
    ap.add_argument("--symbols", default="", help="Optional comma-separated symbols; overrides --basket")
    ap.add_argument("--days", type=int, default=60, help="Lookback window in days")
    ap.add_argument("--end", default=None, help="Optional end date YYYY-MM-DD for displaced historical windows")
    ap.add_argument("--min-trades", type=int, default=30, help="Trade floor for edge score")
    ap.add_argument("--out", default="data/phi/focus_battery", help="Output directory")
    args = ap.parse_args()

    if args.symbols.strip():
        symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    else:
        symbols = list(BASKETS.get(args.basket, []))
    if not symbols:
        raise SystemExit(f"Unknown or empty basket: {args.basket}")

    base = PhiParams()
    variants = [
        ("baseline", {}),
        ("cluster1", {"cluster_min_confluences": 1}),
        ("omega0382", {"omega_phi_entry": 0.382}),
        ("majors_candidate", dict(PHI_PRESETS["majors_candidate"])),
        ("trend_loose", {"ema200_distance_atr": 0.382}),
        ("wick_loose", {"wick_ratio_min": 0.382}),
        (
            "stagec_like",
            {
                "cluster_min_confluences": 1,
                "adx_min": 10.0,
                "ema200_distance_atr": 0.382,
                "wick_ratio_min": 0.382,
                "omega_phi_entry": 0.382,
            },
        ),
    ]

    log.info(
        "Preparing PHI base frames once: basket=%s symbols=%d days=%d end=%s",
        args.basket,
        len(symbols),
        args.days,
        args.end or "now",
    )
    t0 = time.time()
    prefetched, _n_candles_map = prefetch_symbol_universe(symbols, base, days=args.days, end=args.end)
    base_frames: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        merged = prepare_symbol_frames(sym, base, prefetched=prefetched, days=args.days, end=args.end)
        if merged is not None:
            base_frames[sym] = merged
    log.info("Base frame prep done in %.1fs (%d/%d symbols)", time.time() - t0, len(base_frames), len(symbols))
    if not base_frames:
        raise SystemExit("No symbols prepared for PHI battery")

    results = []
    for idx, (name, overrides) in enumerate(variants, 1):
        params = replace(base, **overrides)
        start = time.time()
        summary, per_symbol = _run_combo(base_frames, params, ACCOUNT_SIZE, args.days)
        elapsed = time.time() - start
        score = _edge_score(summary, min_trades=args.min_trades)
        results.append(
            {
                "variant": name,
                "overrides": overrides,
                "summary": summary,
                "score": score,
                "elapsed_s": round(elapsed, 2),
                "per_symbol_trades": {sym: data["total_trades"] for sym, data in per_symbol.items()},
            }
        )
        log.info(
            "[%d/%d] %s -> trades=%d sharpe=%.3f reliable=%s pnl=%+.2f dd=%.2f%% score=%.2f",
            idx,
            len(variants),
            name,
            summary["total_trades"],
            summary["sharpe"],
            summary["metrics_reliable"],
            summary["total_pnl"],
            summary["max_drawdown"] * 100.0,
            score,
        )

    results.sort(key=lambda item: item["score"], reverse=True)

    print("\n" + "=" * 120)
    print(f"  PHI FOCUS BATTERY - basket={args.basket} days={args.days} end={args.end or 'now'} symbols={len(base_frames)}")
    print("=" * 120)
    print(f"  {'variant':<14} {'trades':>7} {'reliable':>9} {'wr%':>6} {'sharpe':>8} {'maxdd%':>8} {'pnl':>12} {'score':>8}")
    print("  " + "-" * 118)
    for row in results:
        s = row["summary"]
        print(
            f"  {row['variant']:<14} {s['total_trades']:>7} {str(s['metrics_reliable']):>9} "
            f"{s['win_rate']*100:>5.1f} {s['sharpe']:>8.3f} {s['max_drawdown']*100:>7.2f} "
            f"{s['total_pnl']:>+12.2f} {row['score']:>8.2f}"
        )
    print("=" * 120)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = pd.Timestamp.now().strftime("%Y-%m-%d_%H%M%S")
    out_path = out_dir / f"phi_focus_{ts}.json"
    out_payload = {
        "basket": args.basket,
        "days": args.days,
        "end": args.end,
        "symbols": list(base_frames.keys()),
        "results": results,
    }
    out_path.write_text(json.dumps(out_payload, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
