"""core/arb_tab_matrix.py
AURUM Finance — type-matrix helpers for the Arbitrage Hub v2.

Pure module: no Tk, no I/O. Provides venue classification, tab predicate
dispatching, sort comparator, and label compaction logic consumed by
launcher_support.screens.arbitrage_hub.

CEX venue allowlist is hardcoded and derived from
core.arb_scoring._DEFAULT_VENUE_RELIABILITY. Anything not on the list
is treated as DEX.
"""
from __future__ import annotations


# Centralized CEX allowlist. Everything else (hyperliquid, dydx, paradex,
# vertex, etc.) falls through to DEX. Keep lowercase.
CEX_VENUES: frozenset[str] = frozenset({
    "binance",
    "bybit",
    "okx",
    "kucoin",
    "gate",
    "bitget",
    "bingx",
    "mexc",
    "htx",
    "coinbase",
})


def is_cex(venue: str | None) -> bool:
    """True if ``venue`` is a known centralized exchange.

    Case-insensitive. None / empty / unknown → False (treated as DEX).
    """
    if not venue:
        return False
    return str(venue).lower() in CEX_VENUES


# ─── Pair introspection helpers ─────────────────────────────────────

# _type tag written by _arb_paint_opps when merging sources:
#   CC/DD/CD → both legs perp (funding diff)
#   BS       → perp ↔ spot (basis trade)
#   SP       → both legs spot (spot arb)
_TYPE_TO_KINDS: dict[str, tuple[str, str]] = {
    "CC": ("perp", "perp"),
    "DD": ("perp", "perp"),
    "CD": ("perp", "perp"),
    "BS": ("perp", "spot"),
    "SP": ("spot", "spot"),
}


def pair_kinds(pair: dict) -> tuple[str | None, str | None]:
    """Return (kind_a, kind_b) for a pair record, or (None, None) if unknown."""
    t = pair.get("_type")
    if t in _TYPE_TO_KINDS:
        return _TYPE_TO_KINDS[t]
    return (None, None)


def pair_venues(pair: dict) -> tuple[str, str]:
    """Return (venue_a, venue_b) normalized from whichever fields exist.

    Preference order: short/long_venue → venue_perp/venue_spot → venue_a/venue_b.
    Missing fields return empty strings.
    """
    a = (pair.get("short_venue")
         or pair.get("venue_perp")
         or pair.get("venue_a")
         or "")
    b = (pair.get("long_venue")
         or pair.get("venue_spot")
         or pair.get("venue_b")
         or "")
    return (str(a), str(b))


# ─── Tab predicate dispatch ─────────────────────────────────────────

# Known opps tab ids emitted by the hub UI.
_TYPE_TAB_IDS: frozenset[str] = frozenset({
    "cex-cex", "dex-dex", "cex-dex",
    "perp-perp", "spot-spot", "basis",
})


def matches_type(pair: dict, tab_id: str) -> bool:
    """True if ``pair`` belongs in the given tab.

    Meta tabs ("positions", "history") always return False — they read
    from the engine, not from the scanner's opp stream.
    """
    if tab_id not in _TYPE_TAB_IDS:
        return False

    venue_a, venue_b = pair_venues(pair)
    kind_a, kind_b = pair_kinds(pair)

    if tab_id == "cex-cex":
        return is_cex(venue_a) and is_cex(venue_b)
    if tab_id == "dex-dex":
        return (not is_cex(venue_a)) and (not is_cex(venue_b)) \
               and bool(venue_a) and bool(venue_b)
    if tab_id == "cex-dex":
        return is_cex(venue_a) != is_cex(venue_b)
    if tab_id == "perp-perp":
        return kind_a == "perp" and kind_b == "perp"
    if tab_id == "spot-spot":
        return kind_a == "spot" and kind_b == "spot"
    if tab_id == "basis":
        # Basis opps are already same-symbol-two-instruments by
        # construction (one perp leg + one spot leg). Kind asymmetry
        # is the only meaningful signal.
        return (kind_a is not None and kind_b is not None
                and kind_a != kind_b)

    return False
