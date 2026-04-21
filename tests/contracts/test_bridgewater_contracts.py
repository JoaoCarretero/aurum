from __future__ import annotations

import pandas as pd
import pytest

from engines import bridgewater


def test_align_oi_signal_to_candles_keeps_pre_series_window_at_zero():
    candle_times = pd.to_datetime(
        [
            "2026-01-01 00:00:00",
            "2026-01-01 01:00:00",
            "2026-01-01 02:00:00",
            "2026-01-01 03:00:00",
        ]
    )
    oi_signal_df = pd.DataFrame(
        {
            "time": pd.to_datetime(
                [
                    "2026-01-01 02:00:00",
                    "2026-01-01 03:00:00",
                ]
            ),
            "oi_signal": [1.0, -1.0],
        }
    )

    aligned = bridgewater._align_oi_signal_to_candles(pd.Series(candle_times), oi_signal_df)

    assert aligned.tolist() == [0.0, 0.0, 1.0, -1.0]


def test_align_oi_signal_drops_stale_ticks_beyond_2h_tolerance():
    """Bug 4 fix: when the last OI tick is > 2h before a candle, the aligner
    must return 0 (no signal) instead of propagating a stale value."""
    candle_times = pd.to_datetime([
        "2026-01-01 10:00:00",  # close to tick
        "2026-01-01 11:00:00",  # 2h after tick exactly — boundary OK
        "2026-01-01 15:00:00",  # 6h after tick — MUST be dropped
    ])
    oi_signal_df = pd.DataFrame({
        "time": pd.to_datetime(["2026-01-01 09:00:00"]),
        "oi_signal": [0.8],
    })
    aligned = bridgewater._align_oi_signal_to_candles(pd.Series(candle_times), oi_signal_df)
    assert aligned[0] == 0.8          # tick 1h old — fresh
    assert aligned[1] == 0.8          # tick 2h old — within tolerance
    assert aligned[2] == 0.0          # tick 6h old — stale, zeroed


def test_align_series_rejects_rangeindex_series_bug1_fix():
    """Bug 1 fix: a Series without DatetimeIndex must NOT be aligned
    positionally (which fabricated sentiment signal across backtests).
    Return all-default instead.
    """
    import numpy as np
    candle_times = pd.Series(pd.to_datetime([
        "2026-01-01 00:00:00",
        "2026-01-01 01:00:00",
        "2026-01-01 02:00:00",
    ]))
    rangeindex_series = pd.Series([0.9, -0.4, 0.5])  # has RangeIndex, not datetime
    aligned = bridgewater._align_series_to_candles(candle_times, rangeindex_series)
    assert np.array_equal(aligned, np.zeros(3))


def test_align_series_respects_staleness_guard_bug4_fix():
    """Bug 4 fix: searchsorted-based alignment must drop ticks older than
    max_staleness. Without this, a single historical probe row would
    propagate for years of subsequent candles.
    """
    import numpy as np
    tick_times = pd.to_datetime(["2023-11-14 22:00:00", "2026-04-12 11:00:00"])
    series = pd.Series([0.7, -0.3], index=tick_times)
    candle_times = pd.Series(pd.to_datetime([
        "2024-01-01 00:00:00",  # 1.5 months after 2023 tick — MUST be 0
        "2025-06-01 00:00:00",  # 1.5 years after 2023 tick — MUST be 0
        "2026-04-12 12:00:00",  # 1h after 2026 tick — uses real value
        "2026-04-12 15:00:00",  # 4h after 2026 tick — stale, zeroed
    ]))
    aligned = bridgewater._align_series_to_candles(candle_times, series)
    assert aligned[0] == 0.0
    assert aligned[1] == 0.0
    assert aligned[2] == -0.3
    assert aligned[3] == 0.0


