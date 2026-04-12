"""Tests for Bloomberg 3D main menu redesign in launcher.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_launcher():
    spec = importlib.util.spec_from_file_location("launcher", ROOT / "launcher.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tile_colors_defined():
    mod = _load_launcher()
    assert mod.TILE_MARKETS == "#ff8c00"
    assert mod.TILE_EXECUTE == "#00c864"
    assert mod.TILE_RESEARCH == "#33aaff"
    assert mod.TILE_CONTROL == "#c864c8"


def test_main_groups_shape():
    mod = _load_launcher()
    groups = mod.MAIN_GROUPS
    assert len(groups) == 4, "must be exactly 4 tiles"

    labels = [g[0] for g in groups]
    assert labels == ["MARKETS", "EXECUTE", "RESEARCH", "CONTROL"]

    for label, key_num, color, children in groups:
        assert isinstance(label, str) and label.isupper()
        assert key_num in {"1", "2", "3", "4"}
        assert color.startswith("#") and len(color) == 7
        assert isinstance(children, list) and 1 <= len(children) <= 3
        for child_label, method_name in children:
            assert isinstance(child_label, str)
            assert method_name.startswith("_")


def test_main_groups_cover_all_legacy_destinations():
    """Every destination callable in MAIN_MENU must still be reachable via MAIN_GROUPS."""
    mod = _load_launcher()
    legacy_keys = {key for _, key, _ in mod.MAIN_MENU}
    reachable_methods = {
        method for _, _, _, children in mod.MAIN_GROUPS
        for _, method in children
    }
    required_methods = {
        "_markets", "_connections", "_terminal", "_data_center",
        "_strategies", "_arbitrage_hub", "_risk_menu",
        "_command_center", "_config", "_crypto_dashboard",
    }
    missing = required_methods - reachable_methods
    assert not missing, f"MAIN_GROUPS missing destinations: {missing}"


def test_app_has_menu_live_cache():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        assert hasattr(app, "_menu_live")
        assert isinstance(app._menu_live, dict)
        for key in ("markets", "execute", "research", "control"):
            assert key in app._menu_live
            assert isinstance(app._menu_live[key], dict)
        assert hasattr(app, "_start_t")
        assert isinstance(app._start_t, float)
    finally:
        app.destroy()


def test_fetch_markets_fallback_on_exception():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        result = app._fetch_tile_markets()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
        for v in result.values():
            assert isinstance(v, str)
    finally:
        app.destroy()


def test_fetch_execute_returns_dict():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        result = app._fetch_tile_execute()
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
    finally:
        app.destroy()


def test_fetch_research_returns_dict():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        result = app._fetch_tile_research()
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
    finally:
        app.destroy()


def test_fetch_control_uptime_format():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        result = app._fetch_tile_control()
        assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
        assert "h" in result["line2"] or "m" in result["line2"] or result["line2"] == "—"
    finally:
        app.destroy()


def test_menu_live_fetch_populates_cache():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_live_fetch_sync()
        for key in ("markets", "execute", "research", "control"):
            live = app._menu_live[key]
            assert isinstance(live, dict)
            assert set(live.keys()) == {"line1", "line2", "line3", "line4"}
    finally:
        app.destroy()


def test_menu_main_bloomberg_renders_without_exception():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app.update_idletasks()
        assert app._menu_canvas is not None
        items = app._menu_canvas.find_all()
        assert len(items) > 20, f"expected many canvas items, got {len(items)}"
    finally:
        app.destroy()


def test_focus_moves_with_arrow_right():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app.update_idletasks()
        assert app._menu_focused_tile == 0
        app._menu_tile_focus(1)
        assert app._menu_focused_tile == 1
        app._menu_tile_focus_delta(+1)
        assert app._menu_focused_tile == 2
    finally:
        app.destroy()


def test_focus_numeric_jump():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app._menu_tile_focus(3)
        assert app._menu_focused_tile == 3
    finally:
        app.destroy()


def test_expand_and_collapse_state():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        app._menu_tile_expand(0)
        assert app._menu_expanded_tile == 0
        assert app._menu_sub_focus == 0
        app._menu_tile_collapse()
        assert app._menu_expanded_tile is None
    finally:
        app.destroy()


def test_sub_select_dispatches_to_method(monkeypatch):
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        called = []
        monkeypatch.setattr(app, "_markets", lambda: called.append("markets"))
        app._menu_tile_expand(0)
        app._menu_sub_select(0, 0)
        assert called == ["markets"]
    finally:
        app.destroy()


def test_splash_creates_canvas():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._splash()
        app.update_idletasks()
        assert app._menu_canvas is not None
        items = app._menu_canvas.find_all()
        assert len(items) > 15, f"expected >15 items on splash, got {len(items)}"
    finally:
        app.destroy()


def test_splash_click_routes_to_main(monkeypatch):
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._splash()
        called = []
        monkeypatch.setattr(app, "_menu", lambda key: called.append(key))
        app._splash_on_click()
        assert called == ["main"]
    finally:
        app.destroy()


def test_splash_pulse_disarms_on_menu_switch():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._splash()
        assert app._splash_pulse_after_id is not None
        app._splash_canvas = None
        app._splash_pulse_tick()
        assert app._splash_pulse_after_id is None
    finally:
        app.destroy()


def test_live_refresh_schedule_registered():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_main_bloomberg()
        assert hasattr(app, "_menu_live_after_id")
        assert app._menu_live_after_id is not None
    finally:
        app.destroy()


def test_draw_cd_center_accepts_radius_override():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        import tkinter as tk
        canvas = tk.Canvas(app, width=200, height=200, bg="#0a0a0a")
        app._active_cd_center = (100, 100)
        app._draw_cd_center(canvas, r=36)
        canvas.update_idletasks()
        items = canvas.find_all()
        assert len(items) >= 5, f"expected CD primitives, got {len(items)}"
        canvas.destroy()
    finally:
        app.destroy()


def test_app_has_splash_pulse_state():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        # __init__ calls _splash() which arms the pulse and sets the canvas.
        assert hasattr(app, "_splash_cursor_on")
        assert isinstance(app._splash_cursor_on, bool)
        assert hasattr(app, "_splash_pulse_after_id")
        assert app._splash_pulse_after_id is not None
        assert hasattr(app, "_splash_canvas")
        assert app._splash_canvas is not None
    finally:
        app.destroy()


def test_draw_warning_stripe_creates_rect_and_text():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        import tkinter as tk
        canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
        app._draw_warning_stripe(canvas, y=0, height=20, text="TEST WARNING")
        canvas.update_idletasks()
        items = canvas.find_all()
        assert len(items) >= 2, f"expected >=2 items, got {len(items)}"
        canvas.destroy()
    finally:
        app.destroy()


def test_draw_stamp_creates_border_and_text():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        import tkinter as tk
        canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
        app._draw_stamp(canvas, cx=300, cy=100, w=100, h=50,
                        lines=["VAULT", "03"])
        canvas.update_idletasks()
        items = canvas.find_all()
        assert len(items) >= 3, f"expected >=3 items, got {len(items)}"
        canvas.destroy()
    finally:
        app.destroy()


def test_draw_status_block_creates_rows():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        import tkinter as tk
        canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
        rows = [
            ("SYSTEM STATUS", "NOMINAL", "#00c864"),
            ("KILL-SWITCH",   "ARMED [3/3]", "#c83232"),
        ]
        app._draw_status_block(canvas, x=220, y=320, rows=rows)
        canvas.update_idletasks()
        items = canvas.find_all()
        assert len(items) >= len(rows)
        canvas.destroy()
    finally:
        app.destroy()


def test_arbitrage_hub_renders_three_rows():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._arbitrage_hub()
        app.update_idletasks()
        assert hasattr(app, "_arb_hub_row_widgets")
        assert len(app._arb_hub_row_widgets) == 3
        for w in app._arb_hub_row_widgets:
            assert "frame" in w
            assert "bullet" in w
            assert "label" in w
            assert "meta" in w
            assert "sub" in w
    finally:
        app.destroy()
