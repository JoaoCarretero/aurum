"""Unit tests for launcher_support.runs_history.

Logic layers only: local disk scanning, VPS merging, formatters,
recency ordering. Tk rendering is validated by a smoke test that
instantiates a hidden root and runs the render without asserting on
widget geometry.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from launcher_support.runs_history import (
    RunSummary,
    clear_collect_caches,
    collect_local_runs,
    collect_vps_runs,
    fmt_duration,
    fmt_equity,
    fmt_roi,
    fmt_started,
    merge_runs,
)


@pytest.fixture(autouse=True)
def _clear_runs_history_caches():
    clear_collect_caches()
    yield
    clear_collect_caches()


def _write_run(tmp, *, engine_dir_name, run_id, mode, hb_overrides=None,
               account=None):
    engine_dir = tmp / "data" / engine_dir_name
    run_dir = engine_dir / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "logs").mkdir(parents=True)
    hb = {
        "run_id": run_id,
        "status": "running",
        "started_at": "2026-04-20T11:00:00+00:00",
        "last_tick_at": "2026-04-20T11:30:00+00:00",
        "ticks_ok": 2,
        "ticks_fail": 0,
        "novel_total": 100,
        "novel_since_prime": 3,
        "mode": mode,
    }
    if hb_overrides:
        hb.update(hb_overrides)
    (run_dir / "state" / "heartbeat.json").write_text(
        json.dumps(hb), encoding="utf-8")
    if account is not None:
        (run_dir / "state" / "account.json").write_text(
            json.dumps(account), encoding="utf-8")
    return run_dir


# ─── collect_local_runs ────────────────────────────────────────────

def test_collect_local_runs_finds_shadow_and_paper(tmp_path):
    _write_run(tmp_path, engine_dir_name="millennium_shadow",
               run_id="2026-04-19_1900", mode="shadow")
    _write_run(tmp_path, engine_dir_name="millennium_paper",
               run_id="2026-04-19_1905", mode="paper",
               account={"equity": 10500.0, "initial_balance": 10000.0,
                        "trades_closed": 3})
    runs = collect_local_runs(tmp_path / "data")
    assert len(runs) == 2
    modes = {r.mode for r in runs}
    assert modes == {"shadow", "paper"}


def test_collect_local_runs_reads_account_for_roi(tmp_path):
    _write_run(tmp_path, engine_dir_name="millennium_paper",
               run_id="2026-04-20_0800", mode="paper",
               account={"equity": 10500.0, "initial_balance": 10000.0,
                        "trades_closed": 5})
    runs = collect_local_runs(tmp_path / "data")
    assert len(runs) == 1
    r = runs[0]
    assert r.equity == pytest.approx(10500.0)
    assert r.initial_balance == pytest.approx(10000.0)
    assert r.roi_pct == pytest.approx(5.0)
    assert r.trades_closed == 5


def test_collect_local_runs_skips_missing_heartbeat(tmp_path):
    (tmp_path / "data" / "millennium_paper" / "stub").mkdir(parents=True)
    runs = collect_local_runs(tmp_path / "data")
    assert runs == []


def test_collect_local_runs_prefers_novel_since_prime(tmp_path):
    _write_run(tmp_path, engine_dir_name="millennium_shadow",
               run_id="x1", mode="shadow",
               hb_overrides={"novel_since_prime": 7, "novel_total": 900})
    runs = collect_local_runs(tmp_path / "data")
    assert runs[0].novel == 7  # novel_since_prime wins


def test_collect_local_runs_falls_back_to_novel_total(tmp_path):
    """Older shadow runs without the prime counter fall back to total."""
    _write_run(tmp_path, engine_dir_name="millennium_shadow",
               run_id="x2", mode="shadow",
               hb_overrides={"novel_total": 42})
    # Remove novel_since_prime by rewriting without it
    hb_path = tmp_path / "data" / "millennium_shadow" / "x2" / "state" / "heartbeat.json"
    hb = json.loads(hb_path.read_text())
    hb.pop("novel_since_prime", None)
    hb_path.write_text(json.dumps(hb))
    runs = collect_local_runs(tmp_path / "data")
    assert runs[0].novel == 42


# ─── collect_vps_runs ──────────────────────────────────────────────

class _FakeClient:
    def __init__(self, runs=None, heartbeats=None, accounts=None):
        self._runs = runs or []
        self._heartbeats = heartbeats or {}
        self._accounts = accounts or {}

    def _get(self, path):
        if path == "/v1/runs":
            return self._runs
        if path.startswith("/v1/runs/") and path.endswith("/heartbeat"):
            rid = path.split("/")[3]
            return self._heartbeats.get(rid, {})
        if path.startswith("/v1/runs/") and path.endswith("/account"):
            rid = path.split("/")[3]
            acct = self._accounts.get(rid)
            if acct is None:
                return {"available": False}
            return acct
        return None


def test_collect_vps_runs_builds_summaries():
    runs_payload = [
        {"run_id": "R1", "engine": "millennium", "mode": "shadow",
         "status": "running",
         "started_at": "2026-04-19T19:00:00Z",
         "last_tick_at": "2026-04-20T11:00:00Z"},
    ]
    hbs = {"R1": {"ticks_ok": 10, "ticks_fail": 0,
                  "novel_since_prime": 2,
                  "status": "running",
                  "started_at": "2026-04-19T19:00:00+00:00",
                  "last_tick_at": "2026-04-20T11:00:00+00:00"}}
    client = _FakeClient(runs=runs_payload, heartbeats=hbs)
    rows = collect_vps_runs(client)
    assert len(rows) == 1
    r = rows[0]
    assert r.engine == "MILLENNIUM"
    assert r.mode == "shadow"
    assert r.source == "vps"
    assert r.ticks_ok == 10
    assert r.novel == 2


def test_collect_vps_runs_empty_client_returns_empty():
    assert collect_vps_runs(None) == []


def test_collect_local_runs_uses_ttl_cache(tmp_path):
    _write_run(tmp_path, engine_dir_name="millennium_shadow",
               run_id="L1", mode="shadow")
    runs1 = collect_local_runs(tmp_path / "data")
    _write_run(tmp_path, engine_dir_name="millennium_shadow",
               run_id="L2", mode="shadow")
    runs2 = collect_local_runs(tmp_path / "data")
    assert [r.run_id for r in runs1] == ["L1"]
    assert [r.run_id for r in runs2] == ["L1"]


def test_collect_vps_runs_uses_ttl_cache():
    runs_payload = [
        {"run_id": "R1", "engine": "millennium", "mode": "shadow",
         "status": "running",
         "started_at": "2026-04-19T19:00:00Z",
         "last_tick_at": "2026-04-20T11:00:00Z"},
    ]
    hbs = {"R1": {"ticks_ok": 10, "ticks_fail": 0, "status": "running"}}
    client = _FakeClient(runs=runs_payload, heartbeats=hbs)

    rows1 = collect_vps_runs(client)
    client._heartbeats["R1"] = {"ticks_ok": 99, "ticks_fail": 0, "status": "running"}
    rows2 = collect_vps_runs(client)

    assert rows1[0].ticks_ok == 10
    assert rows2[0].ticks_ok == 10


# ─── merge_runs ────────────────────────────────────────────────────

def test_merge_runs_vps_wins_over_local(tmp_path):
    _write_run(tmp_path, engine_dir_name="millennium_shadow",
               run_id="SHARED", mode="shadow",
               hb_overrides={"ticks_ok": 1})
    local = collect_local_runs(tmp_path / "data")
    vps_row = RunSummary(
        run_id="SHARED", engine="MILLENNIUM", mode="shadow",
        status="running", started_at="2026-04-19T19:00:00Z",
        stopped_at=None, last_tick_at=None,
        ticks_ok=99, ticks_fail=0, novel=2,
        equity=None, initial_balance=None, roi_pct=None,
        trades_closed=None, source="vps", run_dir=None,
        heartbeat={},
    )
    merged = merge_runs(local, [vps_row])
    # Only one row
    assert len(merged) == 1
    assert merged[0].source == "vps"
    assert merged[0].ticks_ok == 99
    # But the local run_dir got attached for file-based readers
    assert merged[0].run_dir is not None


def test_merge_runs_keeps_local_when_no_vps_match(tmp_path):
    _write_run(tmp_path, engine_dir_name="millennium_shadow",
               run_id="LOCAL_ONLY", mode="shadow")
    local = collect_local_runs(tmp_path / "data")
    merged = merge_runs(local, [])
    assert len(merged) == 1
    assert merged[0].source == "local"


def test_merge_runs_sorts_by_recency(tmp_path):
    older = RunSummary(
        run_id="A", engine="E", mode="shadow", status="running",
        started_at="2026-04-19T19:00:00Z", stopped_at=None,
        last_tick_at="2026-04-19T20:00:00Z",
        ticks_ok=1, ticks_fail=0, novel=None,
        equity=None, initial_balance=None, roi_pct=None,
        trades_closed=None, source="vps", run_dir=None, heartbeat={},
    )
    newer = RunSummary(
        run_id="B", engine="E", mode="shadow", status="running",
        started_at="2026-04-20T12:00:00Z", stopped_at=None,
        last_tick_at="2026-04-20T12:30:00Z",
        ticks_ok=1, ticks_fail=0, novel=None,
        equity=None, initial_balance=None, roi_pct=None,
        trades_closed=None, source="vps", run_dir=None, heartbeat={},
    )
    merged = merge_runs([], [older, newer])
    assert [r.run_id for r in merged] == ["B", "A"]


# ─── Formatters ────────────────────────────────────────────────────

def test_fmt_duration_running_counts_toward_now():
    # Started 3 min ago while still running
    past = (datetime.now(timezone.utc) -
            timedelta(minutes=3)).isoformat()
    out = fmt_duration(past, None, None, running=True)
    assert out.endswith("m") or out.endswith("s")  # minute or second form


def test_fmt_duration_stopped_uses_stopped_at():
    start = "2026-04-20T10:00:00+00:00"
    stop = "2026-04-20T12:30:00+00:00"
    assert fmt_duration(start, stop, None, running=False) == "2h30m"


def test_fmt_duration_days_form():
    start = "2026-04-18T10:00:00+00:00"
    stop = "2026-04-20T14:00:00+00:00"
    assert fmt_duration(start, stop, None, running=False) == "2d4h"


def test_fmt_duration_missing_started_returns_dash():
    assert fmt_duration(None, None, None, running=False) == "—"


def test_fmt_equity_renders_dollars():
    assert fmt_equity(10_500.0) == "$10,500"
    assert fmt_equity(None) == "—"


def test_fmt_roi_signs():
    assert fmt_roi(5.42) == "+5.42%"
    assert fmt_roi(-1.0) == "-1.00%"
    assert fmt_roi(None) == "—"


def test_fmt_started_iso():
    assert fmt_started("2026-04-20T11:39:15+00:00") == "2026-04-20 11:39"
    assert fmt_started(None) == "—"


# ─── Smoke (Tk) ────────────────────────────────────────────────────

def test_render_runs_history_smoke(tmp_path, monkeypatch):
    """Smoke test — render with one fake local run, no crash."""
    import tkinter as tk
    from launcher_support import runs_history as rh

    _write_run(tmp_path, engine_dir_name="millennium_paper",
               run_id="SMOKE_RUN", mode="paper",
               account={"equity": 10100.0, "initial_balance": 10000.0,
                        "trades_closed": 1})
    monkeypatch.setattr(rh, "DATA_ROOT", tmp_path / "data")

    root = tk.Tk()
    root.withdraw()
    try:
        frame = rh.render_runs_history(root, root,
                                       client_factory=lambda: None)
        root.update_idletasks()
        assert frame is not None
    finally:
        root.destroy()
