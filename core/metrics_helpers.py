"""Shared metrics helpers for shadow/paper/live runners.

Extracted from tools/maintenance/millennium_shadow.py so paper runner
can reuse identical math. Behavior must stay identical — any drift
would make shadow and paper summary.json incomparable.
"""
from __future__ import annotations

import math


def compute_trade_metrics(records: list[dict], account_size: float | None = None) -> dict:
    """Compute backtest-style metrics from a list of trade records.

    Filters out records flagged `primed=True` (these are historical trades
    used only to populate the dedup set, not live detections). Returns a
    dict with n_trades, wins, losses, WR, PF, net_pnl, sharpe, sortino,
    maxdd, roi_pct + per_engine breakdown.

    `account_size` defaults to `config.params.ACCOUNT_SIZE` (10_000). Paper
    runner passes its configured account_size to make roi_pct meaningful
    for non-default account sizes.
    """
    live = [r for r in records if not r.get("primed", False)]
    n = len(live)
    base = {
        "n_trades": n,
        "n_primed": len(records) - n,
        "wins": 0, "losses": 0, "win_rate": 0.0, "profit_factor": 0.0,
        "net_pnl": 0.0, "mean_pnl": 0.0, "median_pnl": 0.0,
        "sharpe": 0.0, "sortino": 0.0, "maxdd": 0.0, "roi_pct": 0.0,
    }
    if n == 0:
        return base

    pnls = [float(r.get("pnl") or 0.0) for r in live]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p < 0)
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    net_pnl = sum(pnls)
    mean = net_pnl / n
    sorted_pnls = sorted(pnls)
    mid = n // 2
    median = sorted_pnls[mid] if n % 2 else (sorted_pnls[mid-1] + sorted_pnls[mid]) / 2.0

    if n >= 2:
        var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
        sd = math.sqrt(var) if var > 0 else 0.0
        sharpe = mean / sd if sd > 0 else 0.0
        downside = [p - mean for p in pnls if p < mean]
        dvar = sum(d * d for d in downside) / (n - 1) if downside else 0.0
        dsd = math.sqrt(dvar) if dvar > 0 else 0.0
        sortino = mean / dsd if dsd > 0 else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    peak = 0.0
    running = 0.0
    maxdd = 0.0
    for p in pnls:
        running += p
        if running > peak:
            peak = running
        dd = peak - running
        if dd > maxdd:
            maxdd = dd

    if account_size is None:
        try:
            from config.params import ACCOUNT_SIZE
            account_size = float(ACCOUNT_SIZE)
        except Exception:
            account_size = 10_000.0
    roi = (net_pnl / account_size * 100.0) if account_size > 0 else 0.0

    base.update({
        "wins": wins,
        "losses": losses,
        "win_rate": wins / n if n else 0.0,
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else float("inf") if gross_win > 0 else 0.0,
        "net_pnl": round(net_pnl, 2),
        "mean_pnl": round(mean, 2),
        "median_pnl": round(median, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "maxdd": round(maxdd, 2),
        "roi_pct": round(roi, 3),
    })

    by_eng: dict[str, list[float]] = {}
    for r in live:
        slug = str(r.get("strategy") or "unknown").upper()
        by_eng.setdefault(slug, []).append(float(r.get("pnl") or 0.0))
    per_engine = {}
    for slug, pp in by_eng.items():
        w = sum(1 for x in pp if x > 0)
        l = sum(1 for x in pp if x < 0)
        per_engine[slug] = {
            "n_trades": len(pp),
            "wins": w, "losses": l,
            "win_rate": w / len(pp) if pp else 0.0,
            "net_pnl": round(sum(pp), 2),
        }
    base["per_engine"] = per_engine
    return base