def test_collect_sentiment_propagates_end_time_to_all_fetchers(monkeypatch):
    seen: dict[str, tuple[int, int | None]] = {}

    def _funding(sym, limit=0, end_time_ms=None):
        seen["funding"] = (limit, end_time_ms)
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="8h"),
                "funding_rate": [0.001] * 10,
            }
        )

    def _oi(sym, period="15m", limit=0, end_time_ms=None):
        seen["oi"] = (limit, end_time_ms)
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="15min"),
                "oi": [1000.0] * 10,
                "oi_value": [100000.0] * 10,
            }
        )

    def _ls(sym, period="15m", limit=0, end_time_ms=None):
        seen["ls"] = (limit, end_time_ms)
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="15min"),
                "ls_ratio": [1.0] * 10,
                "long_pct": [0.5] * 10,
                "short_pct": [0.5] * 10,
            }
        )

    monkeypatch.setattr(bridgewater, "fetch_funding_rate", _funding)
    monkeypatch.setattr(bridgewater, "fetch_open_interest", _oi)
    monkeypatch.setattr(bridgewater, "fetch_long_short_ratio", _ls)
    monkeypatch.setattr(
        bridgewater,
        "funding_zscore",
        lambda df, window=30: pd.Series([0.0] * len(df), index=df.index),
    )
    monkeypatch.setattr(
        bridgewater,
        "ls_ratio_signal",
        lambda df: pd.Series([0.0] * len(df), index=df.index),
    )

    out = bridgewater.collect_sentiment(["BTCUSDT"], end_time_ms=1234567890, window_days=30)

    assert "BTCUSDT" in out
    assert seen["funding"][1] == 1234567890
    assert seen["oi"][1] == 1234567890
    assert seen["ls"][1] == 1234567890
    assert seen["oi"][0] > 500
    assert seen["ls"][0] > 500


def test_sentiment_limits_keep_live_caps_but_expand_historical_oos_window():
    live = bridgewater._sentiment_limits(30, historical=False)
    historical = bridgewater._sentiment_limits(30, historical=True)

    assert live == (108, 500, 500)
    assert historical == (108, 3168, 3168)


def test_collect_sentiment_marks_historical_oi_ls_unavailable_without_raising(monkeypatch):
    def _funding(sym, limit=0, end_time_ms=None):
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="8h"),
                "funding_rate": [0.001] * 10,
            }
        )

    monkeypatch.setattr(bridgewater, "fetch_funding_rate", _funding)
    monkeypatch.setattr(bridgewater, "fetch_open_interest", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridgewater, "fetch_long_short_ratio", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        bridgewater,
        "funding_zscore",
        lambda df, window=30: pd.Series([0.0] * len(df), index=df.index),
    )

    out = bridgewater.collect_sentiment(["BTCUSDT"], end_time_ms=1234567890, window_days=30)

    assert out["BTCUSDT"]["funding_z"] is not None
    assert out["BTCUSDT"]["oi_df"] is None
    assert out["BTCUSDT"]["oi_ready"] is False
    assert out["BTCUSDT"]["ls_signal"] is None
    assert out["BTCUSDT"]["ls_ready"] is False


def test_collect_sentiment_keeps_other_symbols_when_one_lacks_historical_coverage(monkeypatch):
    def _funding(sym, limit=0, end_time_ms=None):
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="8h"),
                "funding_rate": [0.001] * 10,
            }
        )

    def _oi(sym, period="15m", limit=0, end_time_ms=None):
        if sym == "ETHUSDT":
            return None
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="15min"),
                "oi": [1000.0] * 10,
                "oi_value": [100000.0] * 10,
            }
        )

    def _ls(sym, period="15m", limit=0, end_time_ms=None):
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="15min"),
                "ls_ratio": [1.0] * 10,
                "long_pct": [0.5] * 10,
                "short_pct": [0.5] * 10,
            }
        )

    monkeypatch.setattr(bridgewater, "fetch_funding_rate", _funding)
    monkeypatch.setattr(bridgewater, "fetch_open_interest", _oi)
    monkeypatch.setattr(bridgewater, "fetch_long_short_ratio", _ls)
    monkeypatch.setattr(
        bridgewater,
        "funding_zscore",
        lambda df, window=30: pd.Series([0.0] * len(df), index=df.index),
    )
    monkeypatch.setattr(
        bridgewater,
        "ls_ratio_signal",
        lambda df: pd.Series([0.0] * len(df), index=df.index),
    )
    monkeypatch.setattr(bridgewater, "cached_coverage", lambda kind, sym, period: None)

    out = bridgewater.collect_sentiment(["BTCUSDT", "ETHUSDT"], end_time_ms=1234567890, window_days=30)

    assert out["BTCUSDT"]["oi_ready"] is True
    assert out["ETHUSDT"]["oi_df"] is None
    assert out["ETHUSDT"]["oi_ready"] is False


