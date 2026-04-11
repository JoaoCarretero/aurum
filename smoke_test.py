#!/usr/bin/env python3
"""
AURUM Finance — Dashboard smoke test.

Walks every Tkinter screen in launcher.py without a display, catches runtime
exceptions that static analysis misses. Built after the _unbind collision bug
(App._unbind shadowed tkinter's Misc._unbind) shipped silently and broke every
crypto-futures tab — this file exists to prevent that class of regression.

Usage:
    python smoke_test.py          # run and print results; exit 1 on any fail
    python smoke_test.py --quiet  # only print failures

The test uses `App().withdraw()` + `update_idletasks()` to construct the full
Tkinter widget tree without showing any window, then programmatically navigates
every screen and tab. It does NOT hit the network — async workers are triggered
but not awaited.
"""
from __future__ import annotations

import os
import sys
import time
import traceback
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_launcher():
    spec = importlib.util.spec_from_file_location("launcher", ROOT / "launcher.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load launcher.py spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(quiet: bool = False) -> int:
    mod = load_launcher()

    app = mod.App()
    app.withdraw()

    failures: list[tuple[str, str, str]] = []
    passes: int = 0

    def call(label: str, fn, *args, **kw):
        nonlocal passes
        try:
            fn(*args, **kw)
            app.update_idletasks()
            passes += 1
            if not quiet:
                print(f"  OK    {label}")
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:150]}"
            failures.append((label, msg, traceback.format_exc()))
            print(f"  FAIL  {label}    {msg}")

    def section(name: str):
        if not quiet:
            print(f"\n[{name}]")

    # ── SPLASH + TOP-LEVEL SCREENS ──
    section("SPLASH + TOP-LEVEL")
    call("_splash",         app._splash)

    # ── BLOOMBERG 3D MAIN MENU ──
    section("BLOOMBERG MAIN MENU")
    call("_menu_main_bloomberg", app._menu_main_bloomberg)
    call("focus tile 1",         app._menu_tile_focus, 1)
    call("focus tile 2",         app._menu_tile_focus, 2)
    call("focus tile 3",         app._menu_tile_focus, 3)
    call("focus delta +1",       app._menu_tile_focus_delta, +1)
    call("expand tile 0",        app._menu_tile_expand, 0)
    call("sub focus +1",         app._menu_sub_focus_delta, +1)
    call("collapse",             app._menu_tile_collapse)
    call("expand tile 2",        app._menu_tile_expand, 2)
    call("collapse again",       app._menu_tile_collapse)
    call("live fetch sync",      app._menu_live_fetch_sync)
    call("live apply",           app._menu_live_apply)

    # ── LEGACY MAIN MENU (feature flag rollback) ──
    section("LEGACY FIBONACCI MENU")
    os.environ["AURUM_MENU_STYLE"] = "legacy"
    try:
        call("_menu(main) legacy", app._menu, "main")
    finally:
        os.environ.pop("AURUM_MENU_STYLE", None)

    call("_markets",        app._markets)
    call("_connections",    app._connections)
    call("_terminal",       app._terminal)
    call("_strategies",     app._strategies)
    call("_risk_menu",      app._risk_menu)
    call("_config",         app._config)
    call("_command_center", app._command_center)

    # ── TERMINAL SUB-SCREENS ──
    section("TERMINAL sub-screens")
    call("_data",  app._data)
    call("_procs", app._procs)

    # ── CONFIG EDITORS ──
    section("CONFIG editors")
    call("_cfg_keys", app._cfg_keys)
    call("_cfg_tg",   app._cfg_tg)
    call("_cfg_vps",  app._cfg_vps)

    # ── STRATEGY BRIEFINGS (every engine) ──
    section("STRATEGY BRIEFINGS")
    for parent_key, items in mod.SUB_MENUS.items():
        for name, script, desc in items:
            call(f"_brief({name}/{parent_key})",
                 app._brief, name, script, desc, parent_key)

    # ── ENGINE CONFIG SCREENS ──
    section("CONFIG_BACKTEST screens")
    for name, script, desc in mod.SUB_MENUS.get("backtest", []):
        call(f"_config_backtest({name})",
             app._config_backtest, name, script, desc, "backtest")

    section("CONFIG_LIVE screens")
    for name, script, desc in mod.SUB_MENUS.get("live", []):
        call(f"_config_live({name})",
             app._config_live, name, script, desc, "live")

    # ── CRYPTO FUTURES DASHBOARD + ALL 6 TABS ──
    section("CRYPTO DASHBOARD")
    call("_crypto_dashboard", app._crypto_dashboard)
    for tab in ("home", "market", "portfolio", "trades", "backtest", "cockpit"):
        call(f"  tab:{tab}", app._dash_render_tab, tab)
        call(f"  force_refresh({tab})", app._dash_force_refresh)

    # ── PORTFOLIO account switching ──
    section("PORTFOLIO account switch")
    for acc in ("paper", "testnet", "demo", "live"):
        app._dash_portfolio_account = acc
        call(f"  acc:{acc}", app._dash_render_tab, "portfolio")

    # ── BACKTEST detail select (click real runs) ──
    section("BACKTEST detail select")
    idx_path = ROOT / "data" / "index.json"
    if idx_path.exists():
        import json
        try:
            runs = json.loads(idx_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            runs = []
        app._dash_render_tab("backtest")
        for run in runs[:3]:
            rid = run.get("run_id")
            if rid:
                call(f"_dash_backtest_select({rid})",
                     app._dash_backtest_select, rid)

    # ── PAPER EDIT dialog ──
    section("PAPER EDIT dialog")
    app._dash_portfolio_account = "paper"
    app._dash_render_tab("portfolio")
    try:
        app._dash_paper_edit_dialog()
        app.update_idletasks()
        # Destroy the Toplevel so it doesn't linger
        for w in app.winfo_children():
            if isinstance(w, mod.tk.Toplevel):
                w.destroy()
        app.update_idletasks()
        passes += 1
        if not quiet:
            print("  OK    paper edit dialog")
    except Exception as e:
        msg = f"{type(e).__name__}: {str(e)[:150]}"
        failures.append(("paper dialog", msg, traceback.format_exc()))
        print(f"  FAIL  paper dialog    {msg}")

    # ── STRESS: 20x rapid tab cycling ──
    section("STRESS: rapid tab switching")
    stress_fails = 0
    for i in range(20):
        for tab in ("home", "market", "backtest", "cockpit"):
            try:
                app._dash_render_tab(tab)
                app.update_idletasks()
            except Exception as e:
                stress_fails += 1
                failures.append((f"stress[{i}] {tab}", str(e), traceback.format_exc()))
                break
    if not quiet:
        print(f"  stress cycles: {20 - stress_fails}/20 OK ({20*4 - stress_fails} tab switches)")
    passes += (20 * 4) - stress_fails

    # ── HOME async fetch (triggers worker thread) ──
    section("HOME fetch async")
    app._dash_render_tab("home")
    call("_dash_home_fetch_async", app._dash_home_fetch_async)
    time.sleep(0.3)  # let worker settle
    app.update_idletasks()
    call("_dash_home_render", app._dash_home_render)

    # ── MENU routing ──
    section("menu routing")
    for key in ("main", "markets", "connections", "terminal", "strategies",
                "risk", "command", "settings", "data"):
        call(f"  menu:{key}", app._menu, key)

    # ── DATA CENTER sub-screens ──
    section("DATA CENTER")
    call("_data_center",    app._data_center)
    call("_data_backtests", app._data_backtests)
    # Prove DELETE is reachable from the standalone screen: select a real
    # run and verify the detail panel was populated (it contains the DELETE
    # binding). If the select call crashes or bt_detail stays None, the
    # standalone screen is broken.
    idx_path2 = ROOT / "data" / "index.json"
    if idx_path2.exists():
        import json as _json
        try:
            runs2 = _json.loads(idx_path2.read_text(encoding="utf-8"))
        except (_json.JSONDecodeError, OSError):
            runs2 = []
        if runs2:
            rid = runs2[0].get("run_id")
            if rid:
                call(f"_data_backtests>select({rid})",
                     app._dash_backtest_select, rid)
                # Verify bt_detail was populated (detail panel frame exists
                # and has children — the DELETE button lives in there).
                body = app._dash_widgets.get(("bt_detail",))
                has_children = bool(body and body.winfo_children())
                call("  detail panel populated",
                     lambda: (_ for _ in ()).throw(AssertionError(
                         "bt_detail empty"))) if not has_children else call(
                     "  detail panel populated", lambda: None)
    call("_data_engines", app._data_engines)
    if getattr(app, "_eng_after_id", None):
        try: app.after_cancel(app._eng_after_id)
        except Exception: pass
    if getattr(app, "_eng_tail_stop", None):
        app._eng_tail_stop.set()

    # ── ROUND-TRIP BACK TO SPLASH ──
    section("roundtrip splash")
    call("_splash (roundtrip)", app._splash)

    # ── CLEANUP ──
    app._dash_alive = False
    try:
        app.destroy()
    except Exception:
        pass

    # ── REPORT ──
    print()
    print("=" * 60)
    total = passes + len(failures)
    print(f"  {passes}/{total} passed  ({len(failures)} failures)")
    print("=" * 60)

    if failures:
        print("\nFAILURES:")
        for label, msg, tb in failures:
            print(f"\n--- {label} ---")
            print(f"  {msg}")
            if not quiet:
                print(tb)
        return 1
    return 0


if __name__ == "__main__":
    quiet = "--quiet" in sys.argv or "-q" in sys.argv
    sys.exit(run(quiet=quiet))
