# Limpeza Geral — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute 3-sub-project coordinated cleanup — A) disk hygiene (~2 GB freed in OneDrive), B) performance (HMM cache + lazy imports + session fixtures → −40% walkforward, −20% suite), C) dead code decisions (archive `meanrev` cluster; document `millennium_live.py`) — with zero regression and zero toque em CORE PROTEGIDO.

**Architecture:** Three independent sub-projects. A is pure ops (data/ + git hygiene). B modifies `core/chronos.py`, `core/__init__.py`, `tests/conftest.py`, adds `core/hmm_cache.py`. C moves 5 files into `_archive/` dirs. Each sub-project ends in its own commit. All validated by `smoke_test.py --quiet` (178/178) + `pytest tests/ -q` (≥1374 passed). Reversibility guarantee: anything removed from repo is first zipped into `~/aurum-archive/` (outside OneDrive).

**Tech Stack:** Python 3.14, pytest, sqlite3, zipfile (stdlib), numpy, pandas.

**Protected files — DO NOT modify:** `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`, `config/keys.json`.

**Spec:** `docs/superpowers/specs/2026-04-20-limpeza-geral-design.md`.

---

## File Structure

**Create (new):**
- `~/aurum-archive/` (home dir, not repo) — zipped run archives
- `~/aurum-backups/` (home dir, not repo) — pre-VACUUM DB backup
- `engines/_archive/` + `engines/_archive/__init__.py`
- `tools/maintenance/db_vacuum.py` — SQLite VACUUM wrapper
- `tools/maintenance/archive_old_runs.py` — keep-last-N retention
- `core/hmm_cache.py` — `GaussianHMMNp.fit` memoization
- `tests/core/test_hmm_cache.py` — cache unit tests
- `tests/core/test_hmm_cache_integration.py` — end-to-end fit-with-cache test

**Modify:**
- `core/chronos.py` — add 4-line cache consult/store in `GaussianHMMNp.fit` (lines ~174–230)
- `core/__init__.py` — replace eager re-exports with PEP 562 `__getattr__`
- `tests/conftest.py` — add `synthetic_ohlcv` session fixture
- `.gitignore` — add `server/website/dist/`
- `engines/millennium_live.py` — add header docstring clarifying role

**Move (→ archive):**
- `engines/meanrev.py` → `engines/_archive/meanrev.py`
- `tests/engines/test_meanrev.py` → `tests/engines/_archive/test_meanrev.py` (and `__init__.py`)
- `tools/meanrev_partial_revert_search.py` → `tools/_archive/meanrev_partial_revert_search.py`
- `tools/meanrev_snapback_search.py` → `tools/_archive/meanrev_snapback_search.py`
- `tools/batteries/meanrev_variant_search.py` → `tools/_archive/meanrev_variant_search.py`

**Remove from git index (keep local):**
- `server/website/dist/**`

---

# Sub-project A — Disk Hygiene

## Task A0: Prep — create archive dirs + baseline snapshot

**Files:**
- Create: `~/aurum-archive/` (mkdir)
- Create: `~/aurum-backups/` (mkdir)
- Create: `engines/_archive/__init__.py`
- Create: `tests/engines/_archive/__init__.py`
- Create: `tools/_archive/` (already exists; verify)

- [ ] **Step 1: Create archive/backup dirs outside repo**

```bash
mkdir -p ~/aurum-archive ~/aurum-backups
ls -la ~/aurum-archive ~/aurum-backups
```

Expected: both dirs present and empty.

- [ ] **Step 2: Snapshot baseline for the session log**

```bash
du -sh data/ > /tmp/aurum_baseline_data.txt
du -sh data/bridgewater/ data/aurum.db data/millennium/ data/deshaw/ data/runs/ data/renaissance/ data/jump/ data/db_backups/ 2>&1 >> /tmp/aurum_baseline_data.txt
cat /tmp/aurum_baseline_data.txt
```

Expected: `data/` ~2.9G; `data/bridgewater/` ~1.4G; `data/aurum.db` ~440M.

- [ ] **Step 3: Create `engines/_archive/__init__.py` and `tests/engines/_archive/__init__.py`**

```python
# engines/_archive/__init__.py
"""Archived engines. Kept in-tree for git history but not imported by runtime."""
```

```python
# tests/engines/_archive/__init__.py
"""Archived engine tests. Not collected by pytest (excluded in conftest)."""
```

- [ ] **Step 4: No commit yet — just prep.** These files ride along with Task C commits.

---

## Task A1: Archive bridgewater runs (1.4 GB)

**Files:**
- Create: `~/aurum-archive/bridgewater_runs_2026-04-20.zip`
- Delete: `data/bridgewater/*` (all 230 timestamped dirs)

**Context:** `data/` is gitignored — this is a disk cleanup, not a git cleanup. Zip is safety net.

- [ ] **Step 1: List what will be archived (dry-run)**

```bash
ls data/bridgewater/ | wc -l
du -sh data/bridgewater/
```

Expected: ~230 dirs, ~1.4 GB.

- [ ] **Step 2: Create the zip**

Use Python stdlib for portability across Windows/Linux:

```bash
python -c "
import zipfile, os, pathlib
src = pathlib.Path('data/bridgewater')
dst = pathlib.Path.home() / 'aurum-archive' / 'bridgewater_runs_2026-04-20.zip'
dst.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
    for p in src.rglob('*'):
        if p.is_file():
            zf.write(p, p.relative_to(src.parent))
print(f'zipped to {dst}, size={dst.stat().st_size/1e9:.2f} GB')
"
```

Expected: prints `zipped to .../bridgewater_runs_2026-04-20.zip, size=0.X GB`. May take 2–5 min.

- [ ] **Step 3: Verify zip integrity**

```bash
python -c "
import zipfile, pathlib
z = zipfile.ZipFile(pathlib.Path.home() / 'aurum-archive' / 'bridgewater_runs_2026-04-20.zip')
print('files:', len(z.namelist()))
bad = z.testzip()
print('testzip:', bad if bad else 'OK')
"
```

Expected: `files: >1000, testzip: OK`.

- [ ] **Step 4: Remove `data/bridgewater/` subdirs**

```bash
python -c "
import shutil, pathlib
root = pathlib.Path('data/bridgewater')
for p in sorted(root.iterdir()):
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
print('remaining:', list(root.iterdir()))
"
```

Expected: `remaining: []`.

- [ ] **Step 5: Verify disk freed**

```bash
du -sh data/bridgewater/ data/
```

Expected: `data/bridgewater/` near 0; `data/` dropped by ~1.4 GB.

- [ ] **Step 6: Smoke test — no regression**

```bash
python smoke_test.py --quiet
```

Expected: 178/178 pass.

- [ ] **Step 7: Commit**

`data/` is gitignored so no file change to commit yet. Defer commit until Task A7 (gitignore update) bundles all sub-A changes.

