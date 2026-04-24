"""AlchemyState — reads arbitrage engine snapshot for the ALCHEMY dashboard.

The engine writes `data/janestreet/<run_id>/state/snapshot.json` at the end of each
scan cycle. This module discovers the latest run, reads the snapshot atomically,
caches the last successful read, and flags stale data when the file falls behind.
"""
import json
import time
from pathlib import Path

from core.persistence import atomic_write_text
from config.janestreet_defaults import DEFAULTS as _JS_DEFAULTS

EMPTY_SNAPSHOT = {
    "ts": "",
    "run_id": "",
    "mode": "paper",
    "engine_pid": 0,
    "account": 0,
    "peak": 0,
    "exposure_usd": 0,
    "drawdown_pct": 0,
    "realized_pnl": 0,
    "unrealized_pnl": 0,
    "losses_streak": 0,
    "killed": False,
    "sortino": 0,
    "trades_count": 0,
    "opportunities": [],
    "funding": {},
    "next_funding": {},
    "positions": [],
    "venue_health": {},
    "basis_history": {},
    "_stale": True,
}


class AlchemyState:
    """Reader for the arbitrage engine's live snapshot."""
    _SNAPSHOT_DISCOVERY_TTL_S = 1.0
    _PARAMS_CACHE_TTL_S = 2.0

    def __init__(
        self,
        stale_seconds: int = 10,
        run_dir: Path | None = None,
        root: Path | None = None,
    ):
        self.stale_seconds = stale_seconds
        self._pinned_run = run_dir
        self._root = Path(root) if root is not None else Path.cwd()
        self._last_good: dict = dict(EMPTY_SNAPSHOT)
        self._latest_snapshot_cache: tuple[float, str | None, Path | None] | None = None
        self._params_cache: tuple[float, str, dict] | None = None

    def pin_run(self, run_dir: Path):
        """Called by launcher when it spawns a specific engine run."""
        self._pinned_run = Path(run_dir)
        self._latest_snapshot_cache = None

    def unpin_run(self):
        self._pinned_run = None
        self._latest_snapshot_cache = None

    def _latest_snapshot_path(self) -> Path | None:
        if self._pinned_run is not None:
            p = self._pinned_run / "state" / "snapshot.json"
            return p if p.exists() else None
        base = self._root / "data" / "janestreet"
        if not base.exists():
            return None
        now = time.monotonic()
        cache_key = str(base)
        cached = self._latest_snapshot_cache
        if cached and cached[1] == cache_key and (now - cached[0]) < self._SNAPSHOT_DISCOVERY_TTL_S:
            return cached[2]
        candidates = sorted(
            base.glob("*/state/snapshot.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        latest = candidates[0] if candidates else None
        self._latest_snapshot_cache = (now, cache_key, latest)
        return latest

    def read(self) -> dict:
        p = self._latest_snapshot_path()
        if p is None:
            snap = dict(self._last_good)
            snap["_stale"] = True
            return snap
        age = time.time() - p.stat().st_mtime
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            snap = dict(self._last_good)
            snap["_stale"] = True
            return snap
        data["_stale"] = age > self.stale_seconds
        self._last_good = data
        return data

    DEFAULT_PARAMS = dict(_JS_DEFAULTS)  # SSOT: config/janestreet_defaults.py

    def read_params(self) -> dict:
        p = self._root / "config" / "alchemy_params.json"
        now = time.monotonic()
        cache_key = str(p)
        cached = self._params_cache
        if cached and cached[1] == cache_key and (now - cached[0]) < self._PARAMS_CACHE_TTL_S:
            return dict(cached[2])
        if not p.exists():
            return dict(self.DEFAULT_PARAMS)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            merged = dict(self.DEFAULT_PARAMS)
            merged.update(data)
            self._params_cache = (now, cache_key, dict(merged))
            return merged
        except Exception:
            return dict(self.DEFAULT_PARAMS)

    def write_params(self, updates: dict):
        """Merge updates into alchemy_params.json and touch the reload flag."""
        current = self.read_params()
        current.update(updates)
        p = self._root / "config" / "alchemy_params.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(p, json.dumps(current, indent=2))
        self._params_cache = (time.monotonic(), str(p), dict(current))
        (p.parent / "alchemy_params.json.reload").touch()
