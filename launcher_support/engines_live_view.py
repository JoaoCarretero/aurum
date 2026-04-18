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
import time
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
_STAGE_STYLE: dict[str, tuple[str, str]] = {
    "validated": ("VALIDATED", GREEN),
    "bootstrap_staging": ("BOOTSTRAP", AMBER),
    "research": ("RESEARCH", DIM2),
    "experimental": ("EXPERIMENTAL", RED),
    "quarantined": ("QUARANTINED", HAZARD),
}
_PROCS_CACHE: dict[str, object] = {"ts": 0.0, "rows": []}


def _stage_badge(meta: dict | None) -> tuple[str, str]:
    key = str((meta or {}).get("stage") or "research").strip().lower()
    if key in _STAGE_STYLE:
        return _STAGE_STYLE[key]
    return (key.upper() or "RESEARCH", DIM2)


def footer_hints(*, selected_bucket: Bucket | None, mode: str) -> tuple[str, str]:
    hints = ["ESC main", "UP/DOWN list"]
    if selected_bucket == "LIVE":
        hints += ["LEFT/RIGHT fleet", "ENTER monitor", "S stop", "L log"]
    elif selected_bucket == "READY":
        hints += ["ENTER launch", "M change desk"]
    elif selected_bucket == "RESEARCH":
        hints += ["B backtest", "ENTER backtest"]
    else:
        hints += ["ENTER select"]
    hints += ["M cycle mode"]
    warn = "LIVE MODE - real orders enabled" if mode == "live" else ""
    return ("  ·  ".join(hints), warn)


def cockpit_summary(*, mode: str, live_count: int, ready_count: int, research_count: int) -> list[tuple[str, str, str]]:
    return [
        ("RUNNING", str(live_count), GREEN if live_count else DIM2),
        ("READY", str(ready_count), AMBER_B if ready_count else DIM2),
        ("RESEARCH", str(research_count), WHITE if research_count else DIM2),
        ("DESK", mode.upper(), _MODE_COLORS.get(mode, CYAN)),
    ]


def bucket_title(bucket: Bucket) -> str:
    return {
        "LIVE": "RUNNING NOW",
        "READY": "READY TO LAUNCH",
        "RESEARCH": "RESEARCH ONLY",
    }[bucket]


def bucket_header_title(title: str) -> str:
    if title == "LIVE":
        return "RUNNING NOW"
    if title == "READY LIVE":
        return "READY TO LAUNCH"
    if title == "EXPERIMENTAL":
        return "EXPERIMENTAL"
    return "RESEARCH ONLY"


def row_action_label(bucket: Bucket, meta: dict | None) -> tuple[str, str]:
    if bucket == "LIVE":
        return ("MONITOR", GREEN)
    if bucket == "READY":
        if bool((meta or {}).get("live_bootstrap")) and not bool((meta or {}).get("live_ready")):
            return ("BOOTSTRAP", AMBER)
        return ("LAUNCH", GREEN)
    return ("BACKTEST", DIM2)


def initial_selection(
    *,
    live_items: list[tuple],
    ready_items: list[tuple],
    research_items: list[tuple],
    experimental_items: list[tuple],
) -> tuple[str, Bucket] | None:
    if live_items:
        return str(live_items[0][0]), "LIVE"
    if ready_items:
        return str(ready_items[0][0]), "READY"
    if research_items:
        return str(research_items[0][0]), "RESEARCH"
    if experimental_items:
        return str(experimental_items[0][0]), "RESEARCH"
    return None


def assign_bucket(*, slug: str, is_running: bool, live_ready: bool, live_bootstrap: bool = False) -> Bucket:
    """Decide which bucket an engine belongs to in the cockpit view.

    Rules:
      - A running engine that is also live_ready → LIVE.
      - A non-running live_ready engine → READY.
      - A bootstrap-runnable engine also lands in READY so the cockpit can
        expose its dedicated preflight runner without claiming it is
        validated for production execution.
      - Anything else → RESEARCH.
    """
    if not live_ready and not live_bootstrap:
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


