# ENGINES LIVE Cockpit — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the `EXECUTE → ENGINES LIVE` view in the launcher as a hybrid master-detail cockpit with 3 readiness buckets (LIVE · READY · RESEARCH), a global mode switcher (paper/demo/testnet/live), and a RUN ritual proportional to risk.

**Architecture:** New `launcher_support/engines_live_view.py` module owns the view. Pure logic (bucket assignment, mode state, confirmation validation) is testable via pytest. Tkinter rendering is smoke-tested via `python launcher.py`. `launcher._strategies_live()` shrinks to a delegator. Palette untouched — only semantic aliases added.

**Tech Stack:** Python 3.14, Tkinter, pytest (follows existing `tests/test_engine_picker_contracts.py` pattern: test pure helpers, skip UI runtime).

**Spec:** `docs/superpowers/specs/2026-04-16-engines-live-cockpit-design.md`

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `config/engines.py` | Modify | Add `live_ready: bool` to each engine dict. Export `LIVE_READY_SLUGS`. |
| `core/ui_palette.py` | Modify | Append semantic aliases `MODE_PAPER`, `MODE_DEMO`, `MODE_TESTNET`, `MODE_LIVE`. |
| `launcher_support/engines_live_view.py` | Create | All rendering + interaction for the new view. Public: `render(launcher, parent, on_escape)`. |
| `launcher.py` | Modify | Replace `_strategies_live()` body with delegation to new module. Remove LIVE branch from `_strategies()`. |
| `tests/test_engines_live_view.py` | Create | Test pure helpers: bucket assignment, mode cycling, persistence, confirm validation, uptime fmt. |

---

## Task 1: Add `live_ready` flag + `LIVE_READY_SLUGS` to engine registry

**Files:**
- Modify: `config/engines.py`
- Test: `tests/test_engines_live_view.py` (new)

- [ ] **Step 1: Write failing test for LIVE_READY_SLUGS**

Create `tests/test_engines_live_view.py`:

```python
"""Tests for the new ENGINES LIVE cockpit view.

Follows the project pattern (see test_engine_picker_contracts.py):
test pure helpers, skip Tkinter runtime rendering.
"""
from __future__ import annotations

import pytest


class TestLiveReadySlugs:
    def test_contains_citadel_janestreet_live(self):
        from config.engines import LIVE_READY_SLUGS
        assert "citadel" in LIVE_READY_SLUGS
        assert "janestreet" in LIVE_READY_SLUGS
        assert "live" in LIVE_READY_SLUGS

    def test_excludes_research_engines(self):
        from config.engines import LIVE_READY_SLUGS
        # These have backtest entrypoints but not live-validated runners.
        assert "renaissance" not in LIVE_READY_SLUGS
        assert "jump" not in LIVE_READY_SLUGS
        assert "deshaw" not in LIVE_READY_SLUGS
        assert "kepos" not in LIVE_READY_SLUGS
        assert "phi" not in LIVE_READY_SLUGS

    def test_live_ready_flag_on_each_engine(self):
        from config.engines import ENGINES
        for slug, meta in ENGINES.items():
            assert "live_ready" in meta, f"{slug} missing live_ready flag"
            assert isinstance(meta["live_ready"], bool)
```

- [ ] **Step 2: Run test to confirm failure**

Run: `python -m pytest tests/test_engines_live_view.py::TestLiveReadySlugs -v`
Expected: `ImportError` or `AttributeError` — `LIVE_READY_SLUGS` not defined.

- [ ] **Step 3: Modify `config/engines.py`**

For each engine in `ENGINES`, add `"live_ready": <bool>`. The 3 live-ready slugs today (from `launcher.py:8378` hardcode) are `citadel`, `janestreet`, `live`. All others default to `False`.

Replace the `ENGINES = {...}` block with:

```python
ENGINES = {
    "citadel":     {"script": "engines/citadel.py",      "display": "CITADEL",     "desc": "Systematic momentum — trend-following + fractal alignment",        "live_ready": True},
    "renaissance": {"script": "engines/renaissance.py",   "display": "RENAISSANCE", "desc": "Pattern recognition — harmonic geometry + Bayesian scoring",       "live_ready": False},
    "jump":        {"script": "engines/jump.py",      "display": "JUMP",        "desc": "Order flow — CVD divergence + volume imbalance",                   "live_ready": False},
    "bridgewater": {"script": "engines/bridgewater.py",         "display": "BRIDGEWATER", "desc": "Macro sentiment — funding + OI + LS ratio contrarian",             "live_ready": False},
    "deshaw":      {"script": "engines/deshaw.py",        "display": "DE SHAW",     "desc": "Statistical arb — pairs cointegration + mean reversion",           "live_ready": False},
    "millennium":  {"script": "engines/millennium.py", "display": "MILLENNIUM",  "desc": "Multi-strategy pod — ensemble orchestrator",                       "live_ready": False},
    "twosigma":    {"script": "engines/twosigma.py",      "display": "TWO SIGMA",   "desc": "ML meta-ensemble — LightGBM walk-forward",                         "live_ready": False},
    "janestreet":  {"script": "engines/janestreet.py",     "display": "JANE STREET", "desc": "Cross-venue arb — funding/basis multi-exchange",                   "live_ready": True},
    "aqr":         {"script": "engines/aqr.py",        "display": "AQR",         "desc": "Adaptive allocation — evolutionary parameter optimization",        "live_ready": False},
    "kepos":       {"script": "engines/kepos.py",      "display": "KEPOS",       "desc": "Critical endogeneity fade — Hawkes η≥0.95 reversal plays",         "live_ready": False},
    "graham":      {"script": "engines/graham.py",     "display": "GRAHAM",      "desc": "Endogenous momentum — trend-following gated by Hawkes ENDO regime","live_ready": False},
    "medallion":   {"script": "engines/medallion.py",  "display": "MEDALLION",   "desc": "Berlekamp-Laufer short-term mean-reversion — 7-signal ensemble + Kelly","live_ready": False},
    "phi":         {"script": "engines/phi.py",       "display": "PHI",         "desc": "Fibonacci fractal — multi-TF 0.618 confluence + Golden Trigger",   "live_ready": False},
    "winton":      {"script": "core/chronos.py",          "display": "WINTON",      "desc": "Time-series intelligence — HMM + GARCH + Hurst + seasonality",     "live_ready": False},
    "live":        {"script": "engines/live.py",          "display": "LIVE",        "desc": "Live execution — paper / demo / testnet / real",                   "live_ready": True},
}
```

After the `SCRIPT_TO_KEY = {...}` line (around line 34), add:

```python
# Engines with a validated live runner (paper/demo/testnet/live modes).
# Consumed by launcher_support/engines_live_view.py to split the picker
# into READY LIVE vs RESEARCH buckets. Update this flag per engine only
# after a run-paper smoke test confirms the live entrypoint works.
LIVE_READY_SLUGS = frozenset(k for k, v in ENGINES.items() if v.get("live_ready"))
```

- [ ] **Step 4: Run test to verify pass**

Run: `python -m pytest tests/test_engines_live_view.py::TestLiveReadySlugs -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add config/engines.py tests/test_engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines): live_ready flag + LIVE_READY_SLUGS registry

Replaces the hardcoded {citadel, janestreet, live} set in
launcher.py:8378 with a config-level flag per engine. Prep for
engines_live cockpit redesign.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add mode color semantic aliases to `ui_palette.py`

**Files:**
- Modify: `core/ui_palette.py`
- Test: `tests/test_engines_live_view.py`

- [ ] **Step 1: Append failing test**

Append to `tests/test_engines_live_view.py`:

```python
class TestModeColorAliases:
    def test_mode_aliases_map_to_existing_tokens(self):
        from core.ui_palette import (
            MODE_PAPER, MODE_DEMO, MODE_TESTNET, MODE_LIVE,
            CYAN, GREEN, AMBER, RED,
        )
        assert MODE_PAPER == CYAN
        assert MODE_DEMO == GREEN
        assert MODE_TESTNET == AMBER
        assert MODE_LIVE == RED
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_engines_live_view.py::TestModeColorAliases -v`
Expected: `ImportError` for `MODE_PAPER`.

- [ ] **Step 3: Append aliases to `core/ui_palette.py`**

Append after the last line (line 91, `FONT = "Consolas"`):

```python

