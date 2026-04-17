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
import os
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

_ENGINE_DIR_MAP: dict[str, str] = {
    "citadel": "runs",
}


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _uptime_seconds(proc: dict) -> float | None:
    for key in ("uptime_seconds", "uptime_s", "uptime"):
        value = _safe_float(proc.get(key))
        if value is not None:
            return value
    started = proc.get("started")
    if not started:
        return None
    try:
        from datetime import datetime as _dt
        return (_dt.now() - _dt.fromisoformat(str(started))).total_seconds()
    except Exception:
        return None


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
    _kb("<Up>", lambda _e=None: _move_selection(state, -1))
    _kb("<Down>", lambda _e=None: _move_selection(state, 1))
    _kb("<Left>", lambda _e=None: _move_live_selection(state, -1))
    _kb("<Right>", lambda _e=None: _move_live_selection(state, 1))
    _kb("<Return>", lambda _e=None: _activate_selection(state, launcher))
    _kb("<KeyPress-l>", lambda _e=None: _open_selected_log(state, launcher))
    _kb("<KeyPress-L>", lambda _e=None: _open_selected_log(state, launcher))
    _kb("<KeyPress-s>", lambda _e=None: _stop_selected_live(state, launcher))
    _kb("<KeyPress-S>", lambda _e=None: _stop_selected_live(state, launcher))
    _kb("<KeyPress-b>", lambda _e=None: _open_selected_backtest(state, launcher))
    _kb("<KeyPress-B>", lambda _e=None: _open_selected_backtest(state, launcher))

    refresh()
    return {"refresh": refresh, "cleanup": cleanup, "set_mode": set_mode}


def _build_header(parent, launcher, state) -> tk.Frame:
    h = tk.Frame(parent, bg=BG)
    brand = tk.Frame(h, bg=BG)
    brand.pack(side="left", padx=(0, 12))
    logo = tk.Canvas(brand, width=18, height=18, bg=BG, highlightthickness=0)
    logo.pack(side="left", padx=(0, 6))
    try:
        logo.after(10, lambda: launcher._draw_aurum_logo(logo, 9, 9, scale=5, tag="engines-live"))
    except Exception:
        pass
    tk.Label(brand, text="AURUM", font=(FONT, 8, "bold"),
             fg=WHITE, bg=BG).pack(side="left", padx=(0, 10))
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
    state["desk_lbl"] = tk.Label(right, text="", font=(FONT, 6, "bold"),
                                 fg=DIM2, bg=BG)
    state["desk_lbl"].pack(side="right", padx=(8, 0))
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
    desk_lbl = state.get("desk_lbl")
    if desk_lbl is not None:
        desk_lbl.configure(text=f"DESK {state['mode'].upper()}")
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
        hints += ["◄► fleet", "S stop", "L log"]
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

    state["live_running_slugs"] = [slug for slug, _meta, _proc in live_items]
    state["ordered_items"] = (
        [(slug, "LIVE") for slug, _meta, _proc in live_items] +
        [(slug, "READY") for slug, _meta in ready_items] +
        [(slug, "RESEARCH") for slug, _meta in research_items]
    )

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


def _move_selection(state, delta):
    ordered = state.get("ordered_items") or []
    if not ordered:
        return
    current = (state.get("selected_slug"), state.get("selected_bucket"))
    try:
        idx = ordered.index(current)
    except ValueError:
        idx = 0
    slug, bucket = ordered[(idx + delta) % len(ordered)]
    _select_slug(state, slug, bucket)


def _move_live_selection(state, delta):
    running = state.get("live_running_slugs") or []
    if state.get("selected_bucket") != "LIVE" or not running:
        return
    slug = state.get("selected_slug")
    try:
        idx = running.index(slug)
    except ValueError:
        idx = 0
    _select_slug(state, running[(idx + delta) % len(running)], "LIVE")


