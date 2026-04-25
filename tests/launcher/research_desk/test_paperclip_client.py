"""Tests do client HTTP do Paperclip — sem network real.

Network e mockada via monkeypatch em urllib.request.urlopen.
Budget helpers + circuit breaker + cache sao testaveis sem Tk.
"""
from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from launcher_support.research_desk.paperclip_client import (
    CircuitOpen,
    PaperclipClient,
    PaperclipConfig,
    agent_budget_cents,
    agent_spent_cents,
    format_usd_from_cents,
    total_budget_cents,
)


@pytest.fixture
def client(tmp_path: Path) -> PaperclipClient:
    return PaperclipClient(
        cfg=PaperclipConfig(base_url="http://localhost:1", timeout_sec=0.5),
        cache_dir=tmp_path / "cache",
    )


# ── Budget helpers ────────────────────────────────────────────────


def test_agent_budget_cents_prefers_primary_field() -> None:
    agent = {"monthly_budget_cents": 1000, "budget_cents": 999}
    assert agent_budget_cents(agent) == 1000


def test_agent_budget_cents_falls_back() -> None:
    agent = {"budget_cents": 500}
    assert agent_budget_cents(agent) == 500
    agent2 = {"budget": 250}
    assert agent_budget_cents(agent2) == 250


def test_agent_budget_cents_missing_returns_zero() -> None:
    assert agent_budget_cents({}) == 0
    assert agent_spent_cents({}) == 0


def test_total_budget_aggregates() -> None:
    agents = [
        {"monthly_spent_cents": 500, "monthly_budget_cents": 1000},
        {"monthly_spent_cents": 250, "monthly_budget_cents": 800},
        {"spent": 10, "budget": 100},
    ]
    used, cap = total_budget_cents(agents)
    assert used == 500 + 250 + 10
    assert cap == 1000 + 800 + 100


def test_format_usd_from_cents() -> None:
    assert format_usd_from_cents(0) == "$0.00"
    assert format_usd_from_cents(1234) == "$12.34"
    assert format_usd_from_cents(50) == "$0.50"


# ── Circuit breaker ───────────────────────────────────────────────


def _url_error() -> urllib.error.URLError:
    return urllib.error.URLError(reason="conn refused")


def test_breaker_opens_after_three_failures(client: PaperclipClient) -> None:
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        for _ in range(3):
            with pytest.raises(urllib.error.URLError):
                client.health()
    # 4th call levanta CircuitOpen sem bater na rede
    with pytest.raises(CircuitOpen):
        client.health()


def test_is_online_swallows_errors(client: PaperclipClient) -> None:
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        assert client.is_online() is False
    # Com 3 falhas, breaker abriu — is_online continua retornando False
    # sem levantar CircuitOpen
    assert client.is_online() is False


def test_breaker_half_open_probe_recovers(client: PaperclipClient) -> None:
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        for _ in range(3):
            with pytest.raises(urllib.error.URLError):
                client.health()
    # simula timeout do breaker
    client._breaker_open_until = time.time() - 1.0  # noqa: SLF001

    # next call -> half-open probe; se suceder, breaker fecha
    fake_response = _FakeResponse(b'{"ok": true}')
    with patch("urllib.request.urlopen", return_value=fake_response):
        result = client.health()
    assert result == {"ok": True}
    assert client._consecutive_failures == 0  # noqa: SLF001


# ── Request mocking ───────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, body: bytes):
        self._buf = io.BytesIO(body)

    def read(self) -> bytes:
        return self._buf.read()

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._buf.close()


def test_list_agents_unwraps_list_payload(client: PaperclipClient) -> None:
    payload = [{"id": "a1", "monthly_spent_cents": 100}]
    with patch("urllib.request.urlopen",
               return_value=_FakeResponse(json.dumps(payload).encode())):
        agents = client.list_agents("cid")
    assert agents == payload
    # Cache populado
    cache_file = client.cache_dir / "agents_cid.json"
    assert cache_file.exists()
    assert json.loads(cache_file.read_text()) == payload


def test_list_agents_cached_fallback_when_offline(client: PaperclipClient) -> None:
    # Primeiro popula cache
    payload = [{"id": "a1"}]
    with patch("urllib.request.urlopen",
               return_value=_FakeResponse(json.dumps(payload).encode())):
        client.list_agents("cid")

    # Agora simula offline
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        agents = client.list_agents_cached("cid")
    assert agents == payload


