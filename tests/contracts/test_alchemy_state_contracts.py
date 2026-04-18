"""Contract tests for core.alchemy_state — arbitrage snapshot reader.

Redirects ``root`` to tmp_path so every test is isolated from the real
data/ tree. Covers:

- No snapshot present → EMPTY_SNAPSHOT with _stale=True
- Pinned run with existing snapshot → reads that one
- Pinned run missing → falls back to last_good
- _stale flag: fresh file → False; old file → True
- Malformed JSON → falls back to last_good with _stale=True
- Multiple runs → picks latest by mtime
- read_params: missing file → DEFAULTS; valid overrides merge on top;
  malformed → DEFAULTS fallback
- write_params: creates file, writes JSON atomically, touches reload flag
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from core.alchemy_state import EMPTY_SNAPSHOT, AlchemyState


def _write_snapshot(run_dir: Path, data: dict, mtime: float | None = None):
    """Write data/janestreet/<run_id>/state/snapshot.json with optional mtime."""
    state_dir = run_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / "snapshot.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    if mtime is not None:
        import os
        os.utime(f, (mtime, mtime))
    return f


@pytest.fixture
def tmp_root(tmp_path):
    (tmp_path / "data" / "janestreet").mkdir(parents=True)
    return tmp_path


# ────────────────────────────────────────────────────────────
# read() — snapshot discovery
# ────────────────────────────────────────────────────────────

class TestReadDiscovery:
    def test_no_snapshot_returns_empty_and_stale(self, tmp_root):
        a = AlchemyState(root=tmp_root)
        snap = a.read()
        assert snap["_stale"] is True
        # Every EMPTY_SNAPSHOT key present
        for key in EMPTY_SNAPSHOT:
            assert key in snap

    def test_picks_latest_run_by_mtime(self, tmp_root):
        base = tmp_root / "data" / "janestreet"
        now = time.time()
        _write_snapshot(base / "old_run",
                        {"run_id": "old", "account": 100},
                        mtime=now - 3600)
        _write_snapshot(base / "new_run",
                        {"run_id": "new", "account": 200},
                        mtime=now)
        a = AlchemyState(stale_seconds=60, root=tmp_root)
        snap = a.read()
        assert snap["run_id"] == "new"
        assert snap["account"] == 200


# ────────────────────────────────────────────────────────────
# read() — pin_run override
# ────────────────────────────────────────────────────────────

class TestPinRun:
    def test_pinned_run_reads_that_snapshot(self, tmp_root):
        # Pin a run that's NOT the latest by mtime
        base = tmp_root / "data" / "janestreet"
        latest = _write_snapshot(base / "new_run",
                                 {"run_id": "new"}, mtime=time.time())
        pinned_dir = base / "pinned_run"
        _write_snapshot(pinned_dir,
                        {"run_id": "pinned", "account": 42},
                        mtime=time.time() - 1000)
        a = AlchemyState(root=tmp_root)
        a.pin_run(pinned_dir)
        snap = a.read()
        assert snap["run_id"] == "pinned"
        assert snap["account"] == 42

    def test_pinned_missing_falls_back_to_last_good(self, tmp_root):
        base = tmp_root / "data" / "janestreet"
        pinned_dir = base / "pinned_run"
        pinned_dir.mkdir(parents=True)  # no state/snapshot.json inside
        a = AlchemyState(root=tmp_root)
        a._last_good = {"run_id": "prev", "account": 999, "_stale": False}
        a.pin_run(pinned_dir)
        snap = a.read()
        assert snap["run_id"] == "prev"
        assert snap["_stale"] is True

    def test_unpin_reverts_to_discovery(self, tmp_root):
        base = tmp_root / "data" / "janestreet"
        _write_snapshot(base / "real_run", {"run_id": "real"})
        pinned_dir = base / "pinned_run"
        pinned_dir.mkdir(parents=True)
        a = AlchemyState(root=tmp_root)
        a.pin_run(pinned_dir)
        a.unpin_run()
        assert a.read()["run_id"] == "real"


# ────────────────────────────────────────────────────────────
# read() — stale flag
# ────────────────────────────────────────────────────────────

class TestStaleFlag:
    def test_fresh_snapshot_not_stale(self, tmp_root):
        base = tmp_root / "data" / "janestreet"
        _write_snapshot(base / "r",
                        {"run_id": "r"}, mtime=time.time())
        a = AlchemyState(stale_seconds=60, root=tmp_root)
        assert a.read()["_stale"] is False

    def test_old_snapshot_is_stale(self, tmp_root):
        base = tmp_root / "data" / "janestreet"
        _write_snapshot(base / "r",
                        {"run_id": "r"}, mtime=time.time() - 600)
        a = AlchemyState(stale_seconds=60, root=tmp_root)
        assert a.read()["_stale"] is True


# ────────────────────────────────────────────────────────────
# read() — parse errors
# ────────────────────────────────────────────────────────────

class TestParseFailure:
    def test_malformed_json_falls_back_to_last_good(self, tmp_root):
        base = tmp_root / "data" / "janestreet"
        run_dir = base / "r"
        state_dir = run_dir / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "snapshot.json").write_text("{ not json", encoding="utf-8")
        a = AlchemyState(root=tmp_root)
        a._last_good = {"run_id": "good", "account": 123, "_stale": False}
        snap = a.read()
        assert snap["run_id"] == "good"
        assert snap["_stale"] is True


# ────────────────────────────────────────────────────────────
# read_params / write_params
# ────────────────────────────────────────────────────────────

class TestParams:
    def test_missing_file_returns_defaults(self, tmp_root):
        a = AlchemyState(root=tmp_root)
        params = a.read_params()
        # Defaults come from config.janestreet_defaults — just assert shape
        assert isinstance(params, dict)
        assert len(params) > 0

    def test_partial_override_merges_on_top_of_defaults(self, tmp_root):
        cfg = tmp_root / "config"
        cfg.mkdir()
        # Pick a known default key so we can verify merge
        a = AlchemyState(root=tmp_root)
        defaults = a.DEFAULT_PARAMS
        first_key = next(iter(defaults))
        (cfg / "alchemy_params.json").write_text(
            json.dumps({first_key: "OVERRIDE"}), encoding="utf-8")
        params = a.read_params()
        # Overridden key is replaced
        assert params[first_key] == "OVERRIDE"
        # Other default keys preserved
        for k, v in defaults.items():
            if k != first_key:
                assert params[k] == v

    def test_malformed_params_fallback_to_defaults(self, tmp_root):
        cfg = tmp_root / "config"
        cfg.mkdir()
        (cfg / "alchemy_params.json").write_text("{ bad", encoding="utf-8")
        a = AlchemyState(root=tmp_root)
        assert a.read_params() == dict(a.DEFAULT_PARAMS)

    def test_write_params_creates_file_and_reload_flag(self, tmp_root):
        a = AlchemyState(root=tmp_root)
        a.write_params({"custom_key": "custom_val"})
        params_file = tmp_root / "config" / "alchemy_params.json"
        reload_flag = tmp_root / "config" / "alchemy_params.json.reload"
        assert params_file.exists()
        assert reload_flag.exists()
        data = json.loads(params_file.read_text(encoding="utf-8"))
        assert data["custom_key"] == "custom_val"

    def test_write_params_merges_into_existing(self, tmp_root):
        cfg = tmp_root / "config"
        cfg.mkdir()
        (cfg / "alchemy_params.json").write_text(
            json.dumps({"keep": "me", "overwrite_me": 1}), encoding="utf-8")
        a = AlchemyState(root=tmp_root)
        a.write_params({"overwrite_me": 2, "new": "added"})
        data = json.loads((cfg / "alchemy_params.json").read_text())
        assert data["keep"] == "me"
        assert data["overwrite_me"] == 2
        assert data["new"] == "added"