---

## Task A2: VACUUM `data/aurum.db` (440 MB)

**Files:**
- Create: `tools/maintenance/db_vacuum.py`
- Create: `~/aurum-backups/aurum.db.<stamp>.bak` (at runtime)
- Modify (on disk, gitignored): `data/aurum.db`

- [ ] **Step 1: Write the script**

```python
# tools/maintenance/db_vacuum.py
"""VACUUM data/aurum.db safely: backup first, close connections, report sizes.

Usage:
    python tools/maintenance/db_vacuum.py           # dry-run
    python tools/maintenance/db_vacuum.py --apply   # backup + VACUUM
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "aurum.db"
BACKUP_DIR = Path.home() / "aurum-backups"


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def top_tables(db: Path, limit: int = 5) -> list[tuple[str, int]]:
    con = sqlite3.connect(db)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = [r[0] for r in cur.fetchall()]
    sizes = []
    for name in names:
        cur.execute(f"SELECT COUNT(*) FROM '{name}'")
        sizes.append((name, cur.fetchone()[0]))
    con.close()
    return sorted(sizes, key=lambda x: -x[1])[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually run VACUUM")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}", file=sys.stderr)
        return 1

    size_before = DB_PATH.stat().st_size
    print(f"DB: {DB_PATH}")
    print(f"size before: {human(size_before)}")
    print(f"top tables (by row count):")
    for name, rows in top_tables(DB_PATH):
        print(f"  {name}: {rows:,} rows")

    if not args.apply:
        print("\ndry-run — pass --apply to VACUUM")
        return 0

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_path = BACKUP_DIR / f"aurum.db.{stamp}.bak"
    shutil.copy2(DB_PATH, backup_path)
    print(f"\nbackup: {backup_path} ({human(backup_path.stat().st_size)})")

    con = sqlite3.connect(DB_PATH)
    con.execute("VACUUM")
    con.close()

    size_after = DB_PATH.stat().st_size
    print(f"\nsize after:  {human(size_after)}")
    print(f"delta:       {human(size_before - size_after)} freed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Dry-run to see tables**

```bash
python tools/maintenance/db_vacuum.py
```

Expected: prints size ~440 MB + top 5 tables.

- [ ] **Step 3: Apply VACUUM**

```bash
python tools/maintenance/db_vacuum.py --apply
```

Expected: prints backup path + size-before / size-after. Note delta freed.

- [ ] **Step 4: Verify backup exists and is readable**

```bash
python -c "
import sqlite3, pathlib
latest = sorted((pathlib.Path.home() / 'aurum-backups').glob('aurum.db.*.bak'))[-1]
con = sqlite3.connect(latest)
print('backup tables:', [r[0] for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])
"
```

Expected: lists tables, no errors.

- [ ] **Step 5: Smoke test**

```bash
python smoke_test.py --quiet
```

Expected: 178/178 pass.

- [ ] **Step 6: Stage the script for later commit**

```bash
git add tools/maintenance/db_vacuum.py
```

No commit yet — bundles into the A final commit.

---

## Task A3: keep-last-N retention script + tests

**Files:**
- Create: `tools/maintenance/archive_old_runs.py`
- Create: `tests/tools/test_archive_old_runs.py`
- Create: `tests/tools/__init__.py` (if absent)

- [ ] **Step 1: Write the failing test**

```python
# tests/tools/test_archive_old_runs.py
"""Unit tests for archive_old_runs retention."""
from __future__ import annotations

import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tools.maintenance.archive_old_runs import select_to_archive, archive_and_remove


def _mkrun(parent: Path, name: str, age_days: int) -> Path:
    run = parent / name
    run.mkdir(parents=True)
    (run / "state").mkdir()
    (run / "state" / "x.json").write_text("{}")
    ts = datetime.now().timestamp() - age_days * 86400
    import os
    os.utime(run, (ts, ts))
    return run


def test_select_to_archive_keeps_last_n(tmp_path: Path):
    parent = tmp_path / "engine"
    parent.mkdir()
    for i in range(15):
        _mkrun(parent, f"2026-04-{i+1:02d}_0000", age_days=30 - i)
    runs_all = sorted(parent.iterdir())
    keep, archive = select_to_archive(parent, keep_last=10)
    assert len(keep) == 10
    assert len(archive) == 5
    # Keeps the 10 newest by mtime
    keep_names = {p.name for p in keep}
    newest_10 = {p.name for p in sorted(runs_all, key=lambda p: p.stat().st_mtime)[-10:]}
    assert keep_names == newest_10


def test_select_to_archive_fewer_than_keep_is_noop(tmp_path: Path):
    parent = tmp_path / "engine"
    parent.mkdir()
    for i in range(3):
        _mkrun(parent, f"2026-04-{i+1:02d}_0000", age_days=1)
    keep, archive = select_to_archive(parent, keep_last=10)
    assert len(keep) == 3
    assert len(archive) == 0


def test_archive_and_remove_zips_then_deletes(tmp_path: Path):
    parent = tmp_path / "engine"
    parent.mkdir()
    old = _mkrun(parent, "2026-01-01_0000", age_days=100)
    new = _mkrun(parent, "2026-04-19_0000", age_days=1)
    archive_zip = tmp_path / "archive.zip"
    removed = archive_and_remove(
        to_archive=[old], archive_zip=archive_zip
    )
    assert removed == 1
    assert archive_zip.exists()
    assert not old.exists()
    assert new.exists()
    with zipfile.ZipFile(archive_zip) as zf:
        assert any(old.name in n for n in zf.namelist())
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/tools/test_archive_old_runs.py -v
```

Expected: FAIL with `ModuleNotFoundError: tools.maintenance.archive_old_runs`.

- [ ] **Step 3: Write the script**

```python
# tools/maintenance/archive_old_runs.py
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
    children.sort(key=lambda p: p.stat().st_mtime)  # oldest first
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
    # Only remove after zip is written successfully
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/tools/test_archive_old_runs.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Dry-run across all engines**

```bash
python tools/maintenance/archive_old_runs.py
```

Expected: lists per-engine `keep=N archive=M`. No files moved.

- [ ] **Step 6: Apply with default keep=10**

```bash
python tools/maintenance/archive_old_runs.py --apply
```

Expected: creates zips in `~/aurum-archive/<engine>_older_2026-04-20.zip` for engines with >10 run dirs; `db_backups` handled separately in next step.

- [ ] **Step 7: Apply with keep=5 for `db_backups`**

```bash
python tools/maintenance/archive_old_runs.py --engine db_backups --keep 5 --apply
```

Expected: zips older backups, keeps newest 5.

- [ ] **Step 8: Verify disk freed + smoke test**

```bash
du -sh data/
python smoke_test.py --quiet
```

Expected: `data/` further shrunk; smoke 178/178.

