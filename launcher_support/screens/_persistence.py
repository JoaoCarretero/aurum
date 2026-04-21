"""Persistence for screen-switch metrics.

configure_screen_logging(log_dir) — idempotent attach of RotatingFileHandler
  to `aurum.launcher.screens` logger. Returns the log file path.
dump_screen_metrics(log_dir, *, reason) — snapshot runtime_health,
  filter `screen.*` keys, write JSON; returns path or None.

The in-process `runtime_health` counter dies with the launcher; these
helpers turn it into durable artifacts for data-driven migration
decisions (see docs/architecture/screen_manager.md section "Quando
migrar próxima tela").
"""
from __future__ import annotations

import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.paths import DATA_DIR
from core.ops.health import runtime_health
from core.ops.persistence import atomic_write_json
from launcher_support.screens._metrics import snapshot_timings

_LOGGER_NAME = "aurum.launcher.screens"
_HANDLER_TAG = "aurum.screen_file"
_DEFAULT_LOG_DIR = DATA_DIR / ".launcher_logs"


def _resolve_log_dir(log_dir: Path | None) -> Path:
    target = Path(log_dir) if log_dir is not None else _DEFAULT_LOG_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def configure_screen_logging(log_dir: Path | None = None) -> Path:
    """Attach a RotatingFileHandler to `aurum.launcher.screens`.

    Idempotent — if a handler tagged with `_HANDLER_TAG` already exists
    on the logger, no new handler is added. Returns the path of the log
    file either way.
    """
    directory = _resolve_log_dir(log_dir)
    log_path = directory / "screens.log"
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)

    for handler in logger.handlers:
        if getattr(handler, "_aurum_tag", None) == _HANDLER_TAG:
            return log_path

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler._aurum_tag = _HANDLER_TAG  # type: ignore[attr-defined]
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    logger.addHandler(file_handler)
    return log_path


def _filter_screen_counters(counters: dict[str, int]) -> dict[str, int]:
    return {k: v for k, v in counters.items() if k.startswith("screen.")}


def dump_screen_metrics(
    log_dir: Path | None = None,
    *,
    reason: str = "quit",
) -> Path | None:
    """Write runtime_health screen counters to timestamped JSON.

    Returns the path written, or None if no `screen.*` counters exist or
    IO failed. Swallows OSError — shutdown path must never raise from
    measurement code.
    """
    filtered = _filter_screen_counters(runtime_health.snapshot())
    if not filtered:
        return None
    try:
        directory = _resolve_log_dir(log_dir)
    except OSError:
        return None
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    path = directory / f"screen_metrics_{stamp}.json"
    payload = {
        "schema_version": "screen_metrics.v1",
        "reason": reason,
        "captured_at": stamp,
        "counters": filtered,
    }
    timings = snapshot_timings()
    if timings:
        payload["timings_ms"] = timings
    try:
        atomic_write_json(path, payload)
    except OSError:
        return None
    return path
