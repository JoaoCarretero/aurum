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


class TestBucketAssignment:
    def test_live_takes_precedence_over_ready(self):
        from launcher_support.engines_live_view import assign_bucket
        # Engine is live_ready AND currently running → LIVE bucket.
        assert assign_bucket(slug="citadel", is_running=True, live_ready=True) == "LIVE"

    def test_ready_when_not_running_and_live_ready(self):
        from launcher_support.engines_live_view import assign_bucket
        assert assign_bucket(slug="citadel", is_running=False, live_ready=True) == "READY"

    def test_research_when_not_live_ready(self):
        from launcher_support.engines_live_view import assign_bucket
        assert assign_bucket(slug="renaissance", is_running=False, live_ready=False) == "RESEARCH"

    def test_research_engine_running_stays_research(self):
        # Edge case: a research engine spawned via backtest path is running.
        # It should NOT jump into LIVE bucket of the cockpit view — only
        # engines declared live_ready can occupy LIVE.
        from launcher_support.engines_live_view import assign_bucket
        assert assign_bucket(slug="renaissance", is_running=True, live_ready=False) == "RESEARCH"
