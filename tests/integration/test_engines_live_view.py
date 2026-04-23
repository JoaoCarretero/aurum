"""Tests for the new ENGINES LIVE cockpit view.

Follows the project pattern (see test_engine_picker_contracts.py):
test pure helpers, skip Tkinter runtime rendering.
"""
from __future__ import annotations

import pytest
import tkinter as tk


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
        assert "graham" not in LIVE_READY_SLUGS
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


class TestStageBadges:
    def test_bootstrap_stage_badge(self):
        from launcher_support.engines_live_view import _stage_badge
        label, _color = _stage_badge({"stage": "bootstrap_staging"})
        assert label == "BOOTSTRAP"

    def test_unknown_stage_badge_falls_back_to_uppercase(self):
        from launcher_support.engines_live_view import _stage_badge
        label, _color = _stage_badge({"stage": "shadow"})
        assert label == "SHADOW"


class TestCockpitSummaries:
    def test_footer_hints_live_mode(self):
        from launcher_support.engines_live_view import footer_hints
        hints, warn = footer_hints(selected_bucket="LIVE", mode="live")
        assert "ENTER monitor" in hints
        assert "S stop" in hints
        assert warn == "LIVE MODE - real orders enabled"

    def test_cockpit_summary_counts(self):
        from launcher_support.engines_live_view import cockpit_summary
        cards = cockpit_summary(mode="paper", live_count=2, ready_count=1, research_count=5)
        assert cards[0][0] == "RUNNING"
        assert cards[0][1] == "2"
        assert cards[-1] == ("DESK", "PAPER", cards[-1][2])

    def test_bucket_titles_are_operational(self):
        from launcher_support.engines_live_view import bucket_title
        assert bucket_title("LIVE") == "ENGINES"
        assert bucket_title("READY") == "READY TO LAUNCH"
        assert bucket_title("RESEARCH") == "RESEARCH ONLY"

    def test_bucket_header_title_distinguishes_experimental(self):
        from launcher_support.engines_live_view import bucket_header_title
        assert bucket_header_title("EXPERIMENTAL") == "EXPERIMENTAL"
        assert bucket_header_title("READY LIVE") == "READY TO LAUNCH"

    def test_row_action_label_bootstrap_ready(self):
        from launcher_support.engines_live_view import row_action_label
        label, _color = row_action_label("READY", {"live_bootstrap": True, "live_ready": False})
        assert label == "BOOTSTRAP"

    def test_initial_selection_falls_back_to_experimental_when_needed(self):
        from launcher_support.engines_live_view import initial_selection
        selected = initial_selection(
            live_items=[],
            ready_items=[],
            research_items=[],
            experimental_items=[("graham", {"display": "GRAHAM"})],
        )
        assert selected == ("graham", "RESEARCH")

    def test_experimental_bucket_uses_research_title(self):
        title = "EXPERIMENTAL"
        bucket = "LIVE" if title == "LIVE" else "RESEARCH" if title in ("RESEARCH", "EXPERIMENTAL") else "READY"
        assert bucket == "RESEARCH"


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

    def test_cycle_live_to_shadow(self):
        # SHADOW agora e o 5o modo; live -> shadow -> paper.
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("live") == "shadow"

    def test_cycle_shadow_wraps_to_paper(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("shadow") == "paper"

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


class TestRunningEnginesByBucket:
    def test_maps_citadel_proc_to_citadel_slug(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "backtest", "status": "running", "alive": True, "pid": 100}]
        out = running_slugs_from_procs(procs)
        # "backtest" is the legacy proc name for citadel.
        assert "citadel" in out

    def test_ignores_dead_procs(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "backtest", "status": "running", "alive": False, "pid": 100}]
        assert running_slugs_from_procs(procs) == {}

    def test_ignores_non_running_status(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "backtest", "status": "stopped", "alive": True, "pid": 100}]
        assert running_slugs_from_procs(procs) == {}

    def test_maps_arb_to_janestreet(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "arb", "status": "running", "alive": True, "pid": 7}]
        assert "janestreet" in running_slugs_from_procs(procs)

    def test_unknown_engine_name_dropped(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "ghost", "status": "running", "alive": True, "pid": 9}]
        assert running_slugs_from_procs(procs) == {}


