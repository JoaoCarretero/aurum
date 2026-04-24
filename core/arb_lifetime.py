"""core/arb_lifetime.py
AURUM Finance — lifetime / persistence tracking for arb opps.

Tracks when each (symbol, legs, kinds) tuple was first seen in the scanner
stream so the hub can render a LIFE column (older = more reliable, less
likely to be a transient blip).

Pure module: no Tk, no I/O, no imports from core.arb.* besides the pair
structure convention. In-memory only — state resets on launcher restart.
"""
from __future__ import annotations

import hashlib


def stable_key(pair: dict) -> str:
    """Hash a pair record to a stable identifier across scans.

    Key components: symbol + (venue_a, venue_b) + (_type). Venues are
    lowercased so case differences don't fork the key.
    """
    symbol = str(pair.get("symbol", "")).upper()
    va = str(
        pair.get("short_venue") or pair.get("venue_perp") or pair.get("venue_a") or ""
    ).lower()
    vb = str(
        pair.get("long_venue") or pair.get("venue_spot") or pair.get("venue_b") or ""
    ).lower()
    t = str(pair.get("_type", ""))
    payload = f"{symbol}|{va}|{vb}|{t}".encode()
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


def fmt_duration(seconds: float) -> str:
    """Format a duration as ``Nm`` (<60min) or ``NhMm`` (≥60min).

    Negative/zero → ``0m``. Truncates (does not round).
    """
    s = int(max(0, seconds))
    if s < 3600:
        return f"{s // 60}m"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h{m}m"


class LifetimeTracker:
    """First-seen timestamps for arb-pair keys.

    Use ``observe_pairs(pairs, now)`` each scan tick. Query with
    ``age(key, now)``. Periodically call ``cleanup(now, max_age)`` so
    disappeared pairs don't bloat memory.
    """

    def __init__(self) -> None:
        self._first_seen: dict[str, float] = {}

    def observe(self, key: str, now: float) -> None:
        """Record first-seen time. Idempotent: later observes do not reset."""
        if key not in self._first_seen:
            self._first_seen[key] = float(now)

    def observe_pairs(self, pairs, now: float) -> None:
        """Bulk observe from an iterable of pair records."""
        for p in pairs or []:
            self.observe(stable_key(p), now)

    def age(self, key: str, now: float) -> float | None:
        """Seconds since first-seen, or None if never observed."""
        first = self._first_seen.get(key)
        if first is None:
            return None
        return float(now) - first

    def cleanup(self, now: float, max_age: float) -> None:
        """Drop entries older than ``max_age`` seconds to cap memory."""
        cutoff = float(now) - float(max_age)
        stale = [k for k, t in self._first_seen.items() if t < cutoff]
        for k in stale:
            del self._first_seen[k]
