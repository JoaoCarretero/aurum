"""Contract tests for core.sentiment (THOTH / BRIDGEWATER).

Cobrem 3 fetchers HTTP (mockados) + 4 funções de scoring puras:
- fetch_funding_rate, fetch_open_interest, fetch_long_short_ratio
- funding_zscore (rolling z + fillna)
- oi_delta_signal (OI vs price cross-dynamics)
- ls_ratio_signal (contrarian step function)
- composite_sentiment (weighted combo com contrarian funding)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

import core.sentiment as sentiment
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

    def test_historical_slice_uses_local_cache_without_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sentiment, "_SENTIMENT_CACHE_DIR", tmp_path)
        cache_dir = Path(tmp_path) / "open_interest"
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01 00:00:00", periods=5, freq="15min"),
                "oi": [1000, 1001, 1002, 1003, 1004],
                "oi_value": [50000, 50010, 50020, 50030, 50040],
            }
        ).to_csv(cache_dir / "BTCUSDT_15m.csv", index=False)

        with patch.object(sentiment, "_fetch_binance_rows") as mock_fetch:
            df = fetch_open_interest(
                "BTCUSDT",
                period="15m",
                limit=3,
                end_time_ms=int(pd.Timestamp("2026-01-01 01:00:00").timestamp() * 1000),
            )

        assert mock_fetch.call_count == 0
        assert df is not None
        assert df["oi"].tolist() == [1002, 1003, 1004]

    def test_historical_probe_propagates_endtime_to_live_fetch(self, tmp_path, monkeypatch):
        """When cache is insufficient for the requested OOS window, the live
        fetch MUST carry endTime — otherwise Binance returns the live tail,
        which is look-ahead in any backtest. Bug 2 fix (2026-04-17).
        """
        monkeypatch.setattr(sentiment, "_SENTIMENT_CACHE_DIR", tmp_path)
        payload = [
            {
                "timestamp": 1_700_000_000_000 + i * 900_000,
                "sumOpenInterest": f"{1000.0 + i}",
                "sumOpenInterestValue": f"{50000000.0 + i}",
            }
            for i in range(5)
        ]
        with patch("requests.get", return_value=_mock_resp(payload)) as mock_get:
            df = fetch_open_interest("BTCUSDT", period="15m", limit=5, end_time_ms=123)

        assert df is None  # end_time=123 (1970) is before the mocked payload
        assert mock_get.call_args.kwargs["params"]["endTime"] == 123
        cached = pd.read_csv(Path(tmp_path) / "open_interest" / "BTCUSDT_15m.csv")
        assert len(cached) == 5

    def test_live_fetch_without_end_time_ms_omits_endtime(self, tmp_path, monkeypatch):
        """When no end_time_ms is given (live mode), endTime must NOT be
        passed — that would cap the query unnecessarily.
        """
        monkeypatch.setattr(sentiment, "_SENTIMENT_CACHE_DIR", tmp_path)
        payload = [
            {
                "timestamp": 1_700_000_000_000 + i * 900_000,
                "sumOpenInterest": f"{1000.0 + i}",
                "sumOpenInterestValue": f"{50000000.0 + i}",
            }
            for i in range(5)
        ]
        with patch("requests.get", return_value=_mock_resp(payload)) as mock_get:
            fetch_open_interest("BTCUSDT", period="15m", limit=5)

        assert "endTime" not in mock_get.call_args.kwargs["params"]

    def test_live_fetch_returns_full_merged_cache_not_just_tail_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sentiment, "_SENTIMENT_CACHE_DIR", tmp_path)
        cache_dir = Path(tmp_path) / "open_interest"
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01 00:00:00", periods=5, freq="15min"),
                "oi": [1000, 1001, 1002, 1003, 1004],
                "oi_value": [50000, 50010, 50020, 50030, 50040],
            }
        ).to_csv(cache_dir / "BTCUSDT_15m.csv", index=False)
        payload = [
            {
                "timestamp": int(pd.Timestamp("2026-01-01 01:15:00").timestamp() * 1000),
                "sumOpenInterest": "1005.0",
                "sumOpenInterestValue": "50050.0",
            }
        ]
        with patch("requests.get", return_value=_mock_resp(payload)):
            df = fetch_open_interest("BTCUSDT", period="15m", limit=1)

        assert df is not None
        assert len(df) == 6
        assert df["oi"].tolist() == [1000, 1001, 1002, 1003, 1004, 1005]

    def test_cached_loader_drops_corrupt_time_rows_instead_of_failing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sentiment, "_SENTIMENT_CACHE_DIR", tmp_path)
        cache_dir = Path(tmp_path) / "open_interest"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "XRPUSDT_15m.csv").write_text(
            "time,oi,oi_value\n"
            "2026-03-18 14:30:00,1000,50000\n"
            "0753.75146,1001,50010\n"
            "2026-03-18 14:45:00,1002,50020\n",
            encoding="utf-8",
        )

        df = sentiment._load_cached_frame(
            "open_interest",
            "XRPUSDT",
            "15m",
            ["time", "oi", "oi_value"],
        )

        assert df is not None
        assert len(df) == 2
        assert df["oi"].tolist() == [1000, 1002]


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

    def test_historical_slice_uses_local_cache_without_network(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sentiment, "_SENTIMENT_CACHE_DIR", tmp_path)
        cache_dir = Path(tmp_path) / "long_short_ratio"
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01 00:00:00", periods=5, freq="15min"),
                "ls_ratio": [0.8, 0.9, 1.0, 1.1, 1.2],
                "long_pct": [0.44, 0.45, 0.46, 0.47, 0.48],
                "short_pct": [0.56, 0.55, 0.54, 0.53, 0.52],
            }
        ).to_csv(cache_dir / "BTCUSDT_15m.csv", index=False)

        with patch("requests.get") as mock_get:
            df = fetch_long_short_ratio(
                "BTCUSDT",
                period="15m",
                limit=2,
                end_time_ms=int(pd.Timestamp("2026-01-01 01:00:00").timestamp() * 1000),
            )

        assert mock_get.call_count == 0
        assert df is not None
        assert df["ls_ratio"].tolist() == [1.1, 1.2]

    def test_live_fetch_returns_full_merged_cache_not_just_tail_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sentiment, "_SENTIMENT_CACHE_DIR", tmp_path)
        cache_dir = Path(tmp_path) / "long_short_ratio"
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "time": pd.date_range("2026-01-01 00:00:00", periods=4, freq="15min"),
                "ls_ratio": [0.8, 0.9, 1.0, 1.1],
                "long_pct": [0.44, 0.45, 0.46, 0.47],
                "short_pct": [0.56, 0.55, 0.54, 0.53],
            }
        ).to_csv(cache_dir / "BTCUSDT_15m.csv", index=False)
        payload = [
            {
                "timestamp": int(pd.Timestamp("2026-01-01 01:00:00").timestamp() * 1000),
                "longShortRatio": "1.2",
                "longAccount": "0.48",
                "shortAccount": "0.52",
            }
        ]
        with patch("requests.get", return_value=_mock_resp(payload)):
            df = fetch_long_short_ratio("BTCUSDT", period="15m", limit=1)

        assert df is not None
        assert len(df) == 5
        assert df["ls_ratio"].tolist() == [0.8, 0.9, 1.0, 1.1, 1.2]


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

    def test_normalizes_datetime_units_before_merge_asof(self):
        """Pandas 3.14 rejects merge_asof on datetime64[ns] vs datetime64[us].

        BRIDGEWATER swallows OI build exceptions, so this contract ensures
        OI cannot silently disappear just because the cached OI frame and the
        price frame carry different datetime units.
        """
        price = self._make_price(n=80)
        oi = self._make_oi(n=80)
        price["time"] = pd.to_datetime(price["time"]).astype("datetime64[ns]")
        oi["time"] = pd.to_datetime(oi["time"]).astype("datetime64[us]")

        out = oi_delta_signal(oi, price, window=10)

        assert len(out) == len(price)
        assert "oi_signal" in out.columns

    def test_signal_values_in_expected_set(self):
        price = self._make_price(drift=0.5)
        oi = self._make_oi(drift=5.0)
        out = oi_delta_signal(oi, price, window=10)
        assert set(out["oi_signal"].unique()).issubset({-1.0, -0.3, 0.0, 0.3, 1.0})

    def test_oi_surge_vs_price_crash_produces_bearish(self):
        """Bug 5 fix: signal fires on STATISTICAL deviation, not absolute %.

        A baseline of low-volatility noise followed by a sharp divergence
        (OI surges while price crashes) must trigger -1.0 in the divergent
        tail, demonstrating the z-score is doing its job.
        """
        n = 300
        rng = np.random.default_rng(0)
        times = pd.date_range("2026-01-01", periods=n, freq="15min")
        # Quiet baseline for first 270 bars, then 30 bars of divergence
        oi_base = 1000.0 + np.cumsum(rng.normal(0, 0.2, n))
        price_base = 100.0 + np.cumsum(rng.normal(0, 0.05, n))
        oi_base[270:] += np.arange(30) * 10        # OI rising fast in tail
        price_base[270:] -= np.arange(30) * 0.8    # Price crashing in tail
        oi = pd.DataFrame({"time": times, "oi": oi_base})
        price = pd.DataFrame({"time": times, "close": price_base})
        out = oi_delta_signal(oi, price, window=10, zscore_window=100)
        tail = out["oi_signal"].iloc[-10:]
        assert (tail == -1.0).any(), f"tail signal = {tail.tolist()}"

    def test_flat_data_yields_zero_signal(self):
        # Sem variação em nenhum dos dois
        price = self._make_price(drift=0.0)
        oi = self._make_oi(drift=0.0)
        out = oi_delta_signal(oi, price, window=10)
        assert (out["oi_signal"] == 0.0).all()

    def test_warmup_yields_zero_signal_before_min_periods(self):
        """Bug 5 fix characterization: while the rolling z-score window has
        fewer than min_periods observations, the signal must remain zero.
        """
        price = self._make_price(n=50, drift=-0.5)
        oi = self._make_oi(n=50, drift=20.0)
        out = oi_delta_signal(oi, price, window=10, zscore_window=200)
        # First 20 bars are fully below any min_periods threshold → zero
        assert (out["oi_signal"].iloc[:20] == 0.0).all()


# ────────────────────────────────────────────────────────────
# ls_ratio_signal
# ────────────────────────────────────────────────────────────

class TestLsRatioSignal:
    """Tests for the Bug-3-fix rolling z-score signal (2026-04-17).

    Mechanism: contrarian signal fires when ls_ratio deviates >=1σ (weak)
    or >=2σ (strong) from its rolling 1-week mean. Symmetric by construction.
    """

    def test_warmup_is_zero_until_min_periods(self):
        """Insufficient history -> signal is flat zero (no fake bias)."""
        df = pd.DataFrame({"ls_ratio": [1.5] * 5})
        s = ls_ratio_signal(df)
        assert (s == 0.0).all()

    def test_constant_ratio_returns_zero(self):
        """No variance -> std=0 -> z=NaN -> filled to 0 -> no signal."""
        df = pd.DataFrame({"ls_ratio": [1.8] * 200})
        s = ls_ratio_signal(df)
        assert (s == 0.0).all()

    def test_strong_positive_deviation_is_bearish(self):
        """Crowd unusually long (+2sigma) -> contrarian bearish = -1.0."""
        base = [1.0] * 300
        # Tail swings to ~1.5 — well above mean=1.0, std small
        tail = [1.5] * 10
        rng = np.random.default_rng(0)
        # Add tiny noise to avoid zero std
        noise = list(rng.normal(0, 0.01, 300))
        ratios = [b + n for b, n in zip(base, noise)] + tail
        df = pd.DataFrame({"ls_ratio": ratios})
        s = ls_ratio_signal(df)
        # Last bar: z >> 2 -> signal -1.0
        assert s.iloc[-1] == -1.0

    def test_strong_negative_deviation_is_bullish(self):
        """Crowd unusually short (-2sigma) -> contrarian bullish = +1.0."""
        base = [1.0] * 300
        tail = [0.5] * 10
        rng = np.random.default_rng(0)
        noise = list(rng.normal(0, 0.01, 300))
        ratios = [b + n for b, n in zip(base, noise)] + tail
        df = pd.DataFrame({"ls_ratio": ratios})
        s = ls_ratio_signal(df)
        assert s.iloc[-1] == 1.0

    def test_symmetric_in_magnitude(self):
        """Same deviation either direction must produce same |signal|."""
        rng = np.random.default_rng(0)
        noise_up = list(rng.normal(0, 0.01, 300))
        rng2 = np.random.default_rng(0)
        noise_dn = list(rng2.normal(0, 0.01, 300))
        up = [1.0 + n for n in noise_up] + [1.3] * 5  # ~1.5 sigma above
        dn = [1.0 + n for n in noise_dn] + [0.7] * 5  # ~1.5 sigma below
        s_up = ls_ratio_signal(pd.DataFrame({"ls_ratio": up}))
        s_dn = ls_ratio_signal(pd.DataFrame({"ls_ratio": dn}))
        assert abs(s_up.iloc[-1]) == abs(s_dn.iloc[-1])

    def test_returns_pandas_series(self):
        df = pd.DataFrame({"ls_ratio": [1.0, 2.5, 0.3]})
        s = ls_ratio_signal(df)
        assert isinstance(s, pd.Series)
        assert len(s) == 3

    def test_propagates_datetime_index_when_time_column_present(self):
        """Bug 1 fix — returned Series must be indexed by event time so the
        downstream aligner maps candles to the correct tick (not positional).
        """
        times = pd.date_range("2025-01-01", periods=4, freq="15min")
        df = pd.DataFrame({"time": times, "ls_ratio": [1.0, 1.1, 1.2, 1.3]})
        s = ls_ratio_signal(df)
        assert pd.api.types.is_datetime64_any_dtype(s.index)


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
