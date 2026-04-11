"""AURUM — filesystem utilities.

Tiny module with the non-trivial filesystem operations the rest of the
project needs. Kept dependency-free so anything can import from it.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path


def robust_rmtree(target: Path, retries: int = 3, pause: float = 0.5) -> bool:
    """Remove a directory tree, robust against Windows + OneDrive locks.

    OneDrive keeps handles on freshly-closed files and directories for a
    brief window while it syncs. A plain shutil.rmtree can hit PermissionError
    (WinError 5 "Acesso negado") even on empty directories the current user
    owns. This helper tries, in order:

    1. shutil.rmtree with an onexc / onerror handler that clears the
       read-only bit and retries the individual failing path.
    2. If the tree still exists, falls back to ``cmd /c rmdir /s /q`` on
       Windows — native rmdir bypasses some Python file-handle quirks.
    3. Retries the whole attempt up to ``retries`` times with a pause
       between attempts to let OneDrive catch up.

    Returns True on success, False if the tree still exists after every
    attempt. **Never raises** — the caller decides how to surface the
    failure (log, retry, tombstone, etc).

    Used by the launcher backtest-delete flow and by
    tools/reconcile_runs.py.
    """

    def _on_exc(func, path, exc_info):  # type: ignore[no-untyped-def]
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    for attempt in range(retries):
        if not target.exists():
            return True
        try:
            shutil.rmtree(target, onexc=_on_exc)  # py 3.12+ signature
        except TypeError:
            # Older Python — onerror kwarg instead of onexc
            shutil.rmtree(target, onerror=lambda f, p, e: _on_exc(f, p, e))
        except (OSError, PermissionError):
            pass
        if not target.exists():
            return True
        # Fallback: native rmdir. Some Python file-handle races on Windows
        # disappear when the OS-native command takes the lock instead.
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", str(target)],
                    check=False, capture_output=True, timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not target.exists():
            return True
        time.sleep(pause)

    return not target.exists()
