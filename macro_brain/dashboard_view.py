"""Macro Brain cockpit — COMPACT DENSE dashboard (v2).

Bloomberg terminal style. Maximum info density, minimal chrome.
Grid 8-tile rows, sparklines inline, news filter tabs, economic calendar.

ESC → main menu (fix nav stuck).
Top bar always shows [ENTER TERMINAL] button.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

log = logging.getLogger("macro_brain.dashboard")

# ── COMPACT PALETTE ──────────────────────────────────────────
BG      = "#050505"
PANEL   = "#0d0d0d"
BG2     = "#131313"
BG3     = "#1a1a1a"
AMBER   = "#ffa500"
AMBER_D = "#cc8400"
AMBER_B = "#ffcc33"
GREEN   = "#30c050"
GREEN_D = "#1f8038"
RED     = "#e03030"
RED_D   = "#a02020"
BLUE    = "#4a9eff"
WHITE   = "#e0e0e0"
DIM     = "#606060"
DIM2    = "#222222"
BORDER  = "#1a1a1a"
FONT    = "Consolas"


# ── DATA ─────────────────────────────────────────────────────

def _macro_map(metrics: list[str], n: int = 30) -> dict[str, dict]:
    """Returns {metric: {value, prev, ts, series[n]}}."""
    from macro_brain.persistence.store import macro_series
    out = {}
    for m in metrics:
        series = macro_series(m)
        if not series:
            continue
        values = [r["value"] for r in series[-n:]]
        last = series[-1]
        prev = series[-2] if len(series) > 1 else None
        out[m] = {
            "value": last["value"],
            "ts": last["ts"],
            "prev": prev["value"] if prev else None,
            "series": values,
        }
    return out


def _pct_change(a, b):
    if a is None or b is None or b == 0:
        return None
    return (a - b) / abs(b) * 100


# ── SPARKLINE CANVAS ─────────────────────────────────────────

def _draw_sparkline(canvas: tk.Canvas, values: list[float], color: str = AMBER,
                     w: int = 80, h: int = 14):
    canvas.delete("all")
    if not values or len(values) < 2:
        return
    mn = min(values)
    mx = max(values)
    rng = mx - mn if mx > mn else 1.0
    pts = []
    for i, v in enumerate(values):
        x = 2 + (w - 4) * (i / (len(values) - 1))
        y = h - 2 - (h - 4) * ((v - mn) / rng)
        pts.append(x); pts.append(y)
    if len(pts) >= 4:
        canvas.create_line(*pts, fill=color, width=1)


# ── TILE (compact) ───────────────────────────────────────────

def _tile_compact(parent, label: str, value: str, change: str = "",
                   change_color: str = WHITE, series: list[float] | None = None,
                   spark_color: str = AMBER):
    f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    # Top: label pequeno
    tk.Label(f, text=label, font=(FONT, 6, "bold"), fg=DIM, bg=PANEL,
             anchor="w").pack(fill="x", padx=4, pady=(2, 0))
    # Middle: value dominante
    body = tk.Frame(f, bg=PANEL)
    body.pack(fill="x", padx=4, pady=0)
    tk.Label(body, text=value, font=(FONT, 10, "bold"), fg=WHITE, bg=PANEL,
             anchor="w").pack(side="left")
    if change:
        tk.Label(body, text=change, font=(FONT, 7), fg=change_color, bg=PANEL,
                 anchor="e").pack(side="right", padx=2)
    # Sparkline
    if series and len(series) >= 2:
        canvas = tk.Canvas(f, bg=PANEL, highlightthickness=0, height=14, width=80)
        canvas.pack(fill="x", padx=4, pady=(0, 2))

        def _redraw(evt=None):
            w = canvas.winfo_width() or 80
            _draw_sparkline(canvas, series, color=spark_color, w=w, h=14)

        canvas.bind("<Configure>", _redraw)
        canvas.after(10, _redraw)
    else:
        tk.Frame(f, bg=PANEL, height=4).pack()
    return f


def _metric_grid(parent, metrics_data: dict, specs: list[tuple[str, str, str]],
                  spark_color: str = AMBER):
    """Grid de tiles compactos. specs = [(metric, label, fmt)]."""
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=1)
    for metric, label, fmt in specs:
        info = metrics_data.get(metric) or {}
        val = info.get("value")
        if val is None:
            tile = _tile_compact(row, label, "—", "no data", DIM)
        else:
            try: value_str = fmt.format(val)
            except (ValueError, TypeError): value_str = str(val)
            pct = _pct_change(val, info.get("prev"))
            if pct is not None:
                change = f"{pct:+.2f}%"
                ccol = GREEN if pct > 0 else (RED if pct < 0 else DIM)
                scol = GREEN if pct > 0 else (RED if pct < 0 else AMBER)
            else:
                change = ""; ccol = DIM; scol = spark_color
            tile = _tile_compact(row, label, value_str, change, ccol,
                                 series=info.get("series", []), spark_color=scol)
        tile.pack(side="left", padx=1, fill="both", expand=True)


def _section(parent, title: str, color: str = AMBER):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=(4, 0))
    tk.Frame(row, bg=color, width=2).pack(side="left", fill="y")
    tk.Label(row, text=f" {title}", font=(FONT, 7, "bold"),
             fg=color, bg=BG, anchor="w").pack(side="left")
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(0, 1))


def _fmt_age(ts: str) -> str:
    if not ts: return "—"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "")[:19])
    except ValueError:
        return str(ts)[:10]
    s = int((datetime.utcnow() - dt).total_seconds())
    if s < 0:      return "+" + _fmt_age_future(-s)
    if s < 60:     return f"{s}s"
    if s < 3600:   return f"{s // 60}m"
    if s < 86400:  return f"{s // 3600}h"
    return f"{s // 86400}d"


def _fmt_age_future(s: int) -> str:
    if s < 3600:  return f"{s // 60}m"
    if s < 86400: return f"{s // 3600}h"
    return f"{s // 86400}d"


# ── MAIN RENDER ──────────────────────────────────────────────

def render(parent: tk.Widget, app=None) -> None:
    from macro_brain.persistence.store import (
        active_theses, init_db, latest_regime, open_positions, pnl_summary,
        recent_events,
    )
    init_db()

    # Clear
    for w in parent.winfo_children():
        try: w.destroy()
        except Exception: pass

    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True, padx=6, pady=2)

    # Nav escape bindings — ESC + ENTER
    if app is not None:
        try: app._kb("<Escape>", lambda: app._menu("main"))
        except Exception: pass

    # ── TOP BAR: title + regime + ENTER TERMINAL ──
    top = tk.Frame(outer, bg=BG)
    top.pack(fill="x", pady=(0, 1))
    tk.Label(top, text=" MACRO BRAIN ", font=(FONT, 11, "bold"),
             fg=BG, bg=AMBER, padx=6, pady=1).pack(side="left")
    tk.Label(top, text="  AURUM CIO · live cockpit",
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=3)

    # right side: regime + ENTER TERMINAL
    right = tk.Frame(top, bg=BG)
    right.pack(side="right")

    # Prominent ENTER TERMINAL button
    def _enter_main():
        if app is not None: app._menu("main")
    enter_btn = tk.Label(right, text=" ENTER TERMINAL [ESC] ",
                          font=(FONT, 8, "bold"), fg=BG, bg=AMBER,
                          cursor="hand2", padx=8, pady=2)
    enter_btn.pack(side="right", padx=4)
    enter_btn.bind("<Button-1>", lambda e: _enter_main())

    # Regime tag
    regime = latest_regime()
    if regime:
        reg_name = (regime.get("regime") or "?").upper()
        conf = regime.get("confidence") or 0.0
        reg_color = {"RISK_ON": GREEN, "RISK_OFF": RED,
                     "TRANSITION": AMBER, "UNCERTAINTY": DIM}.get(reg_name, WHITE)
        tk.Label(right, text=f" {reg_name} ", font=(FONT, 8, "bold"),
                 fg=BG, bg=reg_color, padx=4).pack(side="right", padx=(4, 0))
        tk.Label(right, text=f"{conf:.0%}", font=(FONT, 7),
                 fg=AMBER_D, bg=BG).pack(side="right", padx=(0, 3))
        tk.Label(right, text="REGIME", font=(FONT, 6, "bold"),
                 fg=DIM, bg=BG).pack(side="right")

    # Time
    tk.Label(right, text=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="right", padx=8)

    tk.Frame(outer, bg=AMBER, height=1).pack(fill="x", pady=(1, 0))

    # ── RATES ─────────────────────────────────────────
    rates_metrics = _macro_map(["US13W", "US5Y", "US10Y", "US30Y",
                                 "YIELD_SPREAD_10_2", "FED_RATE"])
    _section(outer, "RATES")
    _metric_grid(outer, rates_metrics, [
        ("US13W",     "13W",       "{:.3f}%"),
        ("US5Y",      "5Y",        "{:.3f}%"),
        ("US10Y",     "10Y",       "{:.3f}%"),
        ("US30Y",     "30Y",       "{:.3f}%"),
        ("YIELD_SPREAD_10_2", "10Y-2Y",  "{:.3f}"),
        ("FED_RATE",  "FED",       "{:.2f}%"),
    ], spark_color=BLUE)

    # ── FOREX ─────────────────────────────────────────
    fx_metrics = _macro_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY"])
    _section(outer, "FOREX")
    _metric_grid(outer, fx_metrics, [
        ("DXY",       "DXY",       "{:.2f}"),
        ("EUR_USD",   "EUR/USD",   "{:.4f}"),
        ("USD_JPY",   "USD/JPY",   "{:.2f}"),
        ("GBP_USD",   "GBP/USD",   "{:.4f}"),
        ("USD_CNY",   "USD/CNY",   "{:.4f}"),
    ])

    # ── COMMODITIES ───────────────────────────────────
    cmd_metrics = _macro_map(["GOLD", "SILVER", "WTI_OIL", "BRENT_OIL",
                               "COPPER", "NAT_GAS"])
    _section(outer, "COMMODITIES")
    _metric_grid(outer, cmd_metrics, [
        ("GOLD",      "GOLD",      "${:,.0f}"),
        ("SILVER",    "SILVER",    "${:.2f}"),
        ("WTI_OIL",   "WTI",       "${:.2f}"),
        ("BRENT_OIL", "BRENT",     "${:.2f}"),
        ("COPPER",    "COPPER",    "${:.3f}"),
        ("NAT_GAS",   "NAT GAS",   "${:.3f}"),
    ], spark_color=AMBER_B)

    # ── EQUITY ────────────────────────────────────────
    eq_metrics = _macro_map(["SP500", "NASDAQ", "DAX", "FTSE",
                              "NIKKEI", "HSI", "VIX"])
    _section(outer, "EQUITY · VOL")
    _metric_grid(outer, eq_metrics, [
        ("SP500",    "S&P 500",   "{:,.0f}"),
        ("NASDAQ",   "NASDAQ",    "{:,.0f}"),
        ("DAX",      "DAX",       "{:,.0f}"),
        ("FTSE",     "FTSE",      "{:,.0f}"),
        ("NIKKEI",   "NIKKEI",    "{:,.0f}"),
        ("HSI",      "HSI",       "{:,.0f}"),
        ("VIX",      "VIX",       "{:.2f}"),
    ], spark_color=BLUE)

    # ── CRYPTO TIER 1 (top 4) ─────────────────────────
    crypto1 = _macro_map(["BTC_SPOT", "ETH_SPOT", "SOL_SPOT", "BNB_SPOT",
                           "XRP_SPOT", "BTC_DOMINANCE",
                           "TOTAL_CRYPTO_MCAP", "CRYPTO_FEAR_GREED"])
    _section(outer, "CRYPTO TIER 1 · SENTIMENT")
    _metric_grid(outer, crypto1, [
        ("BTC_SPOT",            "BTC",      "${:,.0f}"),
        ("ETH_SPOT",            "ETH",      "${:,.1f}"),
        ("SOL_SPOT",            "SOL",      "${:.2f}"),
        ("BNB_SPOT",            "BNB",      "${:.0f}"),
        ("XRP_SPOT",            "XRP",      "${:.3f}"),
        ("BTC_DOMINANCE",       "BTC DOM",  "{:.2f}%"),
        ("TOTAL_CRYPTO_MCAP",   "MKT CAP",  "${:,.0f}"),
        ("CRYPTO_FEAR_GREED",   "F&G",      "{:.0f}/100"),
    ], spark_color=AMBER)

    # ── CRYPTO TIER 2 (top 5-10) ──────────────────────
    crypto2 = _macro_map(["USDC_SPOT", "ADA_SPOT", "DOGE_SPOT", "AVAX_SPOT",
                           "TRX_SPOT", "LINK_SPOT", "DOT_SPOT", "TON_SPOT"])
    _section(outer, "CRYPTO TIER 2")
    _metric_grid(outer, crypto2, [
        ("USDC_SPOT", "USDC",  "${:.4f}"),
        ("ADA_SPOT",  "ADA",   "${:.4f}"),
        ("DOGE_SPOT", "DOGE",  "${:.5f}"),
        ("AVAX_SPOT", "AVAX",  "${:.2f}"),
        ("TRX_SPOT",  "TRX",   "${:.4f}"),
        ("LINK_SPOT", "LINK",  "${:.2f}"),
        ("DOT_SPOT",  "DOT",   "${:.3f}"),
        ("TON_SPOT",  "TON",   "${:.2f}"),
    ])

    # ── CRYPTO TIER 3 ─────────────────────────────────
    crypto3 = _macro_map(["POL_SPOT", "SHIB_SPOT", "LTC_SPOT",
                           "BCH_SPOT", "NEAR_SPOT", "UNI_SPOT"])
    _section(outer, "CRYPTO TIER 3")
    _metric_grid(outer, crypto3, [
        ("POL_SPOT",  "POL",   "${:.4f}"),
        ("SHIB_SPOT", "SHIB",  "${:.8f}"),
        ("LTC_SPOT",  "LTC",   "${:.2f}"),
        ("BCH_SPOT",  "BCH",   "${:.2f}"),
        ("NEAR_SPOT", "NEAR",  "${:.3f}"),
        ("UNI_SPOT",  "UNI",   "${:.3f}"),
    ])

    # ── ECONOMIC CALENDAR ─────────────────────────────
    _section(outer, "ECONOMIC CALENDAR · NEXT RELEASES", color=AMBER_B)
    cal_events = recent_events(category="calendar", limit=6)
    # Filter to future only + sort by date
    now_iso = datetime.utcnow().isoformat()
    future = [e for e in cal_events if e.get("ts", "") >= now_iso]
    future.sort(key=lambda e: e.get("ts", ""))
    if future:
        cal_row = tk.Frame(outer, bg=BG)
        cal_row.pack(fill="x", pady=1)
        for e in future[:6]:
            impact = e.get("impact", 0) or 0
            label = (e.get("entities") or ["?"])[0] if e.get("entities") else "?"
            date_s = e.get("ts", "")[:10]
            chip_color = RED if impact >= 0.9 else (AMBER if impact >= 0.7 else DIM)
            chip = tk.Frame(cal_row, bg=PANEL, highlightbackground=chip_color,
                            highlightthickness=1, padx=6, pady=2)
            chip.pack(side="left", padx=2)
            tk.Label(chip, text=f"{label}", font=(FONT, 7, "bold"),
                     fg=chip_color, bg=PANEL).pack()
            tk.Label(chip, text=date_s, font=(FONT, 8, "bold"),
                     fg=WHITE, bg=PANEL).pack()
            tk.Label(chip, text=f"impact {impact:.0%}",
                     font=(FONT, 6), fg=DIM, bg=PANEL).pack()
    else:
        tk.Label(outer, text="  (no upcoming releases — run calendar job)",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(fill="x", padx=4)

    # ── NEWS FEED (with filter tabs) ──────────────────
    news_state = {"filter": "ALL"}

    _section(outer, "LIVE NEWS · INSTITUTIONAL FEEDS", color=AMBER_B)

    # Filter tabs
    tabs_row = tk.Frame(outer, bg=BG)
    tabs_row.pack(fill="x", pady=(0, 2))
    news_body = tk.Frame(outer, bg=BG)
    news_body.pack(fill="x")

    def _render_news():
        for w in news_body.winfo_children():
            try: w.destroy()
            except Exception: pass
        all_events = recent_events(limit=100)
        filtered = [e for e in all_events
                    if e.get("source", "").startswith("rss:")
                    or e.get("category") in ("monetary", "macro", "geopolitics",
                                              "crypto", "commodities")]
        filtered = [e for e in filtered if e.get("category") != "sentiment"]
        cat_filter = news_state["filter"].lower()
        if cat_filter != "all":
            filtered = [e for e in filtered
                        if e.get("category", "").lower() == cat_filter]
        for e in filtered[:10]:
            sent = e.get("sentiment") or 0.0
            impact = e.get("impact") or 0.0
            sent_color = GREEN if sent > 0.2 else (RED if sent < -0.2 else DIM)
            src_name = e.get("source", "?").replace("rss:", "")[:12]
            cat = (e.get("category") or "?")[:7].upper()
            headline = (e.get("headline") or "").strip()
            age = _fmt_age(e.get("ts", ""))
            row = tk.Frame(news_body, bg=BG)
            row.pack(fill="x", pady=0)
            tk.Label(row, text=f"{age:<3}", font=(FONT, 7), fg=DIM, bg=BG,
                     width=4, anchor="w").pack(side="left")
            tk.Label(row, text=f"[{cat:<7}]", font=(FONT, 7, "bold"),
                     fg=AMBER_D, bg=BG, width=10, anchor="w").pack(side="left")
            tk.Label(row, text=src_name, font=(FONT, 7),
                     fg=WHITE, bg=BG, width=13, anchor="w").pack(side="left")
            imp_str = "█" * min(8, max(1, int(impact * 8)))
            tk.Label(row, text=imp_str, font=(FONT, 6),
                     fg=AMBER_B, bg=BG, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=f"{sent:+.2f}", font=(FONT, 7, "bold"),
                     fg=sent_color, bg=BG, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=headline[:140], font=(FONT, 8), fg=WHITE, bg=BG,
                     anchor="w").pack(side="left", fill="x", expand=True)
        if not filtered:
            tk.Label(news_body, text="  (no news matching filter)",
                     font=(FONT, 8), fg=DIM, bg=BG).pack(pady=6)

    def _set_filter(cat):
        news_state["filter"] = cat
        # redraw tabs
        for w in tabs_row.winfo_children():
            try: w.destroy()
            except Exception: pass
        _build_tabs()
        _render_news()

    def _build_tabs():
        cats = ["ALL", "MONETARY", "MACRO", "GEOPOLITICS", "CRYPTO", "COMMODITIES"]
        for c in cats:
            active = (c == news_state["filter"])
            bg_tab = AMBER if active else BG3
            fg_tab = BG if active else DIM
            tab = tk.Label(tabs_row, text=f" {c} ", font=(FONT, 7, "bold"),
                           fg=fg_tab, bg=bg_tab, cursor="hand2", padx=4, pady=1)
            tab.pack(side="left", padx=1)
            tab.bind("<Button-1>", lambda e, x=c: _set_filter(x))

    _build_tabs()
    _render_news()

    # ── MACRO BOOK (compact footer) ───────────────────
    _section(outer, "MACRO BOOK · PAPER", color=AMBER_D)
    book_row = tk.Frame(outer, bg=BG)
    book_row.pack(fill="x", pady=1)
    theses = active_theses()
    positions = open_positions()
    pnl = pnl_summary()
    stats = [
        ("THESES",    f"{len(theses)}"),
        ("POSITIONS", f"{len(positions)}"),
        ("EQUITY",    f"${pnl.get('equity', 0):,.0f}"),
        ("P&L",       f"${pnl.get('total_pnl', 0):+,.0f}"),
    ]
    for lbl, val in stats:
        box = tk.Frame(book_row, bg=PANEL, padx=6, pady=1)
        box.pack(side="left", padx=1)
        tk.Label(box, text=lbl, font=(FONT, 6, "bold"), fg=DIM, bg=PANEL).pack()
        tk.Label(box, text=val, font=(FONT, 9, "bold"), fg=WHITE, bg=PANEL).pack()

    # Theses chips inline
    if theses:
        for t in theses[:4]:
            side_color = GREEN if t["direction"] == "long" else RED
            chip = tk.Frame(book_row, bg=PANEL, padx=4, pady=1)
            chip.pack(side="left", padx=2)
            tk.Label(chip, text=t["direction"].upper(), font=(FONT, 6, "bold"),
                     fg=BG, bg=side_color, padx=2).pack(side="left")
            tk.Label(chip, text=f" {t['asset']} {t['confidence']:.0%}",
                     font=(FONT, 7, "bold"), fg=WHITE, bg=PANEL).pack(side="left")

    # ── FOOTER BUTTONS ────────────────────────────────
    foot = tk.Frame(outer, bg=BG)
    foot.pack(fill="x", pady=(4, 0))

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

    def _refresh():
        render(parent, app)

    for label, cmd, color, fg in [
        ("RUN CYCLE",  _run_cycle, BG3, AMBER),
        ("REFRESH",    _refresh,   BG3, WHITE),
    ]:
        b = tk.Label(foot, text=f"  {label}  ", font=(FONT, 8, "bold"),
                     fg=fg, bg=color, cursor="hand2", padx=6, pady=2)
        b.pack(side="left", padx=2)
        b.bind("<Button-1>", lambda e, c=cmd: c())

    tk.Label(foot, text=" press ESC or click ENTER TERMINAL → main menu",
             font=(FONT, 6), fg=DIM, bg=BG).pack(side="right", padx=4)
