from __future__ import annotations

import numpy as np

from engines import deshaw


def test_pair_has_edge_after_costs_accepts_large_deviation(monkeypatch):
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.001)
    monkeypatch.setattr(deshaw, "SPREAD", 0.001)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.001)
    monkeypatch.setattr(deshaw, "_MIN_EDGE_COST_MULT", 1.5)

    assert deshaw._pair_has_edge_after_costs(
        spread_deviation=3.0,
        notional_a=100.0,
        notional_b=100.0,
    ) is True


def test_pair_has_edge_after_costs_rejects_small_deviation(monkeypatch):
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.001)
    monkeypatch.setattr(deshaw, "SPREAD", 0.001)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.001)
    monkeypatch.setattr(deshaw, "_MIN_EDGE_COST_MULT", 1.5)

    assert deshaw._pair_has_edge_after_costs(
        spread_deviation=0.1,
        notional_a=100.0,
        notional_b=100.0,
    ) is False


def test_spread_state_at_idx_uses_supplied_beta_and_alpha(monkeypatch):
    monkeypatch.setattr(deshaw, "NEWTON_SPREAD_WINDOW", 20)

    a_close = np.array([10.0] * 19 + [15.0], dtype=float)
    b_close = np.array([10.0] * 20, dtype=float)

    state = deshaw._spread_state_at_idx(a_close, b_close, 19, beta=0.5, alpha=0.0, window=20)

    assert state is not None
    assert round(state["spread"], 4) == 10.0
    assert round(state["mean"], 4) == 5.25
    assert state["zscore"] > 1.9


def test_pair_has_economic_width_accepts_wide_spread(monkeypatch):
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.001)
    monkeypatch.setattr(deshaw, "SPREAD", 0.001)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.001)
    monkeypatch.setattr(deshaw, "_PAIR_EDGE_COST_MULT", 1.0)

    a = np.array([100.0, 110.0, 90.0, 115.0, 85.0], dtype=float)
    b = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=float)

    assert deshaw._pair_has_economic_width(a, b, beta=1.0, alpha=0.0) is True


def test_pair_has_economic_width_rejects_narrow_spread(monkeypatch):
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.001)
    monkeypatch.setattr(deshaw, "SPREAD", 0.001)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.001)
    monkeypatch.setattr(deshaw, "_PAIR_EDGE_COST_MULT", 1.0)

    a = np.array([100.0, 100.1, 99.9, 100.1, 99.9], dtype=float)
    b = np.array([100.0, 100.0, 100.0, 100.0, 100.0], dtype=float)

    assert deshaw._pair_has_economic_width(a, b, beta=1.0, alpha=0.0) is False
