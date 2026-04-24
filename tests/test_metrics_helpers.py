"""Unit tests for core.metrics_helpers.compute_trade_metrics."""
from core.metrics_helpers import compute_trade_metrics


def test_empty_records_returns_zeros():
    m = compute_trade_metrics([])
    assert m["n_trades"] == 0
    assert m["wins"] == 0
    assert m["net_pnl"] == 0.0
    assert m["sharpe"] == 0.0


def test_primed_records_excluded():
    records = [
        {"primed": True, "pnl": 100.0, "strategy": "CITADEL"},
        {"primed": False, "pnl": 25.0, "strategy": "CITADEL"},
    ]
    m = compute_trade_metrics(records)
    assert m["n_trades"] == 1
    assert m["n_primed"] == 1
    assert m["net_pnl"] == 25.0


def test_per_engine_breakdown():
    records = [
        {"primed": False, "pnl": 10.0, "strategy": "CITADEL"},
        {"primed": False, "pnl": -5.0, "strategy": "JUMP"},
    ]
    m = compute_trade_metrics(records)
    assert m["per_engine"]["CITADEL"]["n_trades"] == 1
    assert m["per_engine"]["JUMP"]["net_pnl"] == -5.0


def test_account_size_override_affects_roi():
    records = [{"primed": False, "pnl": 100.0, "strategy": "X"}]
    m_10k = compute_trade_metrics(records, account_size=10_000.0)
    m_100k = compute_trade_metrics(records, account_size=100_000.0)
    assert round(m_10k["roi_pct"], 2) == 1.00
    assert round(m_100k["roi_pct"], 2) == 0.10
