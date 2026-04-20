"""Keep-last-N retention for engine run dirs.

Usage:
    python tools/maintenance/archive_old_runs.py                       # dry-run, all engines
    python tools/maintenance/archive_old_runs.py --engine bridgewater  # just one
    python tools/maintenance/archive_old_runs.py --apply               # actually archive
    python tools/maintenance/archive_old_runs.py --keep 5              # override N (default 10)
"""
from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
ARCHIVE_ROOT = Path.home() / "aurum-archive"

DEFAULT_ENGINE_DIRS = [
    "bridgewater",
    "citadel",
    "deshaw",
    "de_shaw",
    "jane_street",
    "janestreet",
    "jump",
    "millennium",
    "millennium_live",
    "millennium_paper",
    "millennium_shadow",
    "renaissance",
    "runs",
    "twosigma",
    "phi",
    "ornstein",
    "meanrev",
    "kepos",
    "graham",
    "medallion",
    "aqr",
    "db_backups",
]


def select_to_archive(parent: Path, keep_last: int) -> tuple[list[Path], list[Path]]:
    """Split children of `parent` into (keep_newest_N, archive_rest)."""
    if not parent.is_dir():
        return [], []
    children = [p for p in parent.iterdir() if p.is_dir()]
    children.sort(key=lambda p: p.stat().st_mtime)
    if len(children) <= keep_last:
        return children, []
    archive = children[:-keep_last]
    keep = children[-keep_last:]
    return keep, archive


def archive_and_remove(*, to_archive: list[Path], archive_zip: Path) -> int:
    """Zip all `to_archive` entries then delete them. Returns count removed."""
    if not to_archive:
        return 0
    archive_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_zip, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for run in to_archive:
            for p in run.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(run.parent))
    removed = 0
    for run in to_archive:
        shutil.rmtree(run, ignore_errors=True)
        if not run.exists():
            removed += 1
    return removed


def process(engine_dir: str, *, keep_last: int, apply: bool, stamp: str) -> None:
    parent = DATA / engine_dir
    if not parent.is_dir():
        return
    keep, to_archive = select_to_archive(parent, keep_last=keep_last)
    print(f"[{engine_dir}] keep={len(keep)} archive={len(to_archive)}")
    if not to_archive or not apply:
        return
    archive_zip = ARCHIVE_ROOT / f"{engine_dir}_older_{stamp}.zip"
    n = archive_and_remove(to_archive=to_archive, archive_zip=archive_zip)
    print(f"[{engine_dir}] archived={n} zip={archive_zip.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default=None, help="Single engine dir name (default: all)")
    ap.add_argument("--keep", type=int, default=10)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    stamp = datetime.now().strftime("%Y-%m-%d")
    targets = [args.engine] if args.engine else DEFAULT_ENGINE_DIRS
    for e in targets:
        process(e, keep_last=args.keep, apply=args.apply, stamp=stamp)
    if not args.apply:
        print("\ndry-run — pass --apply to archive")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
