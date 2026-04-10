"""ALCHEMY — Half-Life HEV Terminal cockpit for arbitrage.

9 panels, fullscreen, dense amber-on-black. Reads live state via AlchemyState
and controls engines/arbitrage.py via parameter hot-reload and subprocess.
"""
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable

# ═══════════════════════════════════════════════════════════
# PALETTE — HEV TERMINAL (Half-Life 1 amber on black)
# ═══════════════════════════════════════════════════════════
HEV_BG      = "#000000"
HEV_PANEL   = "#030200"
HEV_BORDER  = "#3a2200"
HEV_BORDER2 = "#5a3300"
HEV_AMBER   = "#ff8c00"
HEV_AMBER_B = "#ffb347"
HEV_AMBER_D = "#7a4400"
HEV_AMBER_DD= "#3a2200"
HEV_WHITE   = "#d8d8d8"
HEV_DIM     = "#5a3300"
HEV_GREEN   = "#00c040"
HEV_RED     = "#e03030"
HEV_HAZARD  = "#ffcc00"
HEV_BLOOD   = "#8b0000"

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

    # Corner brackets (top-left, bottom-right)
    tk.Frame(wrap, bg=HEV_AMBER, width=10, height=2).place(x=0, y=0)
    tk.Frame(wrap, bg=HEV_AMBER, width=2, height=10).place(x=0, y=0)
    tk.Frame(wrap, bg=HEV_AMBER, width=10, height=2).place(relx=1, rely=1, x=-10, y=-2)
    tk.Frame(wrap, bg=HEV_AMBER, width=2, height=10).place(relx=1, rely=1, x=-2, y=-10)

    # Title bar
    title_bar = tk.Frame(wrap, bg=HEV_PANEL, height=22)
    title_bar.pack(fill="x", padx=1, pady=(1, 0))
    title_bar.pack_propagate(False)

    tk.Label(title_bar, text=f"[{panel_id:02d}] {title}",
             font=font("mono_px", 15), fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left", padx=6)
    tk.Label(title_bar, text=PANEL_LATIN.get(panel_id, ""),
             font=font("mono", 11, "italic"), fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="right", padx=6)

    # Dashed divider (simulate with thin frame)
    tk.Frame(wrap, bg=HEV_AMBER_DD, height=1).pack(fill="x", padx=6)

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
    """Paint the 9-panel HEV cockpit. Root frame is app.main."""
    import datetime as _dt
    root = app.main
    root.configure(bg=HEV_BG)

    # λ watermark (placed first so it's behind everything)
    try:
        tk.Label(root, text="λ", font=(_FONT_CACHE.get("serif", "Georgia"), 520),
                 fg="#0a0500", bg=HEV_BG).place(relx=0.78, rely=0.55, anchor="center")
    except Exception:
        pass

    # Top hazard stripe
    top_haz = hazard_strip(root, height=10)
    top_haz.pack(fill="x")

    # Vitals top bar
    topbar = tk.Frame(root, bg=HEV_BG, height=56)
    topbar.pack(fill="x")
    topbar.pack_propagate(False)

    tk.Label(topbar, text="λ ALCHEMY", font=font("serif", 20, "bold"),
             fg=HEV_AMBER_B, bg=HEV_BG).pack(side="left", padx=18)

    app._alch_clock = tk.Label(topbar, text="", font=font("mono", 12),
                               fg=HEV_AMBER_D, bg=HEV_BG)
    app._alch_clock.pack(side="left", padx=12)

    vitals_frame = tk.Frame(topbar, bg=HEV_BG)
    vitals_frame.pack(side="right", padx=18)

    app._alch_vitals = {}
    for key, label in [
        ("account",   "ACCOUNT"),
        ("drawdown",  "DRAWDOWN"),
        ("positions", "POSITIONS"),
        ("exposure",  "EXPOSURE"),
        ("mode",      "MODE"),
        ("engine",    "ENGINE"),
    ]:
        cell = tk.Frame(vitals_frame, bg=HEV_BG)
        cell.pack(side="left", padx=14)
        tk.Label(cell, text=label, font=font("serif", 9),
                 fg=HEV_AMBER_D, bg=HEV_BG).pack(anchor="e")
        v = tk.Label(cell, text="—", font=font("mono_px", 22),
                     fg=HEV_AMBER, bg=HEV_BG)
        v.pack(anchor="e")
        app._alch_vitals[key] = v

    # Thin amber separator below topbar
    tk.Frame(root, bg=HEV_AMBER_D, height=1).pack(fill="x")

    # ── Cockpit body (grid of 9 panels) ──
    body = tk.Frame(root, bg=HEV_BG)
    body.pack(fill="both", expand=True, padx=4, pady=4)
    body.grid_columnconfigure(0, weight=26, uniform="col")
    body.grid_columnconfigure(1, weight=48, uniform="col")
    body.grid_columnconfigure(2, weight=26, uniform="col")
    body.grid_rowconfigure(0, weight=5, uniform="row")
    body.grid_rowconfigure(1, weight=5, uniform="row")
    body.grid_rowconfigure(2, weight=3, uniform="row")
    body.grid_rowconfigure(3, minsize=70)
    app._alch_body = body

    # Vitals updater
    def update_vitals(snap):
        app._alch_clock.configure(
            text=_dt.datetime.utcnow().strftime("%Y.%m.%d · %H:%M:%S UTC"))
        app._alch_vitals["account"].configure(text=f"${snap.get('account',0):,.0f}")
        dd = snap.get("drawdown_pct", 0) or 0
        app._alch_vitals["drawdown"].configure(
            text=f"{dd:+.2f}%",
            fg=HEV_GREEN if dd > -1 else (HEV_HAZARD if dd > -3 else HEV_RED))
        n = len(snap.get("positions", []) or [])
        app._alch_vitals["positions"].configure(text=f"{n} / 5")
        app._alch_vitals["exposure"].configure(text=f"${snap.get('exposure_usd',0) or 0:,.0f}")
        mode = (snap.get("mode", "—") or "—").upper()
        app._alch_vitals["mode"].configure(
            text=mode,
            fg=HEV_HAZARD if mode == "PAPER" else (HEV_RED if mode == "LIVE" else HEV_AMBER_B))
        running = bool(snap.get("engine_pid", 0)) and not snap.get("_stale", True)
        app._alch_vitals["engine"].configure(
            text="▶ RUN" if running else "■ IDLE",
            fg=HEV_GREEN if running else HEV_DIM)
    app._alch_tick.register(update_vitals)

    # Bottom hazard stripe
    bot_haz = hazard_strip(root, height=10)
    bot_haz.pack(side="bottom", fill="x")

    # Create the 9 panel frames with make_panel
    for pid, row, col, rowspan, title in [
        (1, 0, 0, 2, "OPPORTVNITATES"),
        (2, 0, 1, 1, "FVNDING · RATES"),
        (3, 1, 1, 1, "BASIS · PERP / SPOT"),
        (4, 0, 2, 1, "POSITIONES"),
        (5, 1, 2, 1, "VENVE · HEALTH"),
        (8, 2, 0, 1, "RISK · CONSOLE"),
        (9, 2, 1, 1, "LOG · STREAM"),
        (6, 2, 2, 1, "CONNECTIONES"),
        (7, 3, 0, 1, "MACHINA · ENGINE CONTROL"),
    ]:
        colspan = 3 if pid == 7 else 1
        body_frame = make_panel(body, pid, title,
                                row=row, column=col,
                                rowspan=rowspan, columnspan=colspan,
                                sticky="nsew", padx=2, pady=2)
        setattr(app, f"_alch_p{pid}", body_frame)

    _init_panel_opportunities(app)
    _init_panel_positions(app)
    _init_panel_venue_health(app)
    _init_panel_funding(app)
    _init_panel_risk(app)


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
    hdr.pack(fill="x", padx=4, pady=(2, 0))
    for txt, w in zip(header, widths):
        tk.Label(hdr, text=txt, width=w, anchor="w",
                 font=font("mono", 11), fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="left")

    body = tk.Frame(parent, bg=HEV_PANEL)
    body.pack(fill="both", expand=True, padx=4)

    def update(rows, colors=None):
        for child in body.winfo_children():
            child.destroy()
        for i, row in enumerate(rows):
            row_colors = colors[i] if colors and i < len(colors) else [None] * len(row)
            row_frame = tk.Frame(body, bg=HEV_PANEL)
            row_frame.pack(fill="x")
            for txt, w, c in zip(row, widths, row_colors):
                tk.Label(row_frame, text=str(txt), width=w, anchor="w",
                         font=font("mono_px", 14),
                         fg=c or HEV_AMBER, bg=HEV_PANEL).pack(side="left")
    return body, update


def _init_panel_opportunities(app):
    frame = app._alch_p1
    _, update_rows = _render_table(
        frame,
        header=["#", "SYM", "LONG", "SHORT", "SPRD", "APR", "Ω"],
        widths=[3, 10, 6, 6, 8, 8, 5],
    )
    def update(snap):
        opps = snap.get("opportunities", []) or []
        opps = opps[:12]
        rows, colors = [], []
        for i, o in enumerate(opps, 1):
            long_v = o.get("long", "") or ""
            short_v = o.get("short", "") or ""
            long_g = VENUE_GLYPH.get(long_v, "·") + long_v[:3].upper()
            short_g = VENUE_GLYPH.get(short_v, "·") + short_v[:3].upper()
            rows.append([
                f"{i:02d}",
                (o.get("sym", "—") or "—")[:9],
                long_g,
                short_g,
                f"{(o.get('spread') or 0)*100:+.4f}",
                f"{o.get('apr') or 0:.1f}%",
                f"{o.get('omega') or 0:.1f}",
            ])
            omega_val = o.get('omega') or 0
            c = HEV_AMBER if omega_val < 7 else HEV_HAZARD
            colors.append([HEV_AMBER_D, HEV_HAZARD, HEV_AMBER, HEV_AMBER, HEV_GREEN, HEV_GREEN, c])
        if not rows:
            rows = [["—", "no opportunities", "", "", "", "", ""]]
            colors = [[HEV_DIM] * 7]
        update_rows(rows, colors)
    app._alch_tick.register(update)


def _init_panel_positions(app):
    frame = app._alch_p4
    _, update_rows = _render_table(
        frame,
        header=["SYM", "VENUES", "PNL", "ΔEDGE", "EXIT"],
        widths=[8, 8, 10, 8, 8],
    )
    def update(snap):
        poss = snap.get("positions", []) or []
        rows, colors = [], []
        for p in poss:
            long_g = VENUE_GLYPH.get(p.get("long", "") or "", "·")
            short_g = VENUE_GLYPH.get(p.get("short", "") or "", "·")
            pnl = p.get("pnl", 0) or 0
            exit_s = p.get("exit_in_s", 0) or 0
            h, rem = divmod(int(exit_s), 3600)
            m = rem // 60
            rows.append([
                (p.get("sym", "—") or "—")[:7],
                f"{long_g}/{short_g}",
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
            rows = [["—", "no positions", "", "", ""]]
            colors = [[HEV_DIM] * 5]
        update_rows(rows, colors)
    app._alch_tick.register(update)


def _init_panel_venue_health(app):
    frame = app._alch_p5
    _, update_rows = _render_table(
        frame,
        header=["VEN", "PING", "ERR", "RL", "KS"],
        widths=[10, 7, 5, 7, 6],
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
                f"{VENUE_GLYPH.get(v, '·')} {v[:6].upper()}",
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
    inner.pack(fill="both", expand=True, padx=4, pady=4)

    venues = ["binance", "bybit", "okx", "hyperliquid", "gate"]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT"]

    cells = {}
    # Header row
    hdr = tk.Frame(inner, bg=HEV_PANEL); hdr.pack(fill="x")
    tk.Label(hdr, text="·", width=6, font=font("mono_px", 12),
             fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="left")
    for v in venues:
        tk.Label(hdr, text=f"{VENUE_GLYPH.get(v, '·')} {v[:3].upper()}",
                 width=9, font=font("serif", 10, "bold"),
                 fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left")

    for sym in symbols:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x")
        tk.Label(row, text=sym.replace("USDT", ""), width=6,
                 font=font("mono_px", 13), fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left")
        cells[sym] = {}
        for v in venues:
            lbl = tk.Label(row, text="—", width=9,
                           font=font("mono_px", 13), fg=HEV_AMBER_D, bg="#0a0500")
            lbl.pack(side="left", padx=1)
            cells[sym][v] = lbl

    footer = tk.Label(inner, text="", font=font("mono", 10),
                      fg=HEV_AMBER_D, bg=HEV_PANEL, anchor="e")
    footer.pack(fill="x", pady=(4, 0))

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
    inner.pack(fill="both", expand=True, padx=6, pady=4)

    gauges = {}
    for key, label in [
        ("expo",    "EXPO"),
        ("dd_day",  "DD DAY"),
        ("dd_max",  "DD MAX"),
        ("losses",  "LOSSES"),
        ("sortino", "SORTINO"),
        ("trades",  "TRADES"),
    ]:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x", pady=1)
        tk.Label(row, text=label, width=9, font=font("serif", 9),
                 fg=HEV_AMBER_D, bg=HEV_PANEL, anchor="w").pack(side="left")
        bar_wrap = tk.Frame(row, bg="#1a0f00", height=8, highlightthickness=1,
                            highlightbackground=HEV_AMBER_DD)
        bar_wrap.pack(side="left", fill="x", expand=True, padx=4)
        bar_wrap.pack_propagate(False)
        fill = tk.Frame(bar_wrap, bg=HEV_AMBER)
        fill.place(x=0, y=0, relheight=1, relwidth=0)
        val = tk.Label(row, text="—", width=8, font=font("mono_px", 12),
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
