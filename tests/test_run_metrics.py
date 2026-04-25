"""run_metrics — sharpe/win_rate/avg_R/sortino helpers."""
import math
import pytest

from core.analytics.run_metrics import (
    sharpe_rolling, win_rate, avg_r_multiple, sortino,
)


def test_win_rate_basic():
    trades = [{"pnl_usd": 1}, {"pnl_usd": -1}, {"pnl_usd": 2}]
    assert win_rate(trades) == pytest.approx(2/3)


def test_win_rate_empty():
    assert win_rate([]) == 0.0


def test_avg_r_multiple_basic():
    trades = [{"r_multiple": 1.5}, {"r_multiple": -1.0}, {"r_multiple": 2.0}]
    assert avg_r_multiple(trades) == pytest.approx(0.833, abs=0.01)


def test_sharpe_rolling_constant_returns():
    """All-zero std → sharpe defined as 0 (avoid div by zero)."""
    trades = [{"pnl_usd": 1, "ts_close": "2026-04-24T18:00:00Z"}] * 5
    assert sharpe_rolling(trades) == 0.0


def test_sharpe_rolling_basic():
    trades = [
        {"pnl_usd": 1.0, "ts_close": "2026-04-24T18:00:00Z"},
        {"pnl_usd": 2.0, "ts_close": "2026-04-24T19:00:00Z"},
        {"pnl_usd": -1.0, "ts_close": "2026-04-24T20:00:00Z"},
        {"pnl_usd": 1.5, "ts_close": "2026-04-24T21:00:00Z"},
    ]
    s = sharpe_rolling(trades)
    assert s is not None
    assert math.isfinite(s)


def test_sortino_only_downside_std():
    trades = [{"pnl_usd": 1}, {"pnl_usd": -1}, {"pnl_usd": 2}, {"pnl_usd": -2}]
    s = sortino(trades)
    assert s is not None
    assert math.isfinite(s)
