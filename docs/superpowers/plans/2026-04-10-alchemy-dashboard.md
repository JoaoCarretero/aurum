# ALCHEMY Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a new top-level `ALCHEMY` menu entry in the AURUM launcher that opens a fullscreen Half-Life HEV-Terminal arbitrage cockpit with 9 live panels, reading state from and controlling `engines/arbitrage.py`.

**Architecture:** The existing `engines/arbitrage.py` is extended with a JSON snapshot writer + param hot-reload. A new `core/alchemy_state.py` reads the snapshot and writes params. A new `core/alchemy_ui.py` renders the 9-panel tkinter cockpit. `launcher.py` grows one new menu entry and fullscreen lifecycle helpers. No rewrites of existing engine logic.

**Tech Stack:** Python 3.11, tkinter, stdlib only for the new state layer (json, pathlib, subprocess, signal), `pytest` added as a dev dependency for the testable headless parts.

**Spec reference:** `docs/superpowers/specs/2026-04-10-alchemy-dashboard-design.md`
**Mockup reference:** `.superpowers/brainstorm/2030-1775852615/content/layout-full.html`

---

## File Structure

### New files
| Path | Responsibility | Approx. LOC |
| --- | --- | --- |
| `core/alchemy_state.py` | Snapshot reader, run discovery, param writer, stale detection | ~150 |
| `core/alchemy_ui.py` | Palette, fonts, fullscreen helpers, 9 panel renderers, tick driver | ~700 |
| `config/alchemy_params.json` | Runtime parameters (created on first run by launcher) | JSON |
| `server/fonts/VT323.ttf` | Bundled font (Google Fonts OFL) | binary |
| `server/fonts/ShareTechMono.ttf` | Bundled font (Google Fonts OFL) | binary |
| `server/fonts/Cinzel.ttf` | Bundled font (Google Fonts OFL) | binary |
| `tests/test_alchemy_state.py` | Unit tests for reader + param writer | ~120 |
| `tests/test_alchemy_snapshot.py` | Unit tests for engine snapshot writer | ~80 |
| `tests/conftest.py` | pytest fixtures (tmp run dirs) | ~30 |

### Modified files
| Path | Change | Lines |
| --- | --- | --- |
| `launcher.py` | Add `ALCHEMY` menu entry + `_alchemy_enter()`/`_alchemy_exit()` + subprocess wiring | +~120 |
| `engines/arbitrage.py` | Add `--mode` CLI flag, `_write_snapshot()`, `_check_reload_params()`, basis ring buffer | +~140 |
| `pyproject.toml` | Add `pytest` to optional `[project.optional-dependencies].dev` | +3 |
| `.gitignore` | Add `.superpowers/` and `config/alchemy_params.json.reload` | +2 |

### Files NOT touched
- `core/connections.py` — existing `ConnectionManager` is used as-is
- `core/market_data.py`, `core/portfolio_monitor.py`, etc. — out of scope

---

## Phase 1 — Engine Preparation (testable headless)

### Task 1: Add `--mode` CLI flag to `engines/arbitrage.py`

Today the engine reads two module-level booleans `ARB_LIVE` and `ARB_DEMO` set by `safe_input`. Replace with an `argparse` flag so the launcher can spawn it with `python engines/arbitrage.py --mode paper` without stdin interaction, while preserving backwards-compatible interactive behavior when no flag is passed.

**Files:**
- Modify: `engines/arbitrage.py` — find the existing `ARB_LIVE,ARB_DEMO=False,False` line near the top and the `safe_input` block

- [ ] **Step 1: Locate the mode-selection logic**

Run: `grep -n "ARB_LIVE\|ARB_DEMO\|safe_input" engines/arbitrage.py | head -30`
Expected: shows the globals at the top and a `safe_input`-based prompt somewhere in `main()`/`__main__`.

- [ ] **Step 2: Replace globals with argparse at module load**

At the very top of `engines/arbitrage.py`, just after existing imports and before `ARB_LIVE,ARB_DEMO=False,False`, add:

```python
import argparse

def _parse_mode():
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--mode", choices=["paper","demo","testnet","live"], default=None)
    p.add_argument("--run-id", default=None, help="override auto-generated run id")
    args, _ = p.parse_known_args()
    return args

_ARGS = _parse_mode()
ARB_LIVE = _ARGS.mode == "live"
ARB_DEMO = _ARGS.mode in ("demo","testnet")
ARB_TESTNET = _ARGS.mode == "testnet"
ARB_PAPER = _ARGS.mode == "paper" or _ARGS.mode is None
ARB_MODE = _ARGS.mode or "paper"
```

