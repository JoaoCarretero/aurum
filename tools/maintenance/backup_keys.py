"""AURUM - defensive backup of config/keys.json.

Creates timestamped copies outside the repo so a future agent that
silently overwrites keys.json does not destroy recovery options.
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
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while chunk := fh.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_backup(backup_dir: Path) -> Path | None:
    if not backup_dir.exists():
        return None
    candidates = sorted(
        backup_dir.glob("keys.json.*.bak"),
        key=lambda p: p.name,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _rotate(backup_dir: Path, keep: int) -> None:
    backups = sorted(
        backup_dir.glob("keys.json.*.bak"),
        key=lambda p: p.name,
        reverse=True,
    )
    for old in backups[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def run_backup(
    *,
    keys_path: Path = KEYS_PATH,
    backup_dir: Path | None = None,
    keep: int = 20,
    now: datetime | None = None,
) -> tuple[int, Path | None, bool]:
    if not keys_path.exists():
        return 1, None, False

    backup_dir = backup_dir or _default_backup_dir()
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return 2, None, False

    latest = _latest_backup(backup_dir)
    if latest is not None and _hash_file(keys_path) == _hash_file(latest):
        _rotate(backup_dir, keep)
        return 0, latest, True

    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    dest = backup_dir / f"keys.json.{stamp}.bak"
    shutil.copy2(keys_path, dest)
    _rotate(backup_dir, keep)
    return 0, dest, False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=int, default=20, help="Retain last N backups (default 20)")
    parser.add_argument("--dir", type=Path, default=None, help="Backup dir override")
    args = parser.parse_args()

    code, path, skipped = run_backup(backup_dir=args.dir, keep=args.keep)
    if code == 1:
        print(f"MISSING: {KEYS_PATH}", file=sys.stderr)
        return 1
    if code == 2:
        print("backup dir unwritable", file=sys.stderr)
        return 2
    if skipped and path is not None:
        print(f"SKIP - identical to latest backup ({path.name})")
    elif path is not None and path.exists() and path.stat().st_size > 0:
        print(f"OK - backup -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
