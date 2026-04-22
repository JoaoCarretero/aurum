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
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from config.engines import ENGINE_GROUPS, ENGINE_SORT_WEIGHTS

# ── PALETTE (HL2 VGUI, via SSOT) ─────────────────────────────
from core.ui_palette import (
    BG, BG2, BG3, PANEL,
    BORDER, BORDER_H,
    AMBER, AMBER_H,
    WHITE, DIM, DIM2,
    GREEN, RED, CYAN,
    GLOW, FONT,
)

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

_LIVE_FS_CACHE_TTL_S = 1.0
_LIVE_FS_CACHE: dict[tuple[Any, ...], tuple[float, Any]] = {}
_ENGINE_LIVE_DIR_MAP = {
    "live": "live",
    "janestreet": "janestreet",
    "citadel": "live",
    "bridgewater": "live",
    "jump": "live",
    "deshaw": "live",
    "renaissance": "live",
}


def clear_live_fs_cache() -> None:
    _LIVE_FS_CACHE.clear()


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _engine_live_dir(slug: str) -> Path:
    return _repo_root() / "data" / _ENGINE_LIVE_DIR_MAP.get(slug, slug)


def _cached_live_fs(key: tuple[Any, ...], loader: Callable[[], Any]) -> Any:
    now = time.monotonic()
    cached = _LIVE_FS_CACHE.get(key)
    if cached and (now - cached[0]) < _LIVE_FS_CACHE_TTL_S:
        return cached[1]
    value = loader()
    _LIVE_FS_CACHE[key] = (now, value)
    return value