def _activate_selection(state, launcher):
    slug = state.get("selected_slug")
    bucket = state.get("selected_bucket")
    if not slug or not bucket:
        return
    from config.engines import ENGINES
    meta = ENGINES.get(slug, {})
    if bucket == "READY":
        _run_engine(launcher, slug, meta, state)
    elif bucket == "RESEARCH":
        _go_to_backtest(launcher, slug)


def _selected_proc(state):
    if state.get("selected_bucket") != "LIVE":
        return None
    try:
        from core.proc import list_procs
        running = running_slugs_from_procs(list_procs())
    except Exception:
        return None
    return running.get(state.get("selected_slug"))


def _open_selected_log(state, launcher):
    proc = _selected_proc(state)
    if proc:
        _open_full_log(launcher, proc)


def _stop_selected_live(state, launcher):
    proc = _selected_proc(state)
    if proc:
        _stop_engine(launcher, state, proc)


def _open_selected_backtest(state, launcher):
    if state.get("selected_bucket") == "RESEARCH":
        _go_to_backtest(launcher, state.get("selected_slug"))


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


_LEVERAGE_OPTS = [("1x", "1.0"), ("2x", "2.0"), ("3x", "3.0"), ("5x", "5.0")]


def _latest_run_dir(slug: str) -> Path | None:
    root = Path(__file__).resolve().parent.parent / "data"
    eng_dir = root / _ENGINE_DIR_MAP.get(slug, slug)
    if not eng_dir.is_dir():
        return None
    try:
        runs = sorted([d for d in eng_dir.iterdir() if d.is_dir()],
                      key=lambda d: d.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return runs[0] if runs else None


def _load_positions_for_slug(slug: str) -> list[dict]:
    run_dir = _latest_run_dir(slug)
    if run_dir is None:
        return []
    path = run_dir / "state" / "positions.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [{"symbol": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in data.items()]
    return []


def _resolve_log_path(slug: str, proc: dict) -> Path | None:
    for key in ("log", "log_path", "log_file"):
        val = proc.get(key)
        if val:
            p = Path(val)
            if p.exists():
                return p
    run_dir = _latest_run_dir(slug)
    if run_dir is None:
        return None
    for cand in (run_dir / "logs" / "live.log", run_dir / "logs" / "engine.log", run_dir / "log.txt"):
        if cand.is_file():
            return cand
    return None


def _read_log_tail(path: Path | None, n: int = 18) -> list[str]:
    if path is None:
        return []
    try:
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    except OSError:
        return []


def _runtime_snapshot(slug: str, proc: dict) -> dict:
    positions = _load_positions_for_slug(slug)
    log_path = _resolve_log_path(slug, proc)
    tail = _read_log_tail(log_path)
    pnl = proc.get("pnl")
    if pnl is None:
        vals = [_safe_float(p.get("pnl", p.get("unrealized_pnl"))) for p in positions]
        vals = [v for v in vals if v is not None]
        pnl = sum(vals) if vals else None
    return {
        "positions": positions,
        "positions_count": len(positions),
        "log_path": log_path,
        "tail": tail,
        "pnl": pnl,
        "last_signal": proc.get("last_signal") or (tail[-1] if tail else "-"),
    }


def _pnl_color(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return WHITE
    return GREEN if f > 0 else RED if f < 0 else WHITE


def _desk_metric(parent, label, value, color):
    box = tk.Frame(parent, bg=BG3, highlightbackground=BORDER, highlightthickness=1)
    box.pack(side="left", fill="x", expand=True, padx=(0, 4))
    tk.Label(box, text=label, fg=DIM, bg=BG3, font=(FONT, 6, "bold")).pack(anchor="w", padx=8, pady=(5, 1))
    tk.Label(box, text=str(value), fg=color, bg=BG3, font=(FONT, 8, "bold")).pack(anchor="w", padx=8, pady=(0, 5))


def _mode_bank_snapshot(launcher) -> dict[str, dict]:
    snap: dict[str, dict] = {}
    try:
        from core.portfolio_monitor import PortfolioMonitor
        paper = PortfolioMonitor.paper_state_load()
        snap["paper"] = {
            "status": "editable",
            "detail": f"${float(paper.get('current_balance', 0) or 0):,.2f}",
        }
    except Exception:
        snap["paper"] = {"status": "editable", "detail": "N/A"}

    pm = None
    try:
        getter = getattr(launcher, "_get_portfolio_monitor", None)
        if callable(getter):
            pm = getter()
    except Exception:
        pm = None

    for mode in ("demo", "testnet", "live"):
        has_keys = False
        try:
            if pm is not None:
                has_keys = bool(pm.has_keys(mode))
        except Exception:
            has_keys = False
        snap[mode] = {
            "status": "keys" if has_keys else "offline",
            "detail": "BINANCE" if has_keys else "NO KEYS",
        }
    return snap


def _open_paper_editor(launcher):
    fn = getattr(launcher, "_dash_paper_edit_dialog", None)
    if callable(fn):
        fn()


def _render_mode_bank(parent, launcher, active_mode: str, *, allow_paper_edit: bool = False):
    snap = _mode_bank_snapshot(launcher)
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    box.pack(fill="x", padx=12, pady=(0, 8))
    head = tk.Frame(box, bg=BG2)
    head.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(head, text="ENVIRONMENT BANK", fg=AMBER_D, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(head, text="PAPER / DEMO / TESTNET / LIVE", fg=DIM2, bg=BG2,
             font=(FONT, 6)).pack(side="right")
    row = tk.Frame(box, bg=BG2)
    row.pack(fill="x", padx=8, pady=(0, 8))
    for mode in _MODE_ORDER:
        item = snap.get(mode, {})
        active = mode == active_mode
        color = _MODE_COLORS[mode]
        status = str(item.get("status", "-")).upper()
        detail = str(item.get("detail", "-"))
        card = tk.Frame(row, bg=(PANEL if active else BG3),
                        highlightbackground=(color if active else BORDER),
                        highlightthickness=1)
        card.pack(side="left", fill="x", expand=True, padx=(0, 4))
        tk.Label(card, text=mode.upper(), fg=(color if active else DIM2),
                 bg=card["bg"], font=(FONT, 7, "bold")).pack(anchor="w", padx=8, pady=(6, 1))
        tk.Label(card, text=detail, fg=WHITE, bg=card["bg"],
                 font=(FONT, 8, "bold")).pack(anchor="w", padx=8)
        tk.Label(card, text=status, fg=DIM, bg=card["bg"],
                 font=(FONT, 6, "bold")).pack(anchor="w", padx=8, pady=(1, 6))

    if allow_paper_edit and active_mode == "paper":
        actions = tk.Frame(box, bg=BG2)
        actions.pack(fill="x", padx=10, pady=(0, 8))
        _action_btn(actions, "EDIT PAPER BALANCE", AMBER_B, lambda: _open_paper_editor(launcher))


def _render_live_book(parent, state, running):
    if not running:
        return
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    box.pack(fill="x", padx=12, pady=(12, 0))
    head = tk.Frame(box, bg=BG2)
    head.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(head, text="LIVE FLEET", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(head, text=f"{len(running)} ACTIVE", fg=DIM2, bg=BG2,
             font=(FONT, 6, "bold")).pack(side="right")
    tk.Label(box, text="LEFT / RIGHT SWITCH THE ACTIVE ENGINE ON DESK",
             fg=DIM2, bg=BG2, font=(FONT, 6)).pack(anchor="w", padx=10, pady=(0, 4))
    grid = tk.Frame(box, bg=BG2)
    grid.pack(fill="x", padx=8, pady=(0, 8))
    cols = 3
    for idx, (slug, proc) in enumerate(running.items()):
        snap = _runtime_snapshot(slug, proc)
        active = state.get("selected_slug") == slug
        card = tk.Frame(grid, bg=(PANEL if active else BG3),
                        highlightbackground=(AMBER_B if active else BORDER),
                        highlightthickness=1, cursor="hand2")
        card.grid(row=idx // cols, column=idx % cols, sticky="ew", padx=3, pady=3)
        grid.grid_columnconfigure(idx % cols, weight=1)
        inner = tk.Frame(card, bg=card["bg"])
        inner.pack(fill="both", expand=True, padx=8, pady=6)
        tk.Label(inner, text=slug.upper(), fg=WHITE, bg=card["bg"], font=(FONT, 8, "bold")).pack(anchor="w")
        tk.Label(inner, text=f"{str(proc.get('engine_mode') or proc.get('mode') or 'paper').upper()}  ·  {format_uptime(seconds=_uptime_seconds(proc))}",
                 fg=DIM2, bg=card["bg"], font=(FONT, 6)).pack(anchor="w", pady=(1, 0))
        tk.Label(inner, text=f"{snap['positions_count']} OPEN  ·  {_fmt_pnl(snap['pnl'])}",
                 fg=_pnl_color(snap["pnl"]), bg=card["bg"], font=(FONT, 7, "bold")).pack(anchor="w", pady=(3, 0))
        for w in (card, inner) + tuple(inner.winfo_children()):
            w.bind("<Button-1>", lambda _e, s=slug: _select_slug(state, s, "LIVE"))


def _render_positions_panel(parent, column, positions):
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    box.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0))
    tk.Label(box, text="POSITIONS", fg=AMBER_D, bg=BG2, font=(FONT, 7, "bold")).pack(anchor="w", padx=10, pady=(8, 4))
    if not positions:
        tk.Label(box, text="NO OPEN BOOK", fg=DIM, bg=BG2, font=(FONT, 8)).pack(anchor="w", padx=10, pady=(0, 8))
        return
    hdr = tk.Frame(box, bg=BG3)
    hdr.pack(fill="x", padx=10)
    for text, width in (("SYMBOL", 9), ("SIDE", 7), ("ENTRY", 10), ("P/L", 10)):
        tk.Label(hdr, text=text, fg=DIM, bg=BG3, font=(FONT, 6, "bold"),
                 width=width, anchor="w", padx=3, pady=4).pack(side="left")
    body = tk.Frame(box, bg=BG2)
    body.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    for p in positions[:7]:
        row = tk.Frame(body, bg=BG2)
        row.pack(fill="x")
        side = str(p.get("side", p.get("direction", "?"))).upper()
        for txt, width, color in (
            (str(p.get("symbol", "?")), 9, WHITE),
            (side, 7, GREEN if side == "LONG" else RED if side == "SHORT" else WHITE),
            (str(p.get("entry", p.get("entry_price", "-"))), 10, AMBER_B),
            (_fmt_pnl(p.get("pnl", p.get("unrealized_pnl"))), 10, _pnl_color(p.get("pnl", p.get("unrealized_pnl")))),
        ):
            tk.Label(row, text=txt, fg=color, bg=BG2, font=(FONT, 8),
                     width=width, anchor="w", padx=3, pady=2).pack(side="left")


def _render_log_panel(parent, column, state, launcher, proc, snap):
    box = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    box.grid(row=0, column=column, sticky="nsew", padx=(0, 4) if column == 0 else (4, 0))
    head = tk.Frame(box, bg=BG2)
    head.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(head, text="LOG", fg=AMBER_D, bg=BG2, font=(FONT, 7, "bold")).pack(side="left")
    if snap["log_path"] is not None:
        tk.Label(head, text=snap["log_path"].name, fg=DIM2, bg=BG2,
                 font=(FONT, 6)).pack(side="left", padx=(8, 0))
    _action_btn(head, "OPEN FULL", DIM, lambda: _open_full_log(launcher, proc))
    log_box = tk.Text(box, height=16, bg=BG, fg=WHITE, font=(FONT, 8),
                      wrap="none", highlightbackground=BORDER, highlightthickness=0,
                      state="disabled")
    log_box.pack(fill="both", expand=True, padx=10, pady=(0, 8))
    state["log_box"] = log_box
    _schedule_log_tail(state, launcher, proc)


def _render_detail_ready(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")
    mode = state["mode"]
    run_color = _MODE_COLORS[mode]

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=" DEPLOY READY ", fg=BG, bg=GREEN,
             font=(FONT, 7, "bold"), padx=6, pady=2).pack(side="right")

    if desc:
        tk.Label(parent, text=desc.upper(), fg=DIM2, bg=PANEL,
                 font=(FONT, 7), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=12, pady=(0, 6))

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    deck = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    deck.pack(fill="x", padx=12, pady=(10, 8))
    top = tk.Frame(deck, bg=BG2)
    top.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(top, text="DEPLOY DECK", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(top, text=f"NEXT {mode.upper()}", fg=run_color, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="right")
    facts = tk.Frame(deck, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 8))
    _desk_metric(facts, "RUNNER", "VALIDATED", GREEN)
    _desk_metric(facts, "ROLE", "LAB", WHITE)
    _desk_metric(facts, "STACK", "LIVE", AMBER_B)
    _desk_metric(facts, "RISK", mode.upper(), run_color)

    run = tk.Label(parent, text=f"  DEPLOY IN {mode.upper()}  ",
                   fg=BG, bg=run_color, font=(FONT, 11, "bold"),
                   cursor="hand2", padx=8, pady=10)
    run.pack(fill="x", padx=12, pady=(0, 8))
    run.bind("<Button-1>", lambda _e: _run_engine(launcher, slug, meta, state))

    _render_mode_bank(parent, launcher, mode, allow_paper_edit=True)

    cfg_store = state.setdefault("config", {})
    cfg = cfg_store.setdefault(slug, {"leverage": "2.0"})
    cfg_frame = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    cfg_frame.pack(fill="x", padx=12, pady=(0, 8))
    top_cfg = tk.Frame(cfg_frame, bg=BG2)
    top_cfg.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(top_cfg, text="EXECUTION PROFILE", fg=AMBER_D, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(top_cfg, text="ROUTE AUTO", fg=DIM2, bg=BG2,
             font=(FONT, 6, "bold")).pack(side="right")
    facts = tk.Frame(cfg_frame, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 6))
    _desk_metric(facts, "ACCOUNT", mode.upper(), run_color)
    _desk_metric(facts, "ROUTING", "UNIFIED", WHITE)
    _desk_metric(facts, "RISK", "DESK LIMITS", WHITE)
    lev = tk.Frame(cfg_frame, bg=BG2)
    lev.pack(fill="x", padx=10, pady=(0, 8))
    tk.Label(lev, text="LEVERAGE", fg=DIM, bg=BG2,
             font=(FONT, 7)).pack(side="left", padx=(0, 8))
    for disp, val in _LEVERAGE_OPTS:
        active = cfg.get("leverage") == val
        pill = tk.Label(lev, text=f" {disp} ",
                        fg=(BG if active else DIM2),
                        bg=(AMBER if active else BG3),
                        font=(FONT, 7, "bold"),
                        cursor="hand2", padx=4, pady=1)
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _v=val, _d=cfg, _s=state: _set_cfg(_d, "leverage", _v, _s))

    mandate = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    mandate.pack(fill="x", padx=12, pady=(0, 10))
    tk.Label(mandate, text="MANDATE", fg=AMBER_D, bg=BG2,
             font=(FONT, 7, "bold")).pack(anchor="w", padx=10, pady=(8, 2))
    tk.Label(mandate, text="RESEARCH -> EXECUTION\nSIGNAL -> RISK GATE -> MARKET",
             fg=DIM2, bg=BG2, font=(FONT, 8), anchor="w", justify="left").pack(fill="x", padx=10, pady=(0, 8))

    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(0, 12))
    _action_btn(actions, "VIEW CODE", DIM, lambda: _view_code(launcher, meta.get("script", "")))
    _action_btn(actions, "PAST RUNS", DIM, lambda: _past_runs(launcher, slug))


def _set_cfg(cfg_dict, key, val, state):
    cfg_dict[key] = val
    refresh = state.get("refresh")
    if callable(refresh):
        refresh()


def _run_engine(launcher, slug, meta, state):
    mode = state["mode"]
    raw_cfg = (state.get("config") or {}).get(slug) or {}
    cfg = {"leverage": raw_cfg.get("leverage", "2.0")}
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
    top = tk.Toplevel()
    top.title("LIVE EXECUTION")
    top.configure(bg=BG)
    top.geometry("420x240")
    top.resizable(False, False)
    top.transient()
    top.grab_set()

    tk.Label(top, text=f"LIVE EXECUTION — {engine_name}",
             fg=RED, bg=BG, font=(FONT, 10, "bold")).pack(pady=(14, 4))
    tk.Label(top, text=(f"Você está prestes a ligar {engine_name} em modo LIVE.\n"
                        "REAL MONEY. REAL ORDERS."),
             fg=WHITE, bg=BG, font=(FONT, 8), justify="center").pack(pady=(0, 10))
    tk.Label(top, text=f"DIGITE {engine_name} PRA CONFIRMAR:",
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
            confirm.bind("<Button-1>", lambda _e: (top.destroy(), on_confirm()))
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
    name = meta.get("display", slug.upper())
    try:
        from core.proc import list_procs
        procs = list_procs()
    except Exception:
        procs = []
    running = running_slugs_from_procs(procs)
    proc = running.get(slug, {})
    snap = _runtime_snapshot(slug, proc)
    mode_key = (proc.get("engine_mode") or proc.get("mode") or "paper").lower()
    mode_color = _MODE_COLORS.get(mode_key, CYAN)
    fleet = state.get("live_running_slugs") or []
    fleet_pos = (fleet.index(slug) + 1) if slug in fleet else 1

    _render_live_book(parent, state, running)

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    right = tk.Frame(head, bg=PANEL)
    right.pack(side="right")
    tk.Label(right, text=f"{fleet_pos}/{max(len(fleet), 1)}", fg=DIM2, bg=PANEL,
             font=(FONT, 7, "bold")).pack(side="left", padx=(0, 8))
    tk.Label(right, text="●", fg=GREEN, bg=PANEL,
             font=(FONT, 9, "bold")).pack(side="left")
    tk.Label(right, text=f" {mode_key.upper()} ",
             fg=BG, bg=mode_color, font=(FONT, 7, "bold"),
             padx=4, pady=1).pack(side="left", padx=(4, 0))
    started = proc.get("started")
    if started:
        try:
            from datetime import datetime as _dt
            secs = (_dt.now() - _dt.fromisoformat(started)).total_seconds()
            tk.Label(right, text=f" · {format_uptime(seconds=secs)}",
                     fg=DIM, bg=PANEL, font=(FONT, 8)).pack(side="left")
        except Exception:
            pass

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(4, 0))

    kpis = tk.Frame(parent, bg=PANEL)
    kpis.pack(fill="x", padx=12, pady=(8, 6))
    _kpi_col(kpis, "P/L",    _fmt_pnl(snap["pnl"]), _pnl_color(snap["pnl"]))
    _kpi_col(kpis, "OPEN",   str(snap["positions_count"]), WHITE)
    _kpi_col(kpis, "TRADES", str(proc.get("trades") or 0), WHITE)
    _kpi_col(kpis, "PID",    str(proc.get("pid") or "-"), DIM2)
    _kpi_col(kpis, "SIGNAL", str(snap["last_signal"])[:28], WHITE)

    _render_mode_bank(parent, launcher, mode_key, allow_paper_edit=(mode_key == "paper"))

    ops = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    ops.pack(fill="x", padx=12, pady=(0, 8))
    top = tk.Frame(ops, bg=BG2)
    top.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(top, text="OPERATING MAP", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(top, text="LAB -> LIVE", fg=mode_color, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="right")
    facts = tk.Frame(ops, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 6))
    _desk_metric(facts, "MODE", mode_key.upper(), mode_color)
    _desk_metric(facts, "UPTIME", format_uptime(seconds=_uptime_seconds(proc)), WHITE)
    _desk_metric(facts, "DESK", f"{fleet_pos}/{max(len(fleet), 1)}", WHITE)
    _desk_metric(facts, "RISK", f"{snap['positions_count']} BOOKS", WHITE)
    _desk_metric(facts, "FEED", "ATTACHED" if snap["log_path"] else "OFFLINE",
                 GREEN if snap["log_path"] else RED)
    tk.Label(ops, text="BOOK · TELEMETRY · CONTROL", fg=DIM2, bg=BG2,
             font=(FONT, 8)).pack(anchor="w", padx=10, pady=(0, 8))

    lower = tk.Frame(parent, bg=PANEL)
    lower.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    lower.grid_columnconfigure(0, weight=40, uniform="lower")
    lower.grid_columnconfigure(1, weight=60, uniform="lower")
    lower.grid_rowconfigure(0, weight=1)
    _render_positions_panel(lower, 0, snap["positions"])
    _render_log_panel(lower, 1, state, launcher, proc, snap)

    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(0, 12))
    stop_btn = tk.Label(actions, text="  STOP ENGINE  ",
                        fg=WHITE, bg=RED,
                        font=(FONT, 10, "bold"),
                        cursor="hand2", padx=12, pady=8)
    stop_btn.pack(side="left", padx=(0, 8))
    _bind_hold_to_confirm(stop_btn,
                          on_confirm=lambda: _stop_engine(launcher, state, proc),
                          duration_ms=1500)
    _action_btn(actions, "OPEN LOG", DIM,
                lambda: _open_full_log(launcher, proc))
    _action_btn(actions, "REPORTS", DIM,
                lambda: _past_runs(launcher, slug))
    _action_btn(actions, "VIEW CODE", DIM,
                lambda: _view_code(launcher, meta.get("script", "")))


