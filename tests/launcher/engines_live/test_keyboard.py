"""Unit tests for keyboard.py — pure key routing."""
from __future__ import annotations


def test_escape_on_strip_returns_exit_action():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, ExitView

    s = empty_state()
    action = route(s, "Escape")
    assert isinstance(action, ExitView)


def test_escape_on_detail_goes_back_to_strip():
    from launcher_support.engines_live.state import empty_state, select_engine
    from launcher_support.engines_live.keyboard import route, BackToStrip

    s = empty_state()
    s = select_engine(s, "citadel")
    action = route(s, "Escape")
    assert isinstance(action, BackToStrip)


def test_tab_cycles_focus():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, CycleFocus

    s = empty_state()
    action = route(s, "Tab")
    assert isinstance(action, CycleFocus)


def test_m_cycles_mode():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, CycleMode

    s = empty_state()
    action = route(s, "m")
    assert isinstance(action, CycleMode)


def test_enter_on_strip_opens_detail():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, OpenDetail

    s = empty_state()
    action = route(s, "Return")
    assert isinstance(action, OpenDetail)


def test_s_on_detail_instances_stops_selected_instance():
    from launcher_support.engines_live.state import empty_state, select_engine, select_instance
    from launcher_support.engines_live.keyboard import route, StopInstance

    s = empty_state()
    s = select_engine(s, "citadel")
    s = select_instance(s, "rid-1")
    action = route(s, "s")
    assert isinstance(action, StopInstance)
    assert action.run_id == "rid-1"


def test_a_on_detail_stops_all_instances_of_engine():
    from launcher_support.engines_live.state import empty_state, select_engine
    from launcher_support.engines_live.keyboard import route, StopAll

    s = empty_state()
    s = select_engine(s, "citadel")
    action = route(s, "a")
    assert isinstance(action, StopAll)
    assert action.engine == "citadel"


def test_plus_opens_new_instance_dialog():
    from launcher_support.engines_live.state import empty_state, select_engine
    from launcher_support.engines_live.keyboard import route, OpenNewInstanceDialog

    s = empty_state()
    s = select_engine(s, "citadel")
    action = route(s, "plus")
    assert isinstance(action, OpenNewInstanceDialog)
    assert action.engine == "citadel"


def test_unknown_key_returns_none():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route

    s = empty_state()
    assert route(s, "zzzz") is None
