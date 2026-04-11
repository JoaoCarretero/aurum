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


def test_feature_flag_routes_to_bloomberg_by_default(monkeypatch):
    monkeypatch.delenv("AURUM_MENU_STYLE", raising=False)
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu("main")
        app.update_idletasks()
        assert app._menu_canvas is not None
    finally:
        app.destroy()


def test_feature_flag_legacy_disables_canvas(monkeypatch):
    monkeypatch.setenv("AURUM_MENU_STYLE", "legacy")
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._menu_canvas = None
        app._menu("main")
        app.update_idletasks()
        assert app._menu_canvas is None
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