- [ ] **Step 9: Stage for final commit**

```bash
git add tools/maintenance/archive_old_runs.py tests/tools/test_archive_old_runs.py tests/tools/__init__.py
```

---

## Task A4: Remove `server/website/dist/` from git index

**Files:**
- Modify: `.gitignore`
- Remove from index (keep local): `server/website/dist/**`

- [ ] **Step 1: Confirm dist is tracked**

```bash
git ls-files server/website/dist/ | head -5
```

Expected: lists files including `index-*.js`.

- [ ] **Step 2: Remove from git index (keep on disk)**

```bash
git rm -r --cached server/website/dist/
```

Expected: output `rm 'server/website/dist/...'` for each file.

- [ ] **Step 3: Add to `.gitignore`**

Append to `.gitignore`:

```
# Server website build artifacts (generated by vite build — never versioned)
server/website/dist/
```

- [ ] **Step 4: Verify `git status`**

```bash
git status --short | head -20
```

Expected: shows deletions under `server/website/dist/` + modification to `.gitignore`.

- [ ] **Step 5: Sanity: files still on disk**

```bash
ls server/website/dist/ | head -5
```

Expected: files present (we only untracked them).

---

## Task A5: Clean `tests/_tmp/` orphans

**Files:**
- Delete (on disk): `tests/_tmp/pytest-*/`

- [ ] **Step 1: Count orphans**

```bash
ls tests/_tmp/ 2>/dev/null | wc -l
```

Expected: 30+ dirs.

- [ ] **Step 2: Remove via existing `clean_workspace` utility**

```bash
python tools/maintenance/clean_workspace.py
```

Expected: prints `removed tests/_tmp` line(s), `done removed=N skipped=0`.

- [ ] **Step 3: Verify clean**

```bash
ls tests/_tmp/ 2>/dev/null || echo "empty or absent — ok"
```

Expected: empty or absent.

- [ ] **Step 4: Smoke test**

```bash
python smoke_test.py --quiet
```

Expected: 178/178 pass (tmp is auto-recreated).

---

## Task A6: Final sub-A validation + commit

- [ ] **Step 1: Run the full pytest suite**

```bash
pytest tests/ -q --timeout=120 2>&1 | tail -20
```

