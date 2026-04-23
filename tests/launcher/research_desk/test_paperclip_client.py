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
