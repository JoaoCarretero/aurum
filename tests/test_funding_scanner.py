"""Tests for funding scanner — new venue fetchers (Fase C).

These tests are purely structural — they verify the registry, callable
signatures, and _mk() helper without making real network calls.
"""
import pytest


def test_venue_fetchers_registry_has_13_venues():
    from core.funding_scanner import VENUE_FETCHERS
    assert len(VENUE_FETCHERS) >= 13
    for name in ("gmx", "vertex", "aevo", "drift", "apex"):
        assert name in VENUE_FETCHERS, f"Missing venue: {name}"
        fn, vtype = VENUE_FETCHERS[name]
        assert callable(fn), f"{name}: fn not callable"
        assert vtype == "DEX", f"{name}: expected DEX, got {vtype}"


def test_fetcher_functions_callable():
    from core.funding_scanner import VENUE_FETCHERS
    for name in ("gmx", "vertex", "aevo", "drift", "apex"):
        fn, _ = VENUE_FETCHERS[name]
        assert callable(fn), f"{name}: fn not callable"


def test_mk_helper_builds_valid_opp():
    from core.funding_scanner import _mk
    opp = _mk("BTC", "test_venue", "DEX", 0.0001, 1.0, 50000.0, 1e6, 5e5)
    assert opp.symbol == "BTC"
    assert opp.venue == "test_venue"
    assert opp.venue_type == "DEX"
    assert opp.apr > 0
    assert opp.risk in ("LOW", "MED", "HIGH")
    assert opp.direction == "SHORT"   # positive rate → SHORT


def test_mk_helper_negative_rate():
    from core.funding_scanner import _mk
    opp = _mk("ETH", "test_venue", "DEX", -0.0001, 8.0, 3000.0, 2e6, 1e6)
    assert opp.direction == "LONG"
    assert opp.apr < 0


def test_mk_helper_high_risk_when_zero_vol_oi():
    """Venues like Vertex pass 0 vol/OI — should classify as HIGH risk."""
    from core.funding_scanner import _mk
    opp = _mk("SOL", "vertex", "DEX", 0.0005, 8.0, 150.0, 0.0, 0.0)
    assert opp.risk == "HIGH"


def test_all_original_venues_still_present():
    """Regression — original 8 venues must not be removed."""
    from core.funding_scanner import VENUE_FETCHERS
    original = {"hyperliquid", "dydx", "paradex", "binance", "bybit", "gate", "bitget", "bingx"}
    for name in original:
        assert name in VENUE_FETCHERS, f"Original venue missing: {name}"


def test_dex_venues_labelled_correctly():
    from core.funding_scanner import VENUE_FETCHERS
    dex_venues = {"hyperliquid", "dydx", "paradex", "gmx", "vertex", "aevo", "drift", "apex"}
    for name in dex_venues:
        _, vtype = VENUE_FETCHERS[name]
        assert vtype == "DEX", f"{name}: expected DEX got {vtype}"


def test_cex_venues_labelled_correctly():
    from core.funding_scanner import VENUE_FETCHERS
    cex_venues = {"binance", "bybit", "gate", "bitget", "bingx"}
    for name in cex_venues:
        _, vtype = VENUE_FETCHERS[name]
        assert vtype == "CEX", f"{name}: expected CEX got {vtype}"


def test_vertex_product_map_has_expected_symbols():
    from core.funding_scanner import _VERTEX_PRODUCTS
    assert _VERTEX_PRODUCTS[2] == "BTC"
    assert _VERTEX_PRODUCTS[4] == "ETH"
    assert len(_VERTEX_PRODUCTS) >= 10


def test_is_usdt_base_helper():
    from core.funding_scanner import _is_usdt_base
    assert _is_usdt_base("BTCUSDT") == "BTC"
    assert _is_usdt_base("BTC-USDT") == "BTC"
    assert _is_usdt_base("BTC_USDT") == "BTC"
    assert _is_usdt_base("ETHUSDC") == "ETH"
    assert _is_usdt_base("USDT") is None     # base == suffix → None
    assert _is_usdt_base("BTC-USD") == "BTC"
