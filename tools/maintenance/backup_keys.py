"""AURUM — defensive backup of config/keys.json.

Creates timestamped copies outside the repo so a future agent that
silently overwrites keys.json does NOT destroy recovery options. Runs
on-demand (idempotent, cheap) and from the launcher bootstrap.

Backup location priority:
  1. $AURUM_KEYS_BACKUP_DIR       (if set)
  2. ~/.aurum-backups/keys/       (default, outside the OneDrive synced repo)

Retention:
  - Keeps the N most recent backups (default: 20) — rotates oldest first.
  - Every backup is a plain copy; if you want encryption-at-rest use
    tools/maintenance/encrypt_keys.py separately.

Exit codes:
    0 — backup written (or was already identical to latest)
    1 — source keys.json missing
    2 — backup dir unwritable
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KEYS_PATH = ROOT / "config" / "keys.json"


def _default_backup_dir() -> Path:
    override = os.environ.get("AURUM_KEYS_BACKUP_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".aurum-backups" / "keys"


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _latest_backup(backup_dir: Path) -> Path | None:
    if not backup_dir.exists():
        return None
    candidates = sorted(backup_dir.glob("keys.json.*.bak"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True)
    return candidates[0] if candidates else None


def _rotate(backup_dir: Path, keep: int) -> None:
    backups = sorted(backup_dir.glob("keys.json.*.bak"),
                     key=lambda p: p.stat().st_mtime,
                     reverse=True)
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=20,
                        help="Retain last N backups (default 20)")
    parser.add_argument("--dir", type=Path, default=None,
                        help="Backup dir override")
    args = parser.parse_args()

    if not KEYS_PATH.exists():
        print(f"MISSING: {KEYS_PATH}", file=sys.stderr)
        return 1

    backup_dir = args.dir or _default_backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"backup dir unwritable: {exc}", file=sys.stderr)
        return 2

    # Skip if identical to latest backup (no churn)
    latest = _latest_backup(backup_dir)
    if latest is not None:
        if _hash_file(KEYS_PATH) == _hash_file(latest):
            print(f"SKIP — identical to latest backup ({latest.name})")
            return 0

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dest = backup_dir / f"keys.json.{stamp}.bak"
    shutil.copy2(KEYS_PATH, dest)
    _rotate(backup_dir, args.keep)
    print(f"OK — backup -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
