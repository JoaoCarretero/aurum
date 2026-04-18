"""Contract tests for core.market_data — MarketDataFetcher.

Testes via mock do requests.get, isolados por fetcher privado. Verificam
que o state é atualizado via lock, que erros viram entries em `errors`
dict, e que snapshot() retorna cópias independentes.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.market_data import MarketDataFetcher


def _mock_resp(json_data, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = json_data
    return r


@pytest.fixture
def fetcher():
    return MarketDataFetcher(["BTCUSDT", "ETHUSDT"])


# ────────────────────────────────────────────────────────────
# snapshot / init
# ────────────────────────────────────────────────────────────

class TestFetcherInit:
    def test_fresh_fetcher_empty_state(self, fetcher):
        snap = fetcher.snapshot()
        assert snap["tickers"] == {}
        assert snap["funding"] == {}
        assert snap["fear_greed"] is None
        assert snap["ls_ratio"] is None
        assert snap["last_update"] is None
        assert snap["errors"] == {}

    def test_symbols_preserved(self):
        f = MarketDataFetcher(["BTC", "ETH", "SOL"])
        assert f.symbols == ["BTC", "ETH", "SOL"]

    def test_symbols_copied_not_referenced(self):
        src = ["BTC", "ETH"]
        f = MarketDataFetcher(src)
        src.append("SOL")
        assert "SOL" not in f.symbols

    def test_snapshot_returns_independent_copy(self, fetcher):
        fetcher.tickers = {"BTCUSDT": {"price": 100.0}}
        snap = fetcher.snapshot()
        snap["tickers"]["MUTATED"] = {"price": 999}
        # Original state intacto
        assert "MUTATED" not in fetcher.tickers


# ────────────────────────────────────────────────────────────
# _fetch_tickers
# ────────────────────────────────────────────────────────────

class TestFetchTickers:
    def test_success_populates_tickers(self, fetcher):
        data = [
            {"symbol": "BTCUSDT", "lastPrice": "50000", "priceChangePercent": "2.5",
             "quoteVolume": "1000000", "highPrice": "51000", "lowPrice": "49000"},
            {"symbol": "ETHUSDT", "lastPrice": "3000", "priceChangePercent": "-1.2",
             "quoteVolume": "500000", "highPrice": "3100", "lowPrice": "2950"},
            {"symbol": "IGNOREUSDT", "lastPrice": "1.0"},  # not in symbols
        ]
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_tickers()
        assert set(fetcher.tickers.keys()) == {"BTCUSDT", "ETHUSDT"}
        assert fetcher.tickers["BTCUSDT"]["price"] == 50000.0
        assert fetcher.tickers["BTCUSDT"]["pct"] == 2.5

    def test_filter_only_tracked_symbols(self, fetcher):
        data = [{"symbol": "XRPUSDT", "lastPrice": "1", "priceChangePercent": "0",
                 "quoteVolume": "1", "highPrice": "1", "lowPrice": "1"}]
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_tickers()
        assert fetcher.tickers == {}

    def test_http_error_records_to_errors_dict(self, fetcher):
        with patch("requests.get", return_value=_mock_resp({}, status_code=500)):
            fetcher._fetch_tickers()
        assert "tickers" in fetcher.errors
        assert "500" in fetcher.errors["tickers"]

    def test_exception_records_to_errors(self, fetcher):
        with patch("requests.get", side_effect=Exception("timeout")):
            fetcher._fetch_tickers()
        assert "tickers" in fetcher.errors

    def test_success_clears_previous_error(self, fetcher):
        fetcher.errors["tickers"] = "previous failure"
        data = [{"symbol": "BTCUSDT", "lastPrice": "100", "priceChangePercent": "0",
                 "quoteVolume": "1", "highPrice": "1", "lowPrice": "1"}]
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_tickers()
        assert "tickers" not in fetcher.errors

    def test_malformed_entry_skipped(self, fetcher):
        # Entry com campos faltando → skipped sem crashear
        data = [
            {"symbol": "BTCUSDT", "lastPrice": "100", "priceChangePercent": "0",
             "quoteVolume": "1", "highPrice": "1", "lowPrice": "1"},
            {"symbol": "ETHUSDT"},  # missing fields
        ]
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_tickers()
        assert "BTCUSDT" in fetcher.tickers
        assert "ETHUSDT" not in fetcher.tickers


# ────────────────────────────────────────────────────────────
# _fetch_funding
# ────────────────────────────────────────────────────────────

class TestFetchFunding:
    def test_success_populates_funding(self, fetcher):
        data = [
            {"symbol": "BTCUSDT", "lastFundingRate": "0.0001"},
            {"symbol": "ETHUSDT", "lastFundingRate": "0.00015"},
        ]
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_funding()
        assert fetcher.funding["BTCUSDT"] == 0.0001
        assert fetcher.funding["ETHUSDT"] == 0.00015

    def test_http_error_records(self, fetcher):
        with patch("requests.get", return_value=_mock_resp({}, status_code=503)):
            fetcher._fetch_funding()
        assert "funding" in fetcher.errors

    def test_missing_rate_defaults_to_zero(self, fetcher):
        data = [{"symbol": "BTCUSDT"}]  # no lastFundingRate
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_funding()
        assert fetcher.funding.get("BTCUSDT") == 0.0


# ────────────────────────────────────────────────────────────
# funding_avg
# ────────────────────────────────────────────────────────────

class TestFundingAvg:
    def test_empty_funding_returns_none(self, fetcher):
        assert fetcher.funding_avg() is None

    def test_averages_across_symbols(self, fetcher):
        fetcher.funding = {"BTC": 0.01, "ETH": 0.03}
        assert fetcher.funding_avg() == 0.02


# ────────────────────────────────────────────────────────────
# _fetch_fear_greed
# ────────────────────────────────────────────────────────────

class TestFetchFearGreed:
    def test_success_populates(self, fetcher):
        data = {"data": [{"value": "75", "value_classification": "Greed"}]}
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_fear_greed()
        assert fetcher.fear_greed == {"value": 75, "classification": "Greed"}

    def test_non_numeric_value_defaults_to_zero(self, fetcher):
        data = {"data": [{"value": "not_a_number", "value_classification": "?"}]}
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_fear_greed()
        assert fetcher.fear_greed["value"] == 0

    def test_missing_data_key_handled(self, fetcher):
        # resposta sem "data" → default row vazio → value=0
        with patch("requests.get", return_value=_mock_resp({})):
            fetcher._fetch_fear_greed()
        assert fetcher.fear_greed == {"value": 0, "classification": ""}

    def test_http_error_records(self, fetcher):
        with patch("requests.get", return_value=_mock_resp({}, status_code=500)):
            fetcher._fetch_fear_greed()
        assert "fear_greed" in fetcher.errors


# ────────────────────────────────────────────────────────────
# _fetch_ls_ratio
# ────────────────────────────────────────────────────────────

class TestFetchLsRatio:
    def test_success_populates(self, fetcher):
        data = [{"longShortRatio": "1.8"}]
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_ls_ratio()
        assert fetcher.ls_ratio == 1.8

    def test_empty_response_no_update(self, fetcher):
        fetcher.ls_ratio = None
        with patch("requests.get", return_value=_mock_resp([])):
            fetcher._fetch_ls_ratio()
        assert fetcher.ls_ratio is None

    def test_invalid_value_does_not_override_previous(self, fetcher):
        fetcher.ls_ratio = 1.5  # previous good value
        data = [{"longShortRatio": "not_a_number"}]
        with patch("requests.get", return_value=_mock_resp(data)):
            fetcher._fetch_ls_ratio()
        # Invalid value → early return without changing state
        assert fetcher.ls_ratio == 1.5

    def test_http_error_records(self, fetcher):
        with patch("requests.get", return_value=_mock_resp({}, status_code=429)):
            fetcher._fetch_ls_ratio()
        assert "ls_ratio" in fetcher.errors
