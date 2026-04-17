from __future__ import annotations

from engines import deshaw


def test_pair_pnl_includes_hedge_leg_profit(monkeypatch):
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.0)
    monkeypatch.setattr(deshaw, "SPREAD", 0.0)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.0)
    monkeypatch.setattr(deshaw, "FUNDING_PER_8H", 0.0)
    monkeypatch.setattr(deshaw, "LEVERAGE", 1.0)

    pnl = deshaw._pair_pnl(
        direction="BULLISH",
        beta=1.0,
        entry_a_raw=100.0,
        exit_a_raw=100.0,
        entry_b_raw=100.0,
        exit_b_raw=90.0,
        size_a=1.0,
        duration=0,
    )

    assert pnl == 10.0


def test_pair_pnl_penalizes_bearish_spread_when_hedge_leg_moves_wrong_way(monkeypatch):
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.0)
    monkeypatch.setattr(deshaw, "SPREAD", 0.0)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.0)
    monkeypatch.setattr(deshaw, "FUNDING_PER_8H", 0.0)
    monkeypatch.setattr(deshaw, "LEVERAGE", 1.0)

    pnl = deshaw._pair_pnl(
        direction="BEARISH",
        beta=1.0,
        entry_a_raw=100.0,
        exit_a_raw=100.0,
        entry_b_raw=100.0,
        exit_b_raw=90.0,
        size_a=1.0,
        duration=0,
    )

    assert pnl == -10.0
