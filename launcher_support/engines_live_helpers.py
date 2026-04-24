"""AURUM — pure helpers extraidos de engines_live_view.py.

Modulo contem apenas funcoes/tipos puros (zero Tk, zero mutacao de
state compartilhado do view). engines_live_view.py re-exporta tudo
aqui pra preservar compat com os ~10 call sites externos (launcher.py,
tests, engines_sidebar, etc).

Slice 2026-04-22: extracao pra reduzir engines_live_view.py de 4209
linhas e facilitar testes unitarios das regras de bucket/mode.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from core.ui.ui_palette import (
    AMBER, AMBER_B, CYAN, DIM2,
    GREEN, HAZARD, RED, WHITE,
    MODE_DEMO, MODE_LIVE, MODE_PAPER, MODE_TESTNET,
)

Bucket = Literal["LIVE", "READY", "RESEARCH"]
Mode = Literal["paper", "demo", "testnet", "live", "shadow"]

_MODE_ORDER: tuple[Mode, ...] = ("paper", "demo", "testnet", "live", "shadow")
_DEFAULT_MODE: Mode = "paper"
_DEFAULT_STATE_PATH = Path("data/ui_state.json")
_REPO_ROOT = Path(__file__).resolve().parent.parent

_MODE_COLORS: dict[Mode, str] = {
    "paper":   MODE_PAPER,
    "demo":    MODE_DEMO,
    "testnet": MODE_TESTNET,
    "live":    MODE_LIVE,
    # SHADOW e observacional — usa amber distinto do vermelho LIVE pra
    # deixar claro que nao executa ordens reais, so le o VPS.
    "shadow":  AMBER_B,
}
_STAGE_STYLE: dict[str, tuple[str, str]] = {
    "validated": ("VALIDATED", GREEN),
    "bootstrap_staging": ("BOOTSTRAP", AMBER),
    "research": ("RESEARCH", DIM2),
    "experimental": ("EXPERIMENTAL", RED),
    "quarantined": ("QUARANTINED", HAZARD),
}

# Legacy proc-manager engine names -> canonical slugs.
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


def _stage_badge(meta: dict | None) -> tuple[str, str]:
    key = str((meta or {}).get("stage") or "research").strip().lower()
    if key in _STAGE_STYLE:
        return _STAGE_STYLE[key]
    return (key.upper() or "RESEARCH", DIM2)


def footer_hints(*, selected_bucket: Bucket | None, mode: str) -> tuple[str, str]:
    hints = ["ESC main", "↑↓ list"]
    if selected_bucket == "LIVE":
        hints += ["←→ fleet", "ENTER monitor", "S stop", "L log"]
    elif selected_bucket == "READY":
        hints += ["ENTER launch", "M cycle"]
    elif selected_bucket == "RESEARCH":
        hints += ["B backtest", "ENTER"]
    else:
        hints += ["ENTER select"]
    hints += ["1=paper 2=demo 3=testnet 4=live 5=shadow"]
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
        "LIVE": "ENGINES",
        "READY": "READY TO LAUNCH",
        "RESEARCH": "RESEARCH ONLY",
    }[bucket]


def bucket_header_title(title: str) -> str:
    if title == "LIVE":
        return "ENGINES"
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
    from core.ops.persistence import atomic_write_json
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


def _use_remote_shadow_cache() -> bool:
    """Only trust the global ShadowPoller when running from the repo workspace.

    Tests that chdir() into a temp tree expect pure local disk discovery and
    must not inherit a live poller singleton from another launcher instance.
    """
    try:
        cwd = Path.cwd().resolve()
    except Exception:
        return False
    return cwd == _REPO_ROOT


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


def _sanitize_instance_label(raw: str) -> str:
    label = re.sub(r"[^a-z0-9-]+", "-", str(raw or "").strip().lower())
    label = re.sub(r"-{2,}", "-", label).strip("-")
    return label[:40]
