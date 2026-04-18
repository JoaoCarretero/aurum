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


def test_runtime_snapshot_overrides_reflect_effective_cli_params(monkeypatch):
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_ENTRY", 3.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_EXIT", 0.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_STOP", 3.5)
    monkeypatch.setattr(deshaw, "NEWTON_COINT_PVALUE", 0.15)
    monkeypatch.setattr(deshaw, "NEWTON_HALFLIFE_MIN", 5)
    monkeypatch.setattr(deshaw, "NEWTON_HALFLIFE_MAX", 300)
    monkeypatch.setattr(deshaw, "NEWTON_SPREAD_WINDOW", 60)
    monkeypatch.setattr(deshaw, "NEWTON_RECALC_EVERY", 60)
    monkeypatch.setattr(deshaw, "NEWTON_MAX_HOLD", 72)
    monkeypatch.setattr(deshaw, "NEWTON_SIZE_MULT", 0.3)
    monkeypatch.setattr(deshaw, "NEWTON_MIN_PAIRS", 2)
    monkeypatch.setattr(deshaw, "INTERVAL", "1h")
    monkeypatch.setattr(deshaw, "SCAN_DAYS", 1095)
    monkeypatch.setattr(deshaw, "N_CANDLES", 26280)
    monkeypatch.setattr(deshaw, "LEVERAGE", 1.0)
    monkeypatch.setattr(deshaw, "SYMBOLS", ["BTCUSDT", "ETHUSDT"])

    snapshot = deshaw._apply_runtime_snapshot_overrides(
        {"NEWTON_ZSCORE_ENTRY": 2.0, "SYMBOLS": ["OLDUSDT"]},
        "bluechip_active",
    )

    assert snapshot["NEWTON_ZSCORE_ENTRY"] == 3.0
    assert snapshot["NEWTON_ZSCORE_EXIT"] == 0.0
    assert snapshot["NEWTON_COINT_PVALUE"] == 0.15
    assert snapshot["NEWTON_HALFLIFE_MAX"] == 300
    assert snapshot["NEWTON_MAX_HOLD"] == 72
    assert snapshot["INTERVAL"] == "1h"
    assert snapshot["SCAN_DAYS"] == 1095
    assert snapshot["N_CANDLES"] == 26280
    assert snapshot["SYMBOLS"] == ["BTCUSDT", "ETHUSDT"]
    assert snapshot["BASKET_EFFECTIVE"] == "bluechip_active"
