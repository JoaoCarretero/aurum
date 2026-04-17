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
    # Values live in core/ui_palette.py (HL2/CS 1.6 VGUI palette, 2026-04-15 refactor).
    assert mod.TILE_MARKETS  == "#7FA0B0"   # steel blue
    assert mod.TILE_EXECUTE  == "#7FA84A"   # HP green
    assert mod.TILE_RESEARCH == "#D08F36"   # HL2 orange
    assert mod.TILE_CONTROL  == "#C9B584"   # aged cream


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


def test_calc_centered_viewport(mod):
    viewport = mod.App._calc_centered_viewport(1440, 900, 920, 540)
    assert viewport == (260, 180, 1180, 720)


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


def test_menu_main_bloomberg_realigns_tile_slots_on_resize(app, monkeypatch):
    app._menu_main_bloomberg()
    monkeypatch.setattr(app._menu_canvas, "winfo_width", lambda: 1400)
    monkeypatch.setattr(app._menu_canvas, "winfo_height", lambda: 900)
    app._render_main_menu()
    assert app._active_tile_slots[0][1:] == (292, 316)
    assert app._active_cd_center == (700, 436)


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


def test_menu_live_routes_to_cockpit(app, monkeypatch):
    called = []
    monkeypatch.setattr(app, "_strategies_live", lambda: called.append("live"))
    app._menu("live")
    assert called == ["live"]


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


# ── Arbitrage hub (tabbed rewrite) ──────────────────────────────
# Hub is now a single page with 6 internal tabs (CEX-CEX / DEX-DEX /
# CEX-DEX / BASIS / SPOT / ENGINE). The old row-menu API (_arb_hub_pick,
# _arb_hub_row_widgets, hover cursor, semaphore bullets) was retired in
# the unification refactor.

def test_arbitrage_hub_renders_six_tabs(app):
    app._arbitrage_hub()
    app.update_idletasks()
    assert hasattr(app, "_arb_tab_labels")
    # Six tabs: cex-cex, dex-dex, cex-dex, basis, spot, engine
    expected = {"cex-cex", "dex-dex", "cex-dex", "basis", "spot", "engine"}
    assert set(app._arb_tab_labels.keys()) == expected


def test_arbitrage_hub_default_tab_is_cex_cex(app):
    app._arbitrage_hub()
    app.update_idletasks()
    assert app._arb_tab == "cex-cex"


def test_arbitrage_hub_tab_switch(app):
    app._arbitrage_hub(tab="dex-dex")
    app.update_idletasks()
    assert app._arb_tab == "dex-dex"
    # Re-entering with another tab swaps state
    app._arbitrage_hub(tab="engine")
    app.update_idletasks()
    assert app._arb_tab == "engine"


def test_arbitrage_hub_telem_update_populates_status_strip(app):
    app._arbitrage_hub()

    class FakeTop:
        symbol = "BTC"
        apr = 42.3
        venue = "binance"
        venue_type = "CEX"
    stats = {"dex_online": 3, "cex_online": 5, "total": 1042}
    top = FakeTop()
    opps = [top]
    arb_dd = [{"symbol": "ETH", "net_apr": 18.7,
               "short_venue": "dydx", "long_venue": "hyperliquid",
               "risk": "MED"}]
    arb_cd = [{"symbol": "SOL", "net_apr": 95.2,
               "short_venue": "bybit", "long_venue": "paradex",
               "risk": "HIGH"}]
    arb_cc = [{"symbol": "BTC", "net_apr": 12.4,
               "short_venue": "binance", "long_venue": "bybit",
               "risk": "LOW"}]
    app._arb_hub_telem_update(stats, top, opps, arb_cc, arb_dd, arb_cd,
                              basis=[], spot=[])
    app.update_idletasks()

    # Status strip shows live numbers
    assert "5" in app._arb_sum_cex.cget("text")
    assert "3" in app._arb_sum_dex.cget("text")
    assert "42" in app._arb_sum_best.cget("text")
    # Cache is populated for tab switches
    assert app._arb_cache["top"] is top
    assert app._arb_cache["arb_cc"] == arb_cc
    assert app._arb_cache["arb_dd"] == arb_dd


def test_arb_engine_tab_renders_without_snapshot(app):
    # Engine tab should render even when no JANE STREET run is active.
    app._arbitrage_hub(tab="engine")
    app.update_idletasks()
    # Tab registered as active
    assert app._arb_tab == "engine"


def test_funding_scanner_screen_redirects_to_hub_tab(app):
    """Legacy entry point should land on the right tab of the new desk."""
    app._funding_scanner_screen("dex-dex")
    app.update_idletasks()
    assert app._arb_tab == "dex-dex"

    app._funding_scanner_screen("cex-dex")
    app.update_idletasks()
    assert app._arb_tab == "cex-dex"


def test_arb_basis_screen_redirects_to_hub_tab(app):
    app._arb_basis_screen()
    app.update_idletasks()
    assert app._arb_tab == "basis"


def test_arb_spot_screen_redirects_to_hub_tab(app):
    app._arb_spot_screen()
    app.update_idletasks()
    assert app._arb_tab == "spot"


def test_alchemy_enter_redirects_to_engine_tab(app):
    app._alchemy_enter()
    app.update_idletasks()
    assert app._arb_tab == "engine"
