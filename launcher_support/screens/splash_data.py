"""Pure data readers for SplashScreen. No Tkinter, no threading — testable headless.

Responsibilities:
  Implemented:
    - read last session entry from data/index.json

  Planned (upcoming tasks):
    - read engine roster (status + last Sharpe)
    - load/save splash cache (market pulse between openings)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _parse_timestamp(value) -> Optional[datetime]:
    """Parse ISO timestamp to a comparable UTC-naive datetime, or None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    # Normalize to naive UTC so aware and naive rows sort together without errors.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def read_last_session(index_path: Path) -> Optional[dict]:
    """Retorna o run mais recente do index.json, ou None se ausente/malformado."""
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(rows, list) or not rows:
        return None
    dated = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        parsed = _parse_timestamp(r.get("timestamp"))
        if parsed is None:
            continue
        dated.append((parsed, r))
    if not dated:
        return None
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return dated[0][1]
