"""AURUM — ENGINES LIVE cockpit view.

Hybrid master-detail UI for the EXECUTE → ENGINES LIVE entry.
Separates engines into three buckets by readiness:

    LIVE        — currently running live/demo/testnet/paper
    READY       — has a validated live runner (ENGINES[*].live_ready)
    RESEARCH    — backtest-only, not exposed for live execution

Pure helpers here are testable; Tkinter rendering is smoke-tested
via `python launcher.py` → EXECUTE → ENGINES LIVE.

Spec: docs/superpowers/specs/2026-04-16-engines-live-cockpit-design.md
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from typing import Literal

from core.ui_palette import (
    BG, BG2, BG3, PANEL,
    BORDER, BORDER_H,
    AMBER, AMBER_B, AMBER_D, AMBER_H,
    WHITE, DIM, DIM2,
    GREEN, RED, CYAN, HAZARD,
    MODE_PAPER, MODE_DEMO, MODE_TESTNET, MODE_LIVE,
    FONT,
)

Bucket = Literal["LIVE", "READY", "RESEARCH"]
Mode = Literal["paper", "demo", "testnet", "live"]

_MODE_ORDER: tuple[Mode, ...] = ("paper", "demo", "testnet", "live")
_DEFAULT_MODE: Mode = "paper"
_DEFAULT_STATE_PATH = Path("data/ui_state.json")

_MODE_COLORS: dict[Mode, str] = {
    "paper":   MODE_PAPER,
    "demo":    MODE_DEMO,
    "testnet": MODE_TESTNET,
    "live":    MODE_LIVE,
}


def assign_bucket(*, slug: str, is_running: bool, live_ready: bool) -> Bucket:
    """Decide which bucket an engine belongs to in the cockpit view.

    Rules:
      - A running engine that is also live_ready → LIVE.
      - A non-running live_ready engine → READY.
      - Anything not live_ready → RESEARCH (even if running, since it was
        spawned through the backtest path and doesn't belong on the live
        cockpit).
    """
    if not live_ready:
        return "RESEARCH"
    return "LIVE" if is_running else "READY"


def cycle_mode(current: str) -> Mode:
    """paper → demo → testnet → live → paper. Unknown input → paper."""
    try:
        idx = _MODE_ORDER.index(current)  # type: ignore[arg-type]
    except ValueError:
        return _DEFAULT_MODE
    return _MODE_ORDER[(idx + 1) % len(_MODE_ORDER)]


def load_mode(*, state_path: Path | None = None) -> Mode:
    """Read engines_live.mode from ui_state.json. Missing/invalid → paper."""
    path = state_path or _DEFAULT_STATE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULT_MODE
    mode = (data.get("engines_live") or {}).get("mode")
    if mode in _MODE_ORDER:
        return mode  # type: ignore[return-value]
    return _DEFAULT_MODE


def save_mode(mode: Mode, *, state_path: Path | None = None) -> None:
    """Persist engines_live.mode into ui_state.json. Preserves other keys.

    Uses atomic_write_json so a crashed write leaves the prior file intact.
    """
    from core.persistence import atomic_write_json
    path = state_path or _DEFAULT_STATE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    block = dict(data.get("engines_live") or {})
    block["mode"] = mode
    data["engines_live"] = block
    atomic_write_json(path, data)


def live_confirm_ok(*, engine_name: str, user_input: str) -> bool:
    """Case-sensitive, whitespace-strict match used by the LIVE modal."""
    return user_input == engine_name


def format_uptime(*, seconds: float | int | None) -> str:
    """Render uptime compactly for bucket rows and cockpit headers."""
    if seconds is None:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


# Legacy proc-manager engine names → canonical slugs.
# Matches the mapping in launcher.py::_strategies (_proc_to_slug).
_PROC_TO_SLUG: dict[str, str] = {
    "backtest":    "citadel",
    "mercurio":    "jump",
    "thoth":       "bridgewater",
    "newton":      "deshaw",
    "multi":       "millennium",
    "prometeu":    "twosigma",
    "renaissance": "renaissance",
    "live":        "live",
    "arb":         "janestreet",
    "darwin":      "aqr",
    "chronos":     "winton",
    "kepos":       "kepos",
    "graham":      "graham",
}


def running_slugs_from_procs(procs: list[dict]) -> dict[str, dict]:
    """Filter live proc-manager rows into {slug: proc_row}.

    A proc is considered running when status=='running' AND alive=True.
    Unknown engine names are dropped silently.
    """
    out: dict[str, dict] = {}
    for p in procs:
        if p.get("status") != "running" or not p.get("alive"):
            continue
        slug = _PROC_TO_SLUG.get(p.get("engine"))
        if slug:
            out[slug] = p
    return out


# ════════════════════════════════════════════════════════════════
# Tkinter rendering — smoke-tested via launcher, not unit-tested
# ════════════════════════════════════════════════════════════════

def render(launcher, parent, *, on_escape) -> dict:
    """Mount the ENGINES LIVE cockpit view onto `parent`.

    `launcher` is the AurumTerminal instance (for _kb/_exec/_clr utilities).
    `on_escape` is a no-arg callable invoked when ESC is pressed.

    Returns a handle dict:
        {"refresh": callable, "cleanup": callable, "set_mode": callable}
    """
    state: dict = {
        "mode":           load_mode(),
        "selected_slug":  None,
        "selected_bucket": None,
        "after_handles":  [],
        "bound_keys":     [],
    }

    root = tk.Frame(parent, bg=BG)
    root.pack(fill="both", expand=True)
    # Backref so nested widgets can reach the state when rebinding.
    root._engines_live_state = state  # type: ignore[attr-defined]

    header = _build_header(root, launcher, state)
    header.pack(fill="x", padx=14, pady=(10, 0))

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=14, pady=(8, 0))

    # Split 38/62 master/detail — weighted uniform columns so resize
    # keeps the ratio stable.
    body.grid_columnconfigure(0, weight=38, uniform="body")
    body.grid_columnconfigure(1, weight=62, uniform="body")
    body.grid_rowconfigure(0, weight=1)

    state["master_host"] = tk.Frame(body, bg=BG)
    state["master_host"].grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    state["detail_host"] = tk.Frame(body, bg=BG)
    state["detail_host"].grid(row=0, column=1, sticky="nsew")

    footer = _build_footer(root, state)
    footer.pack(fill="x", padx=14, pady=(6, 10))
    state["footer_frame"] = footer

    def _kb(seq, fn):
        launcher._kb(seq, fn)
        state["bound_keys"].append(seq)

    _kb("<Escape>", on_escape)
    _kb("<Key-0>", on_escape)

    def refresh():
        _render_master_list(state, launcher)
        _render_detail(state, launcher)
        _refresh_header(state)
        _refresh_footer(state)

    def cleanup():
        for aid in list(state.get("after_handles", [])):
            try:
                launcher.after_cancel(aid)
            except Exception:
                pass
        state["after_handles"] = []

    def set_mode(mode):
        if mode not in _MODE_ORDER:
            return
        state["mode"] = mode
        try:
            save_mode(mode)
        except Exception:
            pass
        refresh()

    state["refresh"] = refresh
    state["set_mode"] = set_mode

    _kb("<KeyPress-m>", lambda _e=None: set_mode(cycle_mode(state["mode"])))
    _kb("<KeyPress-M>", lambda _e=None: set_mode(cycle_mode(state["mode"])))

    refresh()
    return {"refresh": refresh, "cleanup": cleanup, "set_mode": set_mode}


def _build_header(parent, launcher, state) -> tk.Frame:
    h = tk.Frame(parent, bg=BG)
    tk.Frame(h, bg=AMBER, width=3, height=22).pack(side="left", padx=(0, 8))
    tk.Label(h, text="ENGINES", font=(FONT, 12, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 14))

    pill_row = tk.Frame(h, bg=BG)
    pill_row.pack(side="left")
    state["mode_pills"] = {}
    for mode in _MODE_ORDER:
        pill = tk.Label(pill_row, text=f" {mode.upper()} ",
                        font=(FONT, 7, "bold"),
                        padx=6, pady=3, cursor="hand2")
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _m=mode: state["set_mode"](_m))
        state["mode_pills"][mode] = pill

    right = tk.Frame(h, bg=BG)
    right.pack(side="right")
    state["counts_lbl"] = tk.Label(right, text="", font=(FONT, 7, "bold"),
                                    fg=DIM, bg=BG)
    state["counts_lbl"].pack(side="right", padx=(8, 0))

    # Header bottom rule — turns RED when mode=live (set in _refresh_header)
    rule = tk.Frame(parent, bg=BORDER, height=1)
    rule.pack(fill="x", pady=(8, 0))
    state["header_rule"] = rule
    return h


def _refresh_header(state):
    for mode, pill in state.get("mode_pills", {}).items():
        color = _MODE_COLORS[mode]
        if mode == state["mode"]:
            pill.configure(fg=BG, bg=color)
        else:
            pill.configure(fg=color, bg=BG3)
    rule = state.get("header_rule")
    if rule is not None:
        rule.configure(bg=(RED if state["mode"] == "live" else BORDER))


def _build_footer(parent, state) -> tk.Frame:
    f = tk.Frame(parent, bg=BG)
    state["footer_lbl"] = tk.Label(f, text="", font=(FONT, 7),
                                    fg=DIM, bg=BG, anchor="w")
    state["footer_lbl"].pack(side="left", fill="x", expand=True)
    state["footer_warn_lbl"] = tk.Label(f, text="", font=(FONT, 7, "bold"),
                                         fg=RED, bg=BG)
    state["footer_warn_lbl"].pack(side="right")
    return f


def _refresh_footer(state):
    selected = state.get("selected_bucket")
    hints = ["ESC main", "▲▼ select"]
    if selected == "LIVE":
        hints += ["S stop", "L log"]
    elif selected == "READY":
        hints += ["ENTER run"]
    elif selected == "RESEARCH":
        hints += ["B backtest"]
    hints += ["M cycle mode"]
    state["footer_lbl"].configure(text="  ·  ".join(hints))
    state["footer_warn_lbl"].configure(
        text=("⚠ LIVE MODE — real orders will be placed"
              if state["mode"] == "live" else ""))


def _render_master_list(state, launcher):
    """Mount the 3-bucket master list on state['master_host']."""
    host = state["master_host"]
    for w in host.winfo_children():
        w.destroy()

    from config.engines import ENGINES, LIVE_READY_SLUGS
    try:
        from core.proc import list_procs
        procs = list_procs()
    except Exception:
        procs = []
    running = running_slugs_from_procs(procs)

    live_items: list[tuple[str, dict, dict]] = []
    ready_items: list[tuple[str, dict]] = []
    research_items: list[tuple[str, dict]] = []
    for slug, meta in ENGINES.items():
        live_ready = slug in LIVE_READY_SLUGS
        bucket = assign_bucket(
            slug=slug,
            is_running=slug in running,
            live_ready=live_ready,
        )
        if bucket == "LIVE":
            live_items.append((slug, meta, running[slug]))
        elif bucket == "READY":
            ready_items.append((slug, meta))
        else:
            research_items.append((slug, meta))

    # Scrollable container
    canvas = tk.Canvas(host, bg=BG, highlightthickness=0)
    vbar = tk.Scrollbar(host, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=BG)
    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")

    # Default selection: first LIVE, else first READY, else first RESEARCH
    if state.get("selected_slug") is None:
        if live_items:
            state["selected_slug"] = live_items[0][0]
            state["selected_bucket"] = "LIVE"
        elif ready_items:
            state["selected_slug"] = ready_items[0][0]
            state["selected_bucket"] = "READY"
        elif research_items:
            state["selected_slug"] = research_items[0][0]
            state["selected_bucket"] = "RESEARCH"

    _render_bucket(inner, "LIVE", live_items, state)
    _render_bucket(inner, "READY LIVE", ready_items, state)
    _render_bucket(inner, "RESEARCH", research_items, state)

    total = len(live_items) + len(ready_items) + len(research_items)
    state["counts_lbl"].configure(
        text=f"{total} engines  ·  {len(live_items)} live")


def _render_bucket(parent, title, items, state):
    if not items:
        return
    header = tk.Frame(parent, bg=BG)
    header.pack(fill="x", pady=(8, 2))
    tk.Frame(header, bg=AMBER, width=3, height=14).pack(side="left", padx=(0, 6))
    tk.Label(header, text=f"{title}", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left")
    tk.Label(header, text=f"  · {len(items)}", font=(FONT, 7),
             fg=DIM, bg=BG).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))

    is_live_bucket = title == "LIVE"
    is_research = title == "RESEARCH"
    for tup in items:
        if is_live_bucket:
            slug, meta, proc = tup
            _render_row_live(parent, slug, meta, proc, state)
        elif is_research:
            slug, meta = tup
            _render_row_research(parent, slug, meta, state)
        else:
            slug, meta = tup
            _render_row_ready(parent, slug, meta, state)


def _select_slug(state, slug, bucket):
    """Update selection and re-render master + detail."""
    state["selected_slug"] = slug
    state["selected_bucket"] = bucket
    state["refresh"]()


def _row_base(parent, slug, state, is_selected):
    bg = BG3 if is_selected else BG
    row = tk.Frame(parent, bg=bg, cursor="hand2")
    # left selection bar (3px amber when selected)
    tk.Frame(row, bg=(AMBER_B if is_selected else BG), width=3).pack(side="left", fill="y")
    row.pack(fill="x", pady=1)
    return row


def _render_row_live(parent, slug, meta, proc, state):
    sel = state.get("selected_slug") == slug
    row = _row_base(parent, slug, state, is_selected=sel)
    bg = row["bg"]
    tk.Label(row, text="●", fg=GREEN, bg=bg,
             font=(FONT, 9, "bold"), padx=4).pack(side="left")
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=WHITE, bg=bg, font=(FONT, 9, "bold")).pack(side="left")
    mode_key = (proc.get("engine_mode") or proc.get("mode") or "").lower()
    if mode_key in _MODE_ORDER:
        tk.Label(row, text=f" {mode_key.upper()} ",
                 fg=BG, bg=_MODE_COLORS[mode_key],
                 font=(FONT, 7, "bold"), padx=4, pady=1).pack(side="left", padx=(6, 0))
    started = proc.get("started")
    if started:
        try:
            from datetime import datetime as _dt
            secs = (_dt.now() - _dt.fromisoformat(started)).total_seconds()
            tk.Label(row, text=format_uptime(seconds=secs),
                     fg=DIM2, bg=bg, font=(FONT, 8)).pack(side="left", padx=(8, 0))
        except Exception:
            pass
    for w in (row,) + tuple(row.winfo_children()):
        w.bind("<Button-1>", lambda _e, _s=slug: _select_slug(state, _s, "LIVE"))


def _render_row_ready(parent, slug, meta, state):
    sel = state.get("selected_slug") == slug
    row = _row_base(parent, slug, state, is_selected=sel)
    bg = row["bg"]
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=WHITE, bg=bg, font=(FONT, 9, "bold"),
             padx=8).pack(side="left")
    sub = _subtitle_for(slug, meta)
    if sub:
        tk.Label(row, text=sub, fg=DIM, bg=bg,
                 font=(FONT, 7)).pack(side="left", padx=(4, 0))
    for w in (row,) + tuple(row.winfo_children()):
        w.bind("<Button-1>", lambda _e, _s=slug: _select_slug(state, _s, "READY"))


def _render_row_research(parent, slug, meta, state):
    sel = state.get("selected_slug") == slug
    row = _row_base(parent, slug, state, is_selected=sel)
    bg = row["bg"]
    tk.Label(row, text="🔒", fg=DIM, bg=bg,
             font=(FONT, 8), padx=4).pack(side="left")
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=DIM, bg=bg, font=(FONT, 9)).pack(side="left")
    sub = _subtitle_for(slug, meta)
    if sub:
        tk.Label(row, text=sub, fg=DIM2, bg=bg,
                 font=(FONT, 7)).pack(side="left", padx=(4, 0))
    for w in (row,) + tuple(row.winfo_children()):
        w.bind("<Button-1>", lambda _e, _s=slug: _select_slug(state, _s, "RESEARCH"))


def _subtitle_for(slug, meta) -> str:
    """Tagline fallback — extended later to read DB / BRIEFINGS."""
    desc = meta.get("desc") or ""
    return desc[:44]


def _render_detail(state, launcher):
    host = state["detail_host"]
    for w in host.winfo_children():
        w.destroy()

    slug = state.get("selected_slug")
    bucket = state.get("selected_bucket")
    if not slug:
        tk.Label(host, text="(no selection)", fg=DIM, bg=BG,
                 font=(FONT, 8)).pack(pady=20)
        return

    from config.engines import ENGINES
    meta = ENGINES.get(slug, {})

    card = tk.Frame(host, bg=PANEL,
                    highlightbackground=BORDER, highlightthickness=1)
    card.pack(fill="both", expand=True)

    if bucket == "RESEARCH":
        _render_detail_research(card, slug, meta, state, launcher)
    elif bucket == "READY":
        _render_detail_ready(card, slug, meta, state, launcher)
    elif bucket == "LIVE":
        _render_detail_live(card, slug, meta, state, launcher)


def _render_detail_research(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=" [ RESEARCH ONLY ] ",
             fg=BG, bg=HAZARD, font=(FONT, 7, "bold"),
             padx=6, pady=2).pack(side="right")

    if desc:
        tk.Label(parent, text=desc, fg=DIM, bg=PANEL,
                 font=(FONT, 8), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=12, pady=(0, 8))

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    note = tk.Frame(parent, bg=PANEL)
    note.pack(fill="x", padx=12, pady=12)
    tk.Label(note, text="⚠", fg=HAZARD, bg=PANEL,
             font=(FONT, 12, "bold")).pack(side="left", padx=(0, 8))
    tk.Label(
        note,
        text=("Essa engine ainda não tem entrypoint live validado.\n"
              "Rode em backtest: EXECUTE → BACKTEST → " + name),
        fg=HAZARD, bg=PANEL, font=(FONT, 8),
        anchor="w", justify="left",
    ).pack(side="left", fill="x", expand=True)

    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(8, 12))
    _action_btn(actions, "GO TO BACKTEST", AMBER,
                lambda: _go_to_backtest(launcher, slug))
    _action_btn(actions, "VIEW CODE", DIM,
                lambda: _view_code(launcher, meta.get("script", "")))


def _action_btn(parent, label, color, cmd):
    b = tk.Label(parent, text=f"  {label}  ",
                 fg=color, bg=BG3,
                 font=(FONT, 8, "bold"),
                 cursor="hand2", padx=4, pady=6)
    b.pack(side="left", padx=(0, 8))
    b.bind("<Button-1>", lambda _e: cmd())
    b.bind("<Enter>", lambda _e, _b=b, _c=color: _b.configure(fg=BG, bg=_c))
    b.bind("<Leave>", lambda _e, _b=b, _c=color: _b.configure(fg=_c, bg=BG3))
    return b


def _go_to_backtest(launcher, slug):
    """Bounce to EXECUTE → BACKTEST, pre-selecting this engine if possible."""
    fn = getattr(launcher, "_strategies_backtest", None)
    if callable(fn):
        fn()


def _view_code(launcher, script_path):
    if not script_path:
        return
    try:
        from code_viewer import CodeViewer
        CodeViewer(launcher, script_path)
    except Exception:
        pass


# Config defaults for the READY skin's inline config row.
_PERIOD_OPTS   = [("30D", "30"), ("90D", "90"), ("180D", "180"), ("365D", "365")]
_BASKET_OPTS   = [("DEFAULT", ""), ("TOP12", "2"), ("DEFI", "3"), ("L1", "4"),
                  ("L2", "5"), ("AI", "6"), ("MEME", "7"), ("MAJORS", "8"),
                  ("BLUECHIP", "9")]
_LEVERAGE_OPTS = [("1x", "1.0"), ("2x", "2.0"), ("3x", "3.0"), ("5x", "5.0")]


def _render_detail_ready(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=" READY ", fg=BG, bg=GREEN,
             font=(FONT, 7, "bold"), padx=6, pady=2).pack(side="right")

    if desc:
        tk.Label(parent, text=desc, fg=DIM, bg=PANEL,
                 font=(FONT, 8), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=12, pady=(0, 8))

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    cfg_store = state.setdefault("config", {})
    cfg = cfg_store.setdefault(slug, {"period": "90", "basket": "", "leverage": "2.0"})

    cfg_frame = tk.Frame(parent, bg=PANEL)
    cfg_frame.pack(fill="x", padx=12, pady=(10, 8))
    tk.Label(cfg_frame, text="CONFIG", fg=AMBER_D, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w", pady=(0, 4))
    _config_row(cfg_frame, "Period",   _PERIOD_OPTS,   cfg, "period", state)
    _config_row(cfg_frame, "Basket",   _BASKET_OPTS,   cfg, "basket", state)
    _config_row(cfg_frame, "Leverage", _LEVERAGE_OPTS, cfg, "leverage", state)

    mode = state["mode"]
    run_color = _MODE_COLORS[mode]
    run_frame = tk.Frame(parent, bg=PANEL)
    run_frame.pack(fill="x", padx=12, pady=(8, 10))
    btn = tk.Label(
        run_frame,
        text=f"  RUN IN {mode.upper()} MODE  ",
        fg=BG, bg=run_color,
        font=(FONT, 11, "bold"),
        cursor="hand2", padx=8, pady=10,
    )
    btn.pack(fill="x")
    btn.bind("<Button-1>",
             lambda _e: _run_engine(launcher, slug, meta, state))

    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(0, 12))
    _action_btn(actions, "VIEW CODE", DIM,
                lambda: _view_code(launcher, meta.get("script", "")))
    _action_btn(actions, "PAST RUNS", DIM,
                lambda: _past_runs(launcher, slug))


def _config_row(parent, label, opts, cfg_dict, cfg_key, state):
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=1)
    tk.Label(row, text=f"  {label:<10}", fg=DIM, bg=PANEL,
             font=(FONT, 8)).pack(side="left")
    for disp, val in opts:
        active = cfg_dict.get(cfg_key) == val
        fg = BG if active else DIM2
        bg = AMBER if active else BG3
        pill = tk.Label(row, text=f" {disp} ",
                        fg=fg, bg=bg, font=(FONT, 7, "bold"),
                        cursor="hand2", padx=4, pady=1)
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _v=val, _k=cfg_key, _d=cfg_dict, _s=state:
                      _set_cfg(_d, _k, _v, _s))


def _set_cfg(cfg_dict, key, val, state):
    cfg_dict[key] = val
    refresh = state.get("refresh")
    if callable(refresh):
        refresh()


def _run_engine(launcher, slug, meta, state):
    mode = state["mode"]
    cfg = (state.get("config") or {}).get(slug) or {}
    name = meta.get("display", slug.upper())
    script = meta.get("script", "")
    desc = meta.get("desc", "")

    def _spawn():
        fn = getattr(launcher, "_exec_live_inline", None)
        if callable(fn):
            fn(name, script, desc, mode, cfg)

    if mode == "live":
        _confirm_live_modal(launcher, name, on_confirm=_spawn)
    else:
        _spawn()


def _confirm_live_modal(launcher, engine_name, *, on_confirm):
    """Ritual modal for LIVE mode — user must type the engine name."""
    top = tk.Toplevel()
    top.title("LIVE EXECUTION")
    top.configure(bg=BG)
    top.geometry("420x240")
    top.resizable(False, False)
    top.transient()
    top.grab_set()

    tk.Label(top, text=f"LIVE EXECUTION — {engine_name}",
             fg=RED, bg=BG, font=(FONT, 10, "bold")).pack(pady=(14, 4))
    tk.Label(
        top,
        text=(f"Você está prestes a ligar {engine_name} em modo LIVE.\n"
              "Real money, real orders."),
        fg=WHITE, bg=BG, font=(FONT, 8), justify="center",
    ).pack(pady=(0, 10))
    tk.Label(top, text=f"Digite  {engine_name}  pra confirmar:",
             fg=DIM, bg=BG, font=(FONT, 8)).pack()

    var = tk.StringVar()
    entry = tk.Entry(top, textvariable=var, bg=BG3, fg=WHITE,
                     insertbackground=WHITE, font=(FONT, 10),
                     width=28, justify="center",
                     highlightbackground=BORDER, highlightthickness=1)
    entry.pack(pady=8)
    entry.focus_set()

    row = tk.Frame(top, bg=BG)
    row.pack(pady=(6, 0))
    cancel = tk.Label(row, text="  CANCEL  ", fg=DIM, bg=BG3,
                      font=(FONT, 8, "bold"), cursor="hand2",
                      padx=4, pady=6)
    cancel.pack(side="left", padx=8)
    cancel.bind("<Button-1>", lambda _e: top.destroy())

    confirm = tk.Label(row, text="  CONFIRM & RUN  ",
                       fg=DIM2, bg=BG3,
                       font=(FONT, 8, "bold"), cursor="arrow",
                       padx=4, pady=6)
    confirm.pack(side="left", padx=8)

    def _on_change(*_):
        ok = live_confirm_ok(engine_name=engine_name, user_input=var.get())
        if ok:
            confirm.configure(fg=BG, bg=RED, cursor="hand2")
            confirm.bind("<Button-1>",
                         lambda _e: (top.destroy(), on_confirm()))
        else:
            confirm.configure(fg=DIM2, bg=BG3, cursor="arrow")
            confirm.unbind("<Button-1>")
    var.trace_add("write", _on_change)
    top.bind("<Escape>", lambda _e: top.destroy())


def _past_runs(launcher, slug):
    fn = getattr(launcher, "_data_center", None)
    if callable(fn):
        fn()


def _render_detail_live(parent, slug, meta, state, launcher):
    """Stub — filled in Task 11."""
    tk.Label(parent, text=f"(live — task 11) {slug}",
             fg=DIM, bg=PANEL, font=(FONT, 8)).pack(pady=20)