# ── Mode color aliases (engines_live_view) ─────────────────────
# Semantic pointers into the HL2 palette. The view consumes these
# instead of CYAN/GREEN/AMBER/RED directly so future retuning of
# mode semantics happens here, not at call sites.
MODE_PAPER   = CYAN    # neutral — local simulation, no exchange
MODE_DEMO    = GREEN   # safe — exchange demo (fake money, real feed)
MODE_TESTNET = AMBER   # warning — real infrastructure, fake money
MODE_LIVE    = RED     # danger — real money, real orders
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_engines_live_view.py::TestModeColorAliases -v`
Expected: 1 PASS.

- [ ] **Step 5: Commit**

```bash
git add core/ui_palette.py tests/test_engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(ui_palette): MODE_PAPER/DEMO/TESTNET/LIVE semantic aliases

Adds pointers into the existing HL2 palette so engines_live_view
can consume mode colors by semantic name rather than hardcoding
CYAN/GREEN/AMBER/RED at call sites.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Create `engines_live_view` module skeleton + bucket assignment logic

**Files:**
- Create: `launcher_support/engines_live_view.py`
- Test: `tests/test_engines_live_view.py`

- [ ] **Step 1: Append failing test for bucket assignment**

Append to `tests/test_engines_live_view.py`:

```python
class TestBucketAssignment:
    def test_live_takes_precedence_over_ready(self):
        from launcher_support.engines_live_view import assign_bucket
        # Engine is live_ready AND currently running → LIVE bucket.
        assert assign_bucket(slug="citadel", is_running=True, live_ready=True) == "LIVE"

    def test_ready_when_not_running_and_live_ready(self):
        from launcher_support.engines_live_view import assign_bucket
        assert assign_bucket(slug="citadel", is_running=False, live_ready=True) == "READY"

    def test_research_when_not_live_ready(self):
        from launcher_support.engines_live_view import assign_bucket
        assert assign_bucket(slug="renaissance", is_running=False, live_ready=False) == "RESEARCH"

    def test_research_engine_running_stays_research(self):
        # Edge case: a research engine spawned via backtest path is running.
        # It should NOT jump into LIVE bucket of the cockpit view — only
        # engines declared live_ready can occupy LIVE.
        from launcher_support.engines_live_view import assign_bucket
        assert assign_bucket(slug="renaissance", is_running=True, live_ready=False) == "RESEARCH"
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_engines_live_view.py::TestBucketAssignment -v`
Expected: `ModuleNotFoundError` — module doesn't exist.

- [ ] **Step 3: Create `launcher_support/engines_live_view.py` with skeleton + assign_bucket**

```python
"""AURUM — ENGINES LIVE cockpit view.

Hybrid master-detail UI for the EXECUTE → ENGINES LIVE entry.
Separates engines into three buckets by readiness:

    LIVE        — currently running live/demo/testnet/paper
    READY       — has a validated live runner (ENGINES[*].live_ready)
    RESEARCH    — backtest-only, not exposed for live execution

Pure helpers here are testable; Tkinter rendering is smoke-tested
via `python launcher.py` → EXECUTE → ENGINES LIVE.

Spec: docs/superpowers/specs/2026-04-16-engines-live-cockpit-design.md
"""
from __future__ import annotations

from typing import Literal

Bucket = Literal["LIVE", "READY", "RESEARCH"]


def assign_bucket(*, slug: str, is_running: bool, live_ready: bool) -> Bucket:
    """Decide which bucket an engine belongs to in the cockpit view.

    Rules:
      - A running engine that is also live_ready → LIVE.
      - A non-running live_ready engine → READY.
      - Anything not live_ready → RESEARCH (even if running, since it was
        spawned through the backtest path and doesn't belong on the live
        cockpit).
    """
    if not live_ready:
        return "RESEARCH"
    return "LIVE" if is_running else "READY"
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest tests/test_engines_live_view.py::TestBucketAssignment -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live_view.py tests/test_engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): skeleton module + assign_bucket helper

First cut of the new cockpit view. assign_bucket is the single
source of truth for LIVE/READY/RESEARCH placement. UI rendering
follows in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Mode state — cycle + persistence

**Files:**
- Modify: `launcher_support/engines_live_view.py`
- Test: `tests/test_engines_live_view.py`

- [ ] **Step 1: Append failing tests**

```python
class TestModeCycle:
    def test_cycle_paper_to_demo(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("paper") == "demo"

    def test_cycle_demo_to_testnet(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("demo") == "testnet"

    def test_cycle_testnet_to_live(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("testnet") == "live"

    def test_cycle_live_wraps_to_paper(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("live") == "paper"

    def test_cycle_unknown_falls_back_to_paper(self):
        from launcher_support.engines_live_view import cycle_mode
        assert cycle_mode("bogus") == "paper"


class TestModePersistence:
    def test_load_returns_paper_when_file_missing(self, tmp_path):
        from launcher_support.engines_live_view import load_mode
        # tmp_path has no ui_state.json.
        assert load_mode(state_path=tmp_path / "ui_state.json") == "paper"

    def test_load_returns_saved_mode(self, tmp_path):
        import json
        from launcher_support.engines_live_view import load_mode, save_mode
        sp = tmp_path / "ui_state.json"
        save_mode("demo", state_path=sp)
        assert load_mode(state_path=sp) == "demo"

    def test_load_rejects_invalid_mode(self, tmp_path):
        import json
        from launcher_support.engines_live_view import load_mode
        sp = tmp_path / "ui_state.json"
        sp.write_text(json.dumps({"engines_live": {"mode": "bogus"}}))
        # Invalid persisted value → safe default.
        assert load_mode(state_path=sp) == "paper"

    def test_save_preserves_other_keys(self, tmp_path):
        import json
        from launcher_support.engines_live_view import save_mode
        sp = tmp_path / "ui_state.json"
        sp.write_text(json.dumps({"other_view": {"foo": 1}}))
        save_mode("testnet", state_path=sp)
        loaded = json.loads(sp.read_text())
        assert loaded["other_view"] == {"foo": 1}
        assert loaded["engines_live"]["mode"] == "testnet"
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_engines_live_view.py::TestModeCycle tests/test_engines_live_view.py::TestModePersistence -v`
Expected: all fail with `ImportError` for `cycle_mode`/`load_mode`/`save_mode`.

- [ ] **Step 3: Append helpers to `engines_live_view.py`**

Add at the top (after imports):

```python
import json
from pathlib import Path

Mode = Literal["paper", "demo", "testnet", "live"]

_MODE_ORDER: tuple[Mode, ...] = ("paper", "demo", "testnet", "live")
_DEFAULT_MODE: Mode = "paper"
_DEFAULT_STATE_PATH = Path("data/ui_state.json")
```

Append at module end:

```python
def cycle_mode(current: str) -> Mode:
    """paper → demo → testnet → live → paper. Unknown input → paper."""
    try:
        idx = _MODE_ORDER.index(current)  # type: ignore[arg-type]
    except ValueError:
        return _DEFAULT_MODE
    return _MODE_ORDER[(idx + 1) % len(_MODE_ORDER)]


def load_mode(*, state_path: Path | None = None) -> Mode:
    """Read engines_live.mode from ui_state.json. Missing/invalid → paper."""
    path = state_path or _DEFAULT_STATE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULT_MODE
    mode = (data.get("engines_live") or {}).get("mode")
    if mode in _MODE_ORDER:
        return mode  # type: ignore[return-value]
    return _DEFAULT_MODE


def save_mode(mode: Mode, *, state_path: Path | None = None) -> None:
    """Persist engines_live.mode into ui_state.json. Preserves other keys.

    Uses atomic_write_json so a crashed write leaves the prior file intact.
    """
    from core.persistence import atomic_write_json
    path = state_path or _DEFAULT_STATE_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    block = dict(data.get("engines_live") or {})
    block["mode"] = mode
    data["engines_live"] = block
    atomic_write_json(path, data)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_engines_live_view.py -v`
Expected: all prior tests still pass + 9 new pass (5 cycle + 4 persistence).

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live_view.py tests/test_engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): mode state cycle + persistence

cycle_mode, load_mode, save_mode — drive the global PAPER · DEMO ·
TESTNET · LIVE switcher in the cockpit header. Persists to
data/ui_state.json via core.persistence.atomic_write_json.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: LIVE confirmation validation + uptime formatting

**Files:**
- Modify: `launcher_support/engines_live_view.py`
- Test: `tests/test_engines_live_view.py`

- [ ] **Step 1: Append failing tests**

```python
class TestLiveConfirmValidates:
    def test_exact_match_confirms(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="CITADEL") is True

    def test_case_sensitive(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="citadel") is False

    def test_trailing_space_rejected(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="CITADEL ") is False

    def test_empty_rejected(self):
        from launcher_support.engines_live_view import live_confirm_ok
        assert live_confirm_ok(engine_name="CITADEL", user_input="") is False


class TestFormatUptime:
    def test_minutes_only(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=42 * 60) == "42m"

    def test_hours_and_minutes(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=2 * 3600 + 14 * 60) == "2h14m"

    def test_zero_seconds(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=0) == "0m"

    def test_sub_minute_rounds_down(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=45) == "0m"

    def test_none_returns_em_dash(self):
        from launcher_support.engines_live_view import format_uptime
        assert format_uptime(seconds=None) == "—"
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_engines_live_view.py::TestLiveConfirmValidates tests/test_engines_live_view.py::TestFormatUptime -v`
Expected: all fail — functions not defined.

- [ ] **Step 3: Append helpers**

Append to `engines_live_view.py`:

```python
def live_confirm_ok(*, engine_name: str, user_input: str) -> bool:
    """Case-sensitive, whitespace-strict match used by the LIVE modal."""
    return user_input == engine_name


def format_uptime(*, seconds: float | int | None) -> str:
    """Render uptime compactly for bucket rows and cockpit headers."""
    if seconds is None:
        return "—"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, _ = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_engines_live_view.py -v`
Expected: 9 new pass (4 confirm + 5 uptime). All prior still pass.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live_view.py tests/test_engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): live_confirm_ok + format_uptime helpers

Pure helpers for the LIVE-mode ritual modal (exact-name match) and
the LIVE bucket row uptime display. Shared between header/detail
rendering paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Running-engine discovery helper

**Files:**
- Modify: `launcher_support/engines_live_view.py`
- Test: `tests/test_engines_live_view.py`

Today `launcher._strategies` maps `proc["engine"]` (legacy proc names) to engine slugs via a hardcoded `_proc_to_slug` dict. This helper lifts that logic out so the new view can consume it and the test can cover the mapping.

- [ ] **Step 1: Append failing tests**

```python
class TestRunningEnginesByBucket:
    def test_maps_citadel_proc_to_citadel_slug(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "backtest", "status": "running", "alive": True, "pid": 100}]
        out = running_slugs_from_procs(procs)
        # "backtest" is the legacy proc name for citadel.
        assert "citadel" in out

    def test_ignores_dead_procs(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "backtest", "status": "running", "alive": False, "pid": 100}]
        assert running_slugs_from_procs(procs) == {}

    def test_ignores_non_running_status(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "backtest", "status": "stopped", "alive": True, "pid": 100}]
        assert running_slugs_from_procs(procs) == {}

    def test_maps_arb_to_janestreet(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "arb", "status": "running", "alive": True, "pid": 7}]
        assert "janestreet" in running_slugs_from_procs(procs)

    def test_unknown_engine_name_dropped(self):
        from launcher_support.engines_live_view import running_slugs_from_procs
        procs = [{"engine": "ghost", "status": "running", "alive": True, "pid": 9}]
        assert running_slugs_from_procs(procs) == {}
