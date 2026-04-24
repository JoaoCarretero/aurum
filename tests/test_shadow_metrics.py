"""Unit tests for _compute_trade_metrics in millennium_shadow."""
from tools.maintenance.millennium_shadow import _compute_trade_metrics


def test_empty_records_returns_zeros():
    m = _compute_trade_metrics([])
    assert m["n_trades"] == 0
    assert m["wins"] == 0
    assert m["net_pnl"] == 0.0
    assert m["sharpe"] == 0.0


def test_primed_records_excluded():
    records = [
        {"primed": True, "pnl": 100.0, "strategy": "CITADEL"},
        {"primed": True, "pnl": -50.0, "strategy": "CITADEL"},
        {"primed": False, "pnl": 25.0, "strategy": "CITADEL"},
    ]
    m = _compute_trade_metrics(records)
    assert m["n_primed"] == 2
    assert m["n_trades"] == 1
    assert m["net_pnl"] == 25.0


def test_sharpe_and_wr():
    records = [
        {"primed": False, "pnl": 10.0, "strategy": "X"},
        {"primed": False, "pnl": 20.0, "strategy": "X"},
        {"primed": False, "pnl": -5.0, "strategy": "X"},
        {"primed": False, "pnl": 15.0, "strategy": "X"},
    ]
    m = _compute_trade_metrics(records)
    assert m["n_trades"] == 4
    assert m["wins"] == 3
    assert m["losses"] == 1
    assert m["win_rate"] == 0.75
    # PF = 45 / 5 = 9
    assert m["profit_factor"] == 9.0
    assert m["net_pnl"] == 40.0
    assert m["sharpe"] > 0


def test_per_engine_breakdown():
    records = [
        {"primed": False, "pnl": 10.0, "strategy": "CITADEL"},
        {"primed": False, "pnl": -5.0, "strategy": "JUMP"},
        {"primed": False, "pnl": 20.0, "strategy": "CITADEL"},
    ]
    m = _compute_trade_metrics(records)
    assert "per_engine" in m
    assert m["per_engine"]["CITADEL"]["n_trades"] == 2
    assert m["per_engine"]["CITADEL"]["net_pnl"] == 30.0
    assert m["per_engine"]["JUMP"]["n_trades"] == 1
    assert m["per_engine"]["JUMP"]["net_pnl"] == -5.0


def test_maxdd_from_equity_curve():
    # Sequence: +100, -50, +30, -80, +20 → cum: 100, 50, 80, 0, 20
    # Peak = 100, lowest after peak = 0 → maxdd = 100
    records = [
        {"primed": False, "pnl": p, "strategy": "X"}
        for p in [100.0, -50.0, 30.0, -80.0, 20.0]
    ]
    m = _compute_trade_metrics(records)
    assert m["maxdd"] == 100.0
