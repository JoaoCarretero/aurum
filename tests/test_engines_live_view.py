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


class TestModeCycle:
    def test_cycle_paper_to_demo(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("paper") == "demo"

    def test_cycle_demo_to_testnet(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("demo") == "testnet"

    def test_cycle_testnet_to_live(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("testnet") == "live"

    def test_cycle_live_wraps_to_paper(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("live") == "paper"

    def test_cycle_unknown_falls_back_to_paper(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("bogus") == "paper"


class TestModePersistence:
    def test_load_returns_paper_when_file_missing(self, tmp_path):
        from launcher_support.engines_live_view import load_mode
        assert load_mode(state_path=tmp_path / "ui_state.json") == "paper"

    def test_load_returns_saved_mode(self, tmp_path):
        from launcher_support.engines_live_view import load_mode, save_mode
        sp = tmp_path / "ui_state.json"
        save_mode("demo", state_path=sp)
        assert load_mode(state_path=sp) == "demo"

    def test_load_rejects_invalid_mode(self, tmp_path):
        import json
        from launcher_support.engines_live_view import load_mode
        sp = tmp_path / "ui_state.json"
        sp.write_text(json.dumps({"engines_live": {"mode": "bogus"}}))
        assert load_mode(state_path=sp) == "paper"

    def test_save_preserves_other_keys(self, tmp_path):
        import json
        from launcher_support.engines_live_view import save_mode
        sp = tmp_path / "ui_state.json"
        sp.write_text(json.dumps({"other_view": {"foo": 1}}))
        save_mode("testnet", state_path=sp)
        loaded = json.loads(sp.read_text())
        assert loaded["other_view"] == {"foo": 1}
        assert loaded["engines_live"]["mode"] == "testnet"


class TestLiveConfirmValidates:
    def test_exact_match_confirms(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="CITADEL") is True

    def test_case_sensitive(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="citadel") is False

    def test_trailing_space_rejected(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="CITADEL ") is False

    def test_empty_rejected(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="") is False


class TestFormatUptime:
    def test_minutes_only(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=42 * 60) == "42m"

    def test_hours_and_minutes(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=2 * 3600 + 14 * 60) == "2h14m"

    def test_zero_seconds(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=0) == "0m"

    def test_sub_minute_rounds_down(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=45) == "0m"

    def test_none_returns_em_dash(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=None) == "—"
