"""Minimal launcher audio feedback helpers.

Default behavior is enabled and dependency-free:
  - Windows: prefers winsound.MessageBeep
  - Fallback: uses Tk bell() when a widget is available

Set AURUM_AUDIO=0/OFF/FALSE to disable audio feedback.
"""
from __future__ import annotations

import os
from typing import Any

try:
    import winsound  # type: ignore
except Exception:  # pragma: no cover - platform dependent
    winsound = None

_DISABLED = {"0", "OFF", "FALSE", "NO"}


def audio_enabled() -> bool:
    raw = str(os.getenv("AURUM_AUDIO", "1")).strip().upper()
    return raw not in _DISABLED


def notify(widget: Any = None, *, error: bool = False) -> bool:
    """Emit a short operator feedback sound.

    Returns True when a backend accepted the request, False otherwise.
    Never raises.
    """
    if not audio_enabled():
        return False
    if _winsound_notify(error=error):
        return True
    return _bell_notify(widget)


def _winsound_notify(*, error: bool) -> bool:
    if winsound is None:
        return False
    try:
        tone = winsound.MB_ICONHAND if error else winsound.MB_OK
        winsound.MessageBeep(tone)
        return True
    except Exception:
        return False


def _bell_notify(widget: Any) -> bool:
    if widget is None:
        return False
    bell = getattr(widget, "bell", None)
    if bell is None:
        return False
    try:
        bell()
        return True
    except Exception:
        return False
