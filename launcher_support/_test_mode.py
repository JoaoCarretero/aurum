"""Shared helper for detecting AURUM_TEST_MODE.

Used by both launcher.py (for the main app) and
launcher_support/screens/arbitrage_hub.py (for the arb hub scanner,
which short-circuits network calls under tests). Extracted to kill the
duplicate definitions that surfaced during the v2 density work.
"""
from __future__ import annotations

import os


def test_mode_enabled() -> bool:
    """True if AURUM_TEST_MODE env var is set to a truthy value."""
    return os.getenv("AURUM_TEST_MODE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }
