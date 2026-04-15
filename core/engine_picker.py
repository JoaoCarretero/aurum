"""
AURUM Finance — Shared Engine Picker (cyberpunk)
=================================================
Compact track-listing component for selecting trading engines.

Layout:
  • Left column  — grouped track list (BACKTEST · LIVE · TOOLS)
  • Right column — detail panel with clickable chips:
      [ OVERVIEW ]  [ CONFIG ]  [ CODE ]  [ RUN ]
    All content stays on the page — nothing navigates away.

Used by:
  • launcher._strategies        → substitui a lista de estratégias
  • macro_brain.dashboard_view  → tab ENGINES

Métricas / code / run são incrementais — caller fornece o que tiver.
"""
from __future__ import annotations

import json
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

# ── PALETTE (cyberpunk) ──────────────────────────────────────
BG       = "#080808"
PANEL    = "#0C0C0C"
BG2      = "#101010"
BG3      = "#181818"
BORDER   = "#242424"
BORDER_H = "#5A5A5A"
WHITE    = "#E6E6E6"
DIM      = "#707070"
DIM2     = "#9A9A9A"
AMBER    = "#C8C8C8"
AMBER_H  = "#F0F0F0"
GREEN    = "#00D26A"
RED      = "#FF4D4F"
CYAN     = "#A8A8A8"
FONT     = "Consolas"
GLOW     = "#141414"

_STATE_COLORS = {
    "running": GREEN,
    "idle":    DIM2,
    "error":   RED,
    "unknown": DIM,
}
_REGIME_COLORS = {
    "BULL": GREEN,
    "BEAR": RED,
    "CHOP": AMBER,
}

# Inline config options (mirrors launcher's PERIODS_UI / BASKETS_UI)
PERIOD_OPTS   = [("30D", "30"), ("90D", "90"), ("180D", "180"), ("365D", "365")]
BASKET_OPTS   = [
    ("DEFAULT", ""), ("TOP12", "2"), ("DEFI", "3"), ("L1", "4"),
    ("L2", "5"), ("AI", "6"), ("MEME", "7"), ("MAJORS", "8"),
    ("BLUECHIP", "9"),
]
LEVERAGE_OPTS = [("1x", "1.0"), ("2x", "2.0"), ("3x", "3.0"), ("5x", "5.0")]


