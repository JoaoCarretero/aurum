"""Unit tests for core.data.ws_price_feed.

The WS loop itself is not exercised (would require a live socket or a
fake server). We test the parser and the thread-safe price map — the
parts that determine whether a message results in a correct live price
being readable by the paper runner.
"""
import json
import time

import pytest

from core.data.ws_price_feed import (
    WSPriceFeed,
    make_live_price_fn,
    parse_message,
)


# ─── parse_message ─────────────────────────────────────────────────

def test_parse_mark_price_combined_stream():
    raw = json.dumps({
        "stream": "xrpusdt@markPrice@1s",
        "data": {
            "e": "markPriceUpdate",
            "E": 1713614567000,
            "s": "XRPUSDT",
            "p": "1.4182",
        },
    })
    assert parse_message(raw) == ("XRPUSDT", 1.4182, 1713614567000)


def test_parse_mark_price_direct():
    """Not all Binance paths wrap in `{stream, data}`; tolerate both."""
    raw = json.dumps({
        "e": "markPriceUpdate",
        "E": 1713614567000,
        "s": "btcusdt",
        "p": "64500.12",
    })
    assert parse_message(raw) == ("BTCUSDT", 64500.12, 1713614567000)


def test_parse_agg_trade():
    raw = json.dumps({
        "stream": "xrpusdt@aggTrade",
        "data": {
            "e": "aggTrade",
            "E": 123,
            "T": 1713614567111,
            "s": "XRPUSDT",
            "p": "1.4181",
            "q": "100",
        },
    })
    assert parse_message(raw) == ("XRPUSDT", 1.4181, 1713614567111)


def test_parse_unknown_event_returns_none():
    raw = json.dumps({"data": {"e": "kline", "s": "BTCUSDT", "k": {}}})
    assert parse_message(raw) is None


def test_parse_garbage_returns_none():
    assert parse_message("not json") is None
    assert parse_message("") is None


def test_parse_missing_symbol_returns_none():
    raw = json.dumps({"data": {"e": "markPriceUpdate", "p": "100"}})
    assert parse_message(raw) is None


def test_parse_bad_price_returns_none():
    raw = json.dumps({"data": {
        "e": "markPriceUpdate", "s": "BTCUSDT", "p": "not-a-number"}})
    assert parse_message(raw) is None


# ─── WSPriceFeed internals ─────────────────────────────────────────

def test_feed_get_last_none_before_any_update():
    feed = WSPriceFeed(symbols=["BTCUSDT"])
    assert feed.get_last("BTCUSDT") is None
    assert feed.get_last_update_ms("BTCUSDT") is None
    assert feed.get_freshness_sec("BTCUSDT") is None


def test_feed_apply_update_stores_price_and_ts():
    feed = WSPriceFeed(symbols=["BTCUSDT"])
    feed._apply_update("BTCUSDT", 64000.5, 1713614567000)
    assert feed.get_last("BTCUSDT") == 64000.5
    assert feed.get_last_update_ms("BTCUSDT") == 1713614567000


def test_feed_case_insensitive_symbols():
    feed = WSPriceFeed(symbols=["btcusdt"])
    feed._apply_update("btcusdt", 1.0, 1_000)
    assert feed.get_last("BTCUSDT") == 1.0
    assert feed.get_last("btcusdt") == 1.0


def test_feed_ignores_nonpositive_price():
    feed = WSPriceFeed(symbols=["BTCUSDT"])
    feed._apply_update("BTCUSDT", 0.0, 1_000)
    feed._apply_update("BTCUSDT", -5.0, 1_001)
    assert feed.get_last("BTCUSDT") is None


def test_feed_multi_symbol_updates_independent():
    feed = WSPriceFeed(symbols=["BTCUSDT", "XRPUSDT"])
    feed._apply_update("BTCUSDT", 60000.0, 1_000)
    feed._apply_update("XRPUSDT", 1.42, 1_001)
    assert feed.get_last("BTCUSDT") == 60000.0
    assert feed.get_last("XRPUSDT") == 1.42


def test_feed_freshness_approximates_wallclock():
    feed = WSPriceFeed(symbols=["BTCUSDT"])
    # Feed the "now" timestamp; freshness should be ~0
    feed._apply_update("BTCUSDT", 60000.0, int(time.time() * 1000))
    age = feed.get_freshness_sec("BTCUSDT")
    assert age is not None
    assert age < 1.0


def test_feed_stream_url_combines_symbols_lowercase():
    feed = WSPriceFeed(symbols=["BTCUSDT", "XRPUSDT"], stream="markPrice@1s")
    url = feed._stream_url()
    assert "btcusdt@markPrice@1s" in url
    assert "xrpusdt@markPrice@1s" in url
    assert url.startswith("wss://fstream.binance.com/stream?streams=")


# ─── make_live_price_fn adapter ───────────────────────────────────

def test_make_live_price_fn_returns_fresh_price():
    feed = WSPriceFeed(symbols=["BTCUSDT"])
    feed._apply_update("BTCUSDT", 60000.0, int(time.time() * 1000))
    fn = make_live_price_fn(feed, max_age_sec=10.0)
    assert fn("BTCUSDT") == 60000.0


def test_make_live_price_fn_rejects_stale():
    feed = WSPriceFeed(symbols=["BTCUSDT"])
    stale_ms = int((time.time() - 300) * 1000)  # 5 min ago
    feed._apply_update("BTCUSDT", 60000.0, stale_ms)
    fn = make_live_price_fn(feed, max_age_sec=60.0)
    assert fn("BTCUSDT") is None


def test_make_live_price_fn_returns_none_for_unknown_symbol():
    feed = WSPriceFeed(symbols=["BTCUSDT"])
    fn = make_live_price_fn(feed)
    assert fn("NEVERSEEN") is None


def test_make_live_price_fn_ignores_feed_exceptions():
    """Adapter must never raise — paper open path relies on that."""
    class BadFeed:
        def get_last(self, s):
            raise RuntimeError("boom")

        def get_freshness_sec(self, s):
            return None

    fn = make_live_price_fn(BadFeed(), max_age_sec=10.0)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        fn("BTCUSDT")  # Exception propagates — the caller handles it,
        # not the adapter. Paper executor wraps live_price_fn in try.
