"""ARBITRAGE — Half-Life HEV Terminal cockpit for cross-venue arbitrage.

9 dense panels, amber-on-black, rendered in-terminal inside the launcher main
frame (no fullscreen). Reads live state via AlchemyState and controls
engines/janestreet.py via parameter hot-reload and subprocess.
"""
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable

# ═══════════════════════════════════════════════════════════
# PALETTE — imported from core/ui_palette (SSOT)
# ═══════════════════════════════════════════════════════════
from core.ui_palette import (
    HEV_BG, HEV_PANEL, HEV_BORDER, HEV_BORDER2,
    HEV_AMBER, HEV_AMBER_B, HEV_AMBER_D, HEV_AMBER_DD,
    HEV_WHITE, HEV_DIM, HEV_GREEN, HEV_RED,
    HEV_HAZARD, HEV_BLOOD,
)

# Venue → planetary glyph
VENUE_GLYPH = {
    "binance":      "☉",  # Sol
    "bybit":        "☽",  # Luna
    "okx":          "☿",  # Mercurius
    "hyperliquid":  "♂",  # Mars
    "gate":         "♃",  # Jupiter
}

# Panel Latin subtitles
PANEL_LATIN = {
    1: "opus magnum",
    2: "flux aurum",
    3: "differentia",
    4: "corpus apertum",
    5: "pulsus",
    6: "nexus",
    7: "solve et coagula",
    8: "timor",
    9: "cronica",
}

# ═══════════════════════════════════════════════════════════
# FONT LOADING — attempts to load bundled TTFs, falls back to Consolas
# ═══════════════════════════════════════════════════════════
_FONT_CACHE = {}

def load_fonts(root: tk.Tk) -> dict:
    """Register VT323/ShareTechMono/Cinzel fonts. Returns a dict of font names.

    Uses tkextrafont if available (cross-platform TTF loading). Falls back to
    Consolas if tkextrafont is not installed or a font file is missing.
    """
    if _FONT_CACHE:
        return _FONT_CACHE
    fonts_dir = Path(__file__).resolve().parent.parent / "server" / "fonts"
    names = {"mono_px": "Consolas", "mono": "Consolas", "serif": "Georgia"}
    try:
        from tkextrafont import Font as ExtraFont  # type: ignore
        for ttf, key, tk_name in [
            ("VT323.ttf",         "mono_px", "VT323"),
            ("ShareTechMono.ttf", "mono",    "Share Tech Mono"),
            ("Cinzel.ttf",        "serif",   "Cinzel"),
        ]:
            path = fonts_dir / ttf
            if path.exists():
                try:
                    ExtraFont(root, file=str(path))
                    names[key] = tk_name
                except Exception:
                    pass
    except ImportError:
        pass
    _FONT_CACHE.update(names)
    return names


def font(kind: str, size: int, weight: str = "normal") -> tuple:
    """Shortcut: font('mono_px', 18) -> ('VT323', 18, 'normal') or Consolas fallback."""
    name = _FONT_CACHE.get(kind, "Consolas")
    return (name, size, weight)


# ═══════════════════════════════════════════════════════════
# PANEL CHROME HELPER
# ═══════════════════════════════════════════════════════════

