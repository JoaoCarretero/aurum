"""Tests for the new ENGINES LIVE cockpit view.

Follows the project pattern (see test_engine_picker_contracts.py):
test pure helpers, skip Tkinter runtime rendering.
"""
from __future__ import annotations

import pytest


class TestLiveReadySlugs:
    def test_contains_citadel_janestreet_live(self):
        from config.engines import LIVE_READY_SLUGS
        assert "citadel" in LIVE_READY_SLUGS
        assert "janestreet" in LIVE_READY_SLUGS
        assert "live" in LIVE_READY_SLUGS

    def test_excludes_research_engines(self):
        from config.engines import LIVE_READY_SLUGS
        # These have backtest entrypoints but not live-validated runners.
        assert "renaissance" not in LIVE_READY_SLUGS
        assert "jump" not in LIVE_READY_SLUGS
        assert "deshaw" not in LIVE_READY_SLUGS
        assert "kepos" not in LIVE_READY_SLUGS
        assert "phi" not in LIVE_READY_SLUGS

    def test_live_ready_flag_on_each_engine(self):
        from config.engines import ENGINES
        for slug, meta in ENGINES.items():
            assert "live_ready" in meta, f"{slug} missing live_ready flag"
            assert isinstance(meta["live_ready"], bool)


class TestModeColorAliases:
    def test_mode_aliases_map_to_existing_tokens(self):
        from core.ui_palette import (
            MODE_PAPER, MODE_DEMO, MODE_TESTNET, MODE_LIVE,
            CYAN, GREEN, AMBER, RED,
        )
        assert MODE_PAPER == CYAN
        assert MODE_DEMO == GREEN
        assert MODE_TESTNET == AMBER
        assert MODE_LIVE == RED