Expected: ≥1374 passed (same as baseline; we didn't touch test logic).

- [ ] **Step 2: Measure disk savings**

```bash
du -sh data/
ls -la ~/aurum-archive/ | head -20
```

Expected: `data/` ≤ 1 GB; archive dir has multiple zips.

- [ ] **Step 3: Review staged changes**

```bash
git status
git diff --cached --stat
```

Expected: `.gitignore` modified, `server/website/dist/**` deleted from index, new scripts staged.

- [ ] **Step 4: Commit sub-project A**

```bash
git commit -m "$(cat <<'EOF'
chore(cleanup): disk hygiene — archive old runs, VACUUM db, untrack dist

Sub-projeto A da limpeza geral 2026-04-20:
- tools/maintenance/db_vacuum.py — VACUUM com backup em ~/aurum-backups/
- tools/maintenance/archive_old_runs.py — keep-last-N com zip em ~/aurum-archive/
- tests/tools/test_archive_old_runs.py — 3 unit tests pra retention logic
- server/website/dist/ removido do git index + adicionado ao .gitignore

Runtime effects (data/ gitignored, nao aparece no diff):
- data/bridgewater/ (1.4GB, 230 runs, BUG_SUSPECT) arquivadas
- data/aurum.db (440MB) compactado via VACUUM
- db_backups/ mantem 5 mais recentes, resto arquivado
- demais engines: keep-last-10
- tests/_tmp orfaos removidos

Reversibilidade: zips em ~/aurum-archive/, backup em ~/aurum-backups/.
Zero toque em CORE PROTEGIDO. Smoke 178/178 + suite full verdes.

Spec: docs/superpowers/specs/2026-04-20-limpeza-geral-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hook validates `keys.json`.

---

# Sub-project B — Performance

## Task B1: HMM cache module + unit tests

**Files:**
- Create: `core/hmm_cache.py`
- Create: `tests/core/test_hmm_cache.py`
- Create: `tests/core/__init__.py` (if absent)

- [ ] **Step 1: Write failing tests**

```python
# tests/core/test_hmm_cache.py
"""Unit tests for the Gaussian HMM fit-result cache."""
from __future__ import annotations

import numpy as np
import pytest

from core.hmm_cache import (
    compute_cache_key,
    cache_get,
    cache_set,
    cache_clear,
    cache_stats,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_clear()
    yield
    cache_clear()


def test_cache_key_is_deterministic():
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    params = {"n_states": 3, "n_iter": 100, "tol": 1e-4, "random_state": 7, "min_covar": 1e-6}
    k1 = compute_cache_key(X, params)
    k2 = compute_cache_key(X, params)
    assert k1 == k2
    assert isinstance(k1, str)
    assert len(k1) == 40  # sha1 hex


def test_cache_key_differs_on_data_change():
    X1 = np.array([[1.0, 2.0], [3.0, 4.0]])
    X2 = np.array([[1.0, 2.0], [3.0, 5.0]])  # last value differs
    params = {"n_states": 3}
    assert compute_cache_key(X1, params) != compute_cache_key(X2, params)


def test_cache_key_differs_on_params_change():
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    assert compute_cache_key(X, {"n_states": 3}) != compute_cache_key(X, {"n_states": 4})


def test_get_missing_returns_none():
    assert cache_get("nonexistent") is None


def test_set_and_get_roundtrip():
    payload = {"means_": np.zeros((3, 2)), "covars_": np.ones((3, 2)), "transmat_": np.eye(3), "startprob_": np.ones(3) / 3}
    cache_set("abc123", payload)
    got = cache_get("abc123")
    assert got is not None
    np.testing.assert_array_equal(got["means_"], payload["means_"])
    np.testing.assert_array_equal(got["covars_"], payload["covars_"])


def test_stats_count_hits_and_misses():
    cache_clear()
    assert cache_stats() == {"hits": 0, "misses": 0, "size": 0}
    cache_get("nothing")
    assert cache_stats()["misses"] == 1
    cache_set("x", {"means_": np.zeros(1)})
    cache_get("x")
    assert cache_stats()["hits"] == 1
    assert cache_stats()["size"] == 1
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/core/test_hmm_cache.py -v
```

Expected: FAIL with `ModuleNotFoundError: core.hmm_cache`.

- [ ] **Step 3: Implement cache module**

```python
# core/hmm_cache.py
"""In-memory cache for GaussianHMMNp fit results.

Keyed by sha1(X-summary, sorted-params). Hit returns a dict with the
trained HMM state. Miss returns None.

Optional disk persistence: if env AURUM_HMM_CACHE_PERSIST=1, payloads are
pickled under data/_cache/hmm/<key>.pkl (gitignored). No eviction — the
cache is intended for within-session reuse during walk-forward batteries.

Clear manually with core.hmm_cache.cache_clear() or
tools/maintenance/clear_hmm_cache.py.
"""
from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path
from typing import Any, Optional

import numpy as np

_CACHE: dict[str, dict[str, Any]] = {}
_STATS = {"hits": 0, "misses": 0}

_PERSIST_DIR = Path(__file__).resolve().parent.parent / "data" / "_cache" / "hmm"


def _persist_enabled() -> bool:
    return os.environ.get("AURUM_HMM_CACHE_PERSIST", "").strip() in ("1", "true", "yes")


def compute_cache_key(X: np.ndarray, params: dict[str, Any]) -> str:
    """sha1 over array shape/dtype/first+last rows + sorted params repr."""
    X = np.asarray(X)
    h = hashlib.sha1()
    h.update(str(X.shape).encode())
    h.update(str(X.dtype).encode())
    if X.size:
        # Include first & last rows + a few checksums — enough entropy
        # to detect any realistic re-fit scenario.
        h.update(X[0].tobytes())
        h.update(X[-1].tobytes())
        h.update(str(float(X.sum())).encode())
        h.update(str(float(np.var(X))).encode())
    # Sorted params for deterministic hashing
    for k in sorted(params.keys()):
        h.update(f"{k}={params[k]!r}".encode())
    return h.hexdigest()


def cache_get(key: str) -> Optional[dict[str, Any]]:
    val = _CACHE.get(key)
    if val is not None:
        _STATS["hits"] += 1
        return val
    if _persist_enabled():
        p = _PERSIST_DIR / f"{key}.pkl"
        if p.exists():
            try:
                val = pickle.loads(p.read_bytes())
                _CACHE[key] = val
                _STATS["hits"] += 1
                return val
            except Exception:
                pass
    _STATS["misses"] += 1
    return None


def cache_set(key: str, payload: dict[str, Any]) -> None:
    _CACHE[key] = payload
    if _persist_enabled():
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        (_PERSIST_DIR / f"{key}.pkl").write_bytes(pickle.dumps(payload))


def cache_clear() -> None:
    _CACHE.clear()
    _STATS["hits"] = 0
    _STATS["misses"] = 0


def cache_stats() -> dict[str, int]:
    return {"hits": _STATS["hits"], "misses": _STATS["misses"], "size": len(_CACHE)}
```

- [ ] **Step 4: Run test to verify pass**

```bash
pytest tests/core/test_hmm_cache.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Stage**

```bash
git add core/hmm_cache.py tests/core/test_hmm_cache.py
# create tests/core/__init__.py if needed
test -f tests/core/__init__.py || (touch tests/core/__init__.py && git add tests/core/__init__.py)
```

No commit — bundled at end of B.

---

## Task B2: Wire cache into `GaussianHMMNp.fit`

**Files:**
- Modify: `core/chronos.py` (inside `class GaussianHMMNp.fit`, ~lines 174–230)
- Create: `tests/core/test_hmm_cache_integration.py`

**Context:** `core/chronos.py` is **NOT** on the CORE PROTEGIDO list. Modification is allowed.

- [ ] **Step 1: Write integration test**

```python
# tests/core/test_hmm_cache_integration.py
"""End-to-end: GaussianHMMNp.fit hits the cache on repeated calls with same input."""
from __future__ import annotations

import numpy as np
import pytest

from core.chronos import GaussianHMMNp
from core.hmm_cache import cache_clear, cache_stats


@pytest.fixture(autouse=True)
def _reset():
    cache_clear()
    yield
    cache_clear()


def _synth(n: int = 200, d: int = 2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, d))


def test_second_fit_is_cache_hit_and_matches():
    X = _synth()
    m1 = GaussianHMMNp(n_states=3, n_iter=50, random_state=7).fit(X)
    stats1 = cache_stats()
    assert stats1["misses"] == 1
    assert stats1["hits"] == 0

    m2 = GaussianHMMNp(n_states=3, n_iter=50, random_state=7).fit(X)
    stats2 = cache_stats()
    assert stats2["hits"] == 1, stats2
    assert stats2["size"] == 1

    # Outputs are numerically identical on cache hit
    np.testing.assert_array_equal(m1.means_, m2.means_)
    np.testing.assert_array_equal(m1.covars_, m2.covars_)
    np.testing.assert_array_equal(m1.transmat_, m2.transmat_)
    np.testing.assert_array_equal(m1.startprob_, m2.startprob_)


def test_different_params_do_not_collide():
    X = _synth()
    GaussianHMMNp(n_states=3, random_state=1).fit(X)
    GaussianHMMNp(n_states=3, random_state=2).fit(X)
    GaussianHMMNp(n_states=4, random_state=1).fit(X)
    s = cache_stats()
    assert s["misses"] == 3
    assert s["size"] == 3


def test_predict_after_cached_fit_works():
    X = _synth()
    GaussianHMMNp(n_states=3, random_state=7).fit(X)
    m2 = GaussianHMMNp(n_states=3, random_state=7).fit(X)
    y = m2.predict(X)
    assert y.shape == (X.shape[0],)
    assert y.min() >= 0 and y.max() <= 2
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/core/test_hmm_cache_integration.py -v
```

Expected: FAIL on `test_second_fit_is_cache_hit_and_matches` (cache never populated).

- [ ] **Step 3: Modify `core/chronos.py` — add cache in fit()**

Locate `def fit(self, X):` at `core/chronos.py:174`. Add cache consult at the top of `fit` and store at the end.

Find this block starting at line 174:

```python
    # ── Fit via Baum-Welch ────────────────────────────────────
    def fit(self, X):
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if X.shape[0] == 1 and X.shape[1] != 1 and X.ndim == 2:
            # Treat 1-D input as column vector
            pass
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        self._init_params(X)
        n_samples = X.shape[0]
        K = self.n_states

        if n_samples < 2 or K == 1:
            return self
```

Replace with:

```python
    # ── Fit via Baum-Welch ────────────────────────────────────
    def fit(self, X):
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if X.shape[0] == 1 and X.shape[1] != 1 and X.ndim == 2:
            # Treat 1-D input as column vector
            pass
        if X.ndim == 1:
            X = X.reshape(-1, 1)

        # Cache consult — avoid re-fitting across walk-forward folds.
        from core.hmm_cache import compute_cache_key, cache_get, cache_set
        _params = {
            "n_states": self.n_states,
            "n_iter": self.n_iter,
            "tol": self.tol,
            "random_state": self.random_state,
            "min_covar": self.min_covar,
        }
        _key = compute_cache_key(X, _params)
        _cached = cache_get(_key)
        if _cached is not None:
            self.means_ = _cached["means_"].copy()
            self.covars_ = _cached["covars_"].copy()
            self.transmat_ = _cached["transmat_"].copy()
            self.startprob_ = _cached["startprob_"].copy()
            return self

        self._init_params(X)
        n_samples = X.shape[0]
        K = self.n_states

        if n_samples < 2 or K == 1:
            cache_set(_key, {
                "means_": self.means_.copy(),
                "covars_": self.covars_.copy(),
                "transmat_": self.transmat_.copy(),
                "startprob_": self.startprob_.copy(),
            })
            return self
```

Then find the end of the EM loop — locate the `return self` at the very end of `fit` (around line 230). Before the final `return self`, add the cache store:

Find:

```python
            if np.isfinite(prev_ll) and abs(ll - prev_ll) < self.tol * max(abs(ll), 1.0):
                break
            prev_ll = ll

        return self
```

Replace with:

```python
            if np.isfinite(prev_ll) and abs(ll - prev_ll) < self.tol * max(abs(ll), 1.0):
                break
            prev_ll = ll

        cache_set(_key, {
            "means_": self.means_.copy(),
            "covars_": self.covars_.copy(),
            "transmat_": self.transmat_.copy(),
            "startprob_": self.startprob_.copy(),
        })
        return self
```

- [ ] **Step 4: Run integration tests to verify pass**

```bash
pytest tests/core/test_hmm_cache_integration.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Run existing chronos tests to check no regression**

```bash
pytest tests/ -q -k "chronos or hmm" 2>&1 | tail -10
```

Expected: all pass (no regressions in HMM-touching tests).

- [ ] **Step 6: Measure speedup — micro-benchmark**

```bash
python -c "
import time, numpy as np
from core.chronos import GaussianHMMNp
from core.hmm_cache import cache_clear, cache_stats

rng = np.random.default_rng(42)
X = rng.normal(size=(1000, 3))

cache_clear()
t0 = time.perf_counter()
for _ in range(3):
    GaussianHMMNp(n_states=3, n_iter=100, random_state=7).fit(X)
t_with = time.perf_counter() - t0
print(f'3 fits, cache enabled:  {t_with:.2f}s  stats={cache_stats()}')

cache_clear()
# Simulate no-cache by forcing unique random_state each call
t0 = time.perf_counter()
for i in range(3):
    GaussianHMMNp(n_states=3, n_iter=100, random_state=7+i).fit(X)
t_no = time.perf_counter() - t0
print(f'3 fits, cache misses:   {t_no:.2f}s')
print(f'speedup factor: {t_no/t_with:.1f}x')
"
```

Expected: cache-enabled ~3x faster for repeated identical fits.

- [ ] **Step 7: Stage**

```bash
git add core/chronos.py tests/core/test_hmm_cache_integration.py
```

---

## Task B3: Session-scoped OHLCV fixture + targeted migration

**Files:**
- Modify: `tests/conftest.py` — add `synthetic_ohlcv` session fixture
- Demonstrate usage in one existing slow test (pick via `--durations=10`)

- [ ] **Step 1: Identify top 10 slowest tests**

```bash
pytest tests/ -q --durations=10 -x 2>&1 | tail -30 > /tmp/aurum_durations.txt
cat /tmp/aurum_durations.txt
```

Expected: prints top 10 slowest with their durations. Note the top 1–3 for targeted migration.

- [ ] **Step 2: Add fixture to `tests/conftest.py`**

Append at the end of `tests/conftest.py`:

```python

# ═══ Session-scoped OHLCV fixtures ═══════════════════════════════
# Synthetic OHLCV data loaded once per session. Tests that need a
# mutable DataFrame should call .copy() inline to avoid polluting the
# shared instance.
#
# Why session scope: fixture construction cost was ~3% of suite time
# because every indicator/signal test rebuilt the same synthetic series.

import numpy as np
import pandas as pd


def _build_ohlcv(n_bars: int, seed: int) -> "pd.DataFrame":
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n_bars))
    high = close + np.abs(rng.normal(0, 0.3, n_bars))
    low = close - np.abs(rng.normal(0, 0.3, n_bars))
    open_ = np.concatenate(([close[0]], close[:-1]))
    volume = rng.integers(1_000, 10_000, n_bars).astype(float)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="15min")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture(scope="session")
