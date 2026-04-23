"""Arbitrage desk hub — 6-tab unified scanner screen.

Extracted from launcher.App._arbitrage_hub. render(app, tab="cex-cex")
builds the status strip (live dot + clock + CEX/DEX/top telemetry),
the grouped tab strip (PAIRS / RATES / EXECUTE buckets), the per-tab
content area, keyboard shortcuts, and kicks the scan/refresh loop.

Tab renderers live on App as _arb_render_* methods. The hub only
dispatches into them via the app parameter.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D,
    BG, BG2, BG3, BORDER, BORDER_H,
    DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)
from launcher_support.screens._metrics import timed_legacy_switch


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
    # Padding squeezed after 2026-04-22 organize pass — was breathing
    # too hard on a single terminal line. Every gap dropped ~25-30%.
    status = tk.Frame(outer, bg=BG, height=18)
    status.pack(fill="x", padx=16, pady=(0, 3))
    status.pack_propagate(False)

    dot_color = GREEN if getattr(app, "_arb_cache", None) else DIM
    app._arb_live_dot = tk.Label(status, text="●",
                                 font=(FONT, 9, "bold"),
                                 fg=dot_color, bg=BG)
    app._arb_live_dot.pack(side="left", padx=(0, 3))
    tk.Label(status, text="LIVE", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 8))

    app._arb_sum_cex = tk.Label(status, text="CEX —",
                                font=(FONT, 7), fg=DIM2, bg=BG)
    app._arb_sum_cex.pack(side="left", padx=(0, 6))
    app._arb_sum_dex = tk.Label(status, text="DEX —",
                                font=(FONT, 7), fg=DIM2, bg=BG)
    app._arb_sum_dex.pack(side="left", padx=(0, 8))

    # Scan staleness — updated by _arb_schedule_clock each second
    app._arb_scan_age = tk.Label(status, text="SCAN —",
                                 font=(FONT, 7), fg=DIM, bg=BG)
    app._arb_scan_age.pack(side="left", padx=(0, 8))

    # Top opp inline
    app._arb_sum_best = tk.Label(status, text="TOP —",
                                 font=(FONT, 7, "bold"),
                                 fg=AMBER, bg=BG)
    app._arb_sum_best.pack(side="left", padx=(0, 10))

    # Engine pill — right side, with ACCT + DD
    app._arb_engine_ddlbl = tk.Label(status, text="", font=(FONT, 7),
                                     fg=DIM, bg=BG)
    app._arb_engine_ddlbl.pack(side="right")
    app._arb_engine_acctlbl = tk.Label(status, text="", font=(FONT, 7),
                                       fg=WHITE, bg=BG)
    app._arb_engine_acctlbl.pack(side="right", padx=(0, 6))
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
    tabs_frame.pack(fill="x", padx=16, pady=(0, 0))
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
        fill="x", padx=16, pady=(2, 3))

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


# ─── extracted from launcher.App._arbitrage_hub (Fase 3) ───

def render_hub(app, tab: str = "opps"):
    """Delegate to launcher_support.screens.arbitrage_hub.render.
    Full hub (status strip + tab strip + content area + scanner +
    refresh loop) lives there. Tab renderers (_arb_render_*) stay
    on App and are dispatched via the app parameter.

    Extracted from launcher.App._arbitrage_hub in Fase 3 refactor.
    """
    # Route legacy tab ids to their new home
    tab = app._ARB_LEGACY_TAB_MAP.get(tab, tab)
    # Speed: if already on the requested tab with live widgets, just
    # repaint from cache instead of tearing down and rebuilding the
    # whole shell (status strip, tab strip, etc.). Saves ~40 widget
    # destroys + re-creates per tab click.
    current = getattr(app, "_arb_tab", None)
    labels = getattr(app, "_arb_tab_labels", None)
    if current == tab and labels:
        try:
            first = next(iter(labels.values()), None)
            if first is not None and first.winfo_exists():
                app._arb_rerender_current_tab()
                return
        except Exception:
            pass
    render(app, tab=tab)


# ─── extracted from launcher.App._arb_update_status_strip (Fase 3) ───

def update_status_strip(app):
    """Refresh scan staleness + engine pill in the hub status strip.

    Extracted from launcher.App._arb_update_status_strip in Fase 3 refactor.
    """
    import time as _time
    # Scan staleness
    scan_lbl = getattr(app, "_arb_scan_age", None)
    if scan_lbl is not None:
        try:
            last = getattr(app, "_arb_last_scan_ts", 0) or 0
            if last > 0:
                age = int(_time.time() - last)
                if age < 60:
                    txt, fg = f"SCAN {age}s ago", GREEN if age <= 20 else AMBER
                else:
                    txt, fg = f"SCAN {age // 60}m ago", RED
            else:
                txt, fg = "SCAN —", DIM
            scan_lbl.configure(text=txt, fg=fg)
        except Exception:
            pass
    # Engine pill
    pill = getattr(app, "_arb_engine_pill", None)
    acctlbl = getattr(app, "_arb_engine_acctlbl", None)
    ddlbl = getattr(app, "_arb_engine_ddlbl", None)
    engine = getattr(app, "_arb_simple_engine", None)
    if pill is not None:
        try:
            if engine is not None and engine.running:
                snap = engine.snapshot()
                mode = snap.get("mode", "paper").upper()
                pill.configure(
                    text=f" {mode} RUN ",
                    bg=GREEN if not snap.get("killed") else RED,
                    fg=BG,
                )
                if acctlbl is not None:
                    acctlbl.configure(
                        text=f"ACCT ${snap.get('account', 0):,.0f}",
                        fg=WHITE)
                if ddlbl is not None:
                    dd = float(snap.get("drawdown_pct", 0) or 0)
                    ddlbl.configure(
                        text=f"DD {dd:+.2f}%",
                        fg=RED if dd > 5 else (AMBER if dd > 1 else DIM))
            else:
                pill.configure(text=" OFF ", bg=DIM, fg=BG)
                if acctlbl is not None:
                    acctlbl.configure(text="", fg=DIM)
                if ddlbl is not None:
                    ddlbl.configure(text="", fg=DIM)
        except Exception:
            pass


# ─── extracted from launcher.App._arb_make_table (Fase 3) ───

def make_table(app, parent, cols: list[tuple[str, int, str]],
               on_click=None):
    """Build a grid-aligned header + body. Returns (body_frame, repaint_fn).

    cols: list of (label, width_chars, anchor). Header and body share the
    same grid column configuration, so cells stay perfectly aligned no
    matter the row content. Previous pack-based implementation drifted
    when cell text lengths varied.

    on_click(row_idx): optional callback fired when the user clicks any
    cell of a body row. Lets each tab attach a detail pane that reacts
    to the selected pair.

    Extracted from launcher.App._arb_make_table in Fase 3 refactor.
    """
    # Header row
    hdr = tk.Frame(parent, bg=BG)
    hdr.pack(fill="x", padx=2)
    for i, (label, w, anchor) in enumerate(cols):
        hdr.grid_columnconfigure(i, minsize=w * 7, weight=0, uniform="arb")
        sticky = "w" if anchor == "w" else "e"
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG, anchor=anchor).grid(
            row=0, column=i, sticky=sticky + "ns", padx=3, pady=(0, 2))
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(0, 2))

    # Body uses the same column config so each column lines up to header
    body = tk.Frame(parent, bg=BG)
    body.pack(fill="both", expand=True, padx=2)
    for i, (_, w, _) in enumerate(cols):
        body.grid_columnconfigure(i, minsize=w * 7, weight=0, uniform="arb")

    # In-place row cache: list of (cells, hover_bg) per current row.
    # repaint() diffs rows against this cache and only mutates cells
    # that actually changed, so a 15s scan refresh doesn't flicker —
    # text just updates like a terminal ticker.
    state = {"rows": [], "placeholder": None}

    def _clear_placeholder():
        if state["placeholder"] is not None:
            state["placeholder"].destroy()
            state["placeholder"] = None

    def _set_placeholder(msg: str):
        # Only replace the message if different — avoid flicker cycles.
        ph = state["placeholder"]
        if ph is not None:
            try:
                if ph.cget("text") == msg:
                    return
                ph.configure(text=msg)
                return
            except Exception:
                pass
        # Remove any rows first (placeholder = empty state)
        for (cells, _) in state["rows"]:
            for c in cells:
                c.destroy()
        state["rows"] = []
        state["placeholder"] = tk.Label(
            body, text=msg, font=(FONT, 8),
            fg=DIM2, bg=BG, justify="center")
        state["placeholder"].grid(
            row=0, column=0, columnspan=len(cols), pady=16)

    def _make_row(ri: int, row, bg_row: str):
        cells = []
        for ci, ((txt, fg), (_, _, anchor)) in enumerate(zip(row, cols)):
            sticky = "w" if anchor == "w" else "e"
            cursor = "hand2" if on_click else "arrow"
            cell = tk.Label(body, text=txt, font=(FONT, 8),
                             fg=fg, bg=bg_row, anchor=anchor,
                             cursor=cursor)
            cell.grid(row=ri, column=ci,
                      sticky=sticky + "nsew", padx=3, pady=1)
            cells.append(cell)
            if on_click is not None:
                cell.bind(
                    "<Button-1>", lambda _e, _i=ri: on_click(_i))
        if on_click is not None:
            def _hover_in(_e, cells=cells):
                for c in cells:
                    c.configure(bg=BG3)
            def _hover_out(_e, cells=cells, bgx=bg_row):
                for c in cells:
                    c.configure(bg=bgx)
            for c in cells:
                c.bind("<Enter>", _hover_in)
                c.bind("<Leave>", _hover_out)
        return cells

    def _update_row(cells, row, bg_row):
        for c, (txt, fg) in zip(cells, row):
            # Only push changes — comparing beforehand keeps Tk from
            # redrawing cells whose text/fg are identical to current.
            try:
                if c.cget("text") != txt:
                    c.configure(text=txt)
                if c.cget("fg") != fg:
                    c.configure(fg=fg)
                if c.cget("bg") != bg_row:
                    c.configure(bg=bg_row)
            except Exception:
                pass

    def repaint(rows: list[list[tuple[str, str]]]):
        """Diff-update rows in place. No destroy+rebuild on normal
        refresh, so the table reads like a ticker instead of blinking."""
        if not rows:
            has_scan = getattr(app, "_arb_cache", None) is not None
            msg = ("  — no pairs match current filters —\n"
                   "  click filter chips above to relax"
                   if has_scan else
                   "  — scanning venues, hold on —")
            _set_placeholder(msg)
            return

        _clear_placeholder()
        # Update existing rows in place where possible
        for ri, row in enumerate(rows):
            bg_row = BG if ri % 2 == 0 else BG2
            if ri < len(state["rows"]):
                cells, _ = state["rows"][ri]
                _update_row(cells, row, bg_row)
                state["rows"][ri] = (cells, bg_row)
            else:
                cells = _make_row(ri, row, bg_row)
                state["rows"].append((cells, bg_row))
        # Trim excess rows (previous refresh had more data than this one)
        while len(state["rows"]) > len(rows):
            cells, _ = state["rows"].pop()
            for c in cells:
                c.destroy()

    return body, repaint


# ─── extracted from launcher.App._arb_rerender_current_tab (Fase 3) ───

def rerender_current_tab(app) -> None:
    """Repaint the active tab from cached scan data (no network).

    Extracted from launcher.App._arb_rerender_current_tab in Fase 3 refactor.
    """
    cache = getattr(app, "_arb_cache", None)
    if not cache:
        return
    try:
        app._arb_hub_telem_update(
            cache.get("stats"), cache.get("top"),
            cache.get("opps", []), cache.get("arb_cc", []),
            cache.get("arb_dd", []), cache.get("arb_cd", []),
            cache.get("basis", []), cache.get("spot", []))
    except Exception:
        pass


# ─── extracted from launcher.App._arb_build_viab_toolbar (Fase 3) ───

def build_viab_toolbar(app, parent):
    """Phase 2: 3-button viability toolbar + NO RISKY VENUES toggle.

    Sits ABOVE the advanced filter chips. User picks a viability
    bucket ([GO ONLY]/[+WAIT]/[ALL]) and optionally excludes venues
    with low reliability. Simpler than the 5-chip cycling bar and
    answers the "does this position make sense?" question directly.

    Extracted from launcher.App._arb_build_viab_toolbar in Fase 3 refactor.
    """
    bar = tk.Frame(parent, bg=BG)
    bar.pack(fill="x", pady=(0, 3))

    # VIAB label dropped — legend row above already establishes the
    # semantics, and the GO/WAIT/ALL chips are self-explanatory.

    state = app._arb_filter_state()
    active = state.get("grade_min", "MAYBE")
    app._arb_viab_btns = {}

    viab_buttons = [
        ("GO ONLY", "GO",    GREEN),
        ("+WAIT",   "MAYBE", AMBER),
        ("ALL",     "SKIP",  DIM),
    ]
    for label, grade, color in viab_buttons:
        is_active = (grade == active)
        fg = BG if is_active else color
        bg = color if is_active else BG
        btn = tk.Label(
            bar, text=f"  {label}  ",
            font=(FONT, 8, "bold"),
            fg=fg, bg=bg, cursor="hand2",
            padx=8, pady=3, bd=0, highlightthickness=0,
        )
        btn.pack(side="left", padx=(0, 2))
        btn.bind("<Button-1>", lambda _e, _g=grade: app._arb_set_grade_min(_g))
        app._arb_viab_btns[label] = (btn, grade)

    # Divider
    tk.Frame(bar, bg=BORDER, width=1, height=18).pack(
        side="left", fill="y", padx=(10, 10))

    # [NO RISKY VENUES] toggle
    on = state.get("exclude_risky_venues", False)
    risky_btn = tk.Label(
        bar,
        text=f" {'[X]' if on else '[ ]'} NO RISKY VENUES ",
        font=(FONT, 8, "bold"),
        fg=RED if on else DIM, bg=BG,
        cursor="hand2", padx=6, pady=3,
    )
    risky_btn.pack(side="left")
    risky_btn.bind("<Button-1>", lambda _e: app._arb_toggle_risky_venues())
    app._arb_viab_btns["risky"] = (risky_btn, None)

    # [REALISTIC] toggle — hides APR>500% (stale funding) and vol<$5M
    # (can't execute without slippage eating the edge). Default ON so
    # the first-open view is clean.
    real_on = state.get("realistic_only", True)
    real_btn = tk.Label(
        bar,
        text=f" {'[X]' if real_on else '[ ]'} REALISTIC ",
        font=(FONT, 8, "bold"),
        fg=AMBER if real_on else DIM, bg=BG,
        cursor="hand2", padx=6, pady=3,
    )
    real_btn.pack(side="left", padx=(6, 0))
    real_btn.bind("<Button-1>", lambda _e: app._arb_toggle_realistic())
    app._arb_viab_btns["realistic"] = (real_btn, None)


# ─── extracted from launcher.App._arb_build_filter_bar (Fase 3) ───

def build_filter_bar(app, parent):
    """Render the shared filter chip strip. Click a chip to cycle its value.

    Filters persist across tab switches via app._arb_filters. Any value
    change re-renders the active tab from the cached scan (no network).

    Extracted from launcher.App._arb_build_filter_bar in Fase 3 refactor.
    """
    # Phase 2: viability toolbar on top, chips below as "advanced"
    app._arb_build_viab_toolbar(parent)

    # Phase 4: ADVANCED chips collapsed by default. Clickable toggle.
    state = app._arb_filter_state()
    adv_container = tk.Frame(parent, bg=BG)
    adv_container.pack(fill="x", pady=(0, 4))

    header = tk.Frame(adv_container, bg=BG)
    header.pack(fill="x")
    advanced_expanded = getattr(app, "_arb_advanced_expanded", False)
    arrow = "▼" if advanced_expanded else "▶"
    toggle = tk.Label(
        header, text=f" {arrow} ADVANCED FILTERS ",
        font=(FONT, 7, "bold"),
        fg=DIM, bg=BG, cursor="hand2", padx=4)
    toggle.pack(side="left")

    def _toggle_advanced(_e=None):
        app._arb_advanced_expanded = not getattr(app, "_arb_advanced_expanded", False)
        # Force full rebuild (not fast-path) by clearing tab labels
        app._arb_tab_labels = None
        app._arbitrage_hub(app._arb_tab)
    toggle.bind("<Button-1>", _toggle_advanced)

    # Early-return if collapsed — chip bar never mounted
    if not advanced_expanded:
        return

    bar = tk.Frame(adv_container, bg=BG2)
    bar.pack(fill="x", pady=(2, 0))
    tk.Label(bar, text=" click pra ciclar ",
             font=(FONT, 6), fg=DIM, bg=BG2).pack(
        side="left", padx=(0, 6))

    app._arb_filter_labels = {}
    filter_defs = [
        ("min_apr",    app._ARB_APR_OPTS),
        ("min_volume", app._ARB_VOL_OPTS),
        ("min_oi",     app._ARB_OI_OPTS),
        ("risk_max",   app._ARB_RISK_OPTS),
        ("grade_min",  app._ARB_GRADE_OPTS),
    ]
    for fkey, fopts in filter_defs:
        cur = state.get(fkey)
        lbl = tk.Label(bar, text=f" {app._arb_fmt_filter(fkey, cur)} ",
                       font=(FONT, 7, "bold"), fg=AMBER, bg=BG3,
                       cursor="hand2", padx=6, pady=2)
        lbl.pack(side="left", padx=2, pady=2)
        app._arb_filter_labels[fkey] = lbl
        # Hover signals "this is a chip you can click to cycle"
        # — previously only the cursor changed, easy to miss.
        lbl.bind("<Enter>",
                 lambda _e, w=lbl: w.config(bg=BORDER_H, fg=AMBER_B))
        lbl.bind("<Leave>",
                 lambda _e, w=lbl: w.config(bg=BG3, fg=AMBER))

        def _cycle(_e=None, _k=fkey, _opts=fopts):
            s = app._arb_filter_state()
            cur = s.get(_k)
            try:
                idx = _opts.index(cur)
            except ValueError:
                idx = 0
            nxt = _opts[(idx + 1) % len(_opts)]
            s[_k] = nxt
            app._arb_filter_labels[_k].configure(
                text=f" {app._arb_fmt_filter(_k, nxt)} ")
            # Keep viability toolbar in sync when grade_min changes
            if _k == "grade_min":
                app._arb_refresh_viab_toolbar()
            app._arb_save_filters()
            app._arb_rerender_current_tab()
        lbl.bind("<Button-1>", _cycle)


# ─── extracted from launcher.App._arb_build_detail_pane (Fase 3) ───

def build_detail_pane(app, parent):
    """Reserve a detail panel below the table. Empty-state is just a
    single-line hint (no separate title + body frames) so the OPPS
    table keeps the full vertical budget until the user clicks a row.
    Body is BG2 so _arb_show_detail's BG2 child labels render as a
    cohesive card when populated.

    Extracted from launcher.App._arb_build_detail_pane in Fase 3 refactor.
    """
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(4, 0))
    body = tk.Frame(parent, bg=BG2)
    body.pack(fill="x", pady=(0, 0))
    default = tk.Label(
        body,
        text="  DETAIL  ›  clique numa linha pra simular posição",
        font=(FONT, 7), fg=DIM, bg=BG2)
    default.pack(anchor="w", padx=4, pady=(2, 2))
    app._arb_detail_body = body
    app._arb_detail_default = default


# ─── extracted from launcher.App._arb_show_detail (Fase 3) ───

@timed_legacy_switch("arb_detail")
def show_detail(app, pair: dict):
    """Render the simulator detail pane for a selected pair.

    Layout (top-down): header | status line (APR/VIAB/SCORE/BKEVN) |
    size chips | simulation table (8h/24h/72h + decay row) | risk
    block (liq/slip/venues) | why-line | collapsible ADVANCED factor
    breakdown | size-aware OPEN AS PAPER button.

    Extracted from launcher.App._arb_show_detail in Fase 3 refactor.
    """
    body = getattr(app, "_arb_detail_body", None)
    if body is None:
        return
    for w in body.winfo_children():
        w.destroy()

    # Track selected pair + size + ADVANCED expansion between clicks
    app._arb_detail_pair = pair
    if not hasattr(app, "_arb_detail_size"):
        app._arb_detail_size = 1000.0
    if not hasattr(app, "_arb_detail_adv"):
        app._arb_detail_adv = False
    size_usd = app._arb_detail_size

    try:
        from core.arb.arb_scoring import score_opp
        res = score_opp(pair)
    except Exception:
        res = None

    # -- Header -----------------------------------------------
    tk.Label(body, text=app._arb_pair_label(pair),
             font=(FONT, 9, "bold"), fg=AMBER, bg=BG2,
             anchor="w").pack(fill="x", padx=6, pady=(4, 1))

    # -- Status line: APR / VIAB / SCORE / BKEVN --------------
    apr_val = float(pair.get("net_apr") or pair.get("apr") or 0)
    status = tk.Frame(body, bg=BG2); status.pack(fill="x", padx=6)
    tk.Label(status, text=f"APR {apr_val:+.1f}%",
             font=(FONT, 9, "bold"),
             fg=GREEN if abs(apr_val) >= 50 else AMBER,
             bg=BG2).pack(side="left")
    if res is not None:
        viab = getattr(res, "viab", res.grade)
        viab_fg = (GREEN if viab == "GO" else
                   AMBER if viab in ("WAIT", "MAYBE") else DIM)
        tk.Label(status, text=f"  ·  {viab}",
                 font=(FONT, 9, "bold"), fg=viab_fg, bg=BG2).pack(side="left")
        tk.Label(status, text=f"  ·  score {res.score:.0f}",
                 font=(FONT, 8), fg=WHITE, bg=BG2).pack(side="left")
        be = getattr(res, "breakeven_h", None)
        if be is not None:
            be_fg = GREEN if be <= 24 else (AMBER if be <= 72 else DIM)
            tk.Label(status, text=f"  ·  bkevn {be:.1f}h",
                     font=(FONT, 8), fg=be_fg, bg=BG2).pack(side="left")

    # -- Size chips -------------------------------------------
    size_row = tk.Frame(body, bg=BG2)
    size_row.pack(fill="x", padx=6, pady=(6, 2))
    tk.Label(size_row, text="SIZE", font=(FONT, 7, "bold"),
             fg=DIM, bg=BG2).pack(side="left", padx=(0, 6))
    for s in app._ARB_SIM_SIZES:
        is_sel = abs(s - size_usd) < 0.01
        chip = tk.Label(
            size_row,
            text=f"  ${int(s):,}  " if s >= 1000 else f"  ${int(s)}  ",
            font=(FONT, 8, "bold"),
            fg=BG if is_sel else WHITE,
            bg=AMBER if is_sel else BG3,
            cursor="hand2", padx=4, pady=2,
        )
        chip.pack(side="left", padx=(0, 3))
        chip.bind("<Button-1>",
                  lambda _e, _s=s: app._arb_set_detail_size(_s))

    # -- Simulation table -------------------------------------
    sim = app._arb_simulate(pair, size_usd)
    sim_frame = tk.Frame(body, bg=BG2)
    sim_frame.pack(fill="x", padx=6, pady=(4, 4))
    cols = [("HOLD", 10, "w"), ("FUNDING", 10, "e"),
            ("FEES", 9, "e"), ("NET", 10, "e")]
    for j, (c, w, a) in enumerate(cols):
        tk.Label(sim_frame, text=c, font=(FONT, 7, "bold"),
                 fg=AMBER, bg=BG2, width=w, anchor=a).grid(
            row=0, column=j, sticky=a, padx=2)
    for i, r in enumerate(sim["rows"], start=1):
        hold_txt = f"{r['hold_h']}h"
        if sim["bkevn_h"] is not None and r["hold_h"] >= sim["bkevn_h"]:
            hold_txt += "  ✓"
        tk.Label(sim_frame, text=hold_txt, font=(FONT, 8),
                 fg=WHITE, bg=BG2, width=10, anchor="w").grid(
            row=i, column=0, sticky="w", padx=2)
        tk.Label(sim_frame, text=f"+${r['funding']:.2f}",
                 font=(FONT, 8), fg=GREEN, bg=BG2,
                 width=10, anchor="e").grid(
            row=i, column=1, sticky="e", padx=2)
        tk.Label(sim_frame, text=f"-${r['fees']:.2f}",
                 font=(FONT, 8), fg=RED, bg=BG2,
                 width=9, anchor="e").grid(
            row=i, column=2, sticky="e", padx=2)
        net_fg = GREEN if r["net"] > 0 else RED
        tk.Label(sim_frame, text=f"${r['net']:+.2f}",
                 font=(FONT, 8, "bold"), fg=net_fg, bg=BG2,
                 width=10, anchor="e").grid(
            row=i, column=3, sticky="e", padx=2)
    # Decay scenario row
    decay_i = len(sim["rows"]) + 1
    d = sim["decay"]
    tk.Label(sim_frame, text=d["label"], font=(FONT, 7, "italic"),
             fg=DIM2, bg=BG2, width=20, anchor="w").grid(
        row=decay_i, column=0, columnspan=2, sticky="w",
        padx=2, pady=(3, 0))
    tk.Label(sim_frame, text=f"-${d['fees']:.2f}",
             font=(FONT, 7, "italic"), fg=DIM2, bg=BG2,
             width=9, anchor="e").grid(
        row=decay_i, column=2, sticky="e", padx=2, pady=(3, 0))
    decay_fg = GREEN if d["net"] > 0 else RED
    tk.Label(sim_frame, text=f"${d['net']:+.2f}",
             font=(FONT, 7, "italic"), fg=decay_fg, bg=BG2,
             width=10, anchor="e").grid(
        row=decay_i, column=3, sticky="e", padx=2, pady=(3, 0))

    # -- Risk block -------------------------------------------
    tk.Frame(body, bg=BORDER, height=1).pack(
        fill="x", padx=6, pady=(2, 2))
    risk = sim["risk"]
    risk_frame = tk.Frame(body, bg=BG2)
    risk_frame.pack(fill="x", padx=6, pady=(2, 2))
    tk.Label(risk_frame, text="RISK", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG2).grid(row=0, column=0, sticky="w",
                                     padx=(0, 8))
    liq_txt = (f"liq {risk['liq_short_pct']:.1f}% short · "
               f"{risk['liq_long_pct']:.1f}% long")
    tk.Label(risk_frame, text=liq_txt, font=(FONT, 7),
             fg=DIM2, bg=BG2).grid(row=0, column=1, sticky="w")
    if risk["slippage_bps"] is not None:
        slip_fg = (GREEN if risk["slippage_bps"] < 5 else
                   AMBER if risk["slippage_bps"] < 15 else RED)
        slip_txt = (f"slip ~{risk['slippage_bps']:.1f}bps "
                    f"(vol ratio {risk['vol_ratio']:,.0f}x)")
    else:
        slip_fg = DIM
        slip_txt = "slip —"
    tk.Label(risk_frame, text=slip_txt, font=(FONT, 7),
             fg=slip_fg, bg=BG2).grid(row=1, column=1, sticky="w")
    venue_bits = []
    for name, rel in (("short", risk["short_rel"]),
                      ("long",  risk["long_rel"])):
        ven = risk["short_venue"] if name == "short" else risk["long_venue"]
        if rel is not None:
            venue_bits.append(f"{ven} {rel:.0f}")
        elif ven:
            venue_bits.append(f"{ven} ?")
    ven_fg = DIM2
    if risk["short_rel"] and risk["long_rel"]:
        worst = min(risk["short_rel"], risk["long_rel"])
        ven_fg = GREEN if worst >= 97 else (AMBER if worst >= 94 else RED)
    tk.Label(risk_frame, text="venues " + " · ".join(venue_bits),
             font=(FONT, 7), fg=ven_fg, bg=BG2).grid(
        row=2, column=1, sticky="w")

    # -- Why line ---------------------------------------------
    if res is not None:
        reason = app._arb_viab_reason(pair, res)
        if reason:
            tk.Label(body, text=reason,
                     font=(FONT, 7), fg=DIM, bg=BG2,
                     anchor="w", justify="left", wraplength=600).pack(
                fill="x", padx=6, pady=(2, 2))

    # -- ADVANCED (collapsible factor breakdown) --------------
    if res is not None:
        adv_on = app._arb_detail_adv
        adv_head = tk.Label(
            body,
            text=("▼ ADVANCED  (factor breakdown)" if adv_on
                  else "▶ ADVANCED  (factor breakdown)"),
            font=(FONT, 7), fg=DIM, bg=BG2,
            anchor="w", cursor="hand2",
        )
        adv_head.pack(fill="x", padx=6, pady=(2, 0))
        adv_head.bind(
            "<Button-1>",
            lambda _e: app._arb_toggle_detail_adv())
        if adv_on:
            adv_grid = tk.Frame(body, bg=BG2)
            adv_grid.pack(fill="x", padx=12, pady=(2, 4))
            factor_rows = [
                ("NET APR", res.factors.get("net_apr"),
                    f"{apr_val:+.1f}%"),
                ("VOLUME",  res.factors.get("volume"),
                    app._fmt_vol(pair.get("volume_24h")
                                  or app._pair_min(pair.get("volume_24h_short"),
                                                     pair.get("volume_24h_long")))),
                ("OI",      res.factors.get("oi"),
                    app._fmt_vol(pair.get("open_interest")
                                  or app._pair_min(pair.get("open_interest_short"),
                                                     pair.get("open_interest_long")))),
                ("RISK",    res.factors.get("risk"),
                    pair.get("risk", "—")),
                ("SLIP",    res.factors.get("slippage"), "—"),
                ("VENUE",   res.factors.get("venue"),
                    app._arb_venue_label(pair)),
            ]
            for i, (label, score, value) in enumerate(factor_rows):
                adv_grid.grid_columnconfigure(1, weight=1)
                tk.Label(adv_grid, text=label, font=(FONT, 7, "bold"),
                         fg=DIM, bg=BG2, width=8, anchor="w").grid(
                    row=i, column=0, sticky="w", padx=(0, 6))
                tk.Label(adv_grid, text=value, font=(FONT, 8),
                         fg=WHITE, bg=BG2, anchor="w").grid(
                    row=i, column=1, sticky="w")
                s_txt = "—" if score is None else f"{score:.0f}/100"
                s_fg = (GREEN if (score or 0) >= 70 else
                        AMBER if (score or 0) >= 40 else DIM)
                tk.Label(adv_grid, text=s_txt, font=(FONT, 7),
                         fg=s_fg, bg=BG2, width=10, anchor="e").grid(
                    row=i, column=2, sticky="e")

    # -- Action bar: size-aware OPEN AS PAPER POSITION --------
    tk.Frame(body, bg=BORDER, height=1).pack(
        fill="x", padx=6, pady=(2, 2))
    action = tk.Frame(body, bg=BG2)
    action.pack(fill="x", padx=6, pady=(2, 6))

    engine = getattr(app, "_arb_simple_engine", None)
    engine_running = engine is not None and engine.running
    size_label = (f"${int(size_usd):,}" if size_usd >= 1000
                  else f"${int(size_usd)}")
    if engine_running:
        btn_text = f" OPEN AS PAPER — {size_label} "
        btn_fg, btn_bg = BG, GREEN
        btn_cmd = lambda _e=None, _p=pair, _s=size_usd: (
            app._arb_open_as_paper(_p, size_usd=_s))
    else:
        btn_text = " START ENGINE FIRST (POSITIONS tab) "
        btn_fg, btn_bg = DIM, BG3
        btn_cmd = lambda _e=None: None
    btn = tk.Label(action, text=btn_text,
                   font=(FONT, 8, "bold"),
                   fg=btn_fg, bg=btn_bg,
                   cursor="hand2" if engine_running else "arrow",
                   padx=10, pady=4)
    btn.pack(side="left")
    btn.bind("<Button-1>", btn_cmd)


# ─── extracted from launcher.App._arb_set_detail_size (Fase 3) ───

def set_detail_size(app, size_usd: float) -> None:
    """Size chip click - re-render detail with new size.

    Extracted from launcher.App._arb_set_detail_size in Fase 3 refactor.
    """
    app._arb_detail_size = float(size_usd)
    pair = getattr(app, "_arb_detail_pair", None)
    if pair is not None:
        app._arb_show_detail(pair)


# ─── extracted from launcher.App._arb_toggle_detail_adv (Fase 3) ───

def toggle_detail_adv(app) -> None:
    """ADVANCED section expand/collapse toggle.

    Extracted from launcher.App._arb_toggle_detail_adv in Fase 3 refactor.
    """
    app._arb_detail_adv = not getattr(app, "_arb_detail_adv", False)
    pair = getattr(app, "_arb_detail_pair", None)
    if pair is not None:
        app._arb_show_detail(pair)


# ─── extracted from launcher.App._arb_render_engine (Fase 3) ───

def render_engine(app, parent):
    """SimpleArbEngine (in-process) controls + live risk + positions.

    Extracted from launcher.App._arb_render_engine in Fase 3 refactor.
    """
    engine = getattr(app, "_arb_simple_engine", None)
    if engine is not None and engine.running:
        snap = engine.snapshot()
        running_badge = ("RUN", GREEN)
    else:
        snap = {
            "mode": "—", "running": False, "killed": False,
            "account": 0, "peak": 0, "drawdown_pct": 0,
            "realized_pnl": 0, "unrealized_pnl": 0, "exposure_usd": 0,
            "losses_streak": 0, "trades_count": 0, "positions": [],
        }
        running_badge = ("OFF", RED)

    # Status strip (engine-specific)
    top = tk.Frame(parent, bg=BG)
    top.pack(fill="x", pady=(0, 4))
    tk.Label(top, text="ARB ENGINE",
             font=(FONT, 9, "bold"), fg=AMBER, bg=BG).pack(side="left")
    tk.Label(top, text=f"  ·  {running_badge[0]}  ·  mode {snap.get('mode', '—')}",
             font=(FONT, 8), fg=running_badge[1], bg=BG).pack(side="left")
    if snap.get("killed"):
        tk.Label(top, text="  ·  KILLED", font=(FONT, 8, "bold"),
                 fg=RED, bg=BG).pack(side="left")

    # Live risk gauges
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))
    gauges = tk.Frame(parent, bg=BG)
    gauges.pack(fill="x", pady=(0, 4))
    for k, label, fmt in [
        ("account", "ACCT", "${:,.0f}"),
        ("drawdown_pct", "DD", "{:+.2f}%"),
        ("exposure_usd", "EXPO", "${:,.0f}"),
        ("realized_pnl", "REAL", "${:+,.2f}"),
        ("unrealized_pnl", "UPNL", "${:+,.2f}"),
        ("losses_streak", "STREAK", "{}"),
        ("trades_count", "TRADES", "{}"),
    ]:
        val = snap.get(k, 0) or 0
        try:
            vtxt = fmt.format(val)
        except Exception:
            vtxt = "—"
        col = tk.Frame(gauges, bg=BG)
        col.pack(side="left", padx=(0, 16))
        tk.Label(col, text=label, font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG).pack(anchor="w")
        tk.Label(col, text=vtxt, font=(FONT, 10, "bold"),
                 fg=WHITE, bg=BG).pack(anchor="w")

    # Controls
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
    ctrls = tk.Frame(parent, bg=BG)
    ctrls.pack(fill="x", pady=(0, 4))
    tk.Label(ctrls, text="  controls:",
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="left")
    for text, cmd, color in [
        ("START PAPER", lambda: app._arb_engine_start("paper"), GREEN),
        ("STOP",        app._arb_engine_stop,                    RED),
    ]:
        b = tk.Label(ctrls, text=f"  {text}  ", font=(FONT, 7, "bold"),
                     fg=BG, bg=color, cursor="hand2", padx=6, pady=1)
        b.pack(side="left", padx=(6, 0))
        b.bind("<Button-1>", lambda _e, _c=cmd: _c())

    # Live positions table (Phase 3: proper diff-updating _arb_make_table
    # instead of tk.Text — gains colored APR/PnL, click-to-detail, etc.)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
    tk.Label(parent, text="OPEN POSITIONS",
             font=(FONT, 7, "bold"), fg=DIM, bg=BG).pack(anchor="w")
    positions = snap.get("positions", [])
    pos_cols = [
        ("SYM",      10, "w"),
        ("VENUES",   18, "w"),
        ("APR NOW",  9,  "e"),
        ("ACCRUED",  9,  "e"),
        ("NET P&L",  9,  "e"),
        ("OPEN",     7,  "e"),
    ]
    _, pos_repaint = app._arb_make_table(parent, pos_cols)
    if positions:
        pos_rows = []
        for p in positions:
            entry_apr = float(p.get("entry_apr", 0) or 0)
            cur_apr = float(p.get("current_apr", 0) or 0)
            # APR decay color: RED if below 50% of entry
            if abs(entry_apr) > 0 and abs(cur_apr) / abs(entry_apr) < 0.5:
                apr_fg = RED
            elif abs(cur_apr) >= 50:
                apr_fg = GREEN
            else:
                apr_fg = AMBER
            accrued = float(p.get("funding_accrued", 0) or 0)
            fees = float(p.get("fees_paid", 0) or 0)
            # Entry fees already deducted; approximate exit fee for
            # net-P&L preview (matches SimpleArbEngine._close math).
            exit_fee_est = fees  # symmetric
            net_pnl = accrued - fees - exit_fee_est
            sv = (p.get("venue_short", "") or "")[:8]
            lv = (p.get("venue_long", "") or "")[:8]
            pos_rows.append([
                ((p.get("symbol", "") or "—")[:10], WHITE),
                (f"{lv}>{sv}"[:18], AMBER_D),
                (f"{cur_apr:+.1f}%", apr_fg),
                (f"${accrued:+.2f}", GREEN if accrued >= 0 else RED),
                (f"${net_pnl:+.2f}", GREEN if net_pnl >= 0 else RED),
                (f"{p.get('hours_open', 0):.1f}h", DIM),
            ])
        pos_repaint(pos_rows)
    else:
        pos_repaint([])
        tk.Label(parent, text="  no positions open — start engine in POSITIONS tab",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=4)

    # Recent closed trades (tail, proper table)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
    tk.Label(parent, text="RECENT CLOSES",
             font=(FONT, 7, "bold"), fg=DIM, bg=BG).pack(anchor="w")
    closed_cols = [
        ("SYM",     10, "w"),
        ("REASON",  11, "w"),
        ("HOLD",    6,  "e"),
        ("P&L",     9,  "e"),
    ]
    _, closed_repaint = app._arb_make_table(parent, closed_cols)
    recent = (snap.get("closed_recent", []) or
              (engine.closed[-10:] if engine is not None else []))
    if recent:
        closed_rows = []
        for c in reversed(recent):
            pnl = float(c.get("pnl", 0) or 0)
            closed_rows.append([
                ((c.get("symbol", "") or "—")[:10], WHITE),
                ((c.get("exit_reason", "") or "")[:11], DIM),
                (f"{c.get('hours_open', 0):.1f}h", DIM),
                (f"${pnl:+.2f}", GREEN if pnl >= 0 else RED),
            ])
        closed_repaint(closed_rows)
    else:
        closed_repaint([])
        tk.Label(parent, text="  no closes yet",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=4)


# ─── extracted from launcher.App._arb_render_opps (Fase 3) ───

def render_opps(app, parent):
    """Unified OPPS table. All 5 legacy tabs (cex-cex / dex-dex /
    cex-dex / basis / spot) merged here, scored + bucketed by VIAB.

    Header collapses the tab title + VIAB legend into one row so
    the table shows up within ~80px of the status strip.

    Extracted from launcher.App._arb_render_opps in Fase 3 refactor.
    """
    head = tk.Frame(parent, bg=BG)
    head.pack(fill="x", pady=(0, 3))
    # GO / WAIT / SKIP legend inline — surfaces the triage rule
    # without burning a second row on it. Colors match the table
    # cells so the eye bridges legend→rows automatically.
    tk.Label(head, text="GO", font=(FONT, 7, "bold"),
             fg=GREEN, bg=BG).pack(side="left", padx=(0, 3))
    tk.Label(head, text="score≥70 · bkevn≤24h · líquido",
             font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left", padx=(0, 8))
    tk.Label(head, text="WAIT", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 3))
    tk.Label(head, text="score≥40 · bkevn≤72h OU vol moderada",
             font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left", padx=(0, 8))
    tk.Label(head, text="SKIP", font=(FONT, 7, "bold"),
             fg=DIM, bg=BG).pack(side="left", padx=(0, 3))
    tk.Label(head, text="resto", font=(FONT, 7),
             fg=DIM2, bg=BG).pack(side="left")
    app._arb_build_filter_bar(parent)
    app._arb_opps_selected = []

    def _on_click(ri: int):
        if 0 <= ri < len(app._arb_opps_selected):
            app._arb_show_detail(app._arb_opps_selected[ri])

    _, repaint = app._arb_make_table(parent, app._ARB_OPPS_COLS,
                                      on_click=_on_click)
    app._arb_opps_repaint = repaint
    repaint([])
    app._arb_build_detail_pane(parent)


# ─── extracted from launcher.App._arb_render_positions (Fase 3) ───

def render_positions(app, parent):
    """Live paper engine positions + controls. Inherits body from
    legacy _arb_render_engine — no destruction, just routed via
    the new 3-tab layout.

    Extracted from launcher.App._arb_render_positions in Fase 3 refactor.
    """
    app._arb_render_engine(parent)


# ─── extracted from launcher.App._arb_render_history (Fase 3) ───

def render_history(app, parent):
    """Closed trades log from SimpleArbEngine. Newest first, realized
    PnL total at top. Read-only; rebuilds only when len(closed)
    changes.

    Extracted from launcher.App._arb_render_history in Fase 3 refactor.
    """
    engine = getattr(app, "_arb_simple_engine", None)
    closed = (engine.closed if engine is not None else [])

    total_pnl = round(sum(c.get("pnl", 0) for c in closed), 2)
    n = len(closed)
    header = tk.Frame(parent, bg=BG)
    header.pack(fill="x", pady=(0, 4))
    tk.Label(header, text="HISTORY",
             font=(FONT, 9, "bold"), fg=AMBER, bg=BG).pack(side="left")
    tk.Label(header, text=f"  ·  {n} trades closed  ·  realized ",
             font=(FONT, 8), fg=DIM, bg=BG).pack(side="left")
    pnl_fg = GREEN if total_pnl >= 0 else RED
    tk.Label(header, text=f"${total_pnl:+,.2f}",
             font=(FONT, 9, "bold"), fg=pnl_fg, bg=BG).pack(side="left")

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 6))

    if not closed:
        tk.Label(parent,
                 text="  No closed trades yet. Start the engine in POSITIONS tab.",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=8)
        return

    cols = [
        ("SYM",    9,  "w"),
        ("VENUES", 16, "w"),
        ("REASON", 11, "w"),
        ("HOLD",   6,  "e"),
        ("PNL",    9,  "e"),
    ]
    _, repaint = app._arb_make_table(parent, cols)
    rows = []
    for c in reversed(closed):  # newest first
        pnl = c.get("pnl", 0) or 0
        pnl_fg = GREEN if pnl >= 0 else RED
        venues = f"{c.get('venue_short','')}/{c.get('venue_long','')}"[:16]
        rows.append([
            (c.get("symbol", "")[:9], WHITE),
            (venues, AMBER_D),
            (c.get("exit_reason", "")[:11], DIM),
            (f"{c.get('hours_open', 0):.1f}h", DIM),
            (f"${pnl:+,.2f}", pnl_fg),
        ])
    repaint(rows)


# ─── extracted from launcher.App._arb_paint_opps (Fase 3) ───

def paint_opps(app, arb_cc, arb_dd, arb_cd, basis, spot):
    """Unified OPPS painter — merges 5 opp types, applies filter+score,
    caps at 50 rows, paints with VIAB column.

    Extracted from launcher.App._arb_paint_opps in Fase 3 refactor.
    """
    repaint = getattr(app, "_arb_opps_repaint", None)
    if repaint is None:
        return

    # Tag each type
    tagged: list[dict] = []
    for p in (arb_cc or []):
        pp = dict(p); pp["_type"] = "CC"; tagged.append(pp)
    for p in (arb_dd or []):
        pp = dict(p); pp["_type"] = "DD"; tagged.append(pp)
    for p in (arb_cd or []):
        pp = dict(p); pp["_type"] = "CD"; tagged.append(pp)
    for p in (basis or []):
        pp = dict(p); pp["_type"] = "BS"
        # Adapt basis to look like an arb pair for scoring
        pp.setdefault("net_apr", pp.get("basis_apr"))
        pp.setdefault("short_venue", pp.get("venue_perp"))
        pp.setdefault("long_venue", pp.get("venue_spot"))
        pp.setdefault("volume_24h_short", pp.get("volume_perp"))
        pp.setdefault("volume_24h_long", pp.get("volume_spot"))
        pp.setdefault("volume_24h", min(
            pp.get("volume_perp", 0) or 0,
            pp.get("volume_spot", 0) or 0))
        tagged.append(pp)
    for p in (spot or []):
        pp = dict(p); pp["_type"] = "SP"
        # Spot spread: convert bps to rough APR equivalent — treat
        # as a one-shot trade (no funding cycle), so scoring is only
        # meaningful for viewing. Use spread_bps as APR proxy.
        pp.setdefault("net_apr", abs(pp.get("spread_bps", 0) or 0) / 100.0)
        pp.setdefault("short_venue", pp.get("venue_a"))
        pp.setdefault("long_venue", pp.get("venue_b"))
        pp.setdefault("volume_24h_short", pp.get("volume_a"))
        pp.setdefault("volume_24h_long", pp.get("volume_b"))
        pp.setdefault("volume_24h", min(
            pp.get("volume_a", 0) or 0,
            pp.get("volume_b", 0) or 0))
        tagged.append(pp)

    # Apply filter+score (with cache) and render cap
    filtered = app._arb_filter_and_score(tagged)[:50]
    app._arb_opps_selected = [p for p, _ in filtered]

    rows = []
    for a, sr in filtered:
        viab = getattr(sr, "viab", sr.grade)
        if viab == "GO":
            viab_fg = GREEN
        elif viab in ("WAIT", "MAYBE"):
            viab_fg = AMBER
        else:
            viab_fg = DIM
        net_apr = float(a.get("net_apr", 0) or 0)
        apr_fg = GREEN if abs(net_apr) >= 50 else (
            AMBER if abs(net_apr) >= 20 else DIM)
        be = getattr(sr, "breakeven_h", None)
        be_txt = f"{be:.1f}h" if be is not None and be < 999 else "—"
        be_fg = GREEN if (be is not None and be <= 24) else (
            AMBER if (be is not None and be <= 72) else DIM)
        short_v = (a.get("short_venue") or "")[:10].lower()
        long_v = (a.get("long_venue") or "")[:10].lower()
        # Long leg goes first (the one you BUY), then short. Arrow
        # direction (→) reads naturally as "take long from here,
        # short to there". Width 22 fits "binance → bybit" plus
        # slack for longer venue names.
        venues = f"{long_v} → {short_v}"[:22]
        rows.append([
            (viab, viab_fg),
            ((a.get("symbol", "") or "—")[:11], WHITE),
            (venues, AMBER_D),
            (f"{net_apr:+.1f}%", apr_fg),
            (be_txt, be_fg),
            (f"{int(sr.score):>3}", DIM),
        ])
    repaint(rows)


# ─── extracted from launcher.App._arb_paint_pairs (Fase 3) ───

def paint_pairs(app, pairs, repaint, selected_attr: str):
    """Render the 9-column pair table with scoring filter applied.

    selected_attr: name of the instance attribute that holds the filtered
    pair list, so click handlers can map row index → pair dict.

    Extracted from launcher.App._arb_paint_pairs in Fase 3 refactor.
    """
    if repaint is None:
        return
    filtered = app._arb_filter_and_score(pairs)[:20]
    # Expose filtered list so _on_click resolves correctly
    setattr(app, selected_attr, [p for p, _ in filtered])

    rows = []
    for i, (a, sr) in enumerate(filtered, 1):
        net_apr = float(a.get("net_apr", 0) or 0)
        apr_fg = GREEN if net_apr >= 20 else (AMBER if net_apr >= 10 else DIM)
        risk = a.get("risk", "—")
        risk_fg = RED if risk == "HIGH" else (AMBER if risk == "MED" else GREEN)
        vol = (a.get("volume_24h") or
               app._pair_min(a.get("volume_24h_short"),
                               a.get("volume_24h_long")) or 0)
        oi = (a.get("open_interest") or
              app._pair_min(a.get("open_interest_short"),
                              a.get("open_interest_long")) or 0)
        grade_fg = (GREEN if sr.grade == "GO" else
                    AMBER if sr.grade == "MAYBE" else DIM)
        grade_txt = f"{int(sr.score):>2} {sr.grade}"
        rows.append([
            (f"{i:>2}", DIM),
            ((a.get("symbol", "—") or "—")[:7], WHITE),
            ((a.get("long_venue") or "—")[:10].lower(), AMBER_D),
            ((a.get("short_venue") or "—")[:10].lower(), AMBER_D),
            (f"{net_apr:+.1f}%", apr_fg),
            (app._fmt_vol(vol), DIM),
            (app._fmt_vol(oi), DIM),
            (risk, risk_fg),
            (grade_txt, grade_fg),
        ])
    repaint(rows)


# ─── extracted from launcher.App._arb_paint_basis (Fase 3) ───

def paint_basis(app, basis):
    """Paint the basis tab repaint callback with filter applied.

    Extracted from launcher.App._arb_paint_basis in Fase 3 refactor.
    """
    repaint = getattr(app, "_arb_basis_repaint", None)
    if repaint is None:
        return
    # Filter: basis pairs can be scored via arb_scoring — each leg has a
    # net_apr-equivalent (basis_apr). Use the user's APR floor + grade
    # filter; volume/OI filters don't apply (basis data is thinner).
    state = app._arb_filter_state()
    min_apr = state.get("min_apr", 0)
    filtered_list = []
    for p in (basis or []):
        if abs(float(p.get("basis_apr", 0) or 0)) < min_apr:
            continue
        filtered_list.append(p)
    filtered_list = filtered_list[:20]
    app._arb_basis_selected = filtered_list
    rows = []
    for i, p in enumerate(filtered_list, 1):
        bps = p.get("basis_bps", 0)
        bps_fg = GREEN if abs(bps) >= 20 else (AMBER if abs(bps) >= 10 else DIM)
        rows.append([
            (f"{i:>2}", DIM),
            (p.get("symbol", "—")[:7], WHITE),
            (p.get("venue_perp", "—")[:9].lower(), AMBER_D),
            (p.get("venue_spot", "—")[:9].lower(), AMBER_D),
            (f"${p.get('mark_price', 0):,.2f}", DIM),
            (f"${p.get('spot_price', 0):,.2f}", DIM),
            (f"{bps:+.0f}bps", bps_fg),
            (f"{p.get('basis_apr', 0):.0f}%", bps_fg),
        ])
    repaint(rows)


# ─── extracted from launcher.App._arb_paint_spot (Fase 3) ───

def paint_spot(app, spot):
    """Paint the spot tab repaint callback with filter applied.

    Extracted from launcher.App._arb_paint_spot in Fase 3 refactor.
    """
    repaint = getattr(app, "_arb_spot_repaint", None)
    if repaint is None:
        return
    # Spot spreads have bps but no APR; apply a minimum-bps tripwire via
    # the risk filter as a loose proxy — HIGH = =3bps, MED = =8, LOW = =15.
    state = app._arb_filter_state()
    risk_max = state.get("risk_max", "HIGH")
    thresholds = {"HIGH": 3, "MED": 8, "LOW": 15}
    min_bps = thresholds.get(risk_max, 3)
    filtered_list = [p for p in (spot or [])
                     if float(p.get("spread_bps", 0) or 0) >= min_bps][:20]
    app._arb_spot_selected = filtered_list
    rows = []
    for i, p in enumerate(filtered_list, 1):
        bps = p.get("spread_bps", 0)
        bps_fg = GREEN if bps >= 15 else (AMBER if bps >= 8 else DIM)
        rows.append([
            (f"{i:>2}", DIM),
            (p.get("symbol", "—")[:7], WHITE),
            (p.get("venue_a", "—")[:9].lower(), AMBER_D),
            (p.get("venue_b", "—")[:9].lower(), AMBER_D),
            (f"${p.get('price_a', 0):,.4f}", DIM),
            (f"${p.get('price_b', 0):,.4f}", DIM),
            (f"{bps:.1f}bps", bps_fg),
        ])
    repaint(rows)


# ─── extracted from launcher.App._arb_basis_screen (Fase 3) ───

def basis_screen(app):
    """Redirect: old basis screen → BASIS tab of the unified desk.

    Extracted from launcher.App._arb_basis_screen in Fase 3 refactor.
    """
    app._arbitrage_hub(tab="basis")


# ─── extracted from launcher.App._arb_basis_screen_legacy (Fase 3) ───

def basis_screen_legacy(app):
    """Spot-perp basis trade screen — shows basis opportunities.

    Extracted from launcher.App._arb_basis_screen_legacy in Fase 3 refactor.
    """
    app._clr(); app._clear_kb()
    app.history.append("_arbitrage_hub")
    app.h_path.configure(text="> ARBITRAGE > BASIS TRADE")
    app.h_stat.configure(text="SCANNING…", fg=AMBER_D)
    app.f_lbl.configure(text="R refresh  |  ESC back")

    app._kb("<Escape>", lambda: app._arbitrage_hub())
    app._kb("<Key-r>", lambda: app._arb_basis_screen())
    app._bind_global_nav()

    outer = tk.Frame(app.main, bg=BG)
    outer.pack(fill="both", expand=True, padx=24, pady=12)

    tk.Label(outer, text="BASIS TRADE", font=(FONT, 10, "bold"),
             fg=AMBER, bg=BG).pack(anchor="center")
    tk.Label(outer, text="spot-perp basis  ·  buy spot, short perp",
             font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="center", pady=(1, 4))
    tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(4, 4))

    # Table
    cols = [("#", 3, "e"), ("SYMBOL", 8, "w"), ("PERP", 10, "w"),
            ("SPOT", 10, "w"), ("MARK", 10, "e"), ("SPOT$", 10, "e"),
            ("BASIS", 8, "e"), ("APR", 8, "e")]
    hrow = tk.Frame(outer, bg=BG); hrow.pack(fill="x")
    for label, w, anchor in cols:
        tk.Label(hrow, text=label, font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG, width=w, anchor=anchor).pack(side="left")
    tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(1, 2))

    inner = tk.Frame(outer, bg=BG)
    inner.pack(fill="both", expand=True)

    # Fetch basis pairs in background
    import threading
    def _worker():
        try:
            from core.ui.funding_scanner import FundingScanner
            scanner = getattr(app, "_funding_scanner", None)
            if scanner is None:
                scanner = FundingScanner()
                app._funding_scanner = scanner
            scanner.scan()
            scanner.scan_spot()
            pairs = scanner.basis_pairs(min_basis_bps=5)[:20]
            app._ui_call_soon(lambda: app._arb_basis_paint(inner, cols, pairs))
        except Exception as e:
            app._ui_call_soon(lambda: tk.Label(inner,
                text=f"  scan failed: {e}", font=(FONT, 8), fg=RED, bg=BG).pack())
    threading.Thread(target=_worker, daemon=True).start()


# ─── extracted from launcher.App._arb_basis_paint (Fase 3) ───

@timed_legacy_switch("arb_basis")
def basis_paint(app, inner, cols, pairs):
    """Paint legacy basis screen rows.

    Extracted from launcher.App._arb_basis_paint in Fase 3 refactor.
    """
    for w in inner.winfo_children():
        w.destroy()
    try:
        app.h_stat.configure(text=f"{len(pairs)} BASIS", fg=AMBER)
    except Exception:
        pass
    if not pairs:
        tk.Label(inner, text="  — no basis opportunities above 5bps —",
                 font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)
        return
    for i, p in enumerate(pairs, 1):
        bg = BG if i % 2 == 1 else BG2
        rf = tk.Frame(inner, bg=bg); rf.pack(fill="x")
        basis_fg = GREEN if abs(p["basis_bps"]) >= 20 else (AMBER if abs(p["basis_bps"]) >= 10 else DIM)
        cells = [
            (f"{i:>3}", DIM), (p["symbol"], WHITE),
            (p["venue_perp"], AMBER_D), (p["venue_spot"], AMBER_D),
            (f"${p['mark_price']:,.2f}", DIM),
            (f"${p['spot_price']:,.2f}", DIM),
            (f"{p['basis_bps']:+.0f}bps", basis_fg),
            (f"{p['basis_apr']:.0f}%", basis_fg),
        ]
        for (txt, fg), (_, w, anchor) in zip(cells, cols):
            tk.Label(rf, text=txt, font=(FONT, 8), fg=fg, bg=bg,
                     width=w, anchor=anchor).pack(side="left")


# ─── extracted from launcher.App._arb_spot_screen (Fase 3) ───

def spot_screen(app):
    """Redirect: old spot screen → SPOT tab of the unified desk.

    Extracted from launcher.App._arb_spot_screen in Fase 3 refactor.
    """
    app._arbitrage_hub(tab="spot")


# ─── extracted from launcher.App._arb_spot_screen_legacy (Fase 3) ───

def spot_screen_legacy(app):
    """Spot-spot spread screen — cross-venue spot price divergence.

    Extracted from launcher.App._arb_spot_screen_legacy in Fase 3 refactor.
    """
    app._clr(); app._clear_kb()
    app.history.append("_arbitrage_hub")
    app.h_path.configure(text="> ARBITRAGE > SPOT ↔ SPOT")
    app.h_stat.configure(text="SCANNING…", fg=AMBER_D)
    app.f_lbl.configure(text="R refresh  |  ESC back")

    app._kb("<Escape>", lambda: app._arbitrage_hub())
    app._kb("<Key-r>", lambda: app._arb_spot_screen())
    app._bind_global_nav()

    outer = tk.Frame(app.main, bg=BG)
    outer.pack(fill="both", expand=True, padx=24, pady=12)

    tk.Label(outer, text="SPOT SPREAD", font=(FONT, 10, "bold"),
             fg=AMBER, bg=BG).pack(anchor="center")
    tk.Label(outer, text="cross-venue spot price divergence",
             font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="center", pady=(1, 4))
    tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(4, 4))

    cols = [("#", 3, "e"), ("SYMBOL", 8, "w"), ("VENUE A", 10, "w"),
            ("VENUE B", 10, "w"), ("PRICE A", 12, "e"), ("PRICE B", 12, "e"),
            ("SPREAD", 10, "e")]
    hrow = tk.Frame(outer, bg=BG); hrow.pack(fill="x")
    for label, w, anchor in cols:
        tk.Label(hrow, text=label, font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG, width=w, anchor=anchor).pack(side="left")
    tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(1, 2))

    inner = tk.Frame(outer, bg=BG)
    inner.pack(fill="both", expand=True)

    import threading
    def _worker():
        try:
            from core.ui.funding_scanner import FundingScanner
            scanner = getattr(app, "_funding_scanner", None)
            if scanner is None:
                scanner = FundingScanner()
                app._funding_scanner = scanner
            scanner.scan_spot()
            pairs = scanner.spot_arb_pairs(min_spread_bps=3)[:20]
            app._ui_call_soon(lambda: app._arb_spot_paint(inner, cols, pairs))
        except Exception as e:
            app._ui_call_soon(lambda: tk.Label(inner,
                text=f"  scan failed: {e}", font=(FONT, 8), fg=RED, bg=BG).pack())
    threading.Thread(target=_worker, daemon=True).start()


# ─── extracted from launcher.App._arb_spot_paint (Fase 3) ───

@timed_legacy_switch("arb_spot")
def spot_paint(app, inner, cols, pairs):
    """Paint legacy spot spread screen rows.

    Extracted from launcher.App._arb_spot_paint in Fase 3 refactor.
    """
    for w in inner.winfo_children():
        w.destroy()
    try:
        app.h_stat.configure(text=f"{len(pairs)} SPREADS", fg=AMBER)
    except Exception:
        pass
    if not pairs:
        tk.Label(inner, text="  — no spot spreads above 3bps —",
                 font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)
        return
    for i, p in enumerate(pairs, 1):
        bg = BG if i % 2 == 1 else BG2
        rf = tk.Frame(inner, bg=bg); rf.pack(fill="x")
        spread_fg = GREEN if p["spread_bps"] >= 15 else (AMBER if p["spread_bps"] >= 8 else DIM)
        cells = [
            (f"{i:>3}", DIM), (p["symbol"], WHITE),
            (p["venue_a"], AMBER_D), (p["venue_b"], AMBER_D),
            (f"${p['price_a']:,.4f}", DIM), (f"${p['price_b']:,.4f}", DIM),
            (f"{p['spread_bps']:.1f}bps", spread_fg),
        ]
        for (txt, fg), (_, w, anchor) in zip(cells, cols):
            tk.Label(rf, text=txt, font=(FONT, 8), fg=fg, bg=bg,
                     width=w, anchor=anchor).pack(side="left")
