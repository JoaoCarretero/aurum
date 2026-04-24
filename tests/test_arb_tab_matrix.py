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