def _kpi_col(parent, label, value, color=WHITE):
    col = tk.Frame(parent, bg=PANEL)
    col.pack(side="left", fill="x", expand=True)
    tk.Label(col, text=label, fg=DIM, bg=PANEL,
             font=(FONT, 6, "bold")).pack(anchor="w")
    tk.Label(col, text=value, fg=color, bg=PANEL,
             font=(FONT, 8, "bold")).pack(anchor="w")


def _fmt_pnl(v):
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)[:10]
    return f"{'+' if f >= 0 else ''}${f:,.2f}"


def _schedule_log_tail(state, launcher, proc):
    box = state.get("log_box")
    if not box or not proc:
        return
    slug = state.get("selected_slug")
    if not slug:
        return
    lines = _read_log_tail(_resolve_log_path(slug, proc), n=18)
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("end", "\n".join(lines) if lines else "(no log available)")
    box.configure(state="disabled")
    box.see("end")
    try:
        aid = launcher.after(1000,
                             lambda: _schedule_log_tail(state, launcher, proc))
        state["after_handles"].append(aid)
    except Exception:
        pass


def _open_full_log(launcher, proc):
    log_path = proc.get("log") or proc.get("log_path") or proc.get("log_file")
    if not log_path:
        return
    try:
        os.startfile(log_path)
    except Exception:
        pass


def _bind_hold_to_confirm(widget, *, on_confirm, duration_ms):
    tok = {"aid": None}

    def _down(_e=None):
        tok["aid"] = widget.after(duration_ms, _fire)

    def _up(_e=None):
        if tok["aid"]:
            try:
                widget.after_cancel(tok["aid"])
            except Exception:
                pass
            tok["aid"] = None

    def _fire():
        tok["aid"] = None
        on_confirm()

    widget.bind("<ButtonPress-1>", _down)
    widget.bind("<ButtonRelease-1>", _up)
    widget.bind("<Leave>", _up)


def _stop_engine(launcher, state, proc):
    try:
        from core.proc import stop_proc
        stop_proc(int(proc["pid"]), expected=proc)
    except Exception:
        return
    refresh = state.get("refresh")
    if callable(refresh):
        refresh()
