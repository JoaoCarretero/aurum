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
              heartbeat: dict, manifest: dict | None = None) -> Path:
    run_dir = data_root / engine_subdir / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps(heartbeat))
    if manifest is not None:
        (run_dir / "state" / "manifest.json").write_text(json.dumps(manifest))
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
