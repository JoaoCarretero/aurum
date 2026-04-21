"""Reversible cleanup of data/ layout.

Moves (never deletes):
- research dirs (_bridgewater_*, anti_overfit, audit, param_search,
  perf_profile, validation) -> data/_archive/research/
- legacy data/runs/<engine>_<timestamp>/ -> data/<engine>/<timestamp>/
- data/nexus.db -> data/_archive/db/nexus.db.<timestamp>

Dry-run by default. Pass --apply to execute.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from config.paths import DATA_DIR

DATA_ROOT: Path = DATA_DIR

_RESEARCH_DIRS: tuple[str, ...] = (
    "_bridgewater_compare",
    "_bridgewater_regime_filter",
    "_bridgewater_rolling_compare",
    "anti_overfit",
    "audit",
    "param_search",
    "perf_profile",
    "validation",
)

_ENGINES_PRESERVED: tuple[str, ...] = (
    "citadel", "bridgewater", "jump", "deshaw", "renaissance",
    "millennium", "twosigma", "aqr", "janestreet", "kepos", "medallion",
    "graham", "meanrev", "ornstein", "ornstein_v2", "phi",
    "millennium_live", "millennium_paper", "millennium_shadow", "live",
)


def plan_moves() -> list[tuple[Path, Path]]:
    """Compute list of (src, dst) pairs without touching disk."""
    moves: list[tuple[Path, Path]] = []
    # Research dirs
    for name in _RESEARCH_DIRS:
        src = DATA_ROOT / name
        if src.exists() and src.is_dir():
            dst = DATA_ROOT / "_archive" / "research" / name
            moves.append((src, dst))
    # Legacy runs/ dir: split per engine
    legacy_runs = DATA_ROOT / "runs"
    if legacy_runs.exists() and legacy_runs.is_dir():
        for sub in legacy_runs.iterdir():
            if not sub.is_dir():
                continue
            engine = sub.name.split("_", 1)[0]
            if engine in _ENGINES_PRESERVED:
                dst = DATA_ROOT / engine / sub.name
                moves.append((sub, dst))
    # nexus.db -> archive with timestamp
    nexus = DATA_ROOT / "nexus.db"
    if nexus.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        dst = DATA_ROOT / "_archive" / "db" / f"nexus.db.{stamp}"
        moves.append((nexus, dst))
    for extra in ("nexus.db-shm", "nexus.db-wal"):
        p = DATA_ROOT / extra
        if p.exists():
            dst = DATA_ROOT / "_archive" / "db" / p.name
            moves.append((p, dst))
    return moves


def run(*, dry_run: bool) -> int:
    moves = plan_moves()
    if not moves:
        print("nothing to clean up.")
        return 0
    for src, dst in moves:
        rel_src = src.relative_to(DATA_ROOT)
        rel_dst = dst.relative_to(DATA_ROOT)
        if dry_run:
            print(f"[dry] mv data/{rel_src} data/{rel_dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            print(f"[skip] data/{rel_dst} already exists")
            continue
        shutil.move(str(src), str(dst))
        print(f"[moved] data/{rel_src} -> data/{rel_dst}")
        print(f"[undo]  mv data/{rel_dst} data/{rel_src}")
    return len(moves)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Execute moves. Default is dry-run.")
    args = ap.parse_args(argv)
    n = run(dry_run=not args.apply)
    print(f"\n{'planned' if not args.apply else 'executed'} {n} moves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
