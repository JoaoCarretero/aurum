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
    """Stub — filled in Task 8."""
    host = state["master_host"]
    for w in host.winfo_children():
        w.destroy()
    tk.Label(host, text="(master list — task 8)",
             fg=DIM, bg=BG, font=(FONT, 8)).pack(pady=20)


def _render_detail(state, launcher):
    """Stub — filled in Task 9+."""
    host = state["detail_host"]
    for w in host.winfo_children():
        w.destroy()
    tk.Label(host, text="(detail — task 9)",
             fg=DIM, bg=BG, font=(FONT, 8)).pack(pady=20)
