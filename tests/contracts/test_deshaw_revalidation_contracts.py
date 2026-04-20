from __future__ import annotations

import pandas as pd

from engines import deshaw


def test_scan_pair_stops_new_entries_after_pair_decay(monkeypatch):
    n = 305
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    base = pd.DataFrame(
        {
            "time": idx,
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
            "vol": [1.0] * n,
            "tbb": [0.0] * n,
            "atr": [1.0] * n,
        }
    )
    hedge = pd.DataFrame(
        {
            "time": idx,
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
        }
    )
    merged = pd.DataFrame(
        {
            "time": idx,
            "a_open": [100.0] * n,
            "a_high": [100.0] * n,
            "a_low": [100.0] * n,
            "a_close": [100.0] * n,
            "a_vol": [1.0] * n,
            "a_tbb": [0.0] * n,
            "a_atr": [1.0] * n,
            "b_open": [100.0] * n,
            "b_high": [100.0] * n,
            "b_low": [100.0] * n,
            "b_close": [100.0] * n,
            "spread": [0.0] * n,
            "spread_mean": [0.0] * n,
            "spread_std_roll": [1.0] * n,
            "zscore": [0.0] * n,
        }
    )
    base.loc[200, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    base.loc[201, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
    base.loc[202, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    merged.loc[200, ["a_open", "a_high", "a_low", "a_close"]] = [130.0, 130.0, 130.0, 130.0]
    merged.loc[201, ["a_open", "a_high", "a_low", "a_close"]] = [100.0, 100.0, 100.0, 100.0]
    merged.loc[202, ["a_open", "a_high", "a_low", "a_close"]] = [130.0, 130.0, 130.0, 130.0]

    monkeypatch.setattr(deshaw, "indicators", lambda df: df)
    monkeypatch.setattr(deshaw, "swing_structure", lambda df: df)
    monkeypatch.setattr(deshaw, "calc_spread_zscore", lambda *args, **kwargs: merged.copy())
    monkeypatch.setattr(
        deshaw,
        "enrich_with_regime",
        lambda df: df.assign(
            hmm_regime_label=["CHOP"] * len(df),
            hmm_confidence=[0.5] * len(df),
            hmm_prob_bull=[0.0] * len(df),
            hmm_prob_bear=[0.0] * len(df),
            hmm_prob_chop=[1.0] * len(df),
        ),
    )
    monkeypatch.setattr(deshaw, "position_size", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr(deshaw, "check_aggregate_notional", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(deshaw, "_pair_has_edge_after_costs", lambda **kwargs: True)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_ENTRY", 2.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_EXIT", 0.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_STOP", 99.0)
    monkeypatch.setattr(deshaw, "NEWTON_SPREAD_WINDOW", 20)
    monkeypatch.setattr(deshaw, "NEWTON_MAX_HOLD", 20)
    monkeypatch.setattr(deshaw, "NEWTON_RECALC_EVERY", 1)
    monkeypatch.setattr(deshaw, "LEVERAGE", 1.0)
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.0)
    monkeypatch.setattr(deshaw, "SPREAD", 0.0)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.0)
    monkeypatch.setattr(deshaw, "FUNDING_PER_8H", 0.0)
    monkeypatch.setattr(deshaw, "TARGET_RR", 1.0)
    monkeypatch.setattr(deshaw, "DD_RISK_SCALE", {})
    monkeypatch.setattr(deshaw, "STREAK_COOLDOWN", {})
    monkeypatch.setattr(deshaw, "_MAX_REVALIDATION_MISSES", 0)

    calls = iter(
        [
            {"beta": 1.0, "alpha": 0.0, "half_life": 20.0, "pvalue": 0.01},
            None,
        ]
    )
    monkeypatch.setattr(deshaw, "_revalidate_pair_window", lambda *args, **kwargs: next(calls, None))

    trades, vetos = deshaw.scan_pair(
        base,
        hedge,
        "AAVEUSDT",
        "SOLUSDT",
        {"beta": 1.0, "alpha": 0.0, "half_life": 20.0, "pvalue": 0.01},
        pd.Series(["CHOP"] * n),
        {},
    )

    assert len(trades) == 1
    assert trades[0]["pair"] == "AAVEUSDT/SOLUSDT"
    assert vetos["pair_decay"] == 1
    assert vetos["pair_inactive"] >= 1


def test_scan_pair_allows_one_revalidation_grace_before_decay(monkeypatch):
    n = 305
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    base = pd.DataFrame(
        {
            "time": idx,
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
            "vol": [1.0] * n,
            "tbb": [0.0] * n,
            "atr": [1.0] * n,
        }
    )
    hedge = pd.DataFrame(
        {
            "time": idx,
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
        }
    )
    merged = pd.DataFrame(
        {
            "time": idx,
            "a_open": [100.0] * n,
            "a_high": [100.0] * n,
            "a_low": [100.0] * n,
            "a_close": [100.0] * n,
            "a_vol": [1.0] * n,
            "a_tbb": [0.0] * n,
            "a_atr": [1.0] * n,
            "b_open": [100.0] * n,
            "b_high": [100.0] * n,
            "b_low": [100.0] * n,
            "b_close": [100.0] * n,
            "spread": [0.0] * n,
            "spread_mean": [0.0] * n,
            "spread_std_roll": [1.0] * n,
            "zscore": [0.0] * n,
        }
    )
    base.loc[200, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    base.loc[201, ["open", "high", "low", "close"]] = [100.0, 100.0, 100.0, 100.0]
    base.loc[202, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    merged.loc[200, ["a_open", "a_high", "a_low", "a_close"]] = [130.0, 130.0, 130.0, 130.0]
    merged.loc[201, ["a_open", "a_high", "a_low", "a_close"]] = [100.0, 100.0, 100.0, 100.0]
    merged.loc[202, ["a_open", "a_high", "a_low", "a_close"]] = [130.0, 130.0, 130.0, 130.0]

    monkeypatch.setattr(deshaw, "indicators", lambda df: df)
    monkeypatch.setattr(deshaw, "swing_structure", lambda df: df)
    monkeypatch.setattr(deshaw, "calc_spread_zscore", lambda *args, **kwargs: merged.copy())
    monkeypatch.setattr(
        deshaw,
        "enrich_with_regime",
        lambda df: df.assign(
            hmm_regime_label=["CHOP"] * len(df),
            hmm_confidence=[0.5] * len(df),
            hmm_prob_bull=[0.0] * len(df),
            hmm_prob_bear=[0.0] * len(df),
            hmm_prob_chop=[1.0] * len(df),
        ),
    )
    monkeypatch.setattr(deshaw, "position_size", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr(deshaw, "check_aggregate_notional", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(deshaw, "_pair_has_edge_after_costs", lambda **kwargs: True)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_ENTRY", 2.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_EXIT", 0.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_STOP", 99.0)
    monkeypatch.setattr(deshaw, "NEWTON_SPREAD_WINDOW", 20)
    monkeypatch.setattr(deshaw, "NEWTON_MAX_HOLD", 20)
    monkeypatch.setattr(deshaw, "NEWTON_RECALC_EVERY", 1)
    monkeypatch.setattr(deshaw, "LEVERAGE", 1.0)
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.0)
    monkeypatch.setattr(deshaw, "SPREAD", 0.0)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.0)
    monkeypatch.setattr(deshaw, "FUNDING_PER_8H", 0.0)
    monkeypatch.setattr(deshaw, "TARGET_RR", 1.0)
    monkeypatch.setattr(deshaw, "DD_RISK_SCALE", {})
    monkeypatch.setattr(deshaw, "STREAK_COOLDOWN", {})
    monkeypatch.setattr(deshaw, "_MAX_REVALIDATION_MISSES", 1)

    refreshed = {"beta": 1.0, "alpha": 0.0, "half_life": 20.0, "pvalue": 0.01}
    calls = [refreshed, None, refreshed]
    state = {"i": 0}

    def _fake_revalidate(*args, **kwargs):
        i = state["i"]
        state["i"] += 1
        if i < len(calls):
            return calls[i]
        return refreshed

    monkeypatch.setattr(deshaw, "_revalidate_pair_window", _fake_revalidate)

    trades, vetos = deshaw.scan_pair(
        base,
        hedge,
        "AAVEUSDT",
        "SOLUSDT",
        {"beta": 1.0, "alpha": 0.0, "half_life": 20.0, "pvalue": 0.01},
        pd.Series(["CHOP"] * n),
        {},
    )

    assert len(trades) == 2
    assert vetos["pair_revalidation_grace"] >= 1
    assert vetos.get("pair_decay", 0) == 0

def test_scan_pair_applies_pair_cooldown_after_stop_loss(monkeypatch):
    n = 305
    idx = pd.date_range("2026-01-01", periods=n, freq="1h")
    base = pd.DataFrame(
        {
            "time": idx,
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
            "vol": [1.0] * n,
            "tbb": [0.0] * n,
            "atr": [1.0] * n,
        }
    )
    hedge = pd.DataFrame(
        {
            "time": idx,
            "open": [100.0] * n,
            "high": [100.0] * n,
            "low": [100.0] * n,
            "close": [100.0] * n,
        }
    )
    merged = pd.DataFrame(
        {
            "time": idx,
            "a_open": [100.0] * n,
            "a_high": [100.0] * n,
            "a_low": [100.0] * n,
            "a_close": [100.0] * n,
            "a_vol": [1.0] * n,
            "a_tbb": [0.0] * n,
            "a_atr": [1.0] * n,
            "b_open": [100.0] * n,
            "b_high": [100.0] * n,
            "b_low": [100.0] * n,
            "b_close": [100.0] * n,
            "spread": [0.0] * n,
            "spread_mean": [0.0] * n,
            "spread_std_roll": [1.0] * n,
            "zscore": [0.0] * n,
        }
    )
    base.loc[200, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    base.loc[201, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    base.loc[202, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    base.loc[203, ["open", "high", "low", "close"]] = [130.0, 130.0, 130.0, 130.0]
    merged.loc[200:203, ["a_open", "a_high", "a_low", "a_close"]] = [130.0, 130.0, 130.0, 130.0]

    monkeypatch.setattr(deshaw, "indicators", lambda df: df)
    monkeypatch.setattr(deshaw, "swing_structure", lambda df: df)
    monkeypatch.setattr(deshaw, "calc_spread_zscore", lambda *args, **kwargs: merged.copy())
    monkeypatch.setattr(
        deshaw,
        "enrich_with_regime",
        lambda df: df.assign(
            hmm_regime_label=["CHOP"] * len(df),
            hmm_confidence=[0.5] * len(df),
            hmm_prob_bull=[0.0] * len(df),
            hmm_prob_bear=[0.0] * len(df),
            hmm_prob_chop=[1.0] * len(df),
        ),
    )
    monkeypatch.setattr(deshaw, "position_size", lambda *args, **kwargs: 1.0)
    monkeypatch.setattr(deshaw, "check_aggregate_notional", lambda *args, **kwargs: (True, "ok"))
    monkeypatch.setattr(deshaw, "_pair_has_edge_after_costs", lambda **kwargs: True)
    monkeypatch.setattr(deshaw, "_revalidate_pair_window", lambda *args, **kwargs: {"beta": 1.0, "alpha": 0.0, "half_life": 20.0, "pvalue": 0.01})
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_ENTRY", 2.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_EXIT", 0.0)
    monkeypatch.setattr(deshaw, "NEWTON_ZSCORE_STOP", 3.0)
    monkeypatch.setattr(deshaw, "NEWTON_SPREAD_WINDOW", 20)
    monkeypatch.setattr(deshaw, "NEWTON_MAX_HOLD", 20)
    monkeypatch.setattr(deshaw, "NEWTON_RECALC_EVERY", 3)
    monkeypatch.setattr(deshaw, "LEVERAGE", 1.0)
    monkeypatch.setattr(deshaw, "SLIPPAGE", 0.0)
    monkeypatch.setattr(deshaw, "SPREAD", 0.0)
    monkeypatch.setattr(deshaw, "COMMISSION", 0.0)
    monkeypatch.setattr(deshaw, "FUNDING_PER_8H", 0.0)
    monkeypatch.setattr(deshaw, "TARGET_RR", 1.0)
    monkeypatch.setattr(deshaw, "DD_RISK_SCALE", {})
    monkeypatch.setattr(deshaw, "STREAK_COOLDOWN", {})

    trades, vetos = deshaw.scan_pair(
        base,
        hedge,
        "AAVEUSDT",
        "SOLUSDT",
        {"beta": 1.0, "alpha": 0.0, "half_life": 20.0, "pvalue": 0.01},
        pd.Series(["CHOP"] * n),
        {},
    )

    assert len(trades) == 1
    assert trades[0]["result"] == "LOSS"
    assert vetos["pair_stop_cooldown"] == 1
    assert vetos["pair_cooldown_active"] >= 1
