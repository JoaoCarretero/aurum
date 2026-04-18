"""Focused tuner for MILLENNIUM live-execution gate parameters.

Runs the expensive data scan once per window, then sweeps only the
portfolio-level execution-gate parameters to reduce overtrading/DD while
keeping edge quality.
"""
from __future__ import annotations

import argparse
import contextlib
import itertools
import io
import json
import logging
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _portfolio_summary(trades: list[dict], days: int, account_size: float) -> dict:
    from analysis.stats import calc_ratios, equity_stats
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {
            "n_trades": 0,
            "roi_pct": 0.0,
            "sharpe": None,
            "sortino": None,
            "max_dd_pct": 0.0,
            "total_pnl": 0.0,
        }
    closed.sort(key=lambda t: t.get("timestamp", ""))
    pnl_s = [t["pnl"] for t in closed]
    _, _, mdd_pct, _ = equity_stats(pnl_s)
    ratios = calc_ratios(pnl_s, n_days=days)
    return {
        "n_trades": len(closed),
        "roi_pct": round(sum(pnl_s) / account_size * 100, 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "max_dd_pct": round(mdd_pct, 2),
        "total_pnl": round(sum(pnl_s), 2),
    }


def _score(summary: dict, days: int) -> float:
    sharpe = float(summary.get("sharpe") or -9.0)
    roi = float(summary.get("roi_pct") or 0.0)
    dd = float(summary.get("max_dd_pct") or 0.0)
    trades = float(summary.get("n_trades") or 0.0)
    trades_per_day = trades / max(days, 1)
    return sharpe * 1.8 + roi * 0.04 - dd * 0.55 - trades_per_day * 0.85


def _diversity_bonus(trades: list[dict]) -> float:
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return -4.0
    counts = {}
    for t in closed:
        counts[t.get("strategy", "?")] = counts.get(t.get("strategy", "?"), 0) + 1
    total = len(closed)
    cit_share = counts.get("CITADEL", 0) / total
    active = sum(1 for n in counts.values() if n > 0)
    bonus = 0.0
    if active >= 3:
        bonus += 0.8
    if cit_share >= 0.08:
        bonus += 0.8
    elif cit_share <= 0.01:
        bonus -= 1.5
    return bonus


def _load_base_trades(ms, days: int):
    from tools.millennium_battery import _reset_millennium_globals
    _reset_millennium_globals(days, interval_minutes=15)
    root_logger = logging.getLogger()
    prev_root = root_logger.level
    prev_ms = ms.log.level
    root_logger.setLevel(logging.ERROR)
    ms.log.setLevel(logging.ERROR)
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            all_dfs, htf_stack, macro, corr = ms._load_dados(generate_plots=False)
            _, all_trades = ms._collect_operational_trades(all_dfs, htf_stack, macro, corr)
    finally:
        root_logger.setLevel(prev_root)
        ms.log.setLevel(prev_ms)
    return all_trades


def main() -> int:
    ap = argparse.ArgumentParser(description="Sweep MILLENNIUM live gate params")
    ap.add_argument("--windows", nargs="+", type=int, default=[90, 360])
    ap.add_argument("--account", type=float, default=10000.0)
    ap.add_argument("--out", default="data/millennium/live_tuner", help="Output directory")
    args = ap.parse_args()

    import engines.millennium as ms

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = ROOT / args.out / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    original = {
        "PORTFOLIO_EXECUTION_ENABLED": ms.PORTFOLIO_EXECUTION_ENABLED,
        "PORTFOLIO_MIN_WEIGHT": deepcopy(ms.PORTFOLIO_MIN_WEIGHT),
        "PORTFOLIO_CHALLENGER_RATIO": ms.PORTFOLIO_CHALLENGER_RATIO,
        "PORTFOLIO_CHALLENGER_MAX_GAP": ms.PORTFOLIO_CHALLENGER_MAX_GAP,
        "PORTFOLIO_GLOBAL_COOLDOWN_BARS": ms.PORTFOLIO_GLOBAL_COOLDOWN_BARS,
        "PORTFOLIO_STRATEGY_COOLDOWN_BARS": deepcopy(ms.PORTFOLIO_STRATEGY_COOLDOWN_BARS),
    }

    base_trades = {}
    for days in args.windows:
        print(f"loading window {days}d")
        base_trades[days] = _load_base_trades(ms, days)

    candidates = []
    for jump_min, ren_min, cit_min, challenger_ratio, challenger_gap, global_cd, jump_cd in itertools.product(
        (0.32, 0.36),
        (0.22, 0.26),
        (0.14, 0.18),
        (0.82, 0.92),
        (0.06, 0.10),
        (1, 3),
        (2, 4),
    ):
        if cit_min >= ren_min:
            continue
        candidates.append({
            "PORTFOLIO_MIN_WEIGHT": {
                "JUMP": jump_min,
                "RENAISSANCE": ren_min,
                "CITADEL": cit_min,
            },
            "PORTFOLIO_CHALLENGER_RATIO": challenger_ratio,
            "PORTFOLIO_CHALLENGER_MAX_GAP": challenger_gap,
            "PORTFOLIO_GLOBAL_COOLDOWN_BARS": global_cd,
            "PORTFOLIO_STRATEGY_COOLDOWN_BARS": {
                "JUMP": jump_cd,
                "RENAISSANCE": 2,
                "CITADEL": 2,
            },
        })

    results = []
    try:
        for idx, cfg in enumerate(candidates, start=1):
            ms.PORTFOLIO_EXECUTION_ENABLED = True
            ms.PORTFOLIO_MIN_WEIGHT = deepcopy(cfg["PORTFOLIO_MIN_WEIGHT"])
            ms.PORTFOLIO_CHALLENGER_RATIO = cfg["PORTFOLIO_CHALLENGER_RATIO"]
            ms.PORTFOLIO_CHALLENGER_MAX_GAP = cfg["PORTFOLIO_CHALLENGER_MAX_GAP"]
            ms.PORTFOLIO_GLOBAL_COOLDOWN_BARS = cfg["PORTFOLIO_GLOBAL_COOLDOWN_BARS"]
            ms.PORTFOLIO_STRATEGY_COOLDOWN_BARS = deepcopy(cfg["PORTFOLIO_STRATEGY_COOLDOWN_BARS"])

            per_window = {}
            agg_score = 0.0
            for days in args.windows:
                rew = ms.operational_core_reweight(base_trades[days])
                summary = _portfolio_summary(rew, days, args.account)
                per_window[str(days)] = summary
                agg_score += _score(summary, days) + _diversity_bonus(rew)
            result = {
                "rank_score": round(agg_score, 4),
                "config": deepcopy(cfg),
                "windows": per_window,
            }
            results.append(result)
            if idx % 25 == 0:
                print(f"swept {idx}/{len(candidates)}")
    finally:
        ms.PORTFOLIO_EXECUTION_ENABLED = original["PORTFOLIO_EXECUTION_ENABLED"]
        ms.PORTFOLIO_MIN_WEIGHT = original["PORTFOLIO_MIN_WEIGHT"]
        ms.PORTFOLIO_CHALLENGER_RATIO = original["PORTFOLIO_CHALLENGER_RATIO"]
        ms.PORTFOLIO_CHALLENGER_MAX_GAP = original["PORTFOLIO_CHALLENGER_MAX_GAP"]
        ms.PORTFOLIO_GLOBAL_COOLDOWN_BARS = original["PORTFOLIO_GLOBAL_COOLDOWN_BARS"]
        ms.PORTFOLIO_STRATEGY_COOLDOWN_BARS = original["PORTFOLIO_STRATEGY_COOLDOWN_BARS"]

    results.sort(key=lambda r: r["rank_score"], reverse=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    lines = [f"# MILLENNIUM live tuner - {ts}\n"]
    for i, row in enumerate(results[:10], start=1):
        lines.append(f"## #{i} score={row['rank_score']:.3f}\n")
        lines.append(f"`{json.dumps(row['config'], ensure_ascii=False)}`\n")
        for win, summary in row["windows"].items():
            lines.append(
                f"- {win}d: trades={summary['n_trades']} roi={summary['roi_pct']} "
                f"sharpe={summary['sharpe']} dd={summary['max_dd_pct']}\n"
            )
        lines.append("\n")
    (out_dir / "summary.md").write_text("".join(lines), encoding="utf-8")
    print(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
