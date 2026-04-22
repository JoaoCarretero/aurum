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
    app.f_lbl.configure(text="1-6 switch tab  |  R refresh  |  ESC back")
    app._kb("<Escape>", lambda: app._menu("main"))
    app._bind_global_nav()

    _outer, outer = app._ui_page_shell(
        "ARBITRAGE DESK",
        "All arbitrage modes in one place — scan, execute, monitor",
    )

    # -- Status strip --
    # Left: live-scan indicator + clock + ISO date, right: scanner
    # telemetry (CEX/DEX counts, top APR). Dot turns green when the
    # scanner has successfully populated the cache, stays dim while
    # the first scan is pending.
    status = tk.Frame(outer, bg=BG, height=20)
    status.pack(fill="x", padx=16, pady=(2, 4))
    status.pack_propagate(False)

    dot_color = GREEN if getattr(app, "_arb_cache", None) else DIM
    app._arb_live_dot = tk.Label(status, text="●",
                                 font=(FONT, 9, "bold"),
                                 fg=dot_color, bg=BG)
    app._arb_live_dot.pack(side="left", padx=(0, 4))
    tk.Label(status, text="LIVE", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 8))
    app._arb_clock = tk.Label(status, text="", font=(FONT, 7),
                              fg=WHITE, bg=BG)
    app._arb_clock.pack(side="left")
    try:
        now = datetime.now()
        app._arb_clock.configure(
            text=f"{now.strftime('%H:%M:%S UTC')}  ·  "
                 f"{now.strftime('%Y-%m-%d')}")
    except Exception:
        pass

    # Right side — telemetry grouped by label·value chips.
    app._arb_sum_best = tk.Label(status, text="TOP  —",
                                 font=(FONT, 7, "bold"),
                                 fg=AMBER, bg=BG)
    app._arb_sum_best.pack(side="right")
    app._arb_sum_dex = tk.Label(status, text="DEX  —",
                                font=(FONT, 7), fg=DIM2, bg=BG)
    app._arb_sum_dex.pack(side="right", padx=(0, 14))
    app._arb_sum_cex = tk.Label(status, text="CEX  —",
                                font=(FONT, 7), fg=DIM2, bg=BG)
    app._arb_sum_cex.pack(side="right", padx=(0, 14))
    tk.Label(status, text="SCAN", font=(FONT, 7, "bold"),
             fg=DIM, bg=BG).pack(side="right", padx=(0, 8))

    # -- Tab strip --
    # Same grouping pattern as Macro Brain: three functional buckets
    # rendered with a heading above and a bronze vertical rule between
    # them. Same HL2 chip styling (bracket-prefixed, solid amber when
    # active, flat BG with dim text when idle, BG3/WHITE on hover).
    # Keys 1-6 preserved.
    arb_group_of = {
        "cex-cex": "PAIRS", "dex-dex": "PAIRS", "cex-dex": "PAIRS",
        "basis": "RATES", "spot": "RATES",
        "engine": "EXECUTE",
    }
    grouped_tabs: list[tuple[str, list[tuple[str, str, str]]]] = []
    for key, tid, label, _color in app._ARB_TAB_DEFS:
        g = arb_group_of.get(tid, "OTHER")
        if not grouped_tabs or grouped_tabs[-1][0] != g:
            grouped_tabs.append((g, []))
        grouped_tabs[-1][1].append((key, tid, label))

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

    # Route to the tab renderer
    render_map = {
        "cex-cex": app._arb_render_cex_cex,
        "dex-dex": app._arb_render_dex_dex,
        "cex-dex": app._arb_render_cex_dex,
        "basis": app._arb_render_basis,
        "spot": app._arb_render_spot,
        "engine": app._arb_render_engine,
    }
    render_fn = render_map.get(tab, app._arb_render_cex_cex)
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
    app._arb_hub_scan_async()
    app._arb_schedule_refresh()

    # Live clock tick — updates every second while the hub is open.
    app._arb_schedule_clock()