def test_list_agents_cached_returns_empty_without_cache(client: PaperclipClient) -> None:
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        assert client.list_agents_cached("empty") == []


def test_create_issue_posts_json_body(client: PaperclipClient) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del timeout
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["body"] = req.data
        captured["headers"] = dict(req.headers)
        return _FakeResponse(b'{"id": "new-issue"}')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = client.create_issue("cid", {"title": "t", "description": "d"})

    assert out == {"id": "new-issue"}
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/companies/cid/issues")
    assert json.loads(captured["body"]) == {"title": "t", "description": "d"}
    assert captured["headers"].get("Content-type") == "application/json"


def test_health_parses_json(client: PaperclipClient) -> None:
    with patch(
        "urllib.request.urlopen",
        return_value=_FakeResponse(b'{"status": "ok", "uptime": 10}'),
    ):
        assert client.health() == {"status": "ok", "uptime": 10}


def test_cache_survives_missing_file(client: PaperclipClient) -> None:
    assert client._load_cache("missing.json") is None  # noqa: SLF001


def test_pause_agent_posts_to_pause_path(client: PaperclipClient) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del timeout
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        return _FakeResponse(b'{"paused": true}')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = client.pause_agent("agent-uuid-1")
    assert out == {"paused": True}
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/agents/agent-uuid-1/pause")


def test_list_heartbeat_runs_fetches_by_agent(client: PaperclipClient) -> None:
    captured: dict[str, Any] = {}
    payload = [{"id": "run1"}, {"id": "run2"}]

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del timeout
        captured["url"] = req.full_url
        return _FakeResponse(json.dumps(payload).encode())

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        runs = client.list_heartbeat_runs("agent-x", limit=10)
    assert runs == payload
    assert "agent_id=agent-x" in captured["url"]
    assert "limit=10" in captured["url"]


def test_list_heartbeat_runs_cached_fallback(client: PaperclipClient) -> None:
    payload = [{"id": "r1"}]
    with patch("urllib.request.urlopen",
               return_value=_FakeResponse(json.dumps(payload).encode())):
        client.list_heartbeat_runs_cached("agent-x")
    # Segunda chamada offline retorna cache
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        runs = client.list_heartbeat_runs_cached("agent-x")
    assert runs == payload


def test_list_heartbeat_runs_cached_empty_no_cache(client: PaperclipClient) -> None:
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        assert client.list_heartbeat_runs_cached("unknown") == []


def test_resume_agent_posts_to_resume_path(client: PaperclipClient) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del timeout
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        return _FakeResponse(b'{"paused": false}')

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        out = client.resume_agent("agent-uuid-2")
    assert out == {"paused": False}
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/api/agents/agent-uuid-2/resume")


def test_cache_save_invalid_dir_is_noop(tmp_path: Path) -> None:
    # Aponta cache_dir pra dentro de um arquivo pre-existente (invalido).
    # __post_init__ nao quebra, _save_cache tbm nao.
    broken = tmp_path / "blocker"
    broken.write_text("x")
    client = PaperclipClient(
        cfg=PaperclipConfig(),
        cache_dir=broken / "subdir",
    )
    # Nao levanta
    client._save_cache("x.json", {"a": 1})  # noqa: SLF001


# ── New behavior: client correctness (FASE B Block 2) ─────────────


def test_is_online_requires_status_ok(client: PaperclipClient) -> None:
    """`is_online` must distinguish a 200 with status=='ok' from a
    degraded server reporting 200 with status=='degraded'/'error'.

    Without this, a half-broken server flips the breaker back to
    closed via _record_success and the UI shows green pill while
    the API is actually serving stale or partial data.
    """
    # status=='ok' -> True
    with patch("urllib.request.urlopen",
               return_value=_FakeResponse(b'{"status":"ok","version":"1"}')):
        assert client.is_online() is True

    # status=='degraded' -> False
    with patch("urllib.request.urlopen",
               return_value=_FakeResponse(b'{"status":"degraded"}')):
        assert client.is_online() is False

    # status missing -> False
    with patch("urllib.request.urlopen",
               return_value=_FakeResponse(b'{"version":"1"}')):
        assert client.is_online() is False


