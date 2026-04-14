"""Macro Brain cockpit — minimalist Bloomberg-style terminal.

Design principles (v5 cleanup):
  - Single accent colour (AMBER) for all section headers and primary chrome.
  - Signal colours (GREEN/RED) only for directional P&L/sentiment.
  - Secondary accent (CYAN) only for navigation / interactive affordances.
  - DIM for metadata, WHITE for primary values.
  - Uniform padding constants everywhere. No per-section colour bleed.
  - Every interactive element gets a hover state.

Tabs:
  [1] US MKTS   rates + FX + equity + commodities + crypto T1/T2
  [2] BR MKTS   IBOV + top B3 stocks + ADRs + BRL forex
  [3] CRYPTO    by network — BTC, ETH, SOL, HYPE, DeFi cross-chain, bots
  [4] INSIGHTS  analytics cards + COT + calendar + live news
  [5] ANALYSIS  FRED econ indicators + banks/funds + insiders/13F
  [6] NETWORK   BTC on-chain + processes + VPS
  [7] BOOK      macro P&L + theses + positions + regime
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import tkinter as tk

log = logging.getLogger("macro_brain.dashboard")

# ── PALETTE ──────────────────────────────────────────────────
#   Backgrounds
BG      = "#050505"
PANEL   = "#0d0d0d"
BG2     = "#131313"
BG3     = "#1a1a1a"
#   Borders
BORDER  = "#222222"
BORDER_H = "#3a3a3a"     # hover border
#   Text
WHITE   = "#e0e0e0"
DIM     = "#606060"
DIM2    = "#909090"
#   Primary accent
AMBER   = "#ffa500"
AMBER_H = "#ffcc33"      # hover amber (brighter)
#   Signal
GREEN   = "#30c050"
RED     = "#e03030"
#   Secondary accent (interactive)
CYAN    = "#00c0d0"
FONT    = "Consolas"

# ── SPACING (consistent across all tabs) ─────────────────────
PAD_OUT         = 8    # outer cockpit padding
PAD_SECTION_TOP = 10   # gap above each section header
PAD_SECTION_BAR = 3    # gap under the section separator
PAD_ROW         = 2    # vertical gap between tile rows
PAD_TILE_X      = 2    # horizontal gap between tiles in a row
PAD_TILE_INNER  = 4    # inner padding of a tile
PAD_COL_GAP     = 6    # gap between left/right columns

_STATE = {"tab": "US MKTS", "news_filter": "ALL"}


# ── DATA UTILS ───────────────────────────────────────────────

def _macro_map(metrics, n=30):
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


def _attach_hover(widget: tk.Widget, default_border: str = BORDER,
                  hover_border: str = BORDER_H) -> None:
    """Give a framed widget a subtle border change on mouse enter/leave."""
    def _on(_e): widget.config(highlightbackground=hover_border)
    def _off(_e): widget.config(highlightbackground=default_border)
    widget.bind("<Enter>", _on)
    widget.bind("<Leave>", _off)


def _tile(parent, label, value, change="", change_color=WHITE,
          series=None, spark_color=AMBER):
    f = tk.Frame(parent, bg=PANEL,
                 highlightbackground=BORDER, highlightthickness=1)
    tk.Label(f, text=label, font=(FONT, 6, "bold"), fg=DIM, bg=PANEL,
             anchor="w").pack(fill="x",
                              padx=PAD_TILE_INNER, pady=(2, 0))
    body = tk.Frame(f, bg=PANEL); body.pack(fill="x", padx=PAD_TILE_INNER)
    tk.Label(body, text=value, font=(FONT, 10, "bold"), fg=WHITE, bg=PANEL,
             anchor="w").pack(side="left")
    if change:
        tk.Label(body, text=change, font=(FONT, 7), fg=change_color,
                 bg=PANEL, anchor="e").pack(side="right", padx=2)
    if series and len(series) >= 2:
        cv = tk.Canvas(f, bg=PANEL, highlightthickness=0, height=14, width=80)
        cv.pack(fill="x", padx=PAD_TILE_INNER, pady=(0, 2))
        def _r(evt=None, c=cv, s=series, col=spark_color):
            w = c.winfo_width() or 80
            _draw_spark(c, s, color=col, w=w, h=14)
        cv.bind("<Configure>", _r)
        cv.after(10, _r)
    else:
        tk.Frame(f, bg=PANEL, height=4).pack()
    _attach_hover(f)
    return f


def _grid(parent, data, specs, spark_color=AMBER):
    row = tk.Frame(parent, bg=BG); row.pack(fill="x", pady=PAD_ROW // 2)
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
        t.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)


def _section(parent, title, color=None, pady_top=None):
    """Section header — always amber bar. `color` param kept for back-compat
    but ignored so palette stays uniform.

    `pady_top` can be passed as (0, 0) for the first section in a tab
    (no gap above); defaults to the standard PAD_SECTION_TOP.
    """
    top = pady_top[0] if pady_top is not None else PAD_SECTION_TOP
    tk.Frame(parent, bg=BG, height=top).pack(fill="x")
    row = tk.Frame(parent, bg=BG); row.pack(fill="x")
    tk.Frame(row, bg=AMBER, width=3).pack(side="left", fill="y")
    tk.Label(row, text=f"  {title}", font=(FONT, 8, "bold"),
             fg=AMBER, bg=BG, anchor="w", padx=2).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x",
                                               pady=(2, PAD_SECTION_BAR))


def _two_col(parent) -> tuple[tk.Frame, tk.Frame]:
    row = tk.Frame(parent, bg=BG); row.pack(fill="x")
    left = tk.Frame(row, bg=BG)
    left.pack(side="left", fill="both", expand=True,
              padx=(0, PAD_COL_GAP // 2))
    right = tk.Frame(row, bg=BG)
    right.pack(side="left", fill="both", expand=True,
               padx=(PAD_COL_GAP // 2, 0))
    return left, right


def _render_bot_slots(parent, network: str,
                      outline: str = BORDER, accent_bg: str = AMBER):
    """Render bot watcher slots — uniform amber chip styling.

    `outline` / `accent_bg` kept for back-compat but overridden to palette.
    """
    try:
        from macro_brain.bots import list_descriptors
        descs = [d for d in list_descriptors() if d.network == network]
    except Exception:
        descs = []
    if not descs:
        return

    status_tone = {
        "planned":    ("·", DIM),
        "scaffolded": ("◦", AMBER),
        "live":       ("●", GREEN),
        "degraded":   ("!", RED),
    }

    slot_row = tk.Frame(parent, bg=BG); slot_row.pack(fill="x",
                                                      pady=PAD_ROW // 2)
    for d in descs:
        slot = tk.Frame(slot_row, bg=PANEL,
                        highlightbackground=BORDER, highlightthickness=1,
                        padx=8, pady=4)
        slot.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
        _attach_hover(slot)
        head = tk.Frame(slot, bg=PANEL); head.pack(anchor="w", fill="x")
        tk.Label(head, text=d.label, font=(FONT, 7, "bold"),
                 fg=AMBER, bg=PANEL).pack(side="left")
        dot, dot_color = status_tone.get(d.status, ("·", DIM))
        tk.Label(head, text=f"  {dot} {d.status}",
                 font=(FONT, 6, "bold"), fg=dot_color,
                 bg=PANEL).pack(side="left")
        tk.Label(slot, text=d.tagline, font=(FONT, 7),
                 fg=DIM2, bg=PANEL, anchor="w").pack(anchor="w")


def _cot_matrix(parent, rows: list[tuple]):
    """Render a CFTC COT positioning matrix — markets × trader classes.

    rows: list of (label, nc_metric, swap_metric, mm_metric) tuples.
    Each metric may be None. Latest value is pulled from macro_data;
    green/red tint based on sign, dim when missing.
    """
    from macro_brain.persistence.store import latest_macro

    def _val(metric: str | None) -> tuple[str, str]:
        if not metric:
            return "—", DIM
        lat = latest_macro(metric, n=1)
        if not lat:
            return "—", DIM
        v = lat[0]["value"]
        try: v = float(v)
        except (TypeError, ValueError):
            return "—", DIM
        s = f"{v:+,.0f}"
        c = GREEN if v > 0 else (RED if v < 0 else WHITE)
        return s, c

    # Header row
    hdr = tk.Frame(parent, bg=BG); hdr.pack(fill="x", pady=(0, 1))
    for txt, w, align in [
        ("MARKET",        14, "w"),
        ("NC NET",        13, "e"),
        ("SWAP · BANKS",  14, "e"),
        ("MM · FUNDS",    14, "e"),
    ]:
        tk.Label(hdr, text=txt, font=(FONT, 6, "bold"), fg=DIM, bg=BG,
                 width=w, anchor=align, padx=4).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(0, 1))

    for label, nc, sw, mm in rows:
        row = tk.Frame(parent, bg=BG); row.pack(fill="x")
        _attach_hover(row, default_border=BG, hover_border=BG)  # no-op hover for row bg

        tk.Label(row, text=label, font=(FONT, 8, "bold"),
                 fg=WHITE, bg=BG, width=14, anchor="w",
                 padx=4).pack(side="left")
        for metric, w in [(nc, 13), (sw, 14), (mm, 14)]:
            s, c = _val(metric)
            tk.Label(row, text=s, font=(FONT, 8),
                     fg=c, bg=BG, width=w, anchor="e",
                     padx=4).pack(side="left")


# ── TAB RENDERERS ────────────────────────────────────────────

def _render_markets_tab(parent):
    """Rates | FX — Commodities | Equity — Crypto (full)."""
    left, right = _two_col(parent)
    rates = _macro_map(["US13W", "US5Y", "US10Y", "US30Y",
                         "YIELD_SPREAD_10_2", "FED_RATE"])
    _section(left, "US RATES · YIELDS", pady_top=(0, 0))
    _grid(left, rates, [
        ("US13W",             "13W",     "{:.3f}%"),
        ("US5Y",              "5Y",      "{:.3f}%"),
        ("US10Y",             "10Y",     "{:.3f}%"),
        ("US30Y",             "30Y",     "{:.3f}%"),
        ("YIELD_SPREAD_10_2", "10Y-2Y",  "{:.3f}"),
        ("FED_RATE",          "FED",     "{:.2f}%"),
    ])

    fx = _macro_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY",
                      "DXY_BROAD"])
    _section(right, "FOREX · MAJOR PAIRS", pady_top=(0, 0))
    _grid(right, fx, [
        ("DXY",       "DXY",     "{:.2f}"),
        ("EUR_USD",   "EUR/USD", "{:.4f}"),
        ("USD_JPY",   "USD/JPY", "{:.2f}"),
        ("GBP_USD",   "GBP/USD", "{:.4f}"),
        ("USD_CNY",   "USD/CNY", "{:.4f}"),
        ("DXY_BROAD", "BROAD",   "{:.2f}"),
    ])

    left2, right2 = _two_col(parent)
    cmd = _macro_map(["GOLD", "SILVER", "WTI_OIL", "BRENT_OIL",
                       "COPPER", "NAT_GAS"])
    _section(left2, "COMMODITIES", pady_top=(0, 0))
    _grid(left2, cmd, [
        ("GOLD",      "GOLD",    "${:,.0f}"),
        ("SILVER",    "SILVER",  "${:.2f}"),
        ("WTI_OIL",   "WTI",     "${:.2f}"),
        ("BRENT_OIL", "BRENT",   "${:.2f}"),
        ("COPPER",    "COPPER",  "${:.3f}"),
        ("NAT_GAS",   "NAT GAS", "${:.3f}"),
    ])

    eq = _macro_map(["SP500", "NASDAQ", "DAX", "FTSE", "NIKKEI", "HSI", "VIX"])
    _section(right2, "EQUITY · VOLATILITY", pady_top=(0, 0))
    _grid(right2, eq, [
        ("SP500",  "S&P 500", "{:,.0f}"),
        ("NASDAQ", "NASDAQ",  "{:,.0f}"),
        ("DAX",    "DAX",     "{:,.0f}"),
        ("FTSE",   "FTSE",    "{:,.0f}"),
        ("NIKKEI", "NIKKEI",  "{:,.0f}"),
        ("HSI",    "HSI",     "{:,.0f}"),
        ("VIX",    "VIX",     "{:.2f}"),
    ])

    c1 = _macro_map(["BTC_SPOT", "ETH_SPOT", "SOL_SPOT", "BNB_SPOT", "XRP_SPOT",
                      "BTC_DOMINANCE", "TOTAL_CRYPTO_MCAP", "CRYPTO_FEAR_GREED"])
    _section(parent, "CRYPTO TIER 1 · SENTIMENT")
    _grid(parent, c1, [
        ("BTC_SPOT",          "BTC",     "${:,.0f}"),
        ("ETH_SPOT",          "ETH",     "${:,.1f}"),
        ("SOL_SPOT",          "SOL",     "${:.2f}"),
        ("BNB_SPOT",          "BNB",     "${:.0f}"),
        ("XRP_SPOT",          "XRP",     "${:.3f}"),
        ("BTC_DOMINANCE",     "BTC DOM", "{:.2f}%"),
        ("TOTAL_CRYPTO_MCAP", "MKT CAP", "${:,.0f}"),
        ("CRYPTO_FEAR_GREED", "F&G",     "{:.0f}/100"),
    ])

    c23 = _macro_map(["USDC_SPOT", "ADA_SPOT", "DOGE_SPOT", "AVAX_SPOT",
                       "TRX_SPOT", "LINK_SPOT", "DOT_SPOT", "TON_SPOT",
                       "POL_SPOT", "SHIB_SPOT", "LTC_SPOT", "BCH_SPOT",
                       "NEAR_SPOT", "UNI_SPOT"])
    _section(parent, "CRYPTO TIER 2-3")
    _grid(parent, c23, [
        ("USDC_SPOT", "USDC", "${:.4f}"),
        ("ADA_SPOT",  "ADA",  "${:.4f}"),
        ("DOGE_SPOT", "DOGE", "${:.5f}"),
        ("AVAX_SPOT", "AVAX", "${:.2f}"),
        ("TRX_SPOT",  "TRX",  "${:.4f}"),
        ("LINK_SPOT", "LINK", "${:.2f}"),
        ("DOT_SPOT",  "DOT",  "${:.3f}"),
    ])
    _grid(parent, c23, [
        ("TON_SPOT",  "TON",  "${:.2f}"),
        ("POL_SPOT",  "POL",  "${:.4f}"),
        ("SHIB_SPOT", "SHIB", "${:.8f}"),
        ("LTC_SPOT",  "LTC",  "${:.2f}"),
        ("BCH_SPOT",  "BCH",  "${:.2f}"),
        ("NEAR_SPOT", "NEAR", "${:.3f}"),
        ("UNI_SPOT",  "UNI",  "${:.3f}"),
    ])


def _render_br_tab(parent):
    """Brazilian equities + BRL forex."""
    br_indices = _macro_map([
        "IBOVESPA", "BR_SMALL_CAPS", "BR_REAL_ESTATE",
        "USD_BRL", "EUR_BRL",
    ], n=30)
    _section(parent, "BR INDICES · FOREX", pady_top=(0, 0))
    _grid(parent, br_indices, [
        ("IBOVESPA",       "IBOV",       "{:,.0f}"),
        ("BR_SMALL_CAPS",  "SMALL CAPS", "{:,.2f}"),
        ("BR_REAL_ESTATE", "IFIX",       "{:,.2f}"),
        ("USD_BRL",        "USD/BRL",    "{:.4f}"),
        ("EUR_BRL",        "EUR/BRL",    "{:.4f}"),
    ])

    stocks1 = _macro_map([
        "PETR4_PETROBRAS", "VALE3_VALE", "ITUB4_ITAU", "BBDC4_BRADESCO",
        "BBAS3_BB", "ABEV3_AMBEV", "B3SA3_B3", "WEGE3_WEG",
    ], n=30)
    _section(parent, "B3 TOP STOCKS · BANCOS · PETRO · MINERADORAS")
    _grid(parent, stocks1, [
        ("PETR4_PETROBRAS", "PETR4", "R${:.2f}"),
        ("VALE3_VALE",      "VALE3", "R${:.2f}"),
        ("ITUB4_ITAU",      "ITUB4", "R${:.2f}"),
        ("BBDC4_BRADESCO",  "BBDC4", "R${:.2f}"),
        ("BBAS3_BB",        "BBAS3", "R${:.2f}"),
        ("ABEV3_AMBEV",     "ABEV3", "R${:.2f}"),
        ("B3SA3_B3",        "B3SA3", "R${:.2f}"),
        ("WEGE3_WEG",       "WEGE3", "R${:.2f}"),
    ])

    stocks2 = _macro_map([
        "RENT3_LOCALIZA", "PRIO3_PRIO", "BRAP4_BRADESPAR",
        "SUZB3_SUZANO", "JBSS3_JBS", "KLBN11_KLABIN",
        "ELET3_ELETROBRAS", "MGLU3_MAGALU",
    ], n=30)
    _grid(parent, stocks2, [
        ("RENT3_LOCALIZA",   "RENT3",  "R${:.2f}"),
        ("PRIO3_PRIO",       "PRIO3",  "R${:.2f}"),
        ("BRAP4_BRADESPAR",  "BRAP4",  "R${:.2f}"),
        ("SUZB3_SUZANO",     "SUZB3",  "R${:.2f}"),
        ("JBSS3_JBS",        "JBSS3",  "R${:.2f}"),
        ("KLBN11_KLABIN",    "KLBN11", "R${:.2f}"),
        ("ELET3_ELETROBRAS", "ELET3",  "R${:.2f}"),
        ("MGLU3_MAGALU",     "MGLU3",  "R${:.2f}"),
    ])

    adrs = _macro_map(["VALE_ADR", "ITUB_ADR", "PBR_ADR", "BBD_ADR"], n=30)
    _section(parent, "BRAZILIAN ADRs · US-LISTED")
    _grid(parent, adrs, [
        ("VALE_ADR", "VALE NYSE", "${:.2f}"),
        ("ITUB_ADR", "ITUB NYSE", "${:.2f}"),
        ("PBR_ADR",  "PBR NYSE",  "${:.2f}"),
        ("BBD_ADR",  "BBD NYSE",  "${:.2f}"),
    ])


def _render_crypto_tab(parent):
    """Crypto deep — organizado por rede."""
    _section(parent, "BTC · NETWORK · ON-CHAIN · POSITIONING",
             pady_top=(0, 0))
    btc = _macro_map([
        "BTC_SPOT", "BTC_DOMINANCE", "BTC_HASH_RATE", "BTC_DIFFICULTY",
        "BTC_BLOCK_HEIGHT", "BTC_MEMPOOL_COUNT", "BTC_FEE_FASTEST_SATVB",
        "BTC_24H_TX_COUNT",
    ], n=30)
    _grid(parent, btc, [
        ("BTC_SPOT",              "PRICE",      "${:,.0f}"),
        ("BTC_DOMINANCE",         "DOMINANCE",  "{:.2f}%"),
        ("BTC_HASH_RATE",         "HASHRATE",   "{:,.0f}"),
        ("BTC_DIFFICULTY",        "DIFFICULTY", "{:,.0f}"),
        ("BTC_BLOCK_HEIGHT",      "BLOCK",      "{:,.0f}"),
        ("BTC_MEMPOOL_COUNT",     "MEMPOOL",    "{:,.0f}"),
        ("BTC_FEE_FASTEST_SATVB", "FEE sat/vB", "{:.0f}"),
        ("BTC_24H_TX_COUNT",      "24H TX",     "{:,.0f}"),
    ])
    btc_extra = _macro_map([
        "BTC_CME_NET_LONGS", "BTC_CME_SWAP_NET", "BTC_CME_MM_NET",
    ], n=12)
    _grid(parent, btc_extra, [
        ("BTC_CME_NET_LONGS", "BTC CME NC NET", "{:+,.0f}"),
        ("BTC_CME_SWAP_NET",  "BTC CME BANKS",  "{:+,.0f}"),
        ("BTC_CME_MM_NET",    "BTC CME FUNDS",  "{:+,.0f}"),
    ])

    _section(parent, "ETH · ETHEREUM · DEFI DOMINANT")
    eth = _macro_map(["ETH_SPOT", "DEFI_ETHEREUM_TVL"], n=30)
    _grid(parent, eth, [
        ("ETH_SPOT",          "ETH PRICE",    "${:,.1f}"),
        ("DEFI_ETHEREUM_TVL", "ETH DEFI TVL", "${:,.0f}"),
    ])

    _section(parent, "SOL · SOLANA · HIGH THROUGHPUT")
    sol = _macro_map(["SOL_SPOT", "DEFI_SOLANA_TVL"], n=30)
    _grid(parent, sol, [
        ("SOL_SPOT",        "SOL PRICE",    "${:.2f}"),
        ("DEFI_SOLANA_TVL", "SOL DEFI TVL", "${:,.0f}"),
    ])
    _render_bot_slots(parent, network="SOL")

    _section(parent, "HYPE · HYPERLIQUID · PERPS")
    hl = _macro_map([
        "HL_TOTAL_OI", "HL_BTC_PRICE", "HL_BTC_OI_USD", "HL_BTC_FUNDING",
        "HL_ETH_OI_USD", "HL_ETH_FUNDING", "HL_HYPE_PRICE",
        "HL_HYPE_OI_USD",
    ], n=12)
    _grid(parent, hl, [
        ("HL_TOTAL_OI",    "TOTAL OI",    "${:,.0f}"),
        ("HL_BTC_PRICE",   "BTC PERP",    "${:,.0f}"),
        ("HL_BTC_OI_USD",  "BTC OI",      "${:,.0f}"),
        ("HL_BTC_FUNDING", "BTC FUNDING", "{:+.4f}%"),
        ("HL_ETH_OI_USD",  "ETH OI",      "${:,.0f}"),
        ("HL_ETH_FUNDING", "ETH FUNDING", "{:+.4f}%"),
        ("HL_HYPE_PRICE",  "HYPE TOKEN",  "${:.2f}"),
        ("HL_HYPE_OI_USD", "HYPE OI",     "${:,.0f}"),
    ])
    _render_bot_slots(parent, network="HYPE")

    _section(parent, "CROSS-CHAIN DEFI · TVL PER NETWORK")
    defi = _macro_map([
        "DEFI_TOTAL_TVL", "DEFI_ETHEREUM_TVL", "DEFI_SOLANA_TVL",
        "DEFI_BSC_TVL", "DEFI_BASE_TVL", "DEFI_ARBITRUM_TVL",
        "DEFI_TRON_TVL", "DEFI_HYPERLIQUID_TVL",
    ], n=30)
    _grid(parent, defi, [
        ("DEFI_TOTAL_TVL",       "TOTAL",    "${:,.0f}"),
        ("DEFI_ETHEREUM_TVL",    "ETH",      "${:,.0f}"),
        ("DEFI_SOLANA_TVL",      "SOL",      "${:,.0f}"),
        ("DEFI_BSC_TVL",         "BSC",      "${:,.0f}"),
        ("DEFI_BASE_TVL",        "BASE",     "${:,.0f}"),
        ("DEFI_ARBITRUM_TVL",    "ARB",      "${:,.0f}"),
        ("DEFI_TRON_TVL",        "TRON",     "${:,.0f}"),
        ("DEFI_HYPERLIQUID_TVL", "HYPE L1",  "${:,.0f}"),
    ])


def _render_insights_tab(parent):
    """Analytics cards — COT | Calendar — Live news."""
    from macro_brain.persistence.store import recent_events

    try:
        from macro_brain.ml_engine.analytics import compute_all
        insights = compute_all()
    except Exception:
        insights = []
    if insights:
        _section(parent, "MACRO ANALYTICS · DERIVED INSIGHTS",
                 pady_top=(0, 0))
        sig_c = {"bullish": GREEN, "bearish": RED,
                 "warning": AMBER, "neutral": DIM2}
        row = tk.Frame(parent, bg=BG); row.pack(fill="x", pady=PAD_ROW // 2)
        for ins in insights:
            sc = sig_c.get(ins.signal, WHITE)
            card = tk.Frame(row, bg=PANEL,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
            _attach_hover(card)
            tk.Label(card, text=ins.name.upper(), font=(FONT, 6, "bold"),
                     fg=DIM, bg=PANEL, anchor="w").pack(
                         fill="x", padx=PAD_TILE_INNER, pady=(2, 0))
            tk.Label(card, text=str(ins.value), font=(FONT, 9, "bold"),
                     fg=WHITE, bg=PANEL, anchor="w").pack(
                         fill="x", padx=PAD_TILE_INNER)
            tk.Label(card, text=ins.signal.upper(), font=(FONT, 7, "bold"),
                     fg=sc, bg=PANEL, anchor="w").pack(
                         fill="x", padx=PAD_TILE_INNER)
            tk.Label(card, text=ins.detail[:60], font=(FONT, 7),
                     fg=DIM2, bg=PANEL, anchor="w", wraplength=180,
                     justify="left").pack(
                         fill="x", padx=PAD_TILE_INNER, pady=(0, 2))

    _section(parent, "ECONOMIC CALENDAR · NEXT RELEASES")
    cal_events = recent_events(category="calendar", limit=20)
    now_iso = datetime.utcnow().isoformat()
    future = sorted([e for e in cal_events if e.get("ts", "") >= now_iso],
                    key=lambda e: e.get("ts", ""))[:12]
    if future:
        for e in future:
            impact = e.get("impact", 0) or 0
            label = (e.get("entities") or ["?"])[0] if e.get("entities") else "?"
            date_s = e.get("ts", "")[:10]
            imp_c = RED if impact >= 0.9 else (AMBER if impact >= 0.7 else DIM)
            row = tk.Frame(parent, bg=BG); row.pack(fill="x", padx=2)
            tk.Frame(row, bg=imp_c, width=3).pack(side="left", fill="y")
            tk.Label(row, text=f" {date_s} ", font=(FONT, 8),
                     fg=WHITE, bg=BG, width=12, anchor="w").pack(side="left")
            tk.Label(row, text=label, font=(FONT, 8, "bold"),
                     fg=WHITE, bg=BG, width=28, anchor="w").pack(side="left")
            tk.Label(row, text=f"{impact:.0%}", font=(FONT, 7),
                     fg=imp_c, bg=BG).pack(side="left")
    else:
        tk.Label(parent, text="  (no upcoming releases)",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)

    _section(parent, "LIVE NEWS · INSTITUTIONAL FEEDS")
    tabs_row = tk.Frame(parent, bg=BG)
    tabs_row.pack(fill="x", pady=(0, PAD_ROW))
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
        for e in filt[:15]:
            sent = e.get("sentiment") or 0.0
            impact = e.get("impact") or 0.0
            sc = GREEN if sent > 0.2 else (RED if sent < -0.2 else DIM2)
            src = e.get("source", "?").replace("rss:", "").replace(
                "newsapi:", "")[:12]
            ca = (e.get("category") or "?")[:7].upper()
            hl = (e.get("headline") or "").strip()
            age = _fmt_age(e.get("ts", ""))
            row = tk.Frame(news_body, bg=BG); row.pack(fill="x")
            tk.Label(row, text=f"{age:<3}", font=(FONT, 7), fg=DIM,
                     bg=BG, width=4, anchor="w").pack(side="left")
            tk.Label(row, text=f"[{ca:<7}]", font=(FONT, 7, "bold"),
                     fg=AMBER, bg=BG, width=10, anchor="w").pack(side="left")
            tk.Label(row, text=src, font=(FONT, 7), fg=DIM2, bg=BG,
                     width=13, anchor="w").pack(side="left")
            imp_str = "█" * min(8, max(1, int(impact * 8)))
            tk.Label(row, text=imp_str, font=(FONT, 6), fg=AMBER,
                     bg=BG, width=9, anchor="w").pack(side="left")
            tk.Label(row, text=f"{sent:+.2f}", font=(FONT, 7, "bold"),
                     fg=sc, bg=BG, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=hl[:160], font=(FONT, 8), fg=WHITE, bg=BG,
                     anchor="w").pack(side="left", fill="x", expand=True)
        if not filt:
            tk.Label(news_body, text="  (no news matching filter)",
                     font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)

    def _set_filter(c):
        _STATE["news_filter"] = c
        for w in tabs_row.winfo_children():
            try: w.destroy()
            except Exception: pass
        _build_news_tabs()
        _render_news()

    def _build_news_tabs():
        cats = ["ALL", "MONETARY", "MACRO", "GEOPOLITICS",
                "CRYPTO", "COMMODITIES"]
        for c in cats:
            active = (c == _STATE["news_filter"])
            tab = tk.Label(
                tabs_row, text=f" {c} ",
                font=(FONT, 7, "bold"),
                fg=BG if active else DIM2,
                bg=AMBER if active else BG3,
                cursor="hand2", padx=6, pady=2,
            )
            tab.pack(side="left", padx=1)
            tab.bind("<Button-1>", lambda e, x=c: _set_filter(x))
            if not active:
                tab.bind("<Enter>",
                         lambda e, t=tab: t.config(bg=BORDER_H))
                tab.bind("<Leave>",
                         lambda e, t=tab: t.config(bg=BG3))

    _build_news_tabs()
    _render_news()


def _render_analysis_tab(parent):
    """FRED econ indicators + banks/funds COT + insiders/13F."""
    from macro_brain.persistence.store import recent_events

    econ = _macro_map([
        "CPI_US", "CORE_CPI_US", "UNEMPLOYMENT_US", "NONFARM_PAYROLLS",
        "JOBLESS_CLAIMS", "MICHIGAN_SENTIMENT", "M2_MONEY_SUPPLY",
        "FED_BALANCE_SHEET", "HOUSING_STARTS", "INDUSTRIAL_PRODUCTION",
        "FED_RATE", "US10Y", "YIELD_SPREAD_10_2",
    ], n=30)
    _section(parent, "ECONOMIC INDICATORS · FRED", pady_top=(0, 0))
    _grid(parent, econ, [
        ("CPI_US",             "CPI",            "{:.2f}"),
        ("CORE_CPI_US",        "CORE CPI",       "{:.2f}"),
        ("UNEMPLOYMENT_US",    "UNEMPLOYMENT",   "{:.2f}%"),
        ("NONFARM_PAYROLLS",   "NFP",            "{:,.0f}"),
        ("JOBLESS_CLAIMS",     "JOBLESS CLAIMS", "{:,.0f}"),
        ("MICHIGAN_SENTIMENT", "MICHIGAN",       "{:.1f}"),
    ])
    _grid(parent, econ, [
        ("M2_MONEY_SUPPLY",       "M2",            "{:,.0f}"),
        ("FED_BALANCE_SHEET",     "FED BAL SHEET", "{:,.0f}"),
        ("HOUSING_STARTS",        "HOUSING",       "{:,.0f}"),
        ("INDUSTRIAL_PRODUCTION", "INDUST PROD",   "{:.2f}"),
        ("FED_RATE",              "FED FUNDS",     "{:.2f}%"),
        ("US10Y",                 "10Y YIELD",     "{:.2f}%"),
    ])

    _section(parent, "CFTC COT · POSITIONING MATRIX · weekly")
    _cot_matrix(parent, [
        # (label,      NC NET,             SWAP (banks),      MM (funds))
        ("DXY",        "DXY_NET_LONGS",    None,              None),
        ("EUR FX",     "EUR_FX_NET_LONGS", None,              None),
        ("JPY FX",     "JPY_FX_NET_LONGS", None,              None),
        ("GBP FX",     "GBP_FX_NET_LONGS", None,              None),
        ("GOLD",       "GOLD_NET_LONGS",   "GOLD_SWAP_NET",   "GOLD_MM_NET"),
        ("SILVER",     "SILVER_NET_LONGS", "SILVER_SWAP_NET", "SILVER_MM_NET"),
        ("WTI CRUDE",  "WTI_NET_LONGS",    "WTI_SWAP_NET",    "WTI_MM_NET"),
        ("BRENT",      None,               "BRENT_SWAP_NET",  "BRENT_MM_NET"),
        ("COPPER",     None,               "COPPER_SWAP_NET", "COPPER_MM_NET"),
        ("NAT GAS",    None,               "NAT_GAS_SWAP_NET", None),
        ("SP500 ES",   "SP500_ES_NET_LONGS", None,            None),
        ("BTC CME",    "BTC_CME_NET_LONGS", "BTC_CME_SWAP_NET", "BTC_CME_MM_NET"),
        ("ETH CME",    None,               "ETH_CME_SWAP_NET", "ETH_CME_MM_NET"),
    ])

    insider_events = recent_events(category="insider", limit=10)
    inst_events = recent_events(category="institutional", limit=10)
    left, right = _two_col(parent)

    _section(left, "INSIDER TRADING · SEC FORM 4 (realtime)")
    if insider_events:
        for e in insider_events:
            age = _fmt_age(e.get("ts", ""))
            hl = (e.get("headline", "") or "").replace("INSIDER: ", "")
            row = tk.Frame(left, bg=BG); row.pack(fill="x")
            tk.Label(row, text=f" {age:<4}", font=(FONT, 7), fg=DIM,
                     bg=BG, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=hl[:72], font=(FONT, 8),
                     fg=WHITE, bg=BG, anchor="w").pack(
                         side="left", fill="x", expand=True)
    else:
        tk.Label(left, text="  (no insider filings)",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)

    _section(right, "13F · INSTITUTIONAL HOLDINGS (quarterly)")
    if inst_events:
        for e in inst_events:
            age = _fmt_age(e.get("ts", ""))
            hl = (e.get("headline", "") or "").replace("13F FILING: ", "")
            row = tk.Frame(right, bg=BG); row.pack(fill="x")
            tk.Label(row, text=f" {age:<4}", font=(FONT, 7), fg=DIM,
                     bg=BG, width=6, anchor="w").pack(side="left")
            tk.Label(row, text=hl[:72], font=(FONT, 8),
                     fg=WHITE, bg=BG, anchor="w").pack(
                         side="left", fill="x", expand=True)
    else:
        tk.Label(right, text="  (no 13F filings)",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)


def _render_network_tab(parent):
    """BTC on-chain — Portal | VPS — Processes."""
    onchain = _macro_map([
        "BTC_HASH_RATE", "BTC_DIFFICULTY", "BTC_BLOCK_HEIGHT",
        "BTC_MEMPOOL_COUNT", "BTC_FEE_FASTEST_SATVB",
        "BTC_24H_TX_COUNT", "BTC_24H_MINER_REVENUE_USD",
        "BTC_24H_TRADE_VOLUME_USD",
    ], n=30)
    _section(parent, "BTC ON-CHAIN · NETWORK STATE", pady_top=(0, 0))
    _grid(parent, onchain, [
        ("BTC_HASH_RATE",             "HASHRATE",   "{:,.0f}"),
        ("BTC_DIFFICULTY",            "DIFF",       "{:,.0f}"),
        ("BTC_BLOCK_HEIGHT",          "BLOCK",      "{:,.0f}"),
        ("BTC_MEMPOOL_COUNT",         "MEMPOOL",    "{:,.0f}"),
        ("BTC_FEE_FASTEST_SATVB",     "FEE sat/vB", "{:.0f}"),
        ("BTC_24H_TX_COUNT",          "24H TX",     "{:,.0f}"),
        ("BTC_24H_MINER_REVENUE_USD", "MINER REV",  "${:,.0f}"),
        ("BTC_24H_TRADE_VOLUME_USD",  "VOL USD",    "${:,.0f}"),
    ])

    adv = _macro_map([
        "BTC_FEE_30MIN_SATVB", "BTC_FEE_1H_SATVB", "BTC_FEE_ECONOMY_SATVB",
        "BTC_MEMPOOL_VSIZE", "BTC_AVG_BLOCK_TIME_MIN",
        "BTC_24H_FEES_BTC", "BTC_24H_MINED",
    ], n=30)
    _section(parent, "BTC ADVANCED · FEES · BLOCK TIME")
    _grid(parent, adv, [
        ("BTC_FEE_30MIN_SATVB",    "30MIN FEE",  "{:.0f}"),
        ("BTC_FEE_1H_SATVB",       "1H FEE",     "{:.0f}"),
        ("BTC_FEE_ECONOMY_SATVB",  "ECON FEE",   "{:.0f}"),
        ("BTC_MEMPOOL_VSIZE",      "MP VSIZE",   "{:,.0f}"),
        ("BTC_AVG_BLOCK_TIME_MIN", "BLOCK TIME", "{:.1f}"),
        ("BTC_24H_FEES_BTC",       "24H FEES",   "{:.2f}"),
        ("BTC_24H_MINED",          "24H MINED",  "{:.0f}"),
    ])

    left, right = _two_col(parent)

    _section(left, "ENGINES PORTAL · PROCESS MONITOR")
    try:
        from core.proc import list_procs
        procs = list_procs()
    except Exception:
        procs = []
    running = [p for p in procs if p.get("alive") or
               p.get("status") == "running"]
    finished = [p for p in procs if not p.get("alive") and
                p.get("status") == "finished"]

    stat_row = tk.Frame(left, bg=BG); stat_row.pack(fill="x",
                                                    pady=PAD_ROW // 2)
    for label, val in [
        ("ACTIVE",   f"{len(running)}"),
        ("FINISHED", f"{len(finished)}"),
        ("TOTAL",    f"{len(procs)}"),
    ]:
        box = tk.Frame(stat_row, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1,
                       padx=10, pady=4)
        box.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
        _attach_hover(box)
        tk.Label(box, text=label, font=(FONT, 6, "bold"),
                 fg=DIM, bg=PANEL).pack()
        tk.Label(box, text=val, font=(FONT, 14, "bold"),
                 fg=WHITE, bg=PANEL).pack()

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
                    vps_detail = f"{host}:{cfg.get('port', 22)}"
            else:
                vps_detail = "host not set"
    except (OSError, json.JSONDecodeError):
        pass

    _section(right, "VPS STATUS")
    vps_c = GREEN if vps_online else RED
    vps_box = tk.Frame(right, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1,
                       padx=12, pady=10)
    vps_box.pack(fill="x", padx=2, pady=2)
    _attach_hover(vps_box)
    tk.Label(vps_box, text="● ONLINE" if vps_online else "○ OFFLINE",
             font=(FONT, 14, "bold"), fg=vps_c, bg=PANEL).pack(anchor="w")
    tk.Label(vps_box, text=vps_detail, font=(FONT, 8),
             fg=WHITE, bg=PANEL).pack(anchor="w")
    tk.Label(vps_box, text="SSH connect test · port 22",
             font=(FONT, 6), fg=DIM, bg=PANEL).pack(anchor="w",
                                                     pady=(2, 0))

    if procs:
        _section(parent, "PROCESSES · ACTIVE + RECENT")
        hdr = tk.Frame(parent, bg=BG); hdr.pack(fill="x", pady=(0, 1))
        for txt, w in [("", 3), ("ENGINE", 16), ("PID", 12),
                       ("STATUS", 10), ("STARTED", 15)]:
            tk.Label(hdr, text=txt, font=(FONT, 6, "bold"), fg=DIM,
                     bg=BG, width=w, anchor="w").pack(side="left")

        for p in procs[:15]:
            engine = (p.get("engine") or "?").upper()
            pid = p.get("pid") or "?"
            status = p.get("status", "?")
            alive = p.get("alive", False)
            sc = GREEN if alive else DIM
            row = tk.Frame(parent, bg=BG); row.pack(fill="x")
            tk.Label(row, text=f" {'●' if alive else '○'}",
                     font=(FONT, 8, "bold"), fg=sc, bg=BG,
                     width=3).pack(side="left")
            tk.Label(row, text=f"{engine:<14}", font=(FONT, 8, "bold"),
                     fg=WHITE, bg=BG, width=16,
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"{pid}", font=(FONT, 7),
                     fg=DIM, bg=BG, width=12,
                     anchor="w").pack(side="left")
            tk.Label(row, text=status.upper(), font=(FONT, 7, "bold"),
                     fg=sc, bg=BG, width=10,
                     anchor="w").pack(side="left")
            started = p.get("started", "")
            tk.Label(row,
                     text=f"{_fmt_age(started)} ago" if started else "",
                     font=(FONT, 7), fg=DIM, bg=BG, anchor="w").pack(
                         side="left", fill="x", expand=True)


def _render_book_tab(parent):
    """Macro paper P&L header · Theses | Positions · Regime details."""
    from macro_brain.persistence.store import (
        active_theses, latest_regime, open_positions, pnl_summary,
    )

    pnl = pnl_summary()
    total = pnl.get("total_pnl", 0) or 0
    equity = pnl.get("equity", 0) or 0
    initial = pnl.get("initial", 0) or 0
    dd_pct = ((initial - equity) / initial * 100) if initial else 0
    theses = active_theses()
    positions = open_positions()

    _section(parent, "MACRO BOOK · PAPER", pady_top=(0, 0))
    pnl_row = tk.Frame(parent, bg=BG); pnl_row.pack(fill="x",
                                                    pady=PAD_ROW // 2)
    for label, val, color in [
        ("EQUITY",    f"${equity:,.0f}",                       WHITE),
        ("TOTAL P&L", f"${total:+,.0f}",
                      GREEN if total >= 0 else RED),
        ("INITIAL",   f"${initial:,.0f}",                      DIM2),
        ("DRAWDOWN",
         f"{-dd_pct:+.2f}%" if dd_pct > 0 else "0.00%",
         RED if dd_pct > 0 else GREEN),
        ("THESES",    f"{len(theses)}",                        AMBER),
        ("POSITIONS", f"{len(positions)}",                     AMBER),
    ]:
        box = tk.Frame(pnl_row, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1,
                       padx=12, pady=6)
        box.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
        _attach_hover(box)
        tk.Label(box, text=val, font=(FONT, 13, "bold"),
                 fg=color, bg=PANEL).pack()
        tk.Label(box, text=label, font=(FONT, 7, "bold"),
                 fg=DIM, bg=PANEL).pack()

    left, right = _two_col(parent)

    _section(left, "ACTIVE THESES")
    if theses:
        for t in theses:
            card = tk.Frame(left, bg=PANEL,
                            highlightbackground=BORDER,
                            highlightthickness=1)
            card.pack(fill="x", pady=2, padx=2)
            _attach_hover(card)
            hdr_c = tk.Frame(card, bg=PANEL)
            hdr_c.pack(fill="x", padx=6, pady=(4, 2))
            sc = GREEN if t["direction"] == "long" else RED
            tk.Label(hdr_c, text=t["direction"].upper(),
                     font=(FONT, 8, "bold"), fg=sc, bg=PANEL).pack(side="left")
            tk.Label(hdr_c, text=f"  {t['asset']}",
                     font=(FONT, 10, "bold"),
                     fg=WHITE, bg=PANEL).pack(side="left")
            tk.Label(hdr_c, text=f"conf {t['confidence']:.0%}",
                     font=(FONT, 8), fg=AMBER,
                     bg=PANEL).pack(side="right", padx=4)
            tk.Label(hdr_c, text=f"{t.get('target_horizon_days', '?')}d",
                     font=(FONT, 8), fg=DIM,
                     bg=PANEL).pack(side="right", padx=4)
            rationale = t.get("rationale", "") or ""
            tk.Label(card, text=rationale[:250], font=(FONT, 8), fg=DIM2,
                     bg=PANEL, wraplength=500, justify="left",
                     anchor="w").pack(fill="x", padx=6, pady=(0, 4))
    else:
        tk.Label(left, text="  (no active theses)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=6)

    _section(right, "OPEN POSITIONS")
    if positions:
        for p in positions:
            sc = GREEN if p["side"] == "long" else RED
            card = tk.Frame(right, bg=PANEL,
                            highlightbackground=BORDER,
                            highlightthickness=1)
            card.pack(fill="x", pady=2, padx=2)
            _attach_hover(card)
            tk.Label(card,
                     text=f"  {p['side'].upper()}  {p['asset']}",
                     font=(FONT, 10, "bold"),
                     fg=sc, bg=PANEL).pack(anchor="w", padx=6,
                                           pady=(4, 0))
            detail = (
                f"  size ${p['size_usd']:,.0f}  @  "
                f"{p['entry_price']:,.2f}"
            )
            tk.Label(card, text=detail, font=(FONT, 8),
                     fg=WHITE, bg=PANEL).pack(anchor="w", padx=6,
                                               pady=(0, 4))
    else:
        tk.Label(right, text="  (no open positions)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=6)

    _section(parent, "CURRENT REGIME · DETAILS")
    regime = latest_regime()
    if regime:
        reg_name = (regime.get("regime") or "?").upper()
        conf = regime.get("confidence") or 0.0
        reg_color = {"RISK_ON": GREEN, "RISK_OFF": RED,
                     "TRANSITION": AMBER, "UNCERTAINTY": DIM2}.get(
                         reg_name, WHITE)
        reg_row = tk.Frame(parent, bg=BG); reg_row.pack(fill="x",
                                                        pady=PAD_ROW // 2)
        tk.Label(reg_row, text=reg_name, font=(FONT, 20, "bold"),
                 fg=reg_color, bg=BG).pack(side="left", padx=(8, 20))
        col = tk.Frame(reg_row, bg=BG); col.pack(side="left")
        tk.Label(col, text=f"confidence {conf:.0%}",
                 font=(FONT, 10), fg=WHITE, bg=BG).pack(anchor="w")
        tk.Label(col,
                 text=f"snapshot age {_fmt_age(regime.get('ts', ''))}",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w")
        reason = regime.get("reason") or ""
        if reason:
            tk.Label(parent, text=f"  {reason}", font=(FONT, 8),
                     fg=DIM2, bg=BG, anchor="w",
                     wraplength=1000, justify="left").pack(
                         fill="x", padx=6, pady=(2, 0))
    else:
        tk.Label(parent, text="  (no regime snapshot yet)",
                 font=(FONT, 9), fg=DIM, bg=BG).pack(pady=6)


# ── TAB BAR / MAIN RENDER ────────────────────────────────────

_TABS = [
    ("US MKTS",  "1", _render_markets_tab),
    ("BR MKTS",  "2", _render_br_tab),
    ("CRYPTO",   "3", _render_crypto_tab),
    ("INSIGHTS", "4", _render_insights_tab),
    ("ANALYSIS", "5", _render_analysis_tab),
    ("NETWORK",  "6", _render_network_tab),
    ("BOOK",     "7", _render_book_tab),
]


def render(parent: tk.Widget, app=None) -> None:
    from macro_brain.persistence.store import init_db, latest_regime
    init_db()

    for w in parent.winfo_children():
        try: w.destroy()
        except Exception: pass

    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True, padx=PAD_OUT, pady=PAD_OUT // 2)

    if app is not None:
        for k in ("<Escape>", "<Key-0>", "<BackSpace>"):
            try: app._kb(k, lambda: app._menu("main"))
            except Exception: pass
        try: app._kb("<Key-r>", lambda: render(parent, app))
        except Exception: pass

    # ── TOP BAR ────────────────────────────────────────
    top = tk.Frame(outer, bg=BG); top.pack(fill="x")
    tk.Label(top, text=" MACRO BRAIN ", font=(FONT, 11, "bold"),
             fg=BG, bg=AMBER, padx=6, pady=1).pack(side="left")
    tk.Label(top, text="  AURUM CIO · live cockpit",
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=3)

    right = tk.Frame(top, bg=BG); right.pack(side="right")

    def _enter_main():
        if app is not None: app._menu("main")

    enter_btn = tk.Label(
        right, text=" ENTER TERMINAL [ESC] ",
        font=(FONT, 8, "bold"), fg=BG, bg=AMBER,
        cursor="hand2", padx=8, pady=2,
    )
    enter_btn.pack(side="right", padx=4)
    enter_btn.bind("<Button-1>", lambda e: _enter_main())
    enter_btn.bind("<Enter>", lambda e: enter_btn.config(bg=AMBER_H))
    enter_btn.bind("<Leave>", lambda e: enter_btn.config(bg=AMBER))

    regime = latest_regime()
    if regime:
        rn = (regime.get("regime") or "?").upper()
        c = regime.get("confidence") or 0.0
        rc = {"RISK_ON": GREEN, "RISK_OFF": RED,
              "TRANSITION": AMBER, "UNCERTAINTY": DIM2}.get(rn, WHITE)
        tk.Label(right, text=f" {rn} ", font=(FONT, 8, "bold"),
                 fg=BG, bg=rc, padx=4).pack(side="right", padx=(4, 0))
        tk.Label(right, text=f"{c:.0%}", font=(FONT, 7),
                 fg=AMBER, bg=BG).pack(side="right", padx=(0, 3))
        tk.Label(right, text="REGIME", font=(FONT, 6, "bold"),
                 fg=DIM, bg=BG).pack(side="right")

    tk.Label(right, text=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="right", padx=8)

    tk.Frame(outer, bg=AMBER, height=1).pack(fill="x", pady=(2, 0))

    # ── TAB BAR ────────────────────────────────────────
    tab_bar = tk.Frame(outer, bg=BG)
    tab_bar.pack(fill="x", pady=(6, 0))

    content = tk.Frame(outer, bg=BG)
    content.pack(fill="both", expand=True, pady=(6, 0))

    def _switch_tab(name):
        _STATE["tab"] = name
        for w in tab_bar.winfo_children():
            try: w.destroy()
            except Exception: pass
        _build_tabs()
        for w in content.winfo_children():
            try: w.destroy()
            except Exception: pass
        for tab_name, _k, renderer in _TABS:
            if tab_name == name:
                try: renderer(content)
                except Exception as e:
                    log.warning(f"tab render {name} failed: {e}")
                    tk.Label(content, text=f"Error: {e}",
                             font=(FONT, 9), fg=RED, bg=BG).pack(pady=20)
                break

    def _build_tabs():
        for tab_name, key_num, _r in _TABS:
            active = (_STATE["tab"] == tab_name)
            if active:
                fg, bg = BG, AMBER
            else:
                fg, bg = DIM2, BG2
            tab = tk.Label(
                tab_bar,
                text=f"  {key_num} · {tab_name}  ",
                font=(FONT, 10, "bold"),
                fg=fg, bg=bg, cursor="hand2", padx=12, pady=5,
            )
            tab.pack(side="left", padx=(0, 1))
            tab.bind("<Button-1>", lambda e, n=tab_name: _switch_tab(n))
            if not active:
                tab.bind(
                    "<Enter>",
                    lambda e, t=tab: t.config(bg=BG3, fg=WHITE),
                )
                tab.bind(
                    "<Leave>",
                    lambda e, t=tab: t.config(bg=BG2, fg=DIM2),
                )
            if app is not None:
                try: app._kb(f"<Key-{key_num}>",
                             lambda n=tab_name: _switch_tab(n))
                except Exception: pass

    _build_tabs()
    _switch_tab(_STATE["tab"])

    # ── FOOTER ─────────────────────────────────────────
    foot = tk.Frame(outer, bg=BG)
    foot.pack(fill="x", pady=(6, 0), side="bottom")

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

    for label, cmd in [
        ("RUN CYCLE [C]", _run_cycle),
        ("REFRESH [R]",   _refresh),
    ]:
        b = tk.Label(
            foot, text=f"  {label}  ", font=(FONT, 8, "bold"),
            fg=WHITE, bg=BG3, cursor="hand2", padx=8, pady=3,
        )
        b.pack(side="left", padx=2)
        b.bind("<Button-1>", lambda e, c=cmd: c())
        b.bind("<Enter>",
               lambda e, w=b: w.config(bg=BORDER_H, fg=AMBER))
        b.bind("<Leave>",
               lambda e, w=b: w.config(bg=BG3, fg=WHITE))
    if app is not None:
        try: app._kb("<Key-c>", lambda: _run_cycle())
        except Exception: pass

    tk.Label(
        foot,
        text="  ESC main menu  ·  1-7 switch tab  ·  R refresh  ·  C cycle",
        font=(FONT, 7), fg=DIM, bg=BG,
    ).pack(side="right", padx=4)
