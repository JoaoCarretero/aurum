"""Support-only helpers for Phase C real-input capture.

These helpers are intentionally generic and non-invasive. They do not hook into
any sacred path by themselves; they only provide a stable, versioned way to
persist authentic runtime payloads once a support-only instrumentation point is
chosen.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.persistence import atomic_write_json
from core.versioned_state import with_schema_version


PHASE_C_CAPTURE_SCHEMA_VERSION = "phase_c_capture.v1"
PHASE_C_MANIFEST_SCHEMA_VERSION = "phase_c_capture_manifest.v1"
_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CAPTURE_DIR = _ROOT / "tests" / "fixtures" / "phase_c" / "captures"
_DEFAULT_MANIFEST = _ROOT / "tests" / "fixtures" / "phase_c" / "capture_manifest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture_envelope(
    *,
    surface: str,
    fixture_name: str,
    payload: Any,
    source: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    return with_schema_version(
        {
            "captured_at": _utc_now(),
            "surface": surface,
            "fixture_name": fixture_name,
            "source": source or {},
            "notes": notes,
            "payload": payload,
        },
        PHASE_C_CAPTURE_SCHEMA_VERSION,
    )


def write_capture(
    *,
    surface: str,
    fixture_name: str,
    payload: Any,
    source: dict[str, Any] | None = None,
    notes: str = "",
    capture_dir: str | Path | None = None,
) -> Path:
    base = Path(capture_dir) if capture_dir is not None else _DEFAULT_CAPTURE_DIR
    path = base / surface / f"{fixture_name}.json"
    envelope = capture_envelope(
        surface=surface,
        fixture_name=fixture_name,
        payload=payload,
        source=source,
        notes=notes,
    )
    return atomic_write_json(path, envelope)


def capture_manifest(
    entries: list[dict[str, Any]],
    *,
    generated_by: str = "manual",
) -> dict[str, Any]:
    return with_schema_version(
        {
            "generated_at": _utc_now(),
            "generated_by": generated_by,
            "entries": entries,
        },
        PHASE_C_MANIFEST_SCHEMA_VERSION,
    )


def write_capture_manifest(
    entries: list[dict[str, Any]],
    *,
    generated_by: str = "manual",
    path: str | Path | None = None,
) -> Path:
    manifest_path = Path(path) if path is not None else _DEFAULT_MANIFEST
    return atomic_write_json(
        manifest_path,
        capture_manifest(entries, generated_by=generated_by),
    )
