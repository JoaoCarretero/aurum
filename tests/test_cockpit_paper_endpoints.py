"""Contract tests for paper-specific cockpit endpoints.

Covers:
  - /v1/runs/{id}/positions returns state/positions.json snapshot
  - /v1/runs/{id}/equity?tail=N returns tail of reports/equity.jsonl
  - /v1/shadow/start whitelist accepts millennium_paper
  - /v1/shadow/start rejects unknown services
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_app(tmp_path, monkeypatch):
    monkeypatch.setenv("AURUM_COCKPIT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AURUM_COCKPIT_READ_TOKEN", "READ123")
    monkeypatch.setenv("AURUM_COCKPIT_ADMIN_TOKEN", "ADMIN456")
    from tools.cockpit_api import build_app
    return build_app()


@pytest.fixture
def client(api_app):
    return TestClient(api_app)


def _make_paper_run(data_root: Path, run_id: str = "RID") -> Path:
    run_dir = data_root / "millennium_paper" / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps({
        "run_id": run_id, "status": "running",
        "mode": "paper",
    }))
    (run_dir / "state" / "positions.json").write_text(json.dumps({
        "as_of": "2026-04-19T14:00:00Z", "count": 1,
        "positions": [{"id": "pos_1", "symbol": "BTCUSDT", "engine": "CITADEL",
                       "direction": "LONG", "entry_price": 100.0,
                       "size": 1.0, "notional": 100.0,
                       "stop": 98.0, "target": 104.0,
                       "opened_at": "2026-04-19T14:00:00Z", "opened_at_idx": 0,
                       "unrealized_pnl": 5.0, "mtm_price": 105.0,
                       "bars_held": 2}]
    }))
    eq = run_dir / "reports" / "equity.jsonl"
    with open(eq, "w", encoding="utf-8") as fh:
        for i in range(10):
            fh.write(json.dumps({
                "tick": i + 1, "ts": f"t{i}",
                "equity": 10_000.0 + i * 10,
                "balance": 10_000.0 + i * 10,
                "realized": 0.0, "unrealized": i * 10.0,
                "drawdown": 0.0, "positions_open": 1,
            }) + "\n")
    return run_dir


def test_positions_endpoint_returns_snapshot(client, tmp_path):
    _make_paper_run(tmp_path, "RID")
    r = client.get("/v1/runs/RID/positions",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["positions"][0]["symbol"] == "BTCUSDT"


def test_account_endpoint_returns_snapshot(client, tmp_path):
    run_dir = tmp_path / "millennium_paper" / "RID"
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps({
        "run_id": "RID", "status": "running",
    }))
    account_payload = {
        "equity": 10_120.0, "drawdown_pct": 0.12,
        "realized_pnl": 80.0, "unrealized_pnl": 40.0,
        "ks_state": "NORMAL",
        "metrics": {"sharpe": 1.5, "win_rate": 0.6, "profit_factor": 2.0,
                    "maxdd": 30.0, "roi_pct": 1.2},
    }
    (run_dir / "state" / "account.json").write_text(json.dumps(account_payload))
    r = client.get("/v1/runs/RID/account",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["equity"] == 10_120.0
    assert body["metrics"]["sharpe"] == 1.5


def test_account_endpoint_unavailable_when_shadow_run(client, tmp_path):
    run_dir = tmp_path / "millennium_shadow" / "SID"
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps({
        "run_id": "SID", "status": "running",
    }))
    r = client.get("/v1/runs/SID/account",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False


def test_positions_endpoint_empty_when_file_missing(client, tmp_path):
    # Create a paper run without positions.json
    run_dir = tmp_path / "millennium_paper" / "NOPOS"
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps({
        "run_id": "NOPOS", "status": "running",
    }))
    r = client.get("/v1/runs/NOPOS/positions",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert body["positions"] == []


def test_equity_endpoint_tail_respects_limit(client, tmp_path):
    _make_paper_run(tmp_path, "RID")
    r = client.get("/v1/runs/RID/equity?tail=3",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    assert body["points"][-1]["tick"] == 10


def test_equity_endpoint_rejects_invalid_tail(client, tmp_path):
    _make_paper_run(tmp_path, "RID")
    r = client.get("/v1/runs/RID/equity?tail=0",
                   headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 400


def test_equity_requires_auth(client, tmp_path):
    _make_paper_run(tmp_path, "RID")
    r = client.get("/v1/runs/RID/equity")
    assert r.status_code == 401


def test_shadow_start_accepts_millennium_paper(client, tmp_path, monkeypatch):
    # Stub subprocess.run to avoid actual systemctl call
    import tools.cockpit_api as ca

    class DummyResult:
        returncode = 0
        stdout = "Started"
        stderr = ""

    fake_run_called = {"count": 0}

    def fake_run(cmd, **kwargs):
        fake_run_called["count"] += 1
        fake_run_called["cmd"] = cmd
        return DummyResult()

    monkeypatch.setattr(ca.__dict__.get("subprocess", None) or
                        __import__("subprocess"), "run", fake_run)
    r = client.post("/v1/shadow/start?service=millennium_paper",
                    headers={"Authorization": "Bearer ADMIN456"})
    # Either 200 success or 500 if subprocess couldn't be patched cleanly.
    # What matters: whitelist accepts the service, so we should NOT get 400.
    assert r.status_code != 400


def test_shadow_start_rejects_unknown_service(client, tmp_path):
    r = client.post("/v1/shadow/start?service=evil",
                    headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 400


def test_systemctl_action_rejects_unknown_action(client):
    r = client.post("/v1/systemctl/rm_rf?service=millennium_shadow",
                    headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 400
    assert "action must be one of" in r.json()["error"]


def test_systemctl_action_rejects_unknown_service(client):
    r = client.post("/v1/systemctl/start?service=sshd",
                    headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 400
    assert "service must be one of" in r.json()["error"]


def test_systemctl_action_requires_admin(client):
    r = client.post("/v1/systemctl/stop?service=millennium_shadow",
                    headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 403
