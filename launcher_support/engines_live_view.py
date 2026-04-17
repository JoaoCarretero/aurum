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
from pathlib import Path
from typing import Literal

Bucket = Literal["LIVE", "READY", "RESEARCH"]
Mode = Literal["paper", "demo", "testnet", "live"]

_MODE_ORDER: tuple[Mode, ...] = ("paper", "demo", "testnet", "live")
_DEFAULT_MODE: Mode = "paper"
_DEFAULT_STATE_PATH = Path("data/ui_state.json")


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