```

- [ ] **Step 2: Run to confirm failure**

Run: `python -m pytest tests/test_engines_live_view.py::TestRunningEnginesByBucket -v`
Expected: 5 fail — function missing.

- [ ] **Step 3: Append helper**

```python
# Legacy proc-manager engine names → canonical slugs.
# Matches the mapping in launcher.py::_strategies (_proc_to_slug).
_PROC_TO_SLUG: dict[str, str] = {
    "backtest":    "citadel",
    "mercurio":    "jump",
    "thoth":       "bridgewater",
    "newton":      "deshaw",
    "multi":       "millennium",
    "prometeu":    "twosigma",
    "renaissance": "renaissance",
    "live":        "live",
    "arb":         "janestreet",
    "darwin":      "aqr",
    "chronos":     "winton",
    "kepos":       "kepos",
    "graham":      "graham",
    "medallion":   "medallion",
}


def running_slugs_from_procs(procs: list[dict]) -> dict[str, dict]:
    """Filter live proc-manager rows into {slug: proc_row}.

    A proc is considered running when status=='running' AND alive=True.
    Unknown engine names are dropped silently.
    """
    out: dict[str, dict] = {}
    for p in procs:
        if p.get("status") != "running" or not p.get("alive"):
            continue
        slug = _PROC_TO_SLUG.get(p.get("engine"))
        if slug:
            out[slug] = p
    return out
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_engines_live_view.py -v`
Expected: 5 new pass + all prior pass.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/engines_live_view.py tests/test_engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): running_slugs_from_procs helper

Lifts the legacy proc-name → slug mapping out of launcher._strategies
so the new cockpit can consume it and the test suite can cover it.
No behavior change yet — launcher keeps its inline mapping until the
view swap in a later commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Render shell — header + empty body + footer (smoke-testable)

**Files:**
- Modify: `launcher_support/engines_live_view.py`

From here on, tasks produce Tkinter code. Tests stay at pure-helper level; manual smoke test is `python launcher.py` → EXECUTE → ENGINES LIVE.

- [ ] **Step 1: Add `render()` entrypoint + header strip**

Append to `engines_live_view.py`:

```python
import tkinter as tk

from core.ui_palette import (
    BG, BG2, BG3, PANEL,
    BORDER, BORDER_H,
    AMBER, AMBER_B, AMBER_D, AMBER_H,
    WHITE, DIM, DIM2,
    GREEN, RED, CYAN, HAZARD,
    MODE_PAPER, MODE_DEMO, MODE_TESTNET, MODE_LIVE,
    FONT,
)


_MODE_COLORS: dict[Mode, str] = {
    "paper":   MODE_PAPER,
    "demo":    MODE_DEMO,
    "testnet": MODE_TESTNET,
    "live":    MODE_LIVE,
}


