"""Cockpit API client + TTL cache.

Pure module: no tkinter. Callers schedule fetches on background threads
and dispatch UI updates via root.after(0, fn).

Contract:
- get_client() -> CockpitClient | None  (None if keys missing/placeholder)
- runs_cached() -> list[dict]  (cache hit if fresh, fetch + store if stale)
- force_refresh() -> list[dict]  (always fetches, updates cache)
- get_cached_runs() -> list[dict] | None  (read-only accessor, no I/O)
- is_loading() -> bool
- reset_cache_for_tests() -> None
- reset_client_for_tests() -> None

The loading flag is set by external orchestrator (view.py) before dispatching
a background refresh, and cleared on completion. runs_cached() does NOT
toggle it — it's synchronous.

Implementation notes:
- CockpitClient is instantiated via CockpitConfig dataclass (not kwargs).
- list_runs() is the correct method name on CockpitClient.
- Only positive client init is cached (None = retry on next call), matching
  the original _get_cockpit_client behaviour in engines_live_view.py.
- Catches KeyStoreError, ValueError, TypeError like the original.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from core.risk.key_store import KeyStoreError, load_runtime_keys

CACHE_TTL_S: float = 60.0

_CACHE_STATE: dict[str, Any] = {
    "ts": 0.0,
    "runs": None,
    "loading": False,
}
_CACHE_LOCK = threading.Lock()


def reset_cache_for_tests() -> None:
    """Test-only: clear cache state. Never call from production code."""
    with _CACHE_LOCK:
        _CACHE_STATE["ts"] = 0.0
        _CACHE_STATE["runs"] = None
        _CACHE_STATE["loading"] = False


def get_cached_runs() -> list[dict] | None:
    """Read-only accessor. Returns None if never populated."""
    with _CACHE_LOCK:
        return _CACHE_STATE["runs"]


def is_loading() -> bool:
    with _CACHE_LOCK:
        return bool(_CACHE_STATE["loading"])


def _fetch_runs_from_api() -> list[dict]:
    """Actual API call. Isolated for easy mocking in tests."""
    client = get_client()
    if client is None:
        return []
    try:
        runs = client.list_runs()
    except Exception:
        return []
    return runs or []


def runs_cached() -> list[dict]:
    """Returns cached runs if fresh, otherwise fetches + stores + returns."""
    now = time.time()
    with _CACHE_LOCK:
        age = now - _CACHE_STATE["ts"]
        if _CACHE_STATE["runs"] is not None and age < CACHE_TTL_S:
            return _CACHE_STATE["runs"]
    runs = _fetch_runs_from_api()
    with _CACHE_LOCK:
        _CACHE_STATE["runs"] = runs
        _CACHE_STATE["ts"] = time.time()
    return runs


def force_refresh() -> list[dict]:
    """Bypass TTL, always fetch. Store in cache."""
    runs = _fetch_runs_from_api()
    with _CACHE_LOCK:
        _CACHE_STATE["runs"] = runs
        _CACHE_STATE["ts"] = time.time()
    return runs


_CLIENT_SINGLETON: Any = None
_CLIENT_LOCK = threading.Lock()


def get_client():
    """Lazy-init CockpitClient from keys.json runtime key store.

    Returns None if cockpit_api block is missing, incomplete, or has
    placeholder values. Only caches a successful init — failed attempts
    leave singleton as None so the next call retries (e.g. transient
    read during boot).

    Replicates the logic from engines_live_view._get_cockpit_client.
    """
    global _CLIENT_SINGLETON
    with _CLIENT_LOCK:
        if _CLIENT_SINGLETON is not None:
            return _CLIENT_SINGLETON
        try:
            data = load_runtime_keys()
            block = (data or {}).get("cockpit_api")
            if not block or not block.get("base_url") or not block.get("read_token"):
                return None
            from launcher_support.cockpit_client import CockpitClient, CockpitConfig
            cfg = CockpitConfig(
                base_url=block["base_url"],
                read_token=block["read_token"],
                admin_token=block.get("admin_token"),
                timeout_sec=float(block.get("timeout_sec", 5.0)),
            )
            _CLIENT_SINGLETON = CockpitClient(cfg, cache_dir=Path("data/.cockpit_cache"))
            return _CLIENT_SINGLETON
        except (KeyStoreError, ValueError, TypeError):
            return None


def reset_client_for_tests() -> None:
    """Test-only: force re-init of client singleton."""
    global _CLIENT_SINGLETON
    with _CLIENT_LOCK:
        _CLIENT_SINGLETON = None
