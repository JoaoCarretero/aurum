"""Metrics emission for screen switches.

emit_switch_metric(name, phase, ms) — logs timing + increments counter.
@timed_legacy_switch(name) — decorator for instrumenting legacy
destroy+rebuild call sites in launcher.py (used in Task 9).
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from core.ops.health import runtime_health

_log = logging.getLogger("aurum.launcher.screens")

_ALLOWED_PHASES = {"first_visit", "reentry", "legacy_rebuild"}


def emit_switch_metric(name: str, phase: str, *, ms: float) -> None:
    """Record a screen switch metric.

    - Increments counter ``screen.<name>.<phase>`` in runtime_health.
    - Emits INFO log via logger ``aurum.launcher.screens``.
    """
    if phase not in _ALLOWED_PHASES:
        raise ValueError(
            f"phase must be one of {sorted(_ALLOWED_PHASES)}, got {phase!r}"
        )
    runtime_health.record(f"screen.{name}.{phase}")
    _log.info(
        "event=screen_switch name=%s phase=%s ms=%.1f",
        name, phase, ms,
    )


def timed_legacy_switch(name: str) -> Callable:
    """Decorator for legacy destroy+rebuild sites in launcher.py.

    Usage:
        @timed_legacy_switch("results")
        def _render_results(self): ...

    Measures wall-time and emits as phase="legacy_rebuild". Exceptions in
    the wrapped function re-raise after the metric is recorded.
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                ms = (time.perf_counter() - t0) * 1000.0
                emit_switch_metric(name, "legacy_rebuild", ms=ms)
        return wrapper
    return decorator
