"""HTTP client tipado pro Paperclip API (http://127.0.0.1:3100).

Zero deps externas — usa urllib.request da stdlib, espelhando o padrao
de launcher_support/cockpit_client.py (para consistencia na casa).

Paperclip opera em modo local_trusted: sem token, rede 127.0.0.1 so.
Circuit breaker evita floodar requests quando o server ta offline
(3 falhas -> 300s fechado; probe de reabertura automatico). Cache em
disco preserva ultimo snapshot conhecido pra fallback offline do UI.

Uso:

    cfg = PaperclipConfig(base_url="http://127.0.0.1:3100")
    client = PaperclipClient(cfg, cache_dir=Path("data/.paperclip_cache"))
    if client.is_online():
        agents = client.list_agents(company_id)

API mapeada (subset necessario nos sprints 1-3):
  health                 GET  /api/health
  list_agents            GET  /api/companies/{cid}/agents
  get_agent              GET  /api/agents/{aid}
  pause_agent / resume   POST /api/agents/{aid}/pause | /resume
  list_issues            GET  /api/companies/{cid}/issues
  create_issue           POST /api/companies/{cid}/issues
  get_issue              GET  /api/issues/{iid}
  patch_issue            PATCH /api/issues/{iid}
  list_comments          GET  /api/issues/{iid}/comments
  create_comment         POST /api/issues/{iid}/comments
  get_heartbeat_run      GET  /api/heartbeat-runs/{rid}

Sprint 1 usa: health, list_agents, list_issues, create_issue.
Sprints 2-3 adicionam os demais.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PaperclipConfig:
    base_url: str = "http://127.0.0.1:3100"
    timeout_sec: float = 5.0
    poll_interval_sec: float = 5.0


class CircuitOpen(RuntimeError):
    """Raised quando o breaker ta aberto — caller deve usar cache / stub."""


@dataclass
class PaperclipClient:
    cfg: PaperclipConfig = field(default_factory=PaperclipConfig)
    cache_dir: Path = field(default_factory=lambda: Path("data/.paperclip_cache"))
    _consecutive_failures: int = 0
    _breaker_open_until: float = 0.0
    _half_open_probe: bool = False
    _BREAKER_THRESHOLD: int = 3
    _BREAKER_TIMEOUT_SEC: float = 300.0

    def __post_init__(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            # Ambiente read-only — cache vira no-op mas o client funciona.
            pass

    # ── Public API ────────────────────────────────────────────────

    def is_online(self) -> bool:
        """True se health check passa agora. Swallow de todos os erros —
        nao dispara CircuitOpen pra cima; o caller so quer um bool."""
        try:
            self.health()
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                TimeoutError, CircuitOpen, json.JSONDecodeError):
            return False

    def health(self) -> dict:
        """GET /api/health. Levanta em network error ou HTTP != 2xx."""
        data = self._get("/api/health")
        return data if isinstance(data, dict) else {"ok": True}

    def list_agents(self, company_id: str) -> list[dict]:
        """GET /api/companies/{cid}/agents. Cache em agents_{cid}.json."""
        data = self._get(f"/api/companies/{company_id}/agents")
        agents = data if isinstance(data, list) else data.get("agents", [])
        self._save_cache(f"agents_{company_id}.json", agents)
        return agents

    def list_agents_cached(self, company_id: str) -> list[dict]:
        """Retorna live se possivel, cache se offline, [] se nada."""
        try:
            return self.list_agents(company_id)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                TimeoutError, CircuitOpen):
            cached = self._load_cache(f"agents_{company_id}.json")
            return cached if isinstance(cached, list) else []

    def get_agent(self, agent_id: str) -> dict:
        data = self._get(f"/api/agents/{agent_id}")
        return data if isinstance(data, dict) else {}

    def pause_agent(self, agent_id: str) -> dict:
        return self._post(f"/api/agents/{agent_id}/pause")

    def resume_agent(self, agent_id: str) -> dict:
        return self._post(f"/api/agents/{agent_id}/resume")

    def list_issues(self, company_id: str,
                    status: str | None = None) -> list[dict]:
        qs = f"?status={status}" if status else ""
        data = self._get(f"/api/companies/{company_id}/issues{qs}")
        issues = data if isinstance(data, list) else data.get("issues", [])
        self._save_cache(f"issues_{company_id}.json", issues)
        return issues

    def list_issues_cached(self, company_id: str,
                           status: str | None = None) -> list[dict]:
        try:
            return self.list_issues(company_id, status)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                TimeoutError, CircuitOpen):
            cached = self._load_cache(f"issues_{company_id}.json")
            return cached if isinstance(cached, list) else []

    def create_issue(self, company_id: str, payload: dict) -> dict:
        return self._post(f"/api/companies/{company_id}/issues", body=payload)

    def get_issue(self, issue_id: str) -> dict:
        data = self._get(f"/api/issues/{issue_id}")
        return data if isinstance(data, dict) else {}

    def patch_issue(self, issue_id: str, payload: dict) -> dict:
        return self._request(
            f"/api/issues/{issue_id}", method="PATCH", body=payload,
        )  # type: ignore[return-value]

    def list_comments(self, issue_id: str) -> list[dict]:
        data = self._get(f"/api/issues/{issue_id}/comments")
        return data if isinstance(data, list) else data.get("comments", [])

    def create_comment(self, issue_id: str, payload: dict) -> dict:
        return self._post(f"/api/issues/{issue_id}/comments", body=payload)

    def get_heartbeat_run(self, run_id: str) -> dict:
        data = self._get(f"/api/heartbeat-runs/{run_id}")
        return data if isinstance(data, dict) else {}

    # ── Circuit breaker ───────────────────────────────────────────

    def _check_breaker(self) -> None:
        now = time.time()
        if self._breaker_open_until > now:
            raise CircuitOpen(
                f"breaker open for {self._breaker_open_until - now:.0f}s more"
            )
        if self._breaker_open_until != 0.0 and self._breaker_open_until <= now:
            # open -> half-open: libera um probe
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0
            self._half_open_probe = True

    def _record_failure(self) -> None:
        if self._half_open_probe:
            self._half_open_probe = False
            self._consecutive_failures = self._BREAKER_THRESHOLD
            self._breaker_open_until = time.time() + self._BREAKER_TIMEOUT_SEC
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._BREAKER_THRESHOLD:
            self._breaker_open_until = time.time() + self._BREAKER_TIMEOUT_SEC

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0
        self._half_open_probe = False

    # ── Transport ─────────────────────────────────────────────────

    def _request(self, path: str, method: str = "GET",
                 body: Any | None = None) -> dict | list:
        self._check_breaker()
        url = self.cfg.base_url.rstrip("/") + path
        headers = {"Accept": "application/json"}
        data: bytes | None = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_sec) as resp:
                raw = resp.read().decode("utf-8")
                result = json.loads(raw) if raw else {}
                self._record_success()
                return result
        except urllib.error.HTTPError as exc:
            # 5xx conta; 4xx eh culpa do caller, nao do server
            if 500 <= exc.code < 600:
                self._record_failure()
            raise
        except (urllib.error.URLError, OSError, TimeoutError):
            self._record_failure()
            raise

    def _get(self, path: str) -> dict | list:
        return self._request(path, method="GET")

    def _post(self, path: str, body: dict | None = None) -> dict:
        result = self._request(path, method="POST", body=body or {})
        return result if isinstance(result, dict) else {}

    # ── Cache ─────────────────────────────────────────────────────

    def _save_cache(self, fname: str, data: object) -> None:
        try:
            (self.cache_dir / fname).write_text(
                json.dumps(data, default=str), encoding="utf-8",
            )
        except OSError:
            pass

    def _load_cache(self, fname: str) -> object | None:
        path = self.cache_dir / fname
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


# ── Budget aggregation helpers ────────────────────────────────────
# Paperclip retorna cada agente com shape aproximado:
#   { "id": ..., "name": ..., "paused": bool, "status": "idle"|...,
#     "monthly_budget_cents": int, "monthly_spent_cents": int,
#     "current_issue": {...} | None, ... }
# Os nomes de campo podem variar entre versoes; os helpers abaixo sao
# tolerantes: retornam 0 quando campos faltam, sem explodir a UI.

def _coalesce_cents(agent: dict, *keys: str) -> int:
    for k in keys:
        v = agent.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def agent_budget_cents(agent: dict) -> int:
    return _coalesce_cents(agent, "monthly_budget_cents", "budget_cents", "budget")


def agent_spent_cents(agent: dict) -> int:
    return _coalesce_cents(
        agent, "monthly_spent_cents", "spent_cents", "spent", "cost_cents",
    )


def total_budget_cents(agents: list[dict]) -> tuple[int, int]:
    """(used_cents, cap_cents) agregados pelos 4 agentes."""
    used = sum(agent_spent_cents(a) for a in agents)
    cap = sum(agent_budget_cents(a) for a in agents)
    return used, cap


def format_usd_from_cents(cents: int) -> str:
    return f"${cents / 100.0:.2f}"
