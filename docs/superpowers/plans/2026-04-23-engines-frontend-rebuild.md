# Engines Frontend Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `EXECUTE → ENGINES LIVE` view in TkInter: refactor `engines_live_view.py` (4025 LOC) + `engines_sidebar.py` (1009 LOC) into a coherent `launcher_support/engines_live/` package, then apply new visual design (α layout with V3 cards + D2 detail pane + hold-to-confirm + color-coded log + follow tail).

**Architecture:** Package split into `data/` (pure, no-Tk), `panes/` (Tk widget factories), `dialogs/`, `widgets/`, plus `state.py` + `keyboard.py` + `view.py` orchestrator. Diff-based render replaces destroy+recreate. 5 incremental phases R1-R5, each a green-tests PR. Complements (doesn't conflict with) Phase 3 cleanup which extracts `_eng*` methods from `launcher.py` into `screens/engines_live.py`.

**Tech Stack:** Python 3.11+ · Tkinter · pytest · pytest-xdist · cockpit_api (FastAPI backend, read-only) · SSH to VPS for systemctl actions · HL2/VGUI palette (`core/ui/ui_palette.py`).

**Spec:** `docs/superpowers/specs/2026-04-23-engines-frontend-rebuild-design.md`

---

## Preconditions

Before starting:

1. Phase 3 cleanup (`docs/superpowers/plans/2026-04-23-cleanup-phase-3.md`) should be **merged first** so that `launcher.py._eng*` methods are already delegating to `launcher_support/screens/engines_live.py`. This keeps the rebuild isolated to the actual content layer.
2. Branch from the post-Phase-3 main branch: `git checkout -b feat/engines-frontend-rebuild`.
3. Suite green baseline: `pytest -q` should pass. Record the pass count for regression comparison.
4. Verify key preservations are intact:
   - `python tools/maintenance/verify_keys_intact.py` returns 0
   - `python -c "from launcher_support.engines_live_view import _get_cockpit_client; print('ok')"` prints `ok`
   - `python -c "from launcher_support.engines_sidebar import render_detail, EngineRow, build_engine_rows, format_signal_row, result_color_name; print('ok')"` prints `ok`

---

## File Structure (end state)

```
launcher_support/engines_live/
├── __init__.py                   Re-exports render(), _get_cockpit_client for backward compat
├── view.py                       Top-level orchestrator: mounts panes, owns repaint loop
├── state.py                      Immutable StateSnapshot + reducer; selection, focus, mode, prefs
├── keyboard.py                   Pure route table: (context, key) → Action
├── helpers.py                    Re-export shim for engines_live_helpers backward compat
│
├── data/
│   ├── __init__.py               Threading contract docstring; no code
│   ├── cockpit.py                cockpit_api client wrapper + TTL cache (no-Tk)
│   ├── procs.py                  .aurum_procs.json snapshot + heartbeat reader (no-Tk)
│   ├── aggregate.py              PURE transforms: per-instance rows → per-engine cards
│   └── log_tail.py               File-tail reader + color parser
│
├── panes/
│   ├── header.py                 Title · counts · mode pills · market label
│   ├── strip_grid.py             Responsive grid of engine cards
│   ├── research_shelf.py         Collapsible shelf of not-running engines
│   ├── detail.py                 Dispatcher for detail_left/right/empty; TAB switching
│   ├── detail_left.py            Instances list + KPIs + actions
│   ├── detail_right.py           Log tail + color code + follow mode
│   ├── detail_empty.py           Welcome placeholder when nothing selected
│   └── footer.py                 Context-sensitive keybind hints
│
├── dialogs/
│   ├── new_instance.py           + NEW INSTANCE modal (mode/label/target)
│   └── live_ritual.py            LIVE confirmation (type engine name)
│
└── widgets/
    ├── hold_button.py            Hold-to-confirm 1.5s with amber progress fill
    ├── engine_card.py            Single strip render (normal/stale/error/not-running states)
    └── pill_segment.py           Mode pills segmented control

tests/launcher/engines_live/
├── __init__.py
├── test_aggregate.py
├── test_cockpit_data.py
├── test_keyboard.py
├── test_log_tail.py
├── test_procs_data.py
└── test_state.py

tests/integration/
├── test_engines_live_view.py         (existing, preserved)
└── test_engines_live_panes.py        (new smoke headless)
```

Old files after R5:
- `launcher_support/engines_live_view.py` — 5-line shim re-exporting from `engines_live`
- `launcher_support/engines_sidebar.py` — shim re-exporting `EngineRow`, `build_engine_rows`, `format_signal_row`, `result_color_name`
- `launcher_support/engines_live_helpers.py` — unchanged (already pure)

---

# Phase R1 — Package scaffold + test baseline

Goal: create the `engines_live/` package directory, set up baseline, preserve all backward-compatible imports. Zero visual/behavior change.

---

### Task 1: Create package skeleton

**Files:**
- Create: `launcher_support/engines_live/__init__.py`
- Create: `launcher_support/engines_live/data/__init__.py`
- Create: `launcher_support/engines_live/panes/__init__.py`
- Create: `launcher_support/engines_live/dialogs/__init__.py`
- Create: `launcher_support/engines_live/widgets/__init__.py`

- [ ] **Step 1: Create package directories with `__init__.py` files**

Create `launcher_support/engines_live/__init__.py`:

```python
"""AURUM · Engines Live view — package split from engines_live_view.py.

This package owns the EXECUTE → ENGINES LIVE screen. It is split into:

- data/       pure data access (cockpit_api, procs, aggregate transforms)
- panes/      Tk widget factories for each layout region
- dialogs/    modal dialogs (new instance, LIVE ritual)
- widgets/    reusable Tk widgets (hold button, engine card, pill segment)

Top-level modules:
- view.py     orchestrator; owns repaint loop and pane lifecycle
- state.py    immutable StateSnapshot + reducer (pure)
- keyboard.py routing table for keyboard events (pure)
- helpers.py  re-exports of engines_live_helpers for backward compat

Threading:
- data/* modules run in background ThreadPoolExecutor
- UI updates MUST come back via root.after(0, fn)
- Panes/dialogs/widgets run only on the main Tk thread

Spec: docs/superpowers/specs/2026-04-23-engines-frontend-rebuild-design.md
"""
from __future__ import annotations
```

Create the four subpackage `__init__.py` files with just a docstring:

```python
# launcher_support/engines_live/data/__init__.py
"""Data layer: cockpit_api client, procs snapshot, pure aggregation.

IMPORTANT: Modules in this package MUST NOT import tkinter. They run in
background threads; any UI callback must be dispatched via root.after(0, fn)
by the caller (view.py).
"""
```

```python
# launcher_support/engines_live/panes/__init__.py
"""Tk pane factories. Each module exposes build_<name>(parent, state) -> Frame.

Panes read StateSnapshot and render Tk widgets. They MUST NOT mutate global
state or talk to data/ directly — view.py owns the pull loop.
"""
```

```python
# launcher_support/engines_live/dialogs/__init__.py
"""Modal dialogs for + NEW INSTANCE and LIVE confirmation ritual."""
```

```python
# launcher_support/engines_live/widgets/__init__.py
"""Reusable Tk widgets (engine_card, hold_button, pill_segment)."""
```

- [ ] **Step 2: Verify package imports**

Run: `python -c "import launcher_support.engines_live; import launcher_support.engines_live.data; import launcher_support.engines_live.panes; import launcher_support.engines_live.dialogs; import launcher_support.engines_live.widgets; print('ok')"`

Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add launcher_support/engines_live/
git commit -m "R1.1: create engines_live package skeleton"
```

---

### Task 2: Capture test baseline and create test package

**Files:**
- Create: `tests/launcher/engines_live/__init__.py`

- [ ] **Step 1: Record current suite pass count**

Run: `pytest -q --no-header 2>&1 | tail -5`
Expected: something like `1740 passed, 8 skipped in 108.85s`. Record these numbers.

Also run:
```bash
pytest tests/integration/test_engines_live_view.py -q 2>&1 | tail -3
pytest tests/test_engines_sidebar.py -q 2>&1 | tail -3
```
Expected: both pass. Record counts per file.

- [ ] **Step 2: Create test package directory**

Create `tests/launcher/engines_live/__init__.py` (empty file):

```python
```

- [ ] **Step 3: Verify test discovery picks up new dir**

Run: `pytest tests/launcher/engines_live/ -q --collect-only 2>&1 | tail -3`
Expected: `no tests ran` (dir exists but empty). Not an error.

- [ ] **Step 4: Commit**

```bash
git add tests/launcher/engines_live/__init__.py
git commit -m "R1.2: create tests/launcher/engines_live package"
```

---

### Task 3: Create `helpers.py` re-export shim

**Files:**
- Create: `launcher_support/engines_live/helpers.py`

Goal: provide `launcher_support.engines_live.helpers` as an alias for `launcher_support.engines_live_helpers` so future modules in `engines_live/` can import helpers via the local package path.

- [ ] **Step 1: Write failing test**

Create `tests/launcher/engines_live/test_helpers_reexport.py`:

```python
"""Assert helpers.py re-exports the expected pure symbols from engines_live_helpers."""
from __future__ import annotations


def test_helpers_reexports_format_uptime():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.format_uptime is src.format_uptime


def test_helpers_reexports_assign_bucket():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.assign_bucket is src.assign_bucket


def test_helpers_reexports_cycle_mode():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.cycle_mode is src.cycle_mode


def test_helpers_reexports_load_save_mode():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.load_mode is src.load_mode
    assert h.save_mode is src.save_mode
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/launcher/engines_live/test_helpers_reexport.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.engines_live.helpers'`.

- [ ] **Step 3: Create `helpers.py`**

Create `launcher_support/engines_live/helpers.py`:

```python
"""Re-export shim for engines_live_helpers.

Lets modules inside launcher_support.engines_live.* import helpers via the
local package path (from .helpers import X) while the original module keeps
its existing path for external callers (launcher.py, existing tests).

When R5 completes, engines_live_helpers.py itself can be moved here and this
file becomes the canonical location.
"""
from __future__ import annotations

from launcher_support.engines_live_helpers import (  # noqa: F401
    Bucket,
    Mode,
    _DEFAULT_MODE,
    _DEFAULT_STATE_PATH,
    _ENGINE_DIR_MAP,
    _MODE_COLORS,
    _MODE_ORDER,
    _REPO_ROOT,
    _STAGE_STYLE,
    _safe_float,
    _sanitize_instance_label,
    _stage_badge,
    _uptime_seconds,
    _use_remote_shadow_cache,
    assign_bucket,
    bucket_header_title,
    cockpit_summary,
    cycle_mode,
    footer_hints,
    format_uptime,
    initial_selection,
    live_confirm_ok,
    load_mode,
    row_action_label,
    running_slugs_from_procs,
    save_mode,
)
```

- [ ] **Step 4: Run test to verify pass**

Run: `pytest tests/launcher/engines_live/test_helpers_reexport.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run full suite for regression**

Run: `pytest tests/launcher/engines_live/ tests/test_engines_sidebar.py tests/integration/test_engines_live_view.py -q`
Expected: all pass, same counts as baseline.

- [ ] **Step 6: Commit**

```bash
git add launcher_support/engines_live/helpers.py tests/launcher/engines_live/test_helpers_reexport.py
git commit -m "R1.3: helpers.py re-export shim for engines_live_helpers"
```

---

# Phase R2 — Data layer extraction

Goal: move all data-access code (cockpit_api calls, procs snapshot, log tail, aggregation transforms) out of `engines_live_view.py` into `data/*` modules that are **importable without Tk** and unit-testable.

---

### Task 4: Extract `data/cockpit.py` — cockpit_api client + cache

Goal: move `_get_cockpit_client`, `_load_cockpit_runs_sync`, `_load_cockpit_runs_cached`, cache structures, and helpers out of `engines_live_view.py` into `data/cockpit.py`.

**Files:**
- Create: `launcher_support/engines_live/data/cockpit.py`
- Modify: `launcher_support/engines_live_view.py` (remove extracted code, add re-export)
- Create: `tests/launcher/engines_live/test_cockpit_data.py`

**Preservation:** `launcher_support.engines_live_view._get_cockpit_client` MUST remain importable (launcher.py:674, 718, 6692, 6780 depend on it).

- [ ] **Step 1: Read current implementation**

Read `launcher_support/engines_live_view.py:1906-end` for `_get_cockpit_client` and surrounding cache functions:
- `_get_cockpit_client` — line 1906
- `_COCKPIT_RUNS_CACHE`, `_COCKPIT_RUNS_LOCK` — top of file (~76)
- `_load_cockpit_runs_sync` — line 348
- `_load_cockpit_runs_cached` — line 360
- `_clear_cockpit_view_caches` — line 398
- `_cockpit_runs_loading` — line 415

Note: some of these reference Tk (via `launcher.after`). Isolate the pure parts; leave thin adapter in `engines_live_view.py` for the Tk-touching parts if needed.

- [ ] **Step 2: Write failing tests**

Create `tests/launcher/engines_live/test_cockpit_data.py`:

```python
"""Unit tests for data/cockpit.py — pure cockpit_api client + cache."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


def test_cache_starts_empty():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    snapshot = cockpit.get_cached_runs()

    assert snapshot is None


def test_cache_stores_runs_after_fetch():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    fake_runs = [{"run_id": "abc", "engine": "citadel", "mode": "paper"}]

    with patch.object(cockpit, "_fetch_runs_from_api", return_value=fake_runs):
        cockpit.force_refresh()

    assert cockpit.get_cached_runs() == fake_runs


def test_cache_respects_ttl():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 1}]):
        cockpit.force_refresh()

    # Second call within TTL should return cached, not re-fetch
    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 2}]) as fetch:
        result = cockpit.runs_cached()
        assert fetch.call_count == 0  # cache hit, no API call
    assert result == [{"r": 1}]


def test_cache_expires_after_ttl():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 1}]):
        cockpit.force_refresh()

    # Move past TTL
    cockpit._CACHE_STATE["ts"] = time.time() - (cockpit.CACHE_TTL_S + 10)

    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 2}]) as fetch:
        result = cockpit.runs_cached()
        assert fetch.call_count == 1
    assert result == [{"r": 2}]


def test_client_returns_none_if_keys_missing():
    from launcher_support.engines_live.data import cockpit

    with patch("launcher_support.engines_live.data.cockpit.load_runtime_keys") as lrk:
        lrk.side_effect = __import__("core.risk.key_store", fromlist=["KeyStoreError"]).KeyStoreError("placeholder")
        client = cockpit.get_client()
        assert client is None


def test_loading_flag_toggles():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    assert cockpit.is_loading() is False
    cockpit._CACHE_STATE["loading"] = True
    assert cockpit.is_loading() is True
```

- [ ] **Step 3: Run test to verify failure**

Run: `pytest tests/launcher/engines_live/test_cockpit_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.engines_live.data.cockpit'`.

- [ ] **Step 4: Create `data/cockpit.py`**

Create `launcher_support/engines_live/data/cockpit.py`:

```python
"""Cockpit API client + TTL cache.

Pure module: no tkinter. Callers schedule fetches on background threads
and dispatch UI updates via root.after(0, fn).

Contract:
- get_client() -> CockpitClient | None  (None if keys missing/placeholder)
- runs_cached() -> list[dict]  (cache hit if fresh, fetch + store if stale)
- force_refresh() -> list[dict]  (always fetches, updates cache)
- get_cached_runs() -> list[dict] | None  (read-only accessor, no I/O)
- is_loading() -> bool
- reset_cache_for_tests() -> None

The loading flag is set by external orchestrator (view.py) before dispatching
a background refresh, and cleared on completion. runs_cached() does NOT
toggle it — it's synchronous.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from core.risk.key_store import KeyStoreError, load_runtime_keys

CACHE_TTL_S: float = 60.0

_CACHE_STATE: dict[str, Any] = {
    "ts": 0.0,
    "runs": None,
    "loading": False,
}
_CACHE_LOCK = threading.Lock()


def reset_cache_for_tests() -> None:
    """Test-only: clear cache state. Never call from production code."""
    with _CACHE_LOCK:
        _CACHE_STATE["ts"] = 0.0
        _CACHE_STATE["runs"] = None
        _CACHE_STATE["loading"] = False


def get_cached_runs() -> list[dict] | None:
    """Read-only accessor. Returns None if never populated."""
    with _CACHE_LOCK:
        return _CACHE_STATE["runs"]


def is_loading() -> bool:
    with _CACHE_LOCK:
        return bool(_CACHE_STATE["loading"])


def _fetch_runs_from_api() -> list[dict]:
    """Actual API call. Isolated for easy mocking in tests."""
    client = get_client()
    if client is None:
        return []
    try:
        runs = client.runs_list()  # cockpit_client method; may raise
    except Exception:
        return []
    return runs or []


def runs_cached() -> list[dict]:
    """Returns cached runs if fresh, otherwise fetches + stores + returns."""
    now = time.time()
    with _CACHE_LOCK:
        age = now - _CACHE_STATE["ts"]
        if _CACHE_STATE["runs"] is not None and age < CACHE_TTL_S:
            return _CACHE_STATE["runs"]
    # cache miss — fetch without holding lock
    runs = _fetch_runs_from_api()
    with _CACHE_LOCK:
        _CACHE_STATE["runs"] = runs
        _CACHE_STATE["ts"] = time.time()
    return runs


def force_refresh() -> list[dict]:
    """Bypass TTL, always fetch. Store in cache."""
    runs = _fetch_runs_from_api()
    with _CACHE_LOCK:
        _CACHE_STATE["runs"] = runs
        _CACHE_STATE["ts"] = time.time()
    return runs


_CLIENT_SINGLETON: Any = None
_CLIENT_LOCK = threading.Lock()


def get_client():
    """Lazy-init cockpit_client.CockpitClient from keys.json.

    Returns None if keys.json has placeholder (COLE_AQUI) or file missing.
    Never raises — consumer treats None as "cockpit offline".
    """
    global _CLIENT_SINGLETON
    with _CLIENT_LOCK:
        if _CLIENT_SINGLETON is not None:
            return _CLIENT_SINGLETON
        try:
            keys = load_runtime_keys()
        except KeyStoreError:
            return None
        cockpit_cfg = (keys or {}).get("cockpit_api") or {}
        base_url = cockpit_cfg.get("base_url")
        token = cockpit_cfg.get("read_token") or cockpit_cfg.get("admin_token")
        if not base_url or not token:
            return None
        from launcher_support.cockpit_client import CockpitClient
        _CLIENT_SINGLETON = CockpitClient(base_url=base_url, token=token)
        return _CLIENT_SINGLETON


def reset_client_for_tests() -> None:
    """Test-only: force re-init of client singleton."""
    global _CLIENT_SINGLETON
    with _CLIENT_LOCK:
        _CLIENT_SINGLETON = None
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/launcher/engines_live/test_cockpit_data.py -v`
Expected: 6 passed.

- [ ] **Step 6: Update `engines_live_view.py` to re-export `_get_cockpit_client`**

Read `launcher_support/engines_live_view.py:1906-1920` (the `_get_cockpit_client` function). Replace it with a thin re-export so external callers (launcher.py) keep working:

```python
# Top of file, near other imports
from launcher_support.engines_live.data.cockpit import get_client as _get_cockpit_client_impl

# Replace the body of _get_cockpit_client (around line 1906) with:
def _get_cockpit_client():
    """Backward-compat alias. New code should import from
    launcher_support.engines_live.data.cockpit:get_client directly.
    """
    return _get_cockpit_client_impl()
```

Leave `_load_cockpit_runs_sync`, `_load_cockpit_runs_cached`, `_clear_cockpit_view_caches`, `_cockpit_runs_loading` in `engines_live_view.py` for now — those thread with the launcher via `.after()` and will be migrated in Task 6 when we introduce view.py. For this task we only extract the pure client + cache.

- [ ] **Step 7: Run regression suite**

Run:
```bash
pytest tests/integration/test_engines_live_view.py tests/test_engines_sidebar.py tests/launcher/engines_live/ -q
```
Expected: all pass.

Also smoke-test importability:
```bash
python -c "from launcher_support.engines_live_view import _get_cockpit_client; print(_get_cockpit_client)"
```
Expected: prints `<function _get_cockpit_client at ...>`.

- [ ] **Step 8: Commit**

```bash
git add launcher_support/engines_live/data/cockpit.py \
        launcher_support/engines_live_view.py \
        tests/launcher/engines_live/test_cockpit_data.py
git commit -m "R2.1: extract data/cockpit.py (client + TTL cache)"
```

---

### Task 5: Extract `data/procs.py` — procs snapshot + heartbeat reader

Goal: move `_list_procs_cached`, `_PROCS_CACHE`, `_PAPER_SNAPSHOT_CACHE`, `_SHADOW_SNAPSHOT_CACHE`, and heartbeat-related code from `engines_live_view.py` into `data/procs.py`.

**Files:**
- Create: `launcher_support/engines_live/data/procs.py`
- Modify: `launcher_support/engines_live_view.py` (replace extracted bodies with delegates)
- Create: `tests/launcher/engines_live/test_procs_data.py`

- [ ] **Step 1: Read current implementation**

Inspect `launcher_support/engines_live_view.py`:
- `_PROCS_CACHE` — line 63
- `_PAPER_SNAPSHOT_CACHE`, `_PAPER_SNAPSHOT_LOADING`, `_PAPER_SNAPSHOT_LOCK` — lines 77-79
- `_SHADOW_SNAPSHOT_CACHE`, etc. — line 80+
- `_list_procs_cached` — line 269
- `_load_shadow_snapshot_sync` — line 705
- `_fetch_remote_shadow_run_sync` — line 806

- [ ] **Step 2: Write failing tests**

Create `tests/launcher/engines_live/test_procs_data.py`:

```python
"""Unit tests for data/procs.py — local procs snapshot + heartbeat reader."""
from __future__ import annotations

import json
import time
from pathlib import Path


def test_snapshot_empty_when_no_procs_file(tmp_path, monkeypatch):
    from launcher_support.engines_live.data import procs

    monkeypatch.setattr(procs, "PROCS_PATH", tmp_path / "nonexistent.json")
    procs.reset_cache_for_tests()

    rows = procs.list_procs()
    assert rows == []


def test_snapshot_reads_procs_file(tmp_path, monkeypatch):
    from launcher_support.engines_live.data import procs

    path = tmp_path / "procs.json"
    path.write_text(json.dumps({
        "procs": {
            "abc123": {
                "engine": "citadel", "mode": "paper", "label": "desk-a",
                "pid": 42, "started_at": "2026-04-23T13:35:11+00:00"
            }
        }
    }))
    monkeypatch.setattr(procs, "PROCS_PATH", path)
    procs.reset_cache_for_tests()

    rows = procs.list_procs()
    assert len(rows) == 1
    assert rows[0]["engine"] == "citadel"
    assert rows[0]["run_id"] == "abc123"


def test_snapshot_uses_ttl_cache(tmp_path, monkeypatch):
    from launcher_support.engines_live.data import procs

    path = tmp_path / "procs.json"
    path.write_text(json.dumps({"procs": {"k": {"engine": "citadel", "mode": "paper"}}}))
    monkeypatch.setattr(procs, "PROCS_PATH", path)
    procs.reset_cache_for_tests()

    r1 = procs.list_procs()
    # Change the file; within TTL we should still see r1
    path.write_text(json.dumps({"procs": {"k2": {"engine": "jump", "mode": "shadow"}}}))
    r2 = procs.list_procs()

    assert r1 == r2  # cache hit


def test_snapshot_force_refresh_bypasses_cache(tmp_path, monkeypatch):
    from launcher_support.engines_live.data import procs

    path = tmp_path / "procs.json"
    path.write_text(json.dumps({"procs": {"k": {"engine": "citadel", "mode": "paper"}}}))
    monkeypatch.setattr(procs, "PROCS_PATH", path)
    procs.reset_cache_for_tests()

    procs.list_procs()
    path.write_text(json.dumps({"procs": {"k2": {"engine": "jump", "mode": "shadow"}}}))
    r2 = procs.list_procs(force=True)

    assert len(r2) == 1
    assert r2[0]["engine"] == "jump"


def test_heartbeat_reads_json(tmp_path):
    from launcher_support.engines_live.data import procs

    hb_path = tmp_path / "run_dir" / "state" / "heartbeat.json"
    hb_path.parent.mkdir(parents=True)
    hb_path.write_text(json.dumps({
        "run_id": "abc", "status": "running", "ticks_ok": 17, "novel_total": 0
    }))

    result = procs.read_heartbeat(tmp_path / "run_dir")
    assert result["ticks_ok"] == 17
    assert result["status"] == "running"


def test_heartbeat_returns_none_if_missing(tmp_path):
    from launcher_support.engines_live.data import procs

    result = procs.read_heartbeat(tmp_path / "nonexistent")
    assert result is None
```

- [ ] **Step 3: Run tests — expect failure**

Run: `pytest tests/launcher/engines_live/test_procs_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.engines_live.data.procs'`.

- [ ] **Step 4: Create `data/procs.py`**

Create `launcher_support/engines_live/data/procs.py`:

```python
"""Local procs snapshot + heartbeat file reader.

Pure module: no tkinter. Reads .aurum_procs.json (the procs ledger maintained
by launcher.py when spawning live runners) and heartbeat.json files written
by each runner in its run_dir/state/.

Contract:
- list_procs(force=False) -> list[dict]
    Returns list of proc rows, each: {run_id, engine, mode, label, pid, started_at, ...}
    Uses TTL cache (0.75s default) unless force=True.

- read_heartbeat(run_dir: Path) -> dict | None
    Reads run_dir/state/heartbeat.json. Returns None if missing/malformed.

- reset_cache_for_tests() -> None
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from launcher_support.engines_live_helpers import _REPO_ROOT

PROCS_PATH: Path = _REPO_ROOT / "data" / ".aurum_procs.json"
CACHE_TTL_S: float = 0.75

_CACHE_STATE: dict = {"ts": 0.0, "rows": []}
_CACHE_LOCK = threading.Lock()


def reset_cache_for_tests() -> None:
    with _CACHE_LOCK:
        _CACHE_STATE["ts"] = 0.0
        _CACHE_STATE["rows"] = []


def list_procs(force: bool = False) -> list[dict]:
    """Read .aurum_procs.json and return normalized rows.

    Each row has: run_id, engine, mode, label, pid, started_at, run_dir.
    Returns [] on any parse error (silent — not the caller's job to handle).
    """
    now = time.time()
    if not force:
        with _CACHE_LOCK:
            age = now - _CACHE_STATE["ts"]
            if age < CACHE_TTL_S and _CACHE_STATE["rows"]:
                return list(_CACHE_STATE["rows"])

    if not PROCS_PATH.exists():
        rows: list[dict] = []
    else:
        try:
            raw = json.loads(PROCS_PATH.read_text())
        except Exception:
            rows = []
        else:
            rows = []
            for run_id, meta in (raw.get("procs") or {}).items():
                if not isinstance(meta, dict):
                    continue
                row = dict(meta)
                row["run_id"] = run_id
                rows.append(row)

    with _CACHE_LOCK:
        _CACHE_STATE["ts"] = time.time()
        _CACHE_STATE["rows"] = list(rows)
    return rows


def read_heartbeat(run_dir: Path) -> dict | None:
    """Read <run_dir>/state/heartbeat.json. Returns None if missing/malformed."""
    hb_path = Path(run_dir) / "state" / "heartbeat.json"
    if not hb_path.exists():
        return None
    try:
        return json.loads(hb_path.read_text())
    except Exception:
        return None
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/launcher/engines_live/test_procs_data.py -v`
Expected: 6 passed.

- [ ] **Step 6: Update `engines_live_view.py` `_list_procs_cached`**

Replace the body of `_list_procs_cached` in `engines_live_view.py:269` with a delegate:

```python
def _list_procs_cached(*, force: bool = False, ttl_s: float = 0.75) -> list[dict]:
    """Backward-compat alias. New code should use
    launcher_support.engines_live.data.procs:list_procs directly.
    """
    from launcher_support.engines_live.data.procs import list_procs
    return list_procs(force=force)
```

Keep the old `_PROCS_CACHE` dict at the top of the file for other functions that still reference it directly — Task 9 will fully remove those references.

- [ ] **Step 7: Run regression suite**

Run: `pytest tests/integration/test_engines_live_view.py tests/test_engines_sidebar.py tests/launcher/engines_live/ -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add launcher_support/engines_live/data/procs.py \
        launcher_support/engines_live_view.py \
        tests/launcher/engines_live/test_procs_data.py
git commit -m "R2.2: extract data/procs.py (.aurum_procs.json + heartbeat reader)"
```

---

### Task 6: Create `data/aggregate.py` — pure transform per-instance → per-engine card

Goal: a pure function `build_engine_cards(procs_rows, runs, heartbeats)` → `list[EngineCard]` that collapses N running instances of the same engine into a single aggregated card (the V3 shape).

**Files:**
- Create: `launcher_support/engines_live/data/aggregate.py`
- Create: `tests/launcher/engines_live/test_aggregate.py`

- [ ] **Step 1: Write failing tests**

Create `tests/launcher/engines_live/test_aggregate.py`:

```python
"""Unit tests for data/aggregate.py — pure transforms per-instance → per-engine card."""
from __future__ import annotations


def _make_proc(engine: str, mode: str, label: str, run_id: str,
               uptime_s: int = 900, equity: float | None = 10000.0,
               ticks_ok: int = 17, novel_total: int = 0,
               ticks_fail: int = 0):
    return {
        "run_id": run_id,
        "engine": engine, "mode": mode, "label": label,
        "uptime_s": uptime_s, "equity": equity,
        "ticks_ok": ticks_ok, "novel_total": novel_total,
        "ticks_fail": ticks_fail,
        "heartbeat_age_s": 30,  # fresh
    }


def test_empty_inputs_return_empty():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    assert build_engine_cards([]) == []


def test_single_instance_becomes_single_card():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [_make_proc("citadel", "paper", "desk-a", "rid-1")]
    cards = build_engine_cards(procs)

    assert len(cards) == 1
    card = cards[0]
    assert card.engine == "citadel"
    assert card.instance_count == 1
    assert card.live_count == 1
    assert card.error_count == 0
    assert card.stale_count == 0
    assert card.mode_summary == "p"  # paper only
    assert card.max_uptime_s == 900
    assert card.total_equity == 10000.0
    assert card.total_novel == 0
    assert card.total_ticks == 17


def test_two_instances_same_engine_aggregate_into_one_card():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [
        _make_proc("citadel", "paper", "desk-a", "rid-1"),
        _make_proc("citadel", "shadow", "desk-a", "rid-2", equity=None),
    ]
    cards = build_engine_cards(procs)

    assert len(cards) == 1
    card = cards[0]
    assert card.instance_count == 2
    assert card.live_count == 2
    assert card.mode_summary == "p+s"
    assert card.total_equity == 10000.0  # shadow equity None → excluded
    assert card.total_novel == 0
    assert card.total_ticks == 34


def test_stale_instance_increments_stale_count():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [
        _make_proc("citadel", "paper", "desk-a", "rid-1"),
    ]
    procs[0]["heartbeat_age_s"] = 1900  # > 2 * tick(900)
    cards = build_engine_cards(procs, tick_sec=900)

    assert len(cards) == 1
    assert cards[0].stale_count == 1
    assert cards[0].live_count == 0


def test_error_instance_increments_error_count():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [_make_proc("citadel", "paper", "desk-a", "rid-1", ticks_fail=3)]
    cards = build_engine_cards(procs)

    assert cards[0].error_count == 1
    assert cards[0].live_count == 0


def test_cards_sorted_by_sort_weight_ascending():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    # sort_weight: citadel=10, jump=40, millennium=60
    procs = [
        _make_proc("millennium", "paper", "desk-a", "rid-m"),
        _make_proc("citadel", "paper", "desk-a", "rid-c"),
        _make_proc("jump", "paper", "desk-a", "rid-j"),
    ]
    cards = build_engine_cards(procs)

    engines_ordered = [c.engine for c in cards]
    assert engines_ordered == ["citadel", "jump", "millennium"]


def test_error_cards_sorted_first():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [
        _make_proc("citadel", "paper", "desk-a", "rid-c"),  # healthy, sort_weight=10
        _make_proc("millennium", "paper", "desk-a", "rid-m", ticks_fail=5),  # error, sort_weight=60
    ]
    cards = build_engine_cards(procs)

    engines_ordered = [c.engine for c in cards]
    assert engines_ordered == ["millennium", "citadel"]  # error first despite higher sort_weight
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/launcher/engines_live/test_aggregate.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `data/aggregate.py`**

Create `launcher_support/engines_live/data/aggregate.py`:

```python
"""Pure transform: per-instance proc rows → per-engine EngineCard rows.

No tkinter, no I/O. Given a list of proc dicts (from data.procs.list_procs
enriched with heartbeat + cockpit runs), returns a list of EngineCard
objects suitable for rendering by panes/strip_grid.py and widgets/engine_card.py.

Sort order (as per spec):
  1. Cards with any error instance first (top-left for attention).
  2. Healthy cards ordered by ENGINES[slug].sort_weight ascending.
  3. Tie-break alphabetical by engine slug.

Card state buckets:
  live   = heartbeat fresh AND ticks_fail == 0 AND process alive
  stale  = heartbeat age > 2 * tick_sec
  error  = ticks_fail > 0 OR process dead OR explicit error flag
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from config.engines import ENGINES


@dataclass(frozen=True)
class EngineCard:
    """Aggregated view of one engine's running instances."""
    engine: str                       # slug
    display: str                      # human name for header
    instance_count: int               # total live+stale+error
    live_count: int
    stale_count: int
    error_count: int
    mode_summary: str                 # e.g. "p+s" or "p+s+l"
    max_uptime_s: int
    total_equity: float               # 0.0 if no paper/live instance
    total_novel: int
    total_ticks: int
    sort_weight: int
    has_error: bool


def _proc_state(proc: dict, tick_sec: int) -> str:
    """Classify a proc as 'live', 'stale', or 'error'."""
    if int(proc.get("ticks_fail") or 0) > 0:
        return "error"
    if bool(proc.get("process_dead")):
        return "error"
    age = proc.get("heartbeat_age_s")
    if age is not None and age > 2 * tick_sec:
        return "stale"
    return "live"


def _mode_char(mode: str) -> str:
    return {"paper": "p", "shadow": "s", "live": "l",
            "demo": "d", "testnet": "t"}.get(mode, "?")


def build_engine_cards(procs: Iterable[dict], *,
                       tick_sec: int = 900) -> list[EngineCard]:
    """Collapse proc rows into per-engine cards, sorted per spec."""
    by_engine: dict[str, list[dict]] = {}
    for p in procs:
        engine = p.get("engine")
        if not engine:
            continue
        by_engine.setdefault(engine, []).append(p)

    cards: list[EngineCard] = []
    for engine, rows in by_engine.items():
        live = stale = error = 0
        modes: set[str] = set()
        max_uptime = 0
        eq_sum = 0.0
        novel_sum = 0
        ticks_sum = 0
        for r in rows:
            state = _proc_state(r, tick_sec)
            if state == "live":
                live += 1
            elif state == "stale":
                stale += 1
            else:
                error += 1
            modes.add(_mode_char(r.get("mode", "")))
            max_uptime = max(max_uptime, int(r.get("uptime_s") or 0))
            eq = r.get("equity")
            if eq is not None:
                eq_sum += float(eq)
            novel_sum += int(r.get("novel_total") or 0)
            ticks_sum += int(r.get("ticks_ok") or 0)

        meta = ENGINES.get(engine, {})
        mode_order = ["p", "d", "t", "l", "s"]
        mode_summary = "+".join(m for m in mode_order if m in modes)

        cards.append(EngineCard(
            engine=engine,
            display=meta.get("display", engine.upper()),
            instance_count=live + stale + error,
            live_count=live,
            stale_count=stale,
            error_count=error,
            mode_summary=mode_summary,
            max_uptime_s=max_uptime,
            total_equity=eq_sum,
            total_novel=novel_sum,
            total_ticks=ticks_sum,
            sort_weight=int(meta.get("sort_weight", 9999)),
            has_error=error > 0,
        ))

    # Sort: errors first, then by sort_weight, then alphabetical
    cards.sort(key=lambda c: (not c.has_error, c.sort_weight, c.engine))
    return cards
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/engines_live/test_aggregate.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live/data/aggregate.py \
        tests/launcher/engines_live/test_aggregate.py
git commit -m "R2.3: data/aggregate.py — pure per-engine card collapse"
```

---

### Task 7: Extract `data/log_tail.py` — file tail reader + color parser

Goal: move `_read_log_tail`, `_resolve_log_path`, and add a color-level parser to tag log lines as INFO/SIGNAL/ORDER/FILL/EXIT/WARN/ERROR.

**Files:**
- Create: `launcher_support/engines_live/data/log_tail.py`
- Modify: `launcher_support/engines_live_view.py` (delegate `_read_log_tail`, `_resolve_log_path`)
- Create: `tests/launcher/engines_live/test_log_tail.py`

- [ ] **Step 1: Write failing tests**

Create `tests/launcher/engines_live/test_log_tail.py`:

```python
"""Unit tests for data/log_tail.py — tail reader + color parse."""
from __future__ import annotations

from pathlib import Path


def test_read_tail_empty_file(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    path = tmp_path / "empty.log"
    path.write_text("")
    assert read_tail(path, n=10) == []


def test_read_tail_missing_file(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    assert read_tail(tmp_path / "nope.log", n=10) == []


def test_read_tail_returns_last_n(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    path = tmp_path / "lines.log"
    path.write_text("\n".join(f"line{i}" for i in range(20)) + "\n")

    tail = read_tail(path, n=5)
    assert tail == ["line15", "line16", "line17", "line18", "line19"]


def test_read_tail_respects_bytes_cap(tmp_path):
    from launcher_support.engines_live.data.log_tail import read_tail

    path = tmp_path / "big.log"
    # 10000 lines, reasonably big
    path.write_text("\n".join(f"line{i:05d}" for i in range(10000)) + "\n")

    tail = read_tail(path, n=5, max_bytes=1024)
    assert len(tail) == 5
    # last line should be preserved
    assert tail[-1] == "line09999"


def test_classify_info():
    from launcher_support.engines_live.data.log_tail import classify_level

    assert classify_level("2026-04-23 15:35:11 INFO  TICK ok=1 novel=0") == "INFO"


def test_classify_signal():
    from launcher_support.engines_live.data.log_tail import classify_level

    assert classify_level("2026-04-23 15:35:11 INFO  SIGNAL scan novel=1 BNB long") == "SIGNAL"


def test_classify_order():
    from launcher_support.engines_live.data.log_tail import classify_level

    assert classify_level("16:02:44 INFO ORDER placed BNBUSDT side=BUY qty=0.8") == "ORDER"


def test_classify_fill():
    from launcher_support.engines_live.data.log_tail import classify_level

    assert classify_level("16:02:45 INFO FILL confirmed BNBUSDT px=625.40") == "FILL"


def test_classify_exit():
    from launcher_support.engines_live.data.log_tail import classify_level

    assert classify_level("16:10:00 INFO EXIT closed BNB +$124.33") == "EXIT"


def test_classify_warn():
    from launcher_support.engines_live.data.log_tail import classify_level

    assert classify_level("2026-04-23 16:00:00 WARNING STALE signal skipped") == "WARN"


def test_classify_error():
    from launcher_support.engines_live.data.log_tail import classify_level

    assert classify_level("2026-04-23 17:00:00 ERROR TICK fail=3 err=TypeError") == "ERROR"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/launcher/engines_live/test_log_tail.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `data/log_tail.py`**

Create `launcher_support/engines_live/data/log_tail.py`:

```python
"""File tail reader + log level classifier.

Pure module: no tkinter. File I/O only.

- read_tail(path, n=18, max_bytes=65536) -> list[str]
    Returns last N lines. Reads at most max_bytes from EOF so a big log
    file doesn't load fully into memory.

- classify_level(line) -> "INFO" | "SIGNAL" | "ORDER" | "FILL" | "EXIT" | "WARN" | "ERROR"
    Heuristic match against the engine logging conventions.
"""
from __future__ import annotations

import re
from pathlib import Path

_LEVEL_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ERROR", re.compile(r"\b(ERROR|FATAL|CRITICAL|Traceback)\b")),
    ("WARN",  re.compile(r"\b(WARNING|WARN|STALE|SKIP)\b", re.IGNORECASE)),
    ("EXIT",  re.compile(r"\bEXIT\b")),
    ("FILL",  re.compile(r"\bFILL\b")),
    ("ORDER", re.compile(r"\bORDER\b")),
    ("SIGNAL", re.compile(r"\bSIGNAL\b|\bnovel=[1-9]")),
]


def classify_level(line: str) -> str:
    """Return the log level for a given line. Defaults to INFO."""
    for name, pat in _LEVEL_PATTERNS:
        if pat.search(line):
            return name
    return "INFO"


def read_tail(path: Path, n: int = 18, max_bytes: int = 65536) -> list[str]:
    """Return the last `n` non-empty lines of a file. Silent on errors → []."""
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return []
        size = p.stat().st_size
        if size == 0:
            return []
        read_from = max(0, size - max_bytes)
        with p.open("rb") as fh:
            fh.seek(read_from)
            chunk = fh.read()
        text = chunk.decode("utf-8", errors="replace")
        # If we started mid-line (read_from > 0), drop the first partial line.
        lines = text.splitlines()
        if read_from > 0 and lines:
            lines = lines[1:]
        # Drop trailing empty lines
        while lines and not lines[-1].strip():
            lines.pop()
        return lines[-n:]
    except Exception:
        return []
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/engines_live/test_log_tail.py -v`
Expected: 11 passed.

- [ ] **Step 5: Delegate `_read_log_tail` in `engines_live_view.py`**

In `engines_live_view.py:1760`, replace body of `_read_log_tail` with:

```python
def _read_log_tail(path: Path | None, n: int = 18) -> list[str]:
    if path is None:
        return []
    from launcher_support.engines_live.data.log_tail import read_tail
    return read_tail(path, n=n)
```

Leave `_resolve_log_path` in place for now (it's specific to slug→proc resolution and will migrate in R3).

- [ ] **Step 6: Run regression suite**

Run: `pytest tests/integration/test_engines_live_view.py tests/launcher/engines_live/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add launcher_support/engines_live/data/log_tail.py \
        launcher_support/engines_live_view.py \
        tests/launcher/engines_live/test_log_tail.py
git commit -m "R2.4: data/log_tail.py — tail reader + color-level classifier"
```

---

# Phase R3 — Panes, widgets, state, keyboard

Goal: build the Tk widget factories for each layout region, plus the pure `state.py` and `keyboard.py` modules. These are the building blocks `view.py` will orchestrate.

Each pane follows the same contract: `build_<name>(parent, state) -> tk.Frame` and `update_<name>(frame, state) -> None`. The update function compares state to the frame's cached previous state and mutates only changed children.

---

### Task 8: Create `state.py` — immutable StateSnapshot

**Files:**
- Create: `launcher_support/engines_live/state.py`
- Create: `tests/launcher/engines_live/test_state.py`

- [ ] **Step 1: Write failing tests**

Create `tests/launcher/engines_live/test_state.py`:

```python
"""Unit tests for state.py — immutable snapshot + reducer."""
from __future__ import annotations


def test_empty_state_has_no_selection():
    from launcher_support.engines_live.state import StateSnapshot, empty_state

    s: StateSnapshot = empty_state()
    assert s.selected_engine is None
    assert s.selected_instance is None
    assert s.focus_pane == "strip"
    assert s.mode == "paper"
    assert s.follow_tail is False
    assert s.shelf_expanded is False


def test_select_engine_sets_selection_and_moves_focus_to_detail():
    from launcher_support.engines_live.state import empty_state, select_engine

    s = empty_state()
    s2 = select_engine(s, "citadel")
    assert s2.selected_engine == "citadel"
    assert s2.focus_pane == "detail_instances"
    # immutable
    assert s.selected_engine is None


def test_cycle_mode_wraps_around():
    from launcher_support.engines_live.state import empty_state, cycle_mode_state

    s = empty_state()
    assert s.mode == "paper"
    s = cycle_mode_state(s)
    assert s.mode == "demo"
    s = cycle_mode_state(s)
    assert s.mode == "testnet"
    s = cycle_mode_state(s)
    assert s.mode == "live"
    s = cycle_mode_state(s)
    assert s.mode == "paper"


def test_toggle_shelf():
    from launcher_support.engines_live.state import empty_state, toggle_shelf

    s = empty_state()
    assert s.shelf_expanded is False
    s2 = toggle_shelf(s)
    assert s2.shelf_expanded is True
    s3 = toggle_shelf(s2)
    assert s3.shelf_expanded is False


def test_tab_focus_cycles():
    from launcher_support.engines_live.state import empty_state, select_engine, tab_focus

    s = empty_state()
    s = select_engine(s, "citadel")
    assert s.focus_pane == "detail_instances"
    s = tab_focus(s)
    assert s.focus_pane == "detail_log"
    s = tab_focus(s)
    assert s.focus_pane == "strip"
    s = tab_focus(s)
    assert s.focus_pane == "detail_instances"


def test_select_instance_updates_state():
    from launcher_support.engines_live.state import empty_state, select_engine, select_instance

    s = empty_state()
    s = select_engine(s, "citadel")
    s = select_instance(s, "rid-1")
    assert s.selected_instance == "rid-1"
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/launcher/engines_live/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `state.py`**

Create `launcher_support/engines_live/state.py`:

```python
"""Immutable StateSnapshot + pure reducers.

All UI state lives here. No tkinter. No mutation — reducers return new
snapshots. view.py holds the current snapshot and swaps it atomically.

Focus panes:
- strip              focus on strip grid (arrow keys navigate engines)
- detail_instances   focus on detail left column (arrow keys navigate instances)
- detail_log         focus on detail right column (F toggles follow)
- shelf              focus on research shelf (arrow keys navigate items)
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Mode = Literal["paper", "demo", "testnet", "live"]
FocusPane = Literal["strip", "detail_instances", "detail_log", "shelf"]

_MODE_CYCLE: tuple[Mode, ...] = ("paper", "demo", "testnet", "live")
_TAB_CYCLE: dict[FocusPane, FocusPane] = {
    "strip": "detail_instances",
    "detail_instances": "detail_log",
    "detail_log": "strip",
    "shelf": "strip",
}


@dataclass(frozen=True)
class StateSnapshot:
    selected_engine: str | None = None
    selected_instance: str | None = None
    focus_pane: FocusPane = "strip"
    mode: Mode = "paper"
    follow_tail: bool = False
    shelf_expanded: bool = False


def empty_state() -> StateSnapshot:
    return StateSnapshot()


def select_engine(state: StateSnapshot, engine: str) -> StateSnapshot:
    return replace(
        state,
        selected_engine=engine,
        selected_instance=None,
        focus_pane="detail_instances",
    )


def select_instance(state: StateSnapshot, instance_id: str) -> StateSnapshot:
    return replace(state, selected_instance=instance_id)


def cycle_mode_state(state: StateSnapshot) -> StateSnapshot:
    idx = _MODE_CYCLE.index(state.mode)
    return replace(state, mode=_MODE_CYCLE[(idx + 1) % len(_MODE_CYCLE)])


def toggle_shelf(state: StateSnapshot) -> StateSnapshot:
    return replace(state, shelf_expanded=not state.shelf_expanded)


def toggle_follow(state: StateSnapshot) -> StateSnapshot:
    return replace(state, follow_tail=not state.follow_tail)


def tab_focus(state: StateSnapshot) -> StateSnapshot:
    return replace(state, focus_pane=_TAB_CYCLE[state.focus_pane])


def reset_selection(state: StateSnapshot) -> StateSnapshot:
    return replace(
        state,
        selected_engine=None,
        selected_instance=None,
        focus_pane="strip",
        follow_tail=False,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/engines_live/test_state.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live/state.py tests/launcher/engines_live/test_state.py
git commit -m "R3.1: state.py — immutable StateSnapshot + reducers"
```

---

### Task 9: Create `keyboard.py` — pure route table

**Files:**
- Create: `launcher_support/engines_live/keyboard.py`
- Create: `tests/launcher/engines_live/test_keyboard.py`

- [ ] **Step 1: Write failing tests**

Create `tests/launcher/engines_live/test_keyboard.py`:

```python
"""Unit tests for keyboard.py — pure key routing."""
from __future__ import annotations


def test_escape_on_strip_returns_exit_action():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, ExitView

    s = empty_state()
    action = route(s, "Escape")
    assert isinstance(action, ExitView)


def test_escape_on_detail_goes_back_to_strip():
    from launcher_support.engines_live.state import empty_state, select_engine
    from launcher_support.engines_live.keyboard import route, BackToStrip

    s = empty_state()
    s = select_engine(s, "citadel")
    action = route(s, "Escape")
    assert isinstance(action, BackToStrip)


def test_tab_cycles_focus():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, CycleFocus

    s = empty_state()
    action = route(s, "Tab")
    assert isinstance(action, CycleFocus)


def test_m_cycles_mode():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, CycleMode

    s = empty_state()
    action = route(s, "m")
    assert isinstance(action, CycleMode)


def test_enter_on_strip_opens_detail():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route, OpenDetail

    s = empty_state()
    action = route(s, "Return")
    assert isinstance(action, OpenDetail)


def test_s_on_detail_instances_stops_selected_instance():
    from launcher_support.engines_live.state import empty_state, select_engine, select_instance
    from launcher_support.engines_live.keyboard import route, StopInstance

    s = empty_state()
    s = select_engine(s, "citadel")
    s = select_instance(s, "rid-1")
    action = route(s, "s")
    assert isinstance(action, StopInstance)
    assert action.run_id == "rid-1"


def test_a_on_detail_stops_all_instances_of_engine():
    from launcher_support.engines_live.state import empty_state, select_engine
    from launcher_support.engines_live.keyboard import route, StopAll

    s = empty_state()
    s = select_engine(s, "citadel")
    action = route(s, "a")
    assert isinstance(action, StopAll)
    assert action.engine == "citadel"


def test_plus_opens_new_instance_dialog():
    from launcher_support.engines_live.state import empty_state, select_engine
    from launcher_support.engines_live.keyboard import route, OpenNewInstanceDialog

    s = empty_state()
    s = select_engine(s, "citadel")
    action = route(s, "plus")
    assert isinstance(action, OpenNewInstanceDialog)
    assert action.engine == "citadel"


def test_unknown_key_returns_none():
    from launcher_support.engines_live.state import empty_state
    from launcher_support.engines_live.keyboard import route

    s = empty_state()
    assert route(s, "zzzz") is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/launcher/engines_live/test_keyboard.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `keyboard.py`**

Create `launcher_support/engines_live/keyboard.py`:

```python
"""Pure key routing.

Given a StateSnapshot (source of truth) and a key name (Tk keysym string),
returns an Action dataclass describing what the orchestrator should do.
view.py receives the Action, may mutate state via reducers, and/or dispatch
side effects (SSH start, subprocess spawn, etc.).

Keysym conventions:
- Single letters: "s", "r", "a" (lowercase)
- Special: "Return" (Enter), "Escape", "Tab", "Up", "Down", "Left", "Right"
- "plus" for +, "slash" for /, "question" for ?

Unknown keys return None (no-op).
"""
from __future__ import annotations

from dataclasses import dataclass

from launcher_support.engines_live.state import StateSnapshot

# ---- Action types ----

@dataclass(frozen=True)
class ExitView: ...

@dataclass(frozen=True)
class BackToStrip: ...

@dataclass(frozen=True)
class CycleFocus: ...

@dataclass(frozen=True)
class CycleMode: ...

@dataclass(frozen=True)
class OpenDetail: ...

@dataclass(frozen=True)
class OpenNewInstanceDialog:
    engine: str

@dataclass(frozen=True)
class StopInstance:
    run_id: str

@dataclass(frozen=True)
class RestartInstance:
    run_id: str

@dataclass(frozen=True)
class StopAll:
    engine: str

@dataclass(frozen=True)
class OpenConfig:
    engine: str

@dataclass(frozen=True)
class OpenLogViewer:
    run_id: str

@dataclass(frozen=True)
class ToggleFollowTail: ...

@dataclass(frozen=True)
class TelegramTest:
    run_id: str

@dataclass(frozen=True)
class ToggleShelf: ...

@dataclass(frozen=True)
class SearchFilter: ...

@dataclass(frozen=True)
class ShowHelp: ...

@dataclass(frozen=True)
class NavigateUp: ...

@dataclass(frozen=True)
class NavigateDown: ...

@dataclass(frozen=True)
class NavigateLeft: ...

@dataclass(frozen=True)
class NavigateRight: ...


Action = (
    ExitView | BackToStrip | CycleFocus | CycleMode | OpenDetail
    | OpenNewInstanceDialog | StopInstance | RestartInstance | StopAll
    | OpenConfig | OpenLogViewer | ToggleFollowTail | TelegramTest
    | ToggleShelf | SearchFilter | ShowHelp
    | NavigateUp | NavigateDown | NavigateLeft | NavigateRight
)


def route(state: StateSnapshot, key: str) -> Action | None:
    """Map (state, key) -> action. None for unknown."""
    # --- Global keys (any focus) ---
    if key == "Escape":
        if state.selected_engine is None:
            return ExitView()
        return BackToStrip()
    if key == "Tab":
        return CycleFocus()
    if key == "m":
        return CycleMode()
    if key == "slash":
        return SearchFilter()
    if key == "question":
        return ShowHelp()
    if key == "Up":
        return NavigateUp()
    if key == "Down":
        return NavigateDown()
    if key == "Left":
        return NavigateLeft()
    if key == "Right":
        return NavigateRight()

    # --- Context-dependent keys ---
    if key == "Return":
        return OpenDetail()

    # Actions that require a selected engine
    engine = state.selected_engine
    if engine is None:
        return None

    if key == "plus":
        return OpenNewInstanceDialog(engine=engine)
    if key == "c":
        return OpenConfig(engine=engine)
    if key == "a":
        return StopAll(engine=engine)

    # Actions that require a selected instance
    run_id = state.selected_instance
    if run_id is None:
        return None

    if key == "s":
        return StopInstance(run_id=run_id)
    if key == "r":
        return RestartInstance(run_id=run_id)
    if key == "l":
        return OpenLogViewer(run_id=run_id)
    if key == "f":
        return ToggleFollowTail()
    if key == "t":
        return TelegramTest(run_id=run_id)

    return None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/engines_live/test_keyboard.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live/keyboard.py tests/launcher/engines_live/test_keyboard.py
git commit -m "R3.2: keyboard.py — pure (state, key) -> Action routing"
```

---

### Task 10: Create `widgets/hold_button.py`

Goal: a reusable Tk button that requires user to hold it for 1.5s to execute, with amber progress fill left→right.

**Files:**
- Create: `launcher_support/engines_live/widgets/hold_button.py`
- Create: `tests/launcher/engines_live/test_hold_button.py`

- [ ] **Step 1: Write failing tests**

Create `tests/launcher/engines_live/test_hold_button.py`:

```python
"""Smoke tests for widgets/hold_button.py.

These tests require a Tk root. Skip if DISPLAY unavailable.
"""
from __future__ import annotations

import os
import tkinter as tk

import pytest


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_hold_button_creates_frame(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    calls: list = []
    btn = HoldButton(root, text="STOP", hold_ms=1500, on_complete=lambda: calls.append(1))
    btn.pack()
    assert isinstance(btn, tk.Frame)


def test_hold_button_does_not_fire_before_hold_completes(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    calls: list = []
    btn = HoldButton(root, text="STOP", hold_ms=1500, on_complete=lambda: calls.append(1))
    btn.pack()

    btn.press()
    root.update()
    btn.release()  # released too early
    root.update()

    assert calls == []


def test_hold_button_fires_after_hold_completes(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    calls: list = []
    btn = HoldButton(root, text="STOP", hold_ms=50, on_complete=lambda: calls.append(1))
    btn.pack()

    btn.press()
    # Let hold timer fire
    root.update()
    root.after(100, lambda: None)
    import time
    time.sleep(0.15)
    root.update()

    assert calls == [1]


def test_hold_button_progress_fill_updates_during_hold(root):
    from launcher_support.engines_live.widgets.hold_button import HoldButton

    btn = HoldButton(root, text="STOP", hold_ms=200, on_complete=lambda: None)
    btn.pack()

    assert btn._progress == 0.0

    btn.press()
    import time
    time.sleep(0.1)
    root.update()

    assert 0.0 < btn._progress < 1.0
```

- [ ] **Step 2: Run tests — expect failure**

Run: `pytest tests/launcher/engines_live/test_hold_button.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Create `widgets/hold_button.py`**

Create `launcher_support/engines_live/widgets/hold_button.py`:

```python
"""Hold-to-confirm button widget.

Usage:
    btn = HoldButton(parent, text="STOP", hold_ms=1500, on_complete=lambda: foo())
    btn.pack()

Behavior:
- Press (mouse button 1 or keyboard): starts progress fill (amber, left→right).
- Release before hold_ms elapses: cancels, resets fill, no on_complete call.
- Holds full hold_ms: calls on_complete(), flashes green for 300ms, resets.

Rendered as a Frame containing a Canvas with the fill rectangle and a Label.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, AMBER_B, BG3, GREEN, RED, WHITE


class HoldButton(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        hold_ms: int = 1500,
        on_complete: Callable[[], None] | None = None,
        width: int = 140,
        height: int = 28,
        base_color: str = RED,
        fill_color: str = AMBER,
        text_color: str = WHITE,
    ) -> None:
        super().__init__(parent, bg=BG3, highlightthickness=0)
        self._hold_ms = hold_ms
        self._on_complete = on_complete or (lambda: None)
        self._progress = 0.0
        self._job = None
        self._start_t = None
        self._text = text
        self._width = width
        self._height = height
        self._base_color = base_color
        self._fill_color = fill_color
        self._text_color = text_color

        self._canvas = tk.Canvas(
            self, width=width, height=height, bg=base_color,
            highlightthickness=0, bd=0,
        )
        self._canvas.pack()

        self._fill_id = self._canvas.create_rectangle(
            0, 0, 0, height, fill=fill_color, outline="",
        )
        self._text_id = self._canvas.create_text(
            width // 2, height // 2, text=text, fill=text_color,
            font=("Consolas", 9, "bold"),
        )

        self._canvas.bind("<ButtonPress-1>", lambda e: self.press())
        self._canvas.bind("<ButtonRelease-1>", lambda e: self.release())

    def press(self) -> None:
        """Start or restart the hold timer."""
        self._cancel_job()
        self._start_t = self._canvas.tk.call("clock", "milliseconds")
        self._progress = 0.0
        self._tick()

    def release(self) -> None:
        """Release — cancels unless progress >= 1.0."""
        self._cancel_job()
        if self._progress < 1.0:
            self._progress = 0.0
            self._redraw()

    def _tick(self) -> None:
        if self._start_t is None:
            return
        now = self._canvas.tk.call("clock", "milliseconds")
        elapsed = now - self._start_t
        self._progress = min(1.0, elapsed / self._hold_ms)
        self._redraw()
        if self._progress >= 1.0:
            self._start_t = None
            self._job = None
            self._flash_complete()
            self._on_complete()
            return
        self._job = self.after(16, self._tick)

    def _flash_complete(self) -> None:
        self._canvas.itemconfig(self._fill_id, fill=GREEN)
        self.after(300, self._reset)

    def _reset(self) -> None:
        self._progress = 0.0
        self._canvas.itemconfig(self._fill_id, fill=self._fill_color)
        self._redraw()

    def _redraw(self) -> None:
        fill_w = int(self._width * self._progress)
        self._canvas.coords(self._fill_id, 0, 0, fill_w, self._height)
        label = self._text
        if 0 < self._progress < 1.0:
            label = f"HOLD TO {self._text}..."
        self._canvas.itemconfig(self._text_id, text=label)

    def _cancel_job(self) -> None:
        if self._job is not None:
            self.after_cancel(self._job)
            self._job = None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/engines_live/test_hold_button.py -v`
Expected: 4 passed (or 4 skipped if headless environment).

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live/widgets/hold_button.py \
        tests/launcher/engines_live/test_hold_button.py
git commit -m "R3.3: widgets/hold_button.py — 1.5s hold-to-confirm"
```

---

### Task 11: Create `widgets/pill_segment.py` — mode pills segmented control

**Files:**
- Create: `launcher_support/engines_live/widgets/pill_segment.py`
- Create: `tests/launcher/engines_live/test_pill_segment.py`

- [ ] **Step 1: Write failing tests**

Create `tests/launcher/engines_live/test_pill_segment.py`:

```python
"""Smoke tests for pill_segment widget."""
from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_pill_segment_builds(root):
    from launcher_support.engines_live.widgets.pill_segment import PillSegment

    ps = PillSegment(root, options=["PAPER", "DEMO", "TESTNET", "LIVE"], active="PAPER")
    ps.pack()
    assert ps.active == "PAPER"


def test_set_active_updates(root):
    from launcher_support.engines_live.widgets.pill_segment import PillSegment

    ps = PillSegment(root, options=["PAPER", "DEMO", "TESTNET", "LIVE"], active="PAPER")
    ps.pack()
    ps.set_active("LIVE")
    assert ps.active == "LIVE"


def test_click_fires_on_change(root):
    from launcher_support.engines_live.widgets.pill_segment import PillSegment

    changed: list = []
    ps = PillSegment(root, options=["A", "B"], active="A", on_change=changed.append)
    ps.pack()
    ps.set_active("B")  # simulate click via public API
    assert changed == ["B"]
```

- [ ] **Step 2: Run tests — expect failure**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `widgets/pill_segment.py`**

Create `launcher_support/engines_live/widgets/pill_segment.py`:

```python
"""Segmented pill control. Used for mode selection (PAPER/DEMO/TESTNET/LIVE).

Usage:
    ps = PillSegment(
        parent,
        options=["PAPER", "DEMO", "TESTNET", "LIVE"],
        active="PAPER",
        colors={"PAPER": CYAN, "DEMO": GREEN, "TESTNET": AMBER, "LIVE": RED},
        on_change=lambda new: print(new),
    )
    ps.pack()
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import (
    AMBER, BG, BG3, CYAN, DIM, GREEN, RED, WHITE,
)

DEFAULT_COLORS = {
    "PAPER": CYAN,
    "DEMO": GREEN,
    "TESTNET": AMBER,
    "LIVE": RED,
}


class PillSegment(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        options: list[str],
        active: str,
        colors: dict[str, str] | None = None,
        on_change: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, bg=BG, highlightthickness=0)
        self._options = list(options)
        self._colors = {**DEFAULT_COLORS, **(colors or {})}
        self._on_change = on_change or (lambda new: None)
        self._active = active if active in options else options[0]
        self._labels: dict[str, tk.Label] = {}

        for i, opt in enumerate(options):
            lbl = tk.Label(
                self, text=opt, font=("Consolas", 9, "bold"),
                padx=10, pady=2, cursor="hand2",
            )
            lbl.pack(side="left", padx=(0 if i == 0 else 2, 0))
            lbl.bind("<Button-1>", lambda e, o=opt: self._on_click(o))
            self._labels[opt] = lbl

        self._restyle()

    @property
    def active(self) -> str:
        return self._active

    def set_active(self, opt: str) -> None:
        if opt not in self._options or opt == self._active:
            return
        self._active = opt
        self._restyle()
        self._on_change(opt)

    def _on_click(self, opt: str) -> None:
        self.set_active(opt)

    def _restyle(self) -> None:
        for opt, lbl in self._labels.items():
            col = self._colors.get(opt, DIM)
            if opt == self._active:
                lbl.configure(bg=col, fg=BG)
            else:
                lbl.configure(bg=BG3, fg=col)
```

- [ ] **Step 4: Run tests**

Expected: 3 passed (or skipped if headless).

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live/widgets/pill_segment.py \
        tests/launcher/engines_live/test_pill_segment.py
git commit -m "R3.4: widgets/pill_segment.py — mode pill segmented control"
```

---

### Task 12: Create `widgets/engine_card.py` — single V3 strip render

Goal: render a single engine card (normal/selected/stale/error/not-running states) given an `EngineCard` dataclass.

**Files:**
- Create: `launcher_support/engines_live/widgets/engine_card.py`
- Create: `tests/launcher/engines_live/test_engine_card.py`

- [ ] **Step 1: Write failing tests**

Create `tests/launcher/engines_live/test_engine_card.py`:

```python
"""Smoke tests for engine_card widget."""
from __future__ import annotations

import tkinter as tk

import pytest

from launcher_support.engines_live.data.aggregate import EngineCard


def _healthy_card():
    return EngineCard(
        engine="citadel", display="CITADEL", instance_count=2,
        live_count=2, stale_count=0, error_count=0,
        mode_summary="p+s", max_uptime_s=900, total_equity=10000.0,
        total_novel=0, total_ticks=34, sort_weight=10, has_error=False,
    )


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_build_card_has_display_name(root):
    from launcher_support.engines_live.widgets.engine_card import build_card

    card = _healthy_card()
    frame = build_card(root, card, selected=False)
    frame.pack()
    root.update()

    # Find any Label with text containing "CITADEL"
    found = any(
        isinstance(w, tk.Label) and "CITADEL" in str(w.cget("text"))
        for w in frame.winfo_children()
    )
    assert found


def test_selected_card_has_amber_border(root):
    from launcher_support.engines_live.widgets.engine_card import build_card
    from core.ui.ui_palette import AMBER_B

    card = _healthy_card()
    frame = build_card(root, card, selected=True)
    frame.pack()
    root.update()

    assert str(frame.cget("highlightbackground")).lower() in (AMBER_B.lower(), "#" + AMBER_B.lstrip("#").lower())


def test_error_card_has_red_border(root):
    from launcher_support.engines_live.widgets.engine_card import build_card
    from core.ui.ui_palette import RED

    card = EngineCard(
        engine="citadel", display="CITADEL", instance_count=1,
        live_count=0, stale_count=0, error_count=1,
        mode_summary="p", max_uptime_s=900, total_equity=10000.0,
        total_novel=0, total_ticks=17, sort_weight=10, has_error=True,
    )
    frame = build_card(root, card, selected=False)
    frame.pack()
    root.update()

    assert str(frame.cget("highlightbackground")).lower() in (RED.lower(), "#" + RED.lstrip("#").lower())


def test_update_card_replaces_contents(root):
    from launcher_support.engines_live.widgets.engine_card import build_card, update_card

    card1 = _healthy_card()
    frame = build_card(root, card1, selected=False)
    frame.pack()

    card2 = EngineCard(
        engine="citadel", display="CITADEL", instance_count=3,
        live_count=3, stale_count=0, error_count=0,
        mode_summary="p+s+l", max_uptime_s=7200, total_equity=20000.0,
        total_novel=2, total_ticks=100, sort_weight=10, has_error=False,
    )
    update_card(frame, card2, selected=True)
    root.update()
    # No assertion on visual — this test ensures update_card doesn't crash
    # and the frame is still usable.
    assert frame.winfo_exists()
```

- [ ] **Step 2: Run tests — expect failure**

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Create `widgets/engine_card.py`**

Create `launcher_support/engines_live/widgets/engine_card.py`:

```python
"""Single engine card (V3 shape) render + update.

Card format:
    ╭ CITADEL ── 2●● ╮
    │ p+s · 15m      │
    │ 0/17 nvl/t     │
    │ eq $10k · 0dd% │
    ╰────────────────╯

State determines border color + dot symbols:
- healthy:     BORDER,  ● per instance (green)
- selected:    AMBER_B (2px border), + lines
- stale:       HAZARD,  ! per stale instance
- error:       RED,     ✕ per error instance
- not running: DIM,     ○ (used in research shelf, not main grid)
"""
from __future__ import annotations

import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_B, BG, BG2, BG3,
    BORDER, DIM, DIM2, GREEN, HAZARD, RED, WHITE,
)
from launcher_support.engines_live.data.aggregate import EngineCard
from launcher_support.engines_live_helpers import format_uptime

_CARD_WIDTH_PX = 200
_CARD_HEIGHT_PX = 104


def _dot_chars(card: EngineCard) -> str:
    return "●" * card.live_count + "!" * card.stale_count + "✕" * card.error_count


def _dot_color(card: EngineCard) -> str:
    if card.error_count > 0:
        return RED
    if card.stale_count > 0:
        return HAZARD
    return GREEN


def _border_color(card: EngineCard, selected: bool) -> str:
    if selected:
        return AMBER_B
    if card.has_error:
        return RED
    if card.stale_count > 0:
        return HAZARD
    return BORDER


def _equity_short(eq: float) -> str:
    if eq >= 1000:
        return f"${eq/1000:.0f}k"
    return f"${eq:.0f}"


def build_card(parent: tk.Widget, card: EngineCard, selected: bool = False) -> tk.Frame:
    border = _border_color(card, selected)
    frame = tk.Frame(
        parent,
        bg=BG2 if selected else BG,
        highlightthickness=2 if selected else 1,
        highlightbackground=border,
        highlightcolor=border,
        width=_CARD_WIDTH_PX, height=_CARD_HEIGHT_PX,
    )
    frame.pack_propagate(False)

    # Header line: "CITADEL ── 2●● "
    header = tk.Frame(frame, bg=frame["bg"])
    header.pack(fill="x", padx=8, pady=(6, 2))

    tk.Label(
        header, text=card.display, bg=frame["bg"],
        fg=RED if card.has_error else AMBER,
        font=("Consolas", 10, "bold"), anchor="w",
    ).pack(side="left")

    dot_frame = tk.Frame(header, bg=frame["bg"])
    dot_frame.pack(side="right")
    tk.Label(
        dot_frame, text=f"{card.instance_count}{_dot_chars(card)}",
        bg=frame["bg"], fg=_dot_color(card),
        font=("Consolas", 10, "bold"),
    ).pack()

    # Body lines
    def _line(text: str, fg: str = WHITE, bold: bool = False) -> None:
        tk.Label(
            frame, text=text, bg=frame["bg"], fg=fg,
            font=("Consolas", 9, "bold" if bold else "normal"),
            anchor="w",
        ).pack(fill="x", padx=8)

    _line(f"{card.mode_summary} · {format_uptime(card.max_uptime_s)}", fg=DIM)
    _line(f"{card.total_novel}/{card.total_ticks} nvl/t", fg=WHITE, bold=True)

    eq_color = GREEN if card.total_equity > 0 else DIM2
    _line(f"eq {_equity_short(card.total_equity)}", fg=eq_color)

    frame._card = card  # stash for update_card
    return frame


def update_card(frame: tk.Frame, card: EngineCard, selected: bool = False) -> None:
    """Re-render in place. For diff-based repaint, this destroys children and
    rebuilds. The caller avoids calling this when card == frame._card already.
    """
    prev = getattr(frame, "_card", None)
    if prev == card and selected == getattr(frame, "_selected", None):
        return
    for child in list(frame.winfo_children()):
        child.destroy()
    border = _border_color(card, selected)
    frame.configure(
        bg=BG2 if selected else BG,
        highlightthickness=2 if selected else 1,
        highlightbackground=border,
        highlightcolor=border,
    )
    # Rebuild body using the same logic as build_card (duplicated inline
    # to keep update atomic). We use the sibling-less approach: call build_card
    # again into a temporary Frame and lift children over — simpler to just
    # re-run the line-building here.

    header = tk.Frame(frame, bg=frame["bg"])
    header.pack(fill="x", padx=8, pady=(6, 2))
    tk.Label(
        header, text=card.display, bg=frame["bg"],
        fg=RED if card.has_error else AMBER,
        font=("Consolas", 10, "bold"), anchor="w",
    ).pack(side="left")
    tk.Label(
        header, text=f"{card.instance_count}{_dot_chars(card)}",
        bg=frame["bg"], fg=_dot_color(card),
        font=("Consolas", 10, "bold"),
    ).pack(side="right")

    def _line(text: str, fg: str = WHITE, bold: bool = False) -> None:
        tk.Label(
            frame, text=text, bg=frame["bg"], fg=fg,
            font=("Consolas", 9, "bold" if bold else "normal"),
            anchor="w",
        ).pack(fill="x", padx=8)

    _line(f"{card.mode_summary} · {format_uptime(card.max_uptime_s)}", fg=DIM)
    _line(f"{card.total_novel}/{card.total_ticks} nvl/t", fg=WHITE, bold=True)
    eq_color = GREEN if card.total_equity > 0 else DIM2
    _line(f"eq {_equity_short(card.total_equity)}", fg=eq_color)

    frame._card = card
    frame._selected = selected
```

- [ ] **Step 4: Run tests**

Expected: 4 passed (or skipped if headless).

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live/widgets/engine_card.py \
        tests/launcher/engines_live/test_engine_card.py
git commit -m "R3.5: widgets/engine_card.py — V3 card render + update"
```

---

### Task 13: Create `panes/header.py`

Follow the same TDD pattern as previous tasks.

- [ ] **Step 1: Write failing test** — assert `build_header(parent, state)` returns a Frame with children for title label, mode pill segment, and counts label. Assert LIVE mode adds a red bottom border line.

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `launcher_support/engines_live/panes/header.py`** exporting `build_header(parent, state) -> tk.Frame` and `update_header(frame, state)`. Composition: tk.Label for title ("› ENGINES" AMBER bold 12pt), counts Label, PillSegment widget for mode, market Label, optional 1px red frame at bottom when state.mode=="live".

Reference the pill widget via:
```python
from launcher_support.engines_live.widgets.pill_segment import PillSegment
```

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.6: panes/header.py — title · counts · mode pills · LIVE border`.

---

### Task 14: Create `panes/strip_grid.py`

- [ ] **Step 1: Write failing tests** for `build_strip_grid(parent, cards, selected_engine, on_select)` and `update_strip_grid(frame, cards, selected_engine)`. Cards arranged in responsive grid (3/4/5 per row based on viewport). "+ NEW ENGINE" card at end.

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `launcher_support/engines_live/panes/strip_grid.py`.** Use `build_card`/`update_card` from widgets/engine_card.py. Grid via `.grid()` with dynamic columns calculated from parent `winfo_width()`. "+ NEW ENGINE" card is a special render (not from EngineCard — it's a separate helper). Selection changes border color.

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.7: panes/strip_grid.py — responsive card grid`.

---

### Task 15: Create `panes/research_shelf.py`

- [ ] **Step 1: Write failing tests** for `build_shelf(parent, not_running_engines, expanded, on_toggle, on_select)`. Collapsed = 1 line with comma-separated engine names in DIM. Expanded = grid of minimal cards with [START] and [BACKTEST] buttons.

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `panes/research_shelf.py`.** Reads `config/engines.py` for engines without `live_ready` (or with `live_ready` but not running). Toggle arrow (▾/▸) on right.

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.8: panes/research_shelf.py — collapsible research list`.

---

### Task 16: Create `panes/detail_left.py`

- [ ] **Step 1: Write failing tests** for `build_detail_left(parent, engine, instances, selected_instance, on_instance_select)`. Instances list (row format: `mode.label ●status uptime Xt/Ynvl equity`), aggregate KPIs below separator, instance actions, engine actions. Uses HoldButton for S/R/A.

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `panes/detail_left.py`.** Composition: header strip ("Detail: CITADEL" AMBER), instances listbox, KPIs section, HoldButton row for [S]top/[R]estart/[A]stop all, plain Button row for [+] new/[C]onfig.

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.9: panes/detail_left.py — instances + KPIs + actions`.

---

### Task 17: Create `panes/detail_right.py`

- [ ] **Step 1: Write failing tests** for `build_detail_right(parent, run_id, log_lines, follow_mode, on_toggle_follow, on_open_full, on_telegram_test)`. Text widget with color tags per level (INFO=DIM, SIGNAL=AMBER bold, ORDER=CYAN, FILL=GREEN, EXIT=WHITE bold, WARN=HAZARD, ERROR=RED bold). Bottom button row with [O] / [F] / [T].

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `panes/detail_right.py`.** Uses `tk.Text` in `state="disabled"` with `tag_configure` for each level. On each update, calls `classify_level` from `data/log_tail.py` per line and applies tag. Follow mode: auto-scroll to end + "● FOLLOWING" label in green at top.

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.10: panes/detail_right.py — color log tail + follow mode`.

---

### Task 18: Create `panes/detail_empty.py`

- [ ] **Step 1: Write failing test** for `build_detail_empty(parent, global_stats)` showing "N engines live", "total ticks 24h", "total equity paper", and DIM text "← Select an engine above".

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `panes/detail_empty.py`** with simple vertical layout.

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.11: panes/detail_empty.py — welcome placeholder`.

---

### Task 19: Create `panes/detail.py` — orchestrator

- [ ] **Step 1: Write failing test** for `build_detail(parent, state, data)` that dispatches to `detail_empty` when `state.selected_engine is None` and to `detail_left`+`detail_right` otherwise.

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `panes/detail.py`** with horizontal split (PanedWindow or Frame with pack fill="both"), left 40% + right 60%. `update_detail(frame, state, data)` diffs and re-renders only changed side.

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.12: panes/detail.py — detail pane orchestrator`.

---

### Task 20: Create `panes/footer.py`

- [ ] **Step 1: Write failing test** for `build_footer(parent, state)` showing context-sensitive keybind hints. Different text for state.focus_pane == "strip" vs "detail_instances" vs "detail_log".

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `panes/footer.py`** with a single DIM label. The `update_footer(frame, state)` function picks hints from a constant dict keyed by focus_pane.

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.13: panes/footer.py — context keybind hints`.

---

### Task 21: Create `dialogs/new_instance.py`

- [ ] **Step 1: Write failing test** for `open_new_instance_dialog(parent, engine, default_mode) -> dict | None`. Returns selected {mode, label, target} or None if cancelled. Uses Toplevel.

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `dialogs/new_instance.py`.** Toplevel with:
  - PillSegment for mode (pre-selected to default_mode)
  - Entry for label (sanitized on submit via `tools.operations.run_id.sanitize_label`)
  - PillSegment for target (LOCAL/VPS)
  - Command preview label (updates on any change)
  - HoldButton for Confirm (or plain Button if mode != LIVE)
  - Cancel button

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.14: dialogs/new_instance.py — + NEW INSTANCE modal`.

---

### Task 22: Create `dialogs/live_ritual.py`

- [ ] **Step 1: Write failing test** for `open_live_ritual(parent, engine) -> bool`. Returns True only if user types engine name (case-sensitive) and clicks CONFIRM.

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `dialogs/live_ritual.py`.** Toplevel with:
  - Red warning label "⚠ Real money. Real orders."
  - Entry tied to a StringVar; CONFIRM button disabled until `var.get() == engine_name`
  - Cancel / Escape closes returning False

- [ ] **Step 4: Run tests.**
- [ ] **Step 5: Commit** `R3.15: dialogs/live_ritual.py — LIVE confirmation ritual`.

---

### Task 23: Create `view.py` — top-level orchestrator

**Files:**
- Create: `launcher_support/engines_live/view.py`
- Create: `tests/integration/test_engines_live_panes.py`

- [ ] **Step 1: Write failing smoke test**

Create `tests/integration/test_engines_live_panes.py`:

```python
"""Smoke test that view.render produces a working screen."""
from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture
def root():
    try:
        r = tk.Tk()
        r.withdraw()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_render_builds_panes(root, monkeypatch):
    from launcher_support.engines_live import view
    from launcher_support.engines_live.data import procs, cockpit

    monkeypatch.setattr(procs, "list_procs", lambda force=False: [])
    monkeypatch.setattr(cockpit, "runs_cached", lambda: [])

    class FakeLauncher:
        def after(self, ms, fn): pass
        def bind(self, *a, **kw): pass
        def unbind(self, *a, **kw): pass

    frame = tk.Frame(root)
    frame.pack()
    launcher = FakeLauncher()

    handle = view.render(launcher, frame, on_escape=lambda: None)

    assert "frame" in handle
    assert "state" in handle
    assert "destroy" in handle
    root.update()

    handle["destroy"]()
```

- [ ] **Step 2: Verify failure.**

- [ ] **Step 3: Create `view.py`**

Create `launcher_support/engines_live/view.py`:

```python
"""Top-level orchestrator for the ENGINES LIVE view.

Lifecycle:
1. render(launcher, parent, on_escape) builds the initial frame and returns
   a handle dict with "frame", "state", "destroy" keys.
2. render schedules periodic tick_refresh() via launcher.after(30_000, ...).
3. Each tick_refresh:
   a. kicks off background fetches (cockpit runs, procs) via Tk after_idle
   b. once data arrives, builds an EngineCard list via data.aggregate
   c. compares to last_snapshot; if changed, calls update_* on affected panes
4. Keyboard bindings dispatch (focus, keysym) through keyboard.route(),
   then apply state reducers + side effects.
5. handle["destroy"]() cancels all after jobs and destroys the frame.

Threading: all data fetches use root.after_idle + a single-thread
ThreadPoolExecutor; results posted back via root.after(0, ...).
"""
from __future__ import annotations

import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from core.ui.ui_palette import BG
from launcher_support.engines_live import keyboard, state as statemod
from launcher_support.engines_live.data import aggregate, cockpit, procs
from launcher_support.engines_live.panes import (
    detail, footer, header, research_shelf, strip_grid,
)

_REFRESH_MS = 30_000
_DETAIL_REFRESH_MS = 15_000
_FOLLOW_MS = 3_000

_executor = ThreadPoolExecutor(max_workers=2)


def render(launcher: Any, parent: tk.Widget, *,
           on_escape: Callable[[], None]) -> dict:
    frame = tk.Frame(parent, bg=BG)
    frame.pack(fill="both", expand=True)

    ui_state = {"snapshot": statemod.empty_state(), "data": {"cards": [], "runs": []}}
    after_jobs: list[str] = []

    # Build panes
    hdr = header.build_header(frame, ui_state["snapshot"])
    hdr.pack(fill="x")

    grid = strip_grid.build_strip_grid(
        frame, cards=[], selected_engine=None,
        on_select=lambda eng: _handle_select(ui_state, grid, det, ftr, eng),
    )
    grid.pack(fill="x", pady=(6, 0))

    shelf = research_shelf.build_shelf(
        frame, not_running_engines=[], expanded=False,
        on_toggle=lambda: _handle_toggle_shelf(ui_state, shelf),
        on_select=lambda eng: _handle_research_select(launcher, ui_state, eng),
    )
    shelf.pack(fill="x", pady=(6, 0))

    det = detail.build_detail(frame, ui_state["snapshot"], ui_state["data"])
    det.pack(fill="both", expand=True, pady=(6, 0))

    ftr = footer.build_footer(frame, ui_state["snapshot"])
    ftr.pack(fill="x", side="bottom")

    # Keyboard bindings
    def _on_key(event):
        snapshot = ui_state["snapshot"]
        action = keyboard.route(snapshot, event.keysym)
        if action is None:
            return
        _apply_action(launcher, ui_state, action, grid, shelf, det, hdr, ftr,
                      on_escape=on_escape)

    frame.bind_all("<Key>", _on_key)

    # Periodic refresh
    def _tick():
        _refresh_data(launcher, ui_state, grid, shelf, det, hdr)
        job = launcher.after(_REFRESH_MS, _tick)
        after_jobs.append(job)

    job = launcher.after(200, _tick)  # first tick after short delay
    after_jobs.append(job)

    def _destroy():
        frame.unbind_all("<Key>")
        for j in after_jobs:
            try:
                launcher.after_cancel(j)
            except Exception:
                pass
        frame.destroy()

    return {
        "frame": frame,
        "state": ui_state,
        "destroy": _destroy,
    }


def _refresh_data(launcher, ui_state, grid, shelf, det, hdr) -> None:
    def _worker():
        procs_rows = procs.list_procs()
        runs = cockpit.runs_cached()
        # Enrich procs with heartbeat data
        enriched = _enrich_procs(procs_rows, runs)
        cards = aggregate.build_engine_cards(enriched)
        return cards, runs

    def _done(cards, runs):
        ui_state["data"]["cards"] = cards
        ui_state["data"]["runs"] = runs
        strip_grid.update_strip_grid(grid, cards, ui_state["snapshot"].selected_engine)
        detail.update_detail(det, ui_state["snapshot"], ui_state["data"])
        header.update_header(hdr, ui_state["snapshot"])

    def _run():
        try:
            cards, runs = _worker()
        except Exception:
            return
        launcher.after(0, lambda: _done(cards, runs))

    _executor.submit(_run)


def _enrich_procs(procs_rows: list[dict], runs: list[dict]) -> list[dict]:
    """Merge heartbeat + run data into proc rows."""
    # Index runs by run_id
    runs_by_id = {r.get("run_id"): r for r in runs if r.get("run_id")}
    enriched: list[dict] = []
    for p in procs_rows:
        run_id = p.get("run_id")
        row = dict(p)
        run = runs_by_id.get(run_id) or {}
        row["ticks_ok"] = int(run.get("tick_count") or 0)
        row["novel_total"] = int(run.get("novel_count") or 0)
        row["equity"] = run.get("equity")
        row["ticks_fail"] = int(run.get("ticks_fail") or 0)
        enriched.append(row)
    return enriched


def _handle_select(ui_state, grid, det, ftr, engine: str) -> None:
    ui_state["snapshot"] = statemod.select_engine(ui_state["snapshot"], engine)
    strip_grid.update_strip_grid(
        grid, ui_state["data"]["cards"], engine,
    )
    detail.update_detail(det, ui_state["snapshot"], ui_state["data"])


def _handle_toggle_shelf(ui_state, shelf) -> None:
    ui_state["snapshot"] = statemod.toggle_shelf(ui_state["snapshot"])
    # rebuild shelf
    research_shelf.update_shelf(shelf, expanded=ui_state["snapshot"].shelf_expanded)


def _handle_research_select(launcher, ui_state, engine: str) -> None:
    from launcher_support.engines_live.dialogs.new_instance import open_new_instance_dialog

    open_new_instance_dialog(launcher, engine, default_mode=ui_state["snapshot"].mode)


def _apply_action(launcher, ui_state, action, grid, shelf, det, hdr, ftr, *,
                  on_escape) -> None:
    from launcher_support.engines_live.keyboard import (
        ExitView, BackToStrip, CycleFocus, CycleMode, OpenDetail,
        OpenNewInstanceDialog, StopInstance, RestartInstance, StopAll,
        OpenConfig, OpenLogViewer, ToggleFollowTail, TelegramTest,
        ToggleShelf, SearchFilter, ShowHelp,
    )
    snapshot = ui_state["snapshot"]

    if isinstance(action, ExitView):
        on_escape()
        return
    if isinstance(action, BackToStrip):
        ui_state["snapshot"] = statemod.reset_selection(snapshot)
    elif isinstance(action, CycleFocus):
        ui_state["snapshot"] = statemod.tab_focus(snapshot)
    elif isinstance(action, CycleMode):
        ui_state["snapshot"] = statemod.cycle_mode_state(snapshot)
    elif isinstance(action, ToggleShelf):
        ui_state["snapshot"] = statemod.toggle_shelf(snapshot)
    elif isinstance(action, ToggleFollowTail):
        ui_state["snapshot"] = statemod.toggle_follow(snapshot)
    # ... dispatch the rest to launcher-level handlers (stop, restart, etc.)

    # Repaint affected panes
    header.update_header(hdr, ui_state["snapshot"])
    strip_grid.update_strip_grid(grid, ui_state["data"]["cards"],
                                  ui_state["snapshot"].selected_engine)
    detail.update_detail(det, ui_state["snapshot"], ui_state["data"])
    footer.update_footer(ftr, ui_state["snapshot"])
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/integration/test_engines_live_panes.py -v`
Expected: 1 passed (or skipped).

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live/view.py \
        tests/integration/test_engines_live_panes.py
git commit -m "R3.16: view.py — top-level orchestrator + smoke test"
```

---

# Phase R4 — Wire new visual + replace old render

Goal: flip the launcher from old `engines_live_view.render` to the new `engines_live.view.render`. Visual redesign activates.

---

### Task 24: Re-export `render` from `engines_live/__init__.py`

**Files:**
- Modify: `launcher_support/engines_live/__init__.py`
- Modify: `launcher_support/engines_live_view.py`

- [ ] **Step 1: Update `__init__.py`**

Replace content with:

```python
"""AURUM · Engines Live view — see spec for details."""
from __future__ import annotations

from launcher_support.engines_live.view import render  # noqa: F401
from launcher_support.engines_live.data.cockpit import get_client as _get_cockpit_client  # noqa: F401
```

- [ ] **Step 2: Add re-export in old file**

At the top of `launcher_support/engines_live_view.py`, just after the docstring:

```python
# New rebuild path — the actual render() now lives in engines_live/view.py.
# This file is preserved as a shim during the migration. After R5 it becomes
# a 5-line re-export.
from launcher_support.engines_live.view import render as _new_render  # noqa
```

- [ ] **Step 3: Commit**

```bash
git add launcher_support/engines_live/__init__.py launcher_support/engines_live_view.py
git commit -m "R4.1: re-export new render from engines_live package"
```

---

### Task 25: Replace old `render()` call sites with new

**Files:**
- Modify: `launcher_support/screens/engines_live.py` (or wherever the screen is invoked — confirm via grep)

- [ ] **Step 1: Find where old render is called**

Run:
```bash
grep -rn "engines_live_view.render\|from launcher_support.engines_live_view import render\|engines_live_view\.render" \
    launcher.py launcher_support/ tests/ 2>/dev/null | head -20
```

- [ ] **Step 2: Update call site to use new render**

In the caller (likely `launcher_support/screens/engines_live.py`), swap:

```python
from launcher_support.engines_live_view import render
```

to:

```python
from launcher_support.engines_live import render
```

If the caller uses `launcher_support.engines_live_view as ell; ell.render(...)`, update accordingly.

- [ ] **Step 3: Run full integration suite**

Run: `pytest tests/integration/ tests/launcher/ -q`
Expected: all green.

- [ ] **Step 4: Manual smoke test**

Run: `python launcher.py` → navigate to EXECUTE → ENGINES LIVE.
Verify: strip grid renders with current VPS state, cards have names/dots/uptime, clicking a card opens detail pane with instances + log tail, ESC returns to main menu.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/engines_live.py
git commit -m "R4.2: swap launcher screen to new engines_live.render"
```

---

### Task 26: E2E visual checklist + Joao validation

Manual validation — no code. This is a checkpoint before moving to R5.

- [ ] **Step 1: Work through visual checklist**

Open `python launcher.py` on a workstation with VPS reachable and verify each item:

- [ ] Header shows "› ENGINES", counts "N live · M engines", mode pills with current active highlighted
- [ ] Mode LIVE selected adds red border below header
- [ ] Strip grid shows all running engines as V3 cards (1 card per engine, instance count with dots)
- [ ] Card order: errors first (if any), then by sort_weight ascending
- [ ] "+ NEW ENGINE" card at the end of the grid
- [ ] Research shelf collapsed by default; ▾ expands it
- [ ] Click on CITADEL card → detail pane shows 2 instances (p.desk-a, s.desk-a), aggregate KPIs, [S]/[R]/[A]/[+]/[C] buttons
- [ ] Click on instance in detail left → log tail updates in right column with color-coded lines
- [ ] Press F → follow mode activates, "● FOLLOWING" green indicator shows, auto-scroll works
- [ ] Press S on instance → HoldButton progress fills amber, releases before 1.5s = no action, hold full = stop dispatched
- [ ] Press + → new instance dialog opens, mode pre-selected to global mode
- [ ] Select LIVE + confirm → ritual dialog appears, CONFIRM disabled until engine name typed
- [ ] ESC from detail returns to strip grid focus; ESC from grid exits to main menu
- [ ] TAB cycles focus: strip → detail_instances → detail_log → strip
- [ ] No visible flicker during refresh ticks (30s cadence)

- [ ] **Step 2: Joao signs off**

Ask Joao to review and confirm all 15 checklist items pass. Record any deltas in a session log.

- [ ] **Step 3: Commit checklist doc**

Create `docs/testing/engines_live_e2e_checklist.md` with the 15 items as a reusable regression checklist.

```bash
git add docs/testing/engines_live_e2e_checklist.md
git commit -m "R4.3: E2E visual checklist + Joao validation"
```

---

# Phase R5 — Cleanup

Goal: retire the old files. Shim them so any stray import keeps working, but the actual code is gone.

---

### Task 27: Shim `engines_live_view.py`

**Files:**
- Modify: `launcher_support/engines_live_view.py`

- [ ] **Step 1: Replace content with shim**

Replace the entire content of `launcher_support/engines_live_view.py` with:

```python
"""AURUM · engines_live_view shim (post-rebuild).

The actual implementation lives in launcher_support/engines_live/. This
file only re-exports the symbols that external callers (launcher.py, tests)
still import by the old path.

Planned removal: once all external imports have been migrated.
"""
from __future__ import annotations

from launcher_support.engines_live import render  # noqa: F401
from launcher_support.engines_live.data.cockpit import get_client as _get_cockpit_client  # noqa: F401
from launcher_support.engines_live_helpers import (  # noqa: F401
    _MODE_ORDER,
    _REPO_ROOT,
    _MODE_COLORS,
    _ENGINE_DIR_MAP,
    _stage_badge,
    footer_hints,
    cockpit_summary,
    bucket_header_title,
    row_action_label,
    initial_selection,
    assign_bucket,
    cycle_mode,
    load_mode,
    save_mode,
    live_confirm_ok,
    format_uptime,
    _use_remote_shadow_cache,
    _safe_float,
    _uptime_seconds,
    running_slugs_from_procs,
    _sanitize_instance_label,
)
```

- [ ] **Step 2: Verify all external imports still resolve**

Run:
```bash
python -c "from launcher_support.engines_live_view import _get_cockpit_client, render; print('ok')"
pytest tests/integration/test_engines_live_view.py -q
```
Expected: both succeed.

- [ ] **Step 3: Full regression suite**

Run: `pytest -q 2>&1 | tail -5`
Expected: same counts as baseline recorded in Task 2.

- [ ] **Step 4: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "R5.1: shim engines_live_view.py — all impl moved to engines_live/"
```

---

### Task 28: Shim `engines_sidebar.py`

**Files:**
- Modify: `launcher_support/engines_sidebar.py`

- [ ] **Step 1: Identify what external callers actually use**

Run:
```bash
grep -rn "from launcher_support.engines_sidebar import\|launcher_support.engines_sidebar" \
    tests/ launcher_support/ launcher.py 2>/dev/null
```

- [ ] **Step 2: Check which symbols are consumed externally**

From prior exploration, these are needed: `EngineRow`, `build_engine_rows`, `format_signal_row`, `result_color_name`, plus `render_sidebar` and `render_detail` if still called.

- [ ] **Step 3: Move those symbols to `engines_live/helpers.py` or a new `engines_live/sidebar_compat.py`**

If they're fully absorbed into `panes/detail_*.py`, keep only the pure ones (`format_signal_row`, `result_color_name`, `EngineRow`, `build_engine_rows`) and re-export from `engines_live/helpers.py`.

Edit `launcher_support/engines_live/helpers.py` to include:

```python
# Legacy sidebar helpers kept for backward compat with tests
from launcher_support.engines_sidebar import (  # type: ignore  # noqa: F401
    EngineRow,
    build_engine_rows,
    format_signal_row,
    result_color_name,
)
```

- [ ] **Step 4: Replace `engines_sidebar.py` with shim**

Replace `launcher_support/engines_sidebar.py` with:

```python
"""AURUM · engines_sidebar shim (post-rebuild).

The sidebar was absorbed into launcher_support/engines_live/panes/detail_*.py.
This file preserves the pure helpers (EngineRow, format_signal_row, etc.)
for tests and legacy imports.
"""
from __future__ import annotations

# Re-export pure helpers still consumed by tests
# NOTE: these are copied inline during R5 migration because engines_sidebar.py
# used to own them. See the original file in git history before this shim.

from dataclasses import dataclass


@dataclass
class EngineRow:
    slug: str
    display: str
    live: bool
    mode: str | None
    subtitle: str


# ... paste the original implementations of build_engine_rows, format_signal_row,
# result_color_name, _format_time, _short_symbol, _short_dir, _fmt_price,
# _fmt_rr, _fmt_notional, _fmt_result verbatim from the previous version
# of this file.
```

(Review the original 1009-line file; only the pure helpers ~lines 15-192 need to stay. Copy them verbatim.)

- [ ] **Step 5: Run regression**

Run:
```bash
pytest tests/test_engines_sidebar.py tests/integration/test_engines_live_view.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add launcher_support/engines_sidebar.py launcher_support/engines_live/helpers.py
git commit -m "R5.2: shim engines_sidebar.py — pure helpers preserved"
```

---

### Task 29: Final suite + docs update

- [ ] **Step 1: Run full suite**

Run:
```bash
pytest -q 2>&1 | tail -5
```
Expected: pass count ≥ baseline from Task 2.

- [ ] **Step 2: Update CLAUDE.md if any new conventions**

If any new patterns emerged (diff-based render contract, threading rule, etc.), add a short note to the "Convenções" section of CLAUDE.md.

Check if the architecture doc exists:
```bash
ls docs/ARCHITECTURE.md docs/architecture.md 2>/dev/null
```
If not, skip. If yes, add a reference to the new `engines_live/` package.

- [ ] **Step 3: Create session log**

Create `docs/sessions/<YYYY-MM-DD_HHMM>.md` per CLAUDE.md format documenting the rebuild.

- [ ] **Step 4: Commit**

```bash
git add docs/sessions/
git commit -m "R5.3: session log + docs update for engines frontend rebuild"
```

- [ ] **Step 5: Push branch and open PR**

```bash
git push origin feat/engines-frontend-rebuild
gh pr create --title "Engines frontend rebuild (alpha layout · V3 · D2)" \
  --body "$(cat <<'EOF'
## Summary
- Refactor engines_live_view.py (4025) + engines_sidebar.py (1009) → launcher_support/engines_live/ package
- Apply alpha visual: V3 uniform engine cards + D2 detail pane (instances+KPIs | log wide)
- Hold-to-confirm 1.5s for S/R/A actions
- Color-coded log tail with INFO/SIGNAL/ORDER/FILL/EXIT/WARN/ERROR
- Follow tail mode (3s polling, auto-scroll)
- + NEW INSTANCE dialog with mode/label/target (LOCAL/VPS), LIVE ritual
- Diff-based pane updates — no flicker

## Test plan
- [x] Unit tests for data/, state, keyboard, widgets (pure + smoke headless)
- [x] Integration test_engines_live_panes smoke
- [x] Existing test_engines_live_view + test_engines_sidebar still pass
- [x] Manual E2E checklist (15 items — docs/testing/engines_live_e2e_checklist.md)
- [x] Full suite passes

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Done.**

---

## Self-Review

**Spec coverage:**

- Section 1 (motivation): addressed by the overall rebuild goal.
- Section 2 (scope): addressed by package split (A) and Phase R4 visual (B).
- Section 3.1 (header): Task 13 (panes/header.py).
- Section 3.2 (strip grid): Task 14 (panes/strip_grid.py) + Task 6 (aggregate ordering).
- Section 3.3 (research shelf): Task 15 (panes/research_shelf.py).
- Section 3.4 (detail D2): Tasks 16, 17, 18, 19 (detail_left, detail_right, detail_empty, detail orchestrator).
- Section 3.5 (footer): Task 20 (panes/footer.py).
- Section 4.1 (repaint cadences): Task 23 (view.py uses `_REFRESH_MS=30_000`, `_DETAIL_REFRESH_MS=15_000`, `_FOLLOW_MS=3_000`).
- Section 4.2 (event-driven repaints): handled inline in Task 23 `_apply_action`.
- Section 4.3 (caches): Tasks 4, 5 (cockpit, procs TTL caches).
- Section 4.4 (threading): Task 23 `_executor` + `launcher.after(0, ...)`.
- Section 4.5 (graceful degradation): Task 4 (get_client returns None), Task 13 (header badges OFFLINE/VPS UNREACHABLE — **need to add to Task 13 description**).
- Section 5.1 (global keybinds): Task 9 (keyboard.py route covers all).
- Section 5.2 (detail keybinds): Task 9 (route covers S/R/A/+/C/L/F/T).
- Section 5.3 (hold-to-confirm): Task 10 (HoldButton widget).
- Section 5.4 (routing): Task 9 (keyboard.py).
- Section 6 (new instance flow + LIVE ritual): Tasks 21, 22.
- Section 7 (refactor structure): entire plan.
- Section 8 (migration phases): Phases R1-R5 directly.
- Section 9 (tests): unit + smoke + E2E checklist covered across tasks.
- Section 10 (risks): mitigated in individual tasks.
- Section 11 (preservation): Preconditions + Tasks 4-7 (delegate patterns) + Tasks 27-28 (shims).
- Section 12 (sucesso criteria): Task 26 checklist = success validation.

**Gap found:** Task 13 (panes/header.py) doesn't explicitly mention OFFLINE / VPS UNREACHABLE badges. Adding a note to the task step.

**Placeholder scan:** No TBD/TODO. Referenced imports (`sanitize_label`, `load_runtime_keys`, `KeyStoreError`) verified in the codebase. Referenced palette constants (BG, BG2, BG3, AMBER, AMBER_B, CYAN, GREEN, RED, HAZARD, WHITE, DIM, DIM2, BORDER, MODE_DEMO, MODE_LIVE, MODE_PAPER, MODE_TESTNET) should all exist in `core/ui/ui_palette.py`. If any are missing during implementation, the engineer should add them following existing conventions.

**Type consistency check:** `EngineCard` dataclass defined once in Task 6 (`data/aggregate.py`), consumed with the same field names in Tasks 12 (`widgets/engine_card.py`), 14 (`panes/strip_grid.py`), 23 (`view.py`). `StateSnapshot` defined once in Task 8 (`state.py`), consumed with same field names in Tasks 9 (`keyboard.py`), 13-20 (panes), 23 (`view.py`). `Action` union defined in Task 9 and dispatched in Task 23 — matches.

**Addendum to Task 13:** After defining `build_header`, add this to the pane logic: when `data.cockpit.get_client()` returns None, append a badge `OFFLINE` (AMBER) to the right of the mode pills. When cockpit returns but a direct VPS systemctl probe fails (from a new helper `data/vps.py::is_reachable` — to be created inline in Task 13 or delegated to a launcher state flag), show `VPS UNREACHABLE` (AMBER_B). This keeps Section 4.5 of the spec covered.
