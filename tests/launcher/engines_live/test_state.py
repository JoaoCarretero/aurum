"""Unit tests for state.py — immutable snapshot + reducer."""
from __future__ import annotations


def test_empty_state_has_no_selection():
    from launcher_support.engines_live.state import StateSnapshot, empty_state

    s: StateSnapshot = empty_state()
    assert s.selected_engine is None
    assert s.selected_instance is None
    assert s.focus_pane == "strip"
    assert s.mode == "paper"
    assert s.follow_tail is False
    assert s.shelf_expanded is False


def test_select_engine_sets_selection_and_moves_focus_to_detail():
    from launcher_support.engines_live.state import empty_state, select_engine

    s = empty_state()
    s2 = select_engine(s, "citadel")
    assert s2.selected_engine == "citadel"
    assert s2.focus_pane == "detail_instances"
    # immutable
    assert s.selected_engine is None


def test_cycle_mode_wraps_around():
    from launcher_support.engines_live.state import empty_state, cycle_mode_state

    s = empty_state()
    assert s.mode == "paper"
    s = cycle_mode_state(s)
    assert s.mode == "shadow"
    s = cycle_mode_state(s)
    assert s.mode == "demo"
    s = cycle_mode_state(s)
    assert s.mode == "testnet"
    s = cycle_mode_state(s)
    assert s.mode == "live"
    s = cycle_mode_state(s)
    assert s.mode == "paper"


def test_toggle_shelf():
    from launcher_support.engines_live.state import empty_state, toggle_shelf

    s = empty_state()
    assert s.shelf_expanded is False
    s2 = toggle_shelf(s)
    assert s2.shelf_expanded is True
    s3 = toggle_shelf(s2)
    assert s3.shelf_expanded is False


def test_tab_focus_cycles():
    from launcher_support.engines_live.state import empty_state, select_engine, tab_focus

    s = empty_state()
    s = select_engine(s, "citadel")
    assert s.focus_pane == "detail_instances"
    s = tab_focus(s)
    assert s.focus_pane == "detail_log"
    s = tab_focus(s)
    assert s.focus_pane == "strip"
    s = tab_focus(s)
    assert s.focus_pane == "detail_instances"


def test_select_instance_updates_state():
    from launcher_support.engines_live.state import empty_state, select_engine, select_instance

    s = empty_state()
    s = select_engine(s, "citadel")
    s = select_instance(s, "rid-1")
    assert s.selected_instance == "rid-1"


def test_toggle_follow_flips_follow_tail():
    from launcher_support.engines_live.state import empty_state, toggle_follow

    s = empty_state()
    assert s.follow_tail is False
    s2 = toggle_follow(s)
    assert s2.follow_tail is True
    s3 = toggle_follow(s2)
    assert s3.follow_tail is False
    # immutable
    assert s.follow_tail is False


def test_reset_selection_clears_everything():
    from launcher_support.engines_live.state import (
        empty_state,
        reset_selection,
        select_engine,
        select_instance,
        toggle_follow,
    )

    s = empty_state()
    s = select_engine(s, "citadel")
    s = select_instance(s, "rid-1")
    s = toggle_follow(s)
    assert s.selected_engine == "citadel"
    assert s.selected_instance == "rid-1"
    assert s.focus_pane == "detail_instances"
    assert s.follow_tail is True

    s2 = reset_selection(s)
    assert s2.selected_engine is None
    assert s2.selected_instance is None
    assert s2.focus_pane == "strip"
    assert s2.follow_tail is False
    # immutable — original snapshot unchanged
    assert s.selected_engine == "citadel"