def test_collect_sentiment_uses_partial_cached_history_for_oos(monkeypatch):
    def _funding(sym, limit=0, end_time_ms=None):
        return pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=10, freq="8h"),
                "funding_rate": [0.001] * 10,
            }
        )

    monkeypatch.setattr(bridgewater, "fetch_funding_rate", _funding)
    monkeypatch.setattr(bridgewater, "fetch_open_interest", lambda *args, **kwargs: None)
    monkeypatch.setattr(bridgewater, "fetch_long_short_ratio", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        bridgewater,
        "_load_partial_cached_sentiment",
        lambda kind, sym, period, end_time_ms: pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01", periods=12, freq="15min"),
                **(
                    {"oi": [1000.0] * 12, "oi_value": [100000.0] * 12}
                    if kind == "open_interest"
                    else {"ls_ratio": [1.0] * 12, "long_pct": [0.5] * 12, "short_pct": [0.5] * 12}
                ),
            }
        ),
    )
    monkeypatch.setattr(
        bridgewater,
        "funding_zscore",
        lambda df, window=30: pd.Series([0.0] * len(df), index=df.index),
    )
    monkeypatch.setattr(
        bridgewater,
        "ls_ratio_signal",
        lambda df: pd.Series([0.0] * len(df), index=df.index),
    )

    out = bridgewater.collect_sentiment(["BTCUSDT"], end_time_ms=1234567890, window_days=30)

    assert out["BTCUSDT"]["oi_ready"] is True
    assert out["BTCUSDT"]["ls_ready"] is True


def test_parse_symbols_override_normalizes_symbols():
    assert bridgewater._parse_symbols_override("btc, ETHUSDT ,sol") == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]


def test_scan_warmup_bars_has_room_for_indicator_lookbacks():
    assert bridgewater._scan_warmup_bars() >= max(200, bridgewater.W_NORM, bridgewater.PIVOT_N * 3) + 10


def test_scan_window_can_close_trades_respects_max_hold():
    assert bridgewater._scan_window_can_close_trades(bridgewater.MAX_HOLD + 3) is True
    assert bridgewater._scan_window_can_close_trades(bridgewater.MAX_HOLD + 2) is False


def test_sentiment_coverage_start_uses_latest_channel_start():
    sent = {
        "funding_z": pd.Series([0.1, 0.2], index=pd.to_datetime(["2026-04-01", "2026-04-02"])),
        "oi_df": pd.DataFrame({"time": pd.to_datetime(["2026-04-03", "2026-04-04"]), "oi": [1.0, 1.1]}),
        "ls_signal": pd.Series([-0.5, -1.0], index=pd.to_datetime(["2026-04-05", "2026-04-06"])),
    }

    assert bridgewater._sentiment_coverage_start(sent) == pd.Timestamp("2026-04-05")


def test_coverage_scan_start_idx_respects_sentiment_start():
    df = pd.DataFrame({"time": pd.date_range("2026-04-01", periods=10, freq="1h")})
    sent = {
        "funding_z": pd.Series([0.1], index=pd.to_datetime(["2026-04-01 00:00:00"])),
        "oi_df": pd.DataFrame({"time": pd.to_datetime(["2026-04-01 04:00:00"]), "oi": [1.0]}),
        "ls_signal": pd.Series([-0.5], index=pd.to_datetime(["2026-04-01 06:00:00"])),
    }

    assert bridgewater._coverage_scan_start_idx(df, sent, 2) == 6


def test_coverage_eligibility_requires_fraction_and_closeable_window():
    df = pd.DataFrame({"time": pd.date_range("2026-04-01", periods=20, freq="1h")})
    sent = {
        "funding_z": pd.Series([0.1], index=pd.to_datetime(["2026-04-01 00:00:00"])),
        "oi_df": pd.DataFrame({"time": pd.to_datetime(["2026-04-01 14:00:00"]), "oi": [1.0]}),
        "ls_signal": pd.Series([-0.5], index=pd.to_datetime(["2026-04-01 14:00:00"])),
    }

    original_max_hold = bridgewater.MAX_HOLD
    bridgewater.MAX_HOLD = 3
    try:
        out = bridgewater._coverage_eligibility(df, sent, 4, min_fraction=0.70)
    finally:
        bridgewater.MAX_HOLD = original_max_hold

    assert out == {
        "scan_start_idx": 14,
        "covered_scan_candles": 6,
        "total_scan_candles": 16,
        "coverage_fraction": 0.375,
        "closeable": True,
        "eligible": False,
    }