def render(launcher, parent, *, on_escape) -> dict:
    """Mount the ENGINES LIVE cockpit view onto `parent`.

    `launcher` is the AurumTerminal instance (for _kb/_exec/_clr utilities).
    `on_escape` is a no-arg callable invoked when ESC is pressed.

    Returns a handle dict:
        {"refresh": callable, "cleanup": callable, "set_mode": callable}
    """
    state: dict = {
        "mode":           load_mode(),
        "selected_slug":  None,
        "after_handles":  [],
        "bound_keys":     [],
    }

    root = tk.Frame(parent, bg=BG)
    root.pack(fill="both", expand=True)

    header = _build_header(root, launcher, state)
    header.pack(fill="x", padx=14, pady=(10, 0))

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=14, pady=(8, 0))

    # Split 38/62 master/detail. Use weights so window resizing keeps the
    # split ratio stable.
    body.grid_columnconfigure(0, weight=38, uniform="body")
    body.grid_columnconfigure(1, weight=62, uniform="body")
    body.grid_rowconfigure(0, weight=1)

    state["master_host"] = tk.Frame(body, bg=BG)
    state["master_host"].grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    state["detail_host"] = tk.Frame(body, bg=BG)
    state["detail_host"].grid(row=0, column=1, sticky="nsew")

    footer = _build_footer(root, state)
    footer.pack(fill="x", padx=14, pady=(6, 10))
    state["footer_frame"] = footer

    # Keyboard nav
    def _kb(seq, fn):
        launcher._kb(seq, fn)
        state["bound_keys"].append(seq)

    _kb("<Escape>", on_escape)
    _kb("<Key-0>", on_escape)

    def refresh():
        _render_master_list(state, launcher)
        _render_detail(state, launcher)
        _refresh_header(state)
        _refresh_footer(state)

    def cleanup():
        for aid in state.get("after_handles", []):
            try:
                launcher.after_cancel(aid)
            except Exception:
                pass

    def set_mode(mode: Mode):
        if mode not in _MODE_ORDER:
            return
        state["mode"] = mode
        save_mode(mode)
        refresh()

    state["refresh"] = refresh
    state["set_mode"] = set_mode

    _kb("<KeyPress-m>", lambda _e=None: set_mode(cycle_mode(state["mode"])))
    _kb("<KeyPress-M>", lambda _e=None: set_mode(cycle_mode(state["mode"])))

    refresh()
    return {"refresh": refresh, "cleanup": cleanup, "set_mode": set_mode}


def _build_header(parent, launcher, state) -> tk.Frame:
    h = tk.Frame(parent, bg=BG)
    tk.Frame(h, bg=AMBER, width=3, height=22).pack(side="left", padx=(0, 8))
    tk.Label(h, text="ENGINES", font=(FONT, 12, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 14))

    pill_row = tk.Frame(h, bg=BG)
    pill_row.pack(side="left")
    state["mode_pills"] = {}
    for mode in _MODE_ORDER:
        pill = tk.Label(pill_row, text=f" {mode.upper()} ",
                        font=(FONT, 7, "bold"),
                        padx=6, pady=3, cursor="hand2")
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _m=mode: state["set_mode"](_m))
        state["mode_pills"][mode] = pill

    # Right: counts + market label
    right = tk.Frame(h, bg=BG)
    right.pack(side="right")
    state["counts_lbl"] = tk.Label(right, text="", font=(FONT, 7, "bold"),
                                    fg=DIM, bg=BG)
    state["counts_lbl"].pack(side="right", padx=(8, 0))
    # Header bottom rule — turns RED when mode=live (set in _refresh_header)
    state["header_rule"] = tk.Frame(parent, bg=BORDER, height=1)
    state["header_rule"].pack(fill="x", pady=(8, 0))
    return h


def _refresh_header(state):
    for mode, pill in state["mode_pills"].items():
        color = _MODE_COLORS[mode]
        if mode == state["mode"]:
            pill.configure(fg=BG, bg=color)
        else:
            pill.configure(fg=color, bg=BG3)
    state["header_rule"].configure(bg=(RED if state["mode"] == "live" else BORDER))


def _build_footer(parent, state) -> tk.Frame:
    f = tk.Frame(parent, bg=BG)
    state["footer_lbl"] = tk.Label(f, text="", font=(FONT, 7),
                                    fg=DIM, bg=BG, anchor="w")
    state["footer_lbl"].pack(side="left", fill="x", expand=True)
    state["footer_warn_lbl"] = tk.Label(f, text="", font=(FONT, 7, "bold"),
                                         fg=RED, bg=BG)
    state["footer_warn_lbl"].pack(side="right")
    return f


def _refresh_footer(state):
    selected = state.get("selected_bucket")
    hints = ["ESC main", "▲▼ select"]
    if selected == "LIVE":
        hints += ["S stop", "L log"]
    elif selected == "READY":
        hints += ["ENTER run"]
    elif selected == "RESEARCH":
        hints += ["B backtest"]
    hints += ["M cycle mode"]
    state["footer_lbl"].configure(text="  ·  ".join(hints))
    state["footer_warn_lbl"].configure(
        text=("⚠ LIVE MODE — real orders will be placed"
              if state["mode"] == "live" else ""))


def _render_master_list(state, launcher):
    """Stub — filled in Task 8."""
    for w in state["master_host"].winfo_children():
        w.destroy()
    tk.Label(state["master_host"], text="(master list — task 8)",
             fg=DIM, bg=BG, font=(FONT, 8)).pack(pady=20)


def _render_detail(state, launcher):
    """Stub — filled in Task 9."""
    for w in state["detail_host"].winfo_children():
        w.destroy()
    tk.Label(state["detail_host"], text="(detail — task 9)",
             fg=DIM, bg=BG, font=(FONT, 8)).pack(pady=20)
```

- [ ] **Step 2: Quick syntax check**

Run: `python -c "from launcher_support import engines_live_view; print(engines_live_view.render)"`
Expected: prints `<function render at 0x...>`. No exception.

- [ ] **Step 3: Smoke test — mount via a throwaway entry point**

The view isn't wired into the launcher yet. Validate with a tiny script:

Run:

```bash
python -c "
import tkinter as tk
from types import SimpleNamespace
from launcher_support import engines_live_view

root = tk.Tk()
root.geometry('1200x720')
root.configure(bg='#2A2A2A')
# Fake launcher shim — only _kb and after_cancel needed for shell.
launcher = SimpleNamespace(
    _kb=lambda seq, fn: root.bind_all(seq, lambda e, f=fn: f()),
    after_cancel=lambda aid: None,
    after=root.after,
)
h = engines_live_view.render(launcher, root, on_escape=root.destroy)
root.after(500, root.destroy)   # auto-close after 0.5s
root.mainloop()
print('shell mounted OK')
"
```

Expected: `shell mounted OK`. No exception. (The window flashes briefly.)

- [ ] **Step 4: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): shell — header + body split + footer

Mounts the view skeleton: header strip with mode pills (click + M
keybind), master/detail split at 38/62, footer with dynamic keybind
hints. Master list and detail panel are stubs filled by later tasks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Render master list — 3 buckets

**Files:**
- Modify: `launcher_support/engines_live_view.py`

- [ ] **Step 1: Replace `_render_master_list` stub**

Find the `_render_master_list(state, launcher)` stub added in Task 7 and replace it with:

```python
def _render_master_list(state, launcher):
    """Mount the 3-bucket master list on state['master_host']."""
    host = state["master_host"]
    for w in host.winfo_children():
        w.destroy()

    # Pull current data
    from config.engines import ENGINES, LIVE_READY_SLUGS
    try:
        from core.proc import list_procs
        procs = list_procs()
    except Exception:
        procs = []
    running = running_slugs_from_procs(procs)

    # Build ordered lists per bucket
    live_items: list[tuple[str, dict, dict]] = []      # (slug, meta, proc)
    ready_items: list[tuple[str, dict]] = []
    research_items: list[tuple[str, dict]] = []
    for slug, meta in ENGINES.items():
        live_ready = slug in LIVE_READY_SLUGS
        bucket = assign_bucket(
            slug=slug,
            is_running=slug in running,
            live_ready=live_ready,
        )
        if bucket == "LIVE":
            live_items.append((slug, meta, running[slug]))
        elif bucket == "READY":
            ready_items.append((slug, meta))
        else:
            research_items.append((slug, meta))

    # Scrollable container
    canvas = tk.Canvas(host, bg=BG, highlightthickness=0)
    vbar = tk.Scrollbar(host, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas, bg=BG)
    inner.bind("<Configure>",
               lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")

    # Default selection: first LIVE, else first READY, else first RESEARCH
    if state.get("selected_slug") is None:
        if live_items:
            state["selected_slug"] = live_items[0][0]
            state["selected_bucket"] = "LIVE"
        elif ready_items:
            state["selected_slug"] = ready_items[0][0]
            state["selected_bucket"] = "READY"
        elif research_items:
            state["selected_slug"] = research_items[0][0]
            state["selected_bucket"] = "RESEARCH"

    _render_bucket(inner, "LIVE", live_items, state)
    _render_bucket(inner, "READY LIVE", ready_items, state)
    _render_bucket(inner, "RESEARCH", research_items, state)

    # Counts pill in header
    total = len(live_items) + len(ready_items) + len(research_items)
    state["counts_lbl"].configure(
        text=f"{total} engines  ·  {len(live_items)} live")


def _render_bucket(parent, title, items, state):
    if not items:
        return
    header = tk.Frame(parent, bg=BG)
    header.pack(fill="x", pady=(8, 2))
    tk.Frame(header, bg=AMBER, width=3, height=14).pack(side="left", padx=(0, 6))
    tk.Label(header, text=f"{title}", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left")
    tk.Label(header, text=f"  · {len(items)}", font=(FONT, 7),
             fg=DIM, bg=BG).pack(side="left")
    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))

    is_live_bucket = title == "LIVE"
    is_research = title == "RESEARCH"
    for tup in items:
        if is_live_bucket:
            slug, meta, proc = tup
            _render_row_live(parent, slug, meta, proc, state)
        elif is_research:
            slug, meta = tup
            _render_row_research(parent, slug, meta, state)
        else:
            slug, meta = tup
            _render_row_ready(parent, slug, meta, state)