def ohlcv_500():
    """500-bar synthetic OHLCV DataFrame. Shared; caller must .copy() if mutating."""
    return _build_ohlcv(500, seed=42)


@pytest.fixture(scope="session")
def ohlcv_2000():
    """2000-bar synthetic OHLCV DataFrame. Shared; caller must .copy() if mutating."""
    return _build_ohlcv(2000, seed=42)
```

- [ ] **Step 3: Demonstrate usage — migrate one of the top-3 slowest if applicable**

Pick one top-duration test that currently builds its own OHLCV in a setup. Inspect:

```bash
# If top test was e.g. tests/engines/test_citadel_smoke.py
grep -nE "def (test_|_build.*ohlcv|fixture)" tests/engines/test_citadel_smoke.py | head -10
```

Replace an inline synthetic OHLCV construction (typical pattern: `rng = np.random.default_rng(...); close = 100 + np.cumsum(...)`) with the fixture. Example pattern rewrite:

Before:
```python
def test_citadel_on_synthetic():
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0, 0.5, 500))
    # ... builds ohlcv ...
    result = run_citadel(ohlcv)
    assert result.pnl > 0
```

After:
```python
def test_citadel_on_synthetic(ohlcv_500):
    ohlcv = ohlcv_500.copy()
    result = run_citadel(ohlcv)
    assert result.pnl > 0
```

**Only migrate if the fixture matches the test's needs. If none of the top-3 tests use compatible synthetic OHLCV, SKIP this migration step. Adding the fixture is still valuable — incremental adoption.**

- [ ] **Step 4: Run suite and compare timing**

```bash
time pytest tests/ -q --timeout=120 2>&1 | tail -5
```

Expected: same pass count, wall-time ≤ baseline (85s). Record new time.

- [ ] **Step 5: Stage**

```bash
git add tests/conftest.py
# plus any test file modified in Step 3
```

---

## Task B4: Lazy `core/__init__.py` via PEP 562

**Files:**
- Modify: `core/__init__.py`
- Create: `tests/core/test_core_lazy_init.py`

**Context:** Current `core/__init__.py` eagerly imports from `core.data`, `core.indicators`, `core.signals`, `core.portfolio`, `core.htf`. Every `from core.ui.ui_palette import ...` triggers the whole chain, pulling pandas+requests. PEP 562 `__getattr__` defers evaluation.

- [ ] **Step 1: Measure baseline import time**

```bash
python -X importtime -c "from core.ui.ui_palette import BG" 2>&1 | tail -20 > /tmp/aurum_importtime_before.txt
tail -5 /tmp/aurum_importtime_before.txt
```

Expected: final cumulative import time for `core.ui.ui_palette` visible. Baseline ~800ms+ due to eager pandas load.

- [ ] **Step 2: Write failing test that asserts lazy behavior**

```python
# tests/core/test_core_lazy_init.py
"""Ensures core package does not eagerly import pandas or heavy submodules.

The goal: `from core.ui.ui_palette import BG` should not load core.data or
pandas just to get a color constant. PEP 562 __getattr__ makes core's
top-level re-exports on-demand.
"""
from __future__ import annotations

