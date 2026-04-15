"""Contract tests for core.sentiment (THOTH / BRIDGEWATER).

Cobrem 3 fetchers HTTP (mockados) + 4 funções de scoring puras:
- fetch_funding_rate, fetch_open_interest, fetch_long_short_ratio
- funding_zscore (rolling z + fillna)
- oi_delta_signal (OI vs price cross-dynamics)
- ls_ratio_signal (contrarian step function)
- composite_sentiment (weighted combo com contrarian funding)
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from core.sentiment import (
    composite_sentiment,
    fetch_funding_rate,
    fetch_long_short_ratio,
    fetch_open_interest,
    funding_zscore,
    ls_ratio_signal,
    oi_delta_signal,
)


def _mock_resp(json_data, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    return r


# ────────────────────────────────────────────────────────────
# fetch_funding_rate
# ────────────────────────────────────────────────────────────

class TestFetchFundingRate:
    def test_success_returns_dataframe_with_expected_cols(self):
        data = [{"fundingTime": 1_700_000_000_000 + i * 3600_000,
                 "fundingRate": "0.0001"} for i in range(10)]
        with patch("requests.get", return_value=_mock_resp(data)):
            df = fetch_funding_rate("BTCUSDT", limit=10)
        assert df is not None
        assert set(df.columns) == {"time", "funding_rate"}
        assert len(df) == 10

    def test_funding_rate_is_float(self):
        data = [{"fundingTime": 1_700_000_000_000, "fundingRate": "0.00015"}]
        with patch("requests.get", return_value=_mock_resp(data)):
            df = fetch_funding_rate("BTCUSDT")
        assert df["funding_rate"].dtype == float

    def test_time_converted_to_datetime(self):
        data = [{"fundingTime": 1_700_000_000_000, "fundingRate": "0.0"}]
        with patch("requests.get", return_value=_mock_resp(data)):
            df = fetch_funding_rate("BTCUSDT")
        assert pd.api.types.is_datetime64_any_dtype(df["time"])

    def test_non_200_returns_none(self):
        with patch("requests.get", return_value=_mock_resp({}, status_code=500)):
            assert fetch_funding_rate("BTCUSDT") is None

    def test_empty_response_returns_none(self):
        with patch("requests.get", return_value=_mock_resp([])):
            assert fetch_funding_rate("BTCUSDT") is None

    def test_exception_returns_none(self):
        with patch("requests.get", side_effect=Exception("network down")):
            assert fetch_funding_rate("BTCUSDT") is None


# ────────────────────────────────────────────────────────────
# fetch_open_interest
# ────────────────────────────────────────────────────────────

class TestFetchOpenInterest:
    def test_success_returns_dataframe(self):
        data = [{"timestamp": 1_700_000_000_000 + i * 900_000,
                 "sumOpenInterest": "1000.0",
                 "sumOpenInterestValue": "50000000.0"} for i in range(5)]
        with patch("requests.get", return_value=_mock_resp(data)):
            df = fetch_open_interest("BTCUSDT")
        assert df is not None
        assert set(df.columns) == {"time", "oi", "oi_value"}

    def test_non_200_returns_none(self):
        with patch("requests.get", return_value=_mock_resp({}, status_code=404)):
            assert fetch_open_interest("BTCUSDT") is None

    def test_empty_returns_none(self):
        with patch("requests.get", return_value=_mock_resp([])):
            assert fetch_open_interest("BTCUSDT") is None


# ────────────────────────────────────────────────────────────
# fetch_long_short_ratio
# ────────────────────────────────────────────────────────────

class TestFetchLongShortRatio:
    def test_success_returns_dataframe(self):
        data = [{"timestamp": 1_700_000_000_000,
                 "longShortRatio": "1.5",
                 "longAccount": "0.6",
                 "shortAccount": "0.4"}]
        with patch("requests.get", return_value=_mock_resp(data)):
            df = fetch_long_short_ratio("BTCUSDT")
        assert df is not None
        assert set(df.columns) == {"time", "ls_ratio", "long_pct", "short_pct"}

    def test_exception_returns_none(self):
        with patch("requests.get", side_effect=Exception("boom")):
            assert fetch_long_short_ratio("BTCUSDT") is None


# ────────────────────────────────────────────────────────────
# funding_zscore
# ────────────────────────────────────────────────────────────

class TestFundingZscore:
    def test_returns_series(self):
        df = pd.DataFrame({"funding_rate": np.random.default_rng(0).normal(0, 0.001, 50)})
        z = funding_zscore(df)
        assert isinstance(z, pd.Series)
        assert len(z) == len(df)

    def test_nan_filled_with_zero(self):
        # Warmup bars have < min_periods → NaN → fillna(0)
        df = pd.DataFrame({"funding_rate": [0.001] * 3})
        z = funding_zscore(df, window=30)
        assert (z == 0).all()

    def test_zero_std_yields_zero(self):
        # Constant series → std=0 → z=NaN → fillna(0)
        df = pd.DataFrame({"funding_rate": [0.001] * 50})
        z = funding_zscore(df)
        assert (z == 0).all()

    def test_sign_of_z_matches_deviation(self):
        # Series ends with a big positive outlier → z positive at the end
        rates = [0.0] * 49 + [0.01]
        df = pd.DataFrame({"funding_rate": rates})
        z = funding_zscore(df)
        assert z.iloc[-1] > 0


# ────────────────────────────────────────────────────────────
# oi_delta_signal
# ────────────────────────────────────────────────────────────

class TestOiDeltaSignal:
    def _make_price(self, n=50, start=100.0, drift=0.0):
        times = pd.date_range("2026-01-01", periods=n, freq="15min")
        close = start + drift * np.arange(n)
        return pd.DataFrame({"time": times, "close": close})

    def _make_oi(self, n=50, start=1_000.0, drift=0.0):
        times = pd.date_range("2026-01-01", periods=n, freq="15min")
        return pd.DataFrame({"time": times, "oi": start + drift * np.arange(n)})

    def test_returns_merged_with_signal_column(self):
        price = self._make_price()
        oi = self._make_oi()
        out = oi_delta_signal(oi, price, window=10)
        assert "oi_signal" in out.columns
        assert "oi_delta" in out.columns
        assert "price_delta" in out.columns

    def test_signal_values_in_expected_set(self):
        price = self._make_price(drift=0.5)
        oi = self._make_oi(drift=5.0)
        out = oi_delta_signal(oi, price, window=10)
        assert set(out["oi_signal"].unique()).issubset({-1.0, -0.3, 0.0, 0.3, 1.0})

    def test_oi_up_price_down_produces_bearish(self):
        # OI sobe, preço cai → -1 (shorts acumulando)
        price = self._make_price(n=50, start=100.0, drift=-0.5)  # forte queda
        oi = self._make_oi(n=50, start=1_000.0, drift=20.0)      # forte alta OI
        out = oi_delta_signal(oi, price, window=10)
        tail = out["oi_signal"].iloc[-10:]
        assert (tail == -1.0).any()

    def test_flat_data_yields_zero_signal(self):
        # Sem variação em nenhum dos dois
        price = self._make_price(drift=0.0)
        oi = self._make_oi(drift=0.0)
        out = oi_delta_signal(oi, price, window=10)
        assert (out["oi_signal"] == 0.0).all()


# ────────────────────────────────────────────────────────────
# ls_ratio_signal
# ────────────────────────────────────────────────────────────

class TestLsRatioSignal:
    def test_very_long_crowd_bearish(self):
        df = pd.DataFrame({"ls_ratio": [2.5]})
        s = ls_ratio_signal(df)
        assert s.iloc[0] == -1.0

    def test_mildly_long_crowd_weakly_bearish(self):
        df = pd.DataFrame({"ls_ratio": [1.7]})
        s = ls_ratio_signal(df)
        assert s.iloc[0] == -0.5

    def test_very_short_crowd_bullish(self):
        df = pd.DataFrame({"ls_ratio": [0.3]})
        s = ls_ratio_signal(df)
        assert s.iloc[0] == 1.0

    def test_mildly_short_crowd_weakly_bullish(self):
        df = pd.DataFrame({"ls_ratio": [0.6]})
        s = ls_ratio_signal(df)
        assert s.iloc[0] == 0.5

    def test_neutral_ratio_zero_signal(self):
        df = pd.DataFrame({"ls_ratio": [1.0]})
        s = ls_ratio_signal(df)
        assert s.iloc[0] == 0.0

    def test_returns_pandas_series(self):
        df = pd.DataFrame({"ls_ratio": [1.0, 2.5, 0.3]})
        s = ls_ratio_signal(df)
        assert isinstance(s, pd.Series)
        assert len(s) == 3


# ────────────────────────────────────────────────────────────
# composite_sentiment
# ────────────────────────────────────────────────────────────

class TestCompositeSentiment:
    def test_returns_float_in_minus_one_one(self):
        score = composite_sentiment(funding_z=0.5, oi_sig=0.5, ls_sig=0.5)
        assert isinstance(score, float)
        assert -1.0 <= score <= 1.0

    def test_funding_is_contrarian(self):
        # Positive funding_z (longs pagando) → signal bearish (negativo)
        s_positive_fz = composite_sentiment(funding_z=2.0, oi_sig=0.0, ls_sig=0.0)
        s_negative_fz = composite_sentiment(funding_z=-2.0, oi_sig=0.0, ls_sig=0.0)
        assert s_positive_fz < s_negative_fz

    def test_all_bullish_saturates_positive(self):
        # Funding_z muito negativo (shorts pagando) + OI bullish + LS bullish
        score = composite_sentiment(funding_z=-4.0, oi_sig=1.0, ls_sig=1.0)
        assert score == 1.0

    def test_all_bearish_saturates_negative(self):
        score = composite_sentiment(funding_z=4.0, oi_sig=-1.0, ls_sig=-1.0)
        assert score == -1.0

    def test_neutral_inputs_near_zero(self):
        score = composite_sentiment(funding_z=0.0, oi_sig=0.0, ls_sig=0.0)
        assert score == 0.0

    def test_custom_weights_sum_applied(self):
        # 100% peso em funding → score = -funding_z/2 clipped
        score = composite_sentiment(
            funding_z=1.0, oi_sig=0.0, ls_sig=0.0,
            w_funding=1.0, w_oi=0.0, w_ls=0.0,
        )
        assert abs(score - (-0.5)) < 1e-9