def test_filter_stale_market_data_drops_old_series():
    fresh = pd.DataFrame({"time": pd.date_range("2026-04-16", periods=3, freq="1h")})
    stale = pd.DataFrame({"time": pd.date_range("2026-04-10", periods=3, freq="1h")})

    kept, dropped = bridgewater._filter_stale_market_data(
        {"BTCUSDT": fresh, "MATICUSDT": stale},
        "1h",
    )

    assert list(kept.keys()) == ["BTCUSDT"]
    assert dropped == ["MATICUSDT"]


def test_trade_sentiment_diagnostics_surfaces_neutral_oi_share():
    diagnostics = bridgewater._trade_sentiment_diagnostics([
        {"oi_signal": 0.0, "ls_signal": -0.5, "funding_z": 1.2},
        {"oi_signal": 0.0, "ls_signal": 0.0, "funding_z": -0.7},
        {"oi_signal": 0.3, "ls_signal": -0.5, "funding_z": 0.4},
    ])

    assert diagnostics["oi_zero_pct"] == 66.67
    assert diagnostics["oi_nonzero_trades"] == 1
    assert diagnostics["ls_zero_pct"] == 33.33
    assert diagnostics["ls_distribution"] == {"-0.5": 2, "0.0": 1}
    assert diagnostics["funding_positive_pct"] == 66.67
    assert diagnostics["funding_negative_pct"] == 33.33


def test_runtime_preset_robust_forces_disciplined_funding_ls_mode():
    resolved = bridgewater._resolve_runtime_preset(
        "robust",
        strict_direction=False,
        min_components=0,
        min_dir_thresh=None,
        disable_oi=False,
        enable_symbol_health=False,
        allowed_regimes=None,
        post_trade_cooldown_bars=0,
    )

    assert resolved == {
        "preset": "robust",
        "strict_direction": True,
        "min_components": 2,
        "min_dir_thresh": 0.35,
        "disable_oi": True,
        "allowed_macro_regimes": {"BEAR", "CHOP"},
        "post_trade_cooldown_bars": 0,
        "regime_thresholds": {"BEAR": 0.35, "BULL": 0.45, "CHOP": 0.55},
        "symbol_health": None,
        "min_coverage_fraction": 0.70,
    }


def test_runtime_preset_legacy_preserves_explicit_runtime_overrides():
    resolved = bridgewater._resolve_runtime_preset(
        "legacy",
        strict_direction=True,
        min_components=1,
        min_dir_thresh=0.4,
        disable_oi=True,
        enable_symbol_health=True,
        allowed_regimes="BEAR,BULL",
        post_trade_cooldown_bars=3,
    )

    assert resolved == {
        "preset": "legacy",
        "strict_direction": True,
        "min_components": 1,
        "min_dir_thresh": 0.4,
        "disable_oi": True,
        "allowed_macro_regimes": {"BEAR", "BULL"},
        "post_trade_cooldown_bars": 3,
        "regime_thresholds": None,
        "symbol_health": None,
        "min_coverage_fraction": 0.70,
    }


def test_runtime_preset_robust_can_enable_symbol_health():
    resolved = bridgewater._resolve_runtime_preset(
        "robust",
        strict_direction=False,
        min_components=0,
        min_dir_thresh=None,
        disable_oi=False,
        enable_symbol_health=True,
        allowed_regimes=None,
        post_trade_cooldown_bars=0,
    )

    assert resolved["symbol_health"] == {
        "lookback": 8,
        "block_min_trades": 5,
        "block_expectancy": -0.35,
        "block_loss_rate": 0.80,
        "saturation_start": 6,
        "saturation_full": 10,
        "min_multiplier": 0.45,
    }


def test_runtime_preset_robust_allows_explicit_regime_override():
    resolved = bridgewater._resolve_runtime_preset(
        "robust",
        strict_direction=False,
        min_components=0,
        min_dir_thresh=None,
        disable_oi=False,
        enable_symbol_health=False,
        allowed_regimes="CHOP",
        post_trade_cooldown_bars=0,
    )

    assert resolved["allowed_macro_regimes"] == {"CHOP"}


