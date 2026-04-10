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
# COCKPIT RENDER (stub — replaced in Task 9)
# ═══════════════════════════════════════════════════════════

def render_cockpit(app):
    """Paint the 9-panel HEV cockpit. Called by launcher _alchemy_enter.

    STUB: replaced in Task 9 with the real grid. Used here to verify menu wiring.
    """
    root = app.main
    root.configure(bg=HEV_BG)
    tk.Label(root, text="λ ALCHEMY · HEV TERMINAL ONLINE",
             font=font("mono_px", 40), fg=HEV_AMBER, bg=HEV_BG).pack(expand=True)
    tk.Label(root, text="[ESC] to exit · panels coming next task",
             font=font("mono", 14), fg=HEV_AMBER_D, bg=HEV_BG).pack()
