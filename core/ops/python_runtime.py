from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def preferred_python_executable() -> str:
    """Return the best available Python executable for operational runners.

    The launcher process may be running under a bundled interpreter that is
    good enough for Tk but not for the live/paper/shadow runtime. Prefer the
    user-installed Python first, then fall back to the current interpreter.
    """
    candidates: list[Path] = []

    env_path = os.getenv("AURUM_PYTHON_EXE", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())

    if sys.platform == "win32":
        candidates.append(Path.home() / "AppData" / "Local" / "Python" / "bin" / "python.exe")
        candidates.append(Path.home() / "AppData" / "Local" / "Python" / "python.exe")

    if sys.executable:
        candidates.append(Path(sys.executable))

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except OSError:
            resolved = str(candidate)
        key = resolved.lower()
        if key in seen:
            continue
        seen.add(key)
        if Path(resolved).exists():
            return resolved

    return sys.executable or "python"