def _select_slug(state, slug: str, bucket: Bucket):
    """Update selection and re-render master + detail."""
    state["selected_slug"] = slug
    state["selected_bucket"] = bucket
    state["refresh"]()


def _row_base(parent, slug, state, is_selected):
    bg = BG3 if is_selected else BG
    row = tk.Frame(parent, bg=bg, cursor="hand2",
                   highlightbackground=(AMBER_B if is_selected else BG),
                   highlightthickness=0)
    # left selection bar (3px amber when selected)
    tk.Frame(row, bg=(AMBER_B if is_selected else BG), width=3).pack(side="left", fill="y")
    row.pack(fill="x", pady=1)
    return row


def _render_row_live(parent, slug, meta, proc, state):
    sel = state.get("selected_slug") == slug
    row = _row_base(parent, slug, state, is_selected=sel)
    # Dot
    tk.Label(row, text="●", fg=GREEN, bg=row["bg"],
             font=(FONT, 9, "bold"), padx=4).pack(side="left")
    # Name
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=WHITE, bg=row["bg"], font=(FONT, 9, "bold")).pack(side="left")
    # Mode + uptime
    mode_key = (proc.get("engine_mode") or proc.get("mode") or "").lower()
    if mode_key in _MODE_ORDER:
        tk.Label(row, text=f" {mode_key.upper()} ",
                 fg=BG, bg=_MODE_COLORS[mode_key],
                 font=(FONT, 7, "bold"), padx=4, pady=1).pack(side="left", padx=(6, 0))
    started = proc.get("started")
    if started:
        try:
            from datetime import datetime as _dt
            secs = (_dt.now() - _dt.fromisoformat(started)).total_seconds()
            tk.Label(row, text=format_uptime(seconds=secs),
                     fg=DIM2, bg=row["bg"], font=(FONT, 8)).pack(side="left", padx=(8, 0))
        except Exception:
            pass
    # Click binding
    for w in (row,) + tuple(row.winfo_children()):
        w.bind("<Button-1>", lambda _e, _s=slug: _select_slug(state, _s, "LIVE"))


def _render_row_ready(parent, slug, meta, state):
    sel = state.get("selected_slug") == slug
    row = _row_base(parent, slug, state, is_selected=sel)
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=WHITE, bg=row["bg"], font=(FONT, 9, "bold"),
             padx=8).pack(side="left")
    sub = _subtitle_for(slug, meta)
    if sub:
        tk.Label(row, text=sub, fg=DIM, bg=row["bg"],
                 font=(FONT, 7)).pack(side="left", padx=(4, 0))
    for w in (row,) + tuple(row.winfo_children()):
        w.bind("<Button-1>", lambda _e, _s=slug: _select_slug(state, _s, "READY"))


def _render_row_research(parent, slug, meta, state):
    sel = state.get("selected_slug") == slug
    row = _row_base(parent, slug, state, is_selected=sel)
    tk.Label(row, text="🔒", fg=DIM, bg=row["bg"],
             font=(FONT, 8), padx=4).pack(side="left")
    tk.Label(row, text=meta.get("display", slug.upper()),
             fg=DIM, bg=row["bg"], font=(FONT, 9)).pack(side="left")
    sub = _subtitle_for(slug, meta)
    if sub:
        tk.Label(row, text=sub, fg=DIM2, bg=row["bg"],
                 font=(FONT, 7)).pack(side="left", padx=(4, 0))
    for w in (row,) + tuple(row.winfo_children()):
        w.bind("<Button-1>", lambda _e, _s=slug: _select_slug(state, _s, "RESEARCH"))


def _subtitle_for(slug, meta) -> str:
    """Tagline fallback — extended later to read DB / BRIEFINGS."""
    desc = meta.get("desc") or ""
    return desc[:44]
```

- [ ] **Step 2: Smoke test**

Run the same probe from Task 7 Step 3. Expected: window briefly shows 3 buckets with engines listed; `shell mounted OK` prints; no exception.

- [ ] **Step 3: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): master list with LIVE/READY/RESEARCH buckets

Renders three vertical buckets with amber separators. Clicking a row
selects it; selection triggers a refresh (detail panel stubbed until
Task 9). Uses assign_bucket + running_slugs_from_procs from earlier
commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Render detail panel — RESEARCH skin (simplest)

**Files:**
- Modify: `launcher_support/engines_live_view.py`

- [ ] **Step 1: Replace `_render_detail` stub + add research skin**

Replace the `_render_detail(state, launcher)` stub added in Task 7:

```python
def _render_detail(state, launcher):
    host = state["detail_host"]
    for w in host.winfo_children():
        w.destroy()

    slug = state.get("selected_slug")
    bucket = state.get("selected_bucket")
    if not slug:
        tk.Label(host, text="(no selection)", fg=DIM, bg=BG,
                 font=(FONT, 8)).pack(pady=20)
        return

    from config.engines import ENGINES
    meta = ENGINES.get(slug, {})

    card = tk.Frame(host, bg=PANEL,
                    highlightbackground=BORDER, highlightthickness=1)
    card.pack(fill="both", expand=True)

    if bucket == "RESEARCH":
        _render_detail_research(card, slug, meta, state, launcher)
    elif bucket == "READY":
        _render_detail_ready(card, slug, meta, state, launcher)
    elif bucket == "LIVE":
        _render_detail_live(card, slug, meta, state, launcher)


def _render_detail_research(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=" [ RESEARCH ONLY ] ",
             fg=BG, bg=HAZARD, font=(FONT, 7, "bold"),
             padx=6, pady=2).pack(side="right")

    if desc:
        tk.Label(parent, text=desc, fg=DIM, bg=PANEL,
                 font=(FONT, 8), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=12, pady=(0, 8))

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    note = tk.Frame(parent, bg=PANEL)
    note.pack(fill="x", padx=12, pady=12)
    tk.Label(note, text="⚠", fg=HAZARD, bg=PANEL,
             font=(FONT, 12, "bold")).pack(side="left", padx=(0, 8))
    tk.Label(
        note,
        text=("Essa engine ainda não tem entrypoint live validado.\n"
              "Rode em backtest: EXECUTE → BACKTEST → " + name),
        fg=HAZARD, bg=PANEL, font=(FONT, 8),
        anchor="w", justify="left",
    ).pack(side="left", fill="x", expand=True)

    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(8, 12))
    _action_btn(actions, "GO TO BACKTEST", AMBER,
                lambda: _go_to_backtest(launcher, slug))
    _action_btn(actions, "VIEW CODE", DIM,
                lambda: _view_code(launcher, meta.get("script", "")))


