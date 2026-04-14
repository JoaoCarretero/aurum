"""Macro Brain cockpit v3 — 4-TAB organized layout.

Tabs:
  MARKETS    Rates / FX / Commodities / Equity / Crypto
  INSIGHTS   Analytics / COT / News / Calendar
  NETWORK    On-chain / Engines portal / VPS
  BOOK       Regime / Theses / Positions / P&L

Persisted tab state via module-level dict (survives refresh).
Keyboard: 1-4 switch tab, ESC → main menu, R refresh.
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
PANEL   = "#0d0d0d"
BG2     = "#131313"
BG3     = "#1a1a1a"
AMBER   = "#ffa500"
AMBER_D = "#cc8400"
AMBER_B = "#ffcc33"
GREEN   = "#30c050"
RED     = "#e03030"
BLUE    = "#4a9eff"
CYAN    = "#00eaff"
MAGENTA = "#ff00a0"
PURPLE  = "#c87fff"
WHITE   = "#e0e0e0"
DIM     = "#606060"
DIM2    = "#222222"
BORDER  = "#1a1a1a"
FONT    = "Consolas"


# ── TAB STATE (persisted) ───────────────────────────────────
_STATE = {"tab": "MARKETS", "news_filter": "ALL"}


# ── DATA UTILS ───────────────────────────────────────────────

def _macro_map(metrics: list[str], n: int = 30) -> dict[str, dict]:
    from macro_brain.persistence.store import macro_series
    out = {}
    for m in metrics:
        s = macro_series(m)
        if not s: continue
        vals = [r["value"] for r in s[-n:]]
        last = s[-1]; prev = s[-2] if len(s) > 1 else None
        out[m] = {"value": last["value"], "ts": last["ts"],
                  "prev": prev["value"] if prev else None, "series": vals}
    return out


def _pct_change(a, b):
    if a is None or b is None or b == 0: return None
    return (a - b) / abs(b) * 100


def _fmt_age(ts):
    if not ts: return "—"
    try: dt = datetime.fromisoformat(str(ts).replace("Z", "")[:19])
    except ValueError: return str(ts)[:10]
    s = int((datetime.utcnow() - dt).total_seconds())
    if s < 0:
        s = -s
        if s < 3600:  return f"+{s // 60}m"
        if s < 86400: return f"+{s // 3600}h"
        return f"+{s // 86400}d"
    if s < 60:     return f"{s}s"
    if s < 3600:   return f"{s // 60}m"
    if s < 86400:  return f"{s // 3600}h"
    return f"{s // 86400}d"


# ── UI PRIMITIVES ────────────────────────────────────────────

def _draw_spark(canvas, values, color=AMBER, w=80, h=14):
    canvas.delete("all")
    if not values or len(values) < 2: return
    mn, mx = min(values), max(values)
    rng = mx - mn if mx > mn else 1.0
    pts = []
    for i, v in enumerate(values):
        x = 2 + (w - 4) * (i / (len(values) - 1))
        y = h - 2 - (h - 4) * ((v - mn) / rng)
        pts.append(x); pts.append(y)
    if len(pts) >= 4:
        canvas.create_line(*pts, fill=color, width=1)


def _tile(parent, label, value, change="", change_color=WHITE,
          series=None, spark_color=AMBER):
    f = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
    tk.Label(f, text=label, font=(FONT, 6, "bold"), fg=DIM, bg=PANEL,
             anchor="w").pack(fill="x", padx=4, pady=(2, 0))
    body = tk.Frame(f, bg=PANEL); body.pack(fill="x", padx=4)
    tk.Label(body, text=value, font=(FONT, 10, "bold"), fg=WHITE, bg=PANEL,
             anchor="w").pack(side="left")
    if change:
        tk.Label(body, text=change, font=(FONT, 7), fg=change_color,
                 bg=PANEL, anchor="e").pack(side="right", padx=2)
    if series and len(series) >= 2:
        cv = tk.Canvas(f, bg=PANEL, highlightthickness=0, height=14, width=80)
        cv.pack(fill="x", padx=4, pady=(0, 2))
        def _r(evt=None, c=cv, s=series, col=spark_color):
            w = c.winfo_width() or 80
            _draw_spark(c, s, color=col, w=w, h=14)
        cv.bind("<Configure>", _r)
        cv.after(10, _r)
    else:
        tk.Frame(f, bg=PANEL, height=4).pack()
    return f


def _grid(parent, data, specs, spark_color=AMBER):
    row = tk.Frame(parent, bg=BG); row.pack(fill="x", pady=1)
    for metric, label, fmt in specs:
        info = data.get(metric) or {}
        val = info.get("value")
        if val is None:
            t = _tile(row, label, "—", "no data", DIM)
        else:
            try: vs = fmt.format(val)
            except (ValueError, TypeError): vs = str(val)
            pct = _pct_change(val, info.get("prev"))
            if pct is not None:
                ch = f"{pct:+.2f}%"
                cc = GREEN if pct > 0 else (RED if pct < 0 else DIM)
                sc = GREEN if pct > 0 else (RED if pct < 0 else spark_color)
            else:
                ch = ""; cc = DIM; sc = spark_color
            t = _tile(row, label, vs, ch, cc, info.get("series", []), sc)
        t.pack(side="left", padx=1, fill="both", expand=True)


def _section(parent, title, color=AMBER):
    row = tk.Frame(parent, bg=BG); row.pack(fill="x", pady=(4, 0))
    tk.Frame(row, bg=color, width=2).pack(side="left", fill="y")
    tk.Label(row, text=f" {title}", font=(FONT, 7, "bold"),
             fg=color, bg=BG, anchor="w").pack(side="left")
    tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(0, 1))


# ── TAB RENDERERS ────────────────────────────────────────────

def _render_markets_tab(parent):
    """Tab 1: MARKETS — price data across asset classes."""
    # RATES
    rates = _macro_map(["US13W", "US5Y", "US10Y", "US30Y",
                         "YIELD_SPREAD_10_2", "FED_RATE"])
    _section(parent, "US RATES · YIELDS", color=BLUE)
    _grid(parent, rates, [
        ("US13W",     "13W",       "{:.3f}%"),
        ("US5Y",      "5Y",        "{:.3f}%"),
        ("US10Y",     "10Y",       "{:.3f}%"),
        ("US30Y",     "30Y",       "{:.3f}%"),
        ("YIELD_SPREAD_10_2", "10Y-2Y",  "{:.3f}"),
        ("FED_RATE",  "FED FUNDS", "{:.2f}%"),
    ], spark_color=BLUE)

    # FOREX
    fx = _macro_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY",
                      "DXY_BROAD"])
    _section(parent, "FOREX · MAJOR PAIRS")
    _grid(parent, fx, [
        ("DXY",       "DXY",       "{:.2f}"),
        ("EUR_USD",   "EUR/USD",   "{:.4f}"),
        ("USD_JPY",   "USD/JPY",   "{:.2f}"),
        ("GBP_USD",   "GBP/USD",   "{:.4f}"),
        ("USD_CNY",   "USD/CNY",   "{:.4f}"),
        ("DXY_BROAD", "DXY BROAD", "{:.2f}"),
    ])

    # COMMODITIES
    cmd = _macro_map(["GOLD", "SILVER", "WTI_OIL", "BRENT_OIL",
                       "COPPER", "NAT_GAS"])
    _section(parent, "COMMODITIES", color=AMBER_B)
    _grid(parent, cmd, [
        ("GOLD",      "GOLD",      "${:,.0f}"),
        ("SILVER",    "SILVER",    "${:.2f}"),
        ("WTI_OIL",   "WTI",       "${:.2f}"),
        ("BRENT_OIL", "BRENT",     "${:.2f}"),
        ("COPPER",    "COPPER",    "${:.3f}"),
        ("NAT_GAS",   "NAT GAS",   "${:.3f}"),
    ], spark_color=AMBER_B)

    # EQUITY + VIX
    eq = _macro_map(["SP500", "NASDAQ", "DAX", "FTSE", "NIKKEI", "HSI", "VIX"])
    _section(parent, "EQUITY · VOLATILITY", color=BLUE)
    _grid(parent, eq, [
        ("SP500",    "S&P 500",   "{:,.0f}"),
        ("NASDAQ",   "NASDAQ",    "{:,.0f}"),
        ("DAX",      "DAX",       "{:,.0f}"),
        ("FTSE",     "FTSE",      "{:,.0f}"),
        ("NIKKEI",   "NIKKEI",    "{:,.0f}"),
        ("HSI",      "HSI",       "{:,.0f}"),
        ("VIX",      "VIX",       "{:.2f}"),
    ], spark_color=BLUE)

    # CRYPTO TIER 1
    c1 = _macro_map(["BTC_SPOT", "ETH_SPOT", "SOL_SPOT", "BNB_SPOT", "XRP_SPOT",
                      "BTC_DOMINANCE", "TOTAL_CRYPTO_MCAP", "CRYPTO_FEAR_GREED"])
    _section(parent, "CRYPTO TIER 1 · SENTIMENT", color=AMBER)
    _grid(parent, c1, [
        ("BTC_SPOT",            "BTC",      "${:,.0f}"),
        ("ETH_SPOT",            "ETH",      "${:,.1f}"),
        ("SOL_SPOT",            "SOL",      "${:.2f}"),
        ("BNB_SPOT",            "BNB",      "${:.0f}"),
        ("XRP_SPOT",            "XRP",      "${:.3f}"),
        ("BTC_DOMINANCE",       "BTC DOM",  "{:.2f}%"),
        ("TOTAL_CRYPTO_MCAP",   "MKT CAP",  "${:,.0f}"),
        ("CRYPTO_FEAR_GREED",   "F&G",      "{:.0f}/100"),
    ])

    # CRYPTO TIER 2 + 3 (condensed)
    c23 = _macro_map(["USDC_SPOT", "ADA_SPOT", "DOGE_SPOT", "AVAX_SPOT",
                       "TRX_SPOT", "LINK_SPOT", "DOT_SPOT", "TON_SPOT",
                       "POL_SPOT", "SHIB_SPOT", "LTC_SPOT", "BCH_SPOT",
                       "NEAR_SPOT", "UNI_SPOT"])
    _section(parent, "CRYPTO TIER 2-3")
    _grid(parent, c23, [
        ("USDC_SPOT", "USDC",  "${:.4f}"),
        ("ADA_SPOT",  "ADA",   "${:.4f}"),
        ("DOGE_SPOT", "DOGE",  "${:.5f}"),
        ("AVAX_SPOT", "AVAX",  "${:.2f}"),
        ("TRX_SPOT",  "TRX",   "${:.4f}"),
        ("LINK_SPOT", "LINK",  "${:.2f}"),
        ("DOT_SPOT",  "DOT",   "${:.3f}"),
        ("TON_SPOT",  "TON",   "${:.2f}"),
    ])
    _grid(parent, c23, [
        ("POL_SPOT",  "POL",   "${:.4f}"),
        ("SHIB_SPOT", "SHIB",  "${:.8f}"),
        ("LTC_SPOT",  "LTC",   "${:.2f}"),
        ("BCH_SPOT",  "BCH",   "${:.2f}"),
        ("NEAR_SPOT", "NEAR",  "${:.3f}"),
        ("UNI_SPOT",  "UNI",   "${:.3f}"),
    ])


def _render_insights_tab(parent):
    """Tab 2: INSIGHTS — analytics, positioning, news, calendar."""
    from macro_brain.persistence.store import recent_events

    # ANALYTICS
    try:
        from macro_brain.ml_engine.analytics import compute_all
        insights = compute_all()
    except Exception:
        insights = []
    if insights:
        _section(parent, "MACRO ANALYTICS · DERIVED INSIGHTS", color=PURPLE)
        sig_colors = {"bullish": GREEN, "bearish": RED, "warning": AMBER, "neutral": DIM}
        ins_row = tk.Frame(parent, bg=BG); ins_row.pack(fill="x", pady=1)
        for ins in insights:
            sc = sig_colors.get(ins.signal, WHITE)
            card = tk.Frame(ins_row, bg=PANEL, highlightbackground=sc,
                           highlightthickness=1)
            card.pack(side="left", padx=1, fill="both", expand=True)
            tk.Label(card, text=ins.name.upper(), font=(FONT, 6, "bold"),
                     fg=DIM, bg=PANEL, anchor="w").pack(fill="x", padx=4, pady=(2, 0))
            tk.Label(card, text=str(ins.value), font=(FONT, 9, "bold"),
                     fg=WHITE, bg=PANEL, anchor="w").pack(fill="x", padx=4)
            tk.Label(card, text=ins.signal.upper(), font=(FONT, 7, "bold"),
                     fg=sc, bg=PANEL, anchor="w").pack(fill="x", padx=4)
            tk.Label(card, text=ins.detail[:60], font=(FONT, 7),
                     fg=DIM, bg=PANEL, anchor="w", wraplength=180,
                     justify="left").pack(fill="x", padx=4, pady=(0, 2))

    # CFTC COT
    cot = _macro_map([
        "DXY_NET_LONGS", "EUR_FX_NET_LONGS", "JPY_FX_NET_LONGS",
        "GBP_FX_NET_LONGS", "GOLD_NET_LONGS", "SILVER_NET_LONGS",
        "WTI_NET_LONGS", "SP500_ES_NET_LONGS",
    ], n=12)
    _section(parent, "CFTC COT · INSTITUTIONAL POSITIONING (weekly)", color=MAGENTA)
    _grid(parent, cot, [
        ("DXY_NET_LONGS",       "DXY",      "{:+,.0f}"),
        ("EUR_FX_NET_LONGS",    "EUR",      "{:+,.0f}"),
        ("JPY_FX_NET_LONGS",    "JPY",      "{:+,.0f}"),
        ("GBP_FX_NET_LONGS",    "GBP",      "{:+,.0f}"),
        ("GOLD_NET_LONGS",      "GOLD",     "{:+,.0f}"),
        ("SILVER_NET_LONGS",    "SILVER",   "{:+,.0f}"),
        ("WTI_NET_LONGS",       "WTI",      "{:+,.0f}"),
        ("SP500_ES_NET_LONGS",  "SP500",    "{:+,.0f}"),
    ], spark_color=MAGENTA)

    # ECONOMIC CALENDAR
    cal_events = recent_events(category="calendar", limit=20)
    now_iso = datetime.utcnow().isoformat()
    future = sorted([e for e in cal_events if e.get("ts", "") >= now_iso],
                    key=lambda e: e.get("ts", ""))[:6]
    if future:
        _section(parent, "ECONOMIC CALENDAR · NEXT RELEASES", color=AMBER_B)
        cal_row = tk.Frame(parent, bg=BG); cal_row.pack(fill="x", pady=1)
        for e in future:
            impact = e.get("impact", 0) or 0
            label = (e.get("entities") or ["?"])[0] if e.get("entities") else "?"
            date_s = e.get("ts", "")[:10]
            chip_c = RED if impact >= 0.9 else (AMBER if impact >= 0.7 else DIM)
            chip = tk.Frame(cal_row, bg=PANEL, highlightbackground=chip_c,
                            highlightthickness=1, padx=6, pady=2)
            chip.pack(side="left", padx=2)
            tk.Label(chip, text=label, font=(FONT, 7, "bold"),
                     fg=chip_c, bg=PANEL).pack()
            tk.Label(chip, text=date_s, font=(FONT, 8, "bold"),
                     fg=WHITE, bg=PANEL).pack()
            tk.Label(chip, text=f"impact {impact:.0%}",
                     font=(FONT, 6), fg=DIM, bg=PANEL).pack()

    # NEWS FEED with filter tabs
    _section(parent, "LIVE NEWS · INSTITUTIONAL FEEDS", color=AMBER_B)
    tabs_row = tk.Frame(parent, bg=BG); tabs_row.pack(fill="x", pady=(0, 2))
    news_body = tk.Frame(parent, bg=BG); news_body.pack(fill="x")

    def _render_news():
        for w in news_body.winfo_children():
            try: w.destroy()
            except Exception: pass
        all_e = recent_events(limit=100)
        filt = [e for e in all_e
                if (e.get("source", "").startswith("rss:") or
                    e.get("source") == "newsapi" or
                    e.get("category") in ("monetary", "macro", "geopolitics",
                                            "crypto", "commodities"))
                and e.get("category") != "sentiment"]
        cat = _STATE["news_filter"].lower()
        if cat != "all":
            filt = [e for e in filt if e.get("category", "").lower() == cat]
        for e in filt[:12]:
            sent = e.get("sentiment") or 0.0
            impact = e.get("impact") or 0.0
            sc = GREEN if sent > 0.2 else (RED if sent < -0.2 else DIM)
            src = e.get("source", "?").replace("rss:", "").replace("newsapi:", "")[:12]
            ca = (e.get("category") or "?")[:7].upper()
            hl = (e.get("headline") or "").strip()
            age = _fmt_age(e.get("ts", ""))
            row = tk.Frame(news_body, bg=BG); row.pack(fill="x")
            tk.Label(row, text=f"{age:<3}", font=(FONT, 7), fg=DIM, bg=BG,
                     width=4, anchor="w").pack(side="left")
            tk.Label(row, text=f"[{ca:<7}]", font=(FONT, 7, "bold"),
                     fg=AMBER_D, bg=BG, width=10, anchor="w").pack(side="left")
            tk.Label(row, text=src, font=(FONT, 7), fg=WHITE, bg=BG,
                     width=13, anchor="w").pack(side="left")
            imp_str = "█" * min(8, max(1, int(impact * 8)))
            tk.Label(row, text=imp_str, font=(FONT, 6), fg=AMBER_B,
                     bg=BG, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=f"{sent:+.2f}", font=(FONT, 7, "bold"),
                     fg=sc, bg=BG, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=hl[:140], font=(FONT, 8), fg=WHITE, bg=BG,
                     anchor="w").pack(side="left", fill="x", expand=True)
        if not filt:
            tk.Label(news_body, text="  (no news matching filter)",
                     font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)

    def _set_filter(c, parent_frame=tabs_row):
        _STATE["news_filter"] = c
        for w in parent_frame.winfo_children():
            try: w.destroy()
            except Exception: pass
        _build_news_tabs()
        _render_news()

    def _build_news_tabs():
        cats = ["ALL", "MONETARY", "MACRO", "GEOPOLITICS", "CRYPTO", "COMMODITIES"]
        for c in cats:
            active = (c == _STATE["news_filter"])
            tab = tk.Label(tabs_row,
                           text=f" {c} ", font=(FONT, 7, "bold"),
                           fg=BG if active else DIM,
                           bg=AMBER if active else BG3,
                           cursor="hand2", padx=4, pady=1)
            tab.pack(side="left", padx=1)
            tab.bind("<Button-1>", lambda e, x=c: _set_filter(x))

    _build_news_tabs()
    _render_news()


def _render_network_tab(parent):
    """Tab 3: NETWORK — on-chain, engines portal, VPS."""
    # BTC ON-CHAIN
    onchain = _macro_map([
        "BTC_HASH_RATE", "BTC_DIFFICULTY", "BTC_BLOCK_HEIGHT",
        "BTC_MEMPOOL_COUNT", "BTC_FEE_FASTEST_SATVB",
        "BTC_24H_TX_COUNT", "BTC_24H_MINER_REVENUE_USD",
        "BTC_24H_TRADE_VOLUME_USD",
    ], n=30)
    _section(parent, "BTC ON-CHAIN · NETWORK STATE", color="#00ff88")
    _grid(parent, onchain, [
        ("BTC_HASH_RATE",             "HASHRATE",   "{:,.0f}"),
        ("BTC_DIFFICULTY",            "DIFF",       "{:,.0f}"),
        ("BTC_BLOCK_HEIGHT",          "BLOCK",      "{:,.0f}"),
        ("BTC_MEMPOOL_COUNT",         "MEMPOOL",    "{:,.0f}"),
        ("BTC_FEE_FASTEST_SATVB",     "FEE sat/vB", "{:.0f}"),
        ("BTC_24H_TX_COUNT",          "24H TX",     "{:,.0f}"),
        ("BTC_24H_MINER_REVENUE_USD", "MINER REV",  "${:,.0f}"),
        ("BTC_24H_TRADE_VOLUME_USD",  "VOL USD",    "${:,.0f}"),
    ], spark_color="#00ff88")

    # BTC ADVANCED METRICS
    adv = _macro_map([
        "BTC_FEE_30MIN_SATVB", "BTC_FEE_1H_SATVB", "BTC_FEE_ECONOMY_SATVB",
        "BTC_MEMPOOL_VSIZE", "BTC_AVG_BLOCK_TIME_MIN",
        "BTC_24H_FEES_BTC", "BTC_24H_MINED",
    ], n=30)
    _grid(parent, adv, [
        ("BTC_FEE_30MIN_SATVB",      "30MIN FEE",  "{:.0f}"),
        ("BTC_FEE_1H_SATVB",         "1H FEE",     "{:.0f}"),
        ("BTC_FEE_ECONOMY_SATVB",    "ECON FEE",   "{:.0f}"),
        ("BTC_MEMPOOL_VSIZE",        "MP VSIZE",   "{:,.0f}"),
        ("BTC_AVG_BLOCK_TIME_MIN",   "BLOCK TIME", "{:.1f}"),
        ("BTC_24H_FEES_BTC",         "24H FEES BTC", "{:.2f}"),
        ("BTC_24H_MINED",            "24H MINED",  "{:.0f}"),
    ])

    # ENGINES PORTAL
    _section(parent, "ENGINES PORTAL · PROCESS MONITOR", color=CYAN)
    portal_row = tk.Frame(parent, bg=BG); portal_row.pack(fill="x", pady=1)

    try:
        from core.proc import list_procs
        procs = list_procs()
    except Exception:
        procs = []
    running = [p for p in procs if p.get("alive") or p.get("status") == "running"]
    finished = [p for p in procs if not p.get("alive") and p.get("status") == "finished"]

    for label, val in [("ACTIVE", f"{len(running)}"),
                        ("FINISHED", f"{len(finished)}"),
                        ("TOTAL TRACKED", f"{len(procs)}")]:
        box = tk.Frame(portal_row, bg=PANEL, padx=8, pady=2)
        box.pack(side="left", padx=1)
        tk.Label(box, text=label, font=(FONT, 6, "bold"),
                 fg=CYAN, bg=PANEL).pack()
        tk.Label(box, text=val, font=(FONT, 10, "bold"),
                 fg=WHITE, bg=PANEL).pack()

    # VPS
    vps_online = False; vps_detail = "not configured"
    try:
        vps_path = Path("config/vps.json")
        if vps_path.exists():
            cfg = json.loads(vps_path.read_text(encoding="utf-8"))
            host = (cfg.get("host") or "").strip()
            if host and host not in ("", "n/a"):
                import socket
                try:
                    port = int(cfg.get("port", 22))
                    with socket.create_connection((host, port), timeout=3):
                        vps_online = True
                    vps_detail = f"{host}:{port}"
                except (OSError, ValueError):
                    vps_detail = f"{host}:{cfg.get('port', 22)} UNREACHABLE"
            else: vps_detail = "host not set"
    except (OSError, json.JSONDecodeError):
        pass

    vps_c = GREEN if vps_online else RED
    vps_box = tk.Frame(portal_row, bg=PANEL, highlightbackground=vps_c,
                       highlightthickness=1, padx=8, pady=2)
    vps_box.pack(side="left", padx=2)
    tk.Label(vps_box, text="VPS", font=(FONT, 6, "bold"),
             fg=CYAN, bg=PANEL).pack()
    tk.Label(vps_box, text="ONLINE" if vps_online else "OFFLINE",
             font=(FONT, 9, "bold"), fg=vps_c, bg=PANEL).pack()
    tk.Label(vps_box, text=vps_detail[:20], font=(FONT, 6),
             fg=DIM, bg=PANEL).pack()

    # Process list
    if procs:
        _section(parent, "ACTIVE + RECENT PROCESSES")
        for p in procs[:15]:
            engine = (p.get("engine") or "?").upper()
            pid = p.get("pid") or "?"
            status = p.get("status", "?")
            alive = p.get("alive", False)
            sc = GREEN if alive else DIM
            row = tk.Frame(parent, bg=BG); row.pack(fill="x")
            tk.Label(row, text=f"  {'●' if alive else '○'}",
                     font=(FONT, 8, "bold"), fg=sc, bg=BG, width=3).pack(side="left")
            tk.Label(row, text=f"{engine:<14}", font=(FONT, 8, "bold"),
                     fg=WHITE, bg=BG, width=16, anchor="w").pack(side="left")
            tk.Label(row, text=f"pid {pid}", font=(FONT, 7),
                     fg=DIM, bg=BG, width=12, anchor="w").pack(side="left")
            tk.Label(row, text=status.upper(), font=(FONT, 7, "bold"),
                     fg=sc, bg=BG, width=10, anchor="w").pack(side="left")
            started = p.get("started", "")
            tk.Label(row, text=f"{_fmt_age(started)} ago" if started else "",
                     font=(FONT, 7), fg=DIM, bg=BG, anchor="w").pack(
                         side="left", fill="x", expand=True)


def _render_book_tab(parent):
    """Tab 4: BOOK — regime + theses + positions + P&L."""
    from macro_brain.persistence.store import (
        active_theses, latest_regime, open_positions, pnl_summary,
    )

    # REGIME details
    _section(parent, "CURRENT REGIME · DETAILS", color=AMBER)
    regime = latest_regime()
    reg_frame = tk.Frame(parent, bg=BG); reg_frame.pack(fill="x", pady=1)
    if regime:
        reg_name = (regime.get("regime") or "?").upper()
        conf = regime.get("confidence") or 0.0
        reg_color = {"RISK_ON": GREEN, "RISK_OFF": RED,
                     "TRANSITION": AMBER, "UNCERTAINTY": DIM}.get(reg_name, WHITE)
        tk.Label(reg_frame, text=reg_name, font=(FONT, 18, "bold"),
                 fg=reg_color, bg=BG).pack(side="left", padx=(8, 16))
        col = tk.Frame(reg_frame, bg=BG); col.pack(side="left")
        tk.Label(col, text=f"confidence {conf:.0%}", font=(FONT, 9),
                 fg=WHITE, bg=BG).pack(anchor="w")
        tk.Label(col, text=f"age {_fmt_age(regime.get('ts', ''))}",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w")
        reason = regime.get("reason") or ""
        if reason:
            tk.Label(parent, text=f"  reason: {reason}", font=(FONT, 8),
                     fg=DIM, bg=BG, anchor="w",
                     wraplength=1000, justify="left").pack(fill="x", padx=6)
    else:
        tk.Label(reg_frame, text="  (no regime snapshot yet)",
                 font=(FONT, 9), fg=DIM, bg=BG).pack()

    # P&L CARDS
    _section(parent, "MACRO BOOK · P&L", color=AMBER_D)
    pnl = pnl_summary()
    pnl_row = tk.Frame(parent, bg=BG); pnl_row.pack(fill="x", pady=1)
    total = pnl.get("total_pnl", 0) or 0
    equity = pnl.get("equity", 0) or 0
    initial = pnl.get("initial", 0) or 0
    dd_pct = ((initial - equity) / initial * 100) if initial else 0

    for label, val, col in [
        ("EQUITY",   f"${equity:,.0f}", AMBER),
        ("TOTAL P&L", f"${total:+,.0f}", GREEN if total >= 0 else RED),
        ("INITIAL", f"${initial:,.0f}", WHITE),
        ("DRAWDOWN", f"{-dd_pct:+.2f}%" if dd_pct > 0 else "0.00%",
         RED if dd_pct > 0 else GREEN),
    ]:
        box = tk.Frame(pnl_row, bg=BG3, padx=12, pady=6)
        box.pack(side="left", padx=2)
        tk.Label(box, text=val, font=(FONT, 14, "bold"),
                 fg=col, bg=BG3).pack()
        tk.Label(box, text=label, font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG3).pack()

    # ACTIVE THESES
    _section(parent, "ACTIVE THESES")
    theses = active_theses()
    if theses:
        for t in theses:
            card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                            highlightthickness=1)
            card.pack(fill="x", pady=2, padx=2)
            hdr_c = tk.Frame(card, bg=PANEL); hdr_c.pack(fill="x", padx=8, pady=(4, 2))
            sc = GREEN if t["direction"] == "long" else RED
            tk.Label(hdr_c, text=t["direction"].upper(), font=(FONT, 8, "bold"),
                     fg=BG, bg=sc, padx=4).pack(side="left")
            tk.Label(hdr_c, text=f"  {t['asset']}", font=(FONT, 10, "bold"),
                     fg=WHITE, bg=PANEL).pack(side="left")
            tk.Label(hdr_c, text=f"conf {t['confidence']:.0%}", font=(FONT, 8),
                     fg=AMBER_D, bg=PANEL).pack(side="right", padx=4)
            tk.Label(hdr_c, text=f"{t.get('target_horizon_days', '?')}d",
                     font=(FONT, 8), fg=DIM, bg=PANEL).pack(side="right", padx=4)
            rationale = t.get("rationale", "") or ""
            tk.Label(card, text=rationale[:300], font=(FONT, 8), fg=DIM,
                     bg=PANEL, wraplength=900, justify="left",
                     anchor="w").pack(fill="x", padx=8, pady=(0, 4))
    else:
        tk.Label(parent, text="  (no active theses)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=6)

    # OPEN POSITIONS
    _section(parent, "OPEN POSITIONS")
    positions = open_positions()
    if positions:
        tk.Label(parent, text=f"  {'ASSET':<10} {'SIDE':<6} {'SIZE USD':>10} "
                                f"{'ENTRY':>10} {'UNREALIZED':>12}",
                 font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG,
                 anchor="w").pack(fill="x")
        for p in positions:
            sc = GREEN if p["side"] == "long" else RED
            row = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                          highlightthickness=1)
            row.pack(fill="x", pady=1, padx=2)
            text = (f"  {p['asset']:<10} "
                    f"{p['side'].upper():<6} "
                    f"${p['size_usd']:>9,.0f} "
                    f"@ {p['entry_price']:>9,.1f}")
            tk.Label(row, text=text, font=(FONT, 9), fg=sc, bg=PANEL,
                     anchor="w").pack(side="left", fill="x", expand=True, padx=6, pady=3)
    else:
        tk.Label(parent, text="  (no open positions)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=6)


# ── MAIN RENDER ──────────────────────────────────────────────

_TABS = [
    ("MARKETS",  "1", _render_markets_tab),
    ("INSIGHTS", "2", _render_insights_tab),
    ("NETWORK",  "3", _render_network_tab),
    ("BOOK",     "4", _render_book_tab),
]


def render(parent: tk.Widget, app=None) -> None:
    from macro_brain.persistence.store import init_db, latest_regime
    init_db()

    for w in parent.winfo_children():
        try: w.destroy()
        except Exception: pass

    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True, padx=6, pady=2)

    # Nav bindings
    if app is not None:
        for k in ("<Escape>", "<Key-0>", "<BackSpace>"):
            try: app._kb(k, lambda: app._menu("main"))
            except Exception: pass
        try: app._kb("<Key-r>", lambda: render(parent, app))
        except Exception: pass

    # ── TOP BAR ────────────────────────────────────────
    top = tk.Frame(outer, bg=BG); top.pack(fill="x", pady=(0, 1))
    tk.Label(top, text=" MACRO BRAIN ", font=(FONT, 11, "bold"),
             fg=BG, bg=AMBER, padx=6, pady=1).pack(side="left")
    tk.Label(top, text="  AURUM CIO · live cockpit",
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=3)

    right = tk.Frame(top, bg=BG); right.pack(side="right")
    def _enter_main():
        if app is not None: app._menu("main")
    enter_btn = tk.Label(right, text=" ENTER TERMINAL [ESC] ",
                          font=(FONT, 8, "bold"), fg=BG, bg=AMBER,
                          cursor="hand2", padx=8, pady=2)
    enter_btn.pack(side="right", padx=4)
    enter_btn.bind("<Button-1>", lambda e: _enter_main())

    regime = latest_regime()
    if regime:
        rn = (regime.get("regime") or "?").upper()
        c = regime.get("confidence") or 0.0
        rc = {"RISK_ON": GREEN, "RISK_OFF": RED,
              "TRANSITION": AMBER, "UNCERTAINTY": DIM}.get(rn, WHITE)
        tk.Label(right, text=f" {rn} ", font=(FONT, 8, "bold"),
                 fg=BG, bg=rc, padx=4).pack(side="right", padx=(4, 0))
        tk.Label(right, text=f"{c:.0%}", font=(FONT, 7),
                 fg=AMBER_D, bg=BG).pack(side="right", padx=(0, 3))
        tk.Label(right, text="REGIME", font=(FONT, 6, "bold"),
                 fg=DIM, bg=BG).pack(side="right")

    tk.Label(right, text=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="right", padx=8)

    tk.Frame(outer, bg=AMBER, height=1).pack(fill="x", pady=(1, 0))

    # ── TAB BAR ────────────────────────────────────────
    tab_bar = tk.Frame(outer, bg=BG)
    tab_bar.pack(fill="x", pady=(4, 0))

    content = tk.Frame(outer, bg=BG)
    content.pack(fill="both", expand=True, pady=(4, 0))

    def _switch_tab(name):
        _STATE["tab"] = name
        # redraw tab bar
        for w in tab_bar.winfo_children():
            try: w.destroy()
            except Exception: pass
        _build_tabs()
        # render content
        for w in content.winfo_children():
            try: w.destroy()
            except Exception: pass
        for tab_name, _k, renderer in _TABS:
            if tab_name == name:
                try: renderer(content)
                except Exception as e:
                    log.warning(f"tab render {name} failed: {e}")
                    tk.Label(content, text=f"Error rendering {name}: {e}",
                             font=(FONT, 9), fg=RED, bg=BG).pack(pady=20)
                break

    def _build_tabs():
        for tab_name, key_num, _r in _TABS:
            active = (_STATE["tab"] == tab_name)
            fg = BG if active else DIM
            bg = AMBER if active else BG3
            ff = FONT
            tab = tk.Label(tab_bar,
                           text=f" {key_num}  {tab_name} ",
                           font=(ff, 9, "bold"),
                           fg=fg, bg=bg, cursor="hand2", padx=8, pady=3)
            tab.pack(side="left", padx=1)
            tab.bind("<Button-1>", lambda e, n=tab_name: _switch_tab(n))
            # Keyboard: 1-4 switch tab
            if app is not None:
                try: app._kb(f"<Key-{key_num}>",
                             lambda n=tab_name: _switch_tab(n))
                except Exception: pass

    _build_tabs()
    _switch_tab(_STATE["tab"])  # render current tab

    # ── FOOTER ─────────────────────────────────────────
    foot = tk.Frame(outer, bg=BG)
    foot.pack(fill="x", pady=(4, 0), side="bottom")

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

    def _refresh(): render(parent, app)

    for label, cmd, color, fg in [
        ("RUN CYCLE [C]", _run_cycle, BG3, AMBER),
        ("REFRESH [R]",   _refresh,   BG3, WHITE),
    ]:
        b = tk.Label(foot, text=f"  {label}  ", font=(FONT, 8, "bold"),
                     fg=fg, bg=color, cursor="hand2", padx=6, pady=2)
        b.pack(side="left", padx=2)
        b.bind("<Button-1>", lambda e, c=cmd: c())
    if app is not None:
        try: app._kb("<Key-c>", lambda: _run_cycle())
        except Exception: pass

    tk.Label(foot, text=" ESC → main menu  |  1-4 switch tab  |  R refresh  |  C run cycle",
             font=(FONT, 6), fg=DIM, bg=BG).pack(side="right", padx=4)
