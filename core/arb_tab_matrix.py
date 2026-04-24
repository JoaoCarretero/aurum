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