def _action_btn(parent, label, color, cmd):
    b = tk.Label(parent, text=f"  {label}  ",
                 fg=color, bg=BG3,
                 font=(FONT, 8, "bold"),
                 cursor="hand2", padx=4, pady=6)
    b.pack(side="left", padx=(0, 8))
    b.bind("<Button-1>", lambda _e: cmd())
    b.bind("<Enter>", lambda _e, _b=b, _c=color: _b.configure(fg=BG, bg=_c))
    b.bind("<Leave>", lambda _e, _b=b, _c=color: _b.configure(fg=_c, bg=BG3))
    return b


def _go_to_backtest(launcher, slug: str):
    """Bounce to EXECUTE → BACKTEST, pre-selecting this engine if possible."""
    fn = getattr(launcher, "_strategies_backtest", None)
    if callable(fn):
        fn()


def _view_code(launcher, script_path: str):
    if not script_path:
        return
    try:
        from code_viewer import CodeViewer
        CodeViewer(launcher, script_path)
    except Exception:
        pass


def _render_detail_ready(parent, slug, meta, state, launcher):
    """Stub — filled in Task 10."""
    tk.Label(parent, text=f"(ready — task 10) {slug}",
             fg=DIM, bg=PANEL, font=(FONT, 8)).pack(pady=20)


def _render_detail_live(parent, slug, meta, state, launcher):
    """Stub — filled in Task 11."""
    tk.Label(parent, text=f"(live — task 11) {slug}",
             fg=DIM, bg=PANEL, font=(FONT, 8)).pack(pady=20)
```

- [ ] **Step 2: Smoke test**

Same probe as before. Window shows master list; selecting a RESEARCH row (e.g. RENAISSANCE) shows the yellow `[ RESEARCH ONLY ]` badge and the warning text. No exception.

- [ ] **Step 3: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): detail panel — RESEARCH skin

Shows engine name + [RESEARCH ONLY] badge, description, hazard-tone
note explaining that the engine lacks a validated live runner, and
GO-TO-BACKTEST / VIEW-CODE actions. READY and LIVE skins follow in
Tasks 10 and 11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Render detail panel — READY skin (config + RUN button + LIVE modal)

**Files:**
- Modify: `launcher_support/engines_live_view.py`

- [ ] **Step 1: Replace `_render_detail_ready` stub + add LIVE modal + RUN dispatcher**

Replace the stub with:

```python
# Config defaults for the READY skin's inline config row.
_PERIOD_OPTS   = [("30D", "30"), ("90D", "90"), ("180D", "180"), ("365D", "365")]
_BASKET_OPTS   = [("DEFAULT", ""), ("TOP12", "2"), ("DEFI", "3"), ("L1", "4"),
                  ("L2", "5"), ("AI", "6"), ("MEME", "7"), ("MAJORS", "8"),
                  ("BLUECHIP", "9")]
_LEVERAGE_OPTS = [("1x", "1.0"), ("2x", "2.0"), ("3x", "3.0"), ("5x", "5.0")]


def _render_detail_ready(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())
    desc = meta.get("desc", "")

    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    tk.Label(head, text=" READY ", fg=BG, bg=GREEN,
             font=(FONT, 7, "bold"), padx=6, pady=2).pack(side="right")

    if desc:
        tk.Label(parent, text=desc, fg=DIM, bg=PANEL,
                 font=(FONT, 8), anchor="w", justify="left",
                 wraplength=520).pack(fill="x", padx=12, pady=(0, 8))

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    # Config block — stored in state["config"][slug]
    cfg_store = state.setdefault("config", {})
    cfg = cfg_store.setdefault(slug, {"period": "90", "basket": "", "leverage": "2.0"})

    cfg_frame = tk.Frame(parent, bg=PANEL)
    cfg_frame.pack(fill="x", padx=12, pady=(10, 8))
    tk.Label(cfg_frame, text="CONFIG", fg=AMBER_D, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w", pady=(0, 4))
    _config_row(cfg_frame, "Period",   _PERIOD_OPTS,   cfg, "period")
    _config_row(cfg_frame, "Basket",   _BASKET_OPTS,   cfg, "basket")
    _config_row(cfg_frame, "Leverage", _LEVERAGE_OPTS, cfg, "leverage")

    # RUN button — cor do modo global
    mode = state["mode"]
    run_color = _MODE_COLORS[mode]
    run_frame = tk.Frame(parent, bg=PANEL)
    run_frame.pack(fill="x", padx=12, pady=(8, 10))
    btn = tk.Label(
        run_frame,
        text=f"  RUN IN {mode.upper()} MODE  ",
        fg=BG, bg=run_color,
        font=(FONT, 11, "bold"),
        cursor="hand2", padx=8, pady=10,
    )
    btn.pack(fill="x")
    btn.bind("<Button-1>",
             lambda _e: _run_engine(launcher, slug, meta, state))

    # Secondary actions
    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(0, 12))
    _action_btn(actions, "VIEW CODE", DIM,
                lambda: _view_code(launcher, meta.get("script", "")))
    _action_btn(actions, "PAST RUNS", DIM,
                lambda: _past_runs(launcher, slug))


def _config_row(parent, label, opts, cfg_dict, cfg_key):
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=1)
    tk.Label(row, text=f"  {label:<10}", fg=DIM, bg=PANEL,
             font=(FONT, 8)).pack(side="left")
    for disp, val in opts:
        active = cfg_dict.get(cfg_key) == val
        fg = BG if active else DIM2
        bg = AMBER if active else BG3
        pill = tk.Label(row, text=f" {disp} ",
                        fg=fg, bg=bg, font=(FONT, 7, "bold"),
                        cursor="hand2", padx=4, pady=1)
        pill.pack(side="left", padx=(0, 3))
        pill.bind("<Button-1>",
                  lambda _e, _v=val, _k=cfg_key, _d=cfg_dict:
                      _set_cfg(_d, _k, _v, parent))


def _set_cfg(cfg_dict, key, val, parent):
    cfg_dict[key] = val
    # Re-render just the config row segment by refreshing the whole detail.
    # Cheap enough and keeps visual state consistent.
    for w in parent.winfo_children():
        w.destroy()
    # The parent here is the cfg_frame; signalling the caller to rebuild
    # the row by re-running the whole detail panel is simplest.
    top = parent.master
    while top and not hasattr(top, "_engines_live_state"):
        top = top.master
    if top and hasattr(top, "_engines_live_state"):
        top._engines_live_state["refresh"]()


def _run_engine(launcher, slug, meta, state):
    mode = state["mode"]
    cfg = (state.get("config") or {}).get(slug) or {}
    name = meta.get("display", slug.upper())
    script = meta.get("script", "")
    desc = meta.get("desc", "")

    def _spawn():
        fn = getattr(launcher, "_exec_live_inline", None)
        if callable(fn):
            fn(name, script, desc, mode, cfg)

    if mode == "live":
        _confirm_live_modal(launcher, name, on_confirm=_spawn)
    else:
        _spawn()


