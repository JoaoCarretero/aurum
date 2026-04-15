"""Tests for Bloomberg 3D main menu redesign in launcher.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _load_launcher():
    spec = importlib.util.spec_from_file_location("launcher", ROOT / "launcher.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def mod():
    """Load launcher.py once per session (module exec is not cheap)."""
    return _load_launcher()


@pytest.fixture(scope="session")
def _shared_app(mod):
    """Single Tk root shared across the session.

    Creating/destroying Tk roots repeatedly on Windows Python 3.14 exhausts
    the Tcl init pool (`Can't find a usable init.tcl`). One root, withdrawn,
    sidesteps the limit. Tests must not rely on a pristine widget tree
    between calls — they should call the method under test fresh.
    """
    app = mod.App()
    app.withdraw()
    yield app
    try:
        app.destroy()
    except Exception:
        pass


@pytest.fixture
def app(_shared_app):
    """Per-test alias for the shared app — keeps test bodies readable."""
    return _shared_app


# ── Constants / shape tests (no Tk needed) ─────────────────────

def test_tile_colors_defined(mod):
    assert mod.TILE_MARKETS == "#6EB2E8"
    assert mod.TILE_EXECUTE == "#6ADB8A"
    assert mod.TILE_RESEARCH == "#E6C86A"
    assert mod.TILE_CONTROL == "#D88EC8"


def test_main_groups_shape(mod):
    groups = mod.MAIN_GROUPS
    assert len(groups) == 4, "must be exactly 4 tiles"

    labels = [g[0] for g in groups]
    assert labels == ["MARKETS", "EXECUTE", "RESEARCH", "CONTROL"]

    for label, key_num, color, children in groups:
        assert isinstance(label, str) and label.isupper()
        assert key_num in {"1", "2", "3", "4"}
        assert color.startswith("#") and len(color) == 7
        assert isinstance(children, list) and 1 <= len(children) <= 8
        for child_label, method_name in children:
            assert isinstance(child_label, str)
            assert method_name.startswith("_")


def test_main_groups_cover_all_legacy_destinations(mod):
    """Every destination callable in MAIN_MENU must still be reachable via MAIN_GROUPS."""
    legacy_keys = {key for _, key, _ in mod.MAIN_MENU}
    reachable_methods = {
        method for _, _, _, children in mod.MAIN_GROUPS
        for _, method in children
    }
    required_methods = {
        # Markets — direct routes to each market dashboard
        "_market_crypto_futures",
        "_market_crypto_spot",
        "_market_forex",
        "_market_equities",
        "_market_commodities",
        "_market_indices",
        "_market_onchain",
        # Other tiles
        "_connections", "_terminal", "_data_center",
        "_strategies_backtest", "_strategies_live",
        "_arbitrage_hub", "_risk_menu",
        "_command_center", "_config",
    }
    missing = required_methods - reachable_methods
    assert not missing, f"MAIN_GROUPS missing destinations: {missing}"


# ── App / live-cache state ──────────────────────────────────────

def test_app_has_menu_live_cache(app):
    assert hasattr(app, "_menu_live")
    assert isinstance(app._menu_live, dict)
    for key in ("markets", "execute", "research", "control"):
        assert key in app._menu_live
        assert isinstance(app._menu_live[key], dict)
    assert hasattr(app, "_start_t")
    assert isinstance(app._start_t, float)


def test_fetch_markets_fallback_on_exception(app):
    result = app._fetch_tile_markets()
    assert isinstance(result, dict)
    assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
    for v in result.values():
        assert isinstance(v, str)


def test_fetch_execute_returns_dict(app):
    result = app._fetch_tile_execute()
    assert set(result.keys()) == {"line1", "line2", "line3", "line4"}


def test_fetch_research_returns_dict(mod):
    app = object.__new__(mod.App)
    result = app._fetch_tile_research()
    assert set(result.keys()) == {"line1", "line2", "line3", "line4"}


def test_fetch_control_uptime_format(app):
    result = app._fetch_tile_control()
    assert set(result.keys()) == {"line1", "line2", "line3", "line4"}
    assert "h" in result["line2"] or "m" in result["line2"] or result["line2"] == "—"


def test_menu_live_fetch_populates_cache(app):
    app._menu_live_fetch_sync()
    for key in ("markets", "execute", "research", "control"):
        live = app._menu_live[key]
        assert isinstance(live, dict)
        assert set(live.keys()) == {"line1", "line2", "line3", "line4"}


# ── Main menu canvas rendering ─────────────────────────────────

def test_menu_main_bloomberg_renders_without_exception(app):
    app._menu_main_bloomberg()
    app.update_idletasks()
    assert app._menu_canvas is not None
    items = app._menu_canvas.find_all()
    assert len(items) > 20, f"expected many canvas items, got {len(items)}"


def test_focus_moves_with_arrow_right(app):
    app._menu_main_bloomberg()
    app.update_idletasks()
    app._menu_tile_focus(0)
    assert app._menu_focused_tile == 0
    app._menu_tile_focus(1)
    assert app._menu_focused_tile == 1
    app._menu_tile_focus_delta(+1)
    assert app._menu_focused_tile == 2


def test_focus_numeric_jump(app):
    app._menu_main_bloomberg()
    app._menu_tile_focus(3)
    assert app._menu_focused_tile == 3


def test_expand_and_collapse_state(app):
    app._menu_main_bloomberg()
    app._menu_tile_expand(0)
    assert app._menu_expanded_tile == 0
    assert app._menu_sub_focus == 0
    app._menu_tile_collapse()
    assert app._menu_expanded_tile is None


def test_sub_select_dispatches_to_method(app, monkeypatch):
    """MARKETS tile (idx 0) sub 0 = CRYPTO FUTURES → _market_crypto_futures."""
    app._menu_main_bloomberg()
    called = []
    monkeypatch.setattr(
        app, "_market_crypto_futures",
        lambda: called.append("crypto_futures"),
    )
    app._menu_tile_expand(0)
    app._menu_sub_select(0, 0)
    assert called == ["crypto_futures"]


# ── Splash ──────────────────────────────────────────────────────

def test_splash_creates_canvas(app):
    app._splash()
    app.update_idletasks()
    assert app._menu_canvas is not None
    items = app._menu_canvas.find_all()
    assert len(items) > 15, f"expected >15 items on splash, got {len(items)}"


def test_splash_click_routes_to_main(app, monkeypatch):
    app._splash()
    called = []
    monkeypatch.setattr(app, "_macro_brain_menu", lambda: called.append("macro_brain"))
    app._splash_on_click()
    assert called == ["macro_brain"]


def test_splash_pulse_disarms_on_menu_switch(app):
    app._splash()
    assert app._splash_pulse_after_id is not None
    app._splash_canvas = None
    app._splash_pulse_tick()
    assert app._splash_pulse_after_id is None


def test_live_refresh_schedule_registered(app):
    app._menu_main_bloomberg()
    assert hasattr(app, "_menu_live_after_id")
    assert app._menu_live_after_id is not None


def test_draw_cd_center_accepts_radius_override(app):
    import tkinter as tk
    canvas = tk.Canvas(app, width=200, height=200, bg="#0a0a0a")
    app._active_cd_center = (100, 100)
    app._draw_cd_center(canvas, r=36)
    canvas.update_idletasks()
    items = canvas.find_all()
    assert len(items) >= 5, f"expected CD primitives, got {len(items)}"
    canvas.destroy()


def test_app_has_splash_pulse_state(app):
    # __init__ calls _splash() which arms the pulse and sets the canvas.
    assert hasattr(app, "_splash_cursor_on")
    assert isinstance(app._splash_cursor_on, bool)
    assert hasattr(app, "_splash_pulse_after_id")
    # Re-arm the pulse if a prior test cleared it.
    if app._splash_pulse_after_id is None:
        app._splash()
    assert app._splash_pulse_after_id is not None
    assert hasattr(app, "_splash_canvas")
    assert app._splash_canvas is not None


def test_draw_warning_stripe_creates_rect_and_text(app):
    import tkinter as tk
    canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
    app._draw_warning_stripe(canvas, y=0, height=20, text="TEST WARNING")
    canvas.update_idletasks()
    items = canvas.find_all()
    assert len(items) >= 2, f"expected >=2 items, got {len(items)}"
    canvas.destroy()


def test_draw_stamp_creates_border_and_text(app):
    import tkinter as tk
    canvas = tk.Canvas(app, width=920, height=640, bg="#0a0a0a")
    app._draw_stamp(canvas, cx=300, cy=100, w=100, h=50,
                    lines=["VAULT", "03"])
    canvas.update_idletasks()
    items = canvas.find_all()
    assert len(items) >= 3, f"expected >=3 items, got {len(items)}"
    canvas.destroy()


def test_draw_status_block_creates_rows(app):
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


# ── Arbitrage hub ───────────────────────────────────────────────

def test_arbitrage_hub_renders_five_rows(app):
    app._arbitrage_hub()
    app.update_idletasks()
    assert hasattr(app, "_arb_hub_row_widgets")
    assert len(app._arb_hub_row_widgets) == 5
    for w in app._arb_hub_row_widgets:
        assert "frame" in w
        assert "bullet" in w
        assert "label" in w
        assert "meta" in w
        assert "sub" in w


def test_arbitrage_hub_pick_dispatches_to_alchemy(app, monkeypatch):
    app._arbitrage_hub()
    called = []
    monkeypatch.setattr(app, "_alchemy_enter",
                        lambda: called.append("alchemy"))
    app._arb_hub_pick(0)
    assert called == ["alchemy"]


def test_arbitrage_hub_telem_update_populates_sub_lines(app):
    app._arbitrage_hub()

    class FakeTop:
        symbol = "BTC"
        apr = 42.3
        venue = "binance"
    stats = {"dex_online": 3, "cex_online": 5, "total": 1042}
    top = FakeTop()
    arb_dd = [{"symbol": "ETH", "net_apr": 18.7, "short_venue": "dydx", "long_venue": "hyperliquid"}]
    arb_cd = [{"symbol": "SOL", "net_apr": 95.2, "short_venue": "bybit", "long_venue": "paradex"}]
    app._arb_hub_telem_update(stats, top, arb_dd, arb_cd)
    app.update_idletasks()

    rows = app._arb_hub_row_widgets
    assert "JANE ST" in rows[0]["meta"].cget("text")
    assert "3" in rows[1]["meta"].cget("text")
    assert "8" in rows[2]["meta"].cget("text")
    assert "18" in rows[1]["sub"].cget("text") or "19" in rows[1]["sub"].cget("text")
    assert "95" in rows[2]["sub"].cget("text") or "96" in rows[2]["sub"].cget("text")


def test_arbitrage_hub_hover_enter_moves_cursor(app, mod):
    app._arbitrage_hub()
    app.update_idletasks()
    app._arb_hub_idx = 0
    app._arb_hub_repaint()
    app._arb_hub_hover_enter(2)
    app.update_idletasks()
    assert app._arb_hub_idx == 2
    assert app._arb_hub_row_widgets[2]["label"].cget("fg") == mod.AMBER
    assert app._arb_hub_row_widgets[0]["label"].cget("fg") == mod.WHITE


def test_scanner_filter_bar_renders(app):
    try:
        app._funding_scanner_screen("dex-dex")
        app.update_idletasks()
        assert hasattr(app, "_arb_filters")
        assert "min_apr" in app._arb_filters
        assert hasattr(app, "_arb_filter_labels")
        assert len(app._arb_filter_labels) == 5
    finally:
        app._funding_alive = False


def test_arbitrage_hub_semaphore_colors_bullets(app):
    app._arbitrage_hub()
    stats = {"dex_online": 3, "cex_online": 5, "total": 100}

    class FakeTop:
        symbol = "BTC"
        apr = 80.0
        venue = "binance"
    top = FakeTop()
    arb_dd = [{
        "symbol": "ETH", "net_apr": 85.0,
        "short_venue": "dydx", "short_venue_type": "DEX",
        "long_venue": "hyperliquid", "long_venue_type": "DEX",
        "short_apr": 50.0, "long_apr": -35.0,
        "short_rate": 0.0003, "long_rate": -0.0002,
        "short_interval_h": 8, "long_interval_h": 1,
        "mark_price": 3200.0,
        "volume_24h_short": 8_000_000, "volume_24h_long": 5_000_000,
        "open_interest_short": 3_000_000, "open_interest_long": 2_000_000,
    }]
    arb_cd = []
    app._arb_hub_telem_update(stats, top, arb_dd, arb_cd)
    app.update_idletasks()

    rows = app._arb_hub_row_widgets
    bullet_fg = rows[1]["bullet"].cget("fg")
    assert bullet_fg == "#00ff41", f"expected green bullet, got {bullet_fg}"
