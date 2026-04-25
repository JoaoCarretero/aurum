"""Unit tests for LiveRunsScreen."""
from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from launcher_support.screens.live_runs import LiveRunsScreen
from core.ops.run_catalog import RunSummary


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def fake_app():
    app = MagicMock()
    return app


@pytest.fixture
def fake_runs():
    return [
        RunSummary(
            run_id="r1", engine="MILLENNIUM", mode="paper",
            started_at="2026-04-20T12:00:00+00:00",
            stopped_at=None, last_tick_at="2026-04-20T12:05:00+00:00",
            status="running",
            ticks_ok=20, ticks_fail=None, novel=3,
            equity=10123.45, initial_balance=None, roi_pct=None,
            trades_closed=None, source="db", run_dir=None, heartbeat=None,
            host="localhost", label=None, open_count=0, notes=None,
        ),
        RunSummary(
            run_id="r2", engine="MILLENNIUM", mode="shadow",
            started_at="2026-04-19T00:00:00+00:00",
            stopped_at=None, last_tick_at="2026-04-20T21:45:00+00:00",
            status="running",
            ticks_ok=106, ticks_fail=None, novel=664,
            equity=10000.0, initial_balance=None, roi_pct=None,
            trades_closed=None, source="db", run_dir=None, heartbeat=None,
            host="vps", label=None, open_count=0, notes=None,
        ),
    ]


@pytest.mark.gui
def test_screen_builds(gui_root, fake_app, fake_runs, monkeypatch):
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.run_catalog.list_runs_catalog",
        lambda **kw: fake_runs,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    assert s._list_frame is not None
    assert s._detail_frame is not None


@pytest.mark.gui
def test_on_enter_renders_all_mode_by_default(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    calls = []
    def fake_list(**kw):
        calls.append(kw)
        return fake_runs
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.run_catalog.list_runs_catalog",
        fake_list,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    assert calls[0].get("mode") is None  # ALL default


@pytest.mark.gui
def test_set_filter_rerenders_with_mode(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    calls = []
    def fake_list(**kw):
        calls.append(kw)
        return fake_runs
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.run_catalog.list_runs_catalog",
        fake_list,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    s.set_filter("paper")
    assert calls[-1].get("mode") == "paper"


@pytest.mark.gui
def test_ttl_cache_avoids_repeat_query(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    calls = []
    def fake_list(**kw):
        calls.append(kw)
        return fake_runs
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.run_catalog.list_runs_catalog",
        fake_list,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    s.on_enter()  # within TTL
    s.on_enter()
    assert len(calls) == 1


@pytest.mark.gui
def test_detail_panel_renders_sections(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.run_catalog.list_runs_catalog",
        lambda **kw: fake_runs,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    # Detail for first run (auto-select)
    texts = []
    def collect(w):
        if isinstance(w, tk.Label):
            texts.append(w.cget("text"))
        for c in w.winfo_children():
            collect(c)
    collect(s._detail_frame)
    blob = " ".join(texts)
    assert "IDENTITY" in blob
    assert "TIMELINE" in blob
    assert "PERFORMANCE" in blob
    assert "ACTIVITY" in blob


@pytest.mark.gui
def test_render_clears_selection_when_selected_run_disappears(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    """When the selected run is no longer in the catalog (e.g., archived),
    rendering must clear `_selected_run_id` and auto-select the newest
    remaining run instead of leaving a dangling 'run not found' detail."""
    state = {"runs": fake_runs}
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.run_catalog.list_runs_catalog",
        lambda **kw: state["runs"],
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    assert s._selected_run_id == "r1"  # auto-selected newest

    # Simulate r1 being archived: catalog now returns only r2
    state["runs"] = [fake_runs[1]]
    s._list_cache = (0.0, s._mode_filter, [])  # invalidate TTL cache
    s._render()

    assert s._selected_run_id == "r2", (
        "stale selection should be cleared and newest auto-selected"
    )


@pytest.mark.gui
def test_archive_action_calls_archiver(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.run_catalog.list_runs_catalog",
        lambda **kw: fake_runs,
    )
    calls = []
    monkeypatch.setattr(
        "launcher_support.screens.live_runs._archive_run",
        lambda rid: calls.append(rid) or True,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    s._archive_selected()
    assert calls == ["r1"]
