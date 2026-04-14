"""Macro Brain dashboard panel — renders inside launcher's main frame.

Zero coupling with trade engines. Reads state from macro_brain.persistence
and formats into Bloomberg/HL2 aesthetic panels:

  ┌────────────────────────────────────────────────┐
  │ REGIME        theses stats                     │
  │ current / conf / reason / since                │
  ├──────────────────────┬─────────────────────────┤
  │ ACTIVE THESES        │ OPEN POSITIONS + P&L    │
  │ (table)              │ (table)                 │
  ├──────────────────────┴─────────────────────────┤
  │ RECENT EVENTS (news/sentiment feed)            │
  ├────────────────────────────────────────────────┤
  │ DATA HEALTH    last fetch times + status       │
  ├────────────────────────────────────────────────┤
  │ [ RUN NOW ]  [ STATUS ]  [ REFRESH ]           │
  └────────────────────────────────────────────────┘
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

log = logging.getLogger("macro_brain.dashboard")

# ── PALETTE (match launcher's aesthetic) ─────────────────────
BG      = "#0a0a0a"
PANEL   = "#141414"
BG2     = "#1a1a1a"
BG3     = "#222222"
AMBER   = "#ffa500"
AMBER_D = "#cc8400"
GREEN   = "#30c050"
RED     = "#e03030"
WHITE   = "#e0e0e0"
DIM     = "#707070"
DIM2    = "#3a3a3a"
BORDER  = "#333333"
FONT    = "Consolas"


# ── HELPERS ──────────────────────────────────────────────────

def _section_header(parent, title: str) -> None:
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=(10, 0))
    tk.Frame(row, bg=AMBER, width=3).pack(side="left", fill="y")
    tk.Label(row, text=f" {title} ", font=(FONT, 8, "bold"),
             fg=AMBER, bg=BG, anchor="w", padx=6).pack(side="left", fill="x", expand=True)
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))


def _stat_box(parent, label: str, value: str, color: str = WHITE) -> tk.Frame:
    f = tk.Frame(parent, bg=BG3, padx=10, pady=6)
    tk.Label(f, text=value, font=(FONT, 14, "bold"), fg=color, bg=BG3).pack()
    tk.Label(f, text=label, font=(FONT, 7, "bold"), fg=DIM, bg=BG3).pack()
    return f


def _fmt_ts(ts: str) -> str:
    """ISO timestamp → relative age (e.g. '2h ago', '3d ago')."""
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "")[:19])
    except ValueError:
        return ts[:19]
    delta = datetime.utcnow() - dt
    s = int(delta.total_seconds())
    if s < 60:        return f"{s}s ago"
    if s < 3600:      return f"{s // 60}m ago"
    if s < 86400:     return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


# ── RENDER ───────────────────────────────────────────────────

def render(parent: tk.Widget, app=None) -> None:
    """Render the macro brain dashboard into `parent`.

    `app` is the launcher instance (for nav back etc). Can be None.
    """
    # Lazy imports to avoid cost when dashboard not used
    from macro_brain.persistence.store import (
        active_theses, init_db, latest_regime, open_positions, pnl_summary,
        recent_events,
    )
    init_db()

    # Clear parent
    for w in parent.winfo_children():
        try: w.destroy()
        except Exception: pass

    # Scrollable outer frame
    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True, padx=12, pady=8)

    # ── Header ─────────────────────────────────────────────
    hdr = tk.Frame(outer, bg=BG)
    hdr.pack(fill="x", pady=(0, 4))
    tk.Label(hdr, text=" MACRO BRAIN ", font=(FONT, 10, "bold"),
             fg=BG, bg=AMBER, padx=8, pady=3).pack(side="left")
    tk.Label(hdr, text="  Autonomous CIO · weeks-months horizon · separate book",
             font=(FONT, 8), fg=DIM, bg=BG).pack(side="left", fill="x", expand=True)
    tk.Frame(outer, bg=AMBER_D, height=1).pack(fill="x", pady=(4, 0))

    # ── REGIME ─────────────────────────────────────────────
    _section_header(outer, "CURRENT REGIME")
    regime = latest_regime()
    reg_frame = tk.Frame(outer, bg=BG)
    reg_frame.pack(fill="x")

    if regime:
        regime_name = regime.get("regime", "?").upper()
        conf = regime.get("confidence", 0.0) or 0.0
        regime_color = {
            "RISK_ON":     GREEN,
            "RISK_OFF":    RED,
            "TRANSITION":  AMBER,
            "UNCERTAINTY": DIM,
        }.get(regime_name, WHITE)

        tk.Label(reg_frame, text=regime_name, font=(FONT, 20, "bold"),
                 fg=regime_color, bg=BG).pack(side="left", padx=(10, 20))

        conf_str = f"{conf:.0%}" if isinstance(conf, (int, float)) else "?"
        tk.Label(reg_frame, text=f"confidence {conf_str}", font=(FONT, 10),
                 fg=WHITE, bg=BG).pack(side="left")

        # Progress bar for confidence
        bar_frame = tk.Frame(reg_frame, bg=BG2, width=120, height=10)
        bar_frame.pack(side="left", padx=(10, 10))
        bar_frame.pack_propagate(False)
        fill_w = int(120 * min(1.0, max(0.0, conf)))
        if fill_w > 0:
            tk.Frame(bar_frame, bg=regime_color, width=fill_w, height=10).place(x=0, y=0)

        tk.Label(reg_frame, text=_fmt_ts(regime.get("ts", "")), font=(FONT, 8),
                 fg=DIM, bg=BG).pack(side="left", padx=10)

        reason = regime.get("reason", "") or ""
        if reason:
            tk.Label(outer, text=f"  reason: {reason[:140]}", font=(FONT, 8),
                     fg=DIM, bg=BG, anchor="w").pack(fill="x", padx=10, pady=(4, 0))
    else:
        tk.Label(reg_frame, text="(no regime snapshot yet — run brain --once)",
                 font=(FONT, 10), fg=DIM, bg=BG).pack(pady=10)

    # ── P&L SUMMARY ─────────────────────────────────────────
    _section_header(outer, "MACRO BOOK · P&L")
    pnl = pnl_summary()
    pnl_row = tk.Frame(outer, bg=BG)
    pnl_row.pack(fill="x")
    total = pnl.get("total_pnl", 0.0) or 0.0
    equity = pnl.get("equity", 0.0) or 0.0
    initial = pnl.get("initial", 0.0) or 0.0
    dd_pct = ((initial - equity) / initial * 100) if initial else 0.0

    _stat_box(pnl_row, "EQUITY", f"${equity:,.0f}", AMBER).pack(side="left", padx=4)
    _stat_box(pnl_row, "TOTAL P&L",
              f"${total:+,.0f}", GREEN if total >= 0 else RED).pack(side="left", padx=4)
    _stat_box(pnl_row, "INITIAL", f"${initial:,.0f}", WHITE).pack(side="left", padx=4)
    _stat_box(pnl_row, "DRAWDOWN",
              f"{-dd_pct:+.2f}%" if dd_pct > 0 else "0.00%",
              RED if dd_pct > 0 else GREEN).pack(side="left", padx=4)

    # ── ACTIVE THESES + OPEN POSITIONS (side by side) ─────
    row_split = tk.Frame(outer, bg=BG)
    row_split.pack(fill="x", pady=(10, 0))

    left = tk.Frame(row_split, bg=BG)
    left.pack(side="left", fill="both", expand=True, padx=(0, 4))
    right = tk.Frame(row_split, bg=BG)
    right.pack(side="left", fill="both", expand=True, padx=(4, 0))

    _section_header(left, "ACTIVE THESES")
    theses = active_theses()
    if theses:
        for t in theses[:10]:
            card = tk.Frame(left, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            card.pack(fill="x", pady=2, padx=2)
            hdr2 = tk.Frame(card, bg=PANEL)
            hdr2.pack(fill="x", padx=8, pady=(6, 2))
            side_color = GREEN if t["direction"] == "long" else RED
            tk.Label(hdr2, text=t["direction"].upper(), font=(FONT, 8, "bold"),
                     fg=BG, bg=side_color, padx=4).pack(side="left")
            tk.Label(hdr2, text=f"  {t['asset']}", font=(FONT, 10, "bold"),
                     fg=WHITE, bg=PANEL).pack(side="left")
            tk.Label(hdr2, text=f"conf {t['confidence']:.0%}",
                     font=(FONT, 8), fg=AMBER_D, bg=PANEL).pack(side="right", padx=4)
            tk.Label(hdr2, text=f"{t.get('target_horizon_days', '?')}d",
                     font=(FONT, 8), fg=DIM, bg=PANEL).pack(side="right", padx=4)

            rationale = t.get("rationale", "") or ""
            tk.Label(card, text=rationale[:200], font=(FONT, 8), fg=DIM,
                     bg=PANEL, wraplength=380, justify="left", anchor="w").pack(
                         fill="x", padx=8, pady=(0, 6))
    else:
        tk.Label(left, text="(no active theses)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=20)

    _section_header(right, "OPEN POSITIONS")
    positions = open_positions()
    if positions:
        # Table header
        tk.Label(right, text=f"  {'ASSET':<10} {'SIDE':<6} {'SIZE':>9} {'ENTRY':>10}",
                 font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(fill="x")
        for p in positions[:10]:
            side_color = GREEN if p["side"] == "long" else RED
            row_pos = tk.Frame(right, bg=PANEL, highlightbackground=BORDER,
                              highlightthickness=1)
            row_pos.pack(fill="x", pady=1, padx=2)
            text = (f"  {p['asset']:<10} "
                    f"{p['side'].upper():<6} "
                    f"${p['size_usd']:>7,.0f}  "
                    f"@ {p['entry_price']:>9,.1f}")
            tk.Label(row_pos, text=text, font=(FONT, 9), fg=side_color,
                     bg=PANEL, anchor="w").pack(fill="x", padx=6, pady=3)
    else:
        tk.Label(right, text="(no open positions)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=20)

    # ── RECENT EVENTS (news/sentiment) ─────────────────────
    _section_header(outer, "RECENT EVENTS")
    events = recent_events(limit=8)
    if events:
        for e in events:
            sent = e.get("sentiment") or 0.0
            sent_color = GREEN if sent > 0.2 else (RED if sent < -0.2 else DIM)
            row_ev = tk.Frame(outer, bg=BG)
            row_ev.pack(fill="x", pady=1)
            tk.Label(row_ev, text=f"  {_fmt_ts(e.get('ts', '')):<10}",
                     font=(FONT, 8), fg=DIM, bg=BG, width=12,
                     anchor="w").pack(side="left")
            tk.Label(row_ev, text=f"[{e.get('category','?')[:8]}]",
                     font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG,
                     width=11, anchor="w").pack(side="left")
            tk.Label(row_ev, text=f"{sent:+.2f}", font=(FONT, 8, "bold"),
                     fg=sent_color, bg=BG, width=7, anchor="w").pack(side="left")
            tk.Label(row_ev, text=(e.get("headline") or "")[:90],
                     font=(FONT, 8), fg=WHITE, bg=BG,
                     anchor="w").pack(side="left", fill="x", expand=True)
    else:
        tk.Label(outer, text="  (no events ingested yet)",
                 font=(FONT, 9), fg=DIM, bg=BG).pack(pady=10)

    # ── DATA HEALTH ────────────────────────────────────────
    _section_header(outer, "DATA HEALTH")
    health_path = Path("data/macro/health.json")
    if health_path.exists():
        try:
            h = json.loads(health_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            h = {}
        last_runs = h.get("last_runs", {}) or {}
        if last_runs:
            for job, info in sorted(last_runs.items()):
                ts = info.get("ts", "")
                err = info.get("error")
                row_h = tk.Frame(outer, bg=BG)
                row_h.pack(fill="x", pady=1)
                flag = "FAIL" if err else " OK "
                flag_color = RED if err else GREEN
                tk.Label(row_h, text=f"  [{flag}]", font=(FONT, 8, "bold"),
                         fg=flag_color, bg=BG, width=8,
                         anchor="w").pack(side="left")
                tk.Label(row_h, text=f"{job:<14}", font=(FONT, 8),
                         fg=WHITE, bg=BG, anchor="w").pack(side="left")
                tk.Label(row_h, text=_fmt_ts(ts), font=(FONT, 8),
                         fg=DIM, bg=BG, anchor="w").pack(side="left")
        else:
            tk.Label(outer, text="  (no jobs run yet)", font=(FONT, 9),
                     fg=DIM, bg=BG).pack(pady=6)
    else:
        tk.Label(outer, text="  (health file not found — run brain --once)",
                 font=(FONT, 9), fg=DIM, bg=BG).pack(pady=6)

    # ── ACTIONS ────────────────────────────────────────────
    _section_header(outer, "ACTIONS")
    btn_row = tk.Frame(outer, bg=BG)
    btn_row.pack(pady=6)

    def _run_cycle():
        """Trigger a brain --once cycle in background thread."""
        import threading
        def _work():
            try:
                from macro_brain.brain import run_once
                run_once(force=True)
                # Re-render after completion
                if app is not None:
                    try:
                        app.after(0, lambda: render(parent, app))
                    except Exception:
                        pass
            except Exception as e:
                log.error(f"run_cycle failed: {e}")

        threading.Thread(target=_work, daemon=True).start()
        messagebox.showinfo("Macro Brain", "Cycle iniciado em background.")

    def _refresh():
        render(parent, app)

    def _open_doc():
        """Open the blueprint doc."""
        import os, sys, subprocess as sp
        p = Path("docs/plans/macro_brain_blueprint.md").resolve()
        if not p.exists():
            messagebox.showwarning("Macro Brain", "Blueprint not found.")
            return
        try:
            if sys.platform == "win32": os.startfile(str(p))
            elif sys.platform == "darwin": sp.run(["open", str(p)])
            else: sp.run(["xdg-open", str(p)])
        except Exception as e:
            messagebox.showerror("Macro Brain", str(e))

    for label, cmd, color in [
        ("RUN CYCLE",  _run_cycle, AMBER),
        ("REFRESH",    _refresh,   BG3),
        ("BLUEPRINT",  _open_doc,  BG3),
    ]:
        fg = BG if color == AMBER else WHITE
        b = tk.Label(btn_row, text=f"  {label}  ", font=(FONT, 10, "bold"),
                     fg=fg, bg=color, cursor="hand2", padx=12, pady=5)
        b.pack(side="left", padx=4)
        b.bind("<Button-1>", lambda e, c=cmd: c())

    # Back to main menu
    if app is not None:
        back = tk.Label(btn_row, text="  VOLTAR  ", font=(FONT, 10),
                        fg=DIM, bg=BG3, cursor="hand2", padx=10, pady=5)
        back.pack(side="left", padx=4)
        back.bind("<Button-1>", lambda e: app._menu("main"))
