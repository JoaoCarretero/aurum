"""Home dashboard tab — connections, accounts, engines.

Extracted from launcher.App._dash_home_render. Same shape: render(app)
repaints the HOME tab of the main dashboard in place, then re-schedules
the next 10s tick via app.after.
"""
from __future__ import annotations

from datetime import datetime
import threading
import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D,
    BG, BORDER,
    DIM, DIM2, FONT,
    GREEN, PANEL, RED, WHITE,
)

# _get_conn lives in launcher (__main__ when run normally). We access it via
# sys.modules to avoid the __main__-vs-launcher double-import problem.
import sys as _sys


def _get_conn():
    main = _sys.modules.get("__main__") or _sys.modules.get("launcher")
    return main._get_conn()


def render(app):
    """Repaint the HOME tab of the dashboard.

    Reads snapshot from app._dash_home_snap (populated by the dashboard's
    background worker) and refreshes three panels:
      - CONNECTIONS (Binance Futures latency + public-API badges)
      - ACCOUNTS (paper/testnet/demo/live rows with EDIT/OPEN/CONFIG actions)
      - ENGINES (live process list, max 6 rows)

    Then updates app.h_stat (ONLINE/OFFLINE) and re-arms the next tick.
    """
    if not getattr(app, "_dash_alive", False):
        return
    if getattr(app, "_dash_tab", "home") != "home":
        return

    snap = getattr(app, "_dash_home_snap", {}) or {}
    latency = snap.get("latency")
    procs = snap.get("procs") or []
    has_keys = snap.get("has_keys") or {}
    paper_state = snap.get("paper") or {}

    # -- clock --
    clock_l = app._dash_widgets.get(("home_clock",))
    if clock_l:
        clock_l.configure(text=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

    # -- CONNECTIONS panel --
    conn = app._dash_widgets.get(("home_conn",))
    if conn:
        for w in conn.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        # Binance Futures (the one we actively ping)
        rows = [
            ("BINANCE FUTURES", latency is not None,
             f"{int(latency)}ms" if latency is not None else "offline"),
            ("FEAR & GREED API", True, "public"),
            ("BINANCE PUBLIC", True, "public"),
        ]
        for name, ok, detail in rows:
            r = tk.Frame(conn, bg=PANEL)
            r.pack(fill="x", pady=1)
            tk.Label(r, text="●" if ok else "○",
                     font=(FONT, 10, "bold"),
                     fg=GREEN if ok else RED, bg=PANEL,
                     width=3).pack(side="left")
            tk.Label(r, text=name, font=(FONT, 8, "bold"),
                     fg=WHITE if ok else DIM, bg=PANEL,
                     width=20, anchor="w").pack(side="left")
            tk.Label(r, text=detail, font=(FONT, 8),
                     fg=DIM if ok else DIM2, bg=PANEL,
                     anchor="w").pack(side="left", padx=(4, 0))

    # -- ACCOUNTS panel (clickable rows + action buttons) --
    accs = app._dash_widgets.get(("home_accs",))
    if accs:
        for w in accs.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        pm = app._get_portfolio_monitor()
        account_defs = [
            ("paper", "PAPER", AMBER_D),
            ("testnet", "TESTNET", GREEN),
            ("demo", "DEMO", AMBER),
            ("live", "LIVE", RED),
        ]
        for acc_id, label, color in account_defs:
            if acc_id == "paper":
                is_on = True
                detail = f"${paper_state.get('current_balance', 0):,.2f}"
                sub = f"trades {len(paper_state.get('trades') or [])}"
                action = "EDIT"
            else:
                is_on = has_keys.get(acc_id, False)
                if is_on:
                    cached = pm.get_cached(acc_id) or {}
                    eq = cached.get("equity")
                    detail = f"${eq:,.2f}" if eq is not None else "— syncing"
                    sub = "keys ok"
                else:
                    detail = "no keys"
                    sub = ""
                action = "OPEN" if is_on else "CONFIG"

            r = tk.Frame(accs, bg=PANEL)
            r.pack(fill="x", pady=2)
            tk.Label(r, text="●" if is_on else "○",
                     font=(FONT, 10, "bold"),
                     fg=color if is_on else DIM2, bg=PANEL,
                     width=3).pack(side="left")
            tk.Label(r, text=label, font=(FONT, 9, "bold"),
                     fg=WHITE if is_on else DIM, bg=PANEL,
                     width=10, anchor="w").pack(side="left")
            tk.Label(r, text=detail, font=(FONT, 9, "bold"),
                     fg=color if is_on else DIM, bg=PANEL,
                     width=16, anchor="w").pack(side="left")
            tk.Label(r, text=sub, font=(FONT, 7),
                     fg=DIM2, bg=PANEL, anchor="w").pack(side="left")

            # Action button (right)
            btn = tk.Label(r, text=f" {action} ",
                           font=(FONT, 7, "bold"),
                           fg=BG, bg=color if is_on else DIM2,
                           cursor="hand2", padx=6, pady=2)
            btn.pack(side="right", padx=(0, 4))

            def _act(_e=None, a=acc_id, on=is_on):
                if a == "paper":
                    app._dash_paper_edit_dialog()
                elif on:
                    app._dash_portfolio_account = a
                    app._dash_render_tab("portfolio")
                else:
                    # No keys — jump to settings
                    app._dash_alive = False
                    app._config()

            for w in (r, btn):
                w.bind("<Button-1>", _act)
                w.bind("<Enter>", lambda e, b=btn: b.configure(bg=AMBER_B))
                w.bind("<Leave>", lambda e, b=btn, c=color, on=is_on:
                       b.configure(bg=c if on else DIM2))

    # -- ENGINES panel --
    eng = app._dash_widgets.get(("home_engines",))
    if eng:
        for w in eng.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        alive = [p for p in procs if p.get("alive")]
        summary = tk.Frame(eng, bg=PANEL)
        summary.pack(fill="x", pady=(0, 2))
        tk.Label(summary,
                 text=f"{len(alive)} running  ·  {len(procs) - len(alive)} finished",
                 font=(FONT, 7), fg=DIM, bg=PANEL,
                 anchor="w").pack(side="left")

        if not alive:
            tk.Label(eng, text="○ no engines running",
                     font=(FONT, 8), fg=DIM, bg=PANEL,
                     anchor="w").pack(fill="x", pady=2)
            tk.Label(eng, text="go to PORTFOLIO (3) or COCKPIT (6) to start",
                     font=(FONT, 7), fg=DIM2, bg=PANEL,
                     anchor="w").pack(fill="x")
        else:
            for p in alive[:6]:
                eng_name = str(p.get("engine", "?")).upper()
                pid = p.get("pid", "?")
                started = str(p.get("started", ""))[:19].replace("T", " ")
                r = tk.Frame(eng, bg=PANEL)
                r.pack(fill="x", pady=1)
                tk.Label(r, text="●", font=(FONT, 10, "bold"),
                         fg=GREEN, bg=PANEL, width=3).pack(side="left")
                tk.Label(r, text=eng_name, font=(FONT, 8, "bold"),
                         fg=AMBER, bg=PANEL, width=14,
                         anchor="w").pack(side="left")
                tk.Label(r, text=f"PID {pid}", font=(FONT, 7),
                         fg=DIM, bg=PANEL, width=10,
                         anchor="w").pack(side="left")
                tk.Label(r, text=started, font=(FONT, 7),
                         fg=DIM2, bg=PANEL,
                         anchor="w").pack(side="left")

    # Header status
    if latency is not None:
        app.h_stat.configure(text="ONLINE", fg=GREEN)
    else:
        app.h_stat.configure(text="OFFLINE", fg=RED)

    # Reschedule — HOME refresh is lightweight, 10s is fine
    if getattr(app, "_dash_alive", False) and app._dash_tab == "home":
        aid = getattr(app, "_dash_after_id", None)
        if aid:
            try:
                app.after_cancel(aid)
            except Exception:
                pass
        app._dash_after_id = app.after(10000, app._dash_tick_refresh)


def build_home_tab(app, parent):
    """CS 1.6 style HOME: connection status + account management + engines.

    No heavy aggregations — only what's immediately actionable.
    Renders instantly with cached state; background refresh is lightweight.

    Extracted from launcher.App in Fase 3 refactor.
    """
    wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=14, pady=8)

    # -- HUD header --
    hdr = tk.Frame(wrap, bg=BG); hdr.pack(fill="x")
    tk.Label(hdr, text="[ HOME ]", font=(FONT, 9, "bold"),
             fg=AMBER, bg=BG).pack(side="left")
    tk.Label(hdr, text="personal control panel",
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=(8, 0))
    clock_l = tk.Label(hdr, text="", font=(FONT, 7), fg=DIM2, bg=BG)
    clock_l.pack(side="right")
    app._dash_widgets[("home_clock",)] = clock_l
    tk.Frame(wrap, bg=AMBER_D, height=1).pack(fill="x", pady=(2, 8))

    # -- CONNECTIONS box --
    def box(title, parent_):
        f = tk.Frame(parent_, bg=PANEL,
                     highlightbackground=BORDER, highlightthickness=1)
        tk.Label(f, text=f" [ {title} ] ",
                 font=(FONT, 7, "bold"), fg=BG, bg=AMBER,
                 padx=6, pady=2).pack(side="top", anchor="nw", padx=6, pady=(6, 2))
        return f

    conn_box = box("CONNECTIONS", wrap)
    conn_box.pack(fill="x", pady=(0, 6))
    conn_inner = tk.Frame(conn_box, bg=PANEL)
    conn_inner.pack(fill="x", padx=10, pady=(0, 8))
    app._dash_widgets[("home_conn",)] = conn_inner

    # -- ACCOUNTS box --
    acc_box = box("ACCOUNTS", wrap)
    acc_box.pack(fill="x", pady=(0, 6))
    acc_inner = tk.Frame(acc_box, bg=PANEL)
    acc_inner.pack(fill="x", padx=10, pady=(0, 8))
    app._dash_widgets[("home_accs",)] = acc_inner

    # -- ENGINES box --
    eng_box = box("RUNNING ENGINES", wrap)
    eng_box.pack(fill="x", pady=(0, 6))
    eng_inner = tk.Frame(eng_box, bg=PANEL)
    eng_inner.pack(fill="x", padx=10, pady=(0, 8))
    app._dash_widgets[("home_engines",)] = eng_inner

    app.f_lbl.configure(
        text="HOME · connections + accounts + engines · "
             "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit · R refresh"
    )

    # Show a brief "connecting..." placeholder inside each panel until the
    # first fetch completes and populates real data. Avoids a blank flash
    # on tab switch.
    for key in ("home_conn", "home_accs", "home_engines"):
        inner = app._dash_widgets.get((key,))
        if inner is not None:
            tk.Label(inner, text="  connecting...",
                     font=(FONT, 8), fg=DIM2, bg=PANEL,
                     anchor="w").pack(fill="x", pady=2)
    # First real render comes from _dash_home_fetch_async which is
    # invoked by _dash_render_tab right after this build method returns.



