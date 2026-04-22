"""Portfolio dashboard tab — account KPIs, positions, equity, trades, engines.

Extracted from launcher.App._dash_portfolio_render. Same shape: render(app)
refreshes the portfolio-details widget in place, re-schedules the next
15s tick through app.after, and calls back into App helpers for the
portfolio monitor and the paper-edit dialog.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D,
    BG, BORDER,
    DIM, DIM2, FONT,
    GREEN, PANEL, RED, WHITE,
)


def render(app):
    """Repaint the PORTFOLIO tab of the dashboard.

    Pulls cached snapshot from app._get_portfolio_monitor() for the
    selected mode (paper/demo/testnet/live), then rebuilds:
      - Header card (balance, equity, unrealized, today, margin)
      - Open positions table
      - Equity-curve canvas (paper account or income-based fallback)
      - Last 5 trades
      - Rolling metrics (paper summary)
      - Running engines panel with inline STOP buttons
      - Footer summary + 15s re-schedule
    """
    if not getattr(app, "_dash_alive", False):
        return
    if getattr(app, "_dash_tab", "market") != "portfolio":
        return

    pm = app._get_portfolio_monitor()
    mode = getattr(app, "_dash_portfolio_account", "paper")
    data = pm.get_cached(mode) or {}
    details = app._dash_widgets.get(("portfolio_details",))
    if details is None:
        return
    try:
        if not details.winfo_exists():
            return
    except Exception:
        return

    for w in details.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass

    app._dash_portfolio_repaint_account_btns()

    status = data.get("status", pm.status(mode))

    # Empty / no-keys placeholder
    if status == "no_keys":
        box = tk.Frame(details, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1)
        box.pack(pady=24, padx=20, ipadx=24, ipady=20)
        tk.Label(box, text=mode.upper(), font=(FONT, 14, "bold"),
                 fg=AMBER, bg=PANEL).pack(pady=(0, 10))
        tk.Label(box, text="○ Sem API keys configuradas",
                 font=(FONT, 9), fg=DIM, bg=PANEL).pack(pady=2)
        tk.Label(box, text="Configura em:", font=(FONT, 8),
                 fg=DIM, bg=PANEL).pack(pady=(8, 2))
        tk.Label(box, text=f"SETTINGS > API KEYS > {mode.upper()}",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL).pack(pady=(0, 10))
        btn = tk.Label(box, text=" IR PARA SETTINGS ",
                       font=(FONT, 9, "bold"), fg=BG, bg=AMBER,
                       cursor="hand2", padx=12, pady=4)
        btn.pack(pady=(8, 0))
        btn.bind("<Button-1>", lambda e: app._config())
        app._dash_after_id = app.after(15000, app._dash_tick_refresh)
        return

    # === Header card ===
    head = tk.Frame(details, bg=PANEL,
                    highlightbackground=BORDER, highlightthickness=1)
    head.pack(fill="x", pady=(0, 8))
    head_title = " PAPER · simulated " if mode == "paper" else f" {mode.upper()} · Binance Futures "
    tk.Label(head, text=head_title,
             font=(FONT, 8, "bold"), fg=BG, bg=AMBER).pack(side="left", padx=8, pady=4)

    # Paper-only: EDIT button opens editable-state dialog
    if mode == "paper":
        edit_btn = tk.Label(head, text=" EDIT ",
                            font=(FONT, 7, "bold"),
                            fg=BG, bg=AMBER_D, cursor="hand2",
                            padx=6, pady=2)
        edit_btn.pack(side="right", padx=(0, 8), pady=4)
        edit_btn.bind("<Button-1>", lambda e: app._dash_paper_edit_dialog())
        edit_btn.bind("<Enter>", lambda e, b=edit_btn: b.configure(bg=AMBER))
        edit_btn.bind("<Leave>", lambda e, b=edit_btn: b.configure(bg=AMBER_D))
        # Show last-modified timestamp
        lm = data.get("last_modified", "")
        if lm:
            try:
                lm = lm.split("T")[0] + "  " + lm.split("T")[1][:8]
            except Exception:
                pass
            tk.Label(head, text=f"modified: {lm}",
                     font=(FONT, 7), fg=DIM2, bg=PANEL,
                     anchor="e").pack(side="right", padx=(0, 8))

    balance = float(data.get("balance", 0) or 0)
    equity = float(data.get("equity", 0) or 0)
    unr = float(data.get("unrealized_pnl", 0) or 0)
    today = float(data.get("today_pnl", 0) or 0)
    m_used = float(data.get("margin_used", 0) or 0)
    m_free = float(data.get("margin_free", 0) or 0)
    unr_color = GREEN if unr >= 0 else RED
    today_color = GREEN if today >= 0 else RED
    margin_pct = (m_used / equity * 100) if equity > 0 else 0

    grid = tk.Frame(head, bg=PANEL)
    grid.pack(fill="x", padx=12, pady=8)
    cells = [
        ("Balance", f"${balance:,.2f}", WHITE),
        ("Equity", f"${equity:,.2f}", WHITE),
        ("Unreal", f"{'+'  if unr >= 0 else ''}${unr:,.2f}", unr_color),
        ("Today", f"{'+'  if today >= 0 else ''}${today:,.2f}", today_color),
        ("Margin", f"${m_used:,.0f}  ({margin_pct:.0f}%)", AMBER_D),
        ("Free", f"${m_free:,.2f}", DIM),
    ]
    for i, (lbl, val, col) in enumerate(cells):
        cell = tk.Frame(grid, bg=PANEL)
        cell.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 18), pady=2)
        tk.Label(cell, text=lbl, font=(FONT, 7), fg=DIM, bg=PANEL,
                 anchor="w").pack(anchor="w")
        tk.Label(cell, text=val, font=(FONT, 10, "bold"),
                 fg=col, bg=PANEL, anchor="w").pack(anchor="w")

    # === Open positions ===
    positions = data.get("positions") or []
    pos_box = tk.Frame(details, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1)
    pos_box.pack(fill="x", pady=(0, 8))
    tk.Label(pos_box, text=f" POSIÇÕES ABERTAS ({len(positions)}) ",
             font=(FONT, 8, "bold"), fg=AMBER, bg=PANEL,
             anchor="w").pack(fill="x", padx=8, pady=(6, 2))
    tk.Frame(pos_box, bg=DIM2, height=1).pack(fill="x", padx=8)
    if not positions:
        tk.Label(pos_box, text="  (no open positions)",
                 font=(FONT, 8), fg=DIM, bg=PANEL,
                 anchor="w").pack(fill="x", padx=8, pady=4)
    else:
        for p in positions[:8]:
            pl = float(p.get("pnl", 0) or 0)
            pl_col = GREEN if pl >= 0 else RED
            row = tk.Frame(pos_box, bg=PANEL)
            row.pack(fill="x", padx=8, pady=1)
            tk.Label(row, text=p.get("symbol", "?"), font=(FONT, 9, "bold"),
                     fg=AMBER, bg=PANEL, width=12, anchor="w").pack(side="left")
            tk.Label(row, text=p.get("side", "?"), font=(FONT, 8),
                     fg=WHITE, bg=PANEL, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=f"size {p.get('size', 0):.4f}", font=(FONT, 8),
                     fg=DIM, bg=PANEL, width=14, anchor="w").pack(side="left")
            tk.Label(row, text=f"@ {p.get('entry', 0):,.4f}", font=(FONT, 8),
                     fg=DIM, bg=PANEL, width=16, anchor="w").pack(side="left")
            tk.Label(row, text=f"PnL {'+' if pl >= 0 else ''}${pl:,.2f}",
                     font=(FONT, 9, "bold"), fg=pl_col, bg=PANEL,
                     anchor="w").pack(side="left")
        tk.Frame(pos_box, bg=PANEL, height=4).pack()

    # === Equity curve canvas (paper account or income-based) ===
    eq_curve = data.get("equity_curve") or []
    if not eq_curve and data.get("income_7d"):
        # Build a cumulative curve out of income history
        cum = float(data.get("equity", 0) or 0)
        eq_curve = []
        running = 0.0
        for row in data["income_7d"]:
            try:
                running += float(row.get("income", 0) or 0)
                eq_curve.append(round(cum - running, 2))
            except (TypeError, ValueError):
                continue
        eq_curve.reverse()
        if eq_curve:
            eq_curve.append(cum)

    eq_box = tk.Frame(details, bg=PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
    eq_box.pack(fill="x", pady=(0, 8))
    tk.Label(eq_box, text=" EQUITY CURVE ", font=(FONT, 8, "bold"),
             fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=8, pady=(6, 2))
    tk.Frame(eq_box, bg=DIM2, height=1).pack(fill="x", padx=8)
    canvas = tk.Canvas(eq_box, bg=PANEL, height=140,
                       highlightthickness=0, bd=0)
    canvas.pack(fill="x", padx=8, pady=(4, 6))
    canvas.bind("<Configure>",
                lambda e, c=canvas, eq=eq_curve:
                app._dash_draw_equity_canvas(c, eq))

    # === Recent trades ===
    recent = (data.get("recent_trades") or [])[:5]
    rb = tk.Frame(details, bg=PANEL,
                  highlightbackground=BORDER, highlightthickness=1)
    rb.pack(fill="x", pady=(0, 8))
    tk.Label(rb, text=" ÚLTIMOS 5 TRADES ", font=(FONT, 8, "bold"),
             fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=8, pady=(6, 2))
    tk.Frame(rb, bg=DIM2, height=1).pack(fill="x", padx=8)
    if not recent:
        tk.Label(rb, text="  (no trade history)",
                 font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w"
                 ).pack(fill="x", padx=8, pady=4)
    else:
        for i, t in enumerate(recent):
            pnl = float(t.get("pnl", 0) or 0)
            col = GREEN if pnl >= 0 else RED
            sym = t.get("symbol", "?")
            side = t.get("direction") or t.get("side") or t.get("buyer", "?")
            if isinstance(side, bool):
                side = "BUY" if side else "SELL"
            result = t.get("result", "")
            row = tk.Frame(rb, bg=PANEL)
            row.pack(fill="x", padx=8, pady=1)
            tk.Label(row, text=f"#{i + 1}", font=(FONT, 8),
                     fg=DIM, bg=PANEL, width=4).pack(side="left")
            tk.Label(row, text=sym.replace("USDT", ""),
                     font=(FONT, 9, "bold"), fg=AMBER, bg=PANEL,
                     width=8, anchor="w").pack(side="left")
            tk.Label(row, text=str(side)[:5], font=(FONT, 8),
                     fg=WHITE, bg=PANEL, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=str(result), font=(FONT, 8),
                     fg=col, bg=PANEL, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",
                     font=(FONT, 9, "bold"), fg=col, bg=PANEL, width=12,
                     anchor="w").pack(side="left")
        tk.Frame(rb, bg=PANEL, height=4).pack()

    # === Rolling metrics (paper summary if available) ===
    summary = data.get("summary") or {}
    if summary:
        mb = tk.Frame(details, bg=PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
        mb.pack(fill="x", pady=(0, 4))
        tk.Label(mb, text=" MÉTRICAS ", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=8, pady=(6, 2))
        tk.Frame(mb, bg=DIM2, height=1).pack(fill="x", padx=8)
        cells = [
            ("WR", f"{summary.get('win_rate', 0):.1f}%"),
            ("Sharpe", f"{summary.get('sharpe', 0) or 0:.2f}"),
            ("Sortino", f"{summary.get('sortino', 0) or 0:.2f}"),
            ("MaxDD", f"{summary.get('max_dd_pct', 0):.1f}%"),
            ("Trades", str(summary.get('n_trades', 0))),
            ("PnL", f"${summary.get('pnl', 0) or 0:,.2f}"),
        ]
        grid = tk.Frame(mb, bg=PANEL)
        grid.pack(fill="x", padx=12, pady=8)
        for i, (lbl, val) in enumerate(cells):
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=0, column=i, sticky="w", padx=(0, 18))
            tk.Label(cell, text=lbl, font=(FONT, 7), fg=DIM, bg=PANEL,
                     anchor="w").pack(anchor="w")
            tk.Label(cell, text=val, font=(FONT, 9, "bold"),
                     fg=WHITE, bg=PANEL, anchor="w").pack(anchor="w")

    # === RUNNING ENGINES (controls) ===
    try:
        from core.ops.proc import list_procs, stop_proc
        procs = list_procs()
    except Exception:
        procs = []

    eb = tk.Frame(details, bg=PANEL,
                  highlightbackground=BORDER, highlightthickness=1)
    eb.pack(fill="x", pady=(0, 8))

    eb_head = tk.Frame(eb, bg=PANEL)
    eb_head.pack(fill="x", padx=8, pady=(6, 2))
    tk.Label(eb_head, text=f" RUNNING ENGINES ({sum(1 for p in procs if p.get('alive'))}) ",
             font=(FONT, 8, "bold"), fg=AMBER, bg=PANEL,
             anchor="w").pack(side="left")
    start_btn = tk.Label(eb_head, text=" + START NEW ",
                         font=(FONT, 7, "bold"),
                         fg=BG, bg=AMBER, cursor="hand2",
                         padx=6, pady=2)
    start_btn.pack(side="right")

    def _goto_strategies(_e=None):
        app._dash_alive = False
        app._menu("strategies")

    for w in (start_btn,):
        w.bind("<Button-1>", _goto_strategies)
        w.bind("<Enter>", lambda e, b=start_btn: b.configure(bg=AMBER_B))
        w.bind("<Leave>", lambda e, b=start_btn: b.configure(bg=AMBER))
    tk.Frame(eb, bg=DIM2, height=1).pack(fill="x", padx=8)

    engines_known = [
        "backtest", "live", "arb", "newton", "mercurio",
        "thoth", "prometeu", "darwin", "chronos", "multi",
    ]
    seen: dict[str, dict] = {}
    for p in procs:
        seen[p.get("engine", "?")] = p

    any_running = False
    for eng in engines_known:
        info = seen.get(eng)
        is_alive = bool(info and info.get("alive"))
        if not is_alive:
            continue  # skip stopped engines — keep UI clean
        any_running = True

        row = tk.Frame(eb, bg=PANEL)
        row.pack(fill="x", padx=8, pady=2)
        tk.Label(row, text="●", font=(FONT, 9, "bold"),
                 fg=GREEN, bg=PANEL, width=2).pack(side="left")
        tk.Label(row, text=eng.upper(), font=(FONT, 9, "bold"),
                 fg=AMBER, bg=PANEL, width=12,
                 anchor="w").pack(side="left")
        pid = info.get("pid", 0)
        started = str(info.get("started", ""))[:19].replace("T", " ")
        tk.Label(row, text=f"PID {pid}", font=(FONT, 7),
                 fg=DIM, bg=PANEL, width=10,
                 anchor="w").pack(side="left")
        tk.Label(row, text=started, font=(FONT, 7),
                 fg=DIM2, bg=PANEL, anchor="w").pack(side="left", padx=(4, 0))

        stop_l = tk.Label(row, text=" STOP ",
                          font=(FONT, 7, "bold"),
                          fg=BG, bg=RED, cursor="hand2", padx=6)
        stop_l.pack(side="right")

        def _stop(_e=None, p=pid, eng_name=eng):
            try:
                ok = stop_proc(int(p))
            except Exception:
                ok = False
            app.h_stat.configure(
                text=f"{'STOPPED' if ok else 'STOP FAILED'} {eng_name.upper()}",
                fg=GREEN if ok else RED)
            # Re-render portfolio to reflect new proc state
            app.after(600, app._dash_portfolio_render)
        stop_l.bind("<Button-1>", _stop)
        stop_l.bind("<Enter>", lambda e, b=stop_l: b.configure(bg="#ff5050"))
        stop_l.bind("<Leave>", lambda e, b=stop_l: b.configure(bg=RED))

    if not any_running:
        tk.Label(eb, text="  ○ no engines running  ·  click START NEW to launch",
                 font=(FONT, 8), fg=DIM, bg=PANEL,
                 anchor="w").pack(fill="x", padx=8, pady=4)

    # Footer summary
    upd = data.get("ts", "")
    if upd:
        try:
            upd = upd.split("T")[1][:8]
        except Exception:
            pass
    app.f_lbl.configure(
        text=f"PORTFOLIO · {mode.upper()} · upd {upd} · "
             f"1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit"
    )

    # Schedule next refresh
    if getattr(app, "_dash_alive", False) and app._dash_tab == "portfolio":
        aid = getattr(app, "_dash_after_id", None)
        if aid:
            try:
                app.after_cancel(aid)
            except Exception:
                pass
        app._dash_after_id = app.after(15000, app._dash_tick_refresh)