def make_panel(parent, panel_id: int, title: str, **grid_kwargs) -> tk.Frame:
    """Create a panel frame with HEV chrome: border, corner brackets, title bar.

    Returns the body frame where the caller places content.
    """
    wrap = tk.Frame(parent, bg=HEV_BG, highlightthickness=1,
                    highlightbackground=HEV_BORDER, highlightcolor=HEV_BORDER)
    wrap.grid(**grid_kwargs)
    wrap.grid_propagate(False)

    # Corner brackets (top-left, bottom-right) — tight 6px
    tk.Frame(wrap, bg=HEV_AMBER, width=6, height=2).place(x=0, y=0)
    tk.Frame(wrap, bg=HEV_AMBER, width=2, height=6).place(x=0, y=0)
    tk.Frame(wrap, bg=HEV_AMBER, width=6, height=2).place(relx=1, rely=1, x=-6, y=-2)
    tk.Frame(wrap, bg=HEV_AMBER, width=2, height=6).place(relx=1, rely=1, x=-2, y=-6)

    # Title bar — compact 16px
    title_bar = tk.Frame(wrap, bg=HEV_PANEL, height=16)
    title_bar.pack(fill="x", padx=1, pady=(1, 0))
    title_bar.pack_propagate(False)

    tk.Label(title_bar, text=f"[{panel_id:02d}] {title}",
             font=font("mono_px", 10), fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left", padx=4)

    # Thin amber divider
    tk.Frame(wrap, bg=HEV_AMBER_DD, height=1).pack(fill="x", padx=4)

    body = tk.Frame(wrap, bg=HEV_PANEL)
    body.pack(fill="both", expand=True, padx=1, pady=1)
    return body


# ═══════════════════════════════════════════════════════════
# HAZARD STRIPE
# ═══════════════════════════════════════════════════════════

def hazard_strip(parent, height: int = 10) -> tk.Canvas:
    """Yellow/black diagonal hazard stripe across full width."""
    c = tk.Canvas(parent, height=height, bg=HEV_BG, highlightthickness=0)
    def _redraw(event=None):
        c.delete("all")
        w = c.winfo_width()
        step = 18
        for x in range(-height, w + height, step):
            c.create_polygon(
                x, 0, x + height, 0, x + height - height, height, x - height, height,
                fill=HEV_HAZARD, outline="")
            c.create_polygon(
                x + height, 0, x + step, 0, x + step - height, height, x + height - height, height,
                fill=HEV_BG, outline="")
    c.bind("<Configure>", _redraw)
    return c


# ═══════════════════════════════════════════════════════════
# TICK DRIVER
# ═══════════════════════════════════════════════════════════

class TickDriver:
    """Single after() loop that fans out to registered panel updaters.

    The launcher constructs one TickDriver when entering ALCHEMY, registers
    each panel's update function, then calls start(snapshot_provider) with
    a callable that returns the current snapshot dict.
    """

    def __init__(self, root: tk.Tk, interval_ms: int = 2000):
        self.root = root
        self.interval_ms = interval_ms
        self._updaters: list[Callable[[dict], None]] = []
        self._after_id = None
        self._alive = False
        self._snapshot_provider: Callable[[], dict] | None = None

    def register(self, updater: Callable[[dict], None]):
        self._updaters.append(updater)

    def start(self, snapshot_provider: Callable[[], dict]):
        self._alive = True
        self._snapshot_provider = snapshot_provider
        self._tick()

    def stop(self):
        self._alive = False
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _tick(self):
        if not self._alive or self._snapshot_provider is None:
            return
        try:
            snap = self._snapshot_provider()
            for u in self._updaters:
                try:
                    u(snap)
                except Exception as e:
                    print(f"[alchemy] panel updater error: {e}")
        except Exception as e:
            print(f"[alchemy] tick error: {e}")
        self._after_id = self.root.after(self.interval_ms, self._tick)


# ═══════════════════════════════════════════════════════════
# COCKPIT RENDER
# ═══════════════════════════════════════════════════════════

def render_cockpit(app):
    """Paint the 9-panel HEV cockpit inside app.main (no fullscreen)."""
    import datetime as _dt
    root = app.main
    root.configure(bg=HEV_BG)

    # Compact top bar — tighter 18px (was 22)
    topbar = tk.Frame(root, bg=HEV_BG, height=18)
    topbar.pack(fill="x")
    topbar.pack_propagate(False)

    tk.Label(topbar, text="ARBITRAGE", font=font("mono_px", 10, "bold"),
             fg=HEV_AMBER_B, bg=HEV_BG).pack(side="left", padx=(8, 0))

    # Hidden hermetic detail — single tiny λ suffix (the only one in the whole UI).
    tk.Label(topbar, text="λ", font=("Georgia", 7),
             fg=HEV_AMBER_DD, bg=HEV_BG).pack(side="left", padx=(2, 6))

    # Inline vitals (single StringVar-driven label) — denser
    app._alch_vitals_var = tk.StringVar(value="—")
    app._alch_vitals_lbl = tk.Label(
        topbar, textvariable=app._alch_vitals_var,
        font=font("mono_px", 9), fg=HEV_AMBER, bg=HEV_BG, anchor="w")
    app._alch_vitals_lbl.pack(side="left", fill="x", expand=True, padx=(4, 8))

    # Thin amber separator below topbar
    tk.Frame(root, bg=HEV_AMBER_D, height=1).pack(fill="x")

    # ── Cockpit body (grid of 9 panels) ──
    body = tk.Frame(root, bg=HEV_BG)
    body.pack(fill="both", expand=True, padx=2, pady=2)
    body.grid_columnconfigure(0, weight=26, uniform="col")
    body.grid_columnconfigure(1, weight=48, uniform="col")
    body.grid_columnconfigure(2, weight=26, uniform="col")
    body.grid_rowconfigure(0, weight=5, uniform="row")
    body.grid_rowconfigure(1, weight=5, uniform="row")
    body.grid_rowconfigure(2, weight=3, uniform="row")
    body.grid_rowconfigure(3, minsize=44)
    app._alch_body = body

    # Vitals updater — single inline line
    def update_vitals(snap):
        clock = _dt.datetime.utcnow().strftime("%H:%M:%S")
        acct = snap.get("account", 0) or 0
        dd = snap.get("drawdown_pct", 0) or 0
        n = len(snap.get("positions", []) or [])
        expo = snap.get("exposure_usd", 0) or 0
        mode = (snap.get("mode", "—") or "—").upper()
        running = bool(snap.get("engine_pid", 0)) and not snap.get("_stale", True)
        eng = "RUN" if running else "IDLE"
        app._alch_vitals_var.set(
            f"{clock}  \u2502  ACCT ${acct:,.0f}   DD {dd:+.2f}%   "
            f"POS {n}/5   EXPO ${expo:,.0f}   MODE {mode}   ENGINE {eng}"
        )
        # Color shift on drawdown severity
        try:
            color = HEV_AMBER if dd > -1 else (HEV_HAZARD if dd > -3 else HEV_RED)
            app._alch_vitals_lbl.configure(fg=color)
        except Exception:
            pass
    app._alch_tick.register(update_vitals)

    # Create the 9 panel frames with make_panel — plain English titles
    for pid, row, col, rowspan, title in [
        (1, 0, 0, 2, "OPPORTUNITIES"),
        (2, 0, 1, 1, "FUNDING"),
        (3, 1, 1, 1, "BASIS"),
        (4, 0, 2, 1, "POSITIONS"),
        (5, 1, 2, 1, "VENUES"),
        (8, 2, 0, 1, "RISK"),
        (9, 2, 1, 1, "LOGS"),
        (6, 2, 2, 1, "CONNECTIONS"),
        (7, 3, 0, 1, "ENGINE"),
    ]:
        colspan = 3 if pid == 7 else 1
        body_frame = make_panel(body, pid, title,
                                row=row, column=col,
                                rowspan=rowspan, columnspan=colspan,
                                sticky="nsew", padx=1, pady=1)
        setattr(app, f"_alch_p{pid}", body_frame)

    # Stale overlay — shown when snapshot is old AND engine is running
    overlay = tk.Label(root, text="SNAPSHOT STALE · engine not responding",
                       font=font("mono_px", 10, "bold"), fg=HEV_RED, bg="#1a0000",
                       padx=12, pady=6)
    app._alch_overlay = overlay

    def update_overlay(snap):
        stale = snap.get("_stale", True)
        engine_running = bool(app.proc and app.proc.poll() is None)
        if stale and engine_running:
            overlay.place(relx=0.5, rely=0.5, anchor="center")
        else:
            overlay.place_forget()
    app._alch_tick.register(update_overlay)

    _init_panel_opportunities(app)
    _init_panel_positions(app)
    _init_panel_venue_health(app)
    _init_panel_funding(app)
    _init_panel_risk(app)
    _init_panel_basis(app)
    _init_panel_connections(app)
    _init_panel_engine(app)
    _init_panel_log(app)


# ═══════════════════════════════════════════════════════════
# TABLE HELPER + PANEL INITIALIZERS
# ═══════════════════════════════════════════════════════════

def _render_table(parent, header: list, widths: list):
    """Build a header row and return (body_frame, update_fn).

    update_fn(rows, colors=None) replaces body contents with rows.
    - rows: list[list[str]]
    - colors: optional list[list[str|None]] same shape as rows
    """
    # Header
    hdr = tk.Frame(parent, bg=HEV_PANEL)
    hdr.pack(fill="x", padx=2, pady=(1, 0))
    for txt, w in zip(header, widths):
        tk.Label(hdr, text=txt, width=w, anchor="w",
                 font=font("mono", 8), fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="left")

    body = tk.Frame(parent, bg=HEV_PANEL)
    body.pack(fill="both", expand=True, padx=2)

    def update(rows, colors=None):
        for child in body.winfo_children():
            child.destroy()
        for i, row in enumerate(rows):
            row_colors = colors[i] if colors and i < len(colors) else [None] * len(row)
            row_frame = tk.Frame(body, bg=HEV_PANEL)
            row_frame.pack(fill="x")
            for txt, w, c in zip(row, widths, row_colors):
                tk.Label(row_frame, text=str(txt), width=w, anchor="w",
                         font=font("mono_px", 10),
                         fg=c or HEV_AMBER, bg=HEV_PANEL).pack(side="left")
    return body, update


def _init_panel_opportunities(app):
    frame = app._alch_p1
    _, update_rows = _render_table(
        frame,
        header=["#", "SYM", "LONG", "SHORT", "SPRD", "APR", "Ω"],
        widths=[3, 8, 5, 5, 7, 6, 4],
    )
    def update(snap):
        opps = snap.get("opportunities", []) or []
        opps = opps[:10]
        rows, colors = [], []
        for i, o in enumerate(opps, 1):
            long_v = (o.get("long", "") or "")[:3].upper()
            short_v = (o.get("short", "") or "")[:3].upper()
            rows.append([
                f"{i:02d}",
                (o.get("sym", "—") or "—")[:7],
                long_v,
                short_v,
                f"{(o.get('spread') or 0)*100:+.4f}",
                f"{o.get('apr') or 0:.1f}%",
                f"{o.get('omega') or 0:.1f}",
            ])
            omega_val = o.get('omega') or 0
            c = HEV_AMBER if omega_val < 7 else HEV_HAZARD
            colors.append([HEV_AMBER_D, HEV_HAZARD, HEV_AMBER, HEV_AMBER, HEV_GREEN, HEV_GREEN, c])
        if not rows:
            rows = [["—", "no opps", "", "", "", "", ""]]
            colors = [[HEV_DIM] * 7]
        update_rows(rows, colors)
    app._alch_tick.register(update)


def _init_panel_positions(app):
    frame = app._alch_p4
    _, update_rows = _render_table(
        frame,
        header=["SYM", "VEN", "PNL", "EDGE", "EXIT"],
        widths=[6, 8, 7, 6, 6],
    )
    def update(snap):
        poss = snap.get("positions", []) or []
        rows, colors = [], []
        for p in poss:
            long_v = (p.get("long", "") or "")[:3].upper()
            short_v = (p.get("short", "") or "")[:3].upper()
            pnl = p.get("pnl", 0) or 0
            exit_s = p.get("exit_in_s", 0) or 0
            h, rem = divmod(int(exit_s), 3600)
            m = rem // 60
            rows.append([
                (p.get("sym", "—") or "—")[:5],
                f"{long_v}/{short_v}",
                f"{pnl:+.2f}",
                f"-{p.get('edge_decay_pct', 0) or 0:.0f}%",
                f"{h}h{m:02d}m" if exit_s > 0 else "—",
            ])
            colors.append([
                HEV_HAZARD,
                HEV_AMBER,
                HEV_GREEN if pnl >= 0 else HEV_RED,
                HEV_AMBER,
                HEV_HAZARD if exit_s < 7200 else HEV_AMBER,
            ])
        if not rows:
            rows = [["—", "no pos", "", "", ""]]
            colors = [[HEV_DIM] * 5]
        update_rows(rows, colors)
    app._alch_tick.register(update)


def _init_panel_venue_health(app):
    frame = app._alch_p5
    _, update_rows = _render_table(
        frame,
        header=["VEN", "PING", "ERR", "RL", "KS"],
        widths=[5, 6, 4, 5, 5],
    )
    def update(snap):
        health = snap.get("venue_health", {}) or {}
        rows, colors = [], []
        venues = ["binance", "bybit", "okx", "hyperliquid", "gate"]
        for v in venues:
            h = health.get(v, {}) or {}
            disabled = h.get("disabled", False)
            ping = h.get("ping_ms")
            err = h.get("err", 0) or 0
            rl = h.get("rate_limit_pct")
            status = "DOWN" if disabled else ("WARN" if (rl or 0) > 75 else "OK")
            rows.append([
                v[:3].upper(),
                "—" if ping is None else f"{ping}ms",
                str(err),
                "—" if rl is None else f"{rl}%",
                status,
            ])
            colors.append([
                HEV_DIM if disabled else HEV_AMBER,
                HEV_RED if disabled else HEV_AMBER,
                HEV_RED if err > 0 else HEV_AMBER_D,
                HEV_HAZARD if (rl or 0) > 75 else HEV_AMBER,
                HEV_RED if status == "DOWN" else (HEV_HAZARD if status == "WARN" else HEV_GREEN),
            ])
        update_rows(rows, colors)
    app._alch_tick.register(update)


def _init_panel_funding(app):
    frame = app._alch_p2
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=2, pady=2)

    venues = ["binance", "bybit", "okx", "hyperliquid", "gate"]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT"]

    cells = {}
    # Header row — plain 3-letter venue codes
    hdr = tk.Frame(inner, bg=HEV_PANEL); hdr.pack(fill="x")
    tk.Label(hdr, text="", width=5, font=font("mono_px", 9),
             fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="left")
    for v in venues:
        tk.Label(hdr, text=v[:3].upper(),
                 width=7, font=font("mono", 8, "bold"),
                 fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left")

    for sym in symbols:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x")
        tk.Label(row, text=sym.replace("USDT", ""), width=5,
                 font=font("mono_px", 10), fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left")
        cells[sym] = {}
        for v in venues:
            lbl = tk.Label(row, text="—", width=7,
                           font=font("mono_px", 10), fg=HEV_AMBER_D, bg="#0a0500")
            lbl.pack(side="left", padx=1)
            cells[sym][v] = lbl

    footer = tk.Label(inner, text="", font=font("mono", 8),
                      fg=HEV_AMBER_D, bg=HEV_PANEL, anchor="e")
    footer.pack(fill="x", pady=(2, 0))

    def update(snap):
        funding = snap.get("funding", {}) or {}
        for sym in symbols:
            for v in venues:
                rate = (funding.get(sym, {}) or {}).get(v)
                if rate is None:
                    cells[sym][v].configure(text="—", fg=HEV_AMBER_D, bg="#0a0500")
                    continue
                pct = rate * 100
                txt = f"{pct:+.4f}"
                if pct > 0.02:
                    bg, fg = "#3a0a00", "#ff5030"
                elif pct < 0:
                    bg, fg = "#001a00", "#30ff80"
                else:
                    bg, fg = "#0a0500", HEV_AMBER
                cells[sym][v].configure(text=txt, fg=fg, bg=bg)

        # Next funding countdowns
        import time as _t
        nf = snap.get("next_funding", {}) or {}
        now = _t.time()
        parts = []
        for v in venues:
            ts = nf.get(v, 0) or 0
            if ts and ts > now:
                rem = int(ts - now)
                h, m = divmod(rem // 60, 60)
                parts.append(f"{v[:3].upper()} {h}h{m:02d}m")
        footer.configure(text=("next: " + " · ".join(parts)) if parts else "")

    app._alch_tick.register(update)


def _init_panel_risk(app):
    frame = app._alch_p8
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=3, pady=2)

    gauges = {}
    for key, label in [
        ("expo",    "EXPO"),
        ("dd_day",  "DD DAY"),
        ("dd_max",  "DD MAX"),
        ("losses",  "LOSSES"),
        ("sortino", "SORT"),
        ("trades",  "TRADES"),
    ]:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x", pady=0)
        tk.Label(row, text=label, width=7, font=font("mono", 8),
                 fg=HEV_AMBER_D, bg=HEV_PANEL, anchor="w").pack(side="left")
        bar_wrap = tk.Frame(row, bg="#1a0f00", height=6, highlightthickness=1,
                            highlightbackground=HEV_AMBER_DD)
        bar_wrap.pack(side="left", fill="x", expand=True, padx=2)
        bar_wrap.pack_propagate(False)
        fill = tk.Frame(bar_wrap, bg=HEV_AMBER)
        fill.place(x=0, y=0, relheight=1, relwidth=0)
        val = tk.Label(row, text="—", width=6, font=font("mono_px", 9),
                       fg=HEV_AMBER, bg=HEV_PANEL, anchor="e")
        val.pack(side="left")
        gauges[key] = (fill, val)

    def set_bar(fill, val_lbl, pct, text, color=HEV_AMBER):
        pct = max(0, min(1.0, pct))
        fill.configure(bg=color)
        fill.place_configure(relwidth=pct)
        val_lbl.configure(text=text, fg=color)

    def update(snap):
        expo = snap.get("exposure_usd", 0) or 0
        max_expo = 3000
        set_bar(*gauges["expo"], expo / max_expo if max_expo else 0, f"{expo/max_expo*100:.0f}%" if max_expo else "—")

        dd = abs(snap.get("drawdown_pct", 0) or 0)
        set_bar(*gauges["dd_day"], dd / 5.0,
                f"{-dd:+.1f}%",
                color=HEV_GREEN if dd < 1 else (HEV_HAZARD if dd < 3 else HEV_RED))

        set_bar(*gauges["dd_max"], dd / 5.0, f"{-dd:+.1f}%", color=HEV_GREEN)

        loss = snap.get("losses_streak", 0) or 0
        set_bar(*gauges["losses"], loss / 3.0, f"{loss}/3",
                color=HEV_HAZARD if loss >= 2 else HEV_AMBER)

        sort = snap.get("sortino", 0) or 0
        set_bar(*gauges["sortino"], max(0, min(1, sort / 3)), f"{sort:.2f}",
                color=HEV_GREEN if sort > 1 else HEV_AMBER)

        trades = snap.get("trades_count", 0) or 0
        set_bar(*gauges["trades"], min(1, trades / 40), str(trades))

    app._alch_tick.register(update)


def _init_panel_basis(app):
    frame = app._alch_p3
    canvas = tk.Canvas(frame, bg=HEV_PANEL, highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=2, pady=2)

    legend = tk.Frame(frame, bg=HEV_PANEL)
    legend.pack(fill="x", padx=2)
    tk.Label(legend, text="BTC", font=font("mono", 8),
             fg=HEV_AMBER, bg=HEV_PANEL).pack(side="right", padx=3)
    tk.Label(legend, text="ETH", font=font("mono", 8),
             fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="right", padx=3)
    tk.Label(legend, text="SOL", font=font("mono", 8),
             fg=HEV_GREEN, bg=HEV_PANEL).pack(side="right", padx=3)
    stats = tk.Label(legend, text="σ=— μ=—", font=font("mono", 8),
                     fg=HEV_AMBER_D, bg=HEV_PANEL)
    stats.pack(side="left", padx=3)

    def update(snap):
        canvas.delete("all")
        W = canvas.winfo_width() or 400
        H = canvas.winfo_height() or 140
        if W < 10 or H < 10:
            return

        history = snap.get("basis_history", {}) or {}
        symbols = [("BTCUSDT", HEV_AMBER), ("ETHUSDT", HEV_HAZARD), ("SOLUSDT", HEV_GREEN)]

        # Zero line
        canvas.create_line(0, H/2, W, H/2, fill=HEV_AMBER_DD, dash=(3, 4))

        # Collect all values to find global range
        all_vals = []
        for sym, _ in symbols:
            for _, v in history.get(sym, []) or []:
                try:
                    all_vals.append(float(v))
                except (TypeError, ValueError):
                    pass
        if not all_vals:
            canvas.create_text(W/2, H/2, text="no basis data yet",
                               fill=HEV_AMBER_D, font=font("mono", 9))
            stats.configure(text="σ=— μ=—")
            return

        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 0.0001)
        for sym, color in symbols:
            pts = history.get(sym, []) or []
            if len(pts) < 2:
                continue
            coords = []
            for i, (_, v) in enumerate(pts):
                try:
                    vf = float(v)
                except (TypeError, ValueError):
                    continue
                x = (i / (len(pts) - 1)) * W if len(pts) > 1 else W/2
                y = H - ((vf - lo) / span * H)
                coords += [x, y]
            if len(coords) >= 4:
                canvas.create_line(*coords, fill=color, width=1, smooth=False)

        import statistics as _st
        mu = _st.mean(all_vals)
        sigma = _st.pstdev(all_vals) if len(all_vals) > 1 else 0
        stats.configure(text=f"σ={sigma:.4f} μ={mu:+.4f}")

    app._alch_tick.register(update)


def _init_panel_connections(app):
    frame = app._alch_p6
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=3, pady=2)

    from core.connections import ConnectionManager
    conn = ConnectionManager()

    venues = [
        ("binance_futures", "binance",     "Binance"),
        ("bybit",           "bybit",       "Bybit"),
        ("okx",             "okx",         "OKX"),
        ("hyperliquid",     "hyperliquid", "Hyperliquid"),
        ("gate",            "gate",        "Gate.io"),
    ]

    rows = {}
    for conn_key, glyph_key, label in venues:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x", pady=0)
        dot = tk.Label(row, text="●", font=font("mono_px", 10),
                       fg=HEV_DIM, bg=HEV_PANEL)
        dot.pack(side="left")
        tk.Label(row, text=label, width=11, anchor="w",
                 font=font("mono", 9), fg=HEV_AMBER, bg=HEV_PANEL).pack(side="left")
        mode_lbl = tk.Label(row, text="—", font=font("mono", 8),
                            fg=HEV_AMBER_D, bg=HEV_PANEL)
        mode_lbl.pack(side="right")
        rows[conn_key] = (dot, mode_lbl)

    def update(snap):
        try:
            conn_state = conn._load()
        except Exception:
            conn_state = {"connections": {}}
        health = snap.get("venue_health", {}) or {}
        for conn_key, (dot, mode_lbl) in rows.items():
            c = (conn_state.get("connections", {}) or {}).get(conn_key, {}) or {}
            connected = c.get("connected", False)
            mode = c.get("mode", "—")
            glyph_key = conn_key.replace("_futures", "")
            disabled = (health.get(glyph_key, {}) or {}).get("disabled", False)
            if disabled:
                dot.configure(fg=HEV_RED)
                mode_lbl.configure(text="OFFLINE", fg=HEV_RED)
            elif connected:
                dot.configure(fg=HEV_GREEN)
                mode_lbl.configure(text=str(mode).upper(), fg=HEV_GREEN)
            else:
                dot.configure(fg=HEV_DIM)
                mode_lbl.configure(text="IDLE", fg=HEV_AMBER_D)
    app._alch_tick.register(update)


