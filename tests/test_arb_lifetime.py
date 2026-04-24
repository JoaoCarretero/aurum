"""Unit tests for core/arb_lifetime.py."""
import pytest

from core.arb_lifetime import LifetimeTracker, fmt_duration, stable_key


def _pair(**kw):
    base = {"symbol": "BTC", "short_venue": "binance", "long_venue": "bybit",
            "_type": "CC"}
    base.update(kw)
    return base


# ─── stable_key ────────────────────────────────────────────────────

def test_stable_key_identical_pairs_match():
    a = _pair()
    b = _pair()
    assert stable_key(a) == stable_key(b)


def test_stable_key_differs_on_symbol():
    assert stable_key(_pair()) != stable_key(_pair(symbol="ETH"))


def test_stable_key_differs_on_venue():
    a = stable_key(_pair(short_venue="binance"))
    b = stable_key(_pair(short_venue="okx"))
    assert a != b


def test_stable_key_differs_on_type():
    a = stable_key(_pair(_type="CC"))
    b = stable_key(_pair(_type="CD"))
    assert a != b


def test_stable_key_case_insensitive_venue():
    a = stable_key(_pair(short_venue="Binance"))
    b = stable_key(_pair(short_venue="binance"))
    assert a == b


# ─── fmt_duration ──────────────────────────────────────────────────

def test_fmt_duration_under_minute():
    assert fmt_duration(30) == "0m"
    assert fmt_duration(59) == "0m"


def test_fmt_duration_exact_minutes():
    assert fmt_duration(60) == "1m"
    assert fmt_duration(90) == "1m"  # truncate to minutes <60
    assert fmt_duration(59 * 60) == "59m"


def test_fmt_duration_hours_minutes():
    assert fmt_duration(3600) == "1h0m"
    assert fmt_duration(3600 + 30 * 60) == "1h30m"
    assert fmt_duration(4 * 3600 + 15 * 60) == "4h15m"


def test_fmt_duration_negative_returns_zero():
    assert fmt_duration(-5) == "0m"


# ─── LifetimeTracker ───────────────────────────────────────────────

def test_tracker_records_first_seen():
    t = LifetimeTracker()
    key = "abc"
    t.observe(key, now=100.0)
    assert t.age(key, now=160.0) == 60.0


def test_tracker_idempotent_observe():
    t = LifetimeTracker()
    t.observe("x", now=100.0)
    t.observe("x", now=200.0)  # later observation must NOT reset
    assert t.age("x", now=300.0) == 200.0


def test_tracker_unknown_key_returns_none():
    t = LifetimeTracker()
    assert t.age("nope", now=100.0) is None


def test_tracker_observe_from_pairs_bulk():
    t = LifetimeTracker()
    pairs = [_pair(symbol="BTC"), _pair(symbol="ETH")]
    t.observe_pairs(pairs, now=100.0)
    assert t.age(stable_key(pairs[0]), now=160.0) == 60.0
    assert t.age(stable_key(pairs[1]), now=160.0) == 60.0


def test_tracker_cleanup_drops_stale():
    t = LifetimeTracker()
    t.observe("recent", now=600.0)
    t.observe("stale",  now=10.0)
    t.cleanup(now=1000.0, max_age=500.0)
    assert t.age("recent", now=1000.0) is not None
    assert t.age("stale",  now=1000.0) is None
