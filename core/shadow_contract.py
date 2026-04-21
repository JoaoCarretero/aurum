"""Shared contract for shadow/paper/live runners consumed by cockpit API.

Runners write manifest.json + heartbeat.json to `<run_dir>/state/`. The
cockpit API discovers runs via `find_runs` and validates payloads against
these pydantic models. Cockpit client imports the same models for typed
responses. One source of truth avoids schema drift.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RunMode = Literal["shadow", "paper", "testnet", "live", "backtest"]
RunStatus = Literal["running", "stopped", "failed"]


class Manifest(BaseModel):
    """Imutavel: escrito uma vez no start do runner."""
    run_id: str
    engine: str
    mode: RunMode
    started_at: datetime
    commit: str
    branch: str
    config_hash: str
    host: str
    python_version: str | None = None
    label: str | None = None
    model_config = ConfigDict(extra="allow")


class Heartbeat(BaseModel):
    """Mutavel: atualizado a cada tick pelo runner.

    extra='allow' — runner pode evoluir o shape; client consome o que
    conhece e preserva o resto.
    """
    run_id: str
    status: RunStatus
    ticks_ok: int = 0
    ticks_fail: int = 0
    novel_total: int = 0
    last_tick_at: datetime | None = None
    last_error: str | None = None
    tick_sec: int = 0
    started_at: datetime | None = None
    run_hours: float = 0.0
    stopped_at: datetime | None = None
    stopped_reason: str | None = None
    model_config = ConfigDict(extra="allow")


class RunSummary(BaseModel):
    """Linha leve do /runs — o suficiente pra listar sem payloads pesados."""
    run_id: str
    engine: str
    mode: RunMode
    status: RunStatus
    started_at: datetime
    last_tick_at: datetime | None = None
    novel_total: int = 0
    label: str | None = None


class RunDetail(BaseModel):
    """Resposta de /runs/{id}: agrega manifest + heartbeat."""
    manifest: Manifest
    heartbeat: Heartbeat


class TradeRecord(BaseModel):
    """Schema permissivo — engine schema evolve; extra fields preservados."""
    timestamp: datetime
    symbol: str
    strategy: str
    direction: str
    entry: float | None = None
    exit: float | None = None
    pnl: float | None = None
    shadow_observed_at: datetime | None = None

    stop: float | None = None
    target: float | None = None
    exit_p: float | None = None
    rr: float | None = None
    duration: int | None = None
    result: Literal["WIN", "LOSS"] | None = None
    exit_reason: str | None = None
    size: float | None = None
    score: float | None = None
    r_multiple: float | None = None

    macro_bias: Literal["BULL", "BEAR", "CHOP"] | None = None
    vol_regime: Literal["LOW", "NORMAL", "HIGH"] | None = None

    omega_struct: float | None = None
    omega_flow: float | None = None
    omega_cascade: float | None = None
    omega_momentum: float | None = None
    omega_pullback: float | None = None

    struct: str | None = None             # swing_structure label: "UP" | "DOWN" | ...
    struct_str: float | None = None       # struct strength 0-1
    rsi: float | None = None
    dist_ema21: float | None = None
    chop_trade: bool | None = None

    dd_scale: float | None = None
    corr_mult: float | None = None

    hmm_regime: str | None = None
    hmm_confidence: float | None = None

    shadow_run_id: str | None = None

    model_config = ConfigDict(extra="allow")


# --- Discovery ------------------------------------------------

_RUN_DISCOVERY_TTL_S = 1.0
_RUN_DISCOVERY_CACHE: dict[tuple[str, tuple[str, ...] | None], tuple[float, list[Path]]] = {}
_JSON_CACHE_TTL_S = 1.0
_JSON_CACHE: dict[Path, tuple[float, dict]] = {}


def clear_caches() -> None:
    _RUN_DISCOVERY_CACHE.clear()
    _JSON_CACHE.clear()


def _load_json_cached(path: Path) -> dict:
    now = time.monotonic()
    cached = _JSON_CACHE.get(path)
    if cached and (now - cached[0]) < _JSON_CACHE_TTL_S:
        return dict(cached[1])
    payload = json.loads(path.read_text(encoding="utf-8"))
    _JSON_CACHE[path] = (now, dict(payload))
    return payload

def find_runs(data_root: Path, engines: list[str] | None = None) -> list[Path]:
    """Return run_dir paths containing a heartbeat.json, sorted by mtime DESC.

    Honors layouts:
      - data/{engine}_shadow/{run_id}/state/heartbeat.json
      - data/{engine}_paper/{run_id}/state/heartbeat.json
      - data/shadow/{engine}/{run_id}/state/heartbeat.json  (future)

    If `engines` is given, restricts to those engine names.
    """
    cache_key = (str(data_root), tuple(engines) if engines else None)
    now = time.monotonic()
    cached = _RUN_DISCOVERY_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _RUN_DISCOVERY_TTL_S:
        return list(cached[1])

    runs: list[tuple[float, Path]] = []
    if not data_root.exists():
        return []
    for engine_dir in data_root.iterdir():
        if not engine_dir.is_dir():
            continue
        name = engine_dir.name
        # Layout A: data/{engine}_{shadow,paper}/{run_id}/
        if name.endswith("_shadow") or name.endswith("_paper"):
            suffix = "_shadow" if name.endswith("_shadow") else "_paper"
            engine = name.removesuffix(suffix)
            if engines and engine not in engines:
                continue
            for run_dir in engine_dir.iterdir():
                hb = run_dir / "state" / "heartbeat.json"
                if hb.exists():
                    runs.append((hb.stat().st_mtime, run_dir))
        # Layout B: data/shadow/{engine}/{run_id}/
        elif name == "shadow":
            for sub_engine in engine_dir.iterdir():
                if not sub_engine.is_dir():
                    continue
                if engines and sub_engine.name not in engines:
                    continue
                for run_dir in sub_engine.iterdir():
                    hb = run_dir / "state" / "heartbeat.json"
                    if hb.exists():
                        runs.append((hb.stat().st_mtime, run_dir))
    runs.sort(key=lambda t: t[0], reverse=True)
    resolved = [p for _, p in runs]
    _RUN_DISCOVERY_CACHE[cache_key] = (now, list(resolved))
    return resolved


def load_heartbeat(run_dir: Path) -> Heartbeat:
    """Load and validate heartbeat.json. Raises pydantic ValidationError on bad shape."""
    payload = _load_json_cached(run_dir / "state" / "heartbeat.json")
    return Heartbeat(**payload)


def load_manifest(run_dir: Path) -> Manifest | None:
    """Load manifest.json if present; return None for legacy runs that predate the file."""
    path = run_dir / "state" / "manifest.json"
    if not path.exists():
        return None
    payload = _load_json_cached(path)
    return Manifest(**payload)


# --- Config hash ----------------------------------------------

_HASH_FIELDS = (
    "SLIPPAGE", "SPREAD", "COMMISSION", "FUNDING_PER_8H",
    "BASE_RISK", "MAX_RISK", "CONVEX_ALPHA",
    "TARGET_RR", "STOP_ATR_M",
    "SCORE_THRESHOLD", "SCORE_THRESHOLD_HIGH_VOL", "SCORE_THRESHOLD_LOW_VOL",
    "OMEGA_WEIGHTS", "OMEGA_MIN_COMPONENT",
    "MAX_OPEN_POSITIONS", "CORR_THRESHOLD", "CORR_SOFT_THRESHOLD",
    "STREAK_COOLDOWN", "SYM_LOSS_COOLDOWN",
)


def compute_config_hash() -> str:
    """Hash dos campos materialmente relevantes de config/params.py.

    Estavel entre runs com mesma config; muda quando qualquer tuning rolou.
    """
    from config import params as P  # lazy to avoid circular imports
    payload: dict[str, object] = {}
    for field in _HASH_FIELDS:
        if hasattr(P, field):
            payload[field] = getattr(P, field)
    serial = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(serial).hexdigest()[:16]