def _list_procs_cached(*, force: bool = False, ttl_s: float = 0.75) -> list[dict]:
    now = time.monotonic()
    cached_rows = _PROCS_CACHE.get("rows")
    cached_ts = float(_PROCS_CACHE.get("ts") or 0.0)
    if not force and cached_rows is not None and (now - cached_ts) <= ttl_s:
        return list(cached_rows)  # type: ignore[arg-type]
    try:
        from core.proc import list_procs
        rows = list_procs()
    except Exception:
        rows = []
    _PROCS_CACHE["ts"] = now
    _PROCS_CACHE["rows"] = list(rows)
    return rows


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
        # Cancel any pending shadow-panel refresh so it doesn't fire after
        # the user has left the cockpit screen.
        aid = state.pop("shadow_after_id", None)
        if aid is not None:
            try:
                launcher.after_cancel(aid)
            except Exception:
                pass

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
    top = tk.Frame(h, bg=BG)
    top.pack(fill="x")
    brand = tk.Frame(top, bg=BG)
    brand.pack(side="left", padx=(0, 12))
    logo = tk.Canvas(brand, width=18, height=18, bg=BG, highlightthickness=0)
    logo.pack(side="left", padx=(0, 6))
    try:
        logo.after(10, lambda: launcher._draw_aurum_logo(logo, 9, 9, scale=5, tag="engines-live"))
    except Exception:
        pass
    tk.Label(brand, text="AURUM", font=(FONT, 8, "bold"),
             fg=WHITE, bg=BG).pack(side="left", padx=(0, 10))
    tk.Frame(top, bg=AMBER, width=3, height=22).pack(side="left", padx=(0, 8))
    tk.Label(top, text="LIVE COCKPIT", font=(FONT, 12, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 14))

    pill_row = tk.Frame(top, bg=BG)
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

    right = tk.Frame(top, bg=BG)
    right.pack(side="right")
    state["desk_lbl"] = tk.Label(right, text="", font=(FONT, 6, "bold"),
                                 fg=DIM2, bg=BG)
    state["desk_lbl"].pack(side="right", padx=(8, 0))
    state["counts_lbl"] = tk.Label(right, text="", font=(FONT, 7, "bold"),
                                    fg=DIM, bg=BG)
    state["counts_lbl"].pack(side="right", padx=(8, 0))
    state["summary_row"] = tk.Frame(h, bg=BG)
    state["summary_row"].pack(fill="x", pady=(8, 0))

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
    hints, warn = footer_hints(
        selected_bucket=state.get("selected_bucket"),
        mode=state["mode"],
    )
    state["footer_lbl"].configure(text=hints)
    state["footer_warn_lbl"].configure(text=warn)