def _bright(hex_color: str, factor: float = 1.2) -> str:
    """Lighten an #rrggbb color by factor (>1 brightens, <1 darkens)."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        r = max(0, min(255, int(r * factor)))
        g = max(0, min(255, int(g * factor)))
        b = max(0, min(255, int(b * factor)))
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


def _format_track_subtitle(bc: Optional[dict], t: "EngineTrack") -> str:
    """Build a compact subtitle line for a track row.

    Reads brief['best_config'] (battery-validated stats) when available.
    Falls back to track.tagline truncated. Formats like:
        '15m · Sh 4.43 · 256t'  or  '4h · marginal'
    """
    if bc:
        parts: list[str] = []
        tf = bc.get("TF")
        if tf:
            parts.append(str(tf).split()[0])
        sharpe_val = bc.get("Sharpe val")
        if sharpe_val:
            s = str(sharpe_val).split()[0].strip()
            try:
                parts.append(f"Sh {float(s):.2f}")
            except ValueError:
                parts.append(f"Sh {s}")
        status = bc.get("Status")
        if status:
            tag = "EDGE" if "✓" in status else "MARG" if "⚠" in status else "NO-EDGE" if "✗" in status else ""
            if tag:
                parts.append(tag)
        if parts:
            return " · ".join(parts)
    # Fallback: trimmed tagline
    if t.tagline:
        return t.tagline[:44]
    return ""


def _section(parent, title):
    """Amber-bar section header (Bloomberg style)."""
    tk.Frame(parent, bg=PANEL, height=8).pack()
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x")
    tk.Frame(row, bg=AMBER, width=3).pack(side="left", fill="y")
    tk.Label(row, text=f" {title} ", font=(FONT, 7, "bold"),
             fg=AMBER, bg=PANEL, anchor="w", padx=4).pack(
        side="left", fill="x", expand=True)
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))


def _scrollable(parent):
    """Return an inner Frame that scrolls vertically inside parent."""
    outer = tk.Frame(parent, bg=PANEL)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=PANEL, highlightthickness=0)
    sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=PANEL)
    inner.bind("<Configure>",
               lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    win = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=sb.set)
    def _resize(e):
        canvas.itemconfig(win, width=e.width)
    canvas.bind("<Configure>", _resize)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    def _wheel(e):
        try: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception: pass
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
    return inner


@dataclass
class EngineTrack:
    slug: str
    name: str
    group: str = "ENGINES"
    tagline: str = ""
    script_path: str = ""            # absolute or repo-relative path
    status: str = "idle"             # idle | running | error | unknown
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    max_dd: Optional[float] = None
    win_rate: Optional[float] = None
    regime: Optional[str] = None
    last_signal: Optional[str] = None
    last_signal_age: Optional[str] = None
    equity_series: Optional[list] = None
    on_run: Optional[Callable] = None
    on_stop: Optional[Callable] = None
    on_config: Optional[Callable] = None
    # Optional brief metadata (philosophy, pipeline, edge, risk, best_config)
    brief: Optional[dict] = None


# ── DEFAULT GROUP MAPPING ────────────────────────────────────
DEFAULT_GROUPS = {
    "citadel":     "BACKTEST",
    "renaissance": "BACKTEST",
    "jump":        "BACKTEST",
    "bridgewater": "BACKTEST",
    "deshaw":      "BACKTEST",
    "millennium":  "BACKTEST",
    "twosigma":    "BACKTEST",
    "live":        "LIVE",
    "janestreet":  "LIVE",
    "aqr":         "TOOLS",
    "winton":      "TOOLS",
}
GROUP_ORDER = ("BACKTEST", "LIVE", "TOOLS")

# Explicit sort weight per slug so we can promote validated engines (e.g.
# RENAISSANCE just above MILLENNIUM) instead of relying on alphabetical.
# Lower weight = appears earlier. Anything not listed falls back to alpha.
TRACK_SORT_WEIGHT = {
    "citadel":     10,
    "bridgewater": 20,
    "deshaw":      30,
    "jump":        40,
    "renaissance": 50,
    "millennium":  60,
    "twosigma":    70,
    "live":        80,
    "janestreet":  90,
    "aqr":        100,
    "winton":     110,
}
MODULE_INFO = {
    "BACKTEST": {
        "label": "TEST",
        "desc": "rodar e medir",
        "accent": "#4DA3FF",
    },
    "TOOLS": {
        "label": "VALIDATE",
        "desc": "validar e calibrar",
        "accent": "#E0B94B",
    },
    "LIVE": {
        "label": "EXECUTE",
        "desc": "paper e live",
        "accent": "#00D26A",
    },
}


def build_tracks_from_registry(
    registry: dict,
    on_run_for: Optional[Callable[[str, dict], Optional[Callable]]] = None,
    on_stop_for: Optional[Callable[[str, dict], Optional[Callable]]] = None,
    on_config_for: Optional[Callable[[str, dict], Optional[Callable]]] = None,
    brief_for: Optional[Callable[[str, dict], Optional[dict]]] = None,
    groups: Optional[dict[str, str]] = None,
) -> list[EngineTrack]:
    gmap = groups or DEFAULT_GROUPS
    tracks: list[EngineTrack] = []
    for slug, meta in registry.items():
        tracks.append(EngineTrack(
            slug=slug,
            name=meta.get("display", slug.upper()),
            group=gmap.get(slug, "ENGINES"),
            tagline=meta.get("desc", ""),
            script_path=meta.get("script", ""),
            on_run=on_run_for(slug, meta) if on_run_for else None,
            on_stop=on_stop_for(slug, meta) if on_stop_for else None,
            on_config=on_config_for(slug, meta) if on_config_for else None,
            brief=brief_for(slug, meta) if brief_for else None,
        ))
    order_idx = {g: i for i, g in enumerate(GROUP_ORDER)}
    tracks.sort(key=lambda t: (
        order_idx.get(t.group, 99),
        TRACK_SORT_WEIGHT.get(t.slug, 999),
        t.name,
    ))
    return tracks


# ── LOGO (compact AURUM mark, drawn on a tk.Canvas) ──────────
def _draw_logo(cv: tk.Canvas, size: int = 18):
    """Minimal A-pyramid mark in the accent color."""
    cv.delete("all")
    s = size
    # outer A
    cv.create_polygon(
        s * 0.50, s * 0.10,
        s * 0.90, s * 0.90,
        s * 0.65, s * 0.90,
        s * 0.58, s * 0.66,
        s * 0.42, s * 0.66,
        s * 0.35, s * 0.90,
        s * 0.10, s * 0.90,
        fill=AMBER, outline="",
    )
    # inner dart
    cv.create_polygon(
        s * 0.50, s * 0.10,
        s * 0.90, s * 0.90,
        s * 0.74, s * 0.90,
        s * 0.50, s * 0.38,
        fill=AMBER_H, outline="",
    )


# ── RENDER ───────────────────────────────────────────────────
def render(
    parent: tk.Widget,
    tracks: list[EngineTrack],
    on_select: Optional[Callable[[EngineTrack], None]] = None,
    show_modules: bool = False,
    mode: str = "backtest",
) -> dict[str, Any]:
    """Render the iPod-style engine picker.

    ``show_modules``: when True, shows the TEST/VALIDATE/EXECUTE cards in
    the left column header. Launcher now handles group switching via the
    top-nav BACKTEST/ENGINES buttons and segmented toggle, so the default
    is False (hidden) — the cards are redundant and visually noisy.

    ``mode``: 'backtest' (default) shows RUN CUSTOM / RUN CALIBRATED. 'live'
    shows PAPER / DEMO / TESTNET / LIVE pills — the on_run callback gets
    cfg['preset'] = the chosen mode string ('paper' / 'demo' / 'testnet' /
    'live'). Caller is responsible for dispatching to the right runner.
    """
    for w in parent.winfo_children():
        try: w.destroy()
        except Exception: pass

    root = tk.Frame(parent, bg=BG)
    root.pack(fill="both", expand=True)
    tk.Frame(root, bg=AMBER, height=1).pack(fill="x", pady=(0, 6))

    split = tk.Frame(root, bg=BG)
    split.pack(fill="both", expand=True)

    # ── LEFT COLUMN ──────────────────────────────
    left = tk.Frame(split, bg=PANEL, width=252,
                    highlightbackground=BORDER, highlightthickness=1)
    left.pack(side="left", fill="y", padx=(0, 8))
    left.pack_propagate(False)

    # Header: logo + wordmark + engine count
    top = tk.Frame(left, bg=BG2)
    top.pack(fill="x")
    tk.Frame(top, bg=GLOW, height=3).pack(fill="x")
    head = tk.Frame(top, bg=BG2)
    head.pack(fill="x", padx=6, pady=(5, 4))
    logo_cv = tk.Canvas(head, width=20, height=20,
                        bg=BG2, highlightthickness=0)
    logo_cv.pack(side="left", padx=(0, 6), pady=0)
    logo_cv.after(10, lambda: _draw_logo(logo_cv, 20))
    word = tk.Frame(head, bg=BG2)
    word.pack(side="left", fill="x", expand=True)
    tk.Label(word, text="AURUM", font=(FONT, 9, "bold"),
             fg=AMBER, bg=BG2, anchor="w").pack(fill="x")
    tk.Label(word, text="strategy desk / engine picker", font=(FONT, 7),
             fg=DIM, bg=BG2, anchor="w").pack(fill="x")
    badge = tk.Frame(head, bg=BG3, highlightbackground=BORDER, highlightthickness=1)
    badge.pack(side="right")
    tk.Label(badge, text=f"{len(tracks):02d} TRACKS", font=(FONT, 7, "bold"),
             fg=WHITE, bg=BG3, padx=6, pady=4).pack()

    tk.Frame(left, bg=AMBER, height=1).pack(fill="x", pady=(0, 1))

    # TEST/VALIDATE/EXECUTE cards — optional, hidden by default because the
    # top-nav BACKTEST/ENGINES buttons already route by group.
    modules = tk.Frame(left, bg=PANEL)
    if show_modules:
        modules.pack(fill="x", padx=6, pady=(6, 6))

    # List + scrollbar
    list_wrap = tk.Frame(left, bg=PANEL)
    list_wrap.pack(fill="both", expand=True)
    canvas = tk.Canvas(list_wrap, bg=PANEL, highlightthickness=0)
    scrollbar = tk.Scrollbar(list_wrap, orient="vertical",
                             command=canvas.yview)
    track_list = tk.Frame(canvas, bg=PANEL)
    track_list.bind("<Configure>",
                    lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas_win = canvas.create_window((0, 0), window=track_list, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    def _resize(e):
        canvas.itemconfig(canvas_win, width=e.width)
    canvas.bind("<Configure>", _resize)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    # ── RIGHT COLUMN ─────────────────────────────
    right = tk.Frame(split, bg=PANEL,
                     highlightbackground=BORDER, highlightthickness=1)
    right.pack(side="left", fill="both", expand=True)

    # Build list rows (compact)
    # Hide group header when only a single group is in view (filtered mode) —
    # the caller already set the context (BACKTEST / LIVE / ALL) via the top
    # nav, so the redundant header adds noise without signal.
    unique_groups = {t.group for t in tracks}
    show_group_header = len(unique_groups) > 1

    row_widgets: list[tuple[int, tk.Frame, tk.Label, EngineTrack, tk.Frame, tk.Frame]] = []
    current_group = None
    for idx, t in enumerate(tracks):
        if show_group_header and t.group != current_group:
            current_group = t.group
            hdr = tk.Frame(track_list, bg=BG)
            hdr.pack(fill="x", pady=(6, 1))
            tk.Frame(hdr, bg=AMBER, width=3).pack(side="left", fill="y")
            tk.Label(hdr, text=f" {t.group}", font=(FONT, 7, "bold"),
                     fg=AMBER, bg=BG, anchor="w").pack(
                side="left", fill="x", expand=True)
            count = sum(1 for x in tracks if x.group == t.group)
            tk.Label(hdr, text=f"{count} ", font=(FONT, 7),
                     fg=DIM, bg=BG).pack(side="right")

        row = tk.Frame(track_list, bg=PANEL,
                       highlightbackground=PANEL, highlightthickness=1)
        row.pack(fill="x", padx=4, pady=2)

        rail = tk.Frame(row, bg=PANEL, width=3)
        rail.pack(side="left", fill="y")

        led = tk.Label(row, text="●", font=(FONT, 9),
                       fg=_STATE_COLORS.get(t.status, DIM), bg=PANEL)
        led.pack(side="left", padx=(6, 4))

        num = tk.Label(row, text=f"{idx+1:02d}", font=(FONT, 7, "bold"),
                       fg=DIM, bg=PANEL)
        num.pack(side="left", padx=(0, 4))

        main = tk.Frame(row, bg=PANEL)
        main.pack(side="left", fill="x", expand=True, pady=4)
        lbl = tk.Label(main, text=t.name, font=(FONT, 9, "bold"),
                       fg=WHITE, bg=PANEL, anchor="w")
        lbl.pack(fill="x")

        # Subtitle — best_config summary (TF · Sharpe · trades) so the user
        # can scan the list like iPod tracks without opening each one.
        bc = (t.brief or {}).get("best_config") if t.brief else None
        subtitle = _format_track_subtitle(bc, t)
        if subtitle:
            sub = tk.Label(main, text=subtitle, font=(FONT, 7),
                           fg=DIM, bg=PANEL, anchor="w")
            sub.pack(fill="x")

        row_widgets.append((idx, row, lbl, t, rail, main))

    state = {
        "sel": 0,
        "chip": "OVERVIEW",
        "prog_pct": 0.0,
        "prog_tail": "",
        "running": False,
        "pulse": 0,
        "prog_by_slug": {},
        # Inline backtest config — persisted across chip switches
        "cfg_period":   "90",
        "cfg_basket":   "",
        "cfg_leverage": "",
        "cfg_plots":    "s",
    }
    group_indices = {
        group: next((i for i, t in enumerate(tracks) if t.group == group), None)
        for group in GROUP_ORDER
    }

    chip_host = {"frame": None}  # populated in _paint_detail
    chip_content_host = {"frame": None}

    def _apply_progress_from_selection():
        if not tracks:
            state["prog_pct"] = 0.0
            state["prog_tail"] = ""
            state["running"] = False
            return
        cur = tracks[state["sel"]]
        prog = state["prog_by_slug"].get(cur.slug, None)
        if prog is None:
            state["prog_pct"] = 0.0
            state["prog_tail"] = ""
            state["running"] = False
            return
        state["prog_pct"] = max(0.0, min(100.0, float(prog.get("pct", 0.0))))
        state["prog_tail"] = str(prog.get("tail", "") or "")[:240]
        state["running"] = bool(prog.get("running", False))

    def _is_track_running(track: EngineTrack) -> bool:
        prog = state["prog_by_slug"].get(track.slug, None)
        if prog is not None:
            return bool(prog.get("running", False))
        return track.status == "running"

    # ─── selection + scroll (bug fix: only scroll if offscreen)
    def _paint_sel():
        for i, row, lbl, _t, rail, main in row_widgets:
            accent = MODULE_INFO.get(_t.group, {}).get("accent", AMBER)
            running_now = _is_track_running(_t)
            if i == state["sel"]:
                row.config(bg=BG3, highlightbackground=AMBER,
                           highlightthickness=1)
                rail.config(bg=GREEN if running_now else accent)
                for w in row.winfo_children():
                    try: w.config(bg=BG3)
                    except Exception: pass
                for w in main.winfo_children():
                    try: w.config(bg=BG3)
                    except Exception: pass
                lbl.config(fg=GREEN if running_now else accent)
            else:
                row.config(bg=PANEL, highlightbackground=PANEL,
                           highlightthickness=1)
                rail.config(bg=PANEL)
                for w in row.winfo_children():
                    try: w.config(bg=PANEL)
                    except Exception: pass
                for w in main.winfo_children():
                    try: w.config(bg=PANEL)
                    except Exception: pass
                lbl.config(fg=GREEN if running_now else WHITE)

    def _ensure_visible():
        if not row_widgets: return
        try:
            _, row, _, _, _, _ = row_widgets[state["sel"]]
            canvas.update_idletasks()
            y1 = row.winfo_y()
            y2 = y1 + row.winfo_height()
            view_top = canvas.canvasy(0)
            view_h = canvas.winfo_height() or 1
            view_bot = view_top + view_h
            total = track_list.winfo_height() or 1
            scroll_range = max(1, total - view_h)
            if y1 < view_top:
                canvas.yview_moveto(max(0.0, y1 / scroll_range))
            elif y2 > view_bot:
                canvas.yview_moveto(min(1.0, (y2 - view_h) / scroll_range))
            # else: already visible — no scroll

        except Exception:
            pass

    def _paint_modules(host):
        for w in host.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        for group in ("BACKTEST", "TOOLS", "LIVE"):
            info = MODULE_INFO[group]
            idx = group_indices.get(group)
            count = sum(1 for t in tracks if t.group == group)
            active = idx is not None and tracks[state["sel"]].group == group
            card = tk.Frame(
                host,
                bg=(BG3 if active else BG2),
                highlightbackground=(info["accent"] if active else BORDER),
                highlightthickness=1,
                cursor="hand2" if idx is not None else "arrow",
            )
            card.pack(fill="x", pady=2)
            tk.Frame(card, bg=info["accent"], width=4).pack(side="left", fill="y")
            body = tk.Frame(card, bg=(BG3 if active else BG2))
            body.pack(side="left", fill="x", expand=True, padx=8, pady=5)
            tk.Label(body, text=info["label"], font=(FONT, 8, "bold"),
                     fg=(info["accent"] if active else WHITE), bg=body.cget("bg"),
                     anchor="w").pack(fill="x")
            tk.Label(body, text=info["desc"], font=(FONT, 7),
                     fg=DIM, bg=body.cget("bg"), anchor="w").pack(fill="x")
            tk.Label(card, text=f"{count:02d}", font=(FONT, 8, "bold"),
                     fg=WHITE, bg=body.cget("bg")).pack(side="right", padx=8)
            if idx is not None:
                for widget in (card, body, *body.winfo_children()):
                    widget.bind("<Button-1>", lambda _e, _i=idx: _sel(_i, scroll=True))

    # ─── detail panel
    def _paint_detail():
        for w in right.winfo_children():
            try: w.destroy()
            except Exception: pass
        if not tracks:
            tk.Label(right, text="no engines registered",
                     font=(FONT, 9), fg=DIM, bg=PANEL).pack(pady=40)
            return
        t = tracks[state["sel"]]

        # ── Header row: name + status chip
        hero = tk.Frame(right, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        hero.pack(fill="x", padx=10, pady=(10, 0))
        hdr = tk.Frame(hero, bg=BG2)
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(hdr, text=t.name, font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG2, anchor="w").pack(side="left")

        status = "running" if _is_track_running(t) else (t.status or "idle")
        sc = _STATE_COLORS.get(status, DIM)
        tk.Label(hdr, text=f" {status.upper()} ",
                 font=(FONT, 7, "bold"), fg=BG, bg=sc,
                 padx=4).pack(side="right")

        meta = tk.Frame(hero, bg=BG2)
        meta.pack(fill="x", padx=12, pady=(0, 10))
        mod = MODULE_INFO.get(t.group, {"label": t.group, "accent": AMBER})
        tk.Label(meta, text=f" {mod['label']} ",
                 font=(FONT, 7, "bold"), fg=BG, bg=mod["accent"],
                 padx=4).pack(side="left", padx=(0, 6))
        tk.Label(meta, text=t.slug.upper(),
                 font=(FONT, 7, "bold"), fg=DIM, bg=BG2,
                 anchor="w").pack(side="left")
        if t.tagline:
            tk.Label(meta, text=t.tagline[:46],
                     font=(FONT, 7), fg=DIM2, bg=BG2,
                     anchor="e").pack(side="right")

        chip_bar = tk.Frame(right, bg=BG)
        chip_bar.pack(fill="x", padx=10, pady=(8, 0))
        chip_host["frame"] = chip_bar

        def _mk_chip(label, key):
            active = state["chip"] == key
            fg_c = BG if active else WHITE
            bg_c = AMBER if active else BG2
            hov = AMBER_H if active else BORDER_H
            b = tk.Label(chip_bar, text=f" {label} ",
                         font=(FONT, 8, "bold"),
                         fg=fg_c, bg=bg_c, padx=9, pady=4,
                         highlightbackground=(AMBER if active else BORDER),
                         highlightthickness=1,
                         cursor="hand2")
            b.pack(side="left", padx=(0, 3))

            def _click(_e=None, _k=key):
                state["chip"] = _k
                _paint_detail()
            b.bind("<Button-1>", _click)
            if not active:
                b.bind("<Enter>", lambda _e: b.config(bg=hov))
                b.bind("<Leave>", lambda _e: b.config(bg=bg_c))
            return b

        # Chip set adapts to mode — backtest is research-oriented, live is
        # operations-oriented (the iPod "now playing" panel for live trades)
        if mode == "live":
            _chips = [
                ("LAUNCH",    "LAUNCH"),
                ("LOG",       "LOG"),
                ("POSITIONS", "POSITIONS"),
                ("OVERVIEW",  "OVERVIEW"),
            ]
        else:
            _chips = [
                ("OVERVIEW", "OVERVIEW"),
                ("CONFIG",   "CONFIG"),
                ("CODE",     "CODE"),
                ("RUN",      "RUN"),
            ]
        # If the saved chip is not in the current set, reset to first
        if state["chip"] not in {k for _, k in _chips}:
            state["chip"] = _chips[0][1]
        for _label, _key in _chips:
            _mk_chip(_label, _key)

        tk.Frame(right, bg=BORDER, height=1).pack(fill="x",
                                                   padx=12, pady=(4, 0))

        content = tk.Frame(right, bg=PANEL)
        content.pack(fill="both", expand=True, padx=12, pady=8)
        chip_content_host["frame"] = content

        sel_chip = state["chip"]
        if sel_chip == "OVERVIEW":
            _paint_overview(content, t)
        elif sel_chip == "CONFIG":
            _paint_config(content, t)
        elif sel_chip == "CODE":
            _paint_code(content, t)
        elif sel_chip == "LAUNCH":
            _paint_launch(content, t)
        elif sel_chip == "LOG":
            _paint_log(content, t)
        elif sel_chip == "POSITIONS":
            _paint_positions(content, t)
        else:  # RUN (backtest only)
            _paint_run(content, t)

        if on_select:
            try: on_select(t)
            except Exception: pass

    def _set_chip(chip: str):
        state["chip"] = chip
        _paint_detail()

    def _paint_overview(host, t: EngineTrack):
        sbody = _scrollable(host)
        brief = t.brief or {}

        intro = tk.Frame(sbody, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        intro.pack(fill="x", pady=(0, 8))
        tk.Label(intro, text=t.tagline or "strategy engine", font=(FONT, 8),
                 fg=DIM2, bg=BG2, anchor="w", justify="left",
                 wraplength=560).pack(fill="x", padx=10, pady=(9, 6))
        info_row = tk.Frame(intro, bg=BG2)
        info_row.pack(fill="x", padx=10, pady=(0, 9))
        mod = MODULE_INFO.get(t.group, {"label": t.group, "accent": AMBER})
        tk.Label(info_row, text=f" {mod['label']} ",
                 font=(FONT, 7, "bold"), fg=BG, bg=mod["accent"],
                 padx=4).pack(side="left")
        tk.Label(info_row, text=f"  {t.group}",
                 font=(FONT, 7, "bold"), fg=DIM, bg=BG2).pack(side="left")
        inline_status = "running" if _is_track_running(t) else (t.status or "idle")
        tk.Label(info_row, text=inline_status.upper(),
                 font=(FONT, 7, "bold"),
                 fg=_STATE_COLORS.get(inline_status, DIM2), bg=BG2).pack(side="right")

        if brief.get("philosophy"):
            _section(sbody, "RATIONALE")
            tk.Label(sbody, text=brief["philosophy"],
                     font=(FONT, 8), fg=AMBER_H, bg=PANEL,
                     wraplength=560, justify="left",
                     anchor="w").pack(fill="x", pady=(0, 6))

        def _cell(row, label, value):
            c = tk.Frame(row, bg=BG2,
                         highlightbackground=BORDER, highlightthickness=1)
            c.pack(side="left", fill="both", expand=True, padx=1)
            tk.Label(c, text=label, font=(FONT, 6, "bold"),
                     fg=DIM, bg=BG2, anchor="w").pack(
                fill="x", padx=4, pady=(1, 0))
            col = WHITE if value != "--" else DIM
            tk.Label(c, text=value, font=(FONT, 12, "bold"),
                     fg=col, bg=BG2, anchor="w").pack(
                fill="x", padx=4, pady=(0, 4))

        r1 = tk.Frame(sbody, bg=PANEL)
        r1.pack(fill="x", pady=1)
        _cell(r1, "SHARPE", f"{t.sharpe:.2f}" if t.sharpe is not None else "--")
        _cell(r1, "SORTINO", f"{t.sortino:.2f}" if t.sortino is not None else "--")
        r2 = tk.Frame(sbody, bg=PANEL)
        r2.pack(fill="x", pady=1)
        _cell(r2, "MAX DD", f"{t.max_dd:.1%}" if t.max_dd is not None else "--")
        _cell(r2, "WIN%", f"{t.win_rate:.0%}" if t.win_rate is not None else "--")

        summary = tk.Frame(sbody, bg=PANEL)
        summary.pack(fill="x", pady=(8, 2))
        rg = t.regime or "--"
        rc = _REGIME_COLORS.get(rg, BG2)
        tk.Label(summary, text="REGIME", font=(FONT, 6, "bold"),
                 fg=DIM, bg=PANEL).pack(side="left")
        tk.Label(summary, text=f" {rg} ", font=(FONT, 8, "bold"),
                 fg=BG if rg != "--" else DIM2, bg=rc,
                 padx=4).pack(side="left", padx=(4, 10))
        sig = t.last_signal or "no signal"
        age = f" | {t.last_signal_age}" if t.last_signal_age else ""
        tk.Label(summary, text=f"LAST {sig}{age}",
                 font=(FONT, 8),
                 fg=DIM2 if t.last_signal else DIM,
                 bg=PANEL, anchor="w").pack(side="left", fill="x", expand=True)

        if brief.get("edge") or brief.get("risk"):
            _section(sbody, "EDGE / RISK")
            if brief.get("edge"):
                row = tk.Frame(sbody, bg=PANEL)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=" EDGE ", font=(FONT, 7, "bold"),
                         fg=BG, bg=GREEN, padx=4).pack(side="left")
                tk.Label(row, text="  " + brief["edge"],
                         font=(FONT, 8), fg=WHITE, bg=PANEL,
                         anchor="w", wraplength=500,
                         justify="left").pack(side="left", fill="x", expand=True)
            if brief.get("risk"):
                row = tk.Frame(sbody, bg=PANEL)
                row.pack(fill="x", pady=2)
                tk.Label(row, text=" RISK ", font=(FONT, 7, "bold"),
                         fg=BG, bg=RED, padx=4).pack(side="left")
                tk.Label(row, text="  " + brief["risk"],
                         font=(FONT, 8), fg=DIM2, bg=PANEL,
                         anchor="w", wraplength=500,
                         justify="left").pack(side="left", fill="x", expand=True)

        tk.Label(sbody, text="EQUITY 90D", font=(FONT, 6, "bold"),
                 fg=DIM, bg=PANEL, anchor="w").pack(fill="x", pady=(8, 0))
        cv = tk.Canvas(sbody, bg=BG2, highlightthickness=1,
                       highlightbackground=BORDER, height=52)
        cv.pack(fill="x")
        series = t.equity_series
        if series and len(series) >= 2:
            cv.after(20, lambda s=series: _draw_spark(cv, s, AMBER))
        else:
            cv.after(20, lambda: cv.create_text(
                (cv.winfo_width() or 400) // 2, 28,
                text="-- no equity data --", font=(FONT, 8), fill=DIM))

    def _paint_config(host, t: EngineTrack):
        """Interactive config: period, basket, leverage, plots."""
        sbody = _scrollable(host)

        _section(sbody, "PARAMETERS")

        def _pill_row(label, opts, state_key):
            tk.Label(sbody, text=f"  {label}", font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, anchor="w").pack(fill="x", pady=(4, 1))
            wrap = tk.Frame(sbody, bg=PANEL)
            wrap.pack(fill="x", pady=(0, 2))
            btns: list = []
            for text_, val in opts:
                active = state[state_key] == val
                b = tk.Label(wrap, text=f" {text_} ",
                             font=(FONT, 8, "bold"),
                             fg=BG if active else WHITE,
                             bg=AMBER if active else BG3,
                             padx=6, pady=3, cursor="hand2")
                b.pack(side="left", padx=1, pady=1)
                btns.append((b, val))

                def _click(_e=None, _v=val, _btns=btns, _k=state_key):
                    state[_k] = _v
                    for _b, _bv in _btns:
                        on = _bv == _v
                        _b.config(fg=BG if on else WHITE,
                                  bg=AMBER if on else BG3)
                b.bind("<Button-1>", _click)

        _pill_row("PERIOD", PERIOD_OPTS, "cfg_period")
        _pill_row("BASKET", BASKET_OPTS, "cfg_basket")
        _pill_row("LEVERAGE", LEVERAGE_OPTS, "cfg_leverage")

        tk.Label(sbody, text="  CHARTS", font=(FONT, 7, "bold"),
                 fg=DIM, bg=PANEL, anchor="w").pack(fill="x", pady=(4, 1))
        trow = tk.Frame(sbody, bg=PANEL)
        trow.pack(fill="x", pady=(0, 4))
        on = state["cfg_plots"] == "s"
        plot_btn = tk.Label(trow,
                            text=" ON " if on else " OFF ",
                            font=(FONT, 8, "bold"),
                            fg=BG, bg=GREEN if on else BG3,
                            padx=8, pady=3, cursor="hand2")
        plot_btn.pack(side="left", padx=1)

        def _toggle_plots(_e=None):
            state["cfg_plots"] = "n" if state["cfg_plots"] == "s" else "s"
            _on = state["cfg_plots"] == "s"
            plot_btn.config(text=" ON " if _on else " OFF ",
                            fg=BG if _on else DIM,
                            bg=GREEN if _on else BG3)
        plot_btn.bind("<Button-1>", _toggle_plots)

        def _row(label, value, color=WHITE):
            r = tk.Frame(sbody, bg=PANEL)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=f"  {label}", font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, width=14,
                     anchor="w").pack(side="left")
            tk.Label(r, text=value, font=(FONT, 8),
                     fg=color, bg=PANEL, anchor="w",
                     wraplength=440, justify="left").pack(
                side="left", fill="x", expand=True)

        _section(sbody, "IDENTITY")
        _row("SLUG", t.slug, AMBER_H)
        _row("GROUP", t.group)
        _row("SCRIPT", t.script_path or "--", DIM2)
        _row("STATUS", (t.status or "idle").upper(),
             _STATE_COLORS.get(t.status, DIM))

        bc = (t.brief or {}).get("best_config") if t.brief else None
        if bc:
            _section(sbody, "BEST CONFIG")
            for k, v in bc.items():
                v_str = str(v)
                color = (GREEN if "?" in v_str else
                         RED if "?" in v_str else
                         AMBER if "?" in v_str else WHITE)
                _row(k.upper(), v_str, color)

        logic = (t.brief or {}).get("logic") if t.brief else None
        if logic:
            _section(sbody, "PIPELINE")
            for i, step in enumerate(logic, start=1):
                r = tk.Frame(sbody, bg=PANEL)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=f"  {i:02d}", font=(FONT, 7, "bold"),
                         fg=AMBER, bg=PANEL, width=4,
                         anchor="w").pack(side="left")
                tk.Label(r, text=step, font=(FONT, 8),
                         fg=WHITE, bg=PANEL, anchor="w",
                         wraplength=480,
                         justify="left").pack(side="left", fill="x", expand=True)

        if t.on_config:
            tk.Frame(sbody, bg=BORDER, height=1).pack(fill="x", pady=6)
            b = tk.Label(sbody, text=" OPEN FULL EDITOR ",
                         font=(FONT, 8, "bold"),
                         fg=BG, bg=AMBER, padx=10, pady=4,
                         cursor="hand2")
            b.pack(anchor="w")
            b.bind("<Button-1>", lambda _e: _safe(t.on_config))
            b.bind("<Enter>", lambda _e: b.config(bg=AMBER_H))
            b.bind("<Leave>", lambda _e: b.config(bg=AMBER))
    def _paint_code(host, t: EngineTrack):
        path = t.script_path or ""
        # Resolve repo root (parent of "core/")
        root = Path(__file__).resolve().parent.parent
        target = root / path if path else None

        tk.Label(host, text=f"  {path or '— no script path —'}",
                 font=(FONT, 7), fg=DIM2, bg=PANEL,
                 anchor="w").pack(fill="x")

        text = tk.Text(host, bg=BG2, fg=WHITE, insertbackground=AMBER,
                       bd=0, highlightthickness=1,
                       highlightbackground=BORDER,
                       font=(FONT, 8), wrap="none", height=18)
        sb = tk.Scrollbar(host, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True, pady=(4, 0))
        sb.pack(side="right", fill="y", pady=(4, 0))

        try:
            if target and target.is_file():
                with open(target, "r", encoding="utf-8",
                          errors="replace") as f:
                    content = f.read(120_000)  # cap at ~120KB for perf
                text.insert("1.0", content)
            else:
                text.insert("1.0",
                            "# — script not found —\n\n"
                            f"# path: {path}\n")
        except Exception as e:
            text.insert("1.0", f"# error reading file: {e}\n")
        text.configure(state="disabled")

    # progress bar state
    bar_host = {"canvas": None, "pct_lbl": None, "tail_lbl": None}

    # ─── LIVE-MODE PAINTERS ────────────────────────────────
    def _paint_launch(host, t: EngineTrack):
        """Mode launcher: PAPER/DEMO/TESTNET/LIVE pills, leverage knob.
        Replaces the BACKTEST 'RUN' chip in live mode — execution-focused,
        no period/basket cluttering it."""
        sbody = _scrollable(host)
        _section(sbody, "EXECUTION MODE")
        tk.Label(sbody,
                 text=("  Escolhe um modo. PAPER simula sem capital; "
                       "DEMO usa sandbox da exchange; TESTNET usa endpoint "
                       "de teste; LIVE = capital real ⚠"),
                 font=(FONT, 8), fg=DIM2, bg=PANEL,
                 anchor="w", justify="left", wraplength=540).pack(
            fill="x", pady=(0, 8))

        btns = tk.Frame(sbody, bg=PANEL)
        btns.pack(fill="x", pady=(0, 8))
        can_run = t.on_run is not None and not state["running"]

        def _mk_mode(text_, preset, hue):
            bg_c = hue if can_run else BG3
            fg_c = BG if can_run else DIM
            try:
                hov = _bright(hue, 1.2) if can_run else BG3
            except Exception:
                hov = AMBER_H if can_run else BG3
            b = tk.Label(btns, text=text_, font=(FONT, 9, "bold"),
                         fg=fg_c, bg=bg_c, padx=14, pady=6,
                         cursor="hand2" if can_run else "")
            b.pack(side="left", padx=(0, 6))
            if can_run:
                def _fire(_e=None, _p=preset):
                    _safe_cfg_with(t.on_run, _p)
                b.bind("<Button-1>", _fire)
                b.bind("<Enter>", lambda _e, _b=b, _h=hov: _b.config(bg=_h))
                b.bind("<Leave>", lambda _e, _b=b, _h=bg_c: _b.config(bg=_h))

        _mk_mode(" ▶ PAPER ",   "paper",   "#22D3EE")
        _mk_mode(" ▶ DEMO ",    "demo",    "#10F0A0")
        _mk_mode(" ▶ TESTNET ", "testnet", "#E6C86A")
        _mk_mode(" ▶ LIVE ",    "live",    "#F43F5E")

        # Inline leverage knob
        _section(sbody, "LEVERAGE")
        wrap = tk.Frame(sbody, bg=PANEL)
        wrap.pack(fill="x", pady=(0, 6))
        for label, val in LEVERAGE_OPTS:
            active = state["cfg_leverage"] == val
            b = tk.Label(wrap, text=f" {label} ",
                         font=(FONT, 8, "bold"),
                         fg=BG if active else WHITE,
                         bg=AMBER if active else BG3,
                         padx=8, pady=3, cursor="hand2")
            b.pack(side="left", padx=1)
            def _click(_e=None, _v=val):
                state["cfg_leverage"] = _v
                _paint_detail()
            b.bind("<Button-1>", _click)

        # Show current run status if any
        if state["running"]:
            _section(sbody, "STATUS")
            tk.Label(sbody, text=f"  ● RUNNING  ·  {state['prog_tail'][:80]}",
                     font=(FONT, 8, "bold"), fg=GREEN, bg=PANEL,
                     anchor="w").pack(fill="x")

    def _paint_log(host, t: EngineTrack):
        """Live log tail — finds the most recent run dir for this engine
        and tails its log file. Refreshes every 1s while open."""
        from pathlib import Path as _P
        path = _P(__file__).resolve().parent.parent
        # Map slug → engine dir under data/
        eng_dir_map = {
            "live": "live",
            "janestreet": "janestreet",
            "citadel": "live",  # citadel runs live via engines/live.py
            "bridgewater": "live", "jump": "live",
            "deshaw": "live", "renaissance": "live",
        }
        eng_dir = path / "data" / eng_dir_map.get(t.slug, t.slug)
        log_text = "(no live run found for this engine)"
        log_path = None
        if eng_dir.is_dir():
            try:
                runs = sorted(
                    [d for d in eng_dir.iterdir() if d.is_dir()],
                    key=lambda d: d.stat().st_mtime, reverse=True,
                )
                for rd in runs:
                    candidates = [
                        rd / "logs" / "live.log",
                        rd / "logs" / "engine.log",
                        rd / "log.txt",
                    ]
                    for c in candidates:
                        if c.is_file():
                            log_path = c
                            break
                    if log_path:
                        break
            except OSError:
                pass

        head_row = tk.Frame(host, bg=PANEL)
        head_row.pack(fill="x", pady=(0, 4))
        tk.Label(head_row, text=" ▶ LIVE LOG ",
                 font=(FONT, 7, "bold"), fg=BG,
                 bg=GREEN if log_path else DIM,
                 padx=6, pady=2).pack(side="left")
        tk.Label(head_row,
                 text=f"  {log_path.name if log_path else 'no active log'}",
                 font=(FONT, 7), fg=DIM2, bg=PANEL).pack(side="left", padx=(8, 0))

        text_w = tk.Text(host, bg=BG2, fg=WHITE, insertbackground=AMBER,
                         bd=0, highlightthickness=1,
                         highlightbackground=BORDER,
                         font=(FONT, 8), wrap="none", height=20)
        sb = tk.Scrollbar(host, orient="vertical", command=text_w.yview)
        text_w.configure(yscrollcommand=sb.set)
        text_w.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        if log_path:
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                    lines = fh.readlines()[-300:]
                log_text = "".join(lines)
            except OSError as e:
                log_text = f"(read error: {e})"
        text_w.insert("1.0", log_text)
        text_w.see("end")
        text_w.configure(state="disabled")

    def _paint_positions(host, t: EngineTrack):
        """Open positions for this engine's most recent live run."""
        from pathlib import Path as _P
        path = _P(__file__).resolve().parent.parent
        eng_dir_map = {
            "live": "live", "janestreet": "janestreet",
            "citadel": "live", "bridgewater": "live", "jump": "live",
            "deshaw": "live", "renaissance": "live",
        }
        eng_dir = path / "data" / eng_dir_map.get(t.slug, t.slug)
        positions = []
        if eng_dir.is_dir():
            try:
                runs = sorted(
                    [d for d in eng_dir.iterdir() if d.is_dir()],
                    key=lambda d: d.stat().st_mtime, reverse=True,
                )
                for rd in runs:
                    pj = rd / "state" / "positions.json"
                    if pj.is_file():
                        try:
                            data = json.loads(pj.read_text(encoding="utf-8"))
                            if isinstance(data, list):
                                positions = data
                            elif isinstance(data, dict):
                                positions = [
                                    {"symbol": k, **(v if isinstance(v, dict) else {"value": v})}
                                    for k, v in data.items()
                                ]
                            break
                        except (json.JSONDecodeError, OSError):
                            continue
            except OSError:
                pass

        head = tk.Frame(host, bg=PANEL)
        head.pack(fill="x", pady=(0, 6))
        tk.Label(head, text=" ▣ OPEN POSITIONS ",
                 font=(FONT, 7, "bold"), fg=BG,
                 bg=AMBER if positions else DIM,
                 padx=6, pady=2).pack(side="left")
        tk.Label(head, text=f"  {len(positions)} open",
                 font=(FONT, 8, "bold"), fg=AMBER_H,
                 bg=PANEL).pack(side="left", padx=(8, 0))

        if not positions:
            tk.Label(host, text="\n  no open positions",
                     font=(FONT, 9), fg=DIM, bg=PANEL,
                     anchor="w").pack(fill="x", pady=10)
            return

        # Header row
        cols = [("SYMBOL", 10), ("SIDE", 6), ("QTY", 12),
                ("ENTRY", 14), ("PNL", 14)]
        hdr = tk.Frame(host, bg=BG2)
        hdr.pack(fill="x")
        for c, w in cols:
            tk.Label(hdr, text=c, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG2, width=w, anchor="w",
                     padx=4, pady=4).pack(side="left")
        for p in positions:
            row = tk.Frame(host, bg=PANEL)
            row.pack(fill="x")
            sym = str(p.get("symbol", "?"))
            side = str(p.get("side", p.get("direction", "?"))).upper()
            qty = p.get("qty", p.get("size", "—"))
            entry = p.get("entry", p.get("entry_price", "—"))
            pnl = p.get("pnl", p.get("unrealized_pnl", 0)) or 0
            try:
                pnl_v = float(pnl)
                pnl_fg = GREEN if pnl_v > 0 else RED if pnl_v < 0 else DIM
                pnl_s = f"{pnl_v:+,.2f}"
            except (TypeError, ValueError):
                pnl_fg = DIM; pnl_s = str(pnl)
            for txt, w, fg in (
                (sym, 10, WHITE),
                (side, 6, GREEN if side == "LONG" else RED if side == "SHORT" else WHITE),
                (str(qty), 12, WHITE),
                (str(entry), 14, AMBER_H),
                (pnl_s, 14, pnl_fg),
            ):
                tk.Label(row, text=txt, font=(FONT, 8),
                         fg=fg, bg=PANEL, width=w, anchor="w",
                         padx=4, pady=2).pack(side="left")

    def _paint_run(host, t: EngineTrack):
        # Current cfg summary (reads state populated by CONFIG chip)
        def _lookup(opts, val, default="—"):
            for text_, v in opts:
                if v == val: return text_
            return default

        per_lbl = _lookup(PERIOD_OPTS,   state["cfg_period"],   "90D")
        bsk_lbl = _lookup(BASKET_OPTS,   state["cfg_basket"],   "DEFAULT")
        lev_lbl = _lookup(LEVERAGE_OPTS, state["cfg_leverage"], "1x")
        plt_lbl = "ON" if state["cfg_plots"] == "s" else "OFF"

        tk.Label(host,
                 text="  Dispara engine com a config atual (edite em CONFIG).",
                 font=(FONT, 8), fg=DIM2, bg=PANEL,
                 anchor="w").pack(fill="x", pady=(0, 6))

        # Config summary chips
        sumrow = tk.Frame(host, bg=PANEL)
        sumrow.pack(fill="x", pady=(0, 6))
        for lbl, val in (("PERÍODO", per_lbl), ("CESTA", bsk_lbl),
                         ("LEV", lev_lbl), ("PLOTS", plt_lbl)):
            cell = tk.Frame(sumrow, bg=BG2,
                            highlightbackground=BORDER,
                            highlightthickness=1)
            cell.pack(side="left", padx=2, pady=1)
            tk.Label(cell, text=lbl, font=(FONT, 6, "bold"),
                     fg=DIM, bg=BG2, padx=4).pack(side="left")
            tk.Label(cell, text=val, font=(FONT, 8, "bold"),
                     fg=AMBER_H, bg=BG2, padx=4).pack(side="left")

        # Button row — layout depends on `mode`
        btns = tk.Frame(host, bg=PANEL)
        btns.pack(fill="x", pady=(0, 8))
        can_run = t.on_run is not None and not state["running"]
        can_stop = t.on_stop is not None and state["running"]

        def _mk_run(text_, preset, hue, primary=False):
            bg_c = hue if can_run else BG3
            fg_c = BG if can_run else DIM
            hov_factor = 1.15 if primary else 1.25
            try:
                hov = _bright(hue, hov_factor) if can_run else BG3
            except Exception:
                hov = AMBER_H if can_run else BG3
            b = tk.Label(btns, text=text_, font=(FONT, 9, "bold"),
                         fg=fg_c, bg=bg_c, padx=12, pady=5,
                         cursor="hand2" if can_run else "")
            b.pack(side="left", padx=(0, 6))
            if can_run:
                def _fire(_e=None, _p=preset):
                    _safe_cfg_with(t.on_run, _p)
                b.bind("<Button-1>", _fire)
                b.bind("<Enter>", lambda _e, _b=b, _h=hov: _b.config(bg=_h))
                b.bind("<Leave>", lambda _e, _b=b, _h=bg_c: _b.config(bg=_h))
            return b

        if mode == "live":
            # PAPER / DEMO / TESTNET / LIVE — escalating risk, color-coded.
            _mk_run(" ▶ PAPER ",   "paper",   "#22D3EE", primary=True)
            _mk_run(" ▶ DEMO ",    "demo",    "#10F0A0")
            _mk_run(" ▶ TESTNET ", "testnet", "#E6C86A")
            _mk_run(" ▶ LIVE ",    "live",    "#F43F5E")
            tk.Label(host,
                     text="  PAPER = simulado · DEMO = sandbox · TESTNET = test API · LIVE = capital real ⚠",
                     font=(FONT, 7), fg=DIM, bg=PANEL,
                     anchor="w").pack(fill="x", pady=(0, 4))
        else:
            _mk_run(" ▶ RUN CUSTOM ",     "custom",     AMBER, primary=True)
            _mk_run(" ▶ RUN CALIBRATED ", "calibrated", CYAN)
            tk.Label(host,
                     text="  CUSTOM = cfg acima · CALIBRATED = preset validado bateria",
                     font=(FONT, 7), fg=DIM, bg=PANEL,
                     anchor="w").pack(fill="x", pady=(0, 4))

        # Progress bar
        pb_host = tk.Frame(host, bg=PANEL)
        pb_host.pack(fill="x", pady=(4, 2))
        tk.Label(pb_host, text="PROGRESS", font=(FONT, 6, "bold"),
                 fg=DIM, bg=PANEL, anchor="w").pack(side="left")
        pct_lbl = tk.Label(pb_host,
                           text=f"{int(state['prog_pct'])}%",
                           font=(FONT, 7, "bold"), fg=AMBER_H,
                           bg=PANEL)
        pct_lbl.pack(side="right")

        bar_cv = tk.Canvas(host, bg=BG2, highlightthickness=1,
                           highlightbackground=BORDER, height=10)
        bar_cv.pack(fill="x", pady=(0, 6))

        bar_host["canvas"] = bar_cv
        bar_host["pct_lbl"] = pct_lbl

        # Tail
        tk.Label(host, text="LIVE TAIL", font=(FONT, 6, "bold"),
                 fg=DIM, bg=PANEL, anchor="w").pack(
            fill="x", pady=(4, 0))
        tail_lbl = tk.Label(host,
                            text=state["prog_tail"] or "— idle —",
                            font=(FONT, 7),
                            fg=DIM2, bg=BG2,
                            anchor="w", justify="left",
                            wraplength=540)
        tail_lbl.pack(fill="x", ipady=3)
        tail_lbl.configure(highlightbackground=BORDER,
                           highlightthickness=1)
        bar_host["tail_lbl"] = tail_lbl

        _repaint_bar()

    def _repaint_bar():
        cv = bar_host["canvas"]
        if cv is None or not cv.winfo_exists():
            return
        cv.delete("all")
        cv.update_idletasks()
        w = cv.winfo_width() or 300
        h = cv.winfo_height() or 10
        pad = 1
        fw = int((w - pad * 2) * (state["prog_pct"] / 100))
        if fw > 0:
            cv.create_rectangle(pad, pad, pad + fw, h - pad,
                                outline="", fill=AMBER)
            if state["running"]:
                state["pulse"] = (state["pulse"] + 4) % max(fw, 20)
                sx = pad + state["pulse"]
                cv.create_rectangle(max(pad, sx - 4), pad,
                                    min(pad + fw, sx + 4), h - pad,
                                    outline="", fill=AMBER_H)
        if bar_host["pct_lbl"] and bar_host["pct_lbl"].winfo_exists():
            bar_host["pct_lbl"].configure(
                text=f"{int(state['prog_pct'])}%")
        if bar_host["tail_lbl"] and bar_host["tail_lbl"].winfo_exists():
            bar_host["tail_lbl"].configure(
                text=state["prog_tail"] or ("— running —"
                                             if state["running"]
                                             else "— idle —"))

    # periodic repaint while running
    def _tick():
        if state["running"]:
            _repaint_bar()
        try:
            root.after(160, _tick)
        except Exception:
            pass
    root.after(200, _tick)

    def _sel(i: int, scroll: bool = False):
        if not row_widgets: return
        state["sel"] = max(0, min(len(row_widgets) - 1, i))
        state["chip"] = "OVERVIEW"  # reset to overview on selection
        _apply_progress_from_selection()
        _paint_sel()  # cheap: just recolors rows
        if scroll:
            _ensure_visible()
        # Defer the heavy right-panel rebuild to the next idle tick so
        # the row-selection visual lands instantly. Without this the user
        # perceives a "trava" because Tk waits for paint_detail (~30+
        # widget destroy/create) to finish before redrawing the row.
        try:
            root.after_idle(_paint_modules, modules)
            root.after_idle(_paint_detail)
        except Exception:
            _paint_modules(modules)
            _paint_detail()

    footer = tk.Frame(left, bg=BG2)
    footer.pack(fill="x")
    tk.Frame(footer, bg=BORDER, height=1).pack(fill="x")
    tk.Label(footer, text="UP / DOWN navigate   ENTER run", font=(FONT, 7),
             fg=DIM, bg=BG2, anchor="w").pack(fill="x", padx=8, pady=(5, 6))

    for i, row, lbl, _t, rail, main in row_widgets:
        row.bind("<Button-1>", lambda e, _i=i: _sel(_i, scroll=False))
        lbl.bind("<Button-1>", lambda e, _i=i: _sel(_i, scroll=False))
        main.bind("<Button-1>", lambda e, _i=i: _sel(_i, scroll=False))
        rail.bind("<Button-1>", lambda e, _i=i: _sel(_i, scroll=False))
        for child in row.winfo_children():
            child.bind("<Button-1>", lambda e, _i=i: _sel(_i, scroll=False))

    def _wheel(e):
        try: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception: pass
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    _apply_progress_from_selection()
    _paint_modules(modules)
    _paint_sel()
    _paint_detail()

    def _current_cfg():
        return {
            "period":   state["cfg_period"],
            "basket":   state["cfg_basket"],
            "leverage": state["cfg_leverage"],
            "plots":    state["cfg_plots"],
        }

    def _safe_cfg_with(fn, preset="custom"):
        """Call on_run with cfg dict {preset, period, basket, leverage, plots}."""
        if fn is None: return
        cfg = _current_cfg()
        cfg["preset"] = preset
        try:
            fn(cfg)
        except TypeError:
            try: fn()
            except Exception: pass
        except Exception:
            pass

    def _run_current():
        if not tracks: return
        _safe_cfg_with(tracks[state["sel"]].on_run, "custom")

    def _set_progress(slug: str, pct: float,
                      tail: str = "", running: bool = True):
        """External hook — caller tells picker: 'engine `slug` is at `pct`%'."""
        state["prog_by_slug"][slug] = {
            "pct": max(0.0, min(100.0, float(pct))),
            "tail": (tail or "")[:240],
            "running": bool(running),
        }
        _paint_sel()
        _paint_modules(modules)
        cur = tracks[state["sel"]] if tracks else None
        if not cur or cur.slug != slug:
            return
        _apply_progress_from_selection()
        target_chip = "LOG" if mode == "live" else "RUN"
        if state["chip"] != target_chip:
            state["chip"] = target_chip
            _paint_detail()
        else:
            _repaint_bar()

    return {
        "frame": root,
        "select_index": lambda i: _sel(i, scroll=True),
        "current": lambda: tracks[state["sel"]] if tracks else None,
        "run_current": _run_current,
        "delta": lambda d: _sel(state["sel"] + d, scroll=True),
        "open_chip": _set_chip,
        "refresh": _paint_detail,
        "set_progress": _set_progress,
    }


def _safe(fn):
    try: fn()
    except Exception: pass


def _draw_spark(cv: tk.Canvas, series, color: str, pad: int = 4):
    cv.delete("all")
    w = cv.winfo_width() or 200
    h = cv.winfo_height() or 52
    if not series or len(series) < 2: return
    lo, hi = min(series), max(series)
    if hi == lo: hi = lo + 1
    n = len(series)
    pts = []
    for i, v in enumerate(series):
        x = pad + (i / (n - 1)) * (w - 2 * pad)
        y = h - pad - ((v - lo) / (hi - lo)) * (h - 2 * pad)
        pts.extend([x, y])
    shade = pts + [w - pad, h - pad, pad, h - pad]
    cv.create_polygon(*shade, fill=color, stipple="gray12", outline="")
    cv.create_line(*pts, fill=color, width=1, smooth=False)