def _init_panel_engine(app):
    frame = app._alch_p7
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=4, pady=1)

    # Left: buttons
    btn_row = tk.Frame(inner, bg=HEV_PANEL)
    btn_row.pack(side="left", fill="y")

    from core.alchemy_state import AlchemyState
    state = AlchemyState()

    def _start_engine(mode):
        if mode == "live":
            from tkinter import simpledialog
            answer = simpledialog.askstring(
                "LIVE MODE",
                "REAL CAPITAL AT RISK.\nType 'LIVE' to confirm:",
                parent=app)
            if answer != "LIVE":
                return
        if app.proc and app.proc.poll() is None:
            try: app._stop()
            except Exception: pass
        import subprocess, sys as _sys
        from datetime import datetime as _dt
        _NO_WIN = subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0
        app._alch_engine_mode = mode
        run_id = _dt.now().strftime("%Y-%m-%d_%H%M")
        try:
            app.proc = subprocess.Popen(
                [_sys.executable, "engines/janestreet.py", "--mode", mode, "--run-id", run_id],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, text=True, bufsize=1,
                creationflags=_NO_WIN,
            )
        except Exception as e:
            app._alch_log_buf.append(f"spawn failed: {e}")
            return

        from pathlib import Path as _P
        try:
            app._alch_state.pin_run(_P(f"data/janestreet/{run_id}"))
        except Exception:
            pass

        import threading as _th
        def _reader():
            try:
                for line in iter(app.proc.stdout.readline, ""):
                    app._alch_log_buf.append(line.rstrip())
                    if len(app._alch_log_buf) > 500:
                        app._alch_log_buf.pop(0)
                try: app.proc.stdout.close()
                except Exception: pass
            except Exception as e:
                app._alch_log_buf.append(f"reader error: {e}")
        _th.Thread(target=_reader, daemon=True).start()

    def _stop_engine():
        if app.proc and app.proc.poll() is None:
            try: app._stop()
            except Exception: pass
        app._alch_engine_mode = None
        try: app._alch_state.unpin_run()
        except Exception: pass

    def _kill_engine():
        _stop_engine()
        app._alch_log_buf.append("KILL invoked")

    def _mk_btn(text, handler, danger=False):
        bg = "#1a0000" if danger else "#0a0500"
        border = HEV_BLOOD if danger else HEV_AMBER_D
        fg = HEV_RED if danger else HEV_AMBER
        b = tk.Label(btn_row, text=text, font=font("mono_px", 10),
                     fg=fg, bg=bg, padx=6, pady=1,
                     highlightthickness=1, highlightbackground=border)
        b.pack(side="left", padx=1)
        b.bind("<Button-1>", lambda e: handler())
        return b

    _mk_btn("> PAPER",   lambda: _start_engine("paper"))
    _mk_btn("> DEMO",    lambda: _start_engine("demo"))
    _mk_btn("> TESTNET", lambda: _start_engine("testnet"))
    _mk_btn("> LIVE",    lambda: _start_engine("live"), danger=True)
    _mk_btn("# STOP",    _stop_engine)
    _mk_btn("! KILL",    _kill_engine, danger=True)

    # Right: editable params (inline, compact)
    params_row = tk.Frame(inner, bg=HEV_PANEL)
    params_row.pack(side="left", padx=8, fill="y")

    PARAMS = [
        ("MIN_APR",    "40.0"),
        ("MIN_SPREAD", ".0015"),
        ("MAX_POS",    "5"),
        ("POS_PCT",    "0.20"),
        ("LEV",        "2"),
        ("SCAN_S",     "30"),
        ("EXIT_H",     "8"),
        ("MAX_DD_PCT", "0.05"),
    ]
    labels = {}
    for key, default in PARAMS:
        cell = tk.Frame(params_row, bg=HEV_PANEL)
        cell.pack(side="left", padx=4)
        tk.Label(cell, text=key, font=font("mono", 7),
                 fg=HEV_AMBER_D, bg=HEV_PANEL).pack()
        val = tk.Label(cell, text=default, font=font("mono_px", 10),
                       fg=HEV_AMBER, bg=HEV_PANEL, cursor="xterm")
        val.pack()
        labels[key] = val

        def _make_editor(k, lbl):
            def _edit(event):
                entry = tk.Entry(lbl.master, font=font("mono_px", 10),
                                 fg=HEV_HAZARD, bg="#1a1000",
                                 insertbackground=HEV_AMBER, width=7)
                entry.insert(0, lbl.cget("text").rstrip("%x "))
                lbl.pack_forget()
                entry.pack()
                entry.focus_set()
                def _commit(event=None):
                    new_val = entry.get().strip()
                    try:
                        v = float(new_val) if "." in new_val or k in ("MIN_SPREAD", "POS_PCT", "MAX_DD_PCT") else int(new_val)
                        state.write_params({k: v})
                        lbl.configure(text=str(v))
                    except ValueError:
                        pass
                    try: entry.destroy()
                    except Exception: pass
                    lbl.pack()
                entry.bind("<Return>", _commit)
                entry.bind("<FocusOut>", _commit)
                entry.bind("<Escape>", lambda e: (entry.destroy(), lbl.pack()))
            return _edit
        val.bind("<Button-1>", _make_editor(key, val))

    # Load current params on init
    try:
        current = state.read_params()
        for k, lbl in labels.items():
            if k in current:
                lbl.configure(text=str(current[k]))
    except Exception:
        pass


