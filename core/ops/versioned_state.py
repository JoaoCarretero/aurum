"""Helpers for versioned support-state payloads.

These helpers are intended for non-sacred support artifacts only. They preserve
existing field contents and add a top-level ``schema_version`` tag so support
tools can evolve safely over time.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.persistence import atomic_write_json


_READ_CACHE_TTL_S = 1.0
_READ_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}


def clear_read_cache() -> None:
    _READ_CACHE.clear()


def with_schema_version(payload: dict[str, Any], schema_version: str) -> dict[str, Any]:
    out = dict(payload)
    out["schema_version"] = schema_version
    return out


def write_versioned_json(path: str | Path, payload: dict[str, Any], schema_version: str, **json_kwargs: Any) -> Path:
    out = with_schema_version(payload, schema_version)
    dest = atomic_write_json(path, out, **json_kwargs)
    _READ_CACHE[str(Path(dest))] = (time.monotonic(), dict(out))
    return dest


def read_versioned_json(path: str | Path, default: Any = None) -> dict[str, Any] | Any:
    p = Path(path)
    cache_key = str(p)
    cached = _READ_CACHE.get(cache_key)
    now = time.monotonic()
    if cached and (now - cached[0]) < _READ_CACHE_TTL_S:
        return dict(cached[1]) if isinstance(cached[1], dict) else default
    if not p.exists():
        _READ_CACHE.pop(cache_key, None)
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _READ_CACHE[cache_key] = (now, dict(data))
            return data
        _READ_CACHE.pop(cache_key, None)
        return default
    except (json.JSONDecodeError, OSError):
        _READ_CACHE.pop(cache_key, None)
        return default


def schema_version_of(payload: Any) -> str | None:
    if isinstance(payload, dict):
        sv = payload.get("schema_version")
        return str(sv) if sv is not None else None
    return None
