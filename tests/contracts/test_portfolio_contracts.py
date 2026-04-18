"""Contract tests for core.portfolio.

Focam em invariantes, não em magic numbers — sobrevivem a tuning de
params. Cobrem os 5 pontos de entrada públicos: detect_macro,
build_corr_matrix, portfolio_allows, check_aggregate_notional,
position_size.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.params import (
    BASE_RISK,
    CORR_SOFT_MULT,
    CORR_SOFT_THRESHOLD,
    CORR_THRESHOLD,
    MACRO_SYMBOL,
    MAX_OPEN_POSITIONS,
    MAX_RISK,
)
from core.portfolio import (
    build_corr_matrix,
    check_aggregate_notional,
    detect_macro,
    portfolio_allows,
    position_size,
)


# ────────────────────────────────────────────────────────────
# helpers
# ────────────────────────────────────────────────────────────

N = 500  # > EMA200 + SLOPE_N*2 for detect_macro via indicators()


def _make_ohlcv(close: np.ndarray) -> pd.DataFrame:
    n = len(close)
    return pd.DataFrame({
        "close": close,
        "high": close * 1.002,
        "low": close * 0.998,
        "vol": np.full(n, 1_000.0),
        "tbb": np.full(n, 500.0),
    })


def _rw(drift: float, sigma: float, seed: int, start: float = 100.0,
        n: int = N) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return start + np.cumsum(rng.normal(drift, sigma, n))


# ────────────────────────────────────────────────────────────
# detect_macro
# ────────────────────────────────────────────────────────────

class TestDetectMacro:
    def test_returns_none_when_macro_symbol_missing(self):
        all_dfs = {"ETHUSDT": _make_ohlcv(_rw(0.1, 1.0, seed=0))}
        assert detect_macro(all_dfs) is None

    def test_returns_series_of_enum_values(self):
        all_dfs = {MACRO_SYMBOL: _make_ohlcv(_rw(0.1, 1.0, seed=0))}
        out = detect_macro(all_dfs)
        assert isinstance(out, pd.Series)
        assert set(out.dropna().unique()).issubset({"BULL", "BEAR", "CHOP"})

    def test_uptrend_btc_biases_to_bull(self):
        all_dfs = {MACRO_SYMBOL: _make_ohlcv(_rw(0.5, 1.0, seed=0))}
        out = detect_macro(all_dfs).tail(100)
        counts = out.value_counts().to_dict()
        # Bull should dominate last 100 bars of strong uptrend
        assert counts.get("BULL", 0) > counts.get("BEAR", 0)

    def test_downtrend_btc_biases_to_bear(self):
        all_dfs = {MACRO_SYMBOL: _make_ohlcv(_rw(-0.5, 1.0, seed=2, start=500.0))}
        out = detect_macro(all_dfs).tail(100)
        counts = out.value_counts().to_dict()
        assert counts.get("BEAR", 0) > counts.get("BULL", 0)

    def test_length_matches_input(self):
        df = _make_ohlcv(_rw(0.1, 1.0, seed=0))
        all_dfs = {MACRO_SYMBOL: df}
        out = detect_macro(all_dfs)
        assert len(out) == len(df)


# ────────────────────────────────────────────────────────────
# build_corr_matrix
# ────────────────────────────────────────────────────────────

class TestBuildCorrMatrix:
    def test_symmetric_keys(self):
        all_dfs = {
            "A": _make_ohlcv(_rw(0.1, 1.0, seed=0)),
            "B": _make_ohlcv(_rw(0.1, 1.0, seed=1)),
        }
        corr = build_corr_matrix(all_dfs)
        assert corr[("A", "B")] == corr[("B", "A")]

    def test_values_within_minus_one_and_one(self):
        all_dfs = {
            f"S{i}": _make_ohlcv(_rw(0.1, 1.0, seed=i))
            for i in range(4)
        }
        corr = build_corr_matrix(all_dfs)
        for v in corr.values():
            assert -1.0 <= v <= 1.0

    def test_no_self_correlation(self):
        all_dfs = {"A": _make_ohlcv(_rw(0.1, 1.0, seed=0))}
        corr = build_corr_matrix(all_dfs)
        assert ("A", "A") not in corr

    def test_identical_series_correlate_near_one(self):
        close = _rw(0.1, 1.0, seed=7)
        all_dfs = {"A": _make_ohlcv(close), "B": _make_ohlcv(close.copy())}
        corr = build_corr_matrix(all_dfs)
        assert corr[("A", "B")] > 0.99

    def test_short_series_returns_zero(self):
        # series with <30 aligned returns → fallback to 0.0
        short = _make_ohlcv(_rw(0.1, 1.0, seed=0, n=20))
        all_dfs = {"A": short, "B": short.copy()}
        corr = build_corr_matrix(all_dfs)
        assert corr[("A", "B")] == 0.0


# ────────────────────────────────────────────────────────────
# portfolio_allows
# ────────────────────────────────────────────────────────────

class TestPortfolioAllows:
    def test_empty_open_positions_allows_full_size(self):
        ok, motivo, mult = portfolio_allows("BTC", [], {})
        assert ok is True
        assert mult == 1.0
        assert motivo == "ok"

    def test_high_correlation_blocks(self):
        corr = {("BTC", "ETH"): CORR_THRESHOLD + 0.05, ("ETH", "BTC"): CORR_THRESHOLD + 0.05}
        ok, motivo, mult = portfolio_allows("BTC", ["ETH"], corr)
        assert ok is False
        assert mult == 0.0
        assert "corr_alta" in motivo

    def test_soft_correlation_scales_size(self):
        # corr between SOFT (0.75) and THRESHOLD (0.80) → size × CORR_SOFT_MULT
        mid = (CORR_SOFT_THRESHOLD + CORR_THRESHOLD) / 2
        corr = {("BTC", "ETH"): mid, ("ETH", "BTC"): mid}
        ok, motivo, mult = portfolio_allows("BTC", ["ETH"], corr)
        assert ok is True
        assert mult == CORR_SOFT_MULT
        assert "corr_soft" in motivo

    def test_low_correlation_passes_full_size(self):
        corr = {("BTC", "ETH"): 0.1, ("ETH", "BTC"): 0.1}
        ok, motivo, mult = portfolio_allows("BTC", ["ETH"], corr)
        assert ok is True
        assert mult == 1.0

    def test_missing_pair_defaults_to_zero_corr(self):
        # corr dict sem (BTC,ETH) → get() retorna 0.0 → passa full
        ok, _, mult = portfolio_allows("BTC", ["ETH"], {})
        assert ok is True
        assert mult == 1.0

    def test_max_positions_blocks(self):
        open_pos = ["S1", "S2", "S3"][:MAX_OPEN_POSITIONS]
        corr = {(f"NEW", s): 0.1 for s in open_pos}
        corr.update({(s, "NEW"): 0.1 for s in open_pos})
        ok, motivo, mult = portfolio_allows("NEW", open_pos, corr)
        assert ok is False
        assert "max_posicoes" in motivo
        assert mult == 0.0

    def test_hard_corr_beats_max_positions_check(self):
        # Se uma correlação alta já bloqueia, o motivo é corr_alta, não max
        open_pos = ["S1"] * MAX_OPEN_POSITIONS
        corr = {("NEW", "S1"): 0.95, ("S1", "NEW"): 0.95}
        ok, motivo, _ = portfolio_allows("NEW", open_pos, corr)
        assert ok is False
        assert "corr_alta" in motivo


# ────────────────────────────────────────────────────────────
# check_aggregate_notional
# ────────────────────────────────────────────────────────────

class TestCheckAggregateNotional:
    def test_empty_open_positions_allows(self):
        ok, motivo = check_aggregate_notional(
            new_notional=5_000, open_pos=[], account=1_000, leverage=10
        )
        assert ok is True
        assert motivo == "ok"

    def test_under_cap_passes(self):
        # account 1000, leverage 10, cap 10_000; open 3_000, new 2_000 → 5_000
        open_pos = [(10, "BTC", 1.0, 3_000)]  # size × entry = 3_000
        ok, _ = check_aggregate_notional(2_000, open_pos, 1_000, 10)
        assert ok is True

    def test_at_exactly_cap_passes(self):
        # open 5_000 + new 5_000 = 10_000 = cap; use > comparison so equal passes
        open_pos = [(10, "BTC", 1.0, 5_000)]
        ok, _ = check_aggregate_notional(5_000, open_pos, 1_000, 10)
        assert ok is True

    def test_over_cap_blocks(self):
        # open 8_000 + new 3_000 = 11_000 > 10_000 cap
        open_pos = [(10, "BTC", 1.0, 8_000)]
        ok, motivo = check_aggregate_notional(3_000, open_pos, 1_000, 10)
        assert ok is False
        assert "agg_cap" in motivo

    def test_sums_across_multiple_positions(self):
        open_pos = [
            (10, "BTC", 1.0, 3_000),
            (10, "ETH", 1.0, 4_000),
        ]  # open_notional = 7_000
        # cap 10_000; new 4_000 → 11_000 blocks
        ok, _ = check_aggregate_notional(4_000, open_pos, 1_000, 10)
        assert ok is False
        # new 3_000 → 10_000 passes (at cap)
        ok, _ = check_aggregate_notional(3_000, open_pos, 1_000, 10)
        assert ok is True


# ────────────────────────────────────────────────────────────
# position_size
# ────────────────────────────────────────────────────────────

class TestPositionSize:
    def test_zero_distance_returns_zero(self):
        # entry == stop → 0 (no risk possible)
        assert position_size(1_000, 100.0, 100.0, score=0.60) == 0.0

    def test_returns_finite_float_on_valid_inputs(self):
        out = position_size(1_000, 100.0, 99.0, score=0.60)
        assert isinstance(out, float)
        assert np.isfinite(out)
        assert out > 0

    def test_risk_respects_max_bound(self):
        # size * stop_distance ≤ account * MAX_RISK
        account, entry, stop = 10_000, 100.0, 99.0
        size = position_size(account, entry, stop, score=0.95)
        implied_risk = size * abs(entry - stop) / account
        assert implied_risk <= MAX_RISK + 1e-9

    def test_risk_respects_min_bound(self):
        # Mesmo em CHOP com score baixo, size > 0 quando dist > 0
        account, entry, stop = 10_000, 100.0, 99.0
        size = position_size(
            account, entry, stop, score=0.53,
            macro_bias="CHOP", direction="BEARISH", dd_scale=1.0,
        )
        implied_risk = size * abs(entry - stop) / account
        # Floor is BASE_RISK * 0.25
        assert implied_risk >= BASE_RISK * 0.25 - 1e-9

    def test_higher_score_yields_higher_size(self):
        a = position_size(10_000, 100.0, 99.0, score=0.55)
        b = position_size(10_000, 100.0, 99.0, score=0.75)
        assert b >= a

    def test_dd_scale_reduces_size(self):
        normal = position_size(10_000, 100.0, 99.0, score=0.70, dd_scale=1.0)
        stressed = position_size(10_000, 100.0, 99.0, score=0.70, dd_scale=0.2)
        assert stressed < normal

    def test_regime_scale_override_applied(self):
        # Custom regime_scale with 0.1 on BULL should produce smaller size
        # than default (BULL = 0.85)
        normal = position_size(
            10_000, 100.0, 99.0, score=0.70,
            macro_bias="BULL", direction="BULLISH",
        )
        shrunk = position_size(
            10_000, 100.0, 99.0, score=0.70,
            macro_bias="BULL", direction="BULLISH",
            regime_scale={"BULL": 0.1, "BEAR": 0.1, "CHOP": 0.1},
        )
        assert shrunk < normal

    def test_wider_stop_reduces_size(self):
        # Same risk budget → wider stop → smaller size
        tight = position_size(10_000, 100.0, 99.0, score=0.70)
        wide = position_size(10_000, 100.0, 95.0, score=0.70)
        assert wide < tight

    def test_size_scales_linearly_with_account(self):
        a = position_size(1_000, 100.0, 99.0, score=0.70)
        b = position_size(10_000, 100.0, 99.0, score=0.70)
        # Scales roughly 10x (may differ slightly due to rounding)
        assert 9 * a <= b <= 11 * a