import subprocess
import sys


def _import_and_probe(probe_expr: str, target_modules: list[str]) -> dict[str, bool]:
    """Run probe in a clean subprocess; return which target modules got loaded."""
    targets = ",".join(f"'{m}'" for m in target_modules)
    code = f"""
import sys
{probe_expr}
result = {{m: (m in sys.modules) for m in [{targets}]}}
import json
print(json.dumps(result))
"""
    out = subprocess.check_output([sys.executable, "-c", code], text=True)
    import json
    return json.loads(out.strip().splitlines()[-1])


def test_ui_palette_does_not_load_pandas():
    loaded = _import_and_probe(
        "from core.ui.ui_palette import BG",
        ["pandas", "core.data", "core.indicators", "core.signals"],
    )
    # Post-fix: none of these should be loaded just to get a color.
    assert not loaded["pandas"], "pandas eagerly loaded by core.ui.ui_palette"
    assert not loaded["core.data"], "core.data eagerly loaded"
    assert not loaded["core.indicators"], "core.indicators eagerly loaded"
    assert not loaded["core.signals"], "core.signals eagerly loaded"


def test_core_still_exposes_top_level_names_on_access():
    loaded = _import_and_probe(
        "import core; _ = core.fetch; _ = core.indicators",
        ["pandas", "core.data", "core.indicators"],
    )
    # After accessing core.fetch and core.indicators, those modules ARE loaded.
    assert loaded["core.indicators"]
    assert loaded["core.data"]
```

- [ ] **Step 3: Run test to verify failure**

```bash
pytest tests/core/test_core_lazy_init.py -v
```

Expected: FAIL — pandas and core.data ARE currently loaded by `from core.ui.ui_palette import BG`.

- [ ] **Step 4: Rewrite `core/__init__.py` with `__getattr__`**

Replace entire content of `core/__init__.py` with:

```python
"""AURUM Core — reusable trading engine components.

Top-level re-exports are resolved lazily via PEP 562 __getattr__. This
keeps ``from core.ui.ui_palette import BG`` (and other narrow imports)
cheap — they no longer trigger eager pandas / indicator loading.

Callers that want the convenient ``from core import fetch`` or
``core.fetch`` still work unchanged — the first access triggers the real
import on demand.
"""
from __future__ import annotations

