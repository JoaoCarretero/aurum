from __future__ import annotations

import pandas as pd

from core import sentiment


def test_fetch_funding_rate_uses_start_and_end_time_for_historical_window(monkeypatch):
    seen = {}

    def fake_fetch(url, params, label):
        seen["params"] = dict(params)
        return [
            {"fundingTime": 1713552000000, "fundingRate": "0.0001"},
            {"fundingTime": 1713580800000, "fundingRate": "0.0002"},
        ]

    monkeypatch.setattr(sentiment, "_fetch_binance_rows", fake_fetch)

    end_ms = int(pd.Timestamp("2026-04-20 16:00:00").timestamp() * 1000)
    df = sentiment.fetch_funding_rate("BTCUSDT", limit=12, end_time_ms=end_ms)

    assert df is not None
    assert seen["params"]["endTime"] == end_ms
    assert seen["params"]["startTime"] == end_ms - 11 * 8 * 60 * 60 * 1000


def test_fetch_open_interest_returns_partial_cached_history_when_limit_exceeds_api_cap(monkeypatch):
    cached = pd.DataFrame(
        {
            "time": pd.date_range("2026-03-18 00:00:00", periods=600, freq="15min"),
            "oi": [1000.0] * 600,
            "oi_value": [100000.0] * 600,
        }
    )

    monkeypatch.setattr(sentiment, "_load_cached_frame", lambda *args, **kwargs: cached)
    monkeypatch.setattr(sentiment, "_fetch_binance_rows", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("api should not be called")))

    df = sentiment.fetch_open_interest("BTCUSDT", period="15m", limit=1478, end_time_ms=int(pd.Timestamp("2026-04-20 00:00:00").timestamp() * 1000))

    assert df is not None
    assert len(df) == 600
    assert df["time"].max() <= pd.Timestamp("2026-04-20 00:00:00")


def test_fetch_long_short_ratio_returns_partial_cached_history_when_limit_exceeds_api_cap(monkeypatch):
    cached = pd.DataFrame(
        {
            "time": pd.date_range("2026-03-18 00:00:00", periods=600, freq="15min"),
            "ls_ratio": [1.0] * 600,
            "long_pct": [0.5] * 600,
            "short_pct": [0.5] * 600,
        }
    )

    monkeypatch.setattr(sentiment, "_load_cached_frame", lambda *args, **kwargs: cached)
    monkeypatch.setattr(sentiment, "_fetch_binance_rows", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("api should not be called")))

    df = sentiment.fetch_long_short_ratio("BTCUSDT", period="15m", limit=1478, end_time_ms=int(pd.Timestamp("2026-04-20 00:00:00").timestamp() * 1000))

    assert df is not None
    assert len(df) == 600
    assert df["time"].max() <= pd.Timestamp("2026-04-20 00:00:00")
