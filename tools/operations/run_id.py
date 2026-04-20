"""RUN_ID composition helpers for multi-instance runs.

Spec: docs/superpowers/specs/2026-04-20-multi-instance-runs-design.md

A RUN_ID encodes the start timestamp (seconds precision) and, optionally,
a human-chosen label. Examples:
  - "2026-04-20_165432"              (no label)
  - "2026-04-20_165432_kelly5-10k"   (with label)

Labels are operator-facing metadata, sanitized to lowercase [a-z0-9-]
with max 40 chars so they're safe in filesystem paths and URLs.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

_LABEL_MAX_LEN = 40
_LABEL_ALLOWED = re.compile(r"[^a-z0-9-]+")


def sanitize_label(raw: str | None) -> str | None:
    """Reduce a raw label to [a-z0-9-]+, trim dashes, cap at 40 chars.

    Returns ``None`` if the label is empty, whitespace-only, or has no
    allowed characters after sanitization. Callers should treat ``None``
    as "no label — use unlabeled RUN_ID".
    """
    if raw is None:
        return None
    s = _LABEL_ALLOWED.sub("-", raw.lower())
    s = s.strip("-")
    if not s:
        return None
    if len(s) > _LABEL_MAX_LEN:
        s = s[:_LABEL_MAX_LEN].rstrip("-")
    return s or None


def build_run_id(
    ts: datetime | None = None,
    label: str | None = None,
) -> str:
    """Compose a RUN_ID from timestamp (YYYY-MM-DD_HHMMSS) + optional label.

    - ``ts=None`` defaults to ``datetime.now(timezone.utc)``.
    - Naive datetimes are accepted and rendered as-is (caller's
      responsibility to provide UTC if needed).
    - ``label`` is sanitized via :func:`sanitize_label`.
    """
    if ts is None:
        ts = datetime.now(timezone.utc)
    base = ts.strftime("%Y-%m-%d_%H%M%S")
    slug = sanitize_label(label)
    return f"{base}_{slug}" if slug else base
