"""Unit tests for core/arb/tab_matrix.py — venue/predicate/sort helpers.
TDD: tests written before implementation.
"""
import pytest

from core.arb.tab_matrix import CEX_VENUES, is_cex


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

from core.arb.tab_matrix import matches_type, pair_kinds, pair_venues


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


# ─── opps_sort_key ──────────────────────────────────────────────────

from types import SimpleNamespace

from core.arb.tab_matrix import compact_labels, opps_sort_key


def _sr(grade="GO", bkevn=10.0, profit=5.0, score=80.0):
    return SimpleNamespace(
        grade=grade, viab=grade, breakeven_h=bkevn,
        profit_usd_per_1k_24h=profit, score=score,
    )


def test_sort_go_before_wait_before_skip():
    opps = [
        ({"id": 1}, _sr(grade="SKIP")),
        ({"id": 2}, _sr(grade="GO")),
        ({"id": 3}, _sr(grade="MAYBE")),
    ]
    opps.sort(key=opps_sort_key)
    assert [o["id"] for o, _ in opps] == [2, 3, 1]


def test_sort_bkevn_ascending_within_grade():
    opps = [
        ({"id": 1}, _sr(grade="GO", bkevn=50.0)),
        ({"id": 2}, _sr(grade="GO", bkevn=5.0)),
        ({"id": 3}, _sr(grade="GO", bkevn=20.0)),
    ]
    opps.sort(key=opps_sort_key)
    assert [o["id"] for o, _ in opps] == [2, 3, 1]


def test_sort_profit_descending_as_tiebreaker():
    opps = [
        ({"id": 1}, _sr(grade="GO", bkevn=10.0, profit=1.0)),
        ({"id": 2}, _sr(grade="GO", bkevn=10.0, profit=7.0)),
        ({"id": 3}, _sr(grade="GO", bkevn=10.0, profit=3.0)),
    ]
    opps.sort(key=opps_sort_key)
    assert [o["id"] for o, _ in opps] == [2, 3, 1]


def test_sort_handles_none_bkevn_and_profit():
    opps = [
        ({"id": 1}, _sr(grade="GO", bkevn=None, profit=None)),
        ({"id": 2}, _sr(grade="GO", bkevn=5.0, profit=2.0)),
    ]
    opps.sort(key=opps_sort_key)
    # id 2 beats id 1: has bkevn
    assert opps[0][0]["id"] == 2


# ─── compact_labels ────────────────────────────────────────────────

_FULL_LABELS = [
    ("1", "cex-cex",   "1 CEX-CEX",   "#ffd700"),
    ("2", "dex-dex",   "1 DEX-DEX",   "#00eaff"),
    ("3", "cex-dex",   "1 CEX-DEX",   "#c084fc"),
    ("4", "perp-perp", "4 PERP-PERP", "#32bcad"),
    ("5", "spot-spot", "5 SPOT-SPOT", "#ff00a0"),
    ("6", "basis",     "6 BASIS",     "#00ff80"),
    ("7", "positions", "7 POS",       "#888888"),
    ("8", "history",   "8 HIST",      "#666666"),
]


def test_compact_labels_level_0_full():
    # Level 0 = full, with counters
    counts = {tid: 5 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=0)
    assert out[0][2] == "1 CEX-CEX (5)"
    assert out[6][2] == "7 POS (5)"


def test_compact_labels_level_1_drops_counters():
    counts = {tid: 5 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=1)
    assert out[0][2] == "1 CEX-CEX"
    assert "(" not in out[0][2]


def test_compact_labels_level_2_slash():
    counts = {tid: 0 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=2)
    assert out[0][2] == "1 CEX/CEX"
    assert out[3][2] == "4 PERP/PERP"


def test_compact_labels_level_3_abbrev():
    counts = {tid: 0 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=3)
    assert out[0][2] == "1 CC"
    assert out[5][2] == "6 BAS"
    assert out[6][2] == "7 POS"