def _render_master_list(state, launcher):
    """Mount the 3-bucket master list on state['master_host']."""
    host = state["master_host"]
    for w in host.winfo_children():
        w.destroy()

    from config.engines import (
        ENGINES, LIVE_BOOTSTRAP_SLUGS, LIVE_READY_SLUGS, EXPERIMENTAL_SLUGS,
    )
    procs = _list_procs_cached()
    running = running_slugs_from_procs(procs)

    live_items: list[tuple[str, dict, dict]] = []
    ready_items: list[tuple[str, dict]] = []
    research_items: list[tuple[str, dict]] = []
    experimental_items: list[tuple[str, dict]] = []
    for slug, meta in ENGINES.items():
        live_ready = slug in LIVE_READY_SLUGS
        live_bootstrap = slug in LIVE_BOOTSTRAP_SLUGS
        bucket = assign_bucket(
            slug=slug,
            is_running=slug in running,
            live_ready=live_ready,
            live_bootstrap=live_bootstrap,
        )
        if bucket == "LIVE":
            live_items.append((slug, meta, running[slug]))
        elif bucket == "READY":
            ready_items.append((slug, meta))
        elif slug in EXPERIMENTAL_SLUGS:
            # Split RESEARCH into a dedicated EXPERIMENTAL cluster so
            # quarantined / no-edge engines don't get mixed with honest
            # research candidates.
            experimental_items.append((slug, meta))
        else:
            research_items.append((slug, meta))

    state["live_running_slugs"] = [slug for slug, _meta, _proc in live_items]
    state["ordered_items"] = (
        [(slug, "LIVE") for slug, _meta, _proc in live_items] +
        [(slug, "READY") for slug, _meta in ready_items] +
        [(slug, "RESEARCH") for slug, _meta in research_items] +
        [(slug, "RESEARCH") for slug, _meta in experimental_items]
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

    # Default selection: first LIVE, else first READY, else first RESEARCH,
    # falling back to the EXPERIMENTAL cluster when it is the only content.
    if state.get("selected_slug") is None:
        selected = initial_selection(
            live_items=live_items,
            ready_items=ready_items,
            research_items=research_items,
            experimental_items=experimental_items,
        )
        if selected is not None:
            state["selected_slug"], state["selected_bucket"] = selected

    _render_bucket(inner, "LIVE", live_items, state)
    _render_bucket(inner, "READY LIVE", ready_items, state)
    _render_bucket(inner, "RESEARCH", research_items, state)
    _render_bucket(inner, "EXPERIMENTAL", experimental_items, state)

    _render_summary_row(
        state,
        live_count=len(live_items),
        ready_count=len(ready_items),
        research_count=len(research_items) + len(experimental_items),
    )

    total = (len(live_items) + len(ready_items)
             + len(research_items) + len(experimental_items))
    state["counts_lbl"].configure(
        text=f"{total} engines  ·  {len(live_items)} running")


def _render_summary_row(state, *, live_count: int, ready_count: int, research_count: int):
    host = state.get("summary_row")
    if host is None:
        return
    for w in host.winfo_children():
        w.destroy()
    for label, value, color in cockpit_summary(
        mode=state["mode"],
        live_count=live_count,
        ready_count=ready_count,
        research_count=research_count,
    ):
        card = tk.Frame(host, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        card.pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Label(card, text=label, fg=DIM2, bg=BG2,
                 font=(FONT, 6, "bold")).pack(anchor="w", padx=8, pady=(6, 1))
        tk.Label(card, text=value, fg=color, bg=BG2,
                 font=(FONT, 9, "bold")).pack(anchor="w", padx=8, pady=(0, 6))


def _render_bucket(parent, title, items, state):
    if not items:
        return
    bucket = "LIVE" if title == "LIVE" else "RESEARCH" if title in ("RESEARCH", "EXPERIMENTAL") else "READY"
    header = tk.Frame(parent, bg=BG)
    header.pack(fill="x", pady=(8, 2))
    tk.Frame(header, bg=AMBER, width=3, height=14).pack(side="left", padx=(0, 6))
    tk.Label(header, text=bucket_header_title(title), font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left")
    tk.Label(header, text=f"  · {len(items)}", font=(FONT, 7),
             fg=DIM, bg=BG).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))

    is_live_bucket = title == "LIVE"
    # RESEARCH + EXPERIMENTAL share the locked-style row renderer —
    # EXPERIMENTAL is a visual sub-cluster for quarantined engines.
    is_research_like = title in ("RESEARCH", "EXPERIMENTAL")
    for tup in items:
        if is_live_bucket:
            slug, meta, proc = tup
            _render_row_live(parent, slug, meta, proc, state)
        elif is_research_like:
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
    running = running_slugs_from_procs(_list_procs_cached())
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
    stage_label, stage_color = _stage_badge(meta)
    action_label, action_color = row_action_label("LIVE", meta)
    tk.Label(row, text="●", fg=GREEN, bg=bg,
             font=(FONT, 9, "bold"), padx=4).pack(side="left")
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=WHITE, bg=bg, font=(FONT, 9, "bold")).pack(side="left")
    tk.Label(row, text=f" {stage_label} ",
             fg=BG, bg=stage_color, font=(FONT, 6, "bold"),
             padx=4, pady=1).pack(side="left", padx=(6, 0))
    tk.Label(row, text=action_label,
             fg=action_color, bg=bg, font=(FONT, 6, "bold")
             ).pack(side="right", padx=(0, 8))
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
    stage_label, stage_color = _stage_badge(meta)
    action_label, action_color = row_action_label("READY", meta)
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=WHITE, bg=bg, font=(FONT, 9, "bold"),
             padx=8).pack(side="left")
    tk.Label(row, text=f" {stage_label} ",
             fg=BG, bg=stage_color, font=(FONT, 6, "bold"),
             padx=4, pady=1).pack(side="left", padx=(0, 6))
    tk.Label(row, text=action_label,
             fg=action_color, bg=bg, font=(FONT, 6, "bold")
             ).pack(side="right", padx=(0, 8))
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
    stage_label, stage_color = _stage_badge(meta)
    tk.Label(row, text="🔒", fg=DIM, bg=bg,
             font=(FONT, 8), padx=4).pack(side="left")
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=DIM, bg=bg, font=(FONT, 9)).pack(side="left")
    tk.Label(row, text=f" {stage_label} ",
             fg=BG, bg=stage_color, font=(FONT, 6, "bold"),
             padx=4, pady=1).pack(side="left", padx=(6, 0))
    sub = _subtitle_for(slug, meta)
    if sub:
        tk.Label(row, text=sub, fg=DIM2, bg=bg,
                 font=(FONT, 7)).pack(side="left", padx=(4, 0))
    for w in (row,) + tuple(row.winfo_children()):
        w.bind("<Button-1>", lambda _e, _s=slug: _select_slug(state, _s, "RESEARCH"))


