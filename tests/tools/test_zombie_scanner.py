"""Tests for tools/maintenance/zombie_scanner.py.

Exercise zombie detection + one-alert-per-run state management.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.maintenance import zombie_scanner as zs
from core.shadow_contract import Heartbeat


def _make_run(tmp_path: Path, run_id: str, *, status: str, tick_sec: int,
              age_sec: float, label: str = "desk-test",
              engine_name: str = "millennium", mode: str = "shadow") -> Path:
    """Create a synthetic run_dir with heartbeat.json aged by age_sec."""
    last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=age_sec)
    # Layout A: data/{engine}_{mode}/{run_id}/state/heartbeat.json
    run_dir = tmp_path / f"{engine_name}_{mode}" / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    heartbeat = {
        "run_id": run_id,
        "status": status,
        "label": label,
        "started_at": (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),
        "tick_sec": tick_sec,
        "ticks_ok": 10,
        "ticks_fail": 0,
        "novel_total": 0,
        "novel_since_prime": 0,
        "last_scan_scanned": 0,
        "last_scan_dedup": 0,
        "last_scan_stale": 0,
        "last_scan_live": 0,
        "last_novel_at": None,
        "last_tick_at": last_tick_at.isoformat(),
    }
    (run_dir / "state" / "heartbeat.json").write_text(
        json.dumps(heartbeat), encoding="utf-8",
    )
    return run_dir


# ────────────────────────────────────────────────────────────
# is_zombie helper
# ────────────────────────────────────────────────────────────

class TestIsZombie:
    def _hb(self, *, status: str, tick_sec: int, age_sec: float) -> Heartbeat:
        return Heartbeat(
            run_id="R", status=status, tick_sec=tick_sec,
            ticks_ok=1, ticks_fail=0, novel_total=0, novel_since_prime=0,
            last_scan_scanned=0, last_scan_dedup=0, last_scan_stale=0,
            last_scan_live=0, last_novel_at=None,
            last_tick_at=datetime.now(timezone.utc) - timedelta(seconds=age_sec),
        )

    def test_stopped_is_never_zombie(self):
        hb = self._hb(status="stopped", tick_sec=900, age_sec=10_000)
        z, _ = zs.is_zombie(hb, datetime.now(timezone.utc), floor_sec=600)
        assert z is False

    def test_running_recent_is_not_zombie(self):
        # tick_sec 900 → threshold 2700s. 300s old is fresh.
        hb = self._hb(status="running", tick_sec=900, age_sec=300)
        z, _ = zs.is_zombie(hb, datetime.now(timezone.utc), floor_sec=600)
        assert z is False

    def test_running_stale_is_zombie(self):
        # tick_sec 900 → threshold 2700s. 3500s old triggers.
        hb = self._hb(status="running", tick_sec=900, age_sec=3500)
        z, age = zs.is_zombie(hb, datetime.now(timezone.utc), floor_sec=600)
        assert z is True
        assert age > 2700

    def test_floor_applies_when_tick_tiny(self):
        # tick_sec 10 → threshold max(30, 600) = 600. 500s old not zombie.
        hb = self._hb(status="running", tick_sec=10, age_sec=500)
        z, _ = zs.is_zombie(hb, datetime.now(timezone.utc), floor_sec=600)
        assert z is False
        # 700s old → zombie (over floor)
        hb = self._hb(status="running", tick_sec=10, age_sec=700)
        z, _ = zs.is_zombie(hb, datetime.now(timezone.utc), floor_sec=600)
        assert z is True


# ────────────────────────────────────────────────────────────
# scan_once integration
# ────────────────────────────────────────────────────────────

class TestScanOnce:
    def test_scan_clean_no_alerts(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        _make_run(data_root, "R1", status="running",
                  tick_sec=900, age_sec=60)  # fresh
        _make_run(data_root, "R2", status="stopped",
                  tick_sec=900, age_sec=10_000)  # stopped

        sent: list[str] = []
        state = data_root / "state.json"
        new, pruned = zs.scan_once(
            data_root, state, send_fn=lambda m: (sent.append(m) or True),
        )
        assert new == []
        assert sent == []

    def test_scan_detects_zombie_and_alerts_once(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        _make_run(data_root, "R_ZOMBIE", status="running",
                  tick_sec=900, age_sec=3500)

        sent: list[str] = []
        state = data_root / "state.json"

        # First scan: alert fires.
        new, _ = zs.scan_once(
            data_root, state, send_fn=lambda m: (sent.append(m) or True),
        )
        assert new == ["R_ZOMBIE"]
        assert len(sent) == 1
        assert "R_ZOMBIE" in sent[0]
        assert "ZOMBIE RUN" in sent[0]

        # Second scan: already notified, no new alert.
        sent.clear()
        new, _ = zs.scan_once(
            data_root, state, send_fn=lambda m: (sent.append(m) or True),
        )
        assert new == []
        assert sent == []

    def test_failed_send_not_marked_notified(self, tmp_path):
        """If Telegram send fails, we keep trying on next scan."""
        data_root = tmp_path / "data"
        data_root.mkdir()
        _make_run(data_root, "R_FAIL", status="running",
                  tick_sec=900, age_sec=3500)

        sent: list[str] = []
        state = data_root / "state.json"
        # First scan: send returns False
        zs.scan_once(data_root, state,
                     send_fn=lambda m: (sent.append(m), False)[1])
        assert sent  # attempted
        persisted = zs.load_state(state)
        assert "R_FAIL" not in persisted

        # Second scan: retries
        sent.clear()
        new, _ = zs.scan_once(
            data_root, state, send_fn=lambda m: (sent.append(m) or True),
        )
        assert new == ["R_FAIL"]
        assert sent == [sent[0]]

    def test_state_pruned_when_run_dir_gone(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        _make_run(data_root, "R_GONE", status="running",
                  tick_sec=900, age_sec=3500)

        state = data_root / "state.json"
        # First pass: notify R_GONE.
        sent: list[str] = []
        zs.scan_once(data_root, state,
                     send_fn=lambda m: (sent.append(m) or True))
        assert "R_GONE" in zs.load_state(state)

        # Remove the run_dir and rescan — prune should kick in.
        # Clear find_runs' TTL cache (1s) so the rescan doesn't see
        # stale discovery results.
        from core import shadow_contract
        shadow_contract._RUN_DISCOVERY_CACHE.clear()
        import shutil
        shutil.rmtree(data_root / "millennium_shadow" / "R_GONE")

        new, pruned = zs.scan_once(
            data_root, state, send_fn=lambda m: True,
        )
        assert new == []
        assert "R_GONE" in pruned
        assert "R_GONE" not in zs.load_state(state)
