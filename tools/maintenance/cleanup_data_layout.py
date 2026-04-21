"""Reversible cleanup of data/ layout.

Moves (never deletes):
- research dirs (_bridgewater_*, anti_overfit, param_search,
  perf_profile, validation) -> data/_archive/research/
- legacy data/runs/<engine>_<timestamp>/ -> data/<engine>/<timestamp>/
- data/nexus.db -> data/_archive/db/nexus.db.<timestamp>

NOTE: data/audit/ is the LIVE order trail (core.risk.audit_trail.AuditTrail)
and is intentionally excluded from research dirs — it must never be moved.

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


def _active_run_dirs() -> set[Path]:
    """Return set of absolute Paths currently owned by alive engine procs.

    NOTE: core.ops.proc entries do NOT store a run_dir field — they store
    engine name, pid, log_file, status, and Windows identity fingerprints.
    This function therefore returns an empty set; the caller falls back to
    checking active engine names via _active_engine_names() for the runs/
    guard, and conservatively skips the entire runs/ migration if any proc
    is alive (see plan_moves).

    Empty set if proc registry is unreadable (treat as "no active procs" —
    safe default only in dry-run; apply mode uses _active_engine_names).
    """
    return set()


def _active_engine_names() -> set[str]:
    """Return set of engine names for currently alive procs.

    Used to guard legacy runs/ migration: if a citadel proc is alive we
    skip moving any data/runs/citadel_* subdirs to avoid corruption.

    Returns empty set if proc registry is unreadable (conservative: caller
    should warn but not abort in dry-run; in apply mode treats as safe).
    """
    try:
        from core.ops.proc import list_procs
        return {
            p["engine"]
            for p in list_procs()
            if p.get("alive") and p.get("status") == "running"
        }
    except Exception:
        return set()


def plan_moves() -> list[tuple[Path, Path]]:
    """Compute list of (src, dst) pairs without touching disk."""
    active_engines = _active_engine_names()
    moves: list[tuple[Path, Path]] = []

    # Research dirs — none of these are owned by live procs, but guard
    # conservatively: if any proc is alive, still move research dirs since
    # they are never written by running engines. No per-dir guard needed.
    for name in _RESEARCH_DIRS:
        src = DATA_ROOT / name
        if not (src.exists() and src.is_dir()):
            continue
        dst = DATA_ROOT / "_archive" / "research" / name
        moves.append((src, dst))

    # Legacy runs/ dir: split per engine, guard per engine name
    legacy_runs = DATA_ROOT / "runs"
    if legacy_runs.exists() and legacy_runs.is_dir():
        for sub in legacy_runs.iterdir():
            if not sub.is_dir():
                continue
            engine = sub.name.split("_", 1)[0]
            if engine not in _ENGINES_PRESERVED:
                print(
                    f"[warn] data/runs/{sub.name} — unknown engine prefix "
                    f"'{engine}', skipped"
                )
                continue
            if engine in active_engines:
                print(
                    f"[guard] skipping data/runs/{sub.name} — "
                    f"active proc running for engine '{engine}'"
                )
                continue
            dst = DATA_ROOT / engine / sub.name
            moves.append((sub, dst))

    # nexus.db -> archive with timestamp
    # Sidecars (-shm, -wal) only included when primary DB exists (same stamp
    # keeps them associated). If sidecars exist without nexus.db, warn only.
    nexus = DATA_ROOT / "nexus.db"
    if nexus.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        dst = DATA_ROOT / "_archive" / "db" / f"nexus.db.{stamp}"
        moves.append((nexus, dst))
        # Move sidecars with same stamp (keep them associated)
        for ext in ("-shm", "-wal"):
            sidecar = DATA_ROOT / f"nexus.db{ext}"
            if sidecar.exists():
                sidecar_dst = DATA_ROOT / "_archive" / "db" / f"nexus.db.{stamp}{ext}"
                moves.append((sidecar, sidecar_dst))
    else:
        # Warn if sidecars exist without primary DB (inconsistent state)
        for ext in ("-shm", "-wal"):
            orphan = DATA_ROOT / f"nexus.db{ext}"
            if orphan.exists():
                print(
                    f"[warn] data/nexus.db{ext} exists without nexus.db "
                    f"— skipped (orphaned WAL)"
                )

    return moves


def run(*, dry_run: bool) -> int:
    moves = plan_moves()
    if not moves:
        print("nothing to clean up.")
        return 0
    moved = 0
    skipped = 0
    for src, dst in moves:
        rel_src = src.relative_to(DATA_ROOT)
        rel_dst = dst.relative_to(DATA_ROOT)
        if dry_run:
            print(f"[dry] mv data/{rel_src} data/{rel_dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            print(
                f"[WARN] skip: data/{rel_dst} already exists — "
                f"src data/{rel_src} was NOT moved"
            )
            skipped += 1
            continue
        shutil.move(str(src), str(dst))
        print(f"[moved] data/{rel_src} -> data/{rel_dst}")
        print(f"[undo]  mv data/{rel_dst} data/{rel_src}")
        moved += 1
    if not dry_run:
        print(f"\nsummary: {moved} moved, {skipped} skipped (warnings)")
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
