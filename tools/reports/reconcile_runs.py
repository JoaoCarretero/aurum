"""AURUM — Reconcile data/runs/ directories against data/index.json.

Dry-run by default. Prints a diff plan describing orphans, duplicates and
missing entries. With ``--apply``, mutates data/index.json and optionally
deletes orphan directories — asking for a Y/n confirmation per item.

The script NEVER touches files outside data/runs/ or data/index.json. It
refuses to run if either target is missing or unreadable.

Usage:
    python tools/reports/reconcile_runs.py              # print plan (dry-run)
    python tools/reports/reconcile_runs.py --apply      # prompt per item

Exit codes:
    0 — clean or all requested actions applied
    1 — drift detected in dry-run (hint to re-run with --apply)
    2 — fatal error (missing index, unreadable directory, etc.)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

# Ensure repo root on path when invoked as "python tools/reports/reconcile_runs.py".
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.ops.persistence import atomic_write_json

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = ROOT / "data" / "runs"
INDEX_PATH = ROOT / "data" / "index.json"


# ── Output helpers ─────────────────────────────────────────────────────

def _p(text: str = "") -> None:
    print(text)


def _warn(text: str) -> None:
    print(f"  ! {text}", file=sys.stderr)


def _confirm(prompt: str) -> bool:
    """Return True iff the user types 'y' or 'Y'. Anything else (including
    empty line or Ctrl-D) is a no."""
    try:
        ans = input(f"    {prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return ans == "y"


def _robust_rmtree(target: Path, retries: int = 3, pause: float = 0.5) -> bool:
    """Remove a directory tree, robust against Windows + OneDrive locks.

    OneDrive likes to keep handles on freshly-closed files/dirs for a brief
    window while it syncs. A plain shutil.rmtree can hit PermissionError
    (WinError 5 "Acesso negado") even on empty directories the current user
    owns. This helper:

    1. Runs shutil.rmtree with an onexc handler that clears the read-only
       bit and retries — covers some attribute-based refusals.
    2. If rmtree still fails, falls back to `cmd /c rmdir /s /q`, which on
       Windows bypasses some of Python's permission quirks.
    3. Retries the whole thing up to ``retries`` times with a pause.

    Returns True on success, False if the tree still exists after all
    attempts. Never raises — the caller decides how to handle the failure.
    """

    def _on_exc(func, path, exc_info):  # type: ignore[no-untyped-def]
        try:
            os.chmod(path, stat.S_IWRITE)
            func(path)
        except OSError:
            pass

    for attempt in range(retries):
        if not target.exists():
            return True
        try:
            shutil.rmtree(target, onexc=_on_exc)  # py 3.12+ signature
        except TypeError:
            shutil.rmtree(target, onerror=lambda f, p, e: _on_exc(f, p, e))
        except (OSError, PermissionError):
            pass
        if not target.exists():
            return True
        # Fallback: native rmdir — bypasses Python file-handle quirks
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["cmd", "/c", "rmdir", "/s", "/q", str(target)],
                    check=False, capture_output=True, timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not target.exists():
            return True
        time.sleep(pause)
    return not target.exists()


# ── Core diff ──────────────────────────────────────────────────────────

def _load_index() -> list[dict]:
    if not INDEX_PATH.exists():
        _warn(f"{INDEX_PATH} does not exist")
        return []
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _warn(f"cannot read {INDEX_PATH}: {e}")
        sys.exit(2)
    if not isinstance(data, list):
        _warn(f"{INDEX_PATH} is not a JSON array (type: {type(data).__name__})")
        sys.exit(2)
    return [r for r in data if isinstance(r, dict) and r.get("run_id")]


def _list_disk_runs() -> list[Path]:
    if not RUNS_DIR.exists():
        _warn(f"{RUNS_DIR} does not exist")
        return []
    return sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()])


def _run_dir_status(run_dir: Path) -> str:
    """Rough health check of a run directory.

    - ``complete``: has summary.json (modern) or citadel_*.json (legacy)
    - ``partial``: has charts/ or log.txt but no summary
    - ``empty``: directory exists but is empty
    """
    if not run_dir.exists() or not run_dir.is_dir():
        return "missing"
    entries = list(run_dir.iterdir())
    if not entries:
        return "empty"
    names = {e.name for e in entries}
    if "summary.json" in names:
        return "complete"
    if any(n.startswith("citadel_") and n.endswith(".json") for n in names):
        return "complete"
    return "partial"


def _dir_size(run_dir: Path) -> int:
    total = 0
    try:
        for p in run_dir.rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                continue
    except OSError:
        return 0
    return total


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n/1024:.0f}K"
    return f"{n/(1024*1024):.1f}M"


# ── Plan ───────────────────────────────────────────────────────────────

def build_plan(index: list[dict], disk: list[Path]) -> dict:
    """Return a dict describing every drift item between index and disk."""
    disk_ids = {d.name for d in disk}
    index_by_id: dict[str, list[int]] = {}
    for i, row in enumerate(index):
        index_by_id.setdefault(row["run_id"], []).append(i)

    orphans = []  # on disk, not in index
    for d in disk:
        if d.name not in index_by_id:
            orphans.append({
                "run_id": d.name,
                "status": _run_dir_status(d),
                "size":   _dir_size(d),
            })

    missing = []  # in index, not on disk
    for rid, rows in index_by_id.items():
        if rid not in disk_ids:
            missing.append({
                "run_id": rid,
                "rows":   rows,
            })

    duplicates = []  # same run_id, multiple rows
    for rid, rows in index_by_id.items():
        if len(rows) <= 1:
            continue
        # Flag identical vs different rows — helps the user decide
        row_hashes = [
            (index[r].get("pnl"), index[r].get("n_trades"), index[r].get("config_hash"))
            for r in rows
        ]
        all_identical = len(set(row_hashes)) == 1
        duplicates.append({
            "run_id":        rid,
            "indices":       rows,
            "identical":     all_identical,
            "entries":       [index[r] for r in rows],
        })

    return {
        "orphans":    orphans,
        "missing":    missing,
        "duplicates": duplicates,
        "total_index_rows": len(index),
        "total_disk_dirs":  len(disk),
    }


def print_plan(plan: dict) -> None:
    _p()
    _p("=" * 64)
    _p("  AURUM — Index / Runs reconciliation plan")
    _p("=" * 64)
    _p(f"  {plan['total_index_rows']} rows in data/index.json")
    _p(f"  {plan['total_disk_dirs']} directories in data/runs/")
    _p()

    if plan["orphans"]:
        _p("ORPHAN DIRS (on disk, not in index)")
        _p("-" * 64)
        for o in plan["orphans"]:
            _p(f"  • {o['run_id']}")
            _p(f"      status: {o['status']}    size: {_fmt_size(o['size'])}")
        _p()

    if plan["missing"]:
        _p("MISSING DIRS (in index, not on disk)")
        _p("-" * 64)
        for m in plan["missing"]:
            _p(f"  • {m['run_id']}   (index rows: {m['rows']})")
        _p()

    if plan["duplicates"]:
        _p("DUPLICATE INDEX ROWS (same run_id, multiple entries)")
        _p("-" * 64)
        for d in plan["duplicates"]:
            flag = "identical" if d["identical"] else "DIFFERENT values"
            _p(f"  • {d['run_id']}   ×{len(d['indices'])}   ({flag})")
            for e in d["entries"]:
                pnl = e.get("pnl")
                nt = e.get("n_trades")
                ts = e.get("timestamp", "—")
                _p(f"      ts={ts}  pnl={pnl}  trades={nt}")
        _p()

    clean = not (plan["orphans"] or plan["missing"] or plan["duplicates"])
    if clean:
        _p("CLEAN — no drift detected.")
        _p()
        return


# ── Apply ──────────────────────────────────────────────────────────────

def apply_plan(plan: dict, index: list[dict]) -> tuple[list[dict], int]:
    """Mutate ``index`` in place (dedupe) and prompt for orphan deletion.

    Returns ``(new_index, changes_applied)``.
    """
    changes = 0

    # 1) Orphans — filesystem operations can fail on Windows/OneDrive locks.
    # Failures are logged but do NOT abort the rest of the plan (index dedupe
    # is independent and should still land).
    for o in plan["orphans"]:
        rid = o["run_id"]
        _p(f"  orphan: {rid}  ({o['status']}, {_fmt_size(o['size'])})")
        if o["status"] == "complete":
            _p("      — has summary.json, likely a real run never indexed")
            _p("      (you may prefer to re-index instead of deleting)")
            approved = _confirm(f"delete {rid}?")
        else:
            approved = _confirm(f"delete {rid} (crashed mid-run)?")
        if approved:
            if _robust_rmtree(RUNS_DIR / rid):
                changes += 1
            else:
                _warn(f"failed to delete {rid} — still on disk")
                _warn("(likely OneDrive / antivirus lock — try again in a minute)")

    # 2) Duplicates — keep one row per run_id
    dedupe_keep: dict[str, int] = {}
    for d in plan["duplicates"]:
        rid = d["run_id"]
        rows_idx = d["indices"]
        _p()
        _p(f"  duplicate: {rid}   ×{len(rows_idx)}   "
           f"({'identical' if d['identical'] else 'DIFFERENT'})")
        if d["identical"]:
            keep = rows_idx[0]
            _p(f"      identical — keeping row [{keep}], dropping {rows_idx[1:]}")
            if _confirm("apply?"):
                dedupe_keep[rid] = keep
                changes += 1
        else:
            # Show each option
            for n, idx_pos in enumerate(rows_idx):
                e = d["entries"][n]
                _p(f"      [{n}]  ts={e.get('timestamp','—')}  "
                   f"pnl={e.get('pnl')}  trades={e.get('n_trades')}")
            try:
                ans = input(f"    keep which? [0-{len(rows_idx)-1} / s=skip] ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                ans = "s"
            if ans.isdigit() and 0 <= int(ans) < len(rows_idx):
                dedupe_keep[rid] = rows_idx[int(ans)]
                changes += 1
            else:
                _p("      skipped")

    # Build new index: drop duplicate rows not in keep set
    if dedupe_keep:
        seen: set[str] = set()
        new_index: list[dict] = []
        for i, row in enumerate(index):
            rid = row["run_id"]
            if rid in dedupe_keep:
                if i == dedupe_keep[rid]:
                    new_index.append(row)
                # else drop
            else:
                new_index.append(row)
        index = new_index

    # 3) Missing — we don't auto-fix, just warn
    for m in plan["missing"]:
        _p(f"  missing: {m['run_id']} in index but not on disk   "
           f"(rows: {m['rows']}) — leaving as-is")

    return index, changes


# ── Main ───────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="prompt per item and mutate index / filesystem")
    args = ap.parse_args()

    if not RUNS_DIR.exists():
        _warn(f"{RUNS_DIR} does not exist")
        return 2
    if not INDEX_PATH.exists():
        _warn(f"{INDEX_PATH} does not exist")
        return 2

    index = _load_index()
    disk = _list_disk_runs()
    plan = build_plan(index, disk)
    print_plan(plan)

    clean = not (plan["orphans"] or plan["missing"] or plan["duplicates"])
    if clean:
        return 0

    if not args.apply:
        _p("Dry-run only. Re-run with --apply to interactively apply changes.")
        _p()
        return 1

    _p("APPLY mode — you will be prompted per item.")
    _p()
    new_index, changes = apply_plan(plan, index)

    if changes == 0:
        _p()
        _p("No changes applied.")
        return 0

    _p()
    _p(f"Writing {len(new_index)} rows to {INDEX_PATH}...")
    atomic_write_json(INDEX_PATH, new_index)
    _p("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
