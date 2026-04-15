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

    def pin_run(self, run_dir: Path):
        """Called by launcher when it spawns a specific engine run."""
        self._pinned_run = Path(run_dir)

    def unpin_run(self):
        self._pinned_run = None

    def _latest_snapshot_path(self) -> Path | None:
        if self._pinned_run is not None:
            p = self._pinned_run / "state" / "snapshot.json"
            return p if p.exists() else None
        base = self._root / "data" / "janestreet"
        if not base.exists():
            return None
        candidates = sorted(
            base.glob("*/state/snapshot.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

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
        if not p.exists():
            return dict(self.DEFAULT_PARAMS)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            merged = dict(self.DEFAULT_PARAMS)
            merged.update(data)
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
        (p.parent / "alchemy_params.json.reload").touch()
