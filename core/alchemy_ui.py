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
