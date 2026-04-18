"""Shared HTTP transport primitives for infrastructure code."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import time

import requests


@dataclass(frozen=True)
class RetryPolicy:
    statuses: tuple[int, ...] = ()
    attempts: int = 1
    sleep_seconds: float = 0.0


@dataclass(frozen=True)
class RequestSpec:
    method: str
    url: str
    params: dict[str, Any] | None = None
    json: Any = None
    headers: dict[str, str] | None = None
    timeout: float | tuple[float, float] | None = None


@dataclass
class TransportClient:
    session: requests.Session = field(default_factory=requests.Session)

    def request(self, spec: RequestSpec, retry: RetryPolicy | None = None) -> requests.Response:
        policy = retry or RetryPolicy()
        attempt = 0
        while True:
            attempt += 1
            resp = self.session.request(
                method=spec.method,
                url=spec.url,
                params=spec.params,
                json=spec.json,
                headers=spec.headers,
                timeout=spec.timeout,
            )
            if resp.status_code not in policy.statuses or attempt >= max(policy.attempts, 1):
                return resp
            if policy.sleep_seconds > 0:
                time.sleep(policy.sleep_seconds)


def request_json(spec: RequestSpec, retry: RetryPolicy | None = None) -> Any:
    client = TransportClient()
    resp = client.request(spec, retry=retry)
    resp.raise_for_status()
    return resp.json()
