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


def test_collect_sentiment_fails_closed_when_historical_oi_ls_unavailable(monkeypatch):
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

    with pytest.raises(RuntimeError, match="historical sentiment unavailable for OOS window"):
        bridgewater.collect_sentiment(["BTCUSDT"], end_time_ms=1234567890, window_days=30)


def test_collect_sentiment_fails_when_any_symbol_lacks_historical_coverage(monkeypatch):
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

    with pytest.raises(RuntimeError, match="ETHUSDT: oi\\(cache=empty\\)"):
        bridgewater.collect_sentiment(["BTCUSDT", "ETHUSDT"], end_time_ms=1234567890, window_days=30)


def test_parse_symbols_override_normalizes_symbols():
    assert bridgewater._parse_symbols_override("btc, ETHUSDT ,sol") == [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
    ]