def _init_panel_log(app):
    frame = app._alch_p9
    text = tk.Text(frame, bg=HEV_PANEL, fg=HEV_AMBER_B,
                   font=font("mono", 8), relief="flat",
                   borderwidth=0, highlightthickness=0,
                   wrap="none", state="disabled")
    text.pack(fill="both", expand=True, padx=2, pady=2)
    text.tag_config("info", foreground=HEV_AMBER_B)
    text.tag_config("ok",   foreground=HEV_GREEN)
    text.tag_config("warn", foreground=HEV_HAZARD)
    text.tag_config("err",  foreground=HEV_RED)
    text.tag_config("dim",  foreground=HEV_AMBER_D)

    def classify(line):
        lo = (line or "").lower()
        if "error" in lo or "fail" in lo:
            return "err"
        if "warn" in lo or "rate limit" in lo:
            return "warn"
        if "opened" in lo or "closed" in lo or "reloaded" in lo:
            return "ok"
        return "info"

    def update(snap):
        text.configure(state="normal")
        text.delete("1.0", "end")
        buf = getattr(app, "_alch_log_buf", []) or []
        tail = buf[-15:]
        for line in tail:
            tag = classify(line)
            text.insert("end", (line or "") + "\n", tag)
        text.configure(state="disabled")

    app._alch_tick.register(update)