def _latest_live_run_dir(slug: str) -> Path | None:
    def _load() -> Path | None:
        eng_dir = _engine_live_dir(slug)
        if not eng_dir.is_dir():
            return None
        try:
            return max(
                (d for d in eng_dir.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                default=None,
            )
        except OSError:
            return None

    return _cached_live_fs(("latest_live_run_dir", slug), _load)


def _safe_tail_lines(path: Path, n_lines: int = 300) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return "".join(deque(fh, maxlen=n_lines))
    except OSError as e:
        return f"(read error: {e})"


def _load_live_log(slug: str, n_lines: int = 300) -> tuple[Path | None, str]:
    def _load() -> tuple[Path | None, str]:
        eng_dir = _engine_live_dir(slug)
        if not eng_dir.is_dir():
            return None, "(no live run found for this engine)"
        try:
            runs = sorted(
                (d for d in eng_dir.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return None, "(no live run found for this engine)"

        for rd in runs:
            for candidate in (
                rd / "logs" / "live.log",
                rd / "logs" / "engine.log",
                rd / "log.txt",
            ):
                if candidate.is_file():
                    return candidate, _safe_tail_lines(candidate, n_lines=n_lines)
        return None, "(no live run found for this engine)"

    return _cached_live_fs(("live_log", slug, n_lines), _load)


def _load_live_positions(slug: str) -> list[dict[str, Any]]:
    def _load() -> list[dict[str, Any]]:
        eng_dir = _engine_live_dir(slug)
        if not eng_dir.is_dir():
            return []
        try:
            runs = sorted(
                (d for d in eng_dir.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []
        for rd in runs:
            pj = rd / "state" / "positions.json"
            if not pj.is_file():
                continue
            try:
                data = json.loads(pj.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [
                    {"symbol": k, **(v if isinstance(v, dict) else {"value": v})}
                    for k, v in data.items()
                ]
        return []

    return _cached_live_fs(("live_positions", slug), _load)


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

    Prefers brief['what'] — plain-language description — so the user can
    scan the list and understand each engine at a glance. Falls back to
    the numeric calibration summary (TF · Sharpe · status) for engines
    without a 'what' field, then to the raw tagline.
    """
    brief = getattr(t, "brief", None) or {}
    what = brief.get("what")
    if what:
        # 56-char cap keeps the subtitle to one line in the 252-wide sidebar
        return str(what)[:56].rstrip()
    # Numeric fallback: TF · Sharpe · EDGE/MARG tag
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
    if t.tagline:
        return t.tagline[:44]
    return ""


def _section(parent, title):
    """Institutional section header: terse label · 1px rule, no rails."""
    tk.Frame(parent, bg=PANEL, height=10).pack()
    tk.Label(parent, text=title, font=(FONT, 7, "bold"),
             fg=AMBER, bg=PANEL, anchor="w"
             ).pack(fill="x")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 6))


_TRADE_KEYS = ("Trades", "trades", "N trades", "n_trades", "trade_count")
_ROI_KEYS   = ("ROI", "roi", "ROI%", "roi_pct", "ROI val")
_MC_KEYS    = ("MC", "mc", "MC 1000", "monte_carlo", "MC pct")


def _pull_trade_count(bc: dict) -> str | None:
    """Extract trade count from a best_config dict. Returns short display str
    or None when nothing matches. best_config entries come from hand-written
    BRIEFINGS so shape varies — this normalises them for the KPI strip."""
    if not isinstance(bc, dict):
        return None
    # Direct keys
    for k in _TRADE_KEYS:
        if k in bc:
            v = str(bc[k])
            # "225" or "225 trades" → "225"
            tok = v.strip().split()
            if tok and tok[0].replace(",", "").isdigit():
                return tok[0]
            return v[:8]
    # Extract from a "Sharpe val" string like "2.54 · 225 trades · ROI +51%"
    for k in ("Sharpe val", "Sharpe", "sharpe_val"):
        if k in bc:
            import re
            m = re.search(r"(\d[\d,]*)\s*trade", str(bc[k]))
            if m:
                return m.group(1)
    return None


def _pull_roi(bc: dict) -> str | None:
    if not isinstance(bc, dict):
        return None
    for k in _ROI_KEYS:
        if k in bc:
            return str(bc[k])[:10]
    for k in ("Sharpe val", "Sharpe", "sharpe_val"):
        if k in bc:
            import re
            m = re.search(r"ROI\s*([+-]?\d[\d.]*\s*%?)", str(bc[k]))
            if m:
                val = m.group(1).strip()
                if not val.endswith("%"):
                    val += "%"
                return val
    return None


def _pull_mc(bc: dict) -> str | None:
    if not isinstance(bc, dict):
        return None
    for k in _MC_KEYS:
        if k in bc:
            import re
            m = re.search(r"(\d+\.?\d*)\s*%", str(bc[k]))
            if m:
                return f"{m.group(1)}%"
            return str(bc[k])[:8]
    for k in ("Sharpe val", "Sharpe", "sharpe_val"):
        if k in bc:
            import re
            m = re.search(r"MC\s*(\d+\.?\d*)\s*%", str(bc[k]))
            if m:
                return f"{m.group(1)}%"
    return None


def _compact_audit(s: str | None) -> str:
    """Shrink 'Audit' brief field into a short KPI badge like '5/6' or 'OK'."""
    if not s:
        return "--"
    import re
    m = re.search(r"(\d+)\s*/\s*(\d+)", str(s))
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    if "PASS" in str(s).upper() or "✓" in str(s):
        return "PASS"
    if "FAIL" in str(s).upper() or "✗" in str(s):
        return "FAIL"
    if "⚠" in str(s) or "WARN" in str(s).upper():
        return "WARN"
    return str(s)[:6]


def _scrollable(parent):
    """Return an inner Frame that scrolls vertically inside parent.

    Mouse-wheel is bound DIRECTLY on the canvas + inner frame (not via
    bind_all). bind_all on MouseWheel registers a global handler that
    is NOT automatically removed when the canvas is destroyed — every
    re-render leaked another reference, and after a few dozen clicks
    the event dispatch queue spent tens of milliseconds walking dead
    handlers. Direct bindings die with the widget.
    """
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
        return "break"
    canvas.bind("<MouseWheel>", _wheel)
    inner.bind("<MouseWheel>", _wheel)
    return inner


@dataclass
class EngineTrack:
    slug: str
    name: str
    group: str = "ENGINES"
    stage: str = "research"
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
DEFAULT_GROUPS = dict(ENGINE_GROUPS)
GROUP_ORDER = ("BACKTEST", "LIVE", "TOOLS")

# Explicit sort weight per slug so we can promote validated engines (e.g.
# RENAISSANCE just above MILLENNIUM) instead of relying on alphabetical.
# Lower weight = appears earlier. Anything not listed falls back to alpha.
TRACK_SORT_WEIGHT = dict(ENGINE_SORT_WEIGHTS)
MODULE_INFO = {
    "BACKTEST": {
        "label": "RESEARCH",
        "desc": "Backtest, walk-forward, Monte Carlo",
        "accent": "#4DA3FF",
    },
    "TOOLS": {
        "label": "ANALYTICS",
        "desc": "Validation and calibration utilities",
        "accent": "#E0B94B",
    },
    "LIVE": {
        "label": "EXECUTION",
        "desc": "Paper, demo, testnet, live",
        "accent": "#00D26A",
    },
}

_STAGE_STYLE = {
    "validated": ("VALIDATED", GREEN),
    "bootstrap_staging": ("BOOTSTRAP", AMBER),
    "research": ("RESEARCH", DIM2),
    "experimental": ("EXPERIMENTAL", RED),
    "quarantined": ("QUARANTINED", RED),
}


def _stage_badge(stage: Optional[str]) -> tuple[str, str]:
    key = str(stage or "research").strip().lower()
    if key in _STAGE_STYLE:
        return _STAGE_STYLE[key]
    return (key.upper() or "RESEARCH", DIM2)


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
        group = meta.get("module", gmap.get(slug, "ENGINES"))
        tracks.append(EngineTrack(
            slug=slug,
            name=meta.get("display", slug.upper()),
            group=group,
            stage=str(meta.get("stage", "research")),
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
        int(registry.get(t.slug, {}).get("sort_weight", TRACK_SORT_WEIGHT.get(t.slug, 999))),
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
        row.pack(fill="x", padx=4, pady=1)

        rail = tk.Frame(row, bg=PANEL, width=3)
        rail.pack(side="left", fill="y")

        led = tk.Label(row, text="●", font=(FONT, 9),
                       fg=_STATE_COLORS.get(t.status, DIM), bg=PANEL)
        led.pack(side="left", padx=(6, 4))

        num = tk.Label(row, text=f"{idx+1:02d}", font=(FONT, 7, "bold"),
                       fg=DIM, bg=PANEL)
        num.pack(side="left", padx=(0, 4))

        main = tk.Frame(row, bg=PANEL)
        main.pack(side="left", fill="x", expand=True, pady=2)
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
        # Run override — dict from data/aurum.db.runs row, set when user
        # clicks a row in the LAST RUNS overview. Replaces t.sharpe etc.
        # in the KPI tape so the user sees per-run metrics. Cleared on
        # selection change (_sel) and on chip change back to OVERVIEW.
        "run_override": None,
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

    # ─── detail panel (LABORATORY layout)
    # Structure — top to bottom:
    #   1. Identity strip — name + status chip + compressed tagline
    #   2. KPI tape — 8 mini-cells always visible (SHRP/SORT/MDD/WR/TRDS/ROI/MC/AUD)
    #   3. Chip bar — OVER · LAB · CODE · RUN (backtest) or LAUNCH/LOG/POS/OVER (live)
    #   4. Content pane — renders active chip (wrapped in try/except)
    #
    # KPIs move OUT of OVER into the tape so they're visible in every chip.
    # This matches the "laboratory" brief: the numbers are the lab's readout,
    # not a detail you only see when on the OVERVIEW screen.
    _last_paint = {"sel": -1, "chip": None, "running": None, "override": None}

    def _paint_detail():
        # Short-circuit: nothing the paint depends on actually changed.
        # Repeated clicks on the same row + same chip used to rebuild 60+
        # widgets for nothing, which felt like a click freeze when the user
        # clicked twice in a row. run_override is part of the key so
        # clicking a LAST RUNS row triggers a repaint of the KPI tape.
        running = _is_track_running(tracks[state["sel"]]) if tracks else False
        ro = state.get("run_override") or {}
        override_rid = ro.get("run_id") if ro else None
        key = (state["sel"], state["chip"], running, override_rid)
        if (_last_paint["sel"] == key[0]
                and _last_paint["chip"] == key[1]
                and _last_paint["running"] == key[2]
                and _last_paint.get("override") == key[3]):
            return
        (_last_paint["sel"], _last_paint["chip"],
         _last_paint["running"], _last_paint["override"]) = key

        for w in right.winfo_children():
            try: w.destroy()
            except Exception: pass
        if not tracks:
            tk.Label(right, text="no engines registered",
                     font=(FONT, 9), fg=DIM, bg=PANEL).pack(pady=40)
            return
        t = tracks[state["sel"]]
        brief = t.brief or {}
        mod = MODULE_INFO.get(t.group, {"label": t.group, "accent": AMBER})

        # Uniform horizontal padding for every vertical band
        PAD_X = 10

        # ── 1. IDENTITY STRIP — institutional header ──
        # Restrained layout: name left (bold, not colored), module tag,
        # status pill right. Tagline below on its own subtle line.
        # No colored accent rails — institutional look relies on
        # typography hierarchy, not graphical ornament.
        head = tk.Frame(right, bg=PANEL)
        head.pack(fill="x", padx=PAD_X, pady=(10, 0))

        line1 = tk.Frame(head, bg=PANEL)
        line1.pack(fill="x")
        tk.Label(line1, text=t.name, font=(FONT, 11, "bold"),
                 fg=WHITE, bg=PANEL, anchor="w").pack(side="left")
        tk.Label(line1, text=f"   {t.slug.upper()}",
                 font=(FONT, 7), fg=DIM, bg=PANEL).pack(side="left")
        tk.Label(line1, text=f" · {mod['label']}",
                 font=(FONT, 7), fg=DIM, bg=PANEL).pack(side="left")

        stage_label, stage_color = _stage_badge(t.stage)
        tk.Label(line1, text=f" . {stage_label}",
                 font=(FONT, 7, "bold"), fg=stage_color, bg=PANEL).pack(side="left")

        status = "running" if _is_track_running(t) else (t.status or "idle")
        sc = _STATE_COLORS.get(status, DIM)
        tk.Label(line1, text=status.upper(),
                 font=(FONT, 7, "bold"), fg=sc, bg=PANEL,
                 padx=4).pack(side="right")

        tagline = (t.tagline or brief.get("edge", "") or "")[:80]
        if tagline:
            tk.Label(head, text=tagline,
                     font=(FONT, 8), fg=DIM2, bg=PANEL,
                     anchor="w", wraplength=560, justify="left"
                     ).pack(fill="x", pady=(3, 0))

        tk.Frame(right, bg=BORDER, height=1).pack(
            fill="x", padx=PAD_X, pady=(8, 0))

        # ── 2. KPI TAPE — two groups: PERFORMANCE | TRACK RECORD ──
        # When the user clicks a LAST RUN row, state["run_override"] holds
        # that run's metrics; display those instead of the hydrated latest
        # so the tape reflects the clicked history item.
        bc = brief.get("best_config") or {}
        aud = _compact_audit(bc.get("Audit") or bc.get("Status"))
        ro = state.get("run_override") or {}
        _sh = ro.get("sharpe") if ro.get("sharpe") is not None else t.sharpe
        _so = ro.get("sortino") if ro.get("sortino") is not None else t.sortino
        _dd_raw = ro.get("max_dd")
        _mdd = (_dd_raw / 100.0) if isinstance(_dd_raw, (int, float)) else t.max_dd
        _wr_raw = ro.get("win_rate")
        _wr = (_wr_raw / 100.0) if isinstance(_wr_raw, (int, float)) else t.win_rate
        _trds_override = ro.get("n_trades")
        _roi_override = ro.get("roi")
        if isinstance(_roi_override, (int, float)):
            roi = f"{_roi_override:+.1f}%"
        else:
            roi = _pull_roi(bc) or ""
        perf_cells = [
            ("SHRP", f"{_sh:.2f}" if _sh is not None else "--",
             GREEN if (_sh or 0) >= 1.0 else (AMBER if (_sh or 0) > 0 else WHITE)),
            ("SORT", f"{_so:.2f}" if _so is not None else "--", WHITE),
            ("MDD",  f"{_mdd:.1%}" if _mdd is not None else "--",
             GREEN if (_mdd or 1) < 0.10 else (AMBER if (_mdd or 1) < 0.20 else RED)),
            ("WR",   f"{_wr:.0%}" if _wr is not None else "--", WHITE),
        ]
        trds_txt = (str(int(_trds_override))
                    if isinstance(_trds_override, (int, float))
                    else (_pull_trade_count(bc) or "--"))
        # DAYS = scan_days do run clicado (LAST RUNS). Sem override,
        # cai pra "--" (period nao faz sentido no baseline hydrated).
        _days_raw = ro.get("scan_days")
        days_txt = (f"{int(_days_raw)}d"
                    if isinstance(_days_raw, (int, float))
                    else "--")
        # TF = interval do run clicado. Sem override, usa t.brief.best_config.TF.
        _tf_raw = ro.get("interval")
        if _tf_raw:
            tf_txt = str(_tf_raw).lower()
        else:
            tf_txt = str(bc.get("TF") or "--").lower()[:5]
        track_cells = [
            ("TRDS", trds_txt, DIM2),
            ("ROI",  roi or "--",
             GREEN if roi.startswith("+") else (RED if roi.startswith("-") else DIM2)),
            ("DAYS", days_txt, WHITE if days_txt != "--" else DIM2),
            ("TF",   tf_txt, AMBER if tf_txt != "--" else DIM2),
            ("AUD",  aud,
             GREEN if "PASS" in aud else
             AMBER if "WARN" in aud else
             RED if "FAIL" in aud else WHITE),
        ]

        def _mk_group(parent, title, cells):
            """Institutional KPI group — title · flush cells · 1px rule.

            Values are right-aligned and uniformly white. Color is reserved
            for status severity (PASS/WARN/FAIL) and signed returns, not
            every numeric cell — institutional dashboards treat color as
            signal, not decoration.
            """
            grp = tk.Frame(parent, bg=PANEL)
            grp.pack(side="left", fill="both", expand=True, padx=(0, 1))
            tk.Label(grp, text=title, font=(FONT, 6, "bold"),
                     fg=DIM, bg=PANEL, anchor="w"
                     ).pack(fill="x", padx=2, pady=(2, 2))
            row = tk.Frame(grp, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1)
            row.pack(fill="x")
            for i, (label, val, col) in enumerate(cells):
                cell = tk.Frame(row, bg=PANEL)
                cell.pack(side="left", fill="both", expand=True)
                tk.Label(cell, text=label, font=(FONT, 6, "bold"),
                         fg=DIM, bg=PANEL, anchor="w"
                         ).pack(fill="x", padx=6, pady=(4, 0))
                tk.Label(cell, text=val, font=(FONT, 11, "bold"),
                         fg=col if val != "--" else DIM, bg=PANEL,
                         anchor="e").pack(fill="x", padx=6, pady=(0, 5))
                # 1px vertical separator between cells (institutional grid)
                if i < len(cells) - 1:
                    tk.Frame(row, bg=BORDER, width=1).pack(
                        side="left", fill="y")

        tape = tk.Frame(right, bg=PANEL)
        tape.pack(fill="x", padx=PAD_X, pady=(10, 0))
        _mk_group(tape, "PERFORMANCE", perf_cells)
        tk.Frame(tape, bg=PANEL, width=8).pack(side="left", fill="y")
        _mk_group(tape, "TRACK RECORD", track_cells)

        # ── 3. CHIP BAR ────────────────────────────────────────
        chip_bar = tk.Frame(right, bg=BG)
        chip_bar.pack(fill="x", padx=PAD_X, pady=(10, 0))
        chip_host["frame"] = chip_bar

        def _mk_chip(label, key):
            active = state["chip"] == key
            # Chips mais prominentes: inativa tem borda amber (sinaliza
            # interacao), ativa tem fill amber solido. Font bumped 8→9
            # e padding 3→5 pra hit target maior.
            fg_c = BG if active else AMBER
            bg_c = AMBER if active else BG2
            border_c = AMBER if active else AMBER_H
            hov = AMBER_H if active else BG3
            b = tk.Label(chip_bar, text=f" {label} ",
                         font=(FONT, 9, "bold"),
                         fg=fg_c, bg=bg_c, padx=10, pady=5,
                         highlightbackground=border_c,
                         highlightthickness=1,
                         cursor="hand2")
            b.pack(side="left", padx=(0, 3))

            def _click(_e=None, _k=key):
                state["chip"] = _k
                _paint_detail()
            b.bind("<Button-1>", _click)
            if not active:
                b.bind("<Enter>", lambda _e: b.config(bg=hov, fg=BG))
                b.bind("<Leave>", lambda _e: b.config(bg=bg_c, fg=AMBER))
            return b

        if mode == "live":
            _chips = [
                ("LAUNCH",    "LAUNCH"),
                ("LOG",       "LOG"),
                ("POS",       "POSITIONS"),
                ("OVER",      "OVERVIEW"),
            ]
        else:
            # LAB (CONFIG) merged into RUN — editable params now live
            # inline above the run buttons, so the old CONFIG chip would
            # just duplicate the controls.
            _chips = [
                ("OVER",  "OVERVIEW"),
                ("BRIEF", "BRIEF"),
                ("CODE",  "CODE"),
                ("RUN",   "RUN"),
            ]
        if state["chip"] not in {k for _, k in _chips}:
            state["chip"] = _chips[0][1]
        for _label, _key in _chips:
            _mk_chip(_label, _key)

        tk.Frame(right, bg=BORDER, height=1).pack(
            fill="x", padx=PAD_X, pady=(3, 0))

        # ── 4. CONTENT PANE (chip dispatcher with safety wrapper) ──
        content = tk.Frame(right, bg=PANEL)
        content.pack(fill="both", expand=True, padx=PAD_X, pady=8)
        chip_content_host["frame"] = content

        _chip_painters = {
            "OVERVIEW":  _paint_overview,
            "BRIEF":     _paint_brief,
            "CONFIG":    _paint_config,
            "CODE":      _paint_code,
            "RUN":       _paint_run,
            "LAUNCH":    _paint_launch,
            "LOG":       _paint_log,
            "POSITIONS": _paint_positions,
        }
        painter = _chip_painters.get(state["chip"])
        if painter is None:
            tk.Label(content, text=f"unknown chip: {state['chip']}",
                     font=(FONT, 9), fg=RED, bg=PANEL).pack(pady=20)
        else:
            try:
                painter(content, t)
            except Exception as e:
                # Never let a chip painter hang the UI — show the error inline
                import traceback
                tk.Label(content,
                         text=f"chip '{state['chip']}' render failed:\n{e}",
                         font=(FONT, 8), fg=RED, bg=PANEL,
                         anchor="w", justify="left",
                         wraplength=500).pack(fill="x", pady=(10, 4))
                tk.Label(content,
                         text=traceback.format_exc()[:800],
                         font=(FONT, 7), fg=DIM2, bg=PANEL,
                         anchor="w", justify="left",
                         wraplength=540).pack(fill="x")

        if on_select:
            try: on_select(t)
            except Exception: pass

    def _set_chip(chip: str):
        state["chip"] = chip
        _paint_detail()

    def _query_last_runs(slug: str, limit: int = 8) -> list[dict]:
        """Fetch the N most recent backtest runs for a given engine slug.

        Reads from data/aurum.db (the canonical runs index). Returns an
        empty list if the DB is unavailable — never raises. Callers render
        a "no runs yet" placeholder when the list is empty.
        """
        try:
            import sqlite3 as _sq
            _db = Path("data/aurum.db")
            if not _db.exists():
                return []
            _c = _sq.connect(str(_db))
            try:
                rows = _c.execute(
                    """
                    SELECT run_id, timestamp, sharpe, sortino, roi, max_dd,
                           win_rate, n_trades, interval, json_path, veredito
                    FROM runs
                    WHERE engine = ?
                    ORDER BY run_id DESC
                    LIMIT ?
                    """,
                    (slug, int(limit)),
                ).fetchall()
            finally:
                _c.close()
            cols = ("run_id", "timestamp", "sharpe", "sortino", "roi",
                    "max_dd", "win_rate", "n_trades", "interval",
                    "json_path", "veredito")
            return [dict(zip(cols, r)) for r in rows]
        except Exception:
            return []

    def _open_run_artifact(json_path: Optional[str]) -> None:
        """Best-effort open the run JSON in the system default app.

        Silent no-op when the path is missing or the OS call fails — the UI
        never blocks on filesystem issues. On Windows uses os.startfile; on
        other platforms falls back to xdg-open via webbrowser.
        """
        if not json_path:
            return
        try:
            _p = Path(str(json_path))
            if not _p.exists():
                return
            import os as _os
            if hasattr(_os, "startfile"):
                _os.startfile(str(_p))  # type: ignore[attr-defined]
            else:
                import webbrowser as _wb
                _wb.open(_p.as_uri())
        except Exception:
            return

    def _paint_overview(host, t: EngineTrack):
        """LAST RUNS — canonical view of this engine's runs.

        Same table structure as DATA > BACKTESTS (_BT_RUN_COLS) pra
        manter paridade visual. Cada row lista um run real do
        data/aurum.db (engine=slug, ORDER BY run_id DESC). Click
        atualiza a KPI tape acima com as metricas daquele run e abre o
        JSON artifact.

        Columns: DATE/TIME (19) · TF (4) · DAYS (5) · TRDS (6) ·
                 SHRP (8) · ROI (8) · DD (7) · VER (3)
        """
        sbody = _scrollable(host)
        runs = _query_last_runs(t.slug, limit=12)
        if not runs:
            tk.Label(sbody, text="  ▸ no runs indexed for this engine yet",
                     font=(FONT, 8, "italic"), fg=DIM2, bg=PANEL, anchor="w",
                     wraplength=560, justify="left"
                     ).pack(fill="x", pady=(6, 6))
            return

        # Column spec — same widths pra header e rows (tabela alinhada).
        # Se mudar aqui, mude em ambos lugares ou vira drift visual.
        _cols = (
            ("DATE / TIME", 19, "w"),
            ("TF",           4, "w"),
            ("DAYS",         5, "e"),
            ("TRDS",         6, "e"),
            ("SHRP",         8, "e"),
            ("ROI",          8, "e"),
            ("DD",           7, "e"),
            ("V",            3, "e"),
        )

        hdr = tk.Frame(sbody, bg=PANEL)
        hdr.pack(fill="x", pady=(0, 2))
        for txt, w_, anc in _cols:
            tk.Label(hdr, text=txt, font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, width=w_, anchor=anc
                     ).pack(side="left", padx=(3, 0))
        tk.Frame(sbody, bg=BORDER, height=1).pack(fill="x")

        def _sharpe_color(v):
            if v is None: return DIM
            try: f = float(v)
            except (TypeError, ValueError): return DIM
            if f >= 1.5: return GREEN
            if f >= 0.5: return AMBER
            return RED

        def _roi_color(v):
            if v is None: return DIM
            try: return GREEN if float(v) > 0 else RED
            except (TypeError, ValueError): return DIM

        def _dd_color(v):
            # max_dd gravado em 0-100 (percentual). Valores baixos = bom.
            if v is None: return DIM
            try: f = float(v)
            except (TypeError, ValueError): return DIM
            if f < 10.0: return GREEN
            if f < 20.0: return AMBER
            return RED

        active_rid = (state.get("run_override") or {}).get("run_id")

        for run in runs:
            rid = str(run.get("run_id") or "")
            ts_raw = str(run.get("timestamp") or "")
            # Formato canonico: "YYYY-MM-DD HH:MM" (19 chars)
            ts = ts_raw[:16].replace("T", " ") if ts_raw else "-"
            tf = str(run.get("interval") or "-").lower()[:4]
            sd = run.get("scan_days")
            sd_txt = str(int(sd)) if isinstance(sd, (int, float)) else "-"
            sh = run.get("sharpe")
            roi = run.get("roi")
            nt = run.get("n_trades")
            dd = run.get("max_dd")
            ver = str(run.get("veredito") or "").strip().upper()

            sh_txt = f"{sh:+.2f}" if isinstance(sh, (int, float)) else "--"
            roi_txt = f"{roi:+.1f}%" if isinstance(roi, (int, float)) else "--"
            nt_txt = str(int(nt)) if isinstance(nt, (int, float)) else "--"
            dd_txt = f"{dd:.1f}%" if isinstance(dd, (int, float)) else "--"
            ver_txt = ("✓" if "PASS" in ver or ver == "OK"
                       else "⚠" if "WARN" in ver
                       else "✗" if "FAIL" in ver
                       else "·")
            ver_col = (GREEN if ver_txt == "✓"
                       else AMBER if ver_txt == "⚠"
                       else RED if ver_txt == "✗"
                       else DIM)

            is_active = rid == active_rid
            row_bg = BG2 if is_active else PANEL
            row = tk.Frame(sbody, bg=row_bg, cursor="hand2")
            row.pack(fill="x", pady=0)

            # Left accent rail — amber quando selecionado, transparente se nao
            rail_col = AMBER if is_active else PANEL
            tk.Frame(row, bg=rail_col, width=2).pack(side="left", fill="y")

            # Cells — peso "bold" fixo pra todas (consistencia de largura)
            def _c(parent, text, col, w, anchor):
                tk.Label(parent, text=text, font=(FONT, 8, "bold"),
                         fg=col, bg=row_bg, width=w, anchor=anchor
                         ).pack(side="left", padx=(3, 0))

            date_col = AMBER if is_active else WHITE
            _c(row, ts,      date_col,              _cols[0][1], _cols[0][2])
            _c(row, tf,      DIM2,                  _cols[1][1], _cols[1][2])
            _c(row, sd_txt,  DIM2,                  _cols[2][1], _cols[2][2])
            _c(row, nt_txt,  WHITE,                 _cols[3][1], _cols[3][2])
            _c(row, sh_txt,  _sharpe_color(sh),     _cols[4][1], _cols[4][2])
            _c(row, roi_txt, _roi_color(roi),       _cols[5][1], _cols[5][2])
            _c(row, dd_txt,  _dd_color(dd),         _cols[6][1], _cols[6][2])
            _c(row, ver_txt, ver_col,               _cols[7][1], _cols[7][2])

            json_path = run.get("json_path")
            def _click(_e=None, _r=run, _p=json_path):
                state["run_override"] = dict(_r)
                _paint_detail()
                _open_run_artifact(_p)
            def _enter(_e=None, _r=row):
                if _r.winfo_exists():
                    _r.configure(bg=BG3)
                    for child in _r.winfo_children():
                        try: child.configure(bg=BG3)
                        except Exception: pass
            def _leave(_e=None, _r=row, _bg=row_bg):
                if _r.winfo_exists():
                    _r.configure(bg=_bg)
                    for child in _r.winfo_children():
                        try: child.configure(bg=_bg)
                        except Exception: pass
            row.bind("<Button-1>", _click)
            row.bind("<Enter>", _enter)
            row.bind("<Leave>", _leave)
            for child in row.winfo_children():
                child.bind("<Button-1>", _click)
                child.bind("<Enter>", _enter)
                child.bind("<Leave>", _leave)

        # Footer — origem dos dados + hint de click
        tk.Frame(sbody, bg=BORDER, height=1).pack(fill="x", pady=(6, 2))
        tk.Label(sbody, text=f"  ▸ {len(runs)} runs · data/aurum.db (canonical) · click row = overlay KPIs",
                 font=(FONT, 7, "italic"), fg=DIM2, bg=PANEL, anchor="w"
                 ).pack(fill="x", pady=(0, 2))

    def _paint_brief(host, t: EngineTrack):
        """Research brief — institutional layout (moved from OVERVIEW).

        Sections render top-to-bottom in this fixed order:
          1. STRATEGY   — one-paragraph description
          2. METHOD     — numbered pipeline of steps
          3. EDGE · RISK — two terse tagged blocks
          4. EQUITY     — cumulative return curve
          5. RATIONALE  — extended thesis (optional deep-dive)

        Design notes:
          - Values left-aligned; headers 7pt amber bold; body 8pt white/dim
          - Accent bars are 1-2px DIM2, never thick or colored
          - Edge/Risk use a single-pixel top rule instead of filled bars
        """
        sbody = _scrollable(host)
        brief = t.brief or {}

        # ── 1. STRATEGY ─────────────────────────────────────────
        _section(sbody, "STRATEGY")
        what = brief.get("what")
        if what:
            tk.Label(sbody, text=what, font=(FONT, 9), fg=WHITE, bg=PANEL,
                     wraplength=560, justify="left", anchor="w"
                     ).pack(fill="x", pady=(0, 10))
        else:
            tk.Label(sbody, text="No strategy description available.",
                     font=(FONT, 8, "italic"), fg=DIM2, bg=PANEL,
                     anchor="w").pack(fill="x", pady=(0, 10))

        # ── 2. METHOD (pipeline) ────────────────────────────────
        logic = brief.get("logic")
        if logic:
            _section(sbody, "METHOD")
            for i, step in enumerate(logic, start=1):
                r = tk.Frame(sbody, bg=PANEL)
                r.pack(fill="x", pady=1)
                tk.Label(r, text=f"  {i:02d}", font=(FONT, 7),
                         fg=DIM, bg=PANEL, width=4,
                         anchor="w").pack(side="left")
                tk.Label(r, text=step, font=(FONT, 8),
                         fg=WHITE, bg=PANEL, anchor="w",
                         wraplength=510, justify="left"
                         ).pack(side="left", fill="x", expand=True)

        # ── 3. EDGE · RISK ──────────────────────────────────────
        if brief.get("edge") or brief.get("risk"):
            _section(sbody, "EDGE · RISK")
            cards = tk.Frame(sbody, bg=PANEL)
            cards.pack(fill="x", pady=(2, 10))

            def _card(parent, tag, tag_fg, body_text, body_fg, left_pad):
                card = tk.Frame(parent, bg=PANEL,
                                highlightbackground=BORDER,
                                highlightthickness=1)
                card.pack(side="left", fill="both", expand=True,
                          padx=(0 if left_pad == 0 else 4,
                                4 if left_pad == 0 else 0))
                tk.Label(card, text=tag, font=(FONT, 7, "bold"),
                         fg=tag_fg, bg=PANEL
                         ).pack(anchor="w", padx=8, pady=(6, 2))
                tk.Label(card, text=body_text, font=(FONT, 8),
                         fg=body_fg, bg=PANEL, anchor="w",
                         wraplength=250, justify="left"
                         ).pack(fill="x", padx=8, pady=(0, 8))
                return card

            if brief.get("edge"):
                _card(cards, "EDGE", GREEN, brief["edge"], WHITE, 0)
            if brief.get("risk"):
                _card(cards, "RISK", RED, brief["risk"], DIM2, 1)

        # ── 4. EQUITY ───────────────────────────────────────────
        _section(sbody, "EQUITY")
        cv = tk.Canvas(sbody, bg=PANEL, highlightthickness=1,
                       highlightbackground=BORDER, height=80)
        cv.pack(fill="x", pady=(0, 10))
        series = t.equity_series
        if series and len(series) >= 2:
            cv.after(20, lambda s=series: _draw_spark(cv, s, AMBER))
        else:
            cv.after(20, lambda: cv.create_text(
                (cv.winfo_width() or 400) // 2, 40,
                text="no data available",
                font=(FONT, 8), fill=DIM))

        # ── 5. RATIONALE (deep thesis) ─────────────────────────
        if brief.get("philosophy"):
            _section(sbody, "RATIONALE")
            tk.Label(sbody, text=brief["philosophy"],
                     font=(FONT, 8), fg=DIM2, bg=PANEL,
                     wraplength=560, justify="left", anchor="w"
                     ).pack(fill="x", pady=(0, 6))

    def _paint_config(host, t: EngineTrack):
        """LAB chip — the research workspace.

        Two-column layout puts `interactive controls` next to `calibrated
        reference values` so the user can compare what they're about to run
        against what was already validated. Pipeline sits full-width below.

          ┌─ PARAMETERS ─────────┬─ CALIBRATED ─────────┐
          │ PERIOD  [30][90]...  │ TF        1h         │
          │ BASKET  [majors]...  │ BASKET    bluechip   │
          │ LEV     [1x][2x]...  │ SHARPE    2.54       │
          │ CHARTS  [ON] [OFF]   │ STATUS    ✓ VALID    │
          └──────────────────────┴──────────────────────┘
          ▌ PIPELINE
          01  step one...
          02  step two...
          ...
          ── slug · script                 [OPEN EDITOR] ──
        """
        sbody = _scrollable(host)
        brief = t.brief or {}

        # ── Two-column top section ──
        top = tk.Frame(sbody, bg=PANEL)
        top.pack(fill="x", pady=(0, 6))
        col_left = tk.Frame(top, bg=PANEL)
        col_left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        col_right = tk.Frame(top, bg=PANEL)
        col_right.pack(side="left", fill="both", expand=True, padx=(6, 0))

        # ─── LEFT COLUMN: PARAMETERS (interactive) ─────
        _section(col_left, "PARAMETERS")

        def _pill_row(parent, label, opts, state_key):
            tk.Label(parent, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, anchor="w"
                     ).pack(fill="x", pady=(4, 1))
            wrap = tk.Frame(parent, bg=PANEL)
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

        _pill_row(col_left, "PERIOD",   PERIOD_OPTS,   "cfg_period")
        _pill_row(col_left, "BASKET",   BASKET_OPTS,   "cfg_basket")
        _pill_row(col_left, "LEVERAGE", LEVERAGE_OPTS, "cfg_leverage")

        tk.Label(col_left, text="CHARTS", font=(FONT, 7, "bold"),
                 fg=DIM, bg=PANEL, anchor="w"
                 ).pack(fill="x", pady=(4, 1))
        trow = tk.Frame(col_left, bg=PANEL)
        trow.pack(fill="x", pady=(0, 4))
        on = state["cfg_plots"] == "s"
        plot_btn = tk.Label(trow,
                            text=" ON " if on else " OFF ",
                            font=(FONT, 8, "bold"),
                            fg=BG, bg=GREEN if on else BG3,
                            padx=8, pady=3, cursor="hand2")
        plot_btn.pack(side="left")

        def _toggle_plots(_e=None):
            state["cfg_plots"] = "n" if state["cfg_plots"] == "s" else "s"
            _on = state["cfg_plots"] == "s"
            plot_btn.config(text=" ON " if _on else " OFF ",
                            fg=BG if _on else DIM,
                            bg=GREEN if _on else BG3)
        plot_btn.bind("<Button-1>", _toggle_plots)

        # ─── RIGHT COLUMN: CALIBRATED reference values ─────
        _section(col_right, "CALIBRATED")

        def _ref_row(parent, label, value, color=WHITE):
            r = tk.Frame(parent, bg=PANEL)
            r.pack(fill="x", pady=1)
            tk.Label(r, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, width=10,
                     anchor="w").pack(side="left")
            tk.Label(r, text=str(value), font=(FONT, 8),
                     fg=color, bg=PANEL, anchor="w",
                     wraplength=250, justify="left"
                     ).pack(side="left", fill="x", expand=True)

        bc = brief.get("best_config") or {}
        if bc:
            for k, v in bc.items():
                v_str = str(v)
                color = (GREEN if ("✓" in v_str or "PASS" in v_str) else
                         RED if ("✗" in v_str or "FAIL" in v_str) else
                         AMBER if ("⚠" in v_str or "WARN" in v_str) else WHITE)
                # Truncate long values to keep the column narrow
                display = v_str if len(v_str) <= 40 else v_str[:38] + "…"
                _ref_row(col_right, k.upper()[:9], display, color)
        else:
            tk.Label(col_right, text="  (no calibration data)",
                     font=(FONT, 7, "italic"), fg=DIM2, bg=PANEL,
                     anchor="w").pack(fill="x", pady=4)

        # ── PIPELINE (full-width below the two columns) ──
        logic = brief.get("logic")
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
                         wraplength=520,
                         justify="left").pack(
                    side="left", fill="x", expand=True)

        # ── Footer ──
        tk.Frame(sbody, bg=BORDER, height=1).pack(fill="x", pady=(10, 6))
        foot = tk.Frame(sbody, bg=PANEL)
        foot.pack(fill="x", pady=(0, 4))
        tk.Label(foot, text=t.slug.upper(), font=(FONT, 7, "bold"),
                 fg=AMBER_H, bg=PANEL).pack(side="left")
        tk.Label(foot, text=f"  ·  {t.script_path or '--'}",
                 font=(FONT, 7), fg=DIM2, bg=PANEL,
                 anchor="w").pack(side="left", fill="x", expand=True)
        if t.on_config:
            b = tk.Label(foot, text=" OPEN EDITOR ",
                         font=(FONT, 8, "bold"),
                         fg=BG, bg=AMBER, padx=10, pady=4,
                         cursor="hand2")
            b.pack(side="right")
            b.bind("<Button-1>", lambda _e: _safe(t.on_config))
            b.bind("<Enter>", lambda _e: b.config(bg=AMBER_H))
            b.bind("<Leave>", lambda _e: b.config(bg=AMBER))
    def _paint_code(host, t: EngineTrack):
        """CODE chip — source viewer with async file read.

        OneDrive sync can stall a read briefly (WinError 5 / retry loop),
        so we kick the read off in a daemon thread and replace the
        placeholder label once the text arrives. Keeps Tk responsive.
        """
        path = t.script_path or ""
        root = Path(__file__).resolve().parent.parent.parent
        target = root / path if path else None

        tk.Label(host, text=f"  {path or '— no script path —'}",
                 font=(FONT, 7), fg=DIM2, bg=PANEL,
                 anchor="w").pack(fill="x")

        text_wrap = tk.Frame(host, bg=PANEL)
        text_wrap.pack(fill="both", expand=True, pady=(4, 0))
        text = tk.Text(text_wrap, bg=BG2, fg=WHITE, insertbackground=AMBER,
                       bd=0, highlightthickness=1,
                       highlightbackground=BORDER,
                       font=(FONT, 8), wrap="none", height=18)
        sb = tk.Scrollbar(text_wrap, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=sb.set)
        text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        text.insert("1.0", "# loading ...")
        text.configure(state="disabled")

        def _load():
            try:
                if target and target.is_file():
                    with open(target, "r", encoding="utf-8",
                              errors="replace") as f:
                        content = f.read(120_000)  # cap ~120KB
                else:
                    content = f"# — script not found —\n\n# path: {path}\n"
            except Exception as e:
                content = f"# error reading file: {e}\n"

            def _apply():
                try:
                    text.configure(state="normal")
                    text.delete("1.0", "end")
                    text.insert("1.0", content)
                    text.configure(state="disabled")
                except Exception:
                    pass
            try: host.after(0, _apply)
            except Exception: pass

        import threading as _th
        _th.Thread(target=_load, daemon=True).start()

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
        log_path, log_text = _load_live_log(t.slug, n_lines=300)

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

        text_w.insert("1.0", log_text)
        text_w.see("end")
        text_w.configure(state="disabled")

    def _paint_positions(host, t: EngineTrack):
        """Open positions for this engine's most recent live run."""
        positions = _load_live_positions(t.slug)

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
        # Inline editable params (merged from old LAB chip). Row of pill
        # groups — clicking a pill flips state[cfg_*] then re-colors the
        # row without re-rendering the whole RUN view.
        params = tk.Frame(host, bg=PANEL)
        params.pack(fill="x", pady=(0, 6))

        def _pill_group(parent, label, opts, state_key, width_label=8):
            row = tk.Frame(parent, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, width=width_label, anchor="w"
                     ).pack(side="left")
            btns: list = []
            for text_, val in opts:
                active = state[state_key] == val
                b = tk.Label(row, text=f" {text_} ",
                             font=(FONT, 7, "bold"),
                             fg=BG if active else WHITE,
                             bg=AMBER if active else BG3,
                             padx=5, pady=2, cursor="hand2")
                b.pack(side="left", padx=1)
                btns.append((b, val))

                def _click(_e=None, _v=val, _btns=btns, _k=state_key):
                    state[_k] = _v
                    for _b, _bv in _btns:
                        on = _bv == _v
                        _b.config(fg=BG if on else WHITE,
                                  bg=AMBER if on else BG3)
                b.bind("<Button-1>", _click)

        _pill_group(params, "PERIOD",  PERIOD_OPTS,   "cfg_period")
        _pill_group(params, "BASKET",  BASKET_OPTS,   "cfg_basket")
        _pill_group(params, "LEV",     LEVERAGE_OPTS, "cfg_leverage")

        # Charts toggle inline
        tog_row = tk.Frame(params, bg=PANEL)
        tog_row.pack(fill="x", pady=(1, 0))
        tk.Label(tog_row, text="CHARTS", font=(FONT, 7, "bold"),
                 fg=DIM, bg=PANEL, width=8, anchor="w").pack(side="left")
        on = state["cfg_plots"] == "s"
        plot_btn = tk.Label(tog_row,
                            text=" ON " if on else " OFF ",
                            font=(FONT, 7, "bold"),
                            fg=BG, bg=GREEN if on else BG3,
                            padx=6, pady=2, cursor="hand2")
        plot_btn.pack(side="left", padx=1)

        def _toggle_plots(_e=None):
            state["cfg_plots"] = "n" if state["cfg_plots"] == "s" else "s"
            _on = state["cfg_plots"] == "s"
            plot_btn.config(text=" ON " if _on else " OFF ",
                            fg=BG if _on else DIM,
                            bg=GREEN if _on else BG3)
        plot_btn.bind("<Button-1>", _toggle_plots)

        tk.Frame(host, bg=BORDER, height=1).pack(fill="x", pady=(8, 6))

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
        state["run_override"] = None  # drop LAST RUNS overlay on engine switch
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
        return "break"
    # Direct bindings (not bind_all) — avoids global handler leaks across
    # re-renders. See _scrollable() for the rationale.
    canvas.bind("<MouseWheel>", _wheel)
    track_list.bind("<MouseWheel>", _wheel)

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
