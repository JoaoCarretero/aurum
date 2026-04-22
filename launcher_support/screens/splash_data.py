"""Pure data readers for SplashScreen. No Tkinter, no threading — testable headless.

Responsibilities:
  - read last session entry from data/index.json
  - read engine roster (status + last Sharpe)
  - load/save splash cache (market pulse between openings)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def read_last_session(index_path: Path) -> Optional[dict]:
    """Retorna o run mais recente do index.json, ou None se ausente/malformado."""
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(rows, list) or not rows:
        return None
    dated = [r for r in rows if isinstance(r, dict) and r.get("timestamp")]
    if not dated:
        return None
    dated.sort(key=lambda r: r["timestamp"], reverse=True)
    return dated[0]
