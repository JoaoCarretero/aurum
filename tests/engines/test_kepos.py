"""Tests for engines/kepos.py — KEPOS critical endogeneity fade engine."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config.params import ACCOUNT_SIZE, LEVERAGE
from engines.kepos import (
    KeposParams,
    _eta_sustained_critical,
    _regime_exit_triggered,
    _resolve_exit,
    calc_levels,
    compute_features,
    compute_summary,
    decide_direction,
    kepos_size,
    run_backtest,
    scan_symbol,
)


# ════════════════════════════════════════════════════════════════════
# Synthetic data helpers
# ════════════════════════════════════════════════════════════════════

def _make_ohlcv(n: int = 4000, seed: int = 0, vol: float = 0.01,
                start_price: float = 100.0) -> pd.DataFrame:
    """OHLCV fixture with deterministic noise + realistic high/low."""
    rng = np.random.default_rng(seed)
    log_ret = rng.standard_normal(n) * vol
    close = start_price * np.exp(np.cumsum(log_ret))
    # Simple high/low: +/- tiny noise around close
    hi_noise = np.abs(rng.standard_normal(n)) * vol * 0.5
    lo_noise = np.abs(rng.standard_normal(n)) * vol * 0.5
    high = close * (1 + hi_noise)
    low = close * (1 - lo_noise)
    open_ = np.concatenate([[start_price], close[:-1]])
    time = pd.date_range("2025-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "time": time,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "vol": rng.uniform(100, 1000, size=n),
        "tbb": rng.uniform(50, 500, size=n),
    })


def _df_with_feature_columns(n: int = 300,
                             eta_values: np.ndarray | None = None,
                             ext_values: np.ndarray | None = None,
                             atr_values: np.ndarray | None = None,
                             atr_ratio_values: np.ndarray | None = None,
                             open_price: float = 100.0,
                             ) -> pd.DataFrame:
    """Minimal dataframe with only columns the entry-logic functions need,
    for deterministic unit tests."""
    if eta_values is None:
        eta_values = np.full(n, 0.5)
    if ext_values is None:
        ext_values = np.zeros(n)
    if atr_values is None:
        atr_values = np.full(n, 1.0)
    if atr_ratio_values is None:
        atr_ratio_values = np.ones(n)
    price = np.full(n, open_price, dtype=float)
    return pd.DataFrame({
        "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price,
        "eta_smooth": eta_values,
        "kepos_price_ext_sigma": ext_values,
        "kepos_atr_ratio": atr_ratio_values,
        "atr": atr_values,
    })


# ════════════════════════════════════════════════════════════════════
# kepos_size
# ════════════════════════════════════════════════════════════════════

def test_kepos_size_fixed_risk_pct():
    """size = equity * target_pct / |entry - stop|."""
    size = kepos_size(equity=10_000, entry=100.0, stop=98.0, target_pct=0.02)
    # target risk: $200; distance: 2 → 100 units
    assert size == pytest.approx(100.0, rel=1e-6)


def test_kepos_size_zero_on_degenerate_inputs():
    assert kepos_size(10_000, 100.0, 100.0, 0.02) == 0.0  # zero distance
    assert kepos_size(0, 100.0, 98.0, 0.02) == 0.0         # zero equity
    assert kepos_size(-10, 100.0, 98.0, 0.02) == 0.0       # negative equity
    assert kepos_size(float("nan"), 100.0, 98.0, 0.02) == 0.0


def test_kepos_size_respects_target_pct():
    small = kepos_size(10_000, 100.0, 98.0, target_pct=0.01)
    big = kepos_size(10_000, 100.0, 98.0, target_pct=0.04)
    assert big == pytest.approx(small * 4, rel=1e-6)


# ════════════════════════════════════════════════════════════════════
# decide_direction — the four required conditions
# ════════════════════════════════════════════════════════════════════

def test_decide_direction_requires_sustained_eta():
    """Spiking η once is not enough (must be sustained N bars)."""
    params = KeposParams(
        eta_sustained_bars=5, eta_critical=0.95,
        price_ext_sigma=2.0, atr_expansion_ratio=1.3,
    )
    eta = np.full(30, 0.90)
    eta[29] = 0.97  # only last bar crossed
    ext = np.full(30, 3.0)  # extension ok
    atr_r = np.full(30, 1.5)  # atr expansion ok
    df = _df_with_feature_columns(30, eta_values=eta, ext_values=ext,
                                  atr_ratio_values=atr_r)
    assert decide_direction(df, 29, params) == 0


def test_decide_direction_requires_price_extension():
    """With η sustained crit but extension subthreshold → no signal."""
    params = KeposParams(
        eta_sustained_bars=3, eta_critical=0.95,
        price_ext_sigma=2.0, atr_expansion_ratio=1.3,
    )
    eta = np.full(30, 0.97)
    ext = np.full(30, 1.5)   # below 2.0 threshold
    atr_r = np.full(30, 1.5)
    df = _df_with_feature_columns(30, eta_values=eta, ext_values=ext,
                                  atr_ratio_values=atr_r)
    assert decide_direction(df, 29, params) == 0


def test_decide_direction_requires_atr_expansion():
    """η crit + extended but ATR ratio low → no signal."""
    params = KeposParams(
        eta_sustained_bars=3, eta_critical=0.95,
        price_ext_sigma=2.0, atr_expansion_ratio=1.3,
    )
    eta = np.full(30, 0.97)
    ext = np.full(30, 3.0)
    atr_r = np.full(30, 1.0)  # no expansion
    df = _df_with_feature_columns(30, eta_values=eta, ext_values=ext,
                                  atr_ratio_values=atr_r)
    assert decide_direction(df, 29, params) == 0


def test_decide_direction_fades_positive_extension_to_short():
    """All conditions met, positive extension → SHORT (-1)."""
    params = KeposParams(
        eta_sustained_bars=3, eta_critical=0.95,
        price_ext_sigma=2.0, atr_expansion_ratio=1.3,
    )
    eta = np.full(30, 0.97)
    ext = np.full(30, 2.5)   # positive overextension
    atr_r = np.full(30, 1.5)
    df = _df_with_feature_columns(30, eta_values=eta, ext_values=ext,
                                  atr_ratio_values=atr_r)
    assert decide_direction(df, 29, params) == -1


def test_decide_direction_fades_negative_extension_to_long():
    params = KeposParams(
        eta_sustained_bars=3, eta_critical=0.95,
        price_ext_sigma=2.0, atr_expansion_ratio=1.3,
    )
    eta = np.full(30, 0.97)
    ext = np.full(30, -2.5)  # negative overextension
    atr_r = np.full(30, 1.5)
    df = _df_with_feature_columns(30, eta_values=eta, ext_values=ext,
                                  atr_ratio_values=atr_r)
    assert decide_direction(df, 29, params) == +1


def test_decide_direction_guards_nans():
    params = KeposParams(eta_sustained_bars=3)
    eta = np.full(30, 0.97)
    ext = np.full(30, 2.5)
    ext[29] = np.nan
    atr_r = np.full(30, 1.5)
    df = _df_with_feature_columns(30, eta_values=eta, ext_values=ext,
                                  atr_ratio_values=atr_r)
    assert decide_direction(df, 29, params) == 0


# ════════════════════════════════════════════════════════════════════
# calc_levels
# ════════════════════════════════════════════════════════════════════

def test_calc_levels_long_ordering():
    params = KeposParams(stop_atr_mult=1.2, tp_atr_mult=1.8)
    df = _df_with_feature_columns(10, atr_values=np.full(10, 2.0),
                                  open_price=100.0)
    levels = calc_levels(df, t=5, direction=+1, params=params)
    assert levels is not None
    entry, stop, tp = levels
    assert stop < entry < tp
    assert entry == pytest.approx(100.0)
    assert stop == pytest.approx(100.0 - 1.2 * 2.0)
    assert tp == pytest.approx(100.0 + 1.8 * 2.0)


def test_calc_levels_short_ordering():
    params = KeposParams(stop_atr_mult=1.2, tp_atr_mult=1.8)
    df = _df_with_feature_columns(10, atr_values=np.full(10, 2.0),
                                  open_price=100.0)
    levels = calc_levels(df, t=5, direction=-1, params=params)
    assert levels is not None
    entry, stop, tp = levels
    assert tp < entry < stop


def test_calc_levels_returns_none_for_zero_direction():
    df = _df_with_feature_columns(10)
    assert calc_levels(df, t=5, direction=0, params=KeposParams()) is None


def test_calc_levels_returns_none_at_end_of_df():
    df = _df_with_feature_columns(10)
    # t+1 must be < len(df)
    assert calc_levels(df, t=9, direction=+1, params=KeposParams()) is None


# ════════════════════════════════════════════════════════════════════
# Exit resolution
# ════════════════════════════════════════════════════════════════════

def test_resolve_exit_stop_takes_precedence():
    """When both stop and TP are crossed intrabar, stop wins (conservative)."""
    n = 20
    params = KeposParams(max_bars_in_trade=50, eta_exit=0.5,
                         eta_exit_sustained_bars=2)
    df = _df_with_feature_columns(n, eta_values=np.full(n, 0.9))
    # Craft bar where low≤stop and high≥tp simultaneously (long trade)
    df.loc[10, "low"] = 95.0     # stop at 96 → low 95 triggers stop
    df.loc[10, "high"] = 105.0   # tp at 104 → high 105 triggers tp
    res = _resolve_exit(df, bar_idx=10, entry_idx=5, direction=+1,
                        entry=100.0, stop=96.0, tp=104.0, params=params)
    assert res is not None
    reason, price = res
    assert reason == "stop"
    assert price == 96.0


def test_resolve_exit_takes_profit_when_only_tp_hit():
    n = 20
    params = KeposParams(max_bars_in_trade=50, eta_exit=0.5,
                         eta_exit_sustained_bars=2)
    df = _df_with_feature_columns(n, eta_values=np.full(n, 0.9))
    df.loc[10, "low"] = 99.0    # stop at 96, not hit
    df.loc[10, "high"] = 105.0  # tp at 104, hit
    res = _resolve_exit(df, bar_idx=10, entry_idx=5, direction=+1,
                        entry=100.0, stop=96.0, tp=104.0, params=params)
    assert res is not None
    reason, price = res
    assert reason == "tp"
    assert price == 104.0


def test_resolve_exit_time_stop_fires_at_max_bars():
    n = 100
    params = KeposParams(max_bars_in_trade=10, eta_exit=0.5,
                         eta_exit_sustained_bars=2)
    df = _df_with_feature_columns(n, eta_values=np.full(n, 0.9))
    # bar 15, entry 5 → duration 10 = MAX; no stop/tp hit (within [99,101])
    df.loc[15, "low"] = 99.5
    df.loc[15, "high"] = 100.5
    res = _resolve_exit(df, bar_idx=15, entry_idx=5, direction=+1,
                        entry=100.0, stop=98.0, tp=104.0, params=params)
    assert res is not None
    reason, _price = res
    assert reason == "time_stop"


def test_resolve_exit_regime_exit_requires_two_consecutive_below():
    """One bar below threshold is not enough."""
    n = 30
    params = KeposParams(max_bars_in_trade=100, eta_exit=0.85,
                         eta_exit_sustained_bars=2)
    eta = np.full(n, 0.90)
    eta[20] = 0.70  # isolated drop
    df = _df_with_feature_columns(n, eta_values=eta)
    df.loc[20, "low"] = 99.5
    df.loc[20, "high"] = 100.5
    res = _resolve_exit(df, bar_idx=20, entry_idx=10, direction=+1,
                        entry=100.0, stop=98.0, tp=104.0, params=params)
    assert res is None  # only one bar below, no regime exit yet


def test_resolve_exit_regime_exit_fires_after_two_below():
    n = 30
    params = KeposParams(max_bars_in_trade=100, eta_exit=0.85,
                         eta_exit_sustained_bars=2)
    eta = np.full(n, 0.90)
    eta[19] = 0.70
    eta[20] = 0.70
    df = _df_with_feature_columns(n, eta_values=eta)
    df.loc[20, "low"] = 99.5
    df.loc[20, "high"] = 100.5
    res = _resolve_exit(df, bar_idx=20, entry_idx=10, direction=+1,
                        entry=100.0, stop=98.0, tp=104.0, params=params)
    assert res is not None
    reason, _ = res
    assert reason == "regime_exit"


def test_eta_sustained_critical_needs_full_window():
    params = KeposParams(eta_sustained_bars=5, eta_critical=0.95)
    eta = np.array([0.80, 0.97, 0.97, 0.97, 0.97, 0.97])
    df = _df_with_feature_columns(6, eta_values=eta)
    # Last 5 bars are all >= 0.95 → True
    assert _eta_sustained_critical(df, t=5, params=params) is True
    # One of the 5 bars (index 4..5..etc) has 0.80 at bar 0, but we only
    # look at last 5 ending at t=4 → includes 0.80 → False
    assert _eta_sustained_critical(df, t=4, params=params) is False


def test_eta_sustained_critical_handles_nan():
    params = KeposParams(eta_sustained_bars=3, eta_critical=0.95)
    eta = np.array([np.nan, 0.97, 0.97, 0.97])
    df = _df_with_feature_columns(4, eta_values=eta)
    # window is [nan, 0.97, 0.97] → NaN present → False
    assert _eta_sustained_critical(df, t=2, params=params) is False


# ════════════════════════════════════════════════════════════════════
# compute_features — shape/contract only
# ════════════════════════════════════════════════════════════════════

def test_compute_features_adds_required_columns():
    df = _make_ohlcv(3500, seed=1)
    params = KeposParams(
        hawkes_window_bars=1000, hawkes_refit_every=250,
        hawkes_min_events=15, hawkes_vol_lookback=80,
    )
    out = compute_features(df, params)
    required = {
        "atr", "eta_raw", "eta_smooth", "kepos_cum_n",
        "kepos_price_ext_sigma", "kepos_atr_ratio",
    }
    assert required.issubset(out.columns)
    assert len(out) == len(df)


def test_compute_features_does_not_mutate_input():
    df = _make_ohlcv(800, seed=2)
    original_cols = set(df.columns)
    params = KeposParams(
        hawkes_window_bars=500, hawkes_refit_every=100,
        hawkes_min_events=10, hawkes_vol_lookback=50,
    )
    _ = compute_features(df, params)
    assert set(df.columns) == original_cols


# ════════════════════════════════════════════════════════════════════
# Backtest smoke
# ════════════════════════════════════════════════════════════════════

def test_compute_features_hmm_failure_does_not_mutate_shared_params(monkeypatch):
    import engines.kepos as kepos_mod

    df = _make_ohlcv(800, seed=22)
    params = KeposParams(
        hawkes_window_bars=500, hawkes_refit_every=100,
        hawkes_min_events=10, hawkes_vol_lookback=50,
        hmm_enabled=True,
    )

    monkeypatch.setattr(
        kepos_mod,
        "enrich_with_regime",
        lambda _df: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    _ = compute_features(df, params)
    assert params.hmm_enabled is True


def test_scan_symbol_smoke_returns_lists():
    df = _make_ohlcv(3500, seed=3)
    params = KeposParams(
        hawkes_window_bars=1000, hawkes_refit_every=200,
        hawkes_min_events=15, hawkes_vol_lookback=80,
    )
    df_feat = compute_features(df, params)
    trades, vetos = scan_symbol(df_feat, "SYNTH", params, ACCOUNT_SIZE)
    assert isinstance(trades, list)
    assert isinstance(vetos, dict)
    # Trades could be zero on pure noise — that's fine. Just no crash.
    for t in trades:
        assert set(t.keys()) >= {
            "symbol", "direction", "entry", "stop", "tp",
            "size", "pnl", "result", "exit_reason",
        }


def test_run_backtest_returns_summary_shape():
    df = _make_ohlcv(3500, seed=4)
    params = KeposParams(
        hawkes_window_bars=1000, hawkes_refit_every=200,
        hawkes_min_events=15, hawkes_vol_lookback=80,
    )
    trades, vetos, per_sym = run_backtest(
        {"SYNTH": df}, params=params, initial_equity=ACCOUNT_SIZE,
    )
    summary = compute_summary(trades, ACCOUNT_SIZE)
    assert set(summary.keys()) >= {
        "n_trades", "win_rate", "pnl", "roi_pct",
        "final_equity", "max_dd_pct", "sharpe", "sortino",
    }
    assert summary["n_trades"] == len(trades)


def test_run_backtest_size_respects_risk_cap():
    """No open trade should have size*entry-risk > max_pct_equity of equity."""
    df = _make_ohlcv(3500, seed=5, vol=0.02)
    params = KeposParams(
        hawkes_window_bars=1000, hawkes_refit_every=200,
        hawkes_min_events=15, hawkes_vol_lookback=80,
        max_pct_equity=0.02,
    )
    trades, _, _ = run_backtest({"SYNTH": df}, params, ACCOUNT_SIZE)
    for tr in trades:
        dist = abs(tr["entry"] - tr["stop"])
        size = tr["size"]
        risk = dist * size
        assert risk <= tr["account_at_entry"] * 0.021, (
            f"size breach: risk={risk:.2f} > cap"
        )


def test_compute_summary_empty_trades_returns_zeros():
    s = compute_summary([], ACCOUNT_SIZE)
    assert s["n_trades"] == 0
    assert s["pnl"] == 0.0
    assert s["final_equity"] == ACCOUNT_SIZE


# ════════════════════════════════════════════════════════════════════
# Contract
# ════════════════════════════════════════════════════════════════════

def test_kepos_registered_in_engines_dict():
    from config.engines import ENGINES
    assert "kepos" in ENGINES
    assert ENGINES["kepos"]["display"] == "KEPOS"


def test_kepos_script_path_exists():
    from config.engines import ENGINES
    script = ENGINES["kepos"]["script"]
    assert Path(script).exists(), f"{script} missing"


def test_kepos_not_in_frozen_until_validated():
    """KEPOS must NOT be in FROZEN_ENGINES (reserved for code-complete but
    not-yet-validated engines — KEPOS is new and expected to either prove
    out or be discarded)."""
    from config.params import FROZEN_ENGINES
    assert "KEPOS" not in FROZEN_ENGINES


def test_kepos_not_in_engine_intervals_yet():
    """Backtest-first discipline: KEPOS must not have tuned interval entry
    until overfit 6/6 validates edge."""
    from config.params import ENGINE_BASKETS, ENGINE_INTERVALS
    assert "KEPOS" not in ENGINE_INTERVALS
    assert "KEPOS" not in ENGINE_BASKETS