def test_breaker_blocks_concurrent_half_open_probes(client: PaperclipClient) -> None:
    """When the breaker enters half-open, only ONE thread should be
    able to probe; all others must raise CircuitOpen until the probe
    resolves. Without this gate, every concurrent caller after timeout
    elapses hammers the server simultaneously.
    """
    # Trip breaker
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        for _ in range(3):
            with pytest.raises(urllib.error.URLError):
                client.health()
    # Force timeout elapsed
    client._breaker_open_until = time.time() - 1.0  # noqa: SLF001
    client._half_open_probe = False  # noqa: SLF001

    # Manually flip into "probe in flight" state (simulates the first
    # thread reserving the probe between _check_breaker and urlopen).
    with client._breaker_lock:  # noqa: SLF001
        client._half_open_probe = True  # noqa: SLF001

    # All other threads now raise CircuitOpen instead of probing
    with pytest.raises(CircuitOpen, match="half-open probe in flight"):
        client.health()


def test_atomic_cache_write_uses_tmp_then_rename(client: PaperclipClient) -> None:
    """_save_cache must write to .tmp then os.replace, never directly
    to the target file. Concurrent readers must never see a partially
    written JSON file.
    """
    import os as _os

    captured_writes: list[str] = []
    original_replace = _os.replace

    def tracking_replace(src: str, dst: str) -> None:
        captured_writes.append(f"replace({src} -> {dst})")
        return original_replace(src, dst)

    with patch("os.replace", side_effect=tracking_replace):
        client._save_cache("test.json", {"key": "value"})  # noqa: SLF001

    target = client.cache_dir / "test.json"
    tmp = client.cache_dir / "test.json.tmp"
    assert target.exists(), "target file should exist after rename"
    assert not tmp.exists(), "tmp file should be gone after rename"
    assert any("test.json.tmp" in w and "test.json" in w for w in captured_writes), (
        f"expected os.replace call with tmp -> target, got: {captured_writes}"
    )
    assert json.loads(target.read_text(encoding="utf-8")) == {"key": "value"}


def test_4xx_resets_breaker_does_not_open(client: PaperclipClient) -> None:
    """A flood of 4xx responses (caller-side errors, server is alive)
    must NOT open the breaker. Previously, _record_failure kept counter
    untouched on 4xx but the next URLError would tip it over the edge
    even though the server was healthy in between.
    """
    def http_404(*_a: Any, **_kw: Any) -> None:
        raise urllib.error.HTTPError(
            url="x", code=404, msg="not found", hdrs=None, fp=None,  # type: ignore[arg-type]
        )

    # 2 network failures -> counter at 2/3
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        for _ in range(2):
            with pytest.raises(urllib.error.URLError):
                client.health()
    assert client._consecutive_failures == 2  # noqa: SLF001

    # Now 3 x 404 (server is alive): counter must reset to 0
    with patch("urllib.request.urlopen", side_effect=http_404):
        for _ in range(3):
            with pytest.raises(urllib.error.HTTPError):
                client.get_agent("missing")
    assert client._consecutive_failures == 0, (  # noqa: SLF001
        "4xx should reset breaker counter — server is alive"
    )

    # Two more URLErrors should now NOT open the breaker (counter at 2)
    with patch("urllib.request.urlopen", side_effect=_url_error()):
        for _ in range(2):
            with pytest.raises(urllib.error.URLError):
                client.health()
    assert client._consecutive_failures == 2  # noqa: SLF001
    assert client._breaker_open_until == 0.0  # noqa: SLF001


def test_list_issues_url_encodes_status(client: PaperclipClient) -> None:
    """status query param must be URL-encoded — defends against future
    callers passing values with `&`, spaces, or special chars."""
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del timeout
        captured["url"] = req.full_url
        return _FakeResponse(b"[]")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.list_issues("cid", status="in progress&danger")

    assert "%20" in captured["url"] or "+" in captured["url"]
    assert "%26" in captured["url"]  # & encoded


def test_list_heartbeat_runs_url_encodes_agent_id(client: PaperclipClient) -> None:
    """agent_id query param must be URL-encoded via urlencode — catches
    any future caller passing a non-UUID with special characters."""
    captured: dict[str, Any] = {}

    def fake_urlopen(req: urllib.request.Request, timeout: float = 0) -> _FakeResponse:
        del timeout
        captured["url"] = req.full_url
        return _FakeResponse(b"[]")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        client.list_heartbeat_runs("agent with spaces", limit=5)

    # urlencode renders space as +
    assert "agent_id=agent+with+spaces" in captured["url"]
    assert "limit=5" in captured["url"]
