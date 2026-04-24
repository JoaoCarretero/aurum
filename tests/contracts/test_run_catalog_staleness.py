"""Staleness resolution contracts for core.ops.run_catalog.

Locks in the behavior that a cockpit-API run claiming status='running'
but lagging more than 30 minutes on last_tick_at is reclassified as
'stale' — paper/shadow runners tick every 15 minutes, so two missed
ticks is unambiguously a dead process whose heartbeat was never
downgraded. Without this, zombie runs inflate /data engines LIVE count
and the cockpit RUNNING counter.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.ops.run_catalog import RunSummary, is_run_stale, resolve_status


def _iso(delta_minutes: float) -> str:
    return (datetime.now(timezone.utc)
            - timedelta(minutes=delta_minutes)).isoformat()


def test_fresh_running_is_not_stale() -> None:
    assert is_run_stale({"status": "running", "last_tick_at": _iso(5)}) is False


def test_running_lagging_over_threshold_is_stale() -> None:
    assert is_run_stale({"status": "running", "last_tick_at": _iso(35)}) is True


def test_running_without_last_tick_is_not_stale() -> None:
    """Runner primed but still waiting on its first tick — not a zombie."""
    assert is_run_stale({"status": "running", "last_tick_at": None}) is False


def test_stopped_status_is_never_stale() -> None:
    assert is_run_stale({"status": "stopped", "last_tick_at": _iso(999)}) is False


def test_accepts_run_summary_instance() -> None:
    stale_summary = RunSummary(
        run_id="x", engine="CITADEL", mode="paper", status="running",
        started_at=None, stopped_at=None, last_tick_at=_iso(45),
        ticks_ok=None, ticks_fail=None, novel=None,
        equity=None, initial_balance=None, roi_pct=None,
        trades_closed=None, source="vps", run_dir=None, heartbeat=None,
    )
    assert is_run_stale(stale_summary) is True


def test_resolve_status_downgrades_stale_running() -> None:
    assert resolve_status("running", _iso(40)) == "stale"


def test_resolve_status_preserves_fresh_running() -> None:
    assert resolve_status("running", _iso(5)) == "running"


def test_resolve_status_preserves_non_running() -> None:
    assert resolve_status("stopped", _iso(999)) == "stopped"
    assert resolve_status("failed", _iso(5)) == "failed"


def test_resolve_status_handles_missing_tick() -> None:
    assert resolve_status("running", None) == "running"


def test_resolve_status_tolerates_invalid_timestamp() -> None:
    assert resolve_status("running", "not-a-timestamp") == "running"