def _confirm_live_modal(launcher, engine_name: str, *, on_confirm):
    """Ritual modal for LIVE mode — user must type the engine name."""
    top = tk.Toplevel()
    top.title("LIVE EXECUTION")
    top.configure(bg=BG)
    top.geometry("420x240")
    top.resizable(False, False)
    top.transient()
    top.grab_set()

    tk.Label(top, text=f"LIVE EXECUTION — {engine_name}",
             fg=RED, bg=BG, font=(FONT, 10, "bold")).pack(pady=(14, 4))
    tk.Label(
        top,
        text=(f"Você está prestes a ligar {engine_name} em modo LIVE.\n"
              "Real money, real orders."),
        fg=WHITE, bg=BG, font=(FONT, 8), justify="center",
    ).pack(pady=(0, 10))
    tk.Label(top, text=f"Digite  {engine_name}  pra confirmar:",
             fg=DIM, bg=BG, font=(FONT, 8)).pack()

    var = tk.StringVar()
    entry = tk.Entry(top, textvariable=var, bg=BG3, fg=WHITE,
                     insertbackground=WHITE, font=(FONT, 10),
                     width=28, justify="center",
                     highlightbackground=BORDER, highlightthickness=1)
    entry.pack(pady=8)
    entry.focus_set()

    row = tk.Frame(top, bg=BG)
    row.pack(pady=(6, 0))
    cancel = tk.Label(row, text="  CANCEL  ", fg=DIM, bg=BG3,
                      font=(FONT, 8, "bold"), cursor="hand2",
                      padx=4, pady=6)
    cancel.pack(side="left", padx=8)
    cancel.bind("<Button-1>", lambda _e: top.destroy())

    confirm = tk.Label(row, text="  CONFIRM & RUN  ",
                       fg=DIM2, bg=BG3,
                       font=(FONT, 8, "bold"), cursor="arrow",
                       padx=4, pady=6)
    confirm.pack(side="left", padx=8)

    def _on_change(*_):
        ok = live_confirm_ok(engine_name=engine_name, user_input=var.get())
        if ok:
            confirm.configure(fg=BG, bg=RED, cursor="hand2")
            confirm.bind("<Button-1>",
                         lambda _e: (top.destroy(), on_confirm()))
        else:
            confirm.configure(fg=DIM2, bg=BG3, cursor="arrow")
            confirm.unbind("<Button-1>")
    var.trace_add("write", _on_change)
    top.bind("<Escape>", lambda _e: top.destroy())


def _past_runs(launcher, slug: str):
    fn = getattr(launcher, "_data_center", None)
    if callable(fn):
        fn()
```

Update `render()` to stash a backref on the root frame so `_set_cfg` can find the state:

In `render()`, right after the line `root = tk.Frame(parent, bg=BG)` insert:

```python
    root._engines_live_state = state
```

- [ ] **Step 2: Smoke test**

Probe again. Select CITADEL (READY bucket) → right panel shows config rows + a green `RUN IN DEMO MODE` button (if mode=demo). Click a period pill → highlight flips. Cycle mode via `M` → button text + color change. Click RUN with mode=paper/demo/testnet → attempts to call `_exec_live_inline` (may fail harmlessly in the probe since the fake launcher shim doesn't define it). With mode=live → modal pops up.

- [ ] **Step 3: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): detail panel — READY skin + LIVE modal

READY skin shows inline config (period/basket/leverage), a mode-
colored RUN button, and secondary VIEW-CODE/PAST-RUNS actions.
LIVE mode routes through a confirmation modal requiring the user
to type the engine name case-sensitively before firing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Render detail panel — LIVE skin (cockpit with KPIs + log tail + STOP)

**Files:**
- Modify: `launcher_support/engines_live_view.py`

- [ ] **Step 1: Replace `_render_detail_live` stub**

Replace with:

```python
def _render_detail_live(parent, slug, meta, state, launcher):
    name = meta.get("display", slug.upper())

    # Pull proc row from the running snapshot
    try:
        from core.proc import list_procs
        procs = list_procs()
    except Exception:
        procs = []
    running = running_slugs_from_procs(procs)
    proc = running.get(slug, {})
    mode_key = (proc.get("engine_mode") or proc.get("mode") or "paper").lower()
    mode_color = _MODE_COLORS.get(mode_key, CYAN)

    # Header
    head = tk.Frame(parent, bg=PANEL)
    head.pack(fill="x", padx=12, pady=(10, 4))
    tk.Label(head, text=name, fg=AMBER, bg=PANEL,
             font=(FONT, 11, "bold")).pack(side="left")
    right = tk.Frame(head, bg=PANEL)
    right.pack(side="right")
    tk.Label(right, text="●", fg=GREEN, bg=PANEL,
             font=(FONT, 9, "bold")).pack(side="left")
    tk.Label(right, text=f" {mode_key.upper()} ",
             fg=BG, bg=mode_color, font=(FONT, 7, "bold"),
             padx=4, pady=1).pack(side="left", padx=(4, 0))
    started = proc.get("started")
    if started:
        try:
            from datetime import datetime as _dt
            secs = (_dt.now() - _dt.fromisoformat(started)).total_seconds()
            tk.Label(right, text=f" · {format_uptime(seconds=secs)}",
                     fg=DIM, bg=PANEL, font=(FONT, 8)).pack(side="left")
        except Exception:
            pass

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(4, 0))

    # KPI strip — 4 columns
    kpis = tk.Frame(parent, bg=PANEL)
    kpis.pack(fill="x", padx=12, pady=(10, 8))
    _kpi_col(kpis, "PnL",         _fmt_pnl(proc.get("pnl")))
    _kpi_col(kpis, "POSITIONS",   str(proc.get("positions") or 0))
    _kpi_col(kpis, "TRADES",      str(proc.get("trades") or 0))
    _kpi_col(kpis, "LAST SIGNAL", str(proc.get("last_signal") or "—")[:24])

    tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

    # Log tail
    log_header = tk.Frame(parent, bg=PANEL)
    log_header.pack(fill="x", padx=12, pady=(8, 2))
    tk.Label(log_header, text="LOG TAIL", fg=AMBER_D, bg=PANEL,
             font=(FONT, 7, "bold")).pack(side="left")
    _action_btn(log_header, "OPEN FULL", DIM,
                lambda: _open_full_log(launcher, proc))

    log_box = tk.Text(parent, height=10, bg=BG2, fg=WHITE,
                      font=(FONT, 8), wrap="none",
                      highlightbackground=BORDER, highlightthickness=1,
                      state="disabled")
    log_box.pack(fill="both", expand=True, padx=12, pady=(0, 10))
    state["log_box"] = log_box

    # Poll log tail every 1000ms
    _schedule_log_tail(state, launcher, proc)

    # Actions
    actions = tk.Frame(parent, bg=PANEL)
    actions.pack(fill="x", padx=12, pady=(0, 12))
    stop_btn = tk.Label(actions, text="  STOP ENGINE  ",
                        fg=WHITE, bg=RED,
                        font=(FONT, 10, "bold"),
                        cursor="hand2", padx=12, pady=8)
    stop_btn.pack(side="left", padx=(0, 8))
    _bind_hold_to_confirm(stop_btn,
                          on_confirm=lambda: _stop_engine(launcher, state, proc),
                          duration_ms=1500)
    _action_btn(actions, "REPORTS", DIM,
                lambda: _past_runs(launcher, slug))


def _kpi_col(parent, label, value):
    col = tk.Frame(parent, bg=PANEL)
    col.pack(side="left", fill="x", expand=True)
    tk.Label(col, text=label, fg=DIM, bg=PANEL,
             font=(FONT, 7, "bold")).pack(anchor="w")
    tk.Label(col, text=value, fg=WHITE, bg=PANEL,
             font=(FONT, 10, "bold")).pack(anchor="w")


def _fmt_pnl(v) -> str:
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)[:10]
    return f"{'+' if f >= 0 else ''}${f:,.2f}"


def _schedule_log_tail(state, launcher, proc):
    box = state.get("log_box")
    if not box or not proc:
        return
    log_path = proc.get("log") or proc.get("log_path")
    if not log_path:
        return
    try:
        from pathlib import Path as _P
        p = _P(log_path)
        if p.exists():
            lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-15:]
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("end", "\n".join(lines))
            box.configure(state="disabled")
            box.see("end")
    except Exception:
        pass
    aid = launcher.after(1000,
                         lambda: _schedule_log_tail(state, launcher, proc))
    state["after_handles"].append(aid)


def _open_full_log(launcher, proc):
    log_path = proc.get("log") or proc.get("log_path")
    if not log_path:
        return
    try:
        import os
        os.startfile(log_path)
    except Exception:
        pass


