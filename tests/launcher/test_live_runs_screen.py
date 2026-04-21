"""Unit tests for LiveRunsScreen."""
from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from launcher_support.screens.live_runs import LiveRunsScreen


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
        {"run_id": "r1", "engine": "millennium", "mode": "paper",
         "started_at": "2026-04-20T12:00:00+00:00",
         "ended_at": None, "status": "running",
         "tick_count": 20, "novel_count": 3, "open_count": 0,
         "equity": 10123.45, "last_tick_at": "2026-04-20T12:05:00+00:00",
         "host": "localhost", "label": None,
         "run_dir": "data/millennium_paper/2026-04-20_1200", "notes": None},
        {"run_id": "r2", "engine": "millennium", "mode": "shadow",
         "started_at": "2026-04-19T00:00:00+00:00",
         "ended_at": None, "status": "running",
         "tick_count": 106, "novel_count": 664, "open_count": 0,
         "equity": 10000.0, "last_tick_at": "2026-04-20T21:45:00+00:00",
         "host": "vps", "label": None,
         "run_dir": "data/millennium_shadow/2026-04-19_0000", "notes": None},
    ]


@pytest.mark.gui
def test_screen_builds(gui_root, fake_app, fake_runs, monkeypatch):
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
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
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        fake_list,
    )
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.get_live_run",
        lambda rid: next(r for r in fake_runs if r["run_id"] == rid),
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
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        fake_list,
    )
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.get_live_run",
        lambda rid: next(r for r in fake_runs if r["run_id"] == rid),
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
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        fake_list,
    )
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.get_live_run",
        lambda rid: next(r for r in fake_runs if r["run_id"] == rid),
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    s.on_enter()  # within TTL
    s.on_enter()
    assert len(calls) == 1