def test_runtime_preset_robust_caps_min_components_to_available_channels():
    resolved = bridgewater._resolve_runtime_preset(
        "robust",
        strict_direction=False,
        min_components=4,
        min_dir_thresh=None,
        disable_oi=False,
        enable_symbol_health=False,
        allowed_regimes=None,
        post_trade_cooldown_bars=0,
    )

    assert resolved["disable_oi"] is True
    assert resolved["min_components"] == 2


def test_runtime_preset_oi_research_keeps_oi_on_and_hardens_coverage():
    resolved = bridgewater._resolve_runtime_preset(
        "oi_research",
        strict_direction=False,
        min_components=0,
        min_dir_thresh=None,
        disable_oi=False,
        enable_symbol_health=False,
        allowed_regimes=None,
        post_trade_cooldown_bars=0,
    )

    assert resolved == {
        "preset": "oi_research",
        "strict_direction": True,
        "min_components": 2,
        "min_dir_thresh": 0.35,
        "disable_oi": False,
        "allowed_macro_regimes": {"BEAR", "CHOP"},
        "post_trade_cooldown_bars": 0,
        "regime_thresholds": {"BEAR": 0.35, "BULL": 0.45, "CHOP": 0.55},
        "symbol_health": None,
        "min_coverage_fraction": 0.85,
    }


def test_resolve_direction_threshold_uses_regime_specific_override():
    assert bridgewater._resolve_direction_threshold("BEAR", 0.35, {"BEAR": 0.35, "BULL": 0.45}) == 0.35
    assert bridgewater._resolve_direction_threshold("BULL", 0.35, {"BEAR": 0.35, "BULL": 0.45}) == 0.45
    assert bridgewater._resolve_direction_threshold("CHOP", 0.35, {"BEAR": 0.35, "BULL": 0.45}) == 0.35


def test_symbol_health_controls_block_on_strong_negative_expectancy():
    recent_closed = [{"r_multiple": -0.6}] * 5

    mult, reason = bridgewater._symbol_health_controls(
        recent_closed,
        {
            "lookback": 8,
            "block_min_trades": 5,
            "block_expectancy": -0.35,
            "block_loss_rate": 0.80,
            "saturation_start": 6,
            "saturation_full": 10,
            "min_multiplier": 0.45,
        },
    )

    assert mult == 0.0
    assert reason == "symbol_health_block"


def test_symbol_health_controls_scale_after_symbol_saturates():
    recent_closed = [{"r_multiple": -0.1}] * 8

    mult, reason = bridgewater._symbol_health_controls(
        recent_closed,
        {
            "lookback": 8,
            "block_min_trades": 5,
            "block_expectancy": -0.35,
            "block_loss_rate": 0.80,
            "saturation_start": 6,
            "saturation_full": 10,
            "min_multiplier": 0.45,
        },
    )

    assert reason is None
    assert mult == 0.45


# ────────────────────────────────────────────────────────────
# scan_thoth research gates (2026-04-17) — kw-only signature contract
# ────────────────────────────────────────────────────────────

def test_scan_thoth_accepts_research_gates_as_keyword_only():
    """Research gates are keyword-only to prevent accidental positional
    calls from drifting into production wrappers.
    """
    import inspect
    sig = inspect.signature(bridgewater.scan_thoth)
    for name in ("disable_oi", "allowed_macro_regimes", "post_trade_cooldown_bars", "regime_thresholds",
                 "symbol_health", "strict_direction", "min_components",
                 "min_dir_thresh", "exit_on_reversal"):
        p = sig.parameters.get(name)
        assert p is not None, f"missing kw-only param: {name}"
        assert p.kind == inspect.Parameter.KEYWORD_ONLY, (
            f"{name} must be keyword-only, got {p.kind}"
        )


def test_scan_thoth_research_gates_default_off():
    """Default values must preserve the calibrated baseline.
    Changing a default is a behavior change and requires explicit sign-off.
    """
    import inspect
    sig = inspect.signature(bridgewater.scan_thoth)
    defaults = {n: p.default for n, p in sig.parameters.items()}
    assert defaults["disable_oi"] is False
    assert defaults["allowed_macro_regimes"] is None
    assert defaults["post_trade_cooldown_bars"] == 0
    assert defaults["regime_thresholds"] is None
    assert defaults["symbol_health"] is None
    assert defaults["strict_direction"] is False
    assert defaults["min_components"] == 0
    assert defaults["min_dir_thresh"] is None
    assert defaults["exit_on_reversal"] is False