def _bind_hold_to_confirm(widget, *, on_confirm, duration_ms: int):
    """Fires on_confirm only if user holds MB1 for duration_ms."""
    tok = {"aid": None}

    def _down(_e=None):
        tok["aid"] = widget.after(duration_ms, _fire)

    def _up(_e=None):
        if tok["aid"]:
            try:
                widget.after_cancel(tok["aid"])
            except Exception:
                pass
            tok["aid"] = None

    def _fire():
        tok["aid"] = None
        on_confirm()

    widget.bind("<ButtonPress-1>", _down)
    widget.bind("<ButtonRelease-1>", _up)
    widget.bind("<Leave>", _up)


def _stop_engine(launcher, state, proc):
    try:
        from core.proc import stop_proc
        stop_proc(int(proc["pid"]), expected=proc)
    except Exception:
        return
    if "refresh" in state:
        state["refresh"]()
```

- [ ] **Step 2: Smoke test**

Start CITADEL in paper mode via the running launcher (Task 12 will wire that; for now, can test after Task 12). Manually: run `python launcher.py`, start any engine, come back to ENGINES LIVE, select it, see cockpit with KPI strip + log tail. Hold STOP for 1.5s → engine stops.

(If running launcher integration isn't ready yet, skip this smoke until Task 12 — just confirm file imports clean:)

Run: `python -c "from launcher_support import engines_live_view; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "$(cat <<'EOF'
feat(engines_live_view): detail panel — LIVE skin (cockpit)

Running engine cockpit: name + mode chip + uptime in header, 4-col
KPI strip (PnL, positions, trades, last signal), log tail polled
every 1s, hold-to-confirm STOP button (1.5s), REPORTS shortcut.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Wire `launcher._strategies_live()` to the new view + remove LIVE branch from `_strategies()`

**Files:**
- Modify: `launcher.py`

- [ ] **Step 1: Replace `_strategies_live` body**

Find in `launcher.py` (around line 8549):

```python
    def _strategies_live(self):
        """Live/demo/testnet entry point — real execution paths with safety gates."""
        self._strategies(filter_group="LIVE")
```

Replace with:

```python
    def _strategies_live(self):
        """Live/demo/testnet entry point — cockpit view with safety gates.

        Implementation lives in launcher_support.engines_live_view — this
        method only sets up the screen chrome and delegates rendering.
        """
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> ENGINES")
        market_label = MARKETS.get(_conn.active_market, {}).get("label", "UNKNOWN")
        self.h_stat.configure(text=market_label, fg=AMBER_D)
        self.f_lbl.configure(text="ESC main  |  ▲▼ select  |  ENTER run  |  M cycle mode")
        self._bind_global_nav()
        from launcher_support import engines_live_view
        # Tear down any prior cockpit state (e.g. log tail pollers)
        prior = getattr(self, "_engines_live_handle", None)
        if prior and callable(prior.get("cleanup")):
            try:
                prior["cleanup"]()
            except Exception:
                pass
        self._engines_live_handle = engines_live_view.render(
            self, self.main, on_escape=lambda: self._menu("main"),
        )
```

- [ ] **Step 2: Remove dead LIVE branch in `_strategies()`**

In the same file, locate (around line 8373):

```python
        if filter_group == "LIVE":
            # Only expose engines with a concrete live entrypoint. Most
            # backtest strategies do not accept a strategy selector when
            # routed via engines/live.py, so listing them here would launch
            # the wrong engine.
            _live_slugs = {"citadel", "live", "janestreet"}
            tracks = [t for t in tracks if t.slug in _live_slugs]
            for t in tracks:
                t.group = "LIVE"
        elif filter_group:
            tracks = [t for t in tracks if t.group == filter_group]
```

Replace with:

```python
        if filter_group:
            # LIVE view now has its own cockpit (_strategies_live) — the
            # only remaining filter_group values that hit this path are
            # "BACKTEST" and "TOOLS".
            tracks = [t for t in tracks if t.group == filter_group]
```

Also locate the `NOW PLAYING` block around line 8396:

```python
        if filter_group == "LIVE" and running_map:
            self._engines_now_playing(picker_host, tracks, running_map)
```

Remove this block entirely — it's live-only chrome.

And change the picker_mode line (around line 8399):

```python
        picker_mode = "live" if filter_group == "LIVE" else "backtest"
```

To:

```python
        picker_mode = "backtest"
```

- [ ] **Step 3: Smoke test — full launcher path**

Run: `python launcher.py`

Navigate: main → EXECUTE → ENGINES LIVE.

Expected:
- Header shows `› ENGINES` with 4 mode pills (paper highlighted first run or last-persisted).
- Master list shows 3 buckets (or 2 if nothing's running).
- Selecting CITADEL → READY skin with config + RUN button matching active mode color.
- Press `M` → mode cycles, RUN button color + text updates.
- Click a RESEARCH engine (e.g. PHI) → yellow RESEARCH ONLY badge + hazard note.
- ESC returns to main menu.

Then navigate: main → EXECUTE → BACKTEST.
Expected: old engine_picker still works as before (shows all engines by backtest group, no regression).

- [ ] **Step 4: Run tests (full suite, scoped to touched areas)**

Run: `python -m pytest tests/test_engines_live_view.py tests/test_engine_picker_contracts.py tests/test_launcher_main_menu.py tests/test_launcher_support.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add launcher.py
git commit -m "$(cat <<'EOF'
feat(launcher): wire ENGINES LIVE to new cockpit view

_strategies_live delegates to launcher_support.engines_live_view.
The LIVE filter branch of _strategies() is removed (no longer
reached from the menu). BACKTEST picker path is unchanged.

Closes the engines-live-cockpit redesign arc (spec
docs/superpowers/specs/2026-04-16-engines-live-cockpit-design.md).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Session + daily log

**Files:**
- Create: `docs/sessions/YYYY-MM-DD_HHMM.md`
- Create/update: `docs/days/YYYY-MM-DD.md`

- [ ] **Step 1: Resolve current timestamp**

Run: `date +"%Y-%m-%d_%H%M"` and `date +"%Y-%m-%d"` to get the session filename and daily log name.

- [ ] **Step 2: Write session log**

Use the template from `CLAUDE.md`. Fill in:
- Resumo: 1-3 sentences covering the cockpit redesign.
- Commits table: all commits from this session.
- Mudanças Críticas: "Nenhuma mudança em lógica de trading. Apenas UI da view ENGINES LIVE."
- Estado do Sistema: Smoke test state, tests passing count.
- Próximo passo: smoke-test each mode end-to-end with a real engine.

- [ ] **Step 3: Update daily log**

Add a row to `docs/days/YYYY-MM-DD.md` (or create) with the session link and consolidated bullets.

- [ ] **Step 4: Commit logs**

```bash
git add docs/sessions/ docs/days/
git commit -m "$(cat <<'EOF'
docs(sessions): engines-live cockpit redesign session log

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage check:**
- Shell (header/body/footer) → Task 7 ✓
- Master list 3 buckets → Task 8 ✓
- Detail panel LIVE skin → Task 11 ✓
- Detail panel READY skin → Task 10 ✓
- Detail panel RESEARCH skin → Task 9 ✓
- Mode state + cycle + persistence → Task 4 ✓
- LIVE confirmation modal → Task 10 ✓
- Mode color aliases → Task 2 ✓
- `live_ready` registry flag → Task 1 ✓
- Wire launcher → Task 12 ✓
- Running engines discovery → Task 6 ✓
- Uptime formatting → Task 5 ✓

**Placeholder scan:** No TBDs / TODOs / "similar to". Every code step has full code.

**Type consistency:**
- `Mode` literal used consistently (`_MODE_ORDER`, `_MODE_COLORS`, `cycle_mode`, `load_mode`, `save_mode`).
- `Bucket` literal used in `assign_bucket` and state["selected_bucket"].
- `state` is a plain `dict` throughout — documented in `render()`.
- `live_confirm_ok` signature matches usage in `_confirm_live_modal`.
- Module helpers (`_render_bucket`, `_render_row_*`, `_render_detail_*`) all take `state` as their shared side-channel.
