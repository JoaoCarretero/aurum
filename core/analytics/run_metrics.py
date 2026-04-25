"""Run-level performance helpers — shared entre engine_detail_view e cockpit.

Single source of truth pra evitar drift cross-screen. Hoje cockpit
calcula sharpe/win_rate inline em vários sites — esses callers devem
migrar pra cá em um follow-up.
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable


def win_rate(trades: Iterable[dict]) -> float:
    trades = list(trades)
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if (t.get("pnl_usd") or 0) > 0)
    return wins / len(trades)


def avg_r_multiple(trades: Iterable[dict]) -> float | None:
    rs = [t.get("r_multiple") for t in trades
          if t.get("r_multiple") is not None]
    if not rs:
        return None
    return sum(rs) / len(rs)


def sharpe_rolling(trades: Iterable[dict],
                   risk_free: float = 0.0) -> float | None:
    """Simple per-trade sharpe — annualised flag não aplica (curto-prazo).

    Returns 0.0 se std==0 (constant returns), None se < 2 trades.
    """
    pnls = [float(t.get("pnl_usd") or 0) for t in trades]
    if len(pnls) < 2:
        return None
    mean = statistics.mean(pnls) - risk_free
    std = statistics.pstdev(pnls)
    if std == 0:
        return 0.0
    s = mean / std
    return s if math.isfinite(s) else None


def sortino(trades: Iterable[dict], risk_free: float = 0.0) -> float | None:
    """Sortino ratio — only downside deviation no denominador."""
    pnls = [float(t.get("pnl_usd") or 0) for t in trades]
    if len(pnls) < 2:
        return None
    mean = statistics.mean(pnls) - risk_free
    downside = [p for p in pnls if p < 0]
    if not downside:
        return float("inf") if mean > 0 else 0.0
    dstd = math.sqrt(sum(p**2 for p in downside) / len(downside))
    if dstd == 0:
        return 0.0
    s = mean / dstd
    return s if math.isfinite(s) else None
