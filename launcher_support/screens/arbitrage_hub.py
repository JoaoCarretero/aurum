"""Arbitrage desk hub — 6-tab unified scanner screen.

Extracted from launcher.App._arbitrage_hub. render(app, tab="cex-cex")
builds the status strip (live dot + clock + CEX/DEX/top telemetry),
the grouped tab strip (PAIRS / RATES / EXECUTE buckets), the per-tab
content area, keyboard shortcuts, and kicks the scan/refresh loop.

Tab renderers live on App as _arb_render_* methods. The hub only
dispatches into them via the app parameter.
"""
from __future__ import annotations

from datetime import datetime
import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG, BG3, BORDER,
    DIM, DIM2, FONT,
    GREEN, WHITE,
)


def render(app, tab: str = "cex-cex"):
    """Mount the unified arbitrage desk.

    Layout: page shell → status strip → grouped tab strip (PAIRS /
    RATES / EXECUTE) → content frame → separator + first render.
    Keyboard: 1-6 switch tab, R refresh current, ESC back to main.
    The scanner is kicked off here via _arb_hub_scan_async and the
    refresh loop via _arb_schedule_refresh.
    """
    app._clr()
    app._clear_kb()
    app.history.append("main")
    app.h_path.configure(text=f"> ARBITRAGE > {tab.upper()}")
    app.h_stat.configure(text="DESK", fg=AMBER_D)
    app.f_lbl.configure(text="1-3 switch tab  |  R refresh  |  ESC back")
    app._kb("<Escape>", lambda: app._menu("main"))
    app._bind_global_nav()

    # Skip the big _ui_page_shell title (redundant with breadcrumb) and
    # claim the vertical real estate for the actual data. The breadcrumb
    # at the top of the launcher window already shows "> ARBITRAGE > TAB".
    outer = tk.Frame(app.main, bg=BG)
    outer.pack(fill="both", expand=True, padx=16, pady=(4, 4))
    tk.Frame(outer, bg=AMBER, height=2).pack(fill="x", pady=(0, 2))

    # -- Status strip --
    # Single line: LIVE dot · CEX/DEX counts · SCAN Ns ago · TOP opp
    # ─── ENGINE pill · ACCT · DD. All state at a glance, no tab hopping.
    status = tk.Frame(outer, bg=BG, height=22)
    status.pack(fill="x", padx=16, pady=(2, 4))
    status.pack_propagate(False)

    dot_color = GREEN if getattr(app, "_arb_cache", None) else DIM
    app._arb_live_dot = tk.Label(status, text="●",
                                 font=(FONT, 9, "bold"),
                                 fg=dot_color, bg=BG)
    app._arb_live_dot.pack(side="left", padx=(0, 4))
    tk.Label(status, text="LIVE", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 10))

    app._arb_sum_cex = tk.Label(status, text="CEX —",
                                font=(FONT, 7), fg=DIM2, bg=BG)
    app._arb_sum_cex.pack(side="left", padx=(0, 8))
    app._arb_sum_dex = tk.Label(status, text="DEX —",
                                font=(FONT, 7), fg=DIM2, bg=BG)
    app._arb_sum_dex.pack(side="left", padx=(0, 10))

    # Scan staleness — updated by _arb_schedule_clock each second
    app._arb_scan_age = tk.Label(status, text="SCAN —",
                                 font=(FONT, 7), fg=DIM, bg=BG)
    app._arb_scan_age.pack(side="left", padx=(0, 10))

    # Top opp inline
    app._arb_sum_best = tk.Label(status, text="TOP —",
                                 font=(FONT, 7, "bold"),
                                 fg=AMBER, bg=BG)
    app._arb_sum_best.pack(side="left", padx=(0, 14))

    # Engine pill — right side, with ACCT + DD
    app._arb_engine_ddlbl = tk.Label(status, text="", font=(FONT, 7),
                                     fg=DIM, bg=BG)
    app._arb_engine_ddlbl.pack(side="right")
    app._arb_engine_acctlbl = tk.Label(status, text="", font=(FONT, 7),
                                       fg=WHITE, bg=BG)
    app._arb_engine_acctlbl.pack(side="right", padx=(0, 8))
    app._arb_engine_pill = tk.Label(status, text=" OFF ",
                                    font=(FONT, 7, "bold"),
                                    fg=BG, bg=DIM, padx=4)
    app._arb_engine_pill.pack(side="right", padx=(0, 10))

    # Populate engine pill immediately from current state
    try:
        app._arb_update_status_strip()
    except Exception:
        pass

    # -- Tab strip --
    # Phase 1 redesign (2026-04-22): 3 tabs in a single row, no groups.
    # Simpler info architecture: OPPS (all opportunities, unified) /
    # POSITIONS (paper engine live) / HISTORY (closed trades).
    # Keys 1-3 only.
    grouped_tabs: list[tuple[str, list[tuple[str, str, str]]]] = [
        ("", [(key, tid, label) for key, tid, label, _ in app._ARB_TAB_DEFS])
    ]

    tabs_frame = tk.Frame(outer, bg=BG)
    tabs_frame.pack(fill="x", padx=16, pady=(2, 0))
    app._arb_tab = tab
    app._arb_tab_labels = {}

    first_group = True
    for group_name, group_items in grouped_tabs:
        if not first_group:
            tk.Frame(tabs_frame, bg=BORDER, width=1).pack(
                side="left", fill="y", padx=8, pady=(16, 2))
        first_group = False

        g_box = tk.Frame(tabs_frame, bg=BG)
        g_box.pack(side="left", padx=(0, 2))
        if group_name:
            tk.Label(
                g_box, text=group_name,
                font=(FONT, 6, "bold"), fg=AMBER, bg=BG,
                anchor="w", padx=4,
            ).pack(fill="x", pady=(0, 2))

        g_row = tk.Frame(g_box, bg=BG)
        g_row.pack(fill="x")

        for key, tid, label in group_items:
            is_active = (tid == tab)
            if is_active:
                fg, bg = BG, AMBER
            else:
                fg, bg = DIM, BG
            lbl = tk.Label(
                g_row,
                text=f"  [{key}]  {label}  ",
                font=(FONT, 9, "bold"),
                fg=fg, bg=bg, cursor="hand2",
                padx=10, pady=4, bd=0, highlightthickness=0,
            )
            lbl.pack(side="left", padx=(0, 1))
            lbl.bind("<Button-1>",
                     lambda _e, _t=tid: app._arbitrage_hub(_t))
            if not is_active:
                lbl.bind(
                    "<Enter>",
                    lambda _e, w=lbl: w.config(bg=BG3, fg=WHITE),
                )
                lbl.bind(
                    "<Leave>",
                    lambda _e, w=lbl: w.config(bg=BG, fg=DIM),
                )
            app._arb_tab_labels[tid] = lbl

    tk.Frame(outer, bg=BORDER, height=1).pack(
        fill="x", padx=16, pady=(4, 6))

    # -- Content area (tab-specific render) --
    content = tk.Frame(outer, bg=BG)
    content.pack(fill="both", expand=True, padx=16, pady=(0, 6))
    app._arb_content = content

    # Keyboard shortcuts — 1-6 switch tabs, R refresh, ESC back
    for key, tid, _, _ in app._ARB_TAB_DEFS:
        app._kb(f"<Key-{key}>",
                lambda _t=tid: app._arbitrage_hub(_t))
    app._kb("<Key-r>",
            lambda: app._arbitrage_hub(app._arb_tab))

    # Route to the tab renderer (Phase 1 redesign: 3-tab layout)
    render_map = {
        "opps":      app._arb_render_opps,
        "positions": app._arb_render_positions,
        "history":   app._arb_render_history,
    }
    render_fn = render_map.get(tab, app._arb_render_opps)
    render_fn(content)

    # If we have cached scan data from the previous tab visit, repaint
    # immediately instead of waiting ~2s for the next scan to finish.
    cache = getattr(app, "_arb_cache", None)
    if cache:
        try:
            app._arb_hub_telem_update(
                cache["stats"], cache["top"], cache["opps"],
                cache["arb_cc"], cache["arb_dd"], cache["arb_cd"],
                cache["basis"], cache["spot"])
        except Exception:
            pass

    # Kick off first async scan + schedule recurring refresh.
    # Speed: skip new network call if scanner cache is still fresh
    # (<10s). Lets tab-switch reuse existing data instantly.
    try:
        needs_scan = not app._arb_scan_is_fresh()
    except Exception:
        needs_scan = True
    if needs_scan:
        app._arb_hub_scan_async()
    app._arb_schedule_refresh()

    # Live clock tick — updates every second while the hub is open.
    app._arb_schedule_clock()