def _subtitle_for(slug, meta) -> str:
    """Tagline fallback — extended later to read DB / BRIEFINGS."""
    desc = meta.get("desc") or ""
    return desc[:32]


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
    stage_label, stage_color = _stage_badge(meta)

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=f" {stage_label} ",
             fg=BG, bg=stage_color, font=(FONT, 7, "bold"),
             padx=6, pady=2).pack(side="right", padx=(0, 6))
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


_COCKPIT_CLIENT_SINGLETON: object | None = None


def _get_cockpit_client():
    """Lazy singleton. Returns None se config ausente ou invalida.

    Config vem de config/keys.json bloco 'cockpit_api'. Uma vez resolvido
    (positivo ou negativo), cacheia o resultado pra nao retry em cada
    refresh do painel. Launcher vivo dura horas — tentar reabrir o
    arquivo a cada 5s nao ajuda.
    """
    global _COCKPIT_CLIENT_SINGLETON
    if _COCKPIT_CLIENT_SINGLETON is not None:
        return _COCKPIT_CLIENT_SINGLETON or None
    keys_path = Path("config/keys.json")
    if not keys_path.exists():
        _COCKPIT_CLIENT_SINGLETON = False
        return None
    try:
        data = json.loads(keys_path.read_text(encoding="utf-8"))
        block = data.get("cockpit_api")
        if not block or not block.get("base_url") or not block.get("read_token"):
            _COCKPIT_CLIENT_SINGLETON = False
            return None
        from launcher_support.cockpit_client import CockpitClient, CockpitConfig
        cfg = CockpitConfig(
            base_url=block["base_url"],
            read_token=block["read_token"],
            admin_token=block.get("admin_token"),
            timeout_sec=float(block.get("timeout_sec", 5.0)),
        )
        _COCKPIT_CLIENT_SINGLETON = CockpitClient(
            cfg, cache_dir=Path("data/.cockpit_cache"))
        return _COCKPIT_CLIENT_SINGLETON
    except Exception:
        _COCKPIT_CLIENT_SINGLETON = False
        return None


def _is_remote_run(run_dir: Path) -> bool:
    # Path() on Windows normaliza "remote://x" pra "remote:\x" ou "remote:/x".
    # Aceita as três formas pra robustez cross-platform.
    s = str(run_dir).replace("\\", "/")
    return s.startswith("remote:/") or s.startswith("remote://")


def _remote_run_id(run_dir: Path) -> str:
    s = str(run_dir).replace("\\", "/")
    if s.startswith("remote://"):
        return s[len("remote://"):]
    if s.startswith("remote:/"):
        return s[len("remote:/"):]
    return s