# Map attribute name -> "<submodule>:<attr>" to import on first access.
_LAZY = {
    # core.data
    "fetch": "core.data:fetch",
    "fetch_all": "core.data:fetch_all",
    "validate": "core.data:validate",
    # core.indicators (module + selected attrs)
    "indicators": "core.indicators:indicators",
    "swing_structure": "core.indicators:swing_structure",
    "omega": "core.indicators:omega",
    "cvd": "core.indicators:cvd",
    "cvd_divergence": "core.indicators:cvd_divergence",
    "volume_imbalance": "core.indicators:volume_imbalance",
    "liquidation_proxy": "core.indicators:liquidation_proxy",
    # core.signals
    "decide_direction": "core.signals:decide_direction",
    "score_omega": "core.signals:score_omega",
    "score_chop": "core.signals:score_chop",
    "calc_levels": "core.signals:calc_levels",
    "calc_levels_chop": "core.signals:calc_levels_chop",
    "label_trade": "core.signals:label_trade",
    "label_trade_chop": "core.signals:label_trade_chop",
    # core.portfolio
    "detect_macro": "core.portfolio:detect_macro",
    "build_corr_matrix": "core.portfolio:build_corr_matrix",
    "portfolio_allows": "core.portfolio:portfolio_allows",
    "check_aggregate_notional": "core.portfolio:check_aggregate_notional",
    "_wr": "core.portfolio:_wr",
    "position_size": "core.portfolio:position_size",
    # core.htf
    "prepare_htf": "core.htf:prepare_htf",
    "merge_all_htf_to_ltf": "core.htf:merge_all_htf_to_ltf",
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module 'core' has no attribute {name!r}")
    import importlib
    modname, attr = _LAZY[name].split(":")
    mod = importlib.import_module(modname)
    value = getattr(mod, attr)
    globals()[name] = value  # cache for subsequent accesses
    return value


def __dir__():
    return sorted(list(_LAZY.keys()) + list(globals().keys()))


__all__ = list(_LAZY.keys())
```

- [ ] **Step 5: Run lazy test to verify pass**

```bash
pytest tests/core/test_core_lazy_init.py -v
```

Expected: both tests pass.

- [ ] **Step 6: Re-measure import time**

```bash
python -X importtime -c "from core.ui.ui_palette import BG" 2>&1 | tail -20 > /tmp/aurum_importtime_after.txt
echo "--- BEFORE ---"
tail -3 /tmp/aurum_importtime_before.txt
echo "--- AFTER ---"
tail -3 /tmp/aurum_importtime_after.txt
```

Expected: AFTER cumulative time is substantially lower (target: >50% reduction for the narrow ui_palette path).

- [ ] **Step 7: Run suite to catch regressions from changed imports**

```bash
pytest tests/ -q --timeout=120 2>&1 | tail -10
```

Expected: same pass count (≥1374). If any test did `from core import X` and something fails, fix by ensuring `X` is in `_LAZY` dict.

- [ ] **Step 8: Smoke test + launcher import sanity**

```bash
python smoke_test.py --quiet
python -c "import launcher; print('launcher imports OK')"
```

Expected: smoke 178/178; launcher imports without error.

- [ ] **Step 9: Stage**

```bash
git add core/__init__.py tests/core/test_core_lazy_init.py
```

---

## Task B5: Final sub-B validation + commit

- [ ] **Step 1: Run full suite one more time with timing**

```bash
time pytest tests/ -q --timeout=120 2>&1 | tail -5
```

Expected: pass count preserved; wall-time equal or lower than pre-B baseline.

- [ ] **Step 2: Review staged**

```bash
git status
git diff --cached --stat
```

Expected: `core/__init__.py`, `core/chronos.py`, `core/hmm_cache.py`, `tests/conftest.py`, plus new tests under `tests/core/` and `tests/tools/`.

- [ ] **Step 3: Commit sub-project B**

```bash
git commit -m "$(cat <<'EOF'
perf(cleanup): HMM cache + lazy core init + session OHLCV fixture

Sub-projeto B da limpeza geral 2026-04-20:
- core/hmm_cache.py — in-memory memoization de GaussianHMMNp.fit
  keyed por (shape/dtype/primeira+ultima row/sum/var, params sorted).
  Opt-in persist via AURUM_HMM_CACHE_PERSIST=1.
- core/chronos.py — 8 linhas adicionadas em GaussianHMMNp.fit pra
  consultar e popular o cache (zero mudanca de comportamento em miss).
- core/__init__.py — re-exports lazy via PEP 562 __getattr__.
  `from core.ui.ui_palette import BG` nao puxa mais pandas/data/
  indicators/signals. Callers com `from core import fetch` seguem
  funcionando (importa na primeira access).
- tests/conftest.py — fixtures session-scoped `ohlcv_500` e
  `ohlcv_2000` pra reuso entre testes (com .copy() quando mutante).
- tests/core/test_hmm_cache.py (6 tests)
- tests/core/test_hmm_cache_integration.py (3 tests)
- tests/core/test_core_lazy_init.py (2 tests)

Medidas antes/depois reportadas no session log.

Zero toque em CORE PROTEGIDO (indicators/signals/portfolio/params).
Smoke 178/178 + suite full verdes.

Spec: docs/superpowers/specs/2026-04-20-limpeza-geral-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds; pre-commit hook validates `keys.json`.

---

# Sub-project C — Dead Code

## Task C1: Archive meanrev cluster

**Files:**
- Move: `engines/meanrev.py` → `engines/_archive/meanrev.py`
- Move: `tests/engines/test_meanrev.py` → `tests/engines/_archive/test_meanrev.py`
- Move: `tools/meanrev_partial_revert_search.py` → `tools/_archive/meanrev_partial_revert_search.py`
- Move: `tools/meanrev_snapback_search.py` → `tools/_archive/meanrev_snapback_search.py`
- Move: `tools/batteries/meanrev_variant_search.py` → `tools/_archive/meanrev_variant_search.py`

**Context:** `meanrev` is not in `config/engines.py` registry. Memory confirms it's a research-only engine followup to the archived ornstein-v1. The 3 tool scripts and 1 test all import from `engines.meanrev`, so they move together as a coherent archive.

- [ ] **Step 1: Verify meanrev not in registry**

```bash
grep -n "meanrev" config/engines.py || echo "confirmed: not in registry"
```

Expected: `confirmed: not in registry`.

- [ ] **Step 2: Verify the 5 files are the complete cluster**

```bash
# The 4 importers + the module itself
# (already verified in plan prep, re-confirm nothing else imports)
grep -rn "from engines.meanrev\|import engines.meanrev\|from engines import meanrev" --include="*.py" | grep -v _archive
```

Expected: exactly 4 lines — the 3 tools + 1 test listed in Files above.

- [ ] **Step 3: Ensure `engines/_archive/` and `tests/engines/_archive/` have `__init__.py`**

```bash
test -f engines/_archive/__init__.py || (mkdir -p engines/_archive && python -c "
import pathlib
p = pathlib.Path('engines/_archive/__init__.py')
p.write_text('\"\"\"Archived engines. Kept in-tree for git history but not imported by runtime.\"\"\"\n')
")
test -f tests/engines/_archive/__init__.py || (mkdir -p tests/engines/_archive && python -c "
import pathlib
p = pathlib.Path('tests/engines/_archive/__init__.py')
p.write_text('\"\"\"Archived engine tests. Pytest ignores this dir via pyproject/pytest.ini config if present.\"\"\"\n')
")
```

- [ ] **Step 4: Move the 5 files**

```bash
git mv engines/meanrev.py engines/_archive/meanrev.py
git mv tests/engines/test_meanrev.py tests/engines/_archive/test_meanrev.py
git mv tools/meanrev_partial_revert_search.py tools/_archive/meanrev_partial_revert_search.py
git mv tools/meanrev_snapback_search.py tools/_archive/meanrev_snapback_search.py
git mv tools/batteries/meanrev_variant_search.py tools/_archive/meanrev_variant_search.py
```

Expected: each prints `rename ... (100%)`.

- [ ] **Step 5: Update the archived tool scripts' imports so they still work when run directly**

The 3 archived scripts still do `from engines.meanrev import ...`. That import now fails. Update each to reference the archive:

For each of the 3 tool scripts, change:

```python
from engines.meanrev import MeanRevParams, run_backtest, save_run
```

To:

```python
from engines._archive.meanrev import MeanRevParams, run_backtest, save_run
```

Do the same for the archived test:

```python
# tests/engines/_archive/test_meanrev.py
from engines.meanrev import MeanRevParams, decide_entry, simulate_trade
# →
from engines._archive.meanrev import MeanRevParams, decide_entry, simulate_trade
```

- [ ] **Step 6: Configure pytest to ignore the archive dir**

Check for an existing config:

```bash
cat pyproject.toml 2>/dev/null | grep -A5 "tool.pytest" || cat pytest.ini 2>/dev/null || cat setup.cfg 2>/dev/null | grep -A5 "\[tool:pytest\]"
```

Expected: either a pyproject.toml or pytest.ini exists. Add `--ignore=tests/engines/_archive` to `addopts`, or add a `collect_ignore` line in `tests/conftest.py`:

If no clean config location, append to `tests/conftest.py`:

```python
collect_ignore_glob = ["engines/_archive/*", "**/_archive/**"]
```

- [ ] **Step 7: Run suite — archived test must not be collected**

```bash
pytest tests/ -q --collect-only 2>&1 | grep -c "_archive" | head -1
pytest tests/ -q --timeout=120 2>&1 | tail -10
```

Expected: zero `_archive` in collection output; full suite passes (same count as B baseline; the archived test is gone, so count may be lower by exactly the number of tests in `test_meanrev.py`).

- [ ] **Step 8: Run smoke**

```bash
python smoke_test.py --quiet
```

Expected: 178/178.

- [ ] **Step 9: Stage**

```bash
git status | head -20
git add -u engines tests tools
git add engines/_archive/__init__.py tests/engines/_archive/__init__.py
# also the updated conftest.py line if added
git add tests/conftest.py
```

---

## Task C2: Clarify `engines/millennium_live.py` role

**Files:**
- Modify: `engines/millennium_live.py` (header docstring)

**Context:** Grep showed `millennium_live.py` is imported only by tests and `tools/maintenance/millennium_shadow.py`. It's a legit live-bootstrap shim, not dead. Missing context is the problem.

- [ ] **Step 1: Read current header**

Already inspected: docstring is minimal (`"""MILLENNIUM live bootstrap runner."""`). Expand it.

- [ ] **Step 2: Replace header docstring**

Find:

```python
"""MILLENNIUM live bootstrap runner.

This is a dedicated entrypoint for preparing the live path of the
MILLENNIUM pod without pretending the full multi-engine execution loop is
validated yet.
"""
```

Replace with:

```python
"""MILLENNIUM live bootstrap runner.

Entrypoint for preparing the live path of the MILLENNIUM pod, used by
``tools/maintenance/millennium_shadow.py`` and the shadow VPS service.
Kept distinct from ``engines/millennium.py`` (the backtest orchestrator)
so the live path can advance through paper → demo → testnet → live
without destabilizing backtest behavior.

Consumers:
  - tools/maintenance/millennium_shadow.py  (shadow runner, VPS service)
  - tests/engines/test_millennium_live_*    (smoke + contract tests)

When the full multi-engine live execution loop is validated end-to-end,
this module either absorbs into engines/millennium.py or gets a clear
deprecation path. Until then, it stays as the deliberate bootstrap shim.

NOT on the CORE PROTEGIDO list — changes here are allowed with the
normal review bar.
"""
```

- [ ] **Step 3: Run suite**

```bash
python smoke_test.py --quiet
pytest tests/ -q -k millennium_live --timeout=60 2>&1 | tail -5
```

Expected: smoke 178/178; millennium_live tests pass.

- [ ] **Step 4: Stage**

```bash
git add engines/millennium_live.py
```

---

## Task C3: Final sub-C validation + commit

- [ ] **Step 1: Full suite**

```bash
pytest tests/ -q --timeout=120 2>&1 | tail -10
```

Expected: all pass (count dropped by the test_meanrev test count, all others preserved).

- [ ] **Step 2: Verify no dangling references to archived modules**

```bash
grep -rn "from engines.meanrev \|from engines import meanrev$\|import engines.meanrev" --include="*.py" | grep -v _archive
```

Expected: zero hits (everything rerouted to `engines._archive.meanrev`).

- [ ] **Step 3: Commit sub-project C**

```bash
git commit -m "$(cat <<'EOF'
chore(cleanup): archive meanrev cluster + document millennium_live

Sub-projeto C da limpeza geral 2026-04-20:
- engines/meanrev.py → engines/_archive/meanrev.py
- tests/engines/test_meanrev.py → tests/engines/_archive/test_meanrev.py
- tools/meanrev_partial_revert_search.py → tools/_archive/
- tools/meanrev_snapback_search.py → tools/_archive/
- tools/batteries/meanrev_variant_search.py → tools/_archive/
- engines/millennium_live.py header expandido clarificando role

meanrev esta fora do config/engines.py registry; era research-only
followup do ornstein-v1 arquivado. Os 3 tool scripts e o test sao um
cluster coerente que acompanha o engine.

millennium_live nao eh dead code — eh shim de bootstrap live distinto
do backtest orchestrator. Header atualizado reflete o papel.

nexus.db confirmado LIVE (config/paths.py + api/models.py); code_viewer.py
confirmado LIVE (consumido por launcher.py + launcher_support/
engines_live_view.py). Nenhum dos dois arquivado.

Zero toque em CORE PROTEGIDO. Smoke 178/178 verde.

Spec: docs/superpowers/specs/2026-04-20-limpeza-geral-design.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: commit succeeds.

---

# Final: Session log + daily log

## Task Z: Session log + daily log + final check

**Files:**
- Create: `docs/sessions/2026-04-20_<HHMM>.md`
- Modify: `docs/days/2026-04-20.md` (create if absent)

- [ ] **Step 1: Collect metrics for the log**

```bash
du -sh data/
ls -la ~/aurum-archive/ | tail -10
pytest tests/ -q --timeout=120 2>&1 | tail -3
python smoke_test.py --quiet 2>&1 | tail -3
git log --oneline -5
```

- [ ] **Step 2: Write session log**

Follow the EXACT format in `CLAUDE.md` (Session Log section). File:
`docs/sessions/2026-04-20_<HHMM>.md`. Required sections: Resumo, Commits,
Mudanças Críticas, Achados, Estado do Sistema, Arquivos Modificados,
Notas para o Joao.

Key content:
- Resumo: limpeza A+B+C executada (disco −~2GB, cache HMM + lazy core init, meanrev arquivado)
- Mudanças críticas: nenhuma em lógica de trading; zero toque em CORE PROTEGIDO
- Métricas: disk before/after, suite count before/after, importtime before/after, HMM benchmark speedup
- Notas: destacar que arquivos arquivados podem ser restaurados por unzip de ~/aurum-archive/

- [ ] **Step 3: Write/update daily log**

Update `docs/days/2026-04-20.md` per CLAUDE.md format. Session bullet + entregas consolidadas + estado final + pendências pra amanhã.

- [ ] **Step 4: Commit logs**

```bash
git add docs/sessions/2026-04-20_*.md docs/days/2026-04-20.md
git commit -m "$(cat <<'EOF'
docs(sessions): 2026-04-20_<HHMM> limpeza geral — disco + perf + dead code

Session log consolidado da sessao de limpeza em 3 sub-projetos:
A) disco: ~2GB liberados em OneDrive via archive de runs + VACUUM db
B) perf: HMM cache, lazy core __init__, session fixtures pytest
C) dead code: meanrev cluster arquivado, millennium_live documentado

