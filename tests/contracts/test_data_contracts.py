"""Contract tests for core.data — validate + fetch (mocked HTTP)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from core.data import fetch, fetch_all, validate


# ────────────────────────────────────────────────────────────
# validate()
# ────────────────────────────────────────────────────────────

def _valid_df(n: int = 500, taker_bias: float = 0.5) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    vol = np.full(n, 1_000.0)
    return pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=n, freq="1h"),
        "open": close, "high": close * 1.002, "low": close * 0.998,
        "close": close, "vol": vol, "tbb": vol * taker_bias,
    })


class TestValidate:
    def test_valid_df_returns_true(self):
        assert validate(_valid_df(), "BTCUSDT") is True

    def test_short_series_fails(self):
        # < 300 candles → SHORT_SERIES flag
        assert validate(_valid_df(n=100), "BTCUSDT") is False

    def test_duplicates_fail(self):
        df = _valid_df()
        df.loc[5, "time"] = df.loc[4, "time"]  # dup
        assert validate(df, "BTCUSDT") is False

    def test_taker_invalid_fails(self):
        # tbb > vol → taker ratio > 1 → TAKER_INVALID
        df = _valid_df()
        df.loc[0, "tbb"] = df.loc[0, "vol"] * 2.0
        assert validate(df, "BTCUSDT") is False

    def test_taker_biased_high_fails(self):
        # mean taker ratio > 0.70 → TAKER_BIASED
        assert validate(_valid_df(taker_bias=0.80), "BTCUSDT") is False

    def test_taker_biased_low_fails(self):
        assert validate(_valid_df(taker_bias=0.20), "BTCUSDT") is False

    def test_taker_within_bounds_passes(self):
        assert validate(_valid_df(taker_bias=0.50), "BTCUSDT") is True
        assert validate(_valid_df(taker_bias=0.65), "BTCUSDT") is True


# ────────────────────────────────────────────────────────────
# fetch() — HTTP mocked
# ────────────────────────────────────────────────────────────

def _binance_kline_row(ts: int, open_: float = 100.0) -> list:
    # Binance kline shape: 12 fields
    return [
        ts,          # open_time
        open_,       # open
        open_ * 1.01, # high
        open_ * 0.99, # low
        open_ * 1.005, # close
        "1000",      # vol
        ts + 60_000, # close_time
        "100000",    # quote_vol
        100,         # trade_count
        "500",       # taker_buy_base (tbb)
        "50000",     # taker_buy_quote
        "0",         # ignore
    ]


def _make_mock_response(klines: list, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = klines
    return resp


class TestFetch:
    @pytest.fixture(autouse=True)
    def _disable_cache_reads(self, monkeypatch):
        # core/data/base.py is the real module; _cache and requests live there.
        monkeypatch.setattr("core.data.base._cache.read", lambda *args, **kwargs: None)
        monkeypatch.setattr("core.data.base._cache.write", lambda *args, **kwargs: False)

    def test_success_returns_dataframe(self):
        # Single page of 500 candles fits under limit=1000
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(500)]
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)):
            df = fetch("BTCUSDT", interval="1m", n_candles=500)
        assert df is not None
        assert len(df) == 500

    def test_returns_expected_columns(self):
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(400)]
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)):
            df = fetch("BTCUSDT", interval="1m", n_candles=400)
        expected = {"time", "open", "high", "low", "close", "vol", "tbb"}
        assert set(df.columns) == expected

    def test_float_dtype_for_ohlcv(self):
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(400)]
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)):
            df = fetch("BTCUSDT", interval="1m", n_candles=400)
        for col in ("open", "high", "low", "close", "vol", "tbb"):
            assert df[col].dtype == float

    def test_time_converted_to_datetime(self):
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(400)]
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)):
            df = fetch("BTCUSDT", interval="1m", n_candles=400)
        assert pd.api.types.is_datetime64_any_dtype(df["time"])

    def test_sorts_by_time(self):
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(400)]
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)):
            df = fetch("BTCUSDT", interval="1m", n_candles=400)
        times = df["time"].values
        assert np.all(times[1:] >= times[:-1])

    def test_dedupes_time(self):
        # Duplicated timestamps should be dropped
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(400)]
        klines.append(klines[0])  # dup
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)):
            df = fetch("BTCUSDT", interval="1m", n_candles=401)
        assert df["time"].duplicated().sum() == 0

    def test_empty_response_returns_none(self):
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response([])):
            df = fetch("BTCUSDT", interval="1m", n_candles=400)
        assert df is None

    def test_http_error_returns_none_after_retries(self):
        # Status 404 → not 200, not 429, not 5xx → immediate break, frames empty
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response([], status_code=404)):
            df = fetch("BTCUSDT", interval="1m", n_candles=400)
        assert df is None

    def test_futures_uses_fapi_url(self):
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(400)]
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)) as mock_get:
            fetch("BTCUSDT", interval="1m", n_candles=400, futures=True)
        # First call: positional args; url is first arg
        url = mock_get.call_args_list[0].args[0]
        assert "fapi.binance.com" in url

    def test_spot_uses_api_url(self):
        klines = [_binance_kline_row(1_700_000_000_000 + i * 60_000)
                  for i in range(400)]
        with patch("core.data.base._SESSION.get",
                   return_value=_make_mock_response(klines)) as mock_get:
            fetch("BTCUSDT", interval="1m", n_candles=400, futures=False)
        url = mock_get.call_args_list[0].args[0]
        assert "api.binance.com" in url
        assert "fapi" not in url


class TestFetchAll:
    def test_min_rows_allows_short_window_results(self, monkeypatch):
        df = _valid_df(n=72)
        monkeypatch.setattr("core.data.base.fetch", lambda *args, **kwargs: df)
        out = fetch_all(["BTCUSDT"], interval="1h", n_candles=72, workers=1, min_rows=72)
        assert "BTCUSDT" in out

    def test_default_min_rows_filters_short_results(self, monkeypatch):
        df = _valid_df(n=72)
        monkeypatch.setattr("core.data.base.fetch", lambda *args, **kwargs: df)
        out = fetch_all(["BTCUSDT"], interval="1h", n_candles=72, workers=1)
        assert out == {}
