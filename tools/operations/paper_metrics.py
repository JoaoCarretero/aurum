"""Metrics streaming + sparkline helper for paper runner.

Wraps core.metrics_helpers.compute_trade_metrics with a stateful accumulator
of closed trades + equity timeline. Sparkline is a pure function used by
the cockpit UI to render an equity curve in one line of text.
"""
from __future__ import annotations

from core.metrics_helpers import compute_trade_metrics

SPARK_CHARS = "\u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"


def sparkline(values: list[float]) -> str:
    if not values:
        return ""
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 0:
        mid = SPARK_CHARS[len(SPARK_CHARS) // 2]
        return mid * len(values)
    out = []
    n_levels = len(SPARK_CHARS) - 1
    for v in values:
        ratio = (v - lo) / span
        idx = round(ratio * n_levels)
        idx = max(0, min(n_levels, idx))
        out.append(SPARK_CHARS[idx])
    return "".join(out)


class MetricsStreamer:
    def __init__(self, account_size: float = 10_000.0):
        self.account_size = account_size
        self._closed: list[dict] = []
        self._equity: list[dict] = []

    def record_closed(self, trade_dict: dict) -> None:
        self._closed.append(trade_dict)

    def record_equity_point(self, *, tick: int, ts: str, equity: float,
                            balance: float, realized: float, unrealized: float,
                            drawdown: float, positions_open: int) -> None:
        self._equity.append({
            "tick": tick, "ts": ts, "equity": round(equity, 2),
            "balance": round(balance, 2), "realized": round(realized, 2),
            "unrealized": round(unrealized, 2),
            "drawdown": round(drawdown, 2),
            "positions_open": positions_open,
        })

    def equity_points(self) -> list[dict]:
        return list(self._equity)

    def current_metrics(self) -> dict:
        return compute_trade_metrics(self._closed, account_size=self.account_size)
