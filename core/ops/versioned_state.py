"""Helpers for versioned support-state payloads.

These helpers are intended for non-sacred support artifacts only. They preserve
existing field contents and add a top-level ``schema_version`` tag so support
tools can evolve safely over time.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.persistence import atomic_write_json


def with_schema_version(payload: dict[str, Any], schema_version: str) -> dict[str, Any]:
    out = dict(payload)
    out["schema_version"] = schema_version
    return out


def write_versioned_json(path: str | Path, payload: dict[str, Any], schema_version: str, **json_kwargs: Any) -> Path:
    return atomic_write_json(path, with_schema_version(payload, schema_version), **json_kwargs)


def read_versioned_json(path: str | Path, default: Any = None) -> dict[str, Any] | Any:
    p = Path(path)
    if not p.exists():
        return default
    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (json.JSONDecodeError, OSError):
        return default


def schema_version_of(payload: Any) -> str | None:
    if isinstance(payload, dict):
        sv = payload.get("schema_version")
        return str(sv) if sv is not None else None
    return None
