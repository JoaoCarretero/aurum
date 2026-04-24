"""Move orphan run dirs out of data/<engine>_<mode>/ into data/_archive/.

An "orphan" is a run dir that:
  - Is NOT registered in aurum.db :: live_runs
  - Is NOT reported by VPS /v1/runs
  - Is not currently in use (no recent mtime within the safety window)

Typical source: smoke-test / desk-test leftovers from earlier sessions
that were never reconciled. Moving to data/_archive/ preserves them in
case anything depends on them; delete the archive dir manually once
you're confident nothing references them.

Default is dry-run. Use --apply to actually move.

Run:
    python tools/maintenance/cleanup_orphan_run_dirs.py           # dry-run
    python tools/maintenance/cleanup_orphan_run_dirs.py --apply   # move
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.paths import DATA_DIR

DB_PATH = _ROOT / "data" / "aurum.db"
ARCHIVE_ROOT = DATA_DIR / "_archive"

# Only touch dirs whose mtime is older than this. Protects a run that
# just started writing state files but hasn't been inserted into DB yet
# (race between live_runs upsert and first heartbeat).
_SAFETY_AGE_SEC = 3600  # 1h

_MODE_SUFFIXES = ("_paper", "_shadow", "_live")


def _db_run_ids() -> set[str]:
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        return {r[0] for r in conn.execute("SELECT run_id FROM live_runs")}
    finally:
        conn.close()


def _vps_run_ids() -> set[str] | None:
    """Returns None if VPS unreachable (caller must NOT cleanup in that
    case — we can't tell orphan from live without the authoritative
    source)."""
    try:
        from launcher_support.engines_live_view import _get_cockpit_client
    except Exception:
        return None
    client = _get_cockpit_client()
    if client is None:
        return None
    try:
        rows = client._get("/v1/runs")
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    return {str(r.get("run_id")) for r in rows if r.get("run_id")}


def _engine_mode_dirs() -> list[Path]:
    """All data/<slug>_{paper,shadow,live} dirs that exist."""
    out: list[Path] = []
    if not DATA_DIR.exists():
        return out
    for sub in DATA_DIR.iterdir():
        if not sub.is_dir():
            continue
        if sub.name.startswith("_"):
            continue  # skip _archive itself and similar
        if any(sub.name.endswith(suf) for suf in _MODE_SUFFIXES):
            out.append(sub)
    return out


def find_orphans(*, trust_db: bool = False) -> tuple[list[Path], set[str], set[str] | None]:
    """Return (orphan_dirs, db_ids, vps_ids). vps_ids=None means VPS was
    unreachable; when ``trust_db`` is True the caller accepts DB as the
    authoritative source (safe right after a successful --from-vps
    backfill), otherwise the caller must abort to avoid false-positives."""
    db_ids = _db_run_ids()
    vps_ids = _vps_run_ids()
    now = time.time()
    orphans: list[Path] = []
    authoritative_ids = db_ids if vps_ids is None else (db_ids | vps_ids)
    for parent in _engine_mode_dirs():
        for run_dir in parent.iterdir():
            if not run_dir.is_dir():
                continue
            run_id = run_dir.name
            if run_id in authoritative_ids:
                continue
            try:
                mtime = run_dir.stat().st_mtime
            except OSError:
                continue
            if (now - mtime) < _SAFETY_AGE_SEC:
                continue
            orphans.append(run_dir)
    return orphans, db_ids, vps_ids


def move_to_archive(run_dir: Path) -> Path:
    """Move run_dir into data/_archive/<engine>_<mode>/<run_id>/."""
    parent_name = run_dir.parent.name
    dest_parent = ARCHIVE_ROOT / parent_name
    dest_parent.mkdir(parents=True, exist_ok=True)
    dest = dest_parent / run_dir.name
    if dest.exists():
        # Disambiguate with a stamp — don't clobber an earlier archive.
        dest = dest_parent / f"{run_dir.name}__dup_{int(time.time())}"
    shutil.move(str(run_dir), str(dest))
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Move orphans. Default is dry-run.")
    ap.add_argument("--trust-db", action="store_true",
                    help="Proceed even when VPS is unreachable, using "
                         "live_runs table as authoritative. Safe right "
                         "after `backfill_live_runs.py --from-vps --apply`.")
    args = ap.parse_args(argv)

    orphans, db_ids, vps_ids = find_orphans(trust_db=args.trust_db)

    print(f"== orphan run-dir cleanup ==")
    print(f"  DB live_runs rows:   {len(db_ids)}")
    if vps_ids is None:
        print(f"  VPS reachable:       NO — falling back to DB only"
              if args.trust_db else "  VPS reachable:       NO — ABORTING")
        if not args.trust_db:
            print("  (VPS authoritative for 'live' filtering; re-run with "
                  "--trust-db to use DB only)")
            return 2
    else:
        print(f"  VPS reachable:       yes")
        print(f"  VPS run_ids:         {len(vps_ids)}")
    print(f"  orphans found:       {len(orphans)}")

    # Group by parent for a readable summary
    by_parent: dict[str, int] = {}
    for d in orphans:
        by_parent[d.parent.name] = by_parent.get(d.parent.name, 0) + 1
    for parent, n in sorted(by_parent.items()):
        print(f"     · {parent}: {n}")

    if args.apply:
        print(f"\n  moving → {ARCHIVE_ROOT.relative_to(_ROOT)} ...")
        moved = 0
        for d in orphans:
            try:
                move_to_archive(d)
                moved += 1
            except Exception as e:
                print(f"  !! {d.name}: {e}")
        print(f"  moved {moved} dirs")
    else:
        print("\n  dry-run — pass --apply to actually move.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
