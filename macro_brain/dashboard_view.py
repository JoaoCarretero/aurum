"""Macro Brain cockpit — DENSE market-first dashboard.

Layout Bloomberg/HL2: amber on black, minimalist, datos-datos-datos.
Renderizado como intro screen do launcher. User vê esta tela ao abrir
o app; daí navega pra trade engines/backtests/etc via main menu.

Seções (top-down, densidade decrescente):
  1. HEADER       engine name + regime + timestamp
  2. RATES        US13W, US2Y, US5Y, US10Y, US30Y + spreads
  3. FOREX        DXY, EUR, JPY, GBP, CNY
  4. COMMODITIES  Gold, Silver, WTI, Brent, Copper, NatGas
  5. EQUITY       SP500, Nasdaq, DAX, FTSE, Nikkei, HSI, VIX
  6. CRYPTO       BTC, ETH + dominance + F&G
  7. NEWS         Top 10 recent high-impact headlines
  8. MACRO BOOK   Active theses, positions, P&L (compact footer)
  9. ACTIONS      [ENTER TERMINAL] [RUN CYCLE] [REFRESH]
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

log = logging.getLogger("macro_brain.dashboard")

# ── PALETTE ──────────────────────────────────────────────────
BG      = "#050505"
PANEL   = "#0e0e0e"
BG2     = "#141414"
BG3     = "#1c1c1c"
AMBER   = "#ffa500"
AMBER_D = "#cc8400"
AMBER_B = "#ffcc33"
GREEN   = "#30c050"
RED     = "#e03030"
WHITE   = "#e0e0e0"
DIM     = "#707070"
DIM2    = "#2a2a2a"
BORDER  = "#1f1f1f"
FONT    = "Consolas"


# ── DATA FETCHERS ────────────────────────────────────────────

def _macro_latest_map(metrics: list[str]) -> dict[str, dict]:
    """Returns {metric: {value, ts, prev}}."""
    from macro_brain.persistence.store import macro_series
    out = {}
    for m in metrics:
        series = macro_series(m)
        if not series:
            continue
        last = series[-1]
        prev = series[-2] if len(series) > 1 else None
        out[m] = {
            "value": last["value"],
            "ts": last["ts"],
            "prev": prev["value"] if prev else None,
        }
    return out


def _pct_change(latest: float | None, prev: float | None) -> float | None:
    if latest is None or prev is None or prev == 0:
        return None
    return (latest - prev) / abs(prev) * 100


# ── BUILDING BLOCKS ──────────────────────────────────────────

def _rule(parent, color: str = AMBER_D, pady=(2, 0)):
    tk.Frame(parent, bg=color, height=1).pack(fill="x", pady=pady)


def _section_label(parent, text: str, color: str = AMBER):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=(6, 0))
    tk.Frame(row, bg=color, width=3).pack(side="left", fill="y")
    tk.Label(row, text=f" {text} ", font=(FONT, 8, "bold"),
             fg=color, bg=BG, anchor="w", padx=4).pack(side="left")
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))


def _data_tile(parent, label: str, value: str, change: str = "",
               change_color: str = WHITE, width: int = 14) -> tk.Frame:
    """Compact Bloomberg-style data tile."""
    f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    inner = tk.Frame(f, bg=PANEL, padx=6, pady=3)
    inner.pack(fill="both", expand=True)
    tk.Label(inner, text=label, font=(FONT, 7, "bold"), fg=DIM, bg=PANEL,
             width=width, anchor="w").pack(anchor="w")
    tk.Label(inner, text=value, font=(FONT, 11, "bold"), fg=WHITE, bg=PANEL,
             anchor="w").pack(anchor="w")
    if change:
        tk.Label(inner, text=change, font=(FONT, 8), fg=change_color, bg=PANEL,
                 anchor="w").pack(anchor="w")
    return f


def _metric_row(parent, metrics_data: dict, specs: list[tuple[str, str, str]]):
    """Row of data tiles from metrics_data per specs [(metric_key, label, fmt)]."""
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", padx=0, pady=2)
    for metric, label, fmt in specs:
        info = metrics_data.get(metric) or {}
        val = info.get("value")
        prev = info.get("prev")
        if val is None:
            tile = _data_tile(row, label, "—", "no data", DIM)
        else:
            value_str = fmt.format(val)
            pct = _pct_change(val, prev)
            if pct is not None:
                change = f"{pct:+.2f}%"
                change_color = GREEN if pct > 0 else (RED if pct < 0 else DIM)
            else:
                change = ""
                change_color = DIM
            tile = _data_tile(row, label, value_str, change, change_color)
        tile.pack(side="left", padx=2, fill="both", expand=True)


# ── FORMAT HELPERS ───────────────────────────────────────────

def _fmt_age(ts: str) -> str:
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "")[:19])
    except ValueError:
        return str(ts)[:16]
    s = int((datetime.utcnow() - dt).total_seconds())
    if s < 60:    return f"{s}s"
    if s < 3600:  return f"{s // 60}m"
    if s < 86400: return f"{s // 3600}h"
    return f"{s // 86400}d"


# ── MAIN RENDER ──────────────────────────────────────────────

def render(parent: tk.Widget, app=None) -> None:
    """Main cockpit render. Called by launcher."""
    from macro_brain.persistence.store import (
        active_theses, init_db, latest_regime, open_positions, pnl_summary,
        recent_events,
    )
    init_db()

    # Clear parent
    for w in parent.winfo_children():
        try: w.destroy()
        except Exception: pass

    # Scrollable shell
    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True, padx=8, pady=4)

    # ── HEADER ─────────────────────────────────────────────
    hdr = tk.Frame(outer, bg=BG)
    hdr.pack(fill="x", pady=(0, 2))
    tk.Label(hdr, text=" MACRO BRAIN ", font=(FONT, 12, "bold"),
             fg=BG, bg=AMBER, padx=8, pady=2).pack(side="left")
    tk.Label(hdr, text="  AURUM CIO · autonomous",
             font=(FONT, 8), fg=DIM, bg=BG).pack(side="left", padx=4)

    # Current time + regime in header right
    regime = latest_regime()
    right_hdr = tk.Frame(hdr, bg=BG)
    right_hdr.pack(side="right")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC%z") or datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    tk.Label(right_hdr, text=now_str, font=(FONT, 8), fg=DIM, bg=BG).pack(side="right", padx=8)

    if regime:
        reg_name = regime.get("regime", "?").upper()
        conf = regime.get("confidence", 0.0) or 0.0
        reg_color = {"RISK_ON": GREEN, "RISK_OFF": RED,
                     "TRANSITION": AMBER, "UNCERTAINTY": DIM}.get(reg_name, WHITE)
        tk.Label(right_hdr, text=f"  REGIME",
                 font=(FONT, 7, "bold"), fg=DIM, bg=BG).pack(side="right")
        tk.Label(right_hdr, text=f" {reg_name} ",
                 font=(FONT, 9, "bold"), fg=BG, bg=reg_color, padx=4).pack(side="right", padx=4)
        tk.Label(right_hdr, text=f"conf {conf:.0%}",
                 font=(FONT, 8), fg=AMBER_D, bg=BG).pack(side="right")

    _rule(outer, color=AMBER, pady=(3, 0))

    # ── RATES ──────────────────────────────────────────────
    rates_metrics = _macro_latest_map(["US13W", "US5Y", "US10Y", "US30Y",
                                        "YIELD_SPREAD_10_2", "FED_RATE"])
    _section_label(outer, "US RATES · YIELDS")
    _metric_row(outer, rates_metrics, [
        ("US13W",     "13W T-BILL",    "{:.3f}%"),
        ("US5Y",      "5Y",            "{:.3f}%"),
        ("US10Y",     "10Y",           "{:.3f}%"),
        ("US30Y",     "30Y",           "{:.3f}%"),
        ("YIELD_SPREAD_10_2", "10Y-2Y SPREAD", "{:.3f}"),
        ("FED_RATE",  "FED FUNDS",     "{:.2f}%"),
    ])

    # ── FOREX ──────────────────────────────────────────────
    fx_metrics = _macro_latest_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY"])
    _section_label(outer, "FOREX · MAJOR PAIRS")
    _metric_row(outer, fx_metrics, [
        ("DXY",       "DXY",       "{:.3f}"),
        ("EUR_USD",   "EUR/USD",   "{:.4f}"),
        ("USD_JPY",   "USD/JPY",   "{:.2f}"),
        ("GBP_USD",   "GBP/USD",   "{:.4f}"),
        ("USD_CNY",   "USD/CNY",   "{:.4f}"),
    ])

    # ── COMMODITIES ────────────────────────────────────────
    cmd_metrics = _macro_latest_map(["GOLD", "SILVER", "WTI_OIL", "BRENT_OIL",
                                      "COPPER", "NAT_GAS"])
    _section_label(outer, "COMMODITIES")
    _metric_row(outer, cmd_metrics, [
        ("GOLD",      "GOLD ($/oz)",     "${:,.2f}"),
        ("SILVER",    "SILVER ($/oz)",   "${:.3f}"),
        ("WTI_OIL",   "WTI ($/bbl)",     "${:.2f}"),
        ("BRENT_OIL", "BRENT ($/bbl)",   "${:.2f}"),
        ("COPPER",    "COPPER ($/lb)",   "${:.3f}"),
        ("NAT_GAS",   "NAT GAS ($/mmBTU)", "${:.3f}"),
    ])

    # ── EQUITY INDICES + VIX ───────────────────────────────
    eq_metrics = _macro_latest_map(["SP500", "NASDAQ", "DAX", "FTSE",
                                     "NIKKEI", "HSI", "VIX"])
    _section_label(outer, "EQUITY INDICES · VOLATILITY")
    _metric_row(outer, eq_metrics, [
        ("SP500",    "S&P 500",   "{:,.2f}"),
        ("NASDAQ",   "NASDAQ",    "{:,.2f}"),
        ("DAX",      "DAX",       "{:,.2f}"),
        ("FTSE",     "FTSE 100",  "{:,.2f}"),
        ("NIKKEI",   "NIKKEI",    "{:,.2f}"),
        ("HSI",      "HANG SENG", "{:,.2f}"),
        ("VIX",      "VIX",       "{:.2f}"),
    ])

    # ── CRYPTO ─────────────────────────────────────────────
    crypto_metrics = _macro_latest_map([
        "BTC_SPOT", "ETH_SPOT", "SOL_SPOT", "BNB_SPOT",
        "BTC_DOMINANCE", "TOTAL_CRYPTO_MCAP", "CRYPTO_FEAR_GREED",
    ])
    _section_label(outer, "CRYPTO · SENTIMENT")
    _metric_row(outer, crypto_metrics, [
        ("BTC_SPOT",            "BTC",         "${:,.0f}"),
        ("ETH_SPOT",            "ETH",         "${:,.2f}"),
        ("SOL_SPOT",            "SOL",         "${:,.2f}"),
        ("BNB_SPOT",            "BNB",         "${:,.2f}"),
        ("BTC_DOMINANCE",       "BTC DOM",     "{:.2f}%"),
        ("TOTAL_CRYPTO_MCAP",   "TOTAL CAP",   "${:,.0f}"),
        ("CRYPTO_FEAR_GREED",   "FEAR&GREED",  "{:.0f}/100"),
    ])

    # ── NEWS FEED (top 12) ─────────────────────────────────
    _section_label(outer, "LIVE NEWS · INSTITUTIONAL FEEDS", color=AMBER_B)
    events = recent_events(limit=40)
    # Filter to high-impact + not sentiment duplicates
    real_news = [e for e in events if e.get("source", "").startswith("rss:") and e.get("impact", 0) > 0.1][:12]
    # If few RSS, mix in non-sentiment events
    if len(real_news) < 8:
        fallback = [e for e in events if e.get("category") != "sentiment"][:12]
        real_news = fallback

    if not real_news:
        tk.Label(outer, text="  (no news yet — click RUN CYCLE to pull feeds)",
                 font=(FONT, 9), fg=DIM, bg=BG, anchor="w").pack(fill="x", padx=6, pady=4)
    else:
        for e in real_news:
            sent = e.get("sentiment") or 0.0
            impact = e.get("impact") or 0.0
            sent_color = GREEN if sent > 0.2 else (RED if sent < -0.2 else DIM)
            src_name = e.get("source", "?").replace("rss:", "")[:14]
            cat = (e.get("category") or "?")[:9].upper()
            headline = (e.get("headline") or "").strip()
            age = _fmt_age(e.get("ts", ""))

            row = tk.Frame(outer, bg=BG)
            row.pack(fill="x", pady=0, padx=2)
            tk.Label(row, text=f"{age:<4}", font=(FONT, 8), fg=DIM, bg=BG,
                     width=5, anchor="w").pack(side="left")
            tk.Label(row, text=f"[{cat:<9}]", font=(FONT, 8, "bold"),
                     fg=AMBER_D, bg=BG, width=12, anchor="w").pack(side="left")
            tk.Label(row, text=f"{src_name:<14}", font=(FONT, 8),
                     fg=WHITE, bg=BG, width=15, anchor="w").pack(side="left")
            # Impact bar + sentiment flag
            imp_str = "█" * min(10, max(1, int(impact * 10)))
            tk.Label(row, text=imp_str, font=(FONT, 7),
                     fg=AMBER_B, bg=BG, width=11, anchor="w").pack(side="left")
            tk.Label(row, text=f"{sent:+.2f}", font=(FONT, 8, "bold"),
                     fg=sent_color, bg=BG, width=7, anchor="w").pack(side="left")
            tk.Label(row, text=headline[:130], font=(FONT, 8), fg=WHITE, bg=BG,
                     anchor="w").pack(side="left", fill="x", expand=True)

    # ── MACRO BOOK (compact footer) ───────────────────────
    _section_label(outer, "MACRO BOOK · PAPER", color=AMBER_D)
    theses = active_theses()
    positions = open_positions()
    pnl = pnl_summary()

    book_row = tk.Frame(outer, bg=BG)
    book_row.pack(fill="x", pady=2)

    # Mini stats
    stats = [
        ("THESES",   f"{len(theses)}",   AMBER),
        ("POSITIONS", f"{len(positions)}", AMBER),
        ("EQUITY",   f"${pnl.get('equity', 0):,.0f}", WHITE),
        ("P&L",      f"${pnl.get('total_pnl', 0):+,.0f}",
         GREEN if (pnl.get('total_pnl') or 0) >= 0 else RED),
    ]
    for lbl, val, col in stats:
        box = tk.Frame(book_row, bg=PANEL, padx=8, pady=3)
        box.pack(side="left", padx=2)
        tk.Label(box, text=lbl, font=(FONT, 7, "bold"), fg=DIM, bg=PANEL).pack()
        tk.Label(box, text=val, font=(FONT, 10, "bold"), fg=col, bg=PANEL).pack()

    # Theses summary inline
    if theses:
        theses_line = tk.Frame(outer, bg=BG)
        theses_line.pack(fill="x", pady=1)
        for t in theses[:3]:
            side_color = GREEN if t["direction"] == "long" else RED
            chip = tk.Frame(theses_line, bg=PANEL, padx=6, pady=2)
            chip.pack(side="left", padx=2)
            tk.Label(chip, text=t["direction"].upper(), font=(FONT, 7, "bold"),
                     fg=BG, bg=side_color, padx=3).pack(side="left")
            tk.Label(chip, text=f" {t['asset']}",
                     font=(FONT, 8, "bold"), fg=WHITE, bg=PANEL).pack(side="left")
            tk.Label(chip, text=f" {t['confidence']:.0%}",
                     font=(FONT, 8), fg=AMBER_D, bg=PANEL).pack(side="left")

    # ── ACTIONS ────────────────────────────────────────────
    _section_label(outer, "ACTIONS", color=DIM)

    def _run_cycle():
        import threading
        def _work():
            try:
                from macro_brain.brain import run_once
                run_once(force=True)
                if app is not None:
                    app.after(0, lambda: render(parent, app))
            except Exception as e:
                log.error(f"run_cycle failed: {e}")
        threading.Thread(target=_work, daemon=True).start()
        messagebox.showinfo("Macro Brain", "Cycle iniciado em background.")

    def _enter_main():
        if app is not None:
            app._menu("main")

    def _refresh():
        render(parent, app)

    btn_row = tk.Frame(outer, bg=BG)
    btn_row.pack(pady=6)

    for label, cmd, color, fg in [
        ("ENTER TERMINAL",  _enter_main, AMBER, BG),
        ("RUN CYCLE",       _run_cycle,  BG3,   AMBER),
        ("REFRESH",         _refresh,    BG3,   WHITE),
    ]:
        b = tk.Label(btn_row, text=f"  {label}  ", font=(FONT, 10, "bold"),
                     fg=fg, bg=color, cursor="hand2", padx=14, pady=5)
        b.pack(side="left", padx=4)
        b.bind("<Button-1>", lambda e, c=cmd: c())

    if app is not None:
        app._kb("<Return>", _enter_main)
        app._kb("<space>",  _enter_main)
