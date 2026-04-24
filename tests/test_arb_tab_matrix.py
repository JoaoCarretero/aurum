"""Unit tests for core/arb_tab_matrix.py — venue/predicate/sort helpers.
TDD: tests written before implementation.
"""
import pytest

from core.arb_tab_matrix import CEX_VENUES, is_cex


def test_is_cex_known_cex_venues():
    for v in ["binance", "bybit", "okx", "kucoin", "gate", "bitget", "bingx"]:
        assert is_cex(v) is True, f"{v!r} should be classified CEX"


def test_is_cex_dex_venues():
    for v in ["hyperliquid", "dydx", "paradex", "vertex"]:
        assert is_cex(v) is False, f"{v!r} should be classified DEX"


def test_is_cex_case_insensitive():
    assert is_cex("BINANCE") is True
    assert is_cex("HyperLiquid") is False


def test_is_cex_unknown_treated_as_dex():
    assert is_cex("random_venue") is False
    assert is_cex("") is False
    assert is_cex(None) is False


def test_cex_venues_is_frozenset():
    assert isinstance(CEX_VENUES, frozenset)
    assert "binance" in CEX_VENUES


# ─── pair_kinds / pair_venues helpers ────────────────────────────────

from core.arb_tab_matrix import matches_type, pair_kinds, pair_venues


def test_pair_kinds_from_type_cc():
    # _type "CC"/"DD"/"CD" all mean funding (perp-perp)
    assert pair_kinds({"_type": "CC"}) == ("perp", "perp")
    assert pair_kinds({"_type": "DD"}) == ("perp", "perp")
    assert pair_kinds({"_type": "CD"}) == ("perp", "perp")


def test_pair_kinds_from_type_basis():
    assert pair_kinds({"_type": "BS"}) == ("perp", "spot")


def test_pair_kinds_from_type_spot():
    assert pair_kinds({"_type": "SP"}) == ("spot", "spot")


def test_pair_kinds_missing_type_returns_unknown():
    assert pair_kinds({}) == (None, None)
    assert pair_kinds({"_type": "XX"}) == (None, None)


def test_pair_venues_short_long():
    p = {"short_venue": "binance", "long_venue": "bybit"}
    assert pair_venues(p) == ("binance", "bybit")


def test_pair_venues_basis():
    # basis has venue_perp/venue_spot
    p = {"venue_perp": "binance", "venue_spot": "coinbase"}
    assert pair_venues(p) == ("binance", "coinbase")


def test_pair_venues_spot():
    p = {"venue_a": "binance", "venue_b": "okx"}
    assert pair_venues(p) == ("binance", "okx")


def test_pair_venues_missing():
    assert pair_venues({}) == ("", "")


# ─── matches_type predicate dispatch ────────────────────────────────

def _p(**kw):
    base = {"_type": "CC", "short_venue": "binance", "long_venue": "bybit"}
    base.update(kw)
    return base


def test_matches_cex_cex():
    assert matches_type(_p(short_venue="binance", long_venue="bybit"), "cex-cex") is True
    assert matches_type(_p(short_venue="binance", long_venue="hyperliquid"), "cex-cex") is False


def test_matches_dex_dex():
    assert matches_type(
        _p(_type="DD", short_venue="hyperliquid", long_venue="dydx"),
        "dex-dex",
    ) is True
    assert matches_type(
        _p(short_venue="binance", long_venue="bybit"),
        "dex-dex",
    ) is False


def test_matches_cex_dex():
    assert matches_type(
        _p(_type="CD", short_venue="binance", long_venue="hyperliquid"),
        "cex-dex",
    ) is True
    # Both CEX → not CEX-DEX
    assert matches_type(
        _p(short_venue="binance", long_venue="bybit"),
        "cex-dex",
    ) is False


def test_matches_perp_perp():
    assert matches_type(_p(_type="CC"), "perp-perp") is True
    assert matches_type(_p(_type="BS"), "perp-perp") is False


def test_matches_spot_spot():
    assert matches_type(_p(_type="SP"), "spot-spot") is True
    assert matches_type(_p(_type="CC"), "spot-spot") is False


def test_matches_basis():
    assert matches_type(_p(_type="BS"), "basis") is True
    assert matches_type(_p(_type="CC"), "basis") is False


def test_matches_meta_tabs_always_false():
    # POSITIONS and HISTORY are meta tabs — predicate never matches an opp.
    assert matches_type(_p(), "positions") is False
    assert matches_type(_p(), "history") is False


def test_matches_unknown_kind_returns_false():
    # Missing _type → predicates that depend on kind return False
    assert matches_type({"short_venue": "binance", "long_venue": "bybit"},
                        "perp-perp") is False
