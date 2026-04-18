"""Tests do cockpit_client — parsing, circuit breaker, cache."""
from __future__ import annotations

import json
import time
import urllib.error
from unittest.mock import patch, MagicMock

import pytest

from launcher_support.cockpit_client import (
    CockpitClient,
    CockpitConfig,
    CircuitOpen,
)


@pytest.fixture
def tmp_cache(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def cfg():
    return CockpitConfig(
        base_url="http://localhost:8787",
        read_token="READ",
        admin_token="ADMIN",
        timeout_sec=1.0,
    )


def _fake_response(body, status=200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(body).encode("utf-8")
    mock.__enter__.return_value = mock
    return mock


def test_healthz_ok(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    with patch("urllib.request.urlopen", return_value=_fake_response({"status": "ok"})):
        assert client.healthz()["status"] == "ok"


def test_list_runs_returns_list(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    body = [{
        "run_id": "r1", "engine": "millennium", "mode": "shadow",
        "status": "running",
        "started_at": "2026-04-18T02:29:38+00:00",
        "last_tick_at": "2026-04-18T03:00:00+00:00",
        "novel_total": 10,
    }]
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        runs = client.list_runs()
    assert len(runs) == 1
    assert runs[0]["engine"] == "millennium"


def test_circuit_opens_after_3_fails(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    with patch("urllib.request.urlopen", side_effect=OSError("conn refused")):
        for _ in range(3):
            with pytest.raises(OSError):
                client.list_runs()
        # 4ª chamada: circuito aberto
        with pytest.raises(CircuitOpen):
            client.list_runs()


def test_circuit_closes_after_timeout(cfg, tmp_cache, monkeypatch):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    client._breaker_open_until = time.time() - 1  # expired
    client._consecutive_failures = 3
    with patch("urllib.request.urlopen", return_value=_fake_response([])):
        runs = client.list_runs()
    assert runs == []
    assert client._consecutive_failures == 0


def test_cache_saves_on_success(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    body = [{
        "run_id": "r1", "engine": "millennium", "mode": "shadow",
        "status": "running",
        "started_at": "2026-04-18T02:29:38+00:00",
        "last_tick_at": None, "novel_total": 0,
    }]
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        client.list_runs()
    cached = tmp_cache / "runs.json"
    assert cached.exists()


def test_get_heartbeat_uses_run_id(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    hb = {
        "run_id": "r1", "status": "running",
        "ticks_ok": 5, "ticks_fail": 0, "novel_total": 100,
        "last_tick_at": "2026-04-18T03:00:00+00:00",
        "last_error": None, "tick_sec": 900,
    }
    with patch("urllib.request.urlopen", return_value=_fake_response(hb)) as mock:
        got = client.get_heartbeat("r1")
    assert got["ticks_ok"] == 5
    # Verifica que a URL contém o run_id
    req = mock.call_args[0][0]
    assert "r1/heartbeat" in req.full_url


def test_drop_kill_requires_admin_token(cfg, tmp_cache):
    # Client sem admin_token → drop_kill levanta
    cfg_no_admin = CockpitConfig(
        base_url=cfg.base_url,
        read_token=cfg.read_token,
        admin_token=None,
        timeout_sec=cfg.timeout_sec,
    )
    client = CockpitClient(cfg_no_admin, cache_dir=tmp_cache)
    with pytest.raises(PermissionError):
        client.drop_kill("r1")


def test_http_404_does_not_trip_breaker(cfg, tmp_cache):
    """HTTP 4xx é erro do caller, não do servidor — não conta no breaker."""
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    err = urllib.error.HTTPError(
        "http://localhost:8787/v1/runs", 404, "not found", hdrs={}, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=err):
        for _ in range(3):
            with pytest.raises(urllib.error.HTTPError):
                client.list_runs()
            assert client._consecutive_failures == 0
        # 4ª chamada: ainda HTTPError, NÃO CircuitOpen
        with pytest.raises(urllib.error.HTTPError):
            client.list_runs()
        assert client._consecutive_failures == 0


def test_http_500_trips_breaker(cfg, tmp_cache):
    """HTTP 5xx indica problema no servidor — conta no breaker."""
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    err = urllib.error.HTTPError(
        "http://localhost:8787/v1/runs", 500, "server error", hdrs={}, fp=None
    )
    with patch("urllib.request.urlopen", side_effect=err):
        for _ in range(3):
            with pytest.raises(urllib.error.HTTPError):
                client.list_runs()
        # 4ª chamada: breaker aberto
        with pytest.raises(CircuitOpen):
            client.list_runs()


def test_half_open_probe_failure_reopens(cfg, tmp_cache):
    """Half-open: 1 probe; se falhar, breaker reabre imediatamente."""
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    # Simula breaker que acabou de expirar
    client._breaker_open_until = time.time() - 1
    client._consecutive_failures = 3
    with patch("urllib.request.urlopen", side_effect=OSError("conn refused")):
        # Primeira chamada: probe do half-open — falha com OSError
        with pytest.raises(OSError):
            client.list_runs()
        # Segunda chamada: breaker deve estar aberto de novo (probe falhou)
        with pytest.raises(CircuitOpen):
            client.list_runs()
