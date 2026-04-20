"""Tests para cockpit_api.py — endpoints, auth, schemas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_app(tmp_path, monkeypatch):
    """Build FastAPI app with a temp data root and fixed tokens."""
    monkeypatch.setenv("AURUM_COCKPIT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AURUM_COCKPIT_READ_TOKEN", "READ123")
    monkeypatch.setenv("AURUM_COCKPIT_ADMIN_TOKEN", "ADMIN456")
    # Importa aqui pra pegar env vars na hora certa
    from tools.cockpit_api import build_app
    return build_app()


@pytest.fixture
def client(api_app):
    return TestClient(api_app)


def _make_run(data_root: Path, engine_subdir: str, run_id: str,
              heartbeat: dict, manifest: dict | None = None,
              log_text: str | None = None) -> Path:
    run_dir = data_root / engine_subdir / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps(heartbeat))
    if manifest is not None:
        (run_dir / "state" / "manifest.json").write_text(json.dumps(manifest))
    if log_text is not None:
        (run_dir / "logs").mkdir(parents=True, exist_ok=True)
        (run_dir / "logs" / "shadow.log").write_text(log_text, encoding="utf-8")
    return run_dir


def test_healthz_no_auth(client):
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_runs_requires_auth(client):
    r = client.get("/v1/runs")
    assert r.status_code == 401


def test_runs_rejects_bad_token(client):
    r = client.get("/v1/runs", headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 401


def test_runs_empty_when_no_data(client):
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    assert r.json() == []


def test_runs_lists_existing(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "2026-04-18_0229",
        heartbeat={
            "run_id": "2026-04-18_0229", "status": "running",
            "ticks_ok": 5, "ticks_fail": 0, "novel_total": 625,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
        manifest={
            "run_id": "2026-04-18_0229", "engine": "millennium",
            "mode": "shadow", "started_at": "2026-04-18T02:29:38+00:00",
            "commit": "3fa328b", "branch": "feat/phi-engine",
            "config_hash": "sha256:deadbeef", "host": "vmi3200601",
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "2026-04-18_0229"
    assert runs[0]["engine"] == "millennium"
    assert runs[0]["novel_total"] == 625


def test_runs_list_marks_zombie_as_stopped(tmp_path, client):
    """A heartbeat stuck on 'running' with stale last_tick_at surfaces as stopped.

    Reproduces the 2026-04-20 incident: a paper runner killed by
    systemd SIGKILL never updates status; /v1/runs would report
    'running' forever until hand-edit. The API should derive the
    effective status so the cockpit sidebar doesn't lie.
    """
    from datetime import datetime, timezone, timedelta
    stale_ts = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    _make_run(
        tmp_path, "millennium_paper", "zombie_run",
        heartbeat={
            "run_id": "zombie_run", "status": "running",
            "ticks_ok": 3, "ticks_fail": 0, "novel_total": 625,
            "last_tick_at": stale_ts,
            "last_error": None, "tick_sec": 900,
        },
        manifest={
            "run_id": "zombie_run", "engine": "millennium", "mode": "paper",
            "started_at": stale_ts, "commit": "x", "branch": "x",
            "config_hash": "x", "host": "x",
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    # tick_sec=900 -> threshold = max(2700, 600) = 2700s. 4h >> 45m so stale.
    assert runs[0]["status"] == "stopped"


def test_runs_list_includes_label_from_manifest(tmp_path, client):
    """Multi-instance (Fase 2): RunSummary carrega label do manifest."""
    _make_run(
        tmp_path, "millennium_paper", "2026-04-20_165432_kelly5-10k",
        heartbeat={
            "run_id": "2026-04-20_165432_kelly5-10k", "status": "running",
            "ticks_ok": 2, "ticks_fail": 0, "novel_total": 3,
            "last_tick_at": "2026-04-20T16:55:00+00:00",
            "last_error": None, "tick_sec": 900,
            "label": "kelly5-10k",
        },
        manifest={
            "run_id": "2026-04-20_165432_kelly5-10k", "engine": "millennium",
            "mode": "paper", "label": "kelly5-10k",
            "started_at": "2026-04-20T16:54:32+00:00",
            "commit": "abc", "branch": "feat/phi-engine",
            "config_hash": "x", "host": "local",
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert runs[0]["label"] == "kelly5-10k"


def test_runs_list_label_null_when_manifest_omits(tmp_path, client):
    """Backward-compat: runs antigos sem label surfacem label=None."""
    _make_run(
        tmp_path, "millennium_shadow", "legacy_2026-04-18_0229",
        heartbeat={
            "run_id": "legacy_2026-04-18_0229", "status": "running",
            "ticks_ok": 5, "ticks_fail": 0, "novel_total": 625,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
        manifest={
            "run_id": "legacy_2026-04-18_0229", "engine": "millennium",
            "mode": "shadow", "started_at": "2026-04-18T02:29:38+00:00",
            "commit": "x", "branch": "x", "config_hash": "x", "host": "x",
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    assert r.json()[0]["label"] is None


def test_runs_list_keeps_fresh_running_run_as_running(tmp_path, client):
    """Sanity check: healthy heartbeats are NOT downgraded to stopped."""
    from datetime import datetime, timezone, timedelta
    fresh_ts = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
    _make_run(
        tmp_path, "millennium_shadow", "healthy_run",
        heartbeat={
            "run_id": "healthy_run", "status": "running",
            "ticks_ok": 10, "ticks_fail": 0, "novel_total": 100,
            "last_tick_at": fresh_ts,
            "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    assert r.json()[0]["status"] == "running"


def test_runs_admin_token_works(tmp_path, client):
    """Admin token herda read scope."""
    _make_run(
        tmp_path, "millennium_shadow", "r1",
        heartbeat={
            "run_id": "r1", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 10,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_runs_handles_legacy_no_manifest(tmp_path, client):
    """Runs sem manifest.json ainda aparecem (engine derivado do path)."""
    _make_run(
        tmp_path, "millennium_shadow", "legacy_run",
        heartbeat={
            "run_id": "legacy_run", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert runs[0]["engine"] == "millennium"  # derivado do diretório
    assert runs[0]["mode"] == "shadow"


def test_run_detail_returns_manifest_and_heartbeat(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r1",
        heartbeat={
            "run_id": "r1", "status": "running",
            "ticks_ok": 3, "ticks_fail": 0, "novel_total": 42,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
        manifest={
            "run_id": "r1", "engine": "millennium", "mode": "shadow",
            "started_at": "2026-04-18T02:29:38+00:00",
            "commit": "abc", "branch": "feat/phi-engine",
            "config_hash": "sha256:deadbeef", "host": "vmi3200601",
        },
    )
    r = client.get("/v1/runs/r1", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["commit"] == "abc"
    assert body["heartbeat"]["ticks_ok"] == 3


def test_run_detail_404_when_missing(client):
    r = client.get("/v1/runs/does_not_exist", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 404


def test_heartbeat_fast_endpoint(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r2",
        heartbeat={
            "run_id": "r2", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 10,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs/r2/heartbeat", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    assert r.json()["ticks_ok"] == 1


def test_trades_tail(tmp_path, client):
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r3",
        heartbeat={
            "run_id": "r3", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    reports = run_dir / "reports"
    reports.mkdir()
    jsonl = reports / "shadow_trades.jsonl"
    lines = []
    for i in range(10):
        lines.append(json.dumps({
            "timestamp": f"2026-04-18T0{i}:00:00+00:00",
            "symbol": "BTCUSDT", "strategy": "CITADEL",
            "direction": "LONG", "entry": 50000.0 + i,
        }))
    jsonl.write_text("\n".join(lines) + "\n")

    r = client.get(
        "/v1/runs/r3/trades?limit=3",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    # Últimos 3 — ordem preservada do arquivo
    assert [t["entry"] for t in body["trades"]] == [50007.0, 50008.0, 50009.0]


def test_trades_limit_capped_at_500(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r4",
        heartbeat={
            "run_id": "r4", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get(
        "/v1/runs/r4/trades?limit=99999",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r.status_code == 400  # exceeds max


def test_trades_since_filter_works_with_z_suffix(tmp_path, client):
    """since=...Z form should correctly filter records written with +00:00 offset."""
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r_since",
        heartbeat={
            "run_id": "r_since", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    reports = run_dir / "reports"
    reports.mkdir()
    (reports / "shadow_trades.jsonl").write_text("\n".join([
        json.dumps({"timestamp": "2026-04-18T01:00:00+00:00", "symbol": "BTC",
                    "strategy": "X", "direction": "LONG"}),
        json.dumps({"timestamp": "2026-04-18T02:00:00+00:00", "symbol": "BTC",
                    "strategy": "X", "direction": "LONG"}),
        json.dumps({"timestamp": "2026-04-18T03:00:00+00:00", "symbol": "BTC",
                    "strategy": "X", "direction": "LONG"}),
    ]))
    # Client uses the Z-suffix form (common human format)
    r = client.get(
        "/v1/runs/r_since/trades?since=2026-04-18T01:30:00Z",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r.status_code == 200
    body = r.json()
    # Should return only the 02:00 and 03:00 entries
    assert len(body["trades"]) == 2
    assert body["trades"][0]["timestamp"] == "2026-04-18T02:00:00+00:00"


def test_trades_since_invalid_format_returns_400(tmp_path, client):
    """Malformed since query returns 400 rather than silently passing lex compare."""
    _make_run(
        tmp_path, "millennium_shadow", "r_bad_since",
        heartbeat={
            "run_id": "r_bad_since", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get(
        "/v1/runs/r_bad_since/trades?since=not-a-date",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r.status_code == 400


def test_trades_exclude_primed_and_stale_shadow_records_by_default(tmp_path, client):
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r_live_only",
        heartbeat={
            "run_id": "r_live_only", "status": "running",
            "ticks_ok": 2, "ticks_fail": 0, "novel_total": 3,
            "novel_since_prime": 1,
            "last_tick_at": "2026-04-20T10:45:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
    )
    reports = run_dir / "reports"
    reports.mkdir()
    (reports / "shadow_trades.jsonl").write_text("\n".join([
        json.dumps({
            "timestamp": "2026-04-20T10:00:00+00:00",
            "shadow_observed_at": "2026-04-20T10:05:00+00:00",
            "symbol": "BTCUSDT", "strategy": "CITADEL",
            "direction": "LONG", "primed": True,
        }),
        json.dumps({
            "timestamp": "2026-01-24T08:00:00+00:00",
            "shadow_observed_at": "2026-04-20T10:20:00+00:00",
            "symbol": "ETHUSDT", "strategy": "JUMP",
            "direction": "LONG", "primed": False,
        }),
        json.dumps({
            "timestamp": "2026-04-20T10:15:00+00:00",
            "shadow_observed_at": "2026-04-20T10:20:00+00:00",
            "symbol": "SOLUSDT", "strategy": "RENAISSANCE",
            "direction": "SHORT", "primed": False,
        }),
    ]))

    r = client.get(
        "/v1/runs/r_live_only/trades",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["trades"][0]["symbol"] == "SOLUSDT"

    r_all = client.get(
        "/v1/runs/r_live_only/trades?include_primed=true",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r_all.status_code == 200
    body_all = r_all.json()
    assert body_all["count"] == 2
    assert [t["symbol"] for t in body_all["trades"]] == ["BTCUSDT", "SOLUSDT"]


def test_kill_requires_admin(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r5",
        heartbeat={
            "run_id": "r5", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    # Read token rejected
    r = client.post("/v1/runs/r5/kill", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 403


def test_kill_drops_flag(tmp_path, client):
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r6",
        heartbeat={
            "run_id": "r6", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.post("/v1/runs/r6/kill", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 200
    assert (run_dir / ".kill").exists()


def test_kill_404_when_missing(client):
    r = client.post("/v1/runs/missing/kill", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 404


def test_kill_idempotent(tmp_path, client):
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r7",
        heartbeat={
            "run_id": "r7", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    (run_dir / ".kill").write_text("")  # already present
    r = client.post("/v1/runs/r7/kill", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 200


def test_log_tail_basic(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "rlog",
        heartbeat={
            "run_id": "rlog", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
        log_text="\n".join([f"2026-04-18 10:{m:02d}:00  INFO  tick {m}" for m in range(20)]),
    )
    r = client.get("/v1/runs/rlog/log?tail=5",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["lines"]) == 5
    assert "tick 19" in body["lines"][-1]
    assert body["total_lines"] == 20


def test_log_grep_filter(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "rgrep",
        heartbeat={
            "run_id": "rgrep", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
        log_text=(
            "2026-04-18 10:00:00  INFO  tick 1 ok\n"
            "2026-04-18 10:01:00  INFO  telegram sent: SHADOW JUMP LONG BTCUSDT\n"
            "2026-04-18 10:02:00  WARN  telegram send failed: 403 Forbidden\n"
            "2026-04-18 10:03:00  INFO  tick 2 ok\n"
        ),
    )
    r = client.get("/v1/runs/rgrep/log?grep=telegram",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["total_matching"] == 2
    assert all("telegram" in ln.lower() for ln in body["lines"])


def test_log_missing_returns_empty(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "rnolog",
        heartbeat={
            "run_id": "rnolog", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs/rnolog/log",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    assert r.json()["lines"] == []


def test_log_tail_out_of_range_400(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "rbadtail",
        heartbeat={
            "run_id": "rbadtail", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs/rbadtail/log?tail=5000",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 400


def test_telegram_diag_counts_sends_and_failures(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "rdiag",
        heartbeat={
            "run_id": "rdiag", "status": "running",
            "ticks_ok": 3, "ticks_fail": 0, "novel_total": 5,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
        log_text=(
            "2026-04-18 10:00:00  INFO  tick 1 ok\n"
            "2026-04-18 10:01:00  INFO  telegram sent: SHADOW JUMP LONG BTC\n"
            "2026-04-18 10:02:00  INFO  telegram sent: SHADOW CITADEL SHORT ETH\n"
            "2026-04-18 10:03:00  WARN  telegram send failed: 403 bot blocked\n"
            "2026-04-18 10:04:00  INFO  tick 2 ok\n"
        ),
    )
    r = client.get("/v1/runs/rdiag/telegram-diag",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["telegram_failures_logged"] == 1
    assert body["last_failure_reason"].startswith("403 bot blocked")
    assert body["last_failure_ts"] == "2026-04-18 10:03:00"
    assert body["telegram_sends_logged"] >= 2


def test_shadow_start_requires_admin(client):
    r = client.post("/v1/shadow/start", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 403


def test_shadow_start_rejects_unknown_service(client):
    r = client.post(
        "/v1/shadow/start?service=evil_rm_rf",
        headers={"Authorization": "Bearer ADMIN456"},
    )
    assert r.status_code == 400


def test_shadow_start_calls_systemctl(monkeypatch, client):
    import subprocess
    calls = []

    class _Fake:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(args, **kwargs):
        calls.append(args)
        return _Fake(returncode=0, stdout="started", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    r = client.post(
        "/v1/shadow/start",
        headers={"Authorization": "Bearer ADMIN456"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "started"
    assert body["service"] == "millennium_shadow.service"
    assert calls == [["systemctl", "start", "millennium_shadow.service"]]


def test_shadow_start_reports_systemctl_failure(monkeypatch, client):
    import subprocess

    class _Fake:
        returncode = 3
        stdout = ""
        stderr = "Unit millennium_shadow.service not found."

    def _fake_run(args, **kwargs):
        return _Fake()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    r = client.post(
        "/v1/shadow/start",
        headers={"Authorization": "Bearer ADMIN456"},
    )
    assert r.status_code == 500
    assert "Unit" in r.json()["error"]