Then find the existing `ARB_LIVE,ARB_DEMO=False,False` line and DELETE it (it's replaced by the argparse-driven assignments above).

- [ ] **Step 3: Override RUN_ID if provided**

Find the existing `RUN_ID=f"{_D}_{_T}"` line in `engines/arbitrage.py`. Replace with:

```python
RUN_ID = _ARGS.run_id or f"{_D}_{_T}"
```

- [ ] **Step 4: Remove interactive `safe_input` mode prompt**

Search for `safe_input` calls that ask about PAPER/DEMO/LIVE. Keep any interactive confirm for *live trading itself* (the double-confirm safety gate), but bypass the initial mode selection when `_ARGS.mode is not None`. Wrap existing prompts with:

```python
if _ARGS.mode is None:
    # interactive fallback — original safe_input prompt here
    ...
else:
    log.info(f"Mode fixed via CLI: {ARB_MODE}")
```

- [ ] **Step 5: Smoke test the CLI flag**

Run: `python engines/arbitrage.py --mode paper --run-id smoketest_t1 2>&1 | head -20` then immediately `Ctrl+C`.
Expected: engine boots into paper mode without any interactive prompts, creates `data/arbitrage/smoketest_t1/` with `logs/` `state/` `reports/` subdirs. Log line `Mode fixed via CLI: paper` is visible.

- [ ] **Step 6: Clean up + commit**

```bash
rm -rf data/arbitrage/smoketest_t1
git add engines/arbitrage.py
git commit -m "feat(arbitrage): add --mode and --run-id CLI flags"
```

---

### Task 2: Add snapshot writer to `engines/arbitrage.py`

Publish the dashboard-consumable state as `data/arbitrage/<run_id>/state/snapshot.json`, written atomically at the end of each scan cycle.

**Files:**
- Modify: `engines/arbitrage.py` — add a method on the main engine class (same class that already has `_save_state`)
- Create: `tests/test_alchemy_snapshot.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Set up pytest infrastructure**

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

@pytest.fixture
def tmp_run(tmp_path):
    run = tmp_path / "data" / "arbitrage" / "2026-01-01_0000"
    (run / "state").mkdir(parents=True)
    (run / "logs").mkdir()
    (run / "reports").mkdir()
    return run
```

Add pytest to `pyproject.toml` under a new `[project.optional-dependencies]` key:

```toml
dev = [
    "pytest>=7.0,<9",
]
```

Install: `pip install pytest`

- [ ] **Step 2: Write failing test for snapshot shape**

Create `tests/test_alchemy_snapshot.py`:

```python
import json
from pathlib import Path
from engines.arbitrage import Engine  # or whatever the main class is — inspect first

def test_snapshot_contains_required_keys(tmp_run, monkeypatch):
    # Arrange: minimal engine with mocked state
    eng = Engine.__new__(Engine)  # bypass __init__ — we only test the writer
    eng.account = 5000.0
    eng.peak = 5100.0
    eng.positions = []
    eng.closed = []
    eng.killed = False
    eng.consecutive_losses = 0
    eng._snapshot_file = tmp_run / "state" / "snapshot.json"
    eng._latest_opportunities = []
    eng._latest_funding = {}
    eng._latest_basis_history = {}
    eng._latest_venue_health = {}
    eng.venues = {}

    # Act
    eng._write_snapshot()

    # Assert
    data = json.loads(eng._snapshot_file.read_text())
    required = {
        "ts","run_id","mode","engine_pid","account","peak",
        "exposure_usd","drawdown_pct","realized_pnl","unrealized_pnl",
        "losses_streak","killed","sortino","trades_count",
        "opportunities","funding","next_funding","positions",
        "venue_health","basis_history",
    }
    assert required.issubset(data.keys()), f"missing keys: {required - data.keys()}"
    assert data["account"] == 5000.0
    assert data["killed"] is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_alchemy_snapshot.py -v`
Expected: FAIL — either `ImportError` on `Engine` (you need to find the real class name) or `AttributeError` on `_write_snapshot`.

Go check `engines/arbitrage.py` to find the actual engine class name (`grep -n "^class " engines/arbitrage.py`) and update the import in the test.

- [ ] **Step 4: Implement `_write_snapshot()`**

In `engines/arbitrage.py`, locate the engine class that owns `_save_state`. Add right after `_save_state`:

```python
def _write_snapshot(s):
    """Atomic snapshot for the ALCHEMY dashboard. Called at end of each scan cycle."""
    import os, tempfile
    try:
        # Derived values
        exposure = sum(p.size_usd for p in s.positions)
        drawdown = ((s.account - s.peak) / s.peak * 100) if s.peak > 0 else 0.0
        realized = sum(t.get("pnl", 0) for t in s.closed) if s.closed else 0.0
        unrealized = sum(getattr(p, "unrealized_pnl", 0) for p in s.positions)

        data = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": RUN_ID,
            "mode": ARB_MODE,
            "engine_pid": os.getpid(),
            "account": round(s.account, 2),
            "peak": round(s.peak, 2),
            "exposure_usd": round(exposure, 2),
            "drawdown_pct": round(drawdown, 3),
            "realized_pnl": round(realized, 2),
            "unrealized_pnl": round(unrealized, 2),
            "losses_streak": s.consecutive_losses,
            "killed": s.killed,
            "sortino": getattr(s, "_sortino_rolling", 0.0),
            "trades_count": len(s.closed),
            "opportunities": getattr(s, "_latest_opportunities", []),
            "funding": getattr(s, "_latest_funding", {}),
            "next_funding": {v.name: v.next_funding_ts(list(v.funding.keys())[0]) if v.funding else 0
                             for v in s.venues.values()},
            "positions": [
                {
                    "sym": p.symbol,
                    "long": p.v_a,
                    "short": p.v_b,
                    "pnl": round(getattr(p, "unrealized_pnl", 0), 2),
                    "edge_decay_pct": round(
                        ((p.edge - getattr(p, "current_edge", p.edge)) / p.edge * 100)
                        if p.edge else 0, 1),
                    "exit_in_s": int(getattr(p, "exit_in_s", 0)),
                }
                for p in s.positions
            ],
            "venue_health": getattr(s, "_latest_venue_health", {}),
            "basis_history": getattr(s, "_latest_basis_history", {}),
        }

        snapshot_file = getattr(s, "_snapshot_file", DIR / "state" / "snapshot.json")
        # atomic write: tmp + rename
        fd, tmp = tempfile.mkstemp(dir=str(snapshot_file.parent), prefix=".snap_", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, default=str)
        os.replace(tmp, snapshot_file)
    except Exception as e:
        log.debug(f"snapshot write failed: {e}")
```

Also in `__init__` of that engine class (same place `_state_file` is set), add:

```python
s._snapshot_file = DIR / "state" / "snapshot.json"
s._latest_opportunities = []
s._latest_funding = {}
s._latest_basis_history = {}
s._latest_venue_health = {}
s._sortino_rolling = 0.0
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_alchemy_snapshot.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_alchemy_snapshot.py engines/arbitrage.py pyproject.toml
git commit -m "feat(arbitrage): add snapshot writer for ALCHEMY dashboard"
```

---

### Task 3: Wire snapshot writer into scan loop + add param hot-reload + basis ring buffer

**Files:**
- Modify: `engines/arbitrage.py` — scan loop, param reload, basis capture

- [ ] **Step 1: Locate the main scan loop**

Run: `grep -n "async def.*scan\|async def main\|async def run" engines/arbitrage.py`
Expected: shows the scan loop method of the engine class.

- [ ] **Step 2: Add param reload checker**

Add as a method on the engine class:

```python
def _check_reload_params(s):
    """Called at top of each scan cycle. If reload flag file exists, re-read params and delete flag."""
    global MIN_SPREAD, MIN_APR, MAX_POS, POS_PCT, LEV, SCAN_S, EXIT_H, MAX_DD_PCT, KILL_LOSSES
    flag = Path("config/alchemy_params.json.reload")
    if not flag.exists():
        return
    try:
        params = json.loads(Path("config/alchemy_params.json").read_text())
        MIN_SPREAD  = float(params.get("MIN_SPREAD",  MIN_SPREAD))
        MIN_APR     = float(params.get("MIN_APR",     MIN_APR))
        MAX_POS     = int(params.get("MAX_POS",       MAX_POS))
        POS_PCT     = float(params.get("POS_PCT",     POS_PCT))
        LEV         = int(params.get("LEV",           LEV))
        SCAN_S      = int(params.get("SCAN_S",        SCAN_S))
        EXIT_H      = int(params.get("EXIT_H",        EXIT_H))
        MAX_DD_PCT  = float(params.get("MAX_DD_PCT",  MAX_DD_PCT))
        KILL_LOSSES = int(params.get("KILL_LOSSES",   KILL_LOSSES))
        log.info(f"params reloaded: MIN_APR={MIN_APR} MAX_POS={MAX_POS} POS_PCT={POS_PCT}")
    except Exception as e:
        log.warning(f"param reload failed: {e}")
    finally:
        try: flag.unlink()
        except: pass
```

- [ ] **Step 3: Add basis ring buffer**

In `__init__` of the engine class, add:

```python
from collections import deque
s._basis_buffers = {}  # {symbol: deque of (ts, basis)}
s._BASIS_MAX = 60  # 60 samples ≈ 30 minutes at 30s scan
```

Create a helper method:

```python
def _record_basis(s, symbol, perp_px, spot_px):
    if spot_px <= 0: return
    basis = (perp_px - spot_px) / spot_px
    buf = s._basis_buffers.setdefault(symbol, deque(maxlen=s._BASIS_MAX))
    buf.append((int(time.time()), round(basis, 6)))
    s._latest_basis_history = {k: list(v) for k, v in s._basis_buffers.items()}
```

- [ ] **Step 4: Hook into scan loop**

Find the scan loop method (from Step 1). At its top, inside the `while` loop's body, add:

```python
s._check_reload_params()
```

At the point where opportunities are computed (after the existing scoring logic), capture them:

```python
s._latest_opportunities = [
    {
        "sym": o.symbol,
        "long": o.v_long,
        "short": o.v_short,
        "spread": round(o.spread, 6),
        "apr": round(o.apr, 1),
        "omega": round(o.omega, 2),
        "fill_prob": round(getattr(o, "fill_prob", 1.0), 2),
    }
    for o in sorted(opportunities, key=lambda x: -x.omega)[:20]
]
```
*(Adapt to the actual local variable name for opportunities — may be `candidates`, `opps`, etc.)*

At the end of the scan body, after position/state updates, call:

```python
s._latest_funding = {
    sym: {v.name: v.funding.get(sym, 0) for v in s.venues.values() if not v._disabled}
    for sym in set().union(*(v.funding.keys() for v in s.venues.values() if not v._disabled))
}
s._latest_venue_health = {
    v.name: {
        "ping_ms": getattr(v, "last_ping_ms", None),
        "err": v._fail_count,
        "rate_limit_pct": getattr(v, "rate_limit_pct", None),
        "disabled": v._disabled,
    }
    for v in s.venues.values()
}
s._write_snapshot()
```

- [ ] **Step 5: Manual smoke test**

Run: `timeout 45 python engines/arbitrage.py --mode paper --run-id smoketest_t3 2>&1 | tail -20`
Expected: engine runs at least one scan cycle, snapshot.json exists and is populated.

Verify: `cat data/arbitrage/smoketest_t3/state/snapshot.json | python -m json.tool | head -30`
Expected: well-formed JSON with all required keys and some opportunities if market has any.

Test hot reload:
```bash
echo '{"MIN_APR": 20.0, "MAX_POS": 3}' > config/alchemy_params.json
touch config/alchemy_params.json.reload
```
Then watch the log — within one scan cycle you should see `params reloaded: MIN_APR=20.0 MAX_POS=3`.

- [ ] **Step 6: Cleanup + commit**

```bash
rm -rf data/arbitrage/smoketest_t3
rm -f config/alchemy_params.json config/alchemy_params.json.reload
git add engines/arbitrage.py
git commit -m "feat(arbitrage): wire snapshot writer, param reload, basis buffer into scan loop"
```

---

## Phase 2 — State Reader (headless, fully testable)

### Task 4: Create `core/alchemy_state.py` with `AlchemyState` class

**Files:**
- Create: `core/alchemy_state.py`
- Create: `tests/test_alchemy_state.py`

- [ ] **Step 1: Write failing tests for snapshot reader**

Create `tests/test_alchemy_state.py`:

```python
import json, time
from pathlib import Path
import pytest
from core.alchemy_state import AlchemyState, EMPTY_SNAPSHOT

def _make_snap(run_dir: Path, **overrides):
    snap = dict(EMPTY_SNAPSHOT)
    snap.update(overrides)
    (run_dir / "state").mkdir(parents=True, exist_ok=True)
    (run_dir / "state" / "snapshot.json").write_text(json.dumps(snap, default=str))

def test_reads_fresh_snapshot(tmp_path, monkeypatch):
    run = tmp_path / "data" / "arbitrage" / "2026-01-01_0000"
    _make_snap(run, account=4321.0, mode="paper")
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["account"] == 4321.0
    assert snap["mode"] == "paper"
    assert snap["_stale"] is False

def test_returns_empty_when_no_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["account"] == 0
    assert snap["_stale"] is True
    assert snap["opportunities"] == []

def test_marks_stale_when_old(tmp_path, monkeypatch):
    run = tmp_path / "data" / "arbitrage" / "2026-01-01_0000"
    _make_snap(run, account=100.0)
    f = run / "state" / "snapshot.json"
    old = time.time() - 999
    import os; os.utime(f, (old, old))
    monkeypatch.chdir(tmp_path)
    st = AlchemyState(stale_seconds=10)
    snap = st.read()
    assert snap["_stale"] is True
    assert snap["account"] == 100.0  # still returns last data

def test_handles_malformed_json(tmp_path, monkeypatch):
    run = tmp_path / "data" / "arbitrage" / "2026-01-01_0000"
    (run / "state").mkdir(parents=True)
    (run / "state" / "snapshot.json").write_text("{ not json")
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["_stale"] is True

def test_discovers_latest_run(tmp_path, monkeypatch):
    a = tmp_path / "data" / "arbitrage" / "2026-01-01_0000"
    b = tmp_path / "data" / "arbitrage" / "2026-01-02_0000"
    _make_snap(a, account=100.0)
    _make_snap(b, account=200.0)
    # b is newer (created after a)
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["account"] == 200.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alchemy_state.py -v`
Expected: all FAIL with `ImportError: cannot import name 'AlchemyState'`.

- [ ] **Step 3: Implement `core/alchemy_state.py`**

Create `core/alchemy_state.py`:

```python
"""AlchemyState — reads arbitrage engine snapshot for the ALCHEMY dashboard.

The engine writes `data/arbitrage/<run_id>/state/snapshot.json` at the end of each
scan cycle. This module discovers the latest run, reads the snapshot atomically,
caches the last successful read, and flags stale data when the file falls behind.
"""
import json
import time
from pathlib import Path

EMPTY_SNAPSHOT = {
    "ts": "",
    "run_id": "",
    "mode": "paper",
    "engine_pid": 0,
    "account": 0,
    "peak": 0,
    "exposure_usd": 0,
    "drawdown_pct": 0,
    "realized_pnl": 0,
    "unrealized_pnl": 0,
    "losses_streak": 0,
    "killed": False,
    "sortino": 0,
    "trades_count": 0,
    "opportunities": [],
    "funding": {},
    "next_funding": {},
    "positions": [],
    "venue_health": {},
    "basis_history": {},
    "_stale": True,
}


class AlchemyState:
    """Reader for the arbitrage engine's live snapshot."""

    def __init__(self, stale_seconds: int = 10, run_dir: Path | None = None):
        self.stale_seconds = stale_seconds
        self._pinned_run = run_dir  # optional: launcher pins the current run
        self._last_good: dict = dict(EMPTY_SNAPSHOT)

    def pin_run(self, run_dir: Path):
        """Called by launcher when it spawns a specific engine run."""
        self._pinned_run = Path(run_dir)

    def unpin_run(self):
        self._pinned_run = None

    def _latest_snapshot_path(self) -> Path | None:
        if self._pinned_run is not None:
            p = self._pinned_run / "state" / "snapshot.json"
            return p if p.exists() else None
        base = Path("data/arbitrage")
        if not base.exists():
            return None
        candidates = sorted(
            base.glob("*/state/snapshot.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def read(self) -> dict:
        p = self._latest_snapshot_path()
        if p is None:
            snap = dict(self._last_good)
            snap["_stale"] = True
            return snap
        age = time.time() - p.stat().st_mtime
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            snap = dict(self._last_good)
            snap["_stale"] = True
            return snap
        data["_stale"] = age > self.stale_seconds
        self._last_good = data
        return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alchemy_state.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/alchemy_state.py tests/test_alchemy_state.py
git commit -m "feat(alchemy): add AlchemyState snapshot reader"
```

---

### Task 5: Add param writer to `AlchemyState`

**Files:**
- Modify: `core/alchemy_state.py`
- Modify: `tests/test_alchemy_state.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_alchemy_state.py`:

```python
def test_write_params_creates_file_and_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    st = AlchemyState()
    st.write_params({"MIN_APR": 50.0, "MAX_POS": 4})
    params_file = tmp_path / "config" / "alchemy_params.json"
    flag_file   = tmp_path / "config" / "alchemy_params.json.reload"
    assert params_file.exists()
    assert flag_file.exists()
    data = json.loads(params_file.read_text())
    assert data["MIN_APR"] == 50.0
    assert data["MAX_POS"] == 4

def test_write_params_merges_with_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "alchemy_params.json").write_text(
        json.dumps({"MIN_APR": 40.0, "MAX_POS": 5, "LEV": 2}))
    st = AlchemyState()
    st.write_params({"MIN_APR": 60.0})
    data = json.loads((tmp_path / "config" / "alchemy_params.json").read_text())
    assert data["MIN_APR"] == 60.0
    assert data["MAX_POS"] == 5   # preserved
    assert data["LEV"] == 2       # preserved
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_alchemy_state.py::test_write_params_creates_file_and_flag -v`
Expected: FAIL with `AttributeError: 'AlchemyState' object has no attribute 'write_params'`.

- [ ] **Step 3: Add `write_params` to `AlchemyState`**

Append to the `AlchemyState` class in `core/alchemy_state.py`:

```python
    DEFAULT_PARAMS = {
        "MIN_SPREAD": 0.0015,
        "MIN_APR":    40.0,
        "MAX_POS":    5,
        "POS_PCT":    0.20,
        "LEV":        2,
        "SCAN_S":     30,
        "EXIT_H":     8,
        "MAX_DD_PCT": 0.05,
        "KILL_LOSSES": 3,
    }

    def read_params(self) -> dict:
        p = Path("config/alchemy_params.json")
        if not p.exists():
            return dict(self.DEFAULT_PARAMS)
        try:
            data = json.loads(p.read_text())
            merged = dict(self.DEFAULT_PARAMS)
            merged.update(data)
            return merged
        except Exception:
            return dict(self.DEFAULT_PARAMS)

    def write_params(self, updates: dict):
        """Merge updates into alchemy_params.json and touch the reload flag."""
        current = self.read_params()
        current.update(updates)
        p = Path("config/alchemy_params.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(current, indent=2))
        (p.parent / "alchemy_params.json.reload").touch()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_alchemy_state.py -v`
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/alchemy_state.py tests/test_alchemy_state.py
git commit -m "feat(alchemy): add param writer with reload flag"
```

---

## Phase 3 — UI Foundation

### Task 6: Create `core/alchemy_ui.py` with palette, fonts, and chrome helpers

**Files:**
- Create: `core/alchemy_ui.py`
- Create: `server/fonts/` (download three TTFs)

- [ ] **Step 1: Download fonts**

Fonts are Google Fonts OFL-licensed. Download directly:

```bash
mkdir -p server/fonts
curl -L -o server/fonts/VT323.ttf "https://github.com/google/fonts/raw/main/ofl/vt323/VT323-Regular.ttf"
curl -L -o server/fonts/ShareTechMono.ttf "https://github.com/google/fonts/raw/main/ofl/sharetechmono/ShareTechMono-Regular.ttf"
curl -L -o server/fonts/Cinzel.ttf "https://github.com/google/fonts/raw/main/ofl/cinzel/static/Cinzel-Regular.ttf"
```

Verify: `ls -la server/fonts/`
Expected: three files, each at least 30KB.

- [ ] **Step 2: Create the palette + font loader module**

Create `core/alchemy_ui.py`:

```python
"""ALCHEMY — Half-Life HEV Terminal cockpit for arbitrage.

9 panels, fullscreen, dense amber-on-black. Reads live state via AlchemyState
and controls engines/arbitrage.py via parameter hot-reload and subprocess.
"""
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Callable

# ═══════════════════════════════════════════════════════════
# PALETTE — HEV TERMINAL (Half-Life 1 amber on black)
# ═══════════════════════════════════════════════════════════
HEV_BG      = "#000000"
HEV_PANEL   = "#030200"
HEV_BORDER  = "#3a2200"
HEV_BORDER2 = "#5a3300"
HEV_AMBER   = "#ff8c00"
HEV_AMBER_B = "#ffb347"
HEV_AMBER_D = "#7a4400"
HEV_AMBER_DD= "#3a2200"
HEV_WHITE   = "#d8d8d8"
HEV_DIM     = "#5a3300"
HEV_GREEN   = "#00c040"
HEV_RED     = "#e03030"
HEV_HAZARD  = "#ffcc00"
HEV_BLOOD   = "#8b0000"

# Venue → planetary glyph
VENUE_GLYPH = {
    "binance":      "☉",  # Sol
    "bybit":        "☽",  # Luna
    "okx":          "☿",  # Mercurius
    "hyperliquid":  "♂",  # Mars
    "gate":         "♃",  # Jupiter
}

# Panel Latin subtitles
PANEL_LATIN = {
    1: "opus magnum",
    2: "flux aurum",
    3: "differentia",
    4: "corpus apertum",
    5: "pulsus",
    6: "nexus",
    7: "solve et coagula",
    8: "timor",
    9: "cronica",
}

# ═══════════════════════════════════════════════════════════
# FONT LOADING — attempts to load bundled TTFs, falls back to Consolas
# ═══════════════════════════════════════════════════════════
_FONT_CACHE = {}

def load_fonts(root: tk.Tk) -> dict:
    """Register VT323/ShareTechMono/Cinzel fonts. Returns a dict of font names."""
    if _FONT_CACHE:
        return _FONT_CACHE
    fonts_dir = Path(__file__).resolve().parent.parent / "server" / "fonts"
    names = {"mono_px": "Consolas", "mono": "Consolas", "serif": "Georgia"}
    try:
        # tkextrafont is the cleanest cross-platform way but may not be installed
        from tkextrafont import Font as ExtraFont
        for ttf, key, tk_name in [
            ("VT323.ttf",         "mono_px", "VT323"),
            ("ShareTechMono.ttf", "mono",    "Share Tech Mono"),
            ("Cinzel.ttf",        "serif",   "Cinzel"),
        ]:
            path = fonts_dir / ttf
            if path.exists():
                try:
                    ExtraFont(root, file=str(path))
                    names[key] = tk_name
                except Exception:
                    pass
    except ImportError:
        pass
    _FONT_CACHE.update(names)
    return names

def font(kind: str, size: int, weight: str = "normal") -> tuple:
    """Shortcut: font('mono_px', 18) -> ('VT323', 18, 'normal') or fallback."""
    name = _FONT_CACHE.get(kind, "Consolas")
    return (name, size, weight)
```

- [ ] **Step 3: Smoke test fonts module import**

Run: `python -c "from core.alchemy_ui import HEV_AMBER, VENUE_GLYPH, load_fonts; print(HEV_AMBER, VENUE_GLYPH['binance'])"`
Expected: `#ff8c00 ☉`

- [ ] **Step 4: Commit**

```bash
git add core/alchemy_ui.py server/fonts/
git commit -m "feat(alchemy): add HEV palette, venue glyphs, font loader"
```

---

### Task 7: Add panel chrome helper + tick driver shell in `core/alchemy_ui.py`

The `make_panel()` helper is the single render point used by all 9 panels. It creates the frame, corner brackets, title bar with Latin subtitle, and returns a body frame for content.

**Files:**
- Modify: `core/alchemy_ui.py`

- [ ] **Step 1: Add `make_panel` helper**

Append to `core/alchemy_ui.py`:

```python
def make_panel(parent, panel_id: int, title: str, **grid_kwargs) -> tk.Frame:
    """Create a panel frame with HEV chrome: border, corner brackets, title bar.

    Returns the body frame where the caller places content.
    """
    wrap = tk.Frame(parent, bg=HEV_BG, highlightthickness=1,
                    highlightbackground=HEV_BORDER, highlightcolor=HEV_BORDER)
    wrap.grid(**grid_kwargs)
    wrap.grid_propagate(False)

    # Corner brackets (top-left, bottom-right)
    tk.Frame(wrap, bg=HEV_AMBER, width=10, height=2).place(x=0, y=0)
    tk.Frame(wrap, bg=HEV_AMBER, width=2, height=10).place(x=0, y=0)
    tk.Frame(wrap, bg=HEV_AMBER, width=10, height=2).place(relx=1, rely=1, x=-10, y=-2)
    tk.Frame(wrap, bg=HEV_AMBER, width=2, height=10).place(relx=1, rely=1, x=-2, y=-10)

    # Title bar
    title_bar = tk.Frame(wrap, bg=HEV_PANEL, height=22)
    title_bar.pack(fill="x", padx=1, pady=(1, 0))
    title_bar.pack_propagate(False)

    tk.Label(title_bar, text=f"[{panel_id:02d}] {title}",
             font=font("mono_px", 15), fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left", padx=6)
    tk.Label(title_bar, text=PANEL_LATIN.get(panel_id, ""),
             font=font("mono", 11, "italic"), fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="right", padx=6)

    # Dashed divider (simulate dashed line with a thin frame)
    tk.Frame(wrap, bg=HEV_AMBER_DD, height=1).pack(fill="x", padx=6)

    body = tk.Frame(wrap, bg=HEV_PANEL)
    body.pack(fill="both", expand=True, padx=1, pady=1)
    return body


def hazard_strip(parent, height: int = 10) -> tk.Canvas:
    """Yellow/black diagonal hazard stripe across full width."""
    c = tk.Canvas(parent, height=height, bg=HEV_BG, highlightthickness=0)
    def _redraw(event=None):
        c.delete("all")
        w = c.winfo_width()
        step = 18
        for x in range(-height, w + height, step):
            c.create_polygon(
                x, 0, x + height, 0, x + height - height, height, x - height, height,
                fill=HEV_HAZARD, outline="")
            c.create_polygon(
                x + height, 0, x + step, 0, x + step - height, height, x + height - height, height,
                fill=HEV_BG, outline="")
    c.bind("<Configure>", _redraw)
    return c
```

- [ ] **Step 2: Add tick driver shell**

Append to `core/alchemy_ui.py`:

```python
class TickDriver:
    """Single after() loop that fans out to registered panel updaters."""

    def __init__(self, root: tk.Tk, interval_ms: int = 2000):
        self.root = root
        self.interval_ms = interval_ms
        self._updaters: list[Callable[[dict], None]] = []
        self._after_id = None
        self._alive = False

    def register(self, updater: Callable[[dict], None]):
        self._updaters.append(updater)

    def start(self, snapshot_provider: Callable[[], dict]):
        self._alive = True
        self._snapshot_provider = snapshot_provider
        self._tick()

    def stop(self):
        self._alive = False
        if self._after_id:
            try: self.root.after_cancel(self._after_id)
            except Exception: pass
            self._after_id = None

    def _tick(self):
        if not self._alive:
            return
        try:
            snap = self._snapshot_provider()
            for u in self._updaters:
                try: u(snap)
                except Exception as e:
                    print(f"[alchemy] panel updater error: {e}")
        except Exception as e:
            print(f"[alchemy] tick error: {e}")
        self._after_id = self.root.after(self.interval_ms, self._tick)
```

- [ ] **Step 3: Smoke test**

Run: `python -c "from core.alchemy_ui import make_panel, TickDriver, hazard_strip; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add core/alchemy_ui.py
git commit -m "feat(alchemy): add panel chrome helper and tick driver"
```

---

### Task 8: Launcher integration — menu entry and fullscreen lifecycle

**Files:**
- Modify: `launcher.py`

- [ ] **Step 1: Add `ALCHEMY` to `MAIN_MENU`**

In `launcher.py`, locate the `MAIN_MENU` list (around line 93). Insert `ALCHEMY` between `STRATEGIES` and `RISK`:

```python
MAIN_MENU = [
    ("MARKETS",        "markets",     "Seleccionar mercado activo"),
    ("CONNECTIONS",    "connections", "Contas & exchanges"),
    ("TERMINAL",       "terminal",    "Data, charts, research"),
    ("STRATEGIES",     "strategies",  "Backtest & live engines"),
    ("ALCHEMY",        "alchemy",     "Cross-venue arbitrage cockpit"),
    ("RISK",           "risk",        "Portfolio & risk console"),
    ("COMMAND CENTER", "command",     "Site, servers, admin panel"),
    ("SETTINGS",       "settings",    "Config, keys, Telegram"),
]
```

- [ ] **Step 2: Import alchemy modules at the top of launcher.py**

Below the existing `from core.connections import ConnectionManager, MARKETS` line, add:

```python
from core.alchemy_state import AlchemyState
from core import alchemy_ui
```

- [ ] **Step 3: Wire `_menu("alchemy")` into the router**

Find the `_menu` method (around line 551). Add handling for the new key. Inside the existing `if key in ("markets", "connections", "terminal", "risk", "settings"):` block, extend the tuple and dict to include `"alchemy"`:

```python
if key in ("markets", "connections", "terminal", "risk", "settings", "alchemy"):
    {
        "markets": self._markets,
        "connections": self._connections,
        "terminal": self._terminal,
        "risk": self._risk_menu,
        "settings": self._config,
        "alchemy": self._alchemy_enter,
    }[key]()
    return
```

- [ ] **Step 4: Add `_alchemy_enter` and `_alchemy_exit` methods**

Add these as methods on the `App` class in `launcher.py`, placed near the other page methods (after `_connections` is a good spot):

```python
def _alchemy_enter(self):
    """Enter fullscreen HEV Terminal cockpit for arbitrage."""
    # Save previous window state so we can restore on exit
    self._alch_prev_geometry = self.geometry()
    try:
        self._alch_prev_minsize = self.minsize()
    except Exception:
        self._alch_prev_minsize = (860, 560)
    self._alch_prev_resizable = (self.resizable()[0], self.resizable()[1])

    self.minsize(1, 1)
    self.attributes("-fullscreen", True)
    self.configure(bg=alchemy_ui.HEV_BG)

    self._clr(); self._unbind()
    self.history.append("main")

    # Initialize state reader + tick driver
    self._alch_state = AlchemyState(stale_seconds=10)
    self._alch_tick = alchemy_ui.TickDriver(self, interval_ms=2000)
    self._alch_log_buf = []  # deque-like tail for panel [09]
    self._alch_engine_mode = None  # None | paper | demo | testnet | live

    # Load fonts (must happen after Tk is live)
    alchemy_ui.load_fonts(self)

    # Paint cockpit
    alchemy_ui.render_cockpit(self)

    self.bind("<Escape>", self._alchemy_exit)
    self.h_path.configure(text="ALCHEMY")
    self.h_stat.configure(text="HEV ONLINE", fg=alchemy_ui.HEV_AMBER_B)

    # Start the tick
    self._alch_tick.start(lambda: self._alch_state.read())

def _alchemy_exit(self, event=None):
    """Exit the cockpit. Confirm if engine is running."""
    if self.proc and self.proc.poll() is None:
        from tkinter import messagebox
        if not messagebox.askyesno(
            "ALCHEMY",
            "Engine is still running. Stop it before exiting?",
            parent=self):
            return
        self._stop()

    try: self._alch_tick.stop()
    except Exception: pass
    try: self.unbind("<Escape>")
    except Exception: pass

    self.attributes("-fullscreen", False)
    self.geometry(self._alch_prev_geometry)
    try: self.minsize(*self._alch_prev_minsize)
    except Exception: self.minsize(860, 560)
    self.configure(bg=BG)
    self._menu("main")
```

- [ ] **Step 5: Add stub `render_cockpit` in `core/alchemy_ui.py`**

In `core/alchemy_ui.py`, append a stub that just paints a visible "ALCHEMY ONLINE" label so we can smoke-test the menu wiring before building the panels. We will replace this in later tasks.

```python
def render_cockpit(app):
    """Paint the 9-panel HEV cockpit. Called by launcher _alchemy_enter."""
    # STUB — replaced in Task 9+
    root = app.main
    root.configure(bg=HEV_BG)
    tk.Label(root, text="λ ALCHEMY · HEV TERMINAL ONLINE",
             font=font("mono_px", 40), fg=HEV_AMBER, bg=HEV_BG).pack(expand=True)
    tk.Label(root, text="[ESC] to exit · panels coming next task",
             font=font("mono", 14), fg=HEV_AMBER_D, bg=HEV_BG).pack()
```

- [ ] **Step 6: Manual smoke test**

Run: `python launcher.py`

Expected behavior:
1. Launcher splash loads normally
2. Press Enter → main menu shows ALCHEMY as a new entry
3. Click ALCHEMY → window goes fullscreen, black background, "λ ALCHEMY · HEV TERMINAL ONLINE" in big amber letters
4. Press Esc → returns to main menu at original 960×660 window
5. No tracebacks in terminal

If fullscreen fails on the user's Windows setup, fall back to `self.attributes("-zoomed", True)` inside `_alchemy_enter` with a try/except.

- [ ] **Step 7: Commit**

```bash
git add launcher.py core/alchemy_ui.py
git commit -m "feat(alchemy): wire menu entry and fullscreen lifecycle"
```

---

## Phase 4 — Cockpit Rendering

### Task 9: Top bar (hazard stripes + HEV vitals)

**Files:**
- Modify: `core/alchemy_ui.py`

- [ ] **Step 1: Replace `render_cockpit` with grid scaffold + top bar**

Replace the stub `render_cockpit` from Task 8 with:

```python
def render_cockpit(app):
    """Paint the 9-panel HEV cockpit. Root frame is app.main."""
    root = app.main
    root.configure(bg=HEV_BG)

    # λ watermark (placed first so it's behind everything)
    tk.Label(root, text="λ", font=(_FONT_CACHE.get("serif", "Georgia"), 520),
             fg="#0a0500", bg=HEV_BG).place(relx=0.78, rely=0.55, anchor="center")

    # Top hazard stripe
    top_haz = hazard_strip(root, height=10)
    top_haz.pack(fill="x")

    # Vitals top bar
    topbar = tk.Frame(root, bg=HEV_BG, height=56)
    topbar.pack(fill="x")
    topbar.pack_propagate(False)

    tk.Label(topbar, text="λ ALCHEMY", font=font("serif", 20, "bold"),
             fg=HEV_AMBER_B, bg=HEV_BG).pack(side="left", padx=18)

    app._alch_clock = tk.Label(topbar, text="", font=font("mono", 12),
                               fg=HEV_AMBER_D, bg=HEV_BG)
    app._alch_clock.pack(side="left", padx=12)

    vitals_frame = tk.Frame(topbar, bg=HEV_BG)
    vitals_frame.pack(side="right", padx=18)

    app._alch_vitals = {}
    for key, label in [
        ("account",   "ACCOUNT"),
        ("drawdown",  "DRAWDOWN"),
        ("positions", "POSITIONS"),
        ("exposure",  "EXPOSURE"),
        ("mode",      "MODE"),
        ("engine",    "ENGINE"),
    ]:
        cell = tk.Frame(vitals_frame, bg=HEV_BG)
        cell.pack(side="left", padx=14)
        tk.Label(cell, text=label, font=font("serif", 9),
                 fg=HEV_AMBER_D, bg=HEV_BG).pack(anchor="e")
        v = tk.Label(cell, text="—", font=font("mono_px", 22),
                     fg=HEV_AMBER, bg=HEV_BG)
        v.pack(anchor="e")
        app._alch_vitals[key] = v

    # Thin amber separator below topbar
    tk.Frame(root, bg=HEV_AMBER_D, height=1).pack(fill="x")

    # ── Cockpit body (grid of 9 panels) ──
    body = tk.Frame(root, bg=HEV_BG)
    body.pack(fill="both", expand=True, padx=4, pady=4)
    # columns: 26% / 48% / 26%
    body.grid_columnconfigure(0, weight=26, uniform="col")
    body.grid_columnconfigure(1, weight=48, uniform="col")
    body.grid_columnconfigure(2, weight=26, uniform="col")
    # rows: 2 large, 1 medium, 1 fixed for engine control
    body.grid_rowconfigure(0, weight=5, uniform="row")
    body.grid_rowconfigure(1, weight=5, uniform="row")
    body.grid_rowconfigure(2, weight=3, uniform="row")
    body.grid_rowconfigure(3, minsize=70)
    app._alch_body = body

    # Register vitals updater
    def update_vitals(snap):
        import datetime as _dt
        app._alch_clock.configure(
            text=_dt.datetime.utcnow().strftime("%Y.%m.%d · %H:%M:%S UTC"))
        app._alch_vitals["account"].configure(text=f"${snap.get('account',0):,.0f}")
        dd = snap.get("drawdown_pct", 0)
        app._alch_vitals["drawdown"].configure(
            text=f"{dd:+.2f}%",
            fg=HEV_GREEN if dd > -1 else (HEV_HAZARD if dd > -3 else HEV_RED))
        n = len(snap.get("positions", []))
        app._alch_vitals["positions"].configure(text=f"{n} / {snap.get('_max_pos', 5)}")
        app._alch_vitals["exposure"].configure(text=f"${snap.get('exposure_usd',0):,.0f}")
        mode = snap.get("mode", "—").upper()
        app._alch_vitals["mode"].configure(
            text=mode,
            fg=HEV_HAZARD if mode == "PAPER" else (HEV_RED if mode == "LIVE" else HEV_AMBER_B))
        running = snap.get("engine_pid", 0) and not snap.get("_stale", True)
        app._alch_vitals["engine"].configure(
            text="▶ RUN" if running else "■ IDLE",
            fg=HEV_GREEN if running else HEV_DIM)
    app._alch_tick.register(update_vitals)

    # Bottom hazard stripe
    bot_haz = hazard_strip(root, height=10)
    bot_haz.pack(side="bottom", fill="x")

    # Panel stubs for next task — will be replaced with real renderers
    for pid, row, col, rowspan, title in [
        (1, 0, 0, 2, "OPPORTVNITATES"),
        (2, 0, 1, 1, "FVNDING · RATES"),
        (3, 1, 1, 1, "BASIS · PERP / SPOT"),
        (4, 0, 2, 1, "POSITIONES"),
        (5, 1, 2, 1, "VENVE · HEALTH"),
        (8, 2, 0, 1, "RISK · CONSOLE"),
        (9, 2, 1, 1, "LOG · STREAM"),
        (6, 2, 2, 1, "CONNECTIONES"),
        (7, 3, 0, 1, "MACHINA · ENGINE CONTROL"),
    ]:
        colspan = 3 if pid == 7 else 1
        body_frame = make_panel(body, pid, title,
                                row=row, column=col,
                                rowspan=rowspan, columnspan=colspan,
                                sticky="nsew", padx=2, pady=2)
        # Stash on app so later tasks can populate
        setattr(app, f"_alch_p{pid}", body_frame)
```

- [ ] **Step 2: Manual smoke test**

Run: `python launcher.py` → ALCHEMY.

Expected:
- Fullscreen with hazard stripes top+bottom
- `λ ALCHEMY` brand top-left, UTC clock next to it
- 6 vitals top-right, all showing `—` or `0` (engine not running)
- 9 empty panels with title bars (`[01] OPPORTVNITATES · opus magnum`, etc.) arranged in the grid
- Giant faint λ watermark behind everything
- Esc returns to main menu

- [ ] **Step 3: Commit**

```bash
git add core/alchemy_ui.py
git commit -m "feat(alchemy): render cockpit grid + vitals top bar"
```

---

### Task 10: Panels [01] OPPORTVNITATES, [04] POSITIONES, [05] VENVE HEALTH (tabular)

These three panels share a simple table-rendering pattern. Build them together.

**Files:**
- Modify: `core/alchemy_ui.py`

- [ ] **Step 1: Add shared table helper**

Append to `core/alchemy_ui.py`:

```python
def _render_table(parent, header: list[str], widths: list[int]) -> tuple[tk.Frame, Callable]:
    """Build a header row and return (body_frame, update_fn).

    update_fn(rows, colors=None) replaces body contents with rows.
    rows: list[list[str]]; colors: optional list[list[str|None]] same shape.
    """
    # Header
    hdr = tk.Frame(parent, bg=HEV_PANEL)
    hdr.pack(fill="x", padx=4, pady=(2, 0))
    for txt, w in zip(header, widths):
        tk.Label(hdr, text=txt, width=w, anchor="w",
                 font=font("mono", 11), fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="left")

    body = tk.Frame(parent, bg=HEV_PANEL)
    body.pack(fill="both", expand=True, padx=4)

    def update(rows, colors=None):
        for w in body.winfo_children():
            w.destroy()
        for i, row in enumerate(rows):
            row_colors = colors[i] if colors and i < len(colors) else [None] * len(row)
            row_frame = tk.Frame(body, bg=HEV_PANEL)
            row_frame.pack(fill="x")
            for txt, w, c in zip(row, widths, row_colors):
                tk.Label(row_frame, text=str(txt), width=w, anchor="w",
                         font=font("mono_px", 14),
                         fg=c or HEV_AMBER, bg=HEV_PANEL).pack(side="left")
    return body, update
```

- [ ] **Step 2: Add panel [01] OPPORTUNITIES renderer**

Append:

```python
def _init_panel_opportunities(app):
    frame = app._alch_p1
    _, update_rows = _render_table(
        frame,
        header=["#", "SYM", "LONG", "SHORT", "SPRD", "APR", "Ω"],
        widths=[3, 10, 6, 6, 8, 8, 5],
    )
    def update(snap):
        opps = snap.get("opportunities", [])[:12]
        rows, colors = [], []
        for i, o in enumerate(opps, 1):
            long_g = VENUE_GLYPH.get(o.get("long", ""), "·") + (o.get("long", "")[:3].upper())
            short_g = VENUE_GLYPH.get(o.get("short", ""), "·") + (o.get("short", "")[:3].upper())
            rows.append([
                f"{i:02d}",
                o.get("sym", "—")[:9],
                long_g,
                short_g,
                f"{o.get('spread',0)*100:+.4f}",
                f"{o.get('apr',0):.1f}%",
                f"{o.get('omega',0):.1f}",
            ])
            c = HEV_AMBER if o.get('omega', 0) < 7 else HEV_HAZARD
            colors.append([HEV_AMBER_D, HEV_HAZARD, HEV_AMBER, HEV_AMBER, HEV_GREEN, HEV_GREEN, c])
        if not rows:
            rows = [["—", "no opportunities", "", "", "", "", ""]]
            colors = [[HEV_DIM]*7]
        update_rows(rows, colors)
    app._alch_tick.register(update)
```

- [ ] **Step 3: Add panel [04] POSITIONS renderer**

Append:

```python
def _init_panel_positions(app):
    frame = app._alch_p4
    _, update_rows = _render_table(
        frame,
        header=["SYM", "VENUES", "PNL", "ΔEDGE", "EXIT"],
        widths=[8, 8, 10, 8, 8],
    )
    def update(snap):
        poss = snap.get("positions", [])
        rows, colors = [], []
        for p in poss:
            long_g = VENUE_GLYPH.get(p.get("long",""), "·")
            short_g = VENUE_GLYPH.get(p.get("short",""), "·")
            pnl = p.get("pnl", 0)
            exit_s = p.get("exit_in_s", 0)
            h, rem = divmod(exit_s, 3600)
            m = rem // 60
            rows.append([
                p.get("sym", "—")[:7],
                f"{long_g}/{short_g}",
                f"{pnl:+.2f}",
                f"-{p.get('edge_decay_pct', 0):.0f}%",
                f"{h}h{m:02d}m" if exit_s > 0 else "—",
            ])
            colors.append([HEV_HAZARD, HEV_AMBER,
                           HEV_GREEN if pnl >= 0 else HEV_RED,
                           HEV_AMBER, HEV_HAZARD if exit_s < 7200 else HEV_AMBER])
        if not rows:
            rows = [["—", "no positions", "", "", ""]]
            colors = [[HEV_DIM]*5]
        update_rows(rows, colors)
    app._alch_tick.register(update)
```

- [ ] **Step 4: Add panel [05] VENUE HEALTH renderer**

Append:

```python
def _init_panel_venue_health(app):
    frame = app._alch_p5
    _, update_rows = _render_table(
        frame,
        header=["VEN", "PING", "ERR", "RL", "KS"],
        widths=[10, 7, 5, 7, 6],
    )
    def update(snap):
        health = snap.get("venue_health", {})
        rows, colors = [], []
        venues = ["binance", "bybit", "okx", "hyperliquid", "gate"]
        for v in venues:
            h = health.get(v, {})
            disabled = h.get("disabled", False)
            ping = h.get("ping_ms")
            err = h.get("err", 0)
            rl = h.get("rate_limit_pct")
            status = "DOWN" if disabled else ("WARN" if (rl or 0) > 75 else "OK")
            rows.append([
                f"{VENUE_GLYPH.get(v, '·')} {v[:6].upper()}",
                "—" if ping is None else f"{ping}ms",
                str(err),
                "—" if rl is None else f"{rl}%",
                status,
            ])
            colors.append([
                HEV_DIM if disabled else HEV_AMBER,
                HEV_RED if disabled else HEV_AMBER,
                HEV_RED if err > 0 else HEV_AMBER_D,
                HEV_HAZARD if (rl or 0) > 75 else HEV_AMBER,
                HEV_RED if status == "DOWN" else (HEV_HAZARD if status == "WARN" else HEV_GREEN),
            ])
        update_rows(rows, colors)
    app._alch_tick.register(update)
```

- [ ] **Step 5: Wire the three initializers into `render_cockpit`**

At the end of `render_cockpit`, after the panel stubs loop, add:

```python
    _init_panel_opportunities(app)
    _init_panel_positions(app)
    _init_panel_venue_health(app)
```

- [ ] **Step 6: Manual smoke test**

Run: `python launcher.py` → ALCHEMY.

Expected:
- Panels 1, 4, 5 now show headers + placeholder rows ("no opportunities" / "no positions" / all venues listed as DOWN since no engine is running).

Spawn the engine in another terminal: `python engines/arbitrage.py --mode paper --run-id manual_t10`. Wait 30s.

Expected:
- Panels 1, 4, 5 populate with live data within 2-4s of engine's first scan completing.

- [ ] **Step 7: Commit**

```bash
git add core/alchemy_ui.py
git commit -m "feat(alchemy): panels [01] [04] [05] tabular renderers"
```

---

### Task 11: Panels [02] FUNDING heatmap and [08] RISK CONSOLE gauges

**Files:**
- Modify: `core/alchemy_ui.py`

- [ ] **Step 1: Add panel [02] FUNDING heatmap renderer**

Append to `core/alchemy_ui.py`:

```python
def _init_panel_funding(app):
    frame = app._alch_p2
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=4, pady=4)

    # Symbols rows × venue columns (fixed set)
    venues = ["binance", "bybit", "okx", "hyperliquid", "gate"]
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT", "DOGEUSDT", "LINKUSDT"]

    cells = {}
    # Header row
    hdr = tk.Frame(inner, bg=HEV_PANEL); hdr.pack(fill="x")
    tk.Label(hdr, text="·", width=6, font=font("mono_px", 12),
             fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="left")
    for v in venues:
        tk.Label(hdr, text=f"{VENUE_GLYPH.get(v,'·')} {v[:3].upper()}",
                 width=9, font=font("serif", 10, "bold"),
                 fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left")

    for sym in symbols:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x")
        tk.Label(row, text=sym.replace("USDT",""), width=6,
                 font=font("mono_px", 13), fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="left")
        cells[sym] = {}
        for v in venues:
            lbl = tk.Label(row, text="—", width=9,
                           font=font("mono_px", 13), fg=HEV_AMBER_D, bg="#0a0500")
            lbl.pack(side="left", padx=1)
            cells[sym][v] = lbl

    footer = tk.Label(inner, text="", font=font("mono", 10),
                      fg=HEV_AMBER_D, bg=HEV_PANEL, anchor="e")
    footer.pack(fill="x", pady=(4, 0))

    def update(snap):
        funding = snap.get("funding", {})
        for sym in symbols:
            for v in venues:
                rate = funding.get(sym, {}).get(v)
                if rate is None:
                    cells[sym][v].configure(text="—", fg=HEV_AMBER_D, bg="#0a0500")
                    continue
                pct = rate * 100
                txt = f"{pct:+.4f}"
                if pct > 0.02:
                    bg, fg = "#3a0a00", "#ff5030"
                elif pct < 0:
                    bg, fg = "#001a00", "#30ff80"
                else:
                    bg, fg = "#0a0500", HEV_AMBER
                cells[sym][v].configure(text=txt, fg=fg, bg=bg)

        # Next funding countdowns
        nf = snap.get("next_funding", {})
        now = __import__("time").time()
        parts = []
        for v in venues:
            ts = nf.get(v, 0)
            if ts and ts > now:
                rem = int(ts - now)
                h, m = divmod(rem // 60, 60)
                parts.append(f"{v[:3].upper()} {h}h{m:02d}m")
        footer.configure(text="next: " + " · ".join(parts) if parts else "")

    app._alch_tick.register(update)
```

- [ ] **Step 2: Add panel [08] RISK CONSOLE gauges renderer**

Append:

```python
def _init_panel_risk(app):
    frame = app._alch_p8
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=6, pady=4)

    gauges = {}
    for key, label in [
        ("expo",    "EXPO"),
        ("dd_day",  "DD DAY"),
        ("dd_max",  "DD MAX"),
        ("losses",  "LOSSES"),
        ("sortino", "SORTINO"),
        ("trades",  "TRADES"),
    ]:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x", pady=1)
        tk.Label(row, text=label, width=9, font=font("serif", 9),
                 fg=HEV_AMBER_D, bg=HEV_PANEL, anchor="w").pack(side="left")
        bar_wrap = tk.Frame(row, bg="#1a0f00", height=8, highlightthickness=1,
                            highlightbackground=HEV_AMBER_DD)
        bar_wrap.pack(side="left", fill="x", expand=True, padx=4)
        bar_wrap.pack_propagate(False)
        fill = tk.Frame(bar_wrap, bg=HEV_AMBER)
        fill.place(x=0, y=0, relheight=1, relwidth=0)
        val = tk.Label(row, text="—", width=8, font=font("mono_px", 12),
                       fg=HEV_AMBER, bg=HEV_PANEL, anchor="e")
        val.pack(side="left")
        gauges[key] = (fill, val)

    def set_bar(fill, val_lbl, pct, text, color=HEV_AMBER):
        pct = max(0, min(1.0, pct))
        fill.configure(bg=color)
        fill.place_configure(relwidth=pct)
        val_lbl.configure(text=text, fg=color)

    def update(snap):
        expo = snap.get("exposure_usd", 0)
        max_expo = 3000  # TODO read from params
        set_bar(*gauges["expo"], expo/max_expo, f"{expo/max_expo*100:.0f}%")

        dd = abs(snap.get("drawdown_pct", 0))
        set_bar(*gauges["dd_day"], dd/5.0,
                f"{-dd:+.1f}%",
                color=HEV_GREEN if dd < 1 else (HEV_HAZARD if dd < 3 else HEV_RED))

        set_bar(*gauges["dd_max"], dd/5.0, f"{-dd:+.1f}%", color=HEV_GREEN)

        loss = snap.get("losses_streak", 0)
        set_bar(*gauges["losses"], loss/3.0, f"{loss}/3",
                color=HEV_HAZARD if loss >= 2 else HEV_AMBER)

        sort = snap.get("sortino", 0)
        set_bar(*gauges["sortino"], max(0, min(1, sort/3)), f"{sort:.2f}",
                color=HEV_GREEN if sort > 1 else HEV_AMBER)

        trades = snap.get("trades_count", 0)
        set_bar(*gauges["trades"], min(1, trades/40), str(trades))

    app._alch_tick.register(update)
```

- [ ] **Step 3: Wire into `render_cockpit`**

At the end of `render_cockpit`, add:

```python
    _init_panel_funding(app)
    _init_panel_risk(app)
```

- [ ] **Step 4: Manual smoke test**

Run launcher → ALCHEMY. Start engine in paper mode.

Expected:
- Funding grid populates with 8 symbols × 5 venues, cells colored red/green/amber by sign and magnitude
- Next-funding countdowns shown at bottom
- Risk gauges show EXPO, DD DAY, DD MAX, LOSSES, SORTINO, TRADES with animated bars

- [ ] **Step 5: Commit**

```bash
git add core/alchemy_ui.py
git commit -m "feat(alchemy): panels [02] funding heatmap and [08] risk gauges"
```

---

### Task 12: Panel [03] BASIS canvas chart

**Files:**
- Modify: `core/alchemy_ui.py`

- [ ] **Step 1: Add basis panel renderer**

Append to `core/alchemy_ui.py`:

```python
def _init_panel_basis(app):
    frame = app._alch_p3
    canvas = tk.Canvas(frame, bg=HEV_PANEL, highlightthickness=0)
    canvas.pack(fill="both", expand=True, padx=4, pady=4)

    legend = tk.Frame(frame, bg=HEV_PANEL)
    legend.pack(fill="x", padx=4)
    tk.Label(legend, text="━ BTC", font=font("mono", 10),
             fg=HEV_AMBER, bg=HEV_PANEL).pack(side="right", padx=4)
    tk.Label(legend, text="━ ETH", font=font("mono", 10),
             fg=HEV_HAZARD, bg=HEV_PANEL).pack(side="right", padx=4)
    tk.Label(legend, text="━ SOL", font=font("mono", 10),
             fg=HEV_GREEN, bg=HEV_PANEL).pack(side="right", padx=4)
    stats = tk.Label(legend, text="σ=— · μ=—", font=font("mono", 10),
                     fg=HEV_AMBER_D, bg=HEV_PANEL)
    stats.pack(side="left", padx=4)

    def update(snap):
        canvas.delete("all")
        W = canvas.winfo_width() or 400
        H = canvas.winfo_height() or 140
        if W < 10 or H < 10:
            return

        history = snap.get("basis_history", {})
        symbols = [("BTCUSDT", HEV_AMBER), ("ETHUSDT", HEV_HAZARD), ("SOLUSDT", HEV_GREEN)]

        # Zero line
        canvas.create_line(0, H/2, W, H/2, fill=HEV_AMBER_DD, dash=(3, 4))

        # Collect all values to find global range
        all_vals = []
        for sym, _ in symbols:
            for _, v in history.get(sym, []):
                all_vals.append(v)
        if not all_vals:
            canvas.create_text(W/2, H/2, text="no basis data yet",
                               fill=HEV_AMBER_D, font=font("mono", 12))
            stats.configure(text="σ=— · μ=—")
            return

        lo, hi = min(all_vals), max(all_vals)
        span = max(hi - lo, 0.0001)
        for sym, color in symbols:
            pts = history.get(sym, [])
            if len(pts) < 2:
                continue
            coords = []
            for i, (_, v) in enumerate(pts):
                x = (i / (len(pts) - 1)) * W if len(pts) > 1 else W/2
                y = H - ((v - lo) / span * H)
                coords += [x, y]
            canvas.create_line(*coords, fill=color, width=2, smooth=False)

        import statistics as _st
        mu = _st.mean(all_vals)
        sigma = _st.pstdev(all_vals) if len(all_vals) > 1 else 0
        stats.configure(text=f"σ={sigma:.4f} · μ={mu:+.4f}")

    app._alch_tick.register(update)
```

- [ ] **Step 2: Wire into `render_cockpit`**

Add to the list of initializer calls:

```python
    _init_panel_basis(app)
```

- [ ] **Step 3: Manual smoke test**

Start engine, open ALCHEMY. Wait 3-5 scan cycles.

Expected:
- Basis panel shows up to 3 polyline traces (BTC amber, ETH hazard yellow, SOL green) over time
- Legend shows σ and μ stats bottom-left
- "no basis data yet" placeholder if engine hasn't completed a cycle

- [ ] **Step 4: Commit**

```bash
git add core/alchemy_ui.py
git commit -m "feat(alchemy): panel [03] basis canvas chart"
```

---

### Task 13: Panels [06] CONNECTIONES, [07] ENGINE CONTROL, [09] LOG STREAM

**Files:**
- Modify: `core/alchemy_ui.py`

- [ ] **Step 1: Add panel [06] CONNECTIONES renderer**

Append:

```python
def _init_panel_connections(app):
    frame = app._alch_p6
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=6, pady=4)

    from core.connections import ConnectionManager
    conn = ConnectionManager()

    venues = [
        ("binance_futures", "binance",     "Binance"),
        ("bybit",           "bybit",       "Bybit"),
        ("okx",             "okx",         "OKX"),
        ("hyperliquid",     "hyperliquid", "Hyperliquid"),
        ("gate",            "gate",        "Gate.io"),
    ]

    rows = {}
    for conn_key, glyph_key, label in venues:
        row = tk.Frame(inner, bg=HEV_PANEL); row.pack(fill="x", pady=2)
        dot = tk.Label(row, text="●", font=font("mono_px", 14),
                       fg=HEV_DIM, bg=HEV_PANEL)
        dot.pack(side="left")
        tk.Label(row, text=VENUE_GLYPH.get(glyph_key, "·"), width=3,
                 font=font("serif", 13), fg=HEV_AMBER_B, bg=HEV_PANEL).pack(side="left")
        tk.Label(row, text=label, width=11, anchor="w",
                 font=font("mono", 12), fg=HEV_AMBER, bg=HEV_PANEL).pack(side="left")
        mode_lbl = tk.Label(row, text="—", font=font("mono", 11),
                            fg=HEV_AMBER_D, bg=HEV_PANEL)
        mode_lbl.pack(side="right")
        rows[conn_key] = (dot, mode_lbl)

    hint = tk.Label(inner, text="[TAB] toggle · [K] keys · [R] reconnect",
                    font=font("mono", 9), fg=HEV_AMBER_DD, bg=HEV_PANEL)
    hint.pack(side="bottom", pady=(4, 0))

    def update(snap):
        conn_state = conn._load()  # refresh
        health = snap.get("venue_health", {})
        for conn_key, (dot, mode_lbl) in rows.items():
            c = conn_state["connections"].get(conn_key, {})
            connected = c.get("connected", False)
            mode = c.get("mode", "—")
            glyph_key = conn_key.replace("_futures", "")
            disabled = health.get(glyph_key, {}).get("disabled", False)
            if disabled:
                dot.configure(fg=HEV_RED)
                mode_lbl.configure(text="OFFLINE", fg=HEV_RED)
            elif connected:
                dot.configure(fg=HEV_GREEN)
                mode_lbl.configure(text=mode.upper(), fg=HEV_GREEN)
            else:
                dot.configure(fg=HEV_DIM)
                mode_lbl.configure(text="IDLE", fg=HEV_AMBER_D)
    app._alch_tick.register(update)
```

- [ ] **Step 2: Add panel [07] ENGINE CONTROL renderer**

Append:

```python
def _init_panel_engine(app):
    frame = app._alch_p7
    inner = tk.Frame(frame, bg=HEV_PANEL)
    inner.pack(fill="both", expand=True, padx=8, pady=4)

    # Buttons row
    btn_row = tk.Frame(inner, bg=HEV_PANEL)
    btn_row.pack(side="left")

    def _mk_btn(text, mode, danger=False):
        bg = "#1a0000" if danger else "#0a0500"
        border = HEV_BLOOD if danger else HEV_AMBER_D
        fg = HEV_RED if danger else HEV_AMBER
        b = tk.Label(btn_row, text=text, font=font("mono_px", 14),
                     fg=fg, bg=bg, padx=12, pady=4,
                     highlightthickness=1, highlightbackground=border)
        b.pack(side="left", padx=2)
        if mode in ("paper", "demo", "testnet", "live"):
            b.bind("<Button-1>", lambda e: _start_engine(mode))
        elif mode == "stop":
            b.bind("<Button-1>", lambda e: _stop_engine())
        elif mode == "kill":
            b.bind("<Button-1>", lambda e: _kill_engine())
        return b

    def _start_engine(mode):
        if mode == "live":
            from tkinter import simpledialog
            answer = simpledialog.askstring(
                "LIVE MODE",
                "REAL CAPITAL AT RISK.\nType exactly 'LIVE' to confirm:",
                parent=app)
            if answer != "LIVE":
                return
        if app.proc and app.proc.poll() is None:
            app._stop()
        import subprocess, sys as _sys
        _NO_WIN = subprocess.CREATE_NO_WINDOW if _sys.platform == "win32" else 0
        app._alch_engine_mode = mode
        app.proc = subprocess.Popen(
            [_sys.executable, "engines/arbitrage.py", "--mode", mode],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE, text=True, bufsize=1,
            creationflags=_NO_WIN,
        )
        import threading
        def _reader():
            for line in iter(app.proc.stdout.readline, ""):
                app._alch_log_buf.append(line.rstrip())
                if len(app._alch_log_buf) > 500:
                    app._alch_log_buf.pop(0)
            try: app.proc.stdout.close()
            except: pass
        threading.Thread(target=_reader, daemon=True).start()

    def _stop_engine():
        if app.proc and app.proc.poll() is None:
            app._stop()
        app._alch_engine_mode = None

    def _kill_engine():
        _stop_engine()
        app._alch_log_buf.append("⚠ KILL switch invoked")

    _mk_btn("▶ PAPER",   "paper")
    _mk_btn("▶ DEMO",    "demo")
    _mk_btn("▶ TESTNET", "testnet")
    _mk_btn("▶ LIVE",    "live", danger=True)
    _mk_btn("■ STOP",    "stop")
    _mk_btn("⚠ KILL",    "kill", danger=True)

    # Params row (editable)
    params_row = tk.Frame(inner, bg=HEV_PANEL)
    params_row.pack(side="left", padx=24)

    from core.alchemy_state import AlchemyState
    state = AlchemyState()

    PARAMS = [
        ("MIN_APR",    "40.0"),
        ("MIN_SPREAD", ".0015"),
        ("MAX_POS",    "5"),
        ("POS_PCT",    "20%"),
        ("LEV",        "2x"),
        ("SCAN_S",     "30"),
        ("EXIT_H",     "8"),
        ("MAX_DD_PCT", "5%"),
    ]
    labels = {}
    for key, default in PARAMS:
        cell = tk.Frame(params_row, bg=HEV_PANEL)
        cell.pack(side="left", padx=8)
        tk.Label(cell, text=key, font=font("serif", 9),
                 fg=HEV_AMBER_D, bg=HEV_PANEL).pack()
        val = tk.Label(cell, text=default, font=font("mono_px", 15),
                       fg=HEV_AMBER, bg=HEV_PANEL, cursor="xterm")
        val.pack()
        labels[key] = val

        def _make_editor(k, lbl):
            def _edit(event):
                entry = tk.Entry(lbl.master, font=font("mono_px", 14),
                                 fg=HEV_HAZARD, bg="#1a1000",
                                 insertbackground=HEV_AMBER, width=8)
                entry.insert(0, lbl.cget("text").rstrip("%x "))
                lbl.pack_forget()
                entry.pack()
                entry.focus_set()
                def _commit(event=None):
                    new_val = entry.get().strip()
                    try:
                        v = float(new_val) if "." in new_val or k in ("MIN_SPREAD","POS_PCT","MAX_DD_PCT") else int(new_val)
                        state.write_params({k: v})
                        lbl.configure(text=str(v))
                    except ValueError:
                        pass
                    entry.destroy()
                    lbl.pack()
                entry.bind("<Return>", _commit)
                entry.bind("<FocusOut>", _commit)
                entry.bind("<Escape>", lambda e: (entry.destroy(), lbl.pack()))
            return _edit
        val.bind("<Button-1>", _make_editor(key, val))

    # Motto
    tk.Label(inner, text="SOLVE  ET  COAGULA",
             font=font("serif", 11), fg=HEV_AMBER_D, bg=HEV_PANEL).pack(side="right", padx=8)

    # Load current params on init
    current = state.read_params()
    for k, lbl in labels.items():
        if k in current:
            lbl.configure(text=str(current[k]))
```

- [ ] **Step 3: Add panel [09] LOG STREAM renderer**

Append:

```python
def _init_panel_log(app):
    frame = app._alch_p9
    text = tk.Text(frame, bg=HEV_PANEL, fg=HEV_AMBER_B,
                   font=font("mono", 11), relief="flat",
                   borderwidth=0, highlightthickness=0,
                   wrap="none", state="disabled")
    text.pack(fill="both", expand=True, padx=4, pady=4)
    text.tag_config("info", foreground=HEV_AMBER_B)
    text.tag_config("ok",   foreground=HEV_GREEN)
    text.tag_config("warn", foreground=HEV_HAZARD)
    text.tag_config("err",  foreground=HEV_RED)
    text.tag_config("dim",  foreground=HEV_AMBER_D)

    def classify(line: str) -> str:
        lo = line.lower()
        if "error" in lo or "fail" in lo: return "err"
        if "warn" in lo or "rate limit" in lo: return "warn"
        if "opened" in lo or "closed" in lo: return "ok"
        return "info"

    def update(snap):
        text.configure(state="normal")
        text.delete("1.0", "end")
        tail = app._alch_log_buf[-12:]
        for line in tail:
            tag = classify(line)
            text.insert("end", line + "\n", tag)
        text.configure(state="disabled")

    app._alch_tick.register(update)
```

- [ ] **Step 4: Wire all three into `render_cockpit`**

Add to the initializer calls at the end of `render_cockpit`:

```python
    _init_panel_connections(app)
    _init_panel_engine(app)
    _init_panel_log(app)
```

- [ ] **Step 5: Manual smoke test**

Run launcher → ALCHEMY.

Expected:
- Panel [06] shows 5 venues with dots and mode labels
- Panel [07] shows 6 buttons + 8 editable params + motto
- Panel [09] is empty (no engine started yet)
- Click `▶ PAPER` → engine spawns in background, log stream starts populating with colored lines
- Click a param like `MIN_APR` → becomes an Entry field, type 50.5, Enter → value updates, `config/alchemy_params.json` + reload flag written
- Within one scan cycle of the engine, you should see "params reloaded" in the log
- Click `■ STOP` → engine terminates, vitals go back to IDLE

- [ ] **Step 6: Commit**

```bash
git add core/alchemy_ui.py
git commit -m "feat(alchemy): panels [06] connections [07] engine control [09] log stream"
```

---

## Phase 5 — Integration & Debug

### Task 14: Stale overlay + engine process lifecycle polish

**Files:**
- Modify: `core/alchemy_ui.py`
- Modify: `launcher.py`

- [ ] **Step 1: Add stale overlay to cockpit**

In `core/alchemy_ui.py`, inside `render_cockpit`, after `body.grid_...` setup, add:

```python
    # Stale overlay (shown when snapshot is older than stale_seconds and engine should be running)
    overlay = tk.Label(root, text="SNAPSHOT STALE · engine not responding",
                       font=font("mono_px", 36), fg=HEV_RED, bg="#1a0000",
                       padx=40, pady=20)
    app._alch_overlay = overlay

    def update_overlay(snap):
        stale = snap.get("_stale", True)
        engine_running = bool(app.proc and app.proc.poll() is None)
        if stale and engine_running:
            overlay.place(relx=0.5, rely=0.5, anchor="center")
        else:
            overlay.place_forget()
    app._alch_tick.register(update_overlay)
```

- [ ] **Step 2: Pin run dir when engine starts**

In `_start_engine` inside `_init_panel_engine` (from Task 13), after creating `app.proc`, add:

```python
        # Pin the reader to this specific run's directory
        from datetime import datetime as _dt
        run_id = _dt.now().strftime("%Y-%m-%d_%H%M")
        app._alch_state.pin_run(Path(f"data/arbitrage/{run_id}"))
```

And in `_stop_engine`:

```python
        app._alch_state.unpin_run()
```

Note: this means you need to pass `--run-id` to match. Update the Popen call:

```python
        app.proc = subprocess.Popen(
            [_sys.executable, "engines/arbitrage.py", "--mode", mode, "--run-id", run_id],
            ...
```

Move the `run_id` line above the Popen call so it's in scope.

- [ ] **Step 3: Handle Esc-to-exit with running engine gracefully**

This is already done in `_alchemy_exit` from Task 8. Verify it still works by starting the engine, pressing Esc, confirming the dialog, and watching the engine get stopped and the launcher return to the main menu.

- [ ] **Step 4: Add `.gitignore` entries**

Append to `.gitignore`:

```
.superpowers/
config/alchemy_params.json
config/alchemy_params.json.reload
```

- [ ] **Step 5: Commit**

```bash
git add core/alchemy_ui.py launcher.py .gitignore
git commit -m "feat(alchemy): stale overlay + pinned run dir + engine lifecycle polish"
```

---

### Task 15: Full integration smoke test + debug pass

**Files:** none (diagnostic task)

- [ ] **Step 1: Run all unit tests**

Run: `pytest tests/ -v`
Expected: all tests from Phase 1-2 PASS. If any fail, fix the specific test before moving on.

- [ ] **Step 2: Full UI smoke test**

Run: `python launcher.py`. Work through this checklist:

1. [ ] Splash loads cleanly
2. [ ] Press Enter → main menu shows ALCHEMY
3. [ ] Click ALCHEMY → fullscreen with HEV palette, 9 panel frames visible with title bars
4. [ ] Hazard stripes top/bottom, λ watermark behind, vitals top-right all show `—` or `0`
5. [ ] Clock ticks every second (visible in top bar)
6. [ ] Click `▶ PAPER` → engine starts, console window suppressed, log panel populates
7. [ ] Within 5-10s: vitals show ACCOUNT, ENGINE goes green ▶ RUN
8. [ ] Within 30s: OPPORTUNITIES panel populates with real rows
9. [ ] Within 30s: FUNDING grid cells colored by sign
10. [ ] Within 2-3 minutes: BASIS chart shows polylines
11. [ ] VENUE HEALTH shows ping/err/rate-limit per venue
12. [ ] POSITIONS panel shows rows if any trade opens (may need to lower MIN_APR to force one)
13. [ ] RISK gauges animate with exposure/drawdown/sortino
14. [ ] CONNECTIONES updates dots based on venue health
15. [ ] Click on MIN_APR param → edit → Enter → value persists, engine reloads within 1 scan cycle, log confirms "params reloaded"
16. [ ] Click `■ STOP` → engine terminates cleanly, vitals go back to IDLE
17. [ ] Click `⚠ KILL` → engine terminates if running, log shows kill message
18. [ ] Click `▶ LIVE` → confirm dialog appears, cancel keeps engine off
19. [ ] Press Esc → if engine running, prompts to confirm; if stopped, returns to main menu
20. [ ] Main menu at original 960×660 geometry

- [ ] **Step 3: Stale overlay test**

Start engine, then manually rename `data/arbitrage/<run_id>/state/snapshot.json` → within 10s the red `SNAPSHOT STALE` overlay should appear. Rename back → overlay disappears.

- [ ] **Step 4: Font fallback test**

If bundled fonts loaded: panels show VT323/Share Tech Mono/Cinzel correctly.
If tkextrafont is not installed: panels fall back to Consolas with no crash. Test by temporarily renaming the `server/fonts/` dir and relaunching. Restore after.

- [ ] **Step 5: Debug any issues found**

For each broken item in the smoke test checklist:
1. Find the relevant task's code
2. Fix inline
3. Re-run the specific smoke test item
4. Commit the fix with `fix(alchemy): <what>`

- [ ] **Step 6: Final commit**

If there were any fixes not yet committed:

```bash
git add -u
git commit -m "fix(alchemy): integration smoke test fixes"
```

Then tag the feature complete:

```bash
git log --oneline -20
```

Expected: ~15-16 commits from this plan showing the feature build-out.

---

## Appendix A — Known Risks & Mitigations

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| `tkextrafont` not installed → fonts fall back to Consolas | High | Graceful fallback already in `load_fonts()`; visually degraded but functional |
| Fullscreen broken on specific Windows DPI | Low | Fall back to `-zoomed` or large fixed geometry; caught by smoke test #3 |
| Engine's `_latest_opportunities`/etc attributes not set when snapshot called before first scan | Medium | `getattr(s, '_latest_opportunities', [])` fallback in `_write_snapshot` |
| Snapshot write race with reader mid-write | Low | Atomic rename via tempfile; reader catches JSONDecodeError |
| Param hot-reload fights live engine mid-position | Medium | Params apply to future scan cycles only; existing positions unaffected |
| Venue's `next_funding_ts()` signature requires a symbol | Known | Already handled in snapshot writer by picking first symbol or defaulting to 0 |

## Appendix B — Out of Scope (future work)

- Historical PnL curve inside ALCHEMY (live cockpit only; use existing `STRATEGIES → results` for history)
- Click-through from opportunity row to auto-open position (read-only for now)
- Multi-monitor fullscreen support
- Configurable panel layout / dragging
- Websocket push instead of polling snapshot (current 2s tick is fine for arbitrage timescales)

---

## Self-Review

**Spec coverage:**
- Menu placement (top-level ALCHEMY) → Task 8
- Fullscreen lifecycle → Task 8 + Task 14
- Engine integration (dashboard + controller) → Tasks 1-3 + Task 13
- All 9 panels → Tasks 10-13
- Theme (HEV Terminal) → Task 6-9
- Snapshot data flow → Tasks 2-3 + Tasks 4-5
- Param hot-reload → Task 3 + Task 5 + Task 13
- Testing strategy (unit for state, manual for UI) → Tasks 2, 4, 5, 15

**Placeholders:** Scanned — one "TODO read from params" comment in Task 11 risk gauge (max_expo=3000). This is a hardcoded fallback, not a placeholder, but flagging: if desired, replace with `state.read_params().get("MAX_EXPO", 3000)` in a follow-up.

**Type consistency:** `snap.get("opportunities", [])`, `snap.get("positions", [])`, `snap.get("funding", {})`, `snap.get("venue_health", {})`, `snap.get("basis_history", {})` — all match the `EMPTY_SNAPSHOT` shape defined in Task 4.

**Function names:** `make_panel`, `hazard_strip`, `load_fonts`, `font`, `render_cockpit`, `TickDriver`, `AlchemyState`, `_init_panel_*` — all used consistently across tasks.
