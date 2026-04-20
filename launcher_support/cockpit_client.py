"""Typed HTTP client para o Aurum Cockpit API.

Zero dependências externas (usa urllib.request stdlib). Circuit breaker
fecha o canal após 3 falhas consecutivas; reabre após 300s. Cache local
em cache_dir preserva último estado conhecido pra fallback offline.

Uso típico (singleton no launcher):

    cfg = CockpitConfig(base_url="http://localhost:8787",
                        read_token="...", admin_token="...")
    client = CockpitClient(cfg, cache_dir=Path("data/.cockpit_cache"))
    for run in client.list_runs():
        ...
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CockpitConfig:
    base_url: str
    read_token: str
    admin_token: str | None = None
    timeout_sec: float = 5.0
    poll_interval_sec: float = 5.0


class CircuitOpen(RuntimeError):
    """Raised quando o breaker tá aberto — caller deve usar cache."""


@dataclass
class CockpitClient:
    cfg: CockpitConfig
    cache_dir: Path
    _consecutive_failures: int = 0
    _breaker_open_until: float = 0.0
    _half_open_probe: bool = False
    _BREAKER_THRESHOLD: int = 3
    _BREAKER_TIMEOUT_SEC: float = 300.0

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ─── Public API ────────────────────────────────────────────

    def healthz(self) -> dict:
        return self._get("/v1/healthz", auth=False)

    def list_runs(self) -> list[dict]:
        runs = self._get("/v1/runs")
        self._save_cache("runs.json", runs)
        return runs

    def get_run(self, run_id: str) -> dict:
        data = self._get(f"/v1/runs/{run_id}")
        self._save_cache(f"run_{run_id}.json", data)
        return data

    def get_heartbeat(self, run_id: str) -> dict:
        hb = self._get(f"/v1/runs/{run_id}/heartbeat")
        self._save_cache(f"heartbeat_{run_id}.json", hb)
        return hb

    def get_trades(self, run_id: str, limit: int = 50,
                   since: str | None = None) -> dict:
        qs = f"?limit={limit}"
        if since:
            qs += f"&since={since}"
        return self._get(f"/v1/runs/{run_id}/trades{qs}")

    def drop_kill(self, run_id: str) -> dict:
        if not self.cfg.admin_token:
            raise PermissionError("admin_token não configurado em CockpitConfig")
        return self._post(f"/v1/runs/{run_id}/kill", admin=True)

    def latest_run(self, engine: str,
                   mode: str | None = None) -> dict | None:
        """Most recent summary for (engine, mode). When `mode` is None,
        matches any mode. The API returns runs sorted by mtime DESC, so
        the first match is the freshest.

        Without the mode filter, a paper run could shadow (heh) a shadow
        run on panels that assume mode=shadow — e.g. the shadow poller
        would end up pointing at the paper run in the launcher.
        """
        try:
            runs = self.list_runs()
        except (OSError, CircuitOpen, urllib.error.URLError):
            runs = self._load_cache("runs.json") or []
        for r in runs:
            if r.get("engine") != engine:
                continue
            if mode is not None and r.get("mode") != mode:
                continue
            return r
        return None

    def active_runs_for(self, engine: str,
                        mode: str | None = None) -> list[dict]:
        """All RUNNING runs matching (engine, mode), sorted started_at DESC.

        Counterpart to :meth:`latest_run` for multi-instance UIs — returns
        every concurrent run so the operator can pick which one to
        inspect. Stopped and failed runs are excluded. Falls back to the
        disk cache on network failure like other client methods.
        """
        try:
            runs = self.list_runs()
        except (OSError, CircuitOpen, urllib.error.URLError):
            runs = self._load_cache("runs.json") or []
        matches = [
            r for r in runs
            if r.get("engine") == engine
            and r.get("status") == "running"
            and (mode is None or r.get("mode") == mode)
        ]
        matches.sort(key=lambda r: r.get("started_at") or "", reverse=True)
        return matches

    # ─── Internals ─────────────────────────────────────────────

    def _check_breaker(self) -> None:
        now = time.time()
        if self._breaker_open_until > now:
            raise CircuitOpen(
                f"breaker open for {self._breaker_open_until - now:.0f}s more"
            )
        if self._breaker_open_until != 0.0 and self._breaker_open_until <= now:
            # Transition open → half-open: allow a single probe.
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0
            self._half_open_probe = True

    def _record_failure(self) -> None:
        if self._half_open_probe:
            # Probe falhou → reabre breaker imediatamente.
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

    def _request(self, path: str, method: str = "GET",
                 auth: bool = True, admin: bool = False) -> dict | list:
        self._check_breaker()
        url = self.cfg.base_url.rstrip("/") + path
        headers = {}
        if auth:
            token = self.cfg.admin_token if admin else self.cfg.read_token
            if admin and not self.cfg.admin_token:
                raise PermissionError("admin_token required")
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body) if body else {}
                self._record_success()
                return result
        except urllib.error.HTTPError as exc:
            # 4xx é problema do caller (bad request / not found / unauthorized)
            # — não indica trouble no servidor/conexão. Não conta no breaker.
            # 5xx é problema do servidor — conta.
            if 500 <= exc.code < 600:
                self._record_failure()
            raise
        except (urllib.error.URLError, OSError, TimeoutError):
            self._record_failure()
            raise

    def _get(self, path: str, auth: bool = True) -> dict | list:
        return self._request(path, method="GET", auth=auth)

    def _post(self, path: str, admin: bool = False) -> dict:
        result = self._request(path, method="POST", auth=True, admin=admin)
        return result if isinstance(result, dict) else {}

    # ─── Cache ──────────────────────────────────────────────────

    def _save_cache(self, fname: str, data: object) -> None:
        try:
            (self.cache_dir / fname).write_text(json.dumps(data, default=str), encoding="utf-8")
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
