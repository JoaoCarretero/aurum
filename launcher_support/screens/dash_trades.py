"""Trades dashboard tab — paginated filtered trade log.

Extracted from launcher.App._dash_trades_render. Completes the dashboard
trio (home / portfolio / trades). Same shape: render(app) repaints the
TRADES tab in place and re-schedules the next 30s tick through
app.after.
"""
from __future__ import annotations

import threading
import tkinter as tk

from core.ui.ui_palette import (
    AMBER,
    BG3,
    DIM, DIM2, FONT,
    GREEN, PANEL, RED, WHITE,
)


def render(app):
    """Repaint the TRADES tab of the dashboard.

    Reads the cached portfolio snapshot via app._get_portfolio_monitor()
    for the selected mode (paper/demo/testnet/live). Applies the ALL/WIN/
    LOSS filter from app._dash_trades_filter, paginates at 18 rows/page
    (page index held in app._dash_trades_page), and renders the table
    into the (trades_table,) widget registered by the dashboard build.

    Footer + filter-bar labels (trades_page / trades_stats) are refreshed
    from the same slice, and the status bar carries mode + total.
    """
    if not getattr(app, "_dash_alive", False):
        return
    if getattr(app, "_dash_tab", "market") != "trades":
        return
    tbl = app._dash_widgets.get(("trades_table",))
    page_lbl = app._dash_widgets.get(("trades_page",))
    stats_lbl = app._dash_widgets.get(("trades_stats",))
    if tbl is None:
        return
    try:
        if not tbl.winfo_exists():
            return
    except Exception:
        return

    for w in tbl.winfo_children():
        try:
            w.destroy()
        except Exception:
            pass

    pm = app._get_portfolio_monitor()
    mode = getattr(app, "_dash_portfolio_account", "paper")
    cached = pm.get_cached(mode)
    if cached is None:
        # Background refresh, render placeholder
        threading.Thread(target=lambda m=mode: pm.refresh(m), daemon=True).start()
        tk.Label(tbl, text="Loading…", font=(FONT, 9), fg=DIM,
                 bg=PANEL).pack(pady=20)
        return

    trades_raw = cached.get("trades") or cached.get("recent_trades") or []
    trades = []
    for t in trades_raw:
        res = t.get("result")
        if res not in ("WIN", "LOSS"):
            # Live API trades may not have result; derive sign-of-pnl as proxy
            pnl = float(t.get("pnl", 0) or 0)
            res = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else None
        t = dict(t)
        t["_result"] = res or "?"
        trades.append(t)

    # Apply filter
    f = app._dash_trades_filter["result"]
    if f == "win":
        trades = [t for t in trades if t["_result"] == "WIN"]
    elif f == "loss":
        trades = [t for t in trades if t["_result"] == "LOSS"]

    # Pagination
    per_page = 18
    total = len(trades)
    pages = max(1, (total + per_page - 1) // per_page)
    if app._dash_trades_page >= pages:
        app._dash_trades_page = max(0, pages - 1)
    page = app._dash_trades_page
    slice_ = trades[page * per_page:(page + 1) * per_page]

    # Header row
    hdr = tk.Frame(tbl, bg=BG3)
    hdr.pack(fill="x")
    cols = [("#", 4), ("SYMBOL", 12), ("SIDE", 6), ("RSLT", 5),
            ("PnL", 12), ("R-MULT", 8), ("SCORE", 7), ("TIME", 10)]
    for label, w in cols:
        tk.Label(hdr, text=label, font=(FONT, 7, "bold"),
                 fg=AMBER, bg=BG3, width=w, anchor="w",
                 padx=4, pady=3).pack(side="left")
    tk.Frame(tbl, bg=DIM2, height=1).pack(fill="x")

    for i, t in enumerate(slice_):
        row = tk.Frame(tbl, bg=PANEL)
        row.pack(fill="x")
        sym = (t.get("symbol") or "?").replace("USDT", "")
        side = t.get("direction") or t.get("side") or "?"
        if isinstance(side, str):
            side = "LONG" if side.upper() in ("BULLISH", "BUY", "LONG") else "SHORT"
        res = t["_result"]
        pnl = float(t.get("pnl", 0) or 0)
        pnl_col = GREEN if pnl >= 0 else RED
        entry = float(t.get("entry", 0) or 0)
        stop = float(t.get("stop", 0) or 0)
        exit_p = float(t.get("exit_p", t.get("exit", 0)) or 0)
        risk = abs(entry - stop)
        if risk > 0:
            move = (exit_p - entry) if side == "LONG" else (entry - exit_p)
            rmult = move / risk
        else:
            rmult = 0.0
        score = float(t.get("score", 0) or 0)
        tstr = str(t.get("time", t.get("timestamp", "")))[:10]

        vals = [
            (str(page * per_page + i + 1), DIM),
            (sym, AMBER),
            (side, WHITE),
            (res, GREEN if res == "WIN" else RED),
            (f"{'+' if pnl >= 0 else ''}${pnl:,.2f}", pnl_col),
            (f"{rmult:+.2f}R", GREEN if rmult >= 0 else RED),
            (f"{score:.2f}" if score else "—", DIM),
            (tstr, DIM),
        ]
        for (val, col), (_, w) in zip(vals, cols):
            tk.Label(row, text=val, font=(FONT, 8),
                     fg=col, bg=PANEL, width=w, anchor="w",
                     padx=4, pady=2).pack(side="left")

    if not slice_:
        # Context-aware empty state so the user knows WHY the table is empty.
        if total == 0:
            if mode == "paper":
                empty_msg = ("paper account has no trades yet\n"
                             "trades placed in paper mode will appear here")
            elif cached.get("status") == "no_keys":
                empty_msg = (f"{mode.upper()} account has no API keys\n"
                             "configure in SETTINGS > API KEYS")
            else:
                empty_msg = f"no trades on {mode.upper()} account (last 50)"
        else:
            empty_msg = f"no trades match filter '{f.upper()}'\n(total: {total})"
        tk.Label(tbl, text=empty_msg, font=(FONT, 8),
                 fg=DIM, bg=PANEL, justify="center").pack(pady=14)

    if page_lbl:
        page_lbl.configure(text=f"Página {page + 1}/{pages}")
    if stats_lbl:
        wins = sum(1 for t in trades if t["_result"] == "WIN")
        wr = (wins / total * 100) if total else 0
        tot_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
        stats_lbl.configure(
            text=f"Total: {total}  WR {wr:.1f}%  PnL ${tot_pnl:,.0f}")

    app.f_lbl.configure(
        text=f"TRADES · {mode.upper()} · {total} trades · "
             f"1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit")

    if getattr(app, "_dash_alive", False) and app._dash_tab == "trades":
        aid = getattr(app, "_dash_after_id", None)
        if aid:
            try:
                app.after_cancel(aid)
            except Exception:
                pass
        app._dash_after_id = app.after(30000, app._dash_tick_refresh)