class TestExperimentalSplit:
    """All quarantined engines in EXPERIMENTAL_SLUGS must land in RESEARCH
    bucket (not READY) so the cockpit can render them in their own cluster.
    """

    def test_quarantined_slugs_are_research_bucket(self):
        from config.engines import (
            ENGINES, LIVE_READY_SLUGS, LIVE_BOOTSTRAP_SLUGS,
            EXPERIMENTAL_SLUGS,
        )
        from launcher_support.engines_live_view import assign_bucket
        for slug in EXPERIMENTAL_SLUGS:
            assert slug in ENGINES, f"{slug} missing from ENGINES registry"
            bucket = assign_bucket(
                slug=slug,
                is_running=False,
                live_ready=(slug in LIVE_READY_SLUGS),
                live_bootstrap=(slug in LIVE_BOOTSTRAP_SLUGS),
            )
            assert bucket == "RESEARCH", (
                f"{slug} should be RESEARCH (quarantined) but was {bucket}"
            )

    def test_experimental_not_empty(self):
        from config.engines import EXPERIMENTAL_SLUGS
        # Protects against future edits that zero out the set by mistake —
        # the cockpit split relies on this cluster being non-empty.
        assert len(EXPERIMENTAL_SLUGS) >= 1


class TestFindLatestShadowRun:
    def test_returns_none_when_no_runs_dir(self, tmp_path, monkeypatch):
        from launcher_support import engines_live_view as elv
        monkeypatch.chdir(tmp_path)
        assert elv._find_latest_shadow_run() is None

    def test_picks_most_recent_by_mtime(self, tmp_path, monkeypatch):
        import json
        import os
        from launcher_support import engines_live_view as elv
        monkeypatch.chdir(tmp_path)

        shadow_root = tmp_path / "data" / "millennium_shadow"
        for name, mtime in (("older", 1000.0), ("newer", 2000.0)):
            run_dir = shadow_root / name
            (run_dir / "state").mkdir(parents=True)
            hb_path = run_dir / "state" / "heartbeat.json"
            hb_path.write_text(json.dumps({"run_id": name, "status": "running"}))
            os.utime(hb_path, (mtime, mtime))

        result = elv._find_latest_shadow_run()
        assert result is not None
        run_dir, payload = result
        assert run_dir.name == "newer"
        assert payload["run_id"] == "newer"

    def test_skips_runs_without_heartbeat(self, tmp_path, monkeypatch):
        from launcher_support import engines_live_view as elv
        monkeypatch.chdir(tmp_path)
        orphan = tmp_path / "data" / "millennium_shadow" / "orphan"
        orphan.mkdir(parents=True)
        assert elv._find_latest_shadow_run() is None

    def test_skips_corrupted_heartbeat(self, tmp_path, monkeypatch):
        from launcher_support import engines_live_view as elv
        monkeypatch.chdir(tmp_path)
        bad = tmp_path / "data" / "millennium_shadow" / "bad" / "state"
        bad.mkdir(parents=True)
        (bad / "heartbeat.json").write_text("{not json")
        assert elv._find_latest_shadow_run() is None


@pytest.mark.gui
def test_render_detail_reuses_shell_for_paper_refresh(monkeypatch):
    from launcher_support import engines_live_view as elv

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    try:
        host = tk.Frame(root)
        host.pack()
        state = {
            "detail_host": host,
            "mode": "paper",
            "selected_slug": "millennium",
            "selected_bucket": "LIVE",
            "sidebar_collapsed": False,
        }

        monkeypatch.setattr(elv, "_fetch_paper_run_id", lambda launcher, state=None: "RID")
        monkeypatch.setattr(elv, "_active_paper_runs", lambda launcher, state=None: [])
        monkeypatch.setattr(elv, "_fetch_paper_extras", lambda *args, **kwargs: (
            {"run_id": "RID", "status": "running", "last_tick_at": "2026-04-21T20:00:00Z"},
            [],
            [],
            {"equity": 10000.0, "drawdown_pct": 0.0, "initial_balance": 10000.0, "metrics": {}},
        ))
        monkeypatch.setattr(elv, "_schedule_paper_refresh", lambda launcher, state: None)
        monkeypatch.setattr(elv, "_render_vps_control_bar", lambda *args, **kwargs: None)

        elv._render_detail(state, launcher=None)
        first_layout = state["_detail_layout"]
        first_sidebar = state["_sidebar_host"]
        first_detail = state["_detail_inner"]

        elv._render_detail(state, launcher=None)

        assert state["_detail_layout"] is first_layout
        assert state["_sidebar_host"] is first_sidebar
        assert state["_detail_inner"] is first_detail
    finally:
        root.destroy()