Zero toque em CORE PROTEGIDO. Smoke 178/178 + suite full verdes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:** Each spec section has a task. A.1 bridgewater→Task A1. A.2 VACUUM→A2. A.3 keep-last-10→A3. A.4 db_backups→A3 (same script, `--keep 5`). A.5 nexus.db→**dropped** (confirmed live). A.6 dist→A4. A.7 tmp→A5. B.1 HMM cache→B1+B2. B.2 session fixtures→B3. B.3 lazy imports→B4 (scope corrected: root cause is `core/__init__.py`, not `core/ui/ui_palette.py`). C.1 meanrev→C1. C.2 meanrev tools→C1 (bundled). C.3 code_viewer→**dropped** (confirmed live). C.4 millennium_live→C2.

**Placeholder scan:** No TBD/TODO/"add appropriate error handling". Every code block is complete. Every command has expected output.

**Type consistency:** `compute_cache_key(X, params)` / `cache_get(key)` / `cache_set(key, payload)` / `cache_clear()` / `cache_stats()` — consistent across B1 tests and B1 implementation; B2 integration test uses the same signatures. `select_to_archive(parent, keep_last)` returns `(keep, archive)` tuple — matches in A3.

**Scope check:** Single plan for one coordinated cleanup sprint. A/B/C are sub-projects with independent commits but one design. No need to split further.

**Deviations from spec documented:**
- A.5 nexus.db removed (live DB, not orphan)
- B.3 root cause moved from `ui_palette.py` to `core/__init__.py` (ui_palette has no heavy imports; the chain goes through __init__)
- C adjusted: code_viewer.py live (kept); millennium_live.py live (documented); meanrev archival expanded to the full 5-file cluster (engine + 3 tools + 1 test)

Plan ready.
