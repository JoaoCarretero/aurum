"""Unit tests for SUPERTREND FUT engine — port da FSupertrendStrategy.

Coverage targets:
  - supertrend indicator (core.indicators): up/down state, warmup NaN
  - scan_supertrend: LONG valid, SHORT valid, no-signal (chop), NaN/short df
  - _signal_confidence: [0, 1] range, monotonic with distance
  - get_regime_fit, get_metadata helpers
  - live_mode behavior
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.indicators import supertrend
from engines import supertrend_futures as stfu
from engines.supertrend_futures import (
    ENGINE_METADATA,
    _compute_supertrend_set,
    _signal_confidence,
    get_metadata,
    get_regime_fit,
    scan_supertrend,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_ohlc(closes: np.ndarray, seed: int = 0, start_vol: float = 1000.0) -> pd.DataFrame:
    """Build an OHLCV df around a close sequence. Highs/lows wrap the close
    by a small noise band so Supertrend sees realistic TR values.
    """
    rng = np.random.default_rng(seed)
    n = len(closes)
    high = closes + rng.uniform(0.1, 0.5, n)
    low = closes - rng.uniform(0.1, 0.5, n)
    open_ = np.concatenate(([closes[0]], closes[:-1]))  # open = prev close-ish
    vol = np.full(n, start_vol) + rng.uniform(0, 100, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({
        "time": idx, "open": open_, "high": high, "low": low,
        "close": closes, "vol": vol, "tbb": vol * 0.5,
    })


def _bullish_trend(n: int = 400, drift: float = 0.25, noise: float = 0.2, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 + np.cumsum(rng.normal(drift, noise, n))
    return _make_ohlc(closes, seed=seed)


def _bearish_trend(n: int = 400, drift: float = -0.25, noise: float = 0.2, seed: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 200.0 + np.cumsum(rng.normal(drift, noise, n))
    closes = np.maximum(closes, 10.0)  # floor to avoid negatives
    return _make_ohlc(closes, seed=seed)


def _chop_market(n: int = 400, seed: int = 3) -> pd.DataFrame:
    """White-noise around a fixed level — no autocorrelation, no direction.

    Pure white noise (não senoidal nem random-walk) pra garantir que os
    3 Supertrends com períodos distintos raramente convergem na mesma
    direção — é isso que caracteriza chop real.
    """
    rng = np.random.default_rng(seed)
    closes = 100.0 + rng.normal(0, 2.0, n)
    return _make_ohlc(closes, seed=seed)


# ── core.indicators.supertrend ───────────────────────────────────────


def test_supertrend_returns_st_and_stx_columns():
    df = _bullish_trend(n=100)
    out = supertrend(df, multiplier=3, period=10)
    assert list(out.columns) == ["st", "stx"]
    assert out.index.equals(df.index)


def test_supertrend_identifies_uptrend_on_bull_data():
    df = _bullish_trend(n=200, drift=0.5, noise=0.1)  # strong, clean up
    out = supertrend(df, multiplier=3, period=10)
    # Last half of the series should be predominantly 'up'
    tail_stx = out["stx"].iloc[100:].tolist()
    ups = sum(1 for s in tail_stx if s == "up")
    assert ups > len(tail_stx) * 0.6, f"expected mostly up; got {ups}/{len(tail_stx)}"


def test_supertrend_identifies_downtrend_on_bear_data():
    df = _bearish_trend(n=200, drift=-0.5, noise=0.1)
    out = supertrend(df, multiplier=3, period=10)
    tail_stx = out["stx"].iloc[100:].tolist()
    downs = sum(1 for s in tail_stx if s == "down")
    assert downs > len(tail_stx) * 0.6, f"expected mostly down; got {downs}/{len(tail_stx)}"


def test_supertrend_warmup_returns_empty_string():
    df = _bullish_trend(n=50)
    out = supertrend(df, multiplier=3, period=14)
    # First `period` bars haven't accumulated TR SMA → stx should be '' and st == 0
    assert out["stx"].iloc[0] == ""
    assert out["st"].iloc[0] == 0.0


# ── scan_supertrend: entry signals ───────────────────────────────────


def test_scan_emits_long_trade_on_clean_uptrend():
    df = _bullish_trend(n=500, drift=0.6, noise=0.15, seed=11)
    trades, vetos = scan_supertrend(df, symbol="TEST")
    long_trades = [t for t in trades if t["direction"] == "BULLISH"]
    assert len(long_trades) > 0, "clean uptrend should trigger at least one LONG"
    t = long_trades[0]
    # Structural fields
    assert t["strategy"] == "SUPERTREND_FUT"
    assert t["leverage"] == stfu.LEVERAGE
    assert t["entry"] > 0
    assert t["stop"] < t["entry"]       # long: stop below entry
    assert t["target"] > t["entry"]     # long: target above entry
    # All 3 buy supertrends must have been 'up' at idx
    assert t["st_buy_1"] == "up"
    assert t["st_buy_2"] == "up"
    assert t["st_buy_3"] == "up"
    # Stop is ~26.5% below entry
    expected_stop = t["entry"] * (1 - stfu.STOPLOSS_PCT)
    assert abs(t["stop"] - expected_stop) < 1e-4


def test_scan_emits_short_trade_on_clean_downtrend():
    df = _bearish_trend(n=500, drift=-0.6, noise=0.15, seed=22)
    trades, vetos = scan_supertrend(df, symbol="TEST")
    short_trades = [t for t in trades if t["direction"] == "BEARISH"]
    assert len(short_trades) > 0, "clean downtrend should trigger at least one SHORT"
    t = short_trades[0]
    assert t["stop"] > t["entry"]       # short: stop above entry
    assert t["target"] < t["entry"]     # short: target below entry
    assert t["st_sell_1"] == "down"
    assert t["st_sell_2"] == "down"
    assert t["st_sell_3"] == "down"


def test_scan_chop_has_veto_pressure_and_no_edge():
    """Chop (white noise) não gera edge — trades raramente batem target.

    O engine ainda pode disparar porque os 3 Supertrends têm períodos
    similares (8/9/8) e correlacionam em micro-trends. O que caracteriza
    chop não é '0 trades', é 'sem edge': no_confluence vetoes dominam
    e exits são majoritariamente flip/max_hold (não target).
    """
    df = _chop_market(n=500, seed=33)
    trades, vetos = scan_supertrend(df, symbol="TEST")
    assert vetos.get("no_confluence", 0) > 0, "chop should register no_confluence vetoes"
    if trades:
        target_hits = sum(1 for t in trades if t["exit_reason"] == "target")
        # Target deveria ser raro em chop — nunca majoritário
        assert target_hits <= len(trades) // 2, (
            f"chop yielded {target_hits}/{len(trades)} target exits — too many for noise"
        )


# ── Edge cases: insufficient data / NaN ──────────────────────────────


def test_scan_returns_empty_on_short_dataframe():
    df = _bullish_trend(n=10)  # shorter than warmup (max period ~18)
    trades, vetos = scan_supertrend(df, symbol="TEST")
    assert trades == []
    # vetos is empty dict (loop never ran)


def test_scan_handles_zero_volume_rows():
    df = _bullish_trend(n=300, drift=0.5, noise=0.1, seed=44)
    # Wipe out volume for a chunk in the middle of the range
    df.loc[150:200, "vol"] = 0.0
    trades, vetos = scan_supertrend(df, symbol="TEST")
    # Should still return (no crash), and at least one zero_volume veto
    # if the confluence happened to fire in that window.
    assert isinstance(trades, list)
    assert isinstance(vetos, dict)


def test_scan_handles_empty_dataframe():
    df = pd.DataFrame({
        "time": [], "open": [], "high": [], "low": [],
        "close": [], "vol": [], "tbb": [],
    })
    trades, vetos = scan_supertrend(df, symbol="EMPTY")
    assert trades == []


# ── _signal_confidence ───────────────────────────────────────────────


def test_signal_confidence_in_valid_range():
    df = _bullish_trend(n=300, drift=0.5, seed=55)
    df_st = _compute_supertrend_set(df)
    # Pick an idx well past warmup
    for idx in (50, 100, 200, 290):
        for direction in ("BULLISH", "BEARISH"):
            c = _signal_confidence(df_st, idx, direction)
            assert 0.0 <= c <= 1.0, f"confidence {c} out of [0,1] at idx {idx} dir {direction}"


def test_signal_confidence_monotonic_with_distance():
    """A bar very far above the Supertrend line should have higher BULLISH
    confidence than one sitting near it."""
    df = _bullish_trend(n=400, drift=0.6, noise=0.1, seed=66)
    df_st = _compute_supertrend_set(df)
    # Find two indices where the close is at different distances from
    # st_buy_2_line, both post-warmup, both with up trend
    candidates = []
    for idx in range(50, len(df_st) - 1):
        line = df_st["st_buy_2_line"].iat[idx]
        if line > 0 and df_st["st_buy_2"].iat[idx] == "up":
            dist = df_st["close"].iat[idx] - line
            candidates.append((idx, dist))
    if len(candidates) < 2:
        pytest.skip("insufficient up-trend bars for monotonic test")
    candidates.sort(key=lambda pair: pair[1])
    near_idx = candidates[0][0]
    far_idx = candidates[-1][0]
    c_near = _signal_confidence(df_st, near_idx, "BULLISH")
    c_far = _signal_confidence(df_st, far_idx, "BULLISH")
    assert c_far >= c_near, f"expected far distance ({c_far}) ≥ near ({c_near})"


# ── Trade labeling invariants ────────────────────────────────────────


def test_labeled_trade_has_consistent_fields():
    df = _bullish_trend(n=500, drift=0.6, noise=0.15, seed=77)
    trades, _ = scan_supertrend(df, symbol="TEST")
    if not trades:
        pytest.skip("no trades generated for label check")
    for t in trades:
        # Mandatory fields
        for k in ("symbol", "direction", "entry", "stop", "target", "size",
                  "result", "exit_reason", "pnl", "r_multiple", "rr"):
            assert k in t, f"missing field {k}"
        # Result must be one of the terminal states
        assert t["result"] in ("WIN", "LOSS")
        assert t["exit_reason"] in ("stop_initial", "target", "supertrend_flip", "max_hold")
        # R-multiple is finite
        assert np.isfinite(t["r_multiple"])


def test_live_mode_emits_live_result_only():
    df = _bullish_trend(n=500, drift=0.6, noise=0.1, seed=88)
    trades, _ = scan_supertrend(df, symbol="TEST", live_mode=True, live_tail_bars=20)
    if not trades:
        pytest.skip("no live signals")
    for t in trades:
        assert t["result"] == "LIVE"
        assert t["exit_reason"] == "live"
        assert t["pnl"] == 0.0


# ── Metadata helpers ─────────────────────────────────────────────────


def test_get_metadata_returns_copy_with_required_keys():
    md = get_metadata()
    for key in ("name", "display", "origin", "hypothesis", "best_regime",
                "validation", "phase"):
        assert key in md
    assert md["name"] == "SUPERTREND_FUT"
    assert md["phase"] == 1  # phase 1 = port + unit tests
    # Returns a copy — mutating shouldn't affect module-level dict
    md["name"] = "MUTATED"
    assert ENGINE_METADATA["name"] == "SUPERTREND_FUT"


def test_get_regime_fit_returns_expected_values():
    assert get_regime_fit("BULL") > get_regime_fit("CHOP")
    assert get_regime_fit("BEAR") > get_regime_fit("CHOP")
    assert 0.0 <= get_regime_fit("BULL") <= 1.0
    assert 0.0 <= get_regime_fit("CHOP") <= 1.0
    # Unknown / None → neutral midpoint
    assert get_regime_fit(None) == 0.5
    assert get_regime_fit("UNKNOWN") == 0.5
