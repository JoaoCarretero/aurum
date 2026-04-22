"""Scan run directories for zombie heartbeats and alert via Telegram.

Background: cockpit_api.py:_effective_status already derives "stopped" for
runs whose heartbeat.json still says "running" but whose last_tick_at is
older than max(tick_sec * 3, 600s). The display is correct, but nobody
was getting actively notified — operator only saw the zombie on the
dashboard if they happened to look.

This tool closes that loop. Intended use: systemd timer or cron every
5 min on the VPS.

    */5 * * * * cd /srv/aurum.finance && python tools/maintenance/zombie_scanner.py

Mechanics:
  - Iterates every run_dir returned by core.shadow_contract.find_runs
  - For each heartbeat with status=running AND last_tick_at older than
    threshold, classifies as zombie
  - State file (data/.zombie_notified.json) tracks run_ids already
    notified → we alert once per transition, not every scan cycle
  - Sends one Telegram message per NEW zombie
  - Prunes state entries for run_ids whose heartbeat is gone (cleanup)

Exit codes:
  0   — scan completed (may or may not have fired alerts)
  1   — fatal error (keystore, filesystem)

Deliberately synchronous, no external deps beyond stdlib + existing
project imports. Safe to run concurrently with the runners it monitors
(read-only access to heartbeat.json; its state file is separate).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.risk.key_store import KeyStoreError, load_runtime_keys  # noqa: E402
from core.shadow_contract import Heartbeat, find_runs, load_heartbeat  # noqa: E402

log = logging.getLogger("zombie_scanner")

DEFAULT_DATA_ROOT = ROOT / "data"
STATE_FILENAME = ".zombie_notified.json"
# Mirrors cockpit_api._effective_status: tick_sec * 3 floored at 600s.
DEFAULT_STALENESS_FLOOR_SEC = 600


def _telegram_cfg() -> dict | None:
    try:
        data = load_runtime_keys()
    except KeyStoreError as exc:
        log.warning("keystore unreadable: %s", exc)
        return None
    tg = data.get("telegram") or {}
    token = tg.get("bot_token")
    chat_id = tg.get("chat_id")
    if not token or not chat_id:
        return None
    return {"token": str(token), "chat_id": str(chat_id)}


def _send_telegram(cfg: dict, text: str) -> bool:
    """Send a Telegram message. Returns True on success, False otherwise."""
    url = f"https://api.telegram.org/bot{cfg['token']}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": cfg["chat_id"],
        "text": text,
        "parse_mode": "HTML",
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            resp.read()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("telegram send failed: %s", exc)
        return False


def is_zombie(hb: Heartbeat, now: datetime, floor_sec: int) -> tuple[bool, float]:
    """Check if heartbeat qualifies as zombie. Returns (is_zombie, age_sec).

    A zombie has status=running but last_tick_at older than
    max(tick_sec * 3, floor_sec). Mirrors cockpit_api._effective_status.
    """
    if hb.status != "running" or hb.last_tick_at is None:
        return False, 0.0
    threshold = max((hb.tick_sec or 900) * 3, floor_sec)
    age = (now - hb.last_tick_at).total_seconds()
    return age > threshold, age


def load_state(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if isinstance(data, list):
        return {str(x) for x in data}
    return set()


def save_state(state_path: Path, notified: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    tmp.write_text(json.dumps(sorted(notified), indent=2), encoding="utf-8")
    tmp.replace(state_path)


def scan_once(
    data_root: Path,
    state_path: Path,
    *,
    floor_sec: int = DEFAULT_STALENESS_FLOOR_SEC,
    now: datetime | None = None,
    send_fn=None,
    live_run_ids: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Perform one scan pass. Returns (new_zombies, pruned_from_state).

    ``send_fn`` — callable(text: str) -> bool for testability; defaults to
    Telegram-via-keystore.
    """
    now = now or datetime.now(timezone.utc)
    already_notified = load_state(state_path)

    current_run_ids: set[str] = set()
    new_zombies: list[str] = []
    new_zombie_messages: list[str] = []

    for run_dir in find_runs(data_root):
        try:
            hb = load_heartbeat(run_dir)
        except Exception as exc:  # noqa: BLE001 — bad heartbeat ≠ zombie
            log.debug("skip %s: heartbeat unreadable (%s)", run_dir, exc)
            continue
        current_run_ids.add(hb.run_id)

        zombie, age = is_zombie(hb, now, floor_sec)
        if not zombie:
            continue
        if hb.run_id in already_notified:
            continue

        new_zombies.append(hb.run_id)
        label = getattr(hb, "label", None) or hb.run_id
        age_min = int(age // 60)
        msg = (
            f"<b>AURUM · ZOMBIE RUN</b>\n"
            f"run: <code>{hb.run_id}</code>\n"
            f"label: {label}\n"
            f"tick_sec: {hb.tick_sec or '?'}\n"
            f"idle: {age_min}min (threshold "
            f"{max((hb.tick_sec or 900) * 3, floor_sec) // 60}min)\n"
            f"last_tick_at: {hb.last_tick_at}"
        )
        new_zombie_messages.append(msg)

    # Prune state entries for runs that no longer exist on disk (directory
    # was archived/removed) OR that have recovered to non-running status.
    # Also prune runs whose heartbeat is now stopped — next time they
    # zombie, we want a fresh notification.
    if live_run_ids is None:
        live_run_ids = current_run_ids
    to_prune = already_notified - live_run_ids
    pruned: list[str] = sorted(to_prune)
    if to_prune:
        already_notified -= to_prune

    # Actually send. If send_fn is None we try Telegram; if it's provided
    # (tests) we call it directly.
    if send_fn is None:
        cfg = _telegram_cfg()
        def _send(text: str) -> bool:
            if cfg is None:
                log.info("telegram cfg missing — alert suppressed: %s",
                         text.splitlines()[0])
                return False
            return _send_telegram(cfg, text)
        send_fn = _send

    for run_id, msg in zip(new_zombies, new_zombie_messages):
        sent = send_fn(msg)
        if sent:
            already_notified.add(run_id)
            log.info("zombie alerted: %s", run_id)
        else:
            log.warning("zombie NOT alerted (send failed): %s", run_id)

    save_state(state_path, already_notified)
    return new_zombies, pruned


def main(argv: Iterable[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT),
                        help=f"Default: {DEFAULT_DATA_ROOT}")
    parser.add_argument("--state-file", default=None,
                        help=f"Default: <data_root>/{STATE_FILENAME}")
    parser.add_argument("--floor-sec", type=int, default=DEFAULT_STALENESS_FLOOR_SEC,
                        help="Minimum staleness threshold in seconds. Default 600.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    data_root = Path(args.data_root)
    state_path = (Path(args.state_file) if args.state_file
                  else data_root / STATE_FILENAME)
    new_zombies, pruned = scan_once(
        data_root, state_path, floor_sec=args.floor_sec,
    )
    log.info("scan complete: new=%d pruned=%d",
             len(new_zombies), len(pruned))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