def home_fetch_async(app):
    """Lightweight background refresh: only ping exchange + list_procs.

    Does NOT call PortfolioMonitor.refresh for live accounts (too slow) —
    only loads the paper state locally, which is instant.

    Extracted from launcher.App in Fase 3 refactor.
    """
    if not getattr(app, "_dash_alive", False):
        return

    def worker():
        snap: dict = {}
        # Paper state: local file read — instant
        try:
            from core.ui.portfolio_monitor import PortfolioMonitor
            snap["paper"] = PortfolioMonitor.paper_state_load()
        except Exception:
            snap["paper"] = None
        # Exchange latency
        try:
            snap["latency"] = _get_conn().ping("binance_futures")
        except Exception:
            snap["latency"] = None
        # Running engines
        try:
            from core.ops.proc import list_procs
            snap["procs"] = list_procs()
        except Exception:
            snap["procs"] = []
        # Check which accounts have keys (instant — reads keys.json)
        try:
            pm = app._get_portfolio_monitor()
            snap["has_keys"] = {m: pm.has_keys(m)
                                for m in ("testnet", "demo", "live")}
        except Exception:
            snap["has_keys"] = {}

        app._dash_home_snap = snap
        if getattr(app, "_dash_alive", False):
            try: app.after(0, app._dash_home_render)
            except Exception: pass

    threading.Thread(target=worker, daemon=True).start()