def _get_tunnel_status_label() -> tuple[str, str]:
    """Return (text, fg_color) pro badge TUNNEL na linha de status.

    Reads from launcher (lazy import to avoid circular dep). Returns
    ("—", DIM2) if no TunnelManager is wired.
    """
    try:
        from launcher import get_tunnel_manager
        tm = get_tunnel_manager()
    except Exception:
        tm = None
    if tm is None:
        return ("—", DIM2)
    status = getattr(tm, "status", None)
    if status is None:
        return ("—", DIM2)
    # TunnelStatus.value is a lowercase string: up/reconnecting/...
    val = str(status.value).upper()
    color_map = {
        "UP": GREEN,
        "STARTING": AMBER_B,
        "RECONNECTING": AMBER_B,
        "OFFLINE": RED,
        "STOPPING": DIM2,
        "IDLE": DIM2,
        "DISABLED": DIM2,
    }
    return (val, color_map.get(val, DIM2))


def _find_latest_shadow_run() -> tuple[Path, dict] | None:
    """Return (run_dir, heartbeat_payload) for the most recent shadow run.

    Try cockpit_api client first (remoto via tunnel). Se ausente ou falha,
    cai pro disco local (dev / shadow rodando na mesma máquina).
    """
    # Remote path via cockpit API
    client = _get_cockpit_client()
    if client is not None:
        try:
            run = client.latest_run(engine="millennium")
        except Exception:
            run = None
        if run:
            virtual_dir = Path(f"remote://{run['run_id']}")
            try:
                hb = client.get_heartbeat(run["run_id"])
            except Exception:
                # list_runs worked but heartbeat didn't — keep [REMOTE]
                # badge with whatever the summary carried, instead of
                # silently degrading to a stale LOCAL run.
                hb = {
                    "run_id": run["run_id"],
                    "status": run.get("status", "unknown"),
                    "ticks_ok": 0, "ticks_fail": 0,
                    "novel_total": run.get("novel_total", 0),
                    "last_tick_at": run.get("last_tick_at"),
                    "last_error": "heartbeat fetch failed",
                    "tick_sec": 0,
                }
            return virtual_dir, hb

    # Local disk fallback (layout existente)
    root = Path("data/millennium_shadow")
    if not root.exists():
        return None
    candidates: list[tuple[float, Path, dict]] = []
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        hb = sub / "state" / "heartbeat.json"
        if not hb.exists():
            continue
        try:
            payload = json.loads(hb.read_text(encoding="utf-8"))
            mtime = hb.stat().st_mtime
        except (OSError, json.JSONDecodeError):
            continue
        candidates.append((mtime, sub, payload))
    if not candidates:
        return None
    candidates.sort(key=lambda row: row[0], reverse=True)
    _, run_dir, payload = candidates[0]
    return run_dir, payload


def _drop_shadow_kill(run_dir: Path, launcher, state) -> None:
    """Drop a `.kill` flag so the shadow loop exits after the current tick.

    Remote runs (virtual_dir = 'remote://<run_id>') route via cockpit
    client POST /kill. Local runs write the file directly (previous behavior).
    """
    # Remote path via cockpit API
    if _is_remote_run(run_dir):
        client = _get_cockpit_client()
        if client is None or not getattr(client.cfg, "admin_token", None):
            try:
                launcher.h_stat.configure(
                    text="SHADOW KILL: admin_token ausente em keys.json",
                    fg=RED)
            except Exception:
                pass
            return
        run_id = _remote_run_id(run_dir)
        try:
            client.drop_kill(run_id)
        except Exception as exc:
            try:
                launcher.h_stat.configure(
                    text=f"SHADOW KILL fail: {type(exc).__name__}", fg=RED)
            except Exception:
                pass
            return
        try:
            launcher.h_stat.configure(
                text=f"SHADOW KILL dispatched ({run_id})", fg=AMBER)
        except Exception:
            pass
        refresh = state.get("refresh")
        if callable(refresh):
            try:
                launcher.after(250, refresh)
            except Exception:
                refresh()
        return

    # Local path — preserves original file-write behavior
    kill_path = run_dir / ".kill"
    try:
        kill_path.write_text("killed via cockpit\n", encoding="utf-8")
    except OSError as exc:
        try:
            launcher.h_stat.configure(
                text=f"SHADOW KILL fail: {type(exc).__name__}", fg=RED)
        except Exception:
            pass
        return
    try:
        launcher.h_stat.configure(
            text=f"SHADOW KILL flag dropped ({run_dir.name})", fg=AMBER)
    except Exception:
        pass
    refresh = state.get("refresh")
    if callable(refresh):
        try:
            launcher.after(250, refresh)
        except Exception:
            refresh()


