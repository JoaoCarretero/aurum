"""Regression tests for SplashScreen (pilot migration)."""
from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from launcher_support.screens.splash import SplashScreen


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
def fake_app(gui_root):
    app = MagicMock()
    app._SPLASH_DESIGN_W = 920
    app._SPLASH_DESIGN_H = 640
    app.h_stat = tk.Label(gui_root)
    app.h_path = tk.Label(gui_root)
    app.f_lbl = tk.Label(gui_root)
    app._draw_aurum_logo = MagicMock()
    app._draw_panel = MagicMock()
    app._draw_kv_rows = MagicMock()
    app._apply_canvas_scale = MagicMock(return_value=((0, 0, 920, 640), 1.0))
    app._load_json = MagicMock(return_value={
        "telegram": {"bot_token": "x"},
        "demo": {"api_key": "y"},
    })
    app._splash_on_click = MagicMock()
    app._bind_global_nav = MagicMock()
    return app


@pytest.fixture
def fake_conn():
    conn = MagicMock()
    conn.status_summary.return_value = {"market": "demo"}
    return conn


@pytest.mark.gui
def test_splash_builds_canvas(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    assert s.canvas is not None
    assert s.canvas.winfo_reqwidth() > 0


@pytest.mark.gui
def test_splash_draws_logo_panel_rows(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert fake_app._draw_panel.call_count >= 1
    panel_call = fake_app._draw_panel.call_args
    assert panel_call.args[1:5] == (140, 308, 780, 454)

    assert fake_app._draw_kv_rows.call_count >= 2
    left_call = fake_app._draw_kv_rows.call_args_list[0]
    right_call = fake_app._draw_kv_rows.call_args_list[1]
    assert left_call.args[1:3] == (176, 356)
    assert right_call.args[1:3] == (486, 356)
    assert left_call.kwargs["value_x"] == 288
    assert right_call.kwargs["value_x"] == 598
    assert fake_app._draw_aurum_logo.call_count >= 1


@pytest.mark.gui
def test_splash_intro_stays_above_session_panel(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert s._INTRO_Y + s._INTRO_BLOCK_GAP < s._SESSION_PANEL_Y1


@pytest.mark.gui
def test_splash_hero_stays_above_session_panel(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert s._INTRO_Y + s._INTRO_BLOCK_GAP < s._SESSION_PANEL_Y1


@pytest.mark.gui
def test_splash_pulse_timer_cancelled_on_exit(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert len(s._tracked_after_ids) >= 1
    s.on_exit()
    assert s._tracked_after_ids == []


@pytest.mark.gui
def test_splash_header_labels_set_on_enter(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert fake_app.h_stat.cget("text") == "READY"
    assert "ENTER proceed" in fake_app.f_lbl.cget("text")
