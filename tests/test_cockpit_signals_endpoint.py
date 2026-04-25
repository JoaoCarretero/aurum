"""Cockpit endpoint /v1/runs/{run_id}/signals lê tail de signals.jsonl.

Cobre:
  - 200 + JSONL parsed quando reports/signals.jsonl existe
  - 404 quando run_id não corresponde a nenhum run discovery
  - Auth via Bearer token (AURUM_COCKPIT_READ_TOKEN)
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_run(tmp_path, monkeypatch):
    """Cria run_dir fake com signals.jsonl e aponta cockpit pra ele."""
    monkeypatch.setenv("AURUM_COCKPIT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AURUM_COCKPIT_READ_TOKEN", "test-read")
    monkeypatch.setenv("AURUM_COCKPIT_ADMIN_TOKEN", "test-admin")

    run_id = "2026-04-24_174017p_test"
    run_dir = tmp_path / "millennium_paper" / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    # heartbeat.json é o que find_runs() exige pra discovery.
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps({
        "run_id": run_id, "status": "running", "mode": "paper",
    }), encoding="utf-8")

    sig_path = run_dir / "reports" / "signals.jsonl"
    rows = [
        {"ts": "2026-04-24T18:00:00Z", "symbol": "BTCUSDT",
         "decision": "opened", "score": 0.82, "reason": "score>thresh"},
        {"ts": "2026-04-24T18:15:00Z", "symbol": "ETHUSDT",
         "decision": "stale", "score": 0.71, "reason": "signal_age>2x"},
    ]
    sig_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                        encoding="utf-8")

    # Reset shadow_contract caches so the new run_dir is discovered.
    from core import shadow_contract
    shadow_contract.clear_caches()

    from tools.cockpit_api import build_app
    return build_app()


def test_signals_endpoint_returns_jsonl_tail(app_with_run):
    client = TestClient(app_with_run)
    resp = client.get(
        "/v1/runs/2026-04-24_174017p_test/signals?limit=10",
        headers={"Authorization": "Bearer test-read"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "signals" in payload
    assert len(payload["signals"]) == 2
    assert payload["signals"][0]["symbol"] == "BTCUSDT"
    assert payload["signals"][1]["decision"] == "stale"


def test_signals_endpoint_404_when_missing(app_with_run):
    client = TestClient(app_with_run)
    resp = client.get(
        "/v1/runs/nonexistent/signals",
        headers={"Authorization": "Bearer test-read"},
    )
    assert resp.status_code == 404