def _render_shadow_panel(parent, launcher, state, slug: str) -> None:
    """Render SHADOW LOOP status card inside the MILLENNIUM detail.

    Reads `data/millennium_shadow/<latest>/state/heartbeat.json` and shows
    ticks_ok / ticks_fail / signals / last tick + STOP CTA when running.
    Only active for the millennium slug — noop otherwise, so other engines
    keep their existing detail layout untouched.

    Auto-refreshes every 5s while a run is active so the cockpit reflects
    tick progress without needing to navigate away and back.
    """
    if slug != "millennium":
        return

    # Cancel any prior shadow auto-refresh timer so a fresh render doesn't
    # leak `after` callbacks every time the user bounces between engines.
    old_aid = state.pop("shadow_after_id", None)
    if old_aid is not None:
        try:
            launcher.after_cancel(old_aid)
        except Exception:
            pass

    result = _find_latest_shadow_run()

    shadow = tk.Frame(parent, bg=BG2,
                      highlightbackground=BORDER_H, highlightthickness=1)
    shadow.pack(fill="x", padx=12, pady=(0, 10))
    # Stash the frame so the scheduled refresh can rebuild only this card.
    state["shadow_panel_frame"] = shadow
    state["shadow_panel_parent"] = parent
    top = tk.Frame(shadow, bg=BG2)
    top.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(top, text="SHADOW LOOP", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")

    if result is None:
        tk.Label(top, text="NONE", fg=DIM2, bg=BG2,
                 font=(FONT, 7, "bold")).pack(side="right")
        tun_text, tun_fg = _get_tunnel_status_label()
        tun_row = tk.Frame(shadow, bg=BG2)
        tun_row.pack(fill="x", padx=10, pady=(2, 4))
        tk.Label(tun_row, text="TUNNEL:", fg=DIM2, bg=BG2,
                 font=(FONT, 7, "bold")).pack(side="left")
        tk.Label(tun_row, text=f" {tun_text}", fg=tun_fg, bg=BG2,
                 font=(FONT, 7, "bold")).pack(side="left")
        tk.Label(
            shadow,
            text=("Nenhum shadow run encontrado.\n"
                  "Rode:  python tools/millennium_shadow.py "
                  "--tick-sec 900 --run-hours 24"),
            fg=DIM2, bg=BG2, font=(FONT, 7), justify="left", anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 8))
        return

    run_dir, hb = result
    status = str(hb.get("status") or "unknown").upper()
    status_color = GREEN if status == "RUNNING" else DIM2
    tk.Label(top, text=f" {status} ", fg=BG, bg=status_color,
             font=(FONT, 7, "bold"), padx=4).pack(side="right")

    facts = tk.Frame(shadow, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 4))
    fail_n = int(hb.get("ticks_fail", 0) or 0)
    _desk_metric(facts, "TICKS OK",
                 str(hb.get("ticks_ok", 0)), GREEN)
    _desk_metric(facts, "FAIL",
                 str(fail_n), RED if fail_n > 0 else DIM2)
    _desk_metric(facts, "SIGNALS",
                 str(hb.get("novel_total", 0)), AMBER_B)
    _desk_metric(facts, "TICK",
                 f"{int(hb.get('tick_sec', 0) or 0)}s", WHITE)

    tun_text, tun_fg = _get_tunnel_status_label()
    tun_row = tk.Frame(shadow, bg=BG2)
    tun_row.pack(fill="x", padx=10, pady=(0, 2))
    tk.Label(tun_row, text="TUNNEL:", fg=DIM2, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(tun_row, text=f" {tun_text}", fg=tun_fg, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")

    last = hb.get("last_tick_at") or hb.get("stopped_at") or "—"
    source = "REMOTE" if _is_remote_run(run_dir) else "LOCAL"
    tk.Label(shadow,
             text=f"[{source}]  RUN {hb.get('run_id','?')}  ·  last {last}",
             fg=DIM, bg=BG2, font=(FONT, 7), anchor="w").pack(
                 fill="x", padx=10, pady=(0, 4))

    if status == "RUNNING":
        stop_row = tk.Frame(shadow, bg=BG2)
        stop_row.pack(fill="x", padx=10, pady=(0, 8))
        kill_btn = tk.Label(stop_row, text=" STOP SHADOW ",
                            fg=BG, bg=RED, font=(FONT, 7, "bold"),
                            cursor="hand2", padx=6, pady=3)
        kill_btn.pack(side="left")
        kill_btn.bind("<Button-1>",
                      lambda _e, _d=run_dir, _s=state:
                          _drop_shadow_kill(_d, launcher, _s))
        # Poll the heartbeat while the loop runs so the cockpit shows
        # live tick progress. Rebuilds only the shadow card, not the
        # whole detail pane, to avoid flicker elsewhere.
        try:
            aid = launcher.after(
                5000,
                lambda: _refresh_shadow_panel(launcher, state),
            )
            state["shadow_after_id"] = aid
        except Exception:
            pass
    else:
        reason = hb.get("stopped_reason") or "—"
        tk.Label(shadow, text=f"stopped: {reason}",
                 fg=DIM2, bg=BG2, font=(FONT, 7), anchor="w").pack(
                     fill="x", padx=10, pady=(0, 8))


def _refresh_shadow_panel(launcher, state) -> None:
    """Rebuild the shadow card in-place from the latest heartbeat.

    Only replaces the shadow frame — other widgets on the detail stay put.
    Silently aborts if the user has navigated away (frame destroyed).
    """
    frame = state.get("shadow_panel_frame")
    parent = state.get("shadow_panel_parent")
    if frame is None or parent is None:
        return
    try:
        if not frame.winfo_exists():
            return
    except Exception:
        return
    # Only refresh while the Millennium detail is still the active selection.
    if state.get("selected_slug") != "millennium":
        return
    try:
        frame.destroy()
    except Exception:
        return
    _render_shadow_panel(parent, launcher, state, "millennium")


def _render_detail_ready(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")
    mode = state["mode"]
    run_color = _MODE_COLORS[mode]
    meta_stage_label, meta_stage_color = _stage_badge(meta)
    is_bootstrap = bool(meta.get("live_bootstrap")) and not bool(meta.get("live_ready"))
    stage_label = " BOOTSTRAP READY " if is_bootstrap else " DEPLOY READY "
    runner_label = "BOOTSTRAP" if is_bootstrap else "VALIDATED"
    role_label = "STAGING" if is_bootstrap else "LAB"
    route_label = "PREFLIGHT" if is_bootstrap else "UNIFIED"
    mandate_text = (
        "BOOTSTRAP -> PREFLIGHT -> ADAPTER BUILD\nNO REAL EXECUTION LOOP YET"
        if is_bootstrap else
        "RESEARCH -> EXECUTION\nSIGNAL -> RISK GATE -> MARKET"
    )
    cta_text = f"  {'BOOTSTRAP' if is_bootstrap else 'DEPLOY'} IN {mode.upper()}  "

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(8, 2))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=f" {meta_stage_label} ", fg=BG, bg=meta_stage_color,
             font=(FONT, 7, "bold"), padx=6, pady=1).pack(side="right", padx=(0, 6))
    tk.Label(head, text=stage_label, fg=BG, bg=GREEN,
             font=(FONT, 7, "bold"), padx=6, pady=1).pack(side="right")

    if desc:
        tk.Label(parent, text=desc.upper(), fg=DIM2, bg=PANEL,
                 font=(FONT, 7), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=12, pady=(0, 4))

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    # EXECUTION DESK — funde DEPLOY DECK + EXECUTION PROFILE. Mode pills
    # no header ja cobrem PAPER/DEMO/TESTNET/LIVE, entao ENVIRONMENT BANK
    # foi removido.
    desk = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    desk.pack(fill="x", padx=12, pady=(6, 4))
    top = tk.Frame(desk, bg=BG2)
    top.pack(fill="x", padx=10, pady=(6, 2))
    tk.Label(top, text="EXECUTION DESK", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(top, text=f"NEXT {mode.upper()}", fg=run_color, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="right")
    facts = tk.Frame(desk, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 4))
    _desk_metric(facts, "RUNNER", runner_label, GREEN)
    _desk_metric(facts, "ROUTING", route_label, WHITE)
    _desk_metric(facts, "ACCOUNT", mode.upper(), run_color)
    _desk_metric(facts, "RISK", "DESK LIMITS", WHITE)
    lev = tk.Frame(desk, bg=BG2)
    lev.pack(fill="x", padx=10, pady=(0, 6))
    tk.Label(lev, text="LEV", fg=DIM, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left", padx=(0, 6))
    cfg_store = state.setdefault("config", {})
    cfg = cfg_store.setdefault(slug, {"leverage": "2.0"})
    for disp, val in _LEVERAGE_OPTS:
        active = cfg.get("leverage") == val
        pill = tk.Label(lev, text=f" {disp} ",
                        fg=(BG if active else DIM2),
                        bg=(AMBER if active else BG3),
                        font=(FONT, 7, "bold"),
                        cursor="hand2", padx=4, pady=0)
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _v=val, _d=cfg, _s=state: _set_cfg(_d, "leverage", _v, _s))

    run = tk.Label(parent, text=cta_text,
                   fg=BG, bg=run_color, font=(FONT, 10, "bold"),
                   cursor="hand2", padx=8, pady=6)
    run.pack(fill="x", padx=12, pady=(0, 4))
    run.bind("<Button-1>", lambda _e: _run_engine(launcher, slug, meta, state))

    mandate = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
    mandate.pack(fill="x", padx=12, pady=(0, 4))
    tk.Label(mandate, text=f"MANDATE  ·  {mandate_text.replace(chr(10), '  ·  ')}",
             fg=DIM2, bg=BG2, font=(FONT, 7), anchor="w",
             justify="left", wraplength=540).pack(
                 fill="x", padx=10, pady=(6, 6))

    # Shadow loop status (MILLENNIUM only — noop for other engines).
    _render_shadow_panel(parent, launcher, state, slug)

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
    stage_label, stage_color = _stage_badge(meta)
    procs = _list_procs_cached()
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
    tk.Label(head, text=f" {stage_label} ",
             fg=BG, bg=stage_color, font=(FONT, 7, "bold"),
             padx=6, pady=2).pack(side="left", padx=(8, 0))
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

    # ENVIRONMENT BANK removido: mode pills no header ja indicam PAPER/
    # DEMO/TESTNET/LIVE. Operating map fica mais compacto.
    ops = tk.Frame(parent, bg=BG2, highlightbackground=BORDER_H, highlightthickness=1)
    ops.pack(fill="x", padx=12, pady=(4, 4))
    top = tk.Frame(ops, bg=BG2)
    top.pack(fill="x", padx=10, pady=(6, 2))
    tk.Label(top, text="OPERATING MAP", fg=AMBER_B, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="left")
    tk.Label(top, text="LAB -> LIVE", fg=mode_color, bg=BG2,
             font=(FONT, 7, "bold")).pack(side="right")
    facts = tk.Frame(ops, bg=BG2)
    facts.pack(fill="x", padx=8, pady=(0, 4))
    _desk_metric(facts, "MODE", mode_key.upper(), mode_color)
    _desk_metric(facts, "UPTIME", format_uptime(seconds=_uptime_seconds(proc)), WHITE)
    _desk_metric(facts, "DESK", f"{fleet_pos}/{max(len(fleet), 1)}", WHITE)
    _desk_metric(facts, "RISK", f"{snap['positions_count']} BOOKS", WHITE)
    _desk_metric(facts, "FEED", "ATTACHED" if snap["log_path"] else "OFFLINE",
                 GREEN if snap["log_path"] else RED)

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
