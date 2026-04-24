# Arbitrage Hub v2 — Density & Type Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize the Arbitrage Hub into an 8-tab type matrix (CEX-CEX / DEX-DEX / CEX-DEX / PERP-PERP / SPOT-SPOT / BASIS / POSITIONS / HISTORY) with three new execution-oriented columns (PROFIT$/$1k 24h, LIFETIME, DEPTH$1k) and three new filter chips (PROFIT$ ≥, LIFE ≥, VENUES allowlist).

**Architecture:** All predicate / sort / compaction / lifetime logic lives in two new pure modules under `core/arb/` (Tk-free, unit-testable). The hub screen module (`launcher_support/screens/arbitrage_hub.py`) consumes them and keeps the Tk layer thin. `core/arb/arb_scoring.py` is extended — not rewritten — to add two new fields to `ScoreResult` so the simulator and cache semantics stay intact. CORE trading modules (`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`) are untouched.

**Tech Stack:** Python 3.14, Tkinter (launcher GUI), pytest, dataclasses. No new dependencies.

**Source spec:** `docs/superpowers/specs/2026-04-22-arbitrage-hub-v2-density-design.md` (approved brainstorm).

**Branch strategy:** Run in a dedicated worktree off `main` (recommended) via `git worktree add .worktrees/arb-hub-v2 -b feat/arb-hub-v2 main`. The current branch `feat/research-desk` has unrelated ongoing work — keep it separate.

**CORE protection audit (must pass at the end):**
```bash
git diff main...HEAD -- core/indicators.py core/signals.py core/portfolio.py config/params.py
# expected: empty
```

---

## File Structure

**New files (pure logic, fully unit-testable):**
- `core/arb/tab_matrix.py` — venue classifier, predicate dispatcher, sort comparator, compact-label helper.
- `core/arb/lifetime.py` — stable key hashing, `LifetimeTracker` class, `fmt_duration` helper.
- `tests/core/test_tab_matrix.py` — unit tests for predicate/sort/compact.
- `tests/core/test_lifetime.py` — unit tests for tracker + formatter.
- `tests/launcher/test_arb_hub_v2.py` — integration smoke for tab counter + filter wiring.

**Modified files:**
- `core/arb/arb_scoring.py` — extend `ScoreResult` + `score_opp` with two new fields (additive only, no rename).
- `tests/core/test_arb_scoring.py` — new cases for new fields.
- `launcher.py` — rewrite `_ARB_TAB_DEFS` (3→8), extend `_ARB_LEGACY_TAB_MAP`, extend `_ARB_FILTER_DEFAULTS`, update `_ARB_OPPS_COLS`, add `_ARB_LIFETIME_TRACKER` attribute.
- `launcher_support/screens/arbitrage_hub.py` — 8-tab strip with category separator + auto-compact, generic `render_tab_filtered` consuming predicates, new 8-column painter, extended `build_viab_toolbar` with 3 new chips + popovers, extended `filter_and_score` consuming new filter keys, `hub_telem_update` counter + lifetime wiring.

**Untouched:** Detail pane / simulator (`show_detail`), status strip, auto-refresh loop, positions/history tabs, `SimpleArbEngine`, `config/params.py`.

---

## Task Summary

| # | Task | Scope | Tests |
|---|------|-------|-------|
| 1 | Venue classifier (`is_cex`) | `core/arb/tab_matrix.py` | test_tab_matrix |
| 2 | Tab predicate dispatcher (`matches_type`) | tab_matrix.py | test_tab_matrix |
| 3 | Sort comparator + compact-label helper | tab_matrix.py | test_tab_matrix |
| 4 | Lifetime tracker + formatter | `core/arb/lifetime.py` | test_lifetime |
| 5 | `score_opp` gains `profit_usd_per_1k_24h` + `depth_pct_at_1k` | `core/arb/arb_scoring.py` | test_arb_scoring |
| 6 | `_ARB_TAB_DEFS` 8 entries + legacy map + filter defaults | `launcher.py` | — |
| 7 | 8-tab strip render + category separator + auto-compact | `arbitrage_hub.py::render` | test_arb_hub_v2 |
| 8 | Generic `render_tab_filtered` + `render_map` dispatch | arbitrage_hub.py | test_arb_hub_v2 |
| 9 | 8-column `paint_opps` (drop SCORE, add PROFIT$/LIFE/DEPTH) | arbitrage_hub.py | test_arb_hub_v2 |
| 10 | 3 new filter chips + popovers in `build_viab_toolbar` | arbitrage_hub.py | test_arb_hub_v2 |
| 11 | Counter `(N)` update + lifetime wiring in `hub_telem_update` | arbitrage_hub.py | test_arb_hub_v2 |
| 12 | Integration smoke + acceptance audit + final commit | — | smoke_test |

---

## Task 1: Venue classifier (`is_cex`)

**Files:**
- Create: `core/arb/tab_matrix.py`
- Test: `tests/core/test_tab_matrix.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_tab_matrix.py`:

```python
"""Unit tests for core/arb/tab_matrix.py — venue/predicate/sort helpers.
TDD: tests written before implementation.
"""
import pytest

from core.arb.tab_matrix import CEX_VENUES, is_cex


def test_is_cex_known_cex_venues():
    for v in ["binance", "bybit", "okx", "kucoin", "gate", "bitget", "bingx"]:
        assert is_cex(v) is True, f"{v!r} should be classified CEX"


def test_is_cex_dex_venues():
    for v in ["hyperliquid", "dydx", "paradex", "vertex"]:
        assert is_cex(v) is False, f"{v!r} should be classified DEX"


def test_is_cex_case_insensitive():
    assert is_cex("BINANCE") is True
    assert is_cex("HyperLiquid") is False


def test_is_cex_unknown_treated_as_dex():
    assert is_cex("random_venue") is False
    assert is_cex("") is False
    assert is_cex(None) is False


def test_cex_venues_is_frozenset():
    assert isinstance(CEX_VENUES, frozenset)
    assert "binance" in CEX_VENUES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_tab_matrix.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.arb.tab_matrix'`

- [ ] **Step 3: Create the module with minimal implementation**

Create `core/arb/tab_matrix.py`:

```python
"""core/arb/tab_matrix.py
AURUM Finance — type-matrix helpers for the Arbitrage Hub v2.

Pure module: no Tk, no I/O. Provides venue classification, tab predicate
dispatching, sort comparator, and label compaction logic consumed by
launcher_support.screens.arbitrage_hub.

CEX venue allowlist is hardcoded and derived from
core.arb.arb_scoring._DEFAULT_VENUE_RELIABILITY. Anything not on the list
is treated as DEX.
"""
from __future__ import annotations


# Centralized CEX allowlist. Everything else (hyperliquid, dydx, paradex,
# vertex, etc.) falls through to DEX. Keep lowercase.
CEX_VENUES: frozenset[str] = frozenset({
    "binance",
    "bybit",
    "okx",
    "kucoin",
    "gate",
    "bitget",
    "bingx",
    "mexc",
    "htx",
    "coinbase",
})


def is_cex(venue: str | None) -> bool:
    """True if ``venue`` is a known centralized exchange.

    Case-insensitive. None / empty / unknown → False (treated as DEX).
    """
    if not venue:
        return False
    return str(venue).lower() in CEX_VENUES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_tab_matrix.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/arb/tab_matrix.py tests/core/test_tab_matrix.py
git commit -m "feat(arb): add tab_matrix venue classifier"
```

---

## Task 2: Tab predicate dispatcher (`matches_type`)

**Files:**
- Modify: `core/arb/tab_matrix.py` (append)
- Test: `tests/core/test_tab_matrix.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_tab_matrix.py`:

```python
from core.arb.tab_matrix import matches_type, pair_kinds, pair_venues


# ─── pair_kinds / pair_venues helpers ────────────────────────────────

def test_pair_kinds_from_type_cc():
    # _type "CC"/"DD"/"CD" all mean funding (perp-perp)
    assert pair_kinds({"_type": "CC"}) == ("perp", "perp")
    assert pair_kinds({"_type": "DD"}) == ("perp", "perp")
    assert pair_kinds({"_type": "CD"}) == ("perp", "perp")


def test_pair_kinds_from_type_basis():
    assert pair_kinds({"_type": "BS"}) == ("perp", "spot")


def test_pair_kinds_from_type_spot():
    assert pair_kinds({"_type": "SP"}) == ("spot", "spot")


def test_pair_kinds_missing_type_returns_unknown():
    assert pair_kinds({}) == (None, None)
    assert pair_kinds({"_type": "XX"}) == (None, None)


def test_pair_venues_short_long():
    p = {"short_venue": "binance", "long_venue": "bybit"}
    assert pair_venues(p) == ("binance", "bybit")


def test_pair_venues_basis():
    # basis has venue_perp/venue_spot
    p = {"venue_perp": "binance", "venue_spot": "coinbase"}
    assert pair_venues(p) == ("binance", "coinbase")


def test_pair_venues_spot():
    p = {"venue_a": "binance", "venue_b": "okx"}
    assert pair_venues(p) == ("binance", "okx")


def test_pair_venues_missing():
    assert pair_venues({}) == ("", "")


# ─── matches_type predicate dispatch ────────────────────────────────

def _p(**kw):
    base = {"_type": "CC", "short_venue": "binance", "long_venue": "bybit"}
    base.update(kw)
    return base


def test_matches_cex_cex():
    assert matches_type(_p(short_venue="binance", long_venue="bybit"), "cex-cex") is True
    assert matches_type(_p(short_venue="binance", long_venue="hyperliquid"), "cex-cex") is False


def test_matches_dex_dex():
    assert matches_type(
        _p(_type="DD", short_venue="hyperliquid", long_venue="dydx"),
        "dex-dex",
    ) is True
    assert matches_type(
        _p(short_venue="binance", long_venue="bybit"),
        "dex-dex",
    ) is False


def test_matches_cex_dex():
    assert matches_type(
        _p(_type="CD", short_venue="binance", long_venue="hyperliquid"),
        "cex-dex",
    ) is True
    # Both CEX → not CEX-DEX
    assert matches_type(
        _p(short_venue="binance", long_venue="bybit"),
        "cex-dex",
    ) is False


def test_matches_perp_perp():
    assert matches_type(_p(_type="CC"), "perp-perp") is True
    assert matches_type(_p(_type="BS"), "perp-perp") is False


def test_matches_spot_spot():
    assert matches_type(_p(_type="SP"), "spot-spot") is True
    assert matches_type(_p(_type="CC"), "spot-spot") is False


def test_matches_basis():
    assert matches_type(_p(_type="BS"), "basis") is True
    assert matches_type(_p(_type="CC"), "basis") is False


def test_matches_meta_tabs_always_false():
    # POSITIONS and HISTORY are meta tabs — predicate never matches an opp.
    assert matches_type(_p(), "positions") is False
    assert matches_type(_p(), "history") is False


def test_matches_unknown_kind_returns_false():
    # Missing _type → predicates that depend on kind return False
    assert matches_type({"short_venue": "binance", "long_venue": "bybit"},
                        "perp-perp") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_tab_matrix.py -v -k "pair_kinds or pair_venues or matches_"`
Expected: FAIL with `ImportError: cannot import name 'matches_type'`.

- [ ] **Step 3: Append implementation**

Append to `core/arb/tab_matrix.py`:

```python
# ─── Pair introspection helpers ─────────────────────────────────────

# _type tag written by _arb_paint_opps when merging sources:
#   CC/DD/CD → both legs perp (funding diff)
#   BS       → perp ↔ spot (basis trade)
#   SP       → both legs spot (spot arb)
_TYPE_TO_KINDS: dict[str, tuple[str, str]] = {
    "CC": ("perp", "perp"),
    "DD": ("perp", "perp"),
    "CD": ("perp", "perp"),
    "BS": ("perp", "spot"),
    "SP": ("spot", "spot"),
}


def pair_kinds(pair: dict) -> tuple[str | None, str | None]:
    """Return (kind_a, kind_b) for a pair record, or (None, None) if unknown."""
    t = pair.get("_type")
    if t in _TYPE_TO_KINDS:
        return _TYPE_TO_KINDS[t]
    return (None, None)


def pair_venues(pair: dict) -> tuple[str, str]:
    """Return (venue_a, venue_b) normalized from whichever fields exist.

    Preference order: short/long_venue → venue_perp/venue_spot → venue_a/venue_b.
    Missing fields return empty strings.
    """
    a = (pair.get("short_venue")
         or pair.get("venue_perp")
         or pair.get("venue_a")
         or "")
    b = (pair.get("long_venue")
         or pair.get("venue_spot")
         or pair.get("venue_b")
         or "")
    return (str(a), str(b))


# ─── Tab predicate dispatch ─────────────────────────────────────────

# Known opps tab ids emitted by the hub UI.
_TYPE_TAB_IDS: frozenset[str] = frozenset({
    "cex-cex", "dex-dex", "cex-dex",
    "perp-perp", "spot-spot", "basis",
})


def matches_type(pair: dict, tab_id: str) -> bool:
    """True if ``pair`` belongs in the given tab.

    Meta tabs ("positions", "history") always return False — they read
    from the engine, not from the scanner's opp stream.
    """
    if tab_id not in _TYPE_TAB_IDS:
        return False

    venue_a, venue_b = pair_venues(pair)
    kind_a, kind_b = pair_kinds(pair)

    if tab_id == "cex-cex":
        return is_cex(venue_a) and is_cex(venue_b)
    if tab_id == "dex-dex":
        return (not is_cex(venue_a)) and (not is_cex(venue_b)) \
               and bool(venue_a) and bool(venue_b)
    if tab_id == "cex-dex":
        return is_cex(venue_a) != is_cex(venue_b)
    if tab_id == "perp-perp":
        return kind_a == "perp" and kind_b == "perp"
    if tab_id == "spot-spot":
        return kind_a == "spot" and kind_b == "spot"
    if tab_id == "basis":
        # Basis opps are already same-symbol-two-instruments by
        # construction (one perp leg + one spot leg). Kind asymmetry
        # is the only meaningful signal.
        return (kind_a is not None and kind_b is not None
                and kind_a != kind_b)

    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_tab_matrix.py -v`
Expected: all tests PASS (5 from Task 1 + ~15 new).

- [ ] **Step 5: Commit**

```bash
git add core/arb/tab_matrix.py tests/core/test_tab_matrix.py
git commit -m "feat(arb): tab predicate dispatcher by venue/kind"
```

---

## Task 3: Sort comparator + compact-label helper

**Files:**
- Modify: `core/arb/tab_matrix.py` (append)
- Test: `tests/core/test_tab_matrix.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_tab_matrix.py`:

```python
from types import SimpleNamespace

from core.arb.tab_matrix import compact_labels, opps_sort_key


# ─── opps_sort_key ──────────────────────────────────────────────────

def _sr(grade="GO", bkevn=10.0, profit=5.0, score=80.0):
    return SimpleNamespace(
        grade=grade, viab=grade, breakeven_h=bkevn,
        profit_usd_per_1k_24h=profit, score=score,
    )


def test_sort_go_before_wait_before_skip():
    opps = [
        ({"id": 1}, _sr(grade="SKIP")),
        ({"id": 2}, _sr(grade="GO")),
        ({"id": 3}, _sr(grade="MAYBE")),
    ]
    opps.sort(key=opps_sort_key)
    assert [o["id"] for o, _ in opps] == [2, 3, 1]


def test_sort_bkevn_ascending_within_grade():
    opps = [
        ({"id": 1}, _sr(grade="GO", bkevn=50.0)),
        ({"id": 2}, _sr(grade="GO", bkevn=5.0)),
        ({"id": 3}, _sr(grade="GO", bkevn=20.0)),
    ]
    opps.sort(key=opps_sort_key)
    assert [o["id"] for o, _ in opps] == [2, 3, 1]


def test_sort_profit_descending_as_tiebreaker():
    opps = [
        ({"id": 1}, _sr(grade="GO", bkevn=10.0, profit=1.0)),
        ({"id": 2}, _sr(grade="GO", bkevn=10.0, profit=7.0)),
        ({"id": 3}, _sr(grade="GO", bkevn=10.0, profit=3.0)),
    ]
    opps.sort(key=opps_sort_key)
    assert [o["id"] for o, _ in opps] == [2, 3, 1]


def test_sort_handles_none_bkevn_and_profit():
    opps = [
        ({"id": 1}, _sr(grade="GO", bkevn=None, profit=None)),
        ({"id": 2}, _sr(grade="GO", bkevn=5.0, profit=2.0)),
    ]
    opps.sort(key=opps_sort_key)
    # id 2 beats id 1: has bkevn
    assert opps[0][0]["id"] == 2


# ─── compact_labels ────────────────────────────────────────────────

_FULL_LABELS = [
    ("1", "cex-cex",   "1 CEX-CEX",   ("1 CC", "CEX-CEX")),
    ("2", "dex-dex",   "1 DEX-DEX",   ("2 DD", "DEX-DEX")),
    ("3", "cex-dex",   "1 CEX-DEX",   ("3 CD", "CEX-DEX")),
    ("4", "perp-perp", "4 PERP-PERP", ("4 PP", "PERP-PERP")),
    ("5", "spot-spot", "5 SPOT-SPOT", ("5 SS", "SPOT-SPOT")),
    ("6", "basis",     "6 BASIS",     ("6 BAS", "BASIS")),
    ("7", "positions", "7 POS",       ("7 POS", "POSITIONS")),
    ("8", "history",   "8 HIST",      ("8 HIS", "HISTORY")),
]


def test_compact_labels_level_0_full():
    # Level 0 = full, with counters
    counts = {tid: 5 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=0)
    assert out[0][2] == "1 CEX-CEX (5)"
    assert out[6][2] == "7 POS (5)"


def test_compact_labels_level_1_drops_counters():
    counts = {tid: 5 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=1)
    assert out[0][2] == "1 CEX-CEX"
    assert "(" not in out[0][2]


def test_compact_labels_level_2_slash():
    counts = {tid: 0 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=2)
    assert out[0][2] == "1 CEX/CEX"
    assert out[3][2] == "4 PERP/PERP"


def test_compact_labels_level_3_abbrev():
    counts = {tid: 0 for _, tid, _, _ in _FULL_LABELS}
    out = compact_labels(_FULL_LABELS, counts=counts, level=3)
    assert out[0][2] == "1 CC"
    assert out[5][2] == "6 BAS"
    assert out[6][2] == "7 POS"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_tab_matrix.py -v -k "sort or compact"`
Expected: FAIL with `ImportError: cannot import name 'opps_sort_key'`.

- [ ] **Step 3: Append implementation**

Append to `core/arb/tab_matrix.py`:

```python
# ─── Sort comparator ────────────────────────────────────────────────

_GRADE_RANK: dict[str, int] = {"GO": 0, "MAYBE": 1, "WAIT": 1, "SKIP": 2}


def opps_sort_key(entry: tuple[dict, object]) -> tuple[int, float, float]:
    """Sort key: (grade asc, bkevn asc, -profit_usd_per_1k_24h).

    ``entry`` is a ``(pair_dict, ScoreResult)`` tuple as produced by
    ``_arb_filter_and_score``. GO rows sort first; ties broken by
    shortest breakeven, then by highest 24h profit per $1k.

    Missing bkevn/profit fall to worst (9999 / 0) so they sort last
    within their grade bucket.
    """
    _pair, sr = entry
    grade = getattr(sr, "grade", "SKIP")
    rank = _GRADE_RANK.get(grade, 2)

    bkevn = getattr(sr, "breakeven_h", None)
    be = float(bkevn) if bkevn is not None else 9999.0

    profit = getattr(sr, "profit_usd_per_1k_24h", None)
    pf = float(profit) if profit is not None else 0.0

    return (rank, be, -pf)


# ─── Label compaction ───────────────────────────────────────────────

# Abbreviation map used at compaction level 3.
_ABBREV: dict[str, str] = {
    "cex-cex":   "CC",
    "dex-dex":   "DD",
    "cex-dex":   "CD",
    "perp-perp": "PP",
    "spot-spot": "SS",
    "basis":     "BAS",
    "positions": "POS",
    "history":   "HIS",
}


def compact_labels(
    tab_defs: list[tuple[str, str, str, str]],
    *,
    counts: dict[str, int],
    level: int,
) -> list[tuple[str, str, str, str]]:
    """Produce display labels for the tab strip at a given compaction level.

    Args:
        tab_defs: list of (key, tab_id, label_full, color) tuples.
        counts:   per-tab opp count (after filters) keyed by tab_id.
        level:    0=full with counters, 1=drop counters, 2=slash, 3=abbrev.

    Returns:
        New list of (key, tab_id, display_label, color) tuples. Input
        tuples are not mutated.
    """
    out: list[tuple[str, str, str, str]] = []
    for key, tid, label_full, color in tab_defs:
        if level == 0:
            n = counts.get(tid, 0)
            display = f"{label_full} ({n})"
        elif level == 1:
            display = label_full
        elif level == 2:
            display = label_full.replace("-", "/")
        elif level == 3:
            abbrev = _ABBREV.get(tid, tid.upper()[:3])
            display = f"{key} {abbrev}"
        else:
            display = label_full
        out.append((key, tid, display, color))
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_tab_matrix.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/arb/tab_matrix.py tests/core/test_tab_matrix.py
git commit -m "feat(arb): sort comparator + compact label helper"
```

---

## Task 4: Lifetime tracker + formatter

**Files:**
- Create: `core/arb/lifetime.py`
- Test: `tests/core/test_lifetime.py`

- [ ] **Step 1: Write the failing test**

Create `tests/core/test_lifetime.py`:

```python
"""Unit tests for core/arb/lifetime.py."""
import pytest

from core.arb.lifetime import LifetimeTracker, fmt_duration, stable_key


def _pair(**kw):
    base = {"symbol": "BTC", "short_venue": "binance", "long_venue": "bybit",
            "_type": "CC"}
    base.update(kw)
    return base


# ─── stable_key ────────────────────────────────────────────────────

def test_stable_key_identical_pairs_match():
    a = _pair()
    b = _pair()
    assert stable_key(a) == stable_key(b)


def test_stable_key_differs_on_symbol():
    assert stable_key(_pair()) != stable_key(_pair(symbol="ETH"))


def test_stable_key_differs_on_venue():
    a = stable_key(_pair(short_venue="binance"))
    b = stable_key(_pair(short_venue="okx"))
    assert a != b


def test_stable_key_differs_on_type():
    a = stable_key(_pair(_type="CC"))
    b = stable_key(_pair(_type="CD"))
    assert a != b


def test_stable_key_case_insensitive_venue():
    a = stable_key(_pair(short_venue="Binance"))
    b = stable_key(_pair(short_venue="binance"))
    assert a == b


# ─── fmt_duration ──────────────────────────────────────────────────

def test_fmt_duration_under_minute():
    assert fmt_duration(30) == "0m"
    assert fmt_duration(59) == "0m"


def test_fmt_duration_exact_minutes():
    assert fmt_duration(60) == "1m"
    assert fmt_duration(90) == "1m"  # truncate to minutes <60
    assert fmt_duration(59 * 60) == "59m"


def test_fmt_duration_hours_minutes():
    assert fmt_duration(3600) == "1h0m"
    assert fmt_duration(3600 + 30 * 60) == "1h30m"
    assert fmt_duration(4 * 3600 + 15 * 60) == "4h15m"


def test_fmt_duration_negative_returns_zero():
    assert fmt_duration(-5) == "0m"


# ─── LifetimeTracker ───────────────────────────────────────────────

def test_tracker_records_first_seen():
    t = LifetimeTracker()
    key = "abc"
    t.observe(key, now=100.0)
    assert t.age(key, now=160.0) == 60.0


def test_tracker_idempotent_observe():
    t = LifetimeTracker()
    t.observe("x", now=100.0)
    t.observe("x", now=200.0)  # later observation must NOT reset
    assert t.age("x", now=300.0) == 200.0


def test_tracker_unknown_key_returns_none():
    t = LifetimeTracker()
    assert t.age("nope", now=100.0) is None


def test_tracker_observe_from_pairs_bulk():
    t = LifetimeTracker()
    pairs = [_pair(symbol="BTC"), _pair(symbol="ETH")]
    t.observe_pairs(pairs, now=100.0)
    assert t.age(stable_key(pairs[0]), now=160.0) == 60.0
    assert t.age(stable_key(pairs[1]), now=160.0) == 60.0


def test_tracker_cleanup_drops_stale():
    t = LifetimeTracker()
    t.observe("recent", now=100.0)
    t.observe("stale",  now=10.0)
    t.cleanup(now=1000.0, max_age=500.0)
    assert t.age("recent", now=1000.0) is not None
    assert t.age("stale",  now=1000.0) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_lifetime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.arb.lifetime'`.

- [ ] **Step 3: Create the module**

Create `core/arb/lifetime.py`:

```python
"""core/arb/lifetime.py
AURUM Finance — lifetime / persistence tracking for arb opps.

Tracks when each (symbol, legs, kinds) tuple was first seen in the scanner
stream so the hub can render a LIFE column (older = more reliable, less
likely to be a transient blip).

Pure module: no Tk, no I/O, no imports from core.arb.* besides the pair
structure convention. In-memory only — state resets on launcher restart.
"""
from __future__ import annotations

import hashlib


def stable_key(pair: dict) -> str:
    """Hash a pair record to a stable identifier across scans.

    Key components: symbol + (venue_a, venue_b) + (_type). Venues are
    lowercased so case differences don't fork the key.
    """
    symbol = str(pair.get("symbol", "")).upper()
    va = str(
        pair.get("short_venue") or pair.get("venue_perp") or pair.get("venue_a") or ""
    ).lower()
    vb = str(
        pair.get("long_venue") or pair.get("venue_spot") or pair.get("venue_b") or ""
    ).lower()
    t = str(pair.get("_type", ""))
    payload = f"{symbol}|{va}|{vb}|{t}".encode()
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


def fmt_duration(seconds: float) -> str:
    """Format a duration as ``Nm`` (<60min) or ``NhMm`` (≥60min).

    Negative/zero → ``0m``. Truncates (does not round).
    """
    s = int(max(0, seconds))
    if s < 3600:
        return f"{s // 60}m"
    h = s // 3600
    m = (s % 3600) // 60
    return f"{h}h{m}m"


class LifetimeTracker:
    """First-seen timestamps for arb-pair keys.

    Use ``observe_pairs(pairs, now)`` each scan tick. Query with
    ``age(key, now)``. Periodically call ``cleanup(now, max_age)`` so
    disappeared pairs don't bloat memory.
    """

    def __init__(self) -> None:
        self._first_seen: dict[str, float] = {}

    def observe(self, key: str, now: float) -> None:
        """Record first-seen time. Idempotent: later observes do not reset."""
        if key not in self._first_seen:
            self._first_seen[key] = float(now)

    def observe_pairs(self, pairs, now: float) -> None:
        """Bulk observe from an iterable of pair records."""
        for p in pairs or []:
            self.observe(stable_key(p), now)

    def age(self, key: str, now: float) -> float | None:
        """Seconds since first-seen, or None if never observed."""
        first = self._first_seen.get(key)
        if first is None:
            return None
        return float(now) - first

    def cleanup(self, now: float, max_age: float) -> None:
        """Drop entries older than ``max_age`` seconds to cap memory."""
        cutoff = float(now) - float(max_age)
        stale = [k for k, t in self._first_seen.items() if t < cutoff]
        for k in stale:
            del self._first_seen[k]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_lifetime.py -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add core/arb/lifetime.py tests/core/test_lifetime.py
git commit -m "feat(arb): lifetime tracker with blake2b stable key"
```

---

## Task 5: Extend `score_opp` with `profit_usd_per_1k_24h` + `depth_pct_at_1k`

**Files:**
- Modify: `core/arb/arb_scoring.py:285-331`
- Test: `tests/core/test_arb_scoring.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/core/test_arb_scoring.py`:

```python
# ─── New v2 fields: profit_usd_per_1k_24h + depth_pct_at_1k ──────────

def test_score_result_has_profit_field():
    res = score_opp(_make_pair())
    assert hasattr(res, "profit_usd_per_1k_24h")
    assert hasattr(res, "depth_pct_at_1k")


def test_profit_usd_per_1k_24h_formula():
    """profit = apr/100 * $1000 * 24/8760 - $3 (30bps fees_rt on $1k)."""
    # apr=60%  →  0.6 * 1000 * 24/8760 = 1.6438; fees_rt = 3  →  net ≈ -1.356
    res = score_opp(_make_pair(net_apr=60.0))
    expected = 0.60 * 1000.0 * (24.0 / 8760.0) - 3.0
    assert res.profit_usd_per_1k_24h == pytest.approx(expected, rel=1e-3)


def test_profit_high_apr_positive():
    # 300% APR → gross = 8.22/day, minus $3 fees = ~$5.22 net
    res = score_opp(_make_pair(net_apr=300.0))
    assert res.profit_usd_per_1k_24h is not None
    assert res.profit_usd_per_1k_24h > 0


def test_profit_none_when_apr_missing():
    res = score_opp({"symbol": "X"})
    assert res.profit_usd_per_1k_24h is None


def test_depth_pct_none_when_book_depth_missing():
    res = score_opp(_make_pair())
    # No book_depth field in the _make_pair fixture → None.
    assert res.depth_pct_at_1k is None


def test_depth_pct_computed_from_book_depth():
    # If book_depth_usd is present, return slippage-in-bps estimate.
    # Simple linear model: bps = 10_000 / (book_depth_usd / 1000)
    # book=$50k → 10_000/50 = 200 bps
    pair = _make_pair(book_depth_usd=50_000.0)
    res = score_opp(pair)
    assert res.depth_pct_at_1k == pytest.approx(200.0, rel=1e-3)


def test_depth_pct_deep_book_low_slippage():
    pair = _make_pair(book_depth_usd=10_000_000.0)
    res = score_opp(pair)
    # 10_000 / 10_000 = 1.0 bps
    assert res.depth_pct_at_1k == pytest.approx(1.0, rel=1e-3)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/core/test_arb_scoring.py -v -k "profit or depth"`
Expected: FAIL — `AttributeError: 'ScoreResult' object has no attribute 'profit_usd_per_1k_24h'`.

- [ ] **Step 3: Extend ScoreResult and score_opp**

In `core/arb/arb_scoring.py`, modify the `ScoreResult` dataclass (lines 285-292) — add two fields:

```python
@dataclass
class ScoreResult:
    """Result of scoring a single opportunity."""
    score:   float          # 0-100
    grade:   str            # GO / MAYBE / SKIP (legacy)
    viab:    str = "SKIP"   # GO / WAIT / SKIP (new — viability flag)
    breakeven_h: float | None = None
    # v2 density columns (2026-04-23):
    profit_usd_per_1k_24h: float | None = None  # net $ on $1k over 24h, fees_rt = _DEFAULT_RT_FEE_BPS
    depth_pct_at_1k: float | None = None        # slippage bps for $1k notional, from book_depth_usd
    factors: dict = field(default_factory=dict)  # per-factor raw scores (0-100 or None)
```

Above `score_opp` (around line 294, after `_viab` definition), add two helpers:

```python
# v2 density helpers --------------------------------------------------

def _profit_usd_per_1k_24h(opp: dict, rt_fee_bps: float = _DEFAULT_RT_FEE_BPS) -> float | None:
    """Net 24h profit on a $1,000 notional, after round-trip fees.

    gross = apr/100 * $1000 * 24/8760
    fees_rt_usd = rt_fee_bps/10_000 * $1000  (= $3 at 30 bps default)
    net = gross - fees_rt_usd

    Returns None if APR is missing. Can be negative (signals the edge
    doesn't cover fees at this size).
    """
    apr = opp.get("net_apr") or opp.get("apr") or opp.get("basis_apr")
    if apr is None:
        return None
    gross = abs(float(apr)) / 100.0 * 1000.0 * (24.0 / 8760.0)
    fees_usd = rt_fee_bps / 10_000.0 * 1000.0
    return round(gross - fees_usd, 4)


def _depth_pct_at_1k(opp: dict) -> float | None:
    """Slippage bps for a $1,000 notional against the shallowest leg book.

    Expects ``book_depth_usd`` (min of both legs) in the pair record.
    Returns None if absent — the UI shows ``—`` and the DEPTH column
    stays empty until the scanner enriches records.

    Linear model: bps = 10_000 / (book_depth_usd / 1_000). A book of
    $1k matches 100% slippage (10_000 bps); $50k → 200 bps; $10M → 1 bps.
    """
    depth = opp.get("book_depth_usd")
    if depth is None:
        return None
    try:
        d = float(depth)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    return round(10_000.0 / (d / 1000.0), 4)
```

Then inside `score_opp`, after the existing `be = _breakeven_hours(opp)` line, add:

```python
    profit = _profit_usd_per_1k_24h(opp)
    depth = _depth_pct_at_1k(opp)
```

And pass them into `ScoreResult(...)`:

```python
    return ScoreResult(
        score=round(score, 2),
        grade=grade,
        viab=viab,
        breakeven_h=be,
        profit_usd_per_1k_24h=profit,
        depth_pct_at_1k=depth,
        factors=factor_scores,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/core/test_arb_scoring.py -v`
Expected: all tests PASS (existing + 7 new).

Also run: `pytest tests/contracts/test_arb_scoring_contracts.py -v`
Expected: PASS. Adding fields to a dataclass is additive and should not break existing assertions. If the contract test explicitly enumerates `ScoreResult.__dataclass_fields__` keys (a closed shape check) it will fail — in that case, extend the contract's expected-field set to include `profit_usd_per_1k_24h` and `depth_pct_at_1k` in the same commit.

- [ ] **Step 5: Commit**

```bash
git add core/arb/arb_scoring.py tests/core/test_arb_scoring.py
git commit -m "feat(arb-scoring): profit/depth fields for density view"
```

---

## Task 6: `_ARB_TAB_DEFS` 8 entries + legacy map + filter defaults

**Files:**
- Modify: `launcher.py:4229-4290`

- [ ] **Step 1: Read the current definitions**

Run: `grep -n "_ARB_TAB_DEFS\|_ARB_LEGACY_TAB_MAP\|_ARB_FILTER_DEFAULTS\|_ARB_OPPS_COLS\|_ARB_LIFETIME" launcher.py | head -30`
Expected: locate the current 3-tab `_ARB_TAB_DEFS` at line 4229.

- [ ] **Step 2: Replace `_ARB_TAB_DEFS` with 8-tab layout**

In `launcher.py`, replace lines 4229-4242 with:

```python
    _ARB_TAB_DEFS = [
        # (key, tab_id, label_full, color)
        # Type tabs (category="type") — filtered views over the same unified
        # opp set emitted by the scanner. Overlap is expected and documented
        # (ex. binance-perp↔bybit-perp BTC appears in both CEX-CEX and PERP-PERP).
        ("1", "cex-cex",   "1 CEX-CEX",   "#ffd700"),
        ("2", "dex-dex",   "2 DEX-DEX",   "#8ae6a2"),
        ("3", "cex-dex",   "3 CEX-DEX",   "#c084fc"),
        ("4", "perp-perp", "4 PERP-PERP", "#60a5fa"),
        ("5", "spot-spot", "5 SPOT-SPOT", "#fb923c"),
        ("6", "basis",     "6 BASIS",     "#f472b6"),
        # Meta tabs (category="meta") — render from SimpleArbEngine, not
        # the scanner. Separator `|` is inserted between 6 and 7 by the
        # render function.
        ("7", "positions", "7 POSITIONS", "#00ff80"),
        ("8", "history",   "8 HISTORY",   "#c084fc"),
    ]

    # Which tab_ids are "type" (scanner-driven) vs. "meta" (engine-driven).
    # Used by render to place the category separator before POS/HIST.
    _ARB_TAB_CATEGORIES = {
        "cex-cex": "type", "dex-dex": "type", "cex-dex": "type",
        "perp-perp": "type", "spot-spot": "type", "basis": "type",
        "positions": "meta", "history": "meta",
    }

    # Legacy tab ids from Phase 1 + the v1 extraction kept for backward-compat
    # (external callers may still pass "opps" / "cex-cex" / "engine"). v2
    # gives them real predicates again — "opps" maps to CEX-CEX (the default
    # first tab); "engine" stays POSITIONS.
    _ARB_LEGACY_TAB_MAP = {
        "opps": "cex-cex",
        "engine": "positions",
    }
```

- [ ] **Step 3: Extend `_ARB_FILTER_DEFAULTS`**

Replace the `_ARB_FILTER_DEFAULTS` dict (at line 4274 in the original file) with:

```python
    _ARB_FILTER_DEFAULTS = {
        "min_apr": 5.0, "min_volume": 0, "min_oi": 0,
        "risk_max": "HIGH", "grade_min": "MAYBE",
        "exclude_risky_venues": False,
        "realistic_only": True,
        # v2 density filters (2026-04-23) — defaults = off
        "profit_min_usd": 0.0,         # cut opps with net <$X per $1k per 24h
        "life_min_seconds": 0,         # require pair seen for ≥X seconds
        "venues_allow": None,          # None = all venues OK; list = allowlist
    }
```

- [ ] **Step 4: Update `_ARB_OPPS_COLS` (8 columns, drop SCORE)**

Find the current `_ARB_OPPS_COLS` definition in `launcher.py` (grep first):

```bash
grep -n "_ARB_OPPS_COLS" launcher.py
```

Replace its value with the v2 8-column layout:

```python
    _ARB_OPPS_COLS = [
        ("VIAB",     5,  "w"),
        ("SYM",      14, "w"),   # includes TYPE suffix "(P-P)"/"(P-S)"/"(S-S)"
        ("VENUES",   24, "w"),
        ("APR",      8,  "e"),
        ("PROFIT$",  11, "e"),   # $ on $1k 24h after fees_rt
        ("LIFE",     7,  "e"),
        ("BKEVN",    7,  "e"),
        ("DEPTH$1k", 9,  "e"),   # slippage bps on $1k notional
    ]
```

- [ ] **Step 5: Add `_ARB_LIFETIME_TRACKER` attribute hook**

Inside the `App` class near the other `_arb_*` attributes (just above `_arbitrage_hub`), add:

```python
    # Per-instance LifetimeTracker. Lazily created on first access via
    # _arb_lifetime_tracker(). Persists across scan ticks, drops on relaunch.
    _arb_lifetime_tracker_cached: "LifetimeTracker | None" = None

    def _arb_lifetime_tracker(self):
        from core.arb.lifetime import LifetimeTracker
        if self._arb_lifetime_tracker_cached is None:
            self._arb_lifetime_tracker_cached = LifetimeTracker()
        return self._arb_lifetime_tracker_cached
```

- [ ] **Step 6: Run smoke test to catch attribute errors**

Run: `python smoke_test.py --quiet`
Expected: 100% pass. No UI rendering happens here — just verifies the app class imports cleanly.

- [ ] **Step 7: Commit**

```bash
git add launcher.py
git commit -m "feat(arb): declare 8-tab layout + v2 filter defaults"
```

---

## Task 7: 8-tab strip render + category separator + auto-compact

**Files:**
- Modify: `launcher_support/screens/arbitrage_hub.py:24-210` (the `render` function)
- Test: `tests/launcher/test_arb_hub_v2.py` (new)

- [ ] **Step 1: Write the failing integration test**

Create `tests/launcher/test_arb_hub_v2.py`:

```python
"""Integration smoke for Arbitrage Hub v2 density redesign.

Stubs out the Tk layer with a minimal fake app so we can assert on the
label dict the render function produces, without spinning up a Tk root.
"""
from __future__ import annotations

import types

import pytest

tk = pytest.importorskip("tkinter")


class _StubApp:
    """Minimal App-like stub satisfying render()'s expectations.

    We only need enough surface for the tab-strip render path to run:
    main frame, history list, key bindings, filter state.
    """

    def __init__(self, root):
        self.root = root
        self.main = tk.Frame(root)
        self.history = []
        self.h_path = tk.Label(root, text="")
        self.h_stat = tk.Label(root, text="")
        self.f_lbl = tk.Label(root, text="")
        self._kb_bound = []

        # Import the real class attrs defined in launcher.App
        import launcher as _l
        self._ARB_TAB_DEFS = _l.App._ARB_TAB_DEFS
        self._ARB_TAB_CATEGORIES = _l.App._ARB_TAB_CATEGORIES
        self._ARB_LEGACY_TAB_MAP = _l.App._ARB_LEGACY_TAB_MAP
        self._ARB_FILTER_DEFAULTS = dict(_l.App._ARB_FILTER_DEFAULTS)
        self._ARB_OPPS_COLS = _l.App._ARB_OPPS_COLS
        self._arb_filters = dict(self._ARB_FILTER_DEFAULTS)
        self._arb_cache = None
        self._arb_tab = "cex-cex"
        self._arb_tab_labels = {}

    def _clr(self): pass
    def _clear_kb(self): pass
    def _kb(self, k, fn): self._kb_bound.append(k)
    def _bind_global_nav(self): pass
    def _ui_call_soon(self, fn): fn()

    def _arb_update_status_strip(self): pass
    def _arbitrage_hub(self, t): self._arb_tab = t
    def _arb_hub_scan_async(self): pass
    def _arb_schedule_refresh(self): pass
    def _arb_schedule_clock(self): pass
    def _arb_scan_is_fresh(self): return True
    def _arb_hub_telem_update(self, *a, **kw): pass

    def _arb_filter_state(self):
        return self._arb_filters

    def _arb_render_positions(self, parent): pass
    def _arb_render_history(self, parent): pass
    def _arb_render_tab_filtered(self, parent, tab_id): pass


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_render_mounts_eight_tab_labels(tk_root):
    from launcher_support.screens.arbitrage_hub import render
    app = _StubApp(tk_root)
    render(app, tab="cex-cex")
    assert set(app._arb_tab_labels.keys()) == {
        "cex-cex", "dex-dex", "cex-dex",
        "perp-perp", "spot-spot", "basis",
        "positions", "history",
    }


def test_render_active_tab_default_is_cex_cex(tk_root):
    from launcher_support.screens.arbitrage_hub import render
    app = _StubApp(tk_root)
    render(app, tab="cex-cex")
    assert app._arb_tab == "cex-cex"


def test_render_legacy_tab_aliases_to_v2(tk_root):
    from launcher_support.screens.arbitrage_hub import render
    app = _StubApp(tk_root)
    # Legacy "opps" should transparently become "cex-cex"
    render(app, tab="opps")
    assert app._arb_tab == "cex-cex"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v`
Expected: FAIL (currently only 3 tab labels mount; no `_ARB_TAB_CATEGORIES` attribute).

- [ ] **Step 3: Rewrite the `render` function — tab strip section**

First, at the very top of `render(app, tab="cex-cex")` (immediately after the `def render(...)` signature, before any other body line), insert one line so the breadcrumb and the rest of the function see the canonical v2 tab id:

```python
    # Transparent legacy tab alias resolution (e.g. "opps" → "cex-cex").
    tab = app._ARB_LEGACY_TAB_MAP.get(tab, tab)
```

Then in `launcher_support/screens/arbitrage_hub.py`, replace the tab-strip block (lines ~102-163, the big `grouped_tabs` + `tabs_frame` + label loop) with:

```python
    # -- Tab strip (v2: 8 tabs, type category + meta category separated by `|`) --
    # Layout:  [1 CEX-CEX] [2 DEX-DEX] ... [6 BASIS]  |  [7 POSITIONS] [8 HISTORY]
    tabs_frame = tk.Frame(outer, bg=BG)
    tabs_frame.pack(fill="x", padx=16, pady=(0, 0))
    app._arb_tab = tab
    app._arb_tab_labels = {}

    # Partition into (category, items) groups so we can insert a
    # vertical divider between "type" and "meta".
    type_items: list[tuple[str, str, str, str]] = []
    meta_items: list[tuple[str, str, str, str]] = []
    for key, tid, label, color in app._ARB_TAB_DEFS:
        cat = app._ARB_TAB_CATEGORIES.get(tid, "type")
        (type_items if cat == "type" else meta_items).append(
            (key, tid, label, color))

    # Auto-compact level chosen later (default = 0 = full with counters).
    # Initial mount uses level 0; after winfo_reqwidth measure we may
    # re-render with a higher level. Counters default to 0 until scan.
    counts = {tid: 0 for _, tid, _, _ in app._ARB_TAB_DEFS}
    level = getattr(app, "_arb_tab_compact_level", 0)

    from core.arb.tab_matrix import compact_labels

    def _render_strip(_level: int):
        # Clear children before re-render
        for w in tabs_frame.winfo_children():
            w.destroy()
        app._arb_tab_labels = {}

        for grp_idx, grp in enumerate((type_items, meta_items)):
            if grp_idx == 1 and type_items:
                tk.Frame(tabs_frame, bg=BORDER, width=1).pack(
                    side="left", fill="y", padx=8, pady=(8, 2))
            labelled = compact_labels(grp, counts=counts, level=_level)
            for key, tid, label, color in labelled:
                is_active = (tid == tab)
                if is_active:
                    fg, bg = BG, AMBER
                else:
                    fg, bg = DIM, BG
                lbl = tk.Label(
                    tabs_frame,
                    text=f"  {label}  ",
                    font=(FONT, 9, "bold"),
                    fg=fg, bg=bg, cursor="hand2",
                    padx=8, pady=4, bd=0, highlightthickness=0,
                )
                lbl.pack(side="left", padx=(0, 1))
                lbl.bind("<Button-1>",
                         lambda _e, _t=tid: app._arbitrage_hub(_t))
                if not is_active:
                    lbl.bind("<Enter>",
                             lambda _e, w=lbl: w.config(bg=BG3, fg=WHITE))
                    lbl.bind("<Leave>",
                             lambda _e, w=lbl: w.config(bg=BG, fg=DIM))
                app._arb_tab_labels[tid] = lbl

    _render_strip(level)

    # After first layout pass, measure width. If the strip overflows the
    # outer frame's inner width, bump the compact level up to 3 max and
    # re-render once. Idempotent: we don't loop back to level 0.
    def _maybe_compact():
        try:
            outer.update_idletasks()
            strip_w = tabs_frame.winfo_reqwidth()
            avail_w = outer.winfo_width() - 32  # minus padx
            if avail_w <= 0:
                return
            lv = level
            while strip_w > avail_w and lv < 3:
                lv += 1
                _render_strip(lv)
                tabs_frame.update_idletasks()
                strip_w = tabs_frame.winfo_reqwidth()
            app._arb_tab_compact_level = lv
        except Exception:
            pass

    app.main.after_idle(_maybe_compact)
```

Also update the keyboard-shortcut loop (around line 170) — it's already using `app._ARB_TAB_DEFS`, which still works for 8 tabs since keys are "1"-"8". Verify by reading the block; it needs no change except that `for key, tid, _, _ in app._ARB_TAB_DEFS` already unpacks 4 values — leave intact.

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v`
Expected: PASS (all 3 tests).

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/arbitrage_hub.py tests/launcher/test_arb_hub_v2.py
git commit -m "feat(arb-hub): 8-tab strip with category separator + auto-compact"
```

---

## Task 8: Generic `render_tab_filtered` + `render_map` dispatch

**Files:**
- Modify: `launcher_support/screens/arbitrage_hub.py:177-184` (render_map) and append new `render_tab_filtered` function.
- Modify: `launcher.py` (add `_arb_render_tab_filtered` delegate)
- Test: `tests/launcher/test_arb_hub_v2.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/launcher/test_arb_hub_v2.py`:

```python
def test_render_map_dispatches_type_tabs_to_generic(tk_root, monkeypatch):
    """All 6 type tabs use the same generic renderer with the tab id passed in."""
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)

    calls: list[str] = []
    def fake_filtered(parent, tab_id):
        calls.append(tab_id)
    monkeypatch.setattr(app, "_arb_render_tab_filtered",
                        fake_filtered, raising=False)

    for tab_id in ("cex-cex", "dex-dex", "cex-dex",
                    "perp-perp", "spot-spot", "basis"):
        calls.clear()
        ah.render(app, tab=tab_id)
        assert calls == [tab_id], f"tab {tab_id!r} did not dispatch to generic"


def test_render_positions_and_history_use_dedicated_renderers(tk_root, monkeypatch):
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)

    pos_calls = []
    his_calls = []
    monkeypatch.setattr(app, "_arb_render_positions",
                        lambda p: pos_calls.append(True), raising=False)
    monkeypatch.setattr(app, "_arb_render_history",
                        lambda p: his_calls.append(True), raising=False)
    ah.render(app, tab="positions")
    ah.render(app, tab="history")
    assert pos_calls == [True]
    assert his_calls == [True]
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v -k "render_map or positions_and_history"`
Expected: FAIL — current `render_map` only has 3 entries.

- [ ] **Step 3: Rewrite `render_map` in arbitrage_hub.py**

In `launcher_support/screens/arbitrage_hub.py`, replace the current dispatch block (around lines 177-184):

```python
    # Route to the tab renderer. Type tabs (6) all share the generic
    # filtered renderer — the only thing that differs is which predicate
    # they feed into core.arb.tab_matrix.matches_type.
    if tab in ("cex-cex", "dex-dex", "cex-dex",
               "perp-perp", "spot-spot", "basis"):
        app._arb_render_tab_filtered(content, tab)
    elif tab == "positions":
        app._arb_render_positions(content)
    elif tab == "history":
        app._arb_render_history(content)
    else:
        # Defensive fallback: unknown tab → CEX-CEX (the default first tab).
        app._arb_render_tab_filtered(content, "cex-cex")
```

Append the new generic renderer at the bottom of `arbitrage_hub.py`:

```python
# ─── Generic filtered tab renderer (v2 density redesign 2026-04-23) ───

def render_tab_filtered(app, parent, tab_id: str):
    """Render one of the 6 type tabs. Same legend + filter bar +
    opps table as the old unified OPPS view; the only difference is
    which predicate is applied over the cached scan data.

    The active tab id is stashed on the app so paint_opps knows which
    predicate to use when it paints.
    """
    head = tk.Frame(parent, bg=BG)
    head.pack(fill="x", pady=(0, 3))
    tk.Label(head, text="GO", font=(FONT, 7, "bold"),
             fg=GREEN, bg=BG).pack(side="left", padx=(0, 3))
    tk.Label(head, text="score≥70 · bkevn≤24h · líquido",
             font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left", padx=(0, 8))
    tk.Label(head, text="WAIT", font=(FONT, 7, "bold"),
             fg=AMBER, bg=BG).pack(side="left", padx=(0, 3))
    tk.Label(head, text="score≥40 · bkevn≤72h OU vol moderada",
             font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left", padx=(0, 8))
    tk.Label(head, text="SKIP", font=(FONT, 7, "bold"),
             fg=DIM, bg=BG).pack(side="left", padx=(0, 3))
    tk.Label(head, text="resto", font=(FONT, 7),
             fg=DIM2, bg=BG).pack(side="left")

    app._arb_build_filter_bar(parent)
    app._arb_opps_selected = []
    app._arb_active_type_tab = tab_id

    def _on_click(ri: int):
        if 0 <= ri < len(app._arb_opps_selected):
            app._arb_show_detail(app._arb_opps_selected[ri])

    _, repaint = app._arb_make_table(parent, app._ARB_OPPS_COLS,
                                      on_click=_on_click)
    app._arb_opps_repaint = repaint
    repaint([])
    app._arb_build_detail_pane(parent)
```

- [ ] **Step 4: Add delegate in launcher.py**

In `launcher.py`, near the other `_arb_render_*` delegates (search for `_arb_render_opps`), add:

```python
    def _arb_render_tab_filtered(self, parent, tab_id: str):
        from launcher_support.screens.arbitrage_hub import render_tab_filtered
        return render_tab_filtered(self, parent, tab_id)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add launcher_support/screens/arbitrage_hub.py launcher.py tests/launcher/test_arb_hub_v2.py
git commit -m "feat(arb-hub): generic render_tab_filtered dispatched by predicate"
```

---

## Task 9: 8-column `paint_opps` using sort_key + predicate + lifetime + profit$/depth

**Files:**
- Modify: `launcher_support/screens/arbitrage_hub.py:1177-1259` (`paint_opps`)
- Test: `tests/launcher/test_arb_hub_v2.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/launcher/test_arb_hub_v2.py`:

```python
def test_paint_opps_filters_by_active_predicate(tk_root, monkeypatch):
    """When active type tab is CEX-CEX, only CEX-CEX pairs get painted."""
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_active_type_tab = "cex-cex"

    painted_rows = []
    def fake_repaint(rows): painted_rows.extend(rows)
    app._arb_opps_repaint = fake_repaint
    app._arb_opps_selected = []

    # Patch filter_and_score to return pairs + fake ScoreResults without
    # recomputing. Order is sorted by (grade, bkevn, -profit).
    def fake_filter_and_score(self, pairs):
        from types import SimpleNamespace
        out = []
        for p in pairs:
            sr = SimpleNamespace(
                score=80, grade="GO", viab="GO",
                breakeven_h=5.0, profit_usd_per_1k_24h=2.5,
                depth_pct_at_1k=12.0,
            )
            out.append((p, sr))
        return out
    monkeypatch.setattr(app, "_arb_filter_and_score",
                        fake_filter_and_score.__get__(app), raising=False)
    monkeypatch.setattr(app, "_arb_lifetime_tracker",
                        lambda: _FakeTracker(), raising=False)

    cc_pair = {"symbol": "BTC", "short_venue": "binance", "long_venue": "bybit",
               "_type": "CC", "net_apr": 30.0}
    dd_pair = {"symbol": "ETH", "short_venue": "hyperliquid",
               "long_venue": "dydx", "_type": "DD", "net_apr": 25.0}
    ah.paint_opps(app, arb_cc=[cc_pair], arb_dd=[dd_pair],
                   arb_cd=[], basis=[], spot=[])

    # Only CEX-CEX survives the active-tab predicate
    assert len(painted_rows) == 1
    assert app._arb_opps_selected[0]["symbol"] == "BTC"


class _FakeTracker:
    def observe_pairs(self, pairs, now): pass
    def age(self, key, now): return 120.0  # 2 minutes


def test_paint_opps_row_has_eight_columns(tk_root, monkeypatch):
    """Each row must have 8 cells matching _ARB_OPPS_COLS."""
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_active_type_tab = "cex-cex"

    painted_rows = []
    app._arb_opps_repaint = lambda rows: painted_rows.extend(rows)
    app._arb_opps_selected = []

    def fake_filter_and_score(self, pairs):
        from types import SimpleNamespace
        return [(pairs[0], SimpleNamespace(
            score=80, grade="GO", viab="GO",
            breakeven_h=5.0, profit_usd_per_1k_24h=2.5,
            depth_pct_at_1k=12.0))] if pairs else []
    monkeypatch.setattr(app, "_arb_filter_and_score",
                        fake_filter_and_score.__get__(app), raising=False)
    monkeypatch.setattr(app, "_arb_lifetime_tracker",
                        lambda: _FakeTracker(), raising=False)

    pair = {"symbol": "BTC", "short_venue": "binance", "long_venue": "bybit",
            "_type": "CC", "net_apr": 30.0}
    ah.paint_opps(app, arb_cc=[pair], arb_dd=[], arb_cd=[], basis=[], spot=[])

    assert len(painted_rows) == 1
    row = painted_rows[0]
    assert len(row) == 8, f"expected 8 cells, got {len(row)}"
    # Cell order: VIAB, SYM(TYPE), VENUES, APR, PROFIT$, LIFE, BKEVN, DEPTH
    viab_cell, sym_cell, venues_cell, apr_cell, \
        profit_cell, life_cell, bkevn_cell, depth_cell = row
    assert viab_cell[0] == "GO"
    assert "(P-P)" in sym_cell[0]
    assert "binance" in venues_cell[0]
    assert "%" in apr_cell[0]
    assert "$" in profit_cell[0]
    assert "m" in life_cell[0] or "h" in life_cell[0]
    assert "h" in bkevn_cell[0] or "—" in bkevn_cell[0]
    assert "bps" in depth_cell[0] or "—" in depth_cell[0]
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v -k "paint_opps"`
Expected: FAIL.

- [ ] **Step 3: Rewrite `paint_opps`**

In `launcher_support/screens/arbitrage_hub.py`, replace the entire `paint_opps` function (lines ~1177-1259) with:

```python
def paint_opps(app, arb_cc, arb_dd, arb_cd, basis, spot):
    """v2 painter — 8 columns, predicate by active type tab, new sort key.

    Columns: VIAB · SYM(TYPE) · VENUES · APR · PROFIT$/$1k 24h · LIFE ·
    BKEVN · DEPTH$1k. Sort: (grade asc, BKEVN asc, PROFIT$ desc).
    """
    import time as _time
    from core.arb.tab_matrix import matches_type, opps_sort_key, pair_kinds
    from core.arb.lifetime import stable_key, fmt_duration

    repaint = getattr(app, "_arb_opps_repaint", None)
    if repaint is None:
        return

    active_tab = getattr(app, "_arb_active_type_tab", "cex-cex")

    # Tag each opp with its source _type (same convention the v1 painter used)
    tagged: list[dict] = []
    for p in (arb_cc or []):
        pp = dict(p); pp["_type"] = "CC"; tagged.append(pp)
    for p in (arb_dd or []):
        pp = dict(p); pp["_type"] = "DD"; tagged.append(pp)
    for p in (arb_cd or []):
        pp = dict(p); pp["_type"] = "CD"; tagged.append(pp)
    for p in (basis or []):
        pp = dict(p); pp["_type"] = "BS"
        pp.setdefault("net_apr", pp.get("basis_apr"))
        pp.setdefault("short_venue", pp.get("venue_perp"))
        pp.setdefault("long_venue", pp.get("venue_spot"))
        pp.setdefault("volume_24h_short", pp.get("volume_perp"))
        pp.setdefault("volume_24h_long", pp.get("volume_spot"))
        pp.setdefault("volume_24h", min(
            pp.get("volume_perp", 0) or 0,
            pp.get("volume_spot", 0) or 0))
        tagged.append(pp)
    for p in (spot or []):
        pp = dict(p); pp["_type"] = "SP"
        pp.setdefault("net_apr",
                      abs(pp.get("spread_bps", 0) or 0) / 100.0)
        pp.setdefault("short_venue", pp.get("venue_a"))
        pp.setdefault("long_venue", pp.get("venue_b"))
        pp.setdefault("volume_24h_short", pp.get("volume_a"))
        pp.setdefault("volume_24h_long", pp.get("volume_b"))
        pp.setdefault("volume_24h", min(
            pp.get("volume_a", 0) or 0,
            pp.get("volume_b", 0) or 0))
        tagged.append(pp)

    # Observe lifetimes on every pair we know about (before predicate filter,
    # so a pair that shifts between tabs still keeps its original first-seen).
    now = _time.time()
    tracker = app._arb_lifetime_tracker()
    tracker.observe_pairs(tagged, now=now)

    # Apply predicate for the active tab, then score + filter + sort.
    in_tab = [pp for pp in tagged if matches_type(pp, active_tab)]
    scored = app._arb_filter_and_score(in_tab)
    scored.sort(key=opps_sort_key)
    scored = scored[:50]
    app._arb_opps_selected = [p for p, _ in scored]

    # Type suffix map for SYM column
    _kind_to_suffix = {
        ("perp", "perp"): "(P-P)",
        ("perp", "spot"): "(P-S)",
        ("spot", "perp"): "(P-S)",
        ("spot", "spot"): "(S-S)",
    }

    rows = []
    for a, sr in scored:
        viab = getattr(sr, "viab", sr.grade)
        viab_fg = (GREEN if viab == "GO" else
                    AMBER if viab in ("WAIT", "MAYBE") else DIM)

        net_apr = float(a.get("net_apr", 0) or 0)
        apr_fg = (GREEN if abs(net_apr) >= 50 else
                   AMBER if abs(net_apr) >= 20 else DIM)

        suffix = _kind_to_suffix.get(pair_kinds(a), "")
        sym = (a.get("symbol", "") or "—")[:8]
        sym_display = f"{sym} {suffix}" if suffix else sym

        short_v = (a.get("short_venue") or "")[:10].lower()
        long_v = (a.get("long_venue") or "")[:10].lower()
        venues = f"{long_v} → {short_v}"[:24]

        profit = getattr(sr, "profit_usd_per_1k_24h", None)
        if profit is None:
            profit_txt = "—"; profit_fg = DIM
        else:
            profit_txt = f"${profit:+.2f}"
            profit_fg = GREEN if profit > 0 else RED

        age = tracker.age(stable_key(a), now=now)
        life_txt = fmt_duration(age) if age is not None else "—"
        life_fg = DIM2 if age is None else (AMBER if age < 1800 else WHITE)

        be = getattr(sr, "breakeven_h", None)
        if be is None or be >= 999:
            be_txt = "—"; be_fg = DIM
        else:
            be_txt = f"{be:.1f}h"
            be_fg = GREEN if be <= 24 else (AMBER if be <= 72 else DIM)

        depth = getattr(sr, "depth_pct_at_1k", None)
        if depth is None:
            depth_txt = "—"; depth_fg = DIM
        else:
            depth_txt = f"{depth:.1f}bps"
            depth_fg = (GREEN if depth < 5 else
                         AMBER if depth < 15 else RED)

        rows.append([
            (viab, viab_fg),
            (sym_display, WHITE),
            (venues, AMBER_D),
            (f"{net_apr:+.1f}%", apr_fg),
            (profit_txt, profit_fg),
            (life_txt, life_fg),
            (be_txt, be_fg),
            (depth_txt, depth_fg),
        ])
    repaint(rows)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v -k "paint"`
Expected: PASS.

Run: `pytest tests/ -v -k "arb"` — the wider arb test surface should still pass.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/arbitrage_hub.py tests/launcher/test_arb_hub_v2.py
git commit -m "feat(arb-hub): 8-column v2 paint_opps with predicate+lifetime"
```

---

## Task 10: Extend `filter_and_score` + 3 new filter chips in `build_viab_toolbar`

**Files:**
- Modify: `launcher_support/screens/arbitrage_hub.py:461-531` (`build_viab_toolbar`)
- Modify: `launcher_support/screens/arbitrage_hub.py:1737-1841` (`filter_and_score`)
- Modify: `launcher.py` (new delegate methods for 3 chip handlers)
- Test: `tests/launcher/test_arb_hub_v2.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/launcher/test_arb_hub_v2.py`:

```python
def test_filter_and_score_applies_profit_min(tk_root, monkeypatch):
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_filters["profit_min_usd"] = 3.0

    # Stub score_opp to return predictable profits
    from types import SimpleNamespace
    def fake_score_opp(pair, cfg=None):
        profit_by_sym = {"HIGH": 5.0, "LOW": 1.0}
        return SimpleNamespace(
            score=80, grade="GO", viab="GO", breakeven_h=5.0,
            profit_usd_per_1k_24h=profit_by_sym.get(pair["symbol"], 0.0),
            depth_pct_at_1k=10.0,
            factors={"net_apr": 80, "volume": 60, "oi": 60,
                     "risk": 100, "slippage": 50, "venue": 90},
        )
    monkeypatch.setattr("core.arb.arb_scoring.score_opp", fake_score_opp)
    monkeypatch.setattr(app, "_arb_score_fallback",
                        lambda p: fake_score_opp(p), raising=False)
    monkeypatch.setattr(app, "_pair_min",
                        lambda a, b: min(x for x in (a, b) if x is not None),
                        raising=False)
    app._ARB_REALISTIC_APR_MAX = 500.0
    app._ARB_REALISTIC_VOL_MIN = 0.0
    app._ARB_RISKY_VENUES = frozenset()

    pairs = [
        {"symbol": "HIGH", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 100.0, "volume_24h": 10_000_000,
         "open_interest": 10_000_000, "risk": "LOW"},
        {"symbol": "LOW", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 10.0, "volume_24h": 10_000_000,
         "open_interest": 10_000_000, "risk": "LOW"},
    ]
    out = ah.filter_and_score(app, pairs)
    # LOW (profit=1.0) drops below profit_min=3.0; HIGH survives
    symbols = [p["symbol"] for p, _ in out]
    assert "HIGH" in symbols
    assert "LOW" not in symbols


def test_filter_and_score_applies_venues_allow(tk_root, monkeypatch):
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_filters["venues_allow"] = ["binance", "bybit"]

    from types import SimpleNamespace
    sr = SimpleNamespace(score=80, grade="GO", viab="GO", breakeven_h=5.0,
                          profit_usd_per_1k_24h=5.0, depth_pct_at_1k=10.0,
                          factors={})
    monkeypatch.setattr("core.arb.arb_scoring.score_opp", lambda p, cfg=None: sr)
    monkeypatch.setattr(app, "_arb_score_fallback",
                        lambda p: sr, raising=False)
    monkeypatch.setattr(app, "_pair_min",
                        lambda a, b: min(x for x in (a, b) if x is not None),
                        raising=False)
    app._ARB_REALISTIC_APR_MAX = 500.0
    app._ARB_REALISTIC_VOL_MIN = 0.0
    app._ARB_RISKY_VENUES = frozenset()

    p_ok = {"symbol": "OK", "short_venue": "binance", "long_venue": "bybit",
            "_type": "CC", "net_apr": 30.0, "volume_24h": 10_000_000,
            "open_interest": 1_000_000, "risk": "LOW"}
    p_no = {"symbol": "NO", "short_venue": "hyperliquid", "long_venue": "dydx",
            "_type": "DD", "net_apr": 30.0, "volume_24h": 10_000_000,
            "open_interest": 1_000_000, "risk": "LOW"}
    out = ah.filter_and_score(app, [p_ok, p_no])
    symbols = [p["symbol"] for p, _ in out]
    assert "OK" in symbols
    assert "NO" not in symbols


def test_filter_and_score_applies_life_min(tk_root, monkeypatch):
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_filters["life_min_seconds"] = 60  # 1 minute

    class StubTracker:
        def __init__(self): self.ages = {"OLD": 300.0, "NEW": 5.0}
        def observe_pairs(self, pairs, now): pass
        def age(self, key, now):
            # Decode via the "symbol" prefix in stable_key — hack for test
            for sym, age in self.ages.items():
                if sym in key: return age
            # Fallback: parse the blake key — not exposed, so infer via pair
            return None
    tracker = StubTracker()
    # Rebuild stable_key-ish mapping so both SYM keys hit the tracker
    from core.arb import lifetime as _l
    orig_key = _l.stable_key
    def patched_key(pair):
        return pair.get("symbol", "UNKNOWN")  # test-only fake key
    monkeypatch.setattr(_l, "stable_key", patched_key)
    monkeypatch.setattr(app, "_arb_lifetime_tracker",
                        lambda: tracker, raising=False)

    from types import SimpleNamespace
    sr = SimpleNamespace(score=80, grade="GO", viab="GO", breakeven_h=5.0,
                          profit_usd_per_1k_24h=5.0, depth_pct_at_1k=10.0,
                          factors={})
    monkeypatch.setattr("core.arb.arb_scoring.score_opp", lambda p, cfg=None: sr)
    monkeypatch.setattr(app, "_arb_score_fallback",
                        lambda p: sr, raising=False)
    monkeypatch.setattr(app, "_pair_min",
                        lambda a, b: min(x for x in (a, b) if x is not None),
                        raising=False)
    app._ARB_REALISTIC_APR_MAX = 500.0
    app._ARB_REALISTIC_VOL_MIN = 0.0
    app._ARB_RISKY_VENUES = frozenset()

    pairs = [
        {"symbol": "OLD", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 30.0, "volume_24h": 10_000_000,
         "open_interest": 1_000_000, "risk": "LOW"},
        {"symbol": "NEW", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 30.0, "volume_24h": 10_000_000,
         "open_interest": 1_000_000, "risk": "LOW"},
    ]
    out = ah.filter_and_score(app, pairs)
    symbols = [p["symbol"] for p, _ in out]
    assert "OLD" in symbols
    assert "NEW" not in symbols
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v -k "filter_and_score"`
Expected: FAIL.

- [ ] **Step 3: Extend `filter_and_score`**

In `launcher_support/screens/arbitrage_hub.py`, inside the `filter_and_score` function (line ~1739), add new filter reads after the existing ones (after the line `exclude_risky = state.get("exclude_risky_venues", False)`):

```python
    profit_min   = float(state.get("profit_min_usd", 0.0) or 0.0)
    life_min     = float(state.get("life_min_seconds", 0) or 0)
    venues_allow = state.get("venues_allow")  # None OR list[str]
    venues_allow_set = None
    if venues_allow is not None:
        venues_allow_set = frozenset(str(v).lower() for v in venues_allow)

    # Lifetime tracker + now — used below to enforce life_min.
    import time as _t2
    _now = _t2.time()
    tracker = app._arb_lifetime_tracker() if life_min > 0 else None
```

After the existing `exclude_risky` block (just before the `ckey = (...)` cache-key build), add:

```python
        # v2: venue allowlist
        if venues_allow_set is not None:
            sv = (p.get("short_venue") or p.get("venue_perp")
                  or p.get("venue_a") or "").lower()
            lv = (p.get("long_venue") or p.get("venue_spot")
                  or p.get("venue_b") or "").lower()
            if sv and sv not in venues_allow_set:
                continue
            if lv and lv not in venues_allow_set:
                continue

        # v2: minimum lifetime (pair has to be in the stream for N seconds).
        # Skip entirely when the filter is off (life_min <= 0).
        if life_min > 0:
            from core.arb.lifetime import stable_key as _sk
            age = tracker.age(_sk(p), now=_now) if tracker is not None else None
            if age is None or age < life_min:
                continue
```

After the existing `if _G.get(sr.grade, 2) > grade_cap: continue` line, add the profit cut:

```python
        # v2: minimum $ profit per $1k per 24h.
        if profit_min > 0:
            pf = getattr(sr, "profit_usd_per_1k_24h", None)
            if pf is None or pf < profit_min:
                continue
```

And change the sort at the end of the function to use `opps_sort_key`:

```python
    from core.arb.tab_matrix import opps_sort_key
    out.sort(key=opps_sort_key)
    return out
```

(Delete the old `_key` closure and `out.sort(key=_key)` lines.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v -k "filter_and_score"`
Expected: PASS.

- [ ] **Step 5: Add 3 new filter chips to the viab toolbar**

At the end of `build_viab_toolbar` (around line 530 in arbitrage_hub.py), append:

```python
    # Divider
    tk.Frame(bar, bg=BORDER, width=1, height=18).pack(
        side="left", fill="y", padx=(10, 10))

    # v2 density chips — PROFIT$, LIFE, VENUES
    pm = float(state.get("profit_min_usd", 0.0) or 0.0)
    pm_label = f" PROFIT$ ≥ {pm:.0f} " if pm > 0 else " PROFIT$ OFF "
    pm_btn = tk.Label(bar, text=pm_label,
                       font=(FONT, 8, "bold"),
                       fg=AMBER if pm > 0 else DIM, bg=BG,
                       cursor="hand2", padx=6, pady=3)
    pm_btn.pack(side="left", padx=(0, 4))
    pm_btn.bind("<Button-1>", lambda _e: app._arb_open_profit_popover(pm_btn))
    app._arb_viab_btns["profit"] = (pm_btn, None)

    lm = int(state.get("life_min_seconds", 0) or 0)
    lm_label = (f" LIFE ≥ {lm // 60}m " if lm > 0 else " LIFE OFF ")
    lm_btn = tk.Label(bar, text=lm_label,
                       font=(FONT, 8, "bold"),
                       fg=AMBER if lm > 0 else DIM, bg=BG,
                       cursor="hand2", padx=6, pady=3)
    lm_btn.pack(side="left", padx=(0, 4))
    lm_btn.bind("<Button-1>", lambda _e: app._arb_open_life_popover(lm_btn))
    app._arb_viab_btns["life"] = (lm_btn, None)

    va = state.get("venues_allow")
    va_label = (" VENUES ALL " if va is None
                else f" VENUES {len(va)} SEL ")
    va_btn = tk.Label(bar, text=va_label,
                       font=(FONT, 8, "bold"),
                       fg=AMBER if va else DIM, bg=BG,
                       cursor="hand2", padx=6, pady=3)
    va_btn.pack(side="left")
    va_btn.bind("<Button-1>", lambda _e: app._arb_open_venues_popover(va_btn))
    app._arb_viab_btns["venues"] = (va_btn, None)
```

Append three popover openers to `launcher_support/screens/arbitrage_hub.py` (at the bottom of the file):

```python
# ─── v2 filter popovers ───

def open_profit_popover(app, anchor):
    """Numeric entry popover for PROFIT$ ≥ threshold. Persists on Enter."""
    _open_numeric_popover(app, anchor, key="profit_min_usd",
                           title="PROFIT$ ≥", suffix="$",
                           parse=lambda s: float(s))


def open_life_popover(app, anchor):
    """Entry popover with m/h suffix for LIFE ≥."""
    def _parse(s: str) -> float:
        s = s.strip().lower()
        if s.endswith("h"):
            return float(s[:-1]) * 3600
        if s.endswith("m"):
            return float(s[:-1]) * 60
        return float(s) * 60  # bare number = minutes
    _open_numeric_popover(app, anchor, key="life_min_seconds",
                           title="LIFE ≥", suffix="m/h",
                           parse=lambda s: int(_parse(s)))


def open_venues_popover(app, anchor):
    """Checkbox popover listing known venues from connections.json.

    None = all allowed (off). List of lowercase names = allowlist.
    Falls back to the CEX_VENUES constant if connections.json missing.
    """
    import json as _json
    from pathlib import Path as _P

    venues = []
    try:
        path = _P("config") / "connections.json"
        if path.exists():
            data = _json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                venues = sorted(str(k).lower() for k in data.keys())
    except Exception:
        pass
    if not venues:
        from core.arb.tab_matrix import CEX_VENUES
        venues = sorted(CEX_VENUES)

    pop = tk.Toplevel(anchor)
    pop.overrideredirect(True)
    pop.configure(bg=BG)
    x = anchor.winfo_rootx()
    y = anchor.winfo_rooty() + anchor.winfo_height()
    pop.geometry(f"+{x}+{y}")

    current = app._arb_filter_state().get("venues_allow")
    vars: dict[str, tk.BooleanVar] = {}
    for v in venues:
        bv = tk.BooleanVar(value=(current is None or v in current))
        vars[v] = bv
        cb = tk.Checkbutton(pop, text=v, variable=bv,
                             fg=WHITE, bg=BG, selectcolor=BG3,
                             font=(FONT, 8), anchor="w")
        cb.pack(fill="x", padx=4)

    def _commit(_e=None):
        picked = [v for v, bv in vars.items() if bv.get()]
        # All on = None (off); any subset = list
        new_val = None if len(picked) == len(venues) else picked
        app._arb_filter_state()["venues_allow"] = new_val
        app._arb_save_filters()
        pop.destroy()
        app._arb_rerender_current_tab()
        # Re-mount toolbar so label reflects new state
        app._arb_tab_labels = None
        app._arbitrage_hub(app._arb_tab)
    btn = tk.Label(pop, text=" OK ", font=(FONT, 8, "bold"),
                    fg=BG, bg=AMBER, cursor="hand2", padx=8, pady=3)
    btn.pack(pady=(4, 4))
    btn.bind("<Button-1>", _commit)


def _open_numeric_popover(app, anchor, *, key: str, title: str,
                            suffix: str, parse):
    """Shared numeric-entry popover. Commits on <Return>."""
    pop = tk.Toplevel(anchor)
    pop.overrideredirect(True)
    pop.configure(bg=BG)
    x = anchor.winfo_rootx()
    y = anchor.winfo_rooty() + anchor.winfo_height()
    pop.geometry(f"+{x}+{y}")
    tk.Label(pop, text=f"{title} ({suffix})",
             font=(FONT, 7, "bold"), fg=DIM, bg=BG).pack(padx=6, pady=(4, 2))
    ent = tk.Entry(pop, width=10, font=(FONT, 9),
                    fg=WHITE, bg=BG3, insertbackground=WHITE)
    ent.pack(padx=6, pady=(0, 4))
    ent.focus_set()

    def _commit(_e=None):
        raw = ent.get().strip()
        try:
            val = parse(raw) if raw else 0
        except Exception:
            val = 0
        app._arb_filter_state()[key] = val
        app._arb_save_filters()
        pop.destroy()
        app._arb_rerender_current_tab()
        # Re-render toolbar so the chip label reflects the new value
        app._arb_tab_labels = None
        app._arbitrage_hub(app._arb_tab)

    ent.bind("<Return>", _commit)
    ent.bind("<Escape>", lambda _e: pop.destroy())
```

Add three delegates in `launcher.py` near the other chip handlers (search for `_arb_toggle_realistic`):

```python
    def _arb_open_profit_popover(self, anchor):
        from launcher_support.screens.arbitrage_hub import open_profit_popover
        return open_profit_popover(self, anchor)
    def _arb_open_life_popover(self, anchor):
        from launcher_support.screens.arbitrage_hub import open_life_popover
        return open_life_popover(self, anchor)
    def _arb_open_venues_popover(self, anchor):
        from launcher_support.screens.arbitrage_hub import open_venues_popover
        return open_venues_popover(self, anchor)
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v`
Expected: PASS (all tests added so far).

Run: `python smoke_test.py --quiet`
Expected: 100% pass.

- [ ] **Step 7: Commit**

```bash
git add launcher_support/screens/arbitrage_hub.py launcher.py tests/launcher/test_arb_hub_v2.py
git commit -m "feat(arb-hub): profit/life/venues filter chips + persistence"
```

---

## Task 11: Counter `(N)` update + lifetime wiring in `hub_telem_update`

**Files:**
- Modify: `launcher_support/screens/arbitrage_hub.py:1657-1735` (`hub_telem_update`)
- Test: `tests/launcher/test_arb_hub_v2.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/launcher/test_arb_hub_v2.py`:

```python
def test_hub_telem_update_refreshes_tab_counts(tk_root, monkeypatch):
    """After scan, per-tab counter labels show the right (N) values."""
    from launcher_support.screens import arbitrage_hub as ah

    app = _StubApp(tk_root)
    ah.render(app, tab="cex-cex")

    # Bypass painter (we only care about tab labels here)
    monkeypatch.setattr(ah, "paint_opps",
                        lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(app, "_arb_feed_engine",
                        lambda *a, **kw: None, raising=False)

    # Two CEX-CEX, one CEX-DEX, one DEX-DEX
    cc = [
        {"symbol": "BTC", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 30.0},
        {"symbol": "ETH", "short_venue": "binance", "long_venue": "okx",
         "_type": "CC", "net_apr": 40.0},
    ]
    cd = [
        {"symbol": "SOL", "short_venue": "binance", "long_venue": "hyperliquid",
         "_type": "CD", "net_apr": 50.0},
    ]
    dd = [
        {"symbol": "XRP", "short_venue": "hyperliquid", "long_venue": "dydx",
         "_type": "DD", "net_apr": 20.0},
    ]

    stats = {"cex_online": 3, "dex_online": 2}

    # Stub status-strip labels so update doesn't blow up
    class _L: pass
    for n in ("_arb_live_dot", "_arb_sum_cex", "_arb_sum_dex",
              "_arb_sum_best", "_arb_scan_age"):
        lbl = tk.Label(tk_root, text=""); setattr(app, n, lbl)

    ah.hub_telem_update(app, stats=stats, top=None, opps=[],
                         arb_cc=cc, arb_dd=dd, arb_cd=cd,
                         basis=[], spot=[])

    # Labels were updated with counters — text should contain "(2)" for cex-cex,
    # "(1)" for dex-dex, cex-dex, perp-perp; "(0)" for spot-spot and basis
    assert "(2)" in app._arb_tab_labels["cex-cex"].cget("text")
    assert "(1)" in app._arb_tab_labels["dex-dex"].cget("text")
    assert "(1)" in app._arb_tab_labels["cex-dex"].cget("text")
    assert "(4)" in app._arb_tab_labels["perp-perp"].cget("text")
    assert "(0)" in app._arb_tab_labels["spot-spot"].cget("text")
    assert "(0)" in app._arb_tab_labels["basis"].cget("text")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v -k "refreshes_tab_counts"`
Expected: FAIL.

- [ ] **Step 3: Wire counters + lifetime into `hub_telem_update`**

In `launcher_support/screens/arbitrage_hub.py`, inside `hub_telem_update`, after the `app._arb_cache = {...}` block (around line 1703) and before the call to `app._arb_update_status_strip()`, add:

```python
    # v2: per-tab counter (N) and lifetime tracker refresh.
    import time as _time
    _now = _time.time()

    # Assemble the full unified pool for predicate counting.
    _tagged: list[dict] = []
    for _src, _tag in (
        (arb_cc, "CC"), (arb_dd, "DD"), (arb_cd, "CD"),
        (basis, "BS"), (spot, "SP"),
    ):
        for _p in (_src or []):
            _pp = dict(_p); _pp["_type"] = _tag
            _tagged.append(_pp)

    # Observe lifetimes on the full pool so cross-tab opps share first-seen
    tracker = app._arb_lifetime_tracker()
    tracker.observe_pairs(_tagged, now=_now)
    tracker.cleanup(now=_now, max_age=24 * 3600)  # drop after 1 day idle

    # Update per-tab (N) counters. Counts use matches_type over the raw pool
    # — user filters (PROFIT$/LIFE/VENUES) are NOT applied here to keep the
    # counter stable across filter toggles; the active tab's painter is the
    # one that re-applies all filters.
    from core.arb.tab_matrix import matches_type, compact_labels
    _counts: dict[str, int] = {}
    for _tid in ("cex-cex", "dex-dex", "cex-dex",
                  "perp-perp", "spot-spot", "basis"):
        _counts[_tid] = sum(1 for _pp in _tagged if matches_type(_pp, _tid))
    # Meta tabs (positions, history) show engine state counts.
    _eng = getattr(app, "_arb_simple_engine", None)
    _counts["positions"] = len(_eng.positions) if _eng is not None else 0
    _counts["history"]   = len(_eng.closed) if _eng is not None else 0

    # Apply the counts onto existing tab labels.
    level = getattr(app, "_arb_tab_compact_level", 0)
    labelled = compact_labels(app._ARB_TAB_DEFS, counts=_counts, level=level)
    for key, tid, display, _color in labelled:
        lbl = (app._arb_tab_labels or {}).get(tid)
        if lbl is not None:
            try:
                lbl.configure(text=f"  {display}  ")
            except Exception:
                pass
```

(The final block before the existing `if tab == "opps":` routes unchanged. Also replace `if tab == "opps":` with the new v2 logic:)

Replace the existing tab-dispatch block:

```python
    # Route to the repaint callback for the active tab.
    tab = getattr(app, "_arb_tab", "cex-cex")
    if tab in ("cex-cex", "dex-dex", "cex-dex",
                "perp-perp", "spot-spot", "basis"):
        app._arb_paint_opps(arb_cc, arb_dd, arb_cd, basis, spot)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/launcher/test_arb_hub_v2.py -v`
Expected: all PASS.

Run: `pytest tests/ -v -k "arb"`
Expected: existing arb contracts + tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/arbitrage_hub.py tests/launcher/test_arb_hub_v2.py
git commit -m "feat(arb-hub): per-tab counter (N) + lifetime wiring in telem update"
```

---

## Task 12: Integration smoke + acceptance audit + final commit

**Files:**
- Run: tests, smoke, CORE audit
- No code edits unless issues surface.

- [ ] **Step 1: Full test suite**

Run: `pytest tests/ -q`
Expected: all tests pass (no regressions). Note the new test count vs. pre-plan baseline.

- [ ] **Step 2: Smoke test**

Run: `python smoke_test.py --quiet`
Expected: 100% pass.

- [ ] **Step 3: CORE protection audit**

Run:
```bash
git diff main...HEAD -- core/indicators.py core/signals.py core/portfolio.py config/params.py
```
Expected: empty output. If non-empty: STOP and revert the CORE changes before merging.

- [ ] **Step 4: Lint pass**

Run: `ruff check core/arb/tab_matrix.py core/arb/lifetime.py core/arb/arb_scoring.py launcher_support/screens/arbitrage_hub.py launcher.py`
Expected: clean output (or only pre-existing warnings unrelated to the new code).

- [ ] **Step 5: Manual visual pass (João)**

Launch the GUI and walk through:

```bash
python launcher.py
```

Checklist (from spec acceptance criteria):
- Opens on tab `1 CEX-CEX` with 8 columns visible (VIAB · SYM(TYPE) · VENUES · APR · PROFIT$ · LIFE · BKEVN · DEPTH$1k).
- Keys `1`-`8` switch tabs.
- Tab counters `(N)` update after first scan.
- Click `PROFIT$` → popover opens, enter `5`, Enter → opps with profit <$5 drop.
- Click `LIFE` → popover, enter `5m`, Enter → opps with age <5min drop.
- Click `VENUES` → popover with checkboxes, uncheck `hyperliquid` → opps with that venue drop.
- Click a row → detail pane / simulator still works.
- Close and reopen launcher → filter values persist.
- Sort: first row inside each tab is always the GO with smallest BKEVN.

If any item fails, open an issue and do NOT ship the final merge commit.

- [ ] **Step 6: Session log + daily log + PR**

Following the project's "REGRA PERMANENTE — SESSION LOG" in CLAUDE.md, create:
- `docs/sessions/YYYY-MM-DD_HHMM.md` with the standard template.
- Update `docs/days/YYYY-MM-DD.md` with a new "Sessões do dia" entry.

Then commit + PR:

```bash
git add docs/sessions/ docs/days/
git commit -m "docs(session): arb hub v2 density — density implementation complete"
git push -u origin feat/arb-hub-v2
gh pr create --title "Arbitrage Hub v2 — density & type matrix" --body "$(cat <<'EOF'
## Summary
- 8-tab type matrix (CEX-CEX / DEX-DEX / CEX-DEX / PERP-PERP / SPOT-SPOT / BASIS / POSITIONS / HISTORY) replaces the old 3-tab layout.
- 8-column table with three new execution columns: PROFIT$/$1k 24h, LIFE (lifetime tracker), DEPTH$1k.
- Three new filter chips with popovers: PROFIT$ ≥, LIFE ≥, VENUES allowlist.
- Pure logic in new `core/arb/tab_matrix.py` + `core/arb/lifetime.py` (Tk-free, fully unit-tested).
- `score_opp` extended with `profit_usd_per_1k_24h` + `depth_pct_at_1k` (additive; existing callers unaffected).
- Sort: `(grade asc, BKEVN asc, PROFIT$ desc)`.
- CORE protection audit: `git diff` against `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` is empty.

## Test plan
- [ ] `pytest tests/ -q` green
- [ ] `python smoke_test.py --quiet` green
- [ ] Manual walkthrough: 8 tabs switch via keys 1-8, counters update, 3 filter popovers persist, row click opens simulator, sort rules hold.
- [ ] Spec `docs/superpowers/specs/2026-04-22-arbitrage-hub-v2-density-design.md` acceptance criteria 1-10 all satisfied.

Spec: `docs/superpowers/specs/2026-04-22-arbitrage-hub-v2-density-design.md`
Plan: `docs/superpowers/plans/2026-04-23-arbitrage-hub-v2-density.md`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Out of scope (matches spec)

- NET FEE / network gas column — stays inside the detail pane.
- VOL / OI explicit column — DEPTH covers the concept.
- VENUE TIER — stays as tooltip on VENUES hover (future work if needed).
- Decay-aware PERSISTENCE filter, DEPTH MAX %, PAR allowlist, NETWORK filter — phase 2.
- Side panel of filters (arbitragescanner style) — top bar is the chosen affordance.
- Sub-filters inside tabs.
- Header-click-to-sort columns — only add if default sort doesn't hold.
- Simulator / detail-pane changes.
- `SimpleArbEngine` internals.

## Risks (matches spec)

- **Scanner record `_type` / kind**: SPOT-SPOT + BASIS tabs stay visually empty when the scanner doesn't emit those opp types. Fallback is transparent (zero counts, empty table).
- **`book_depth_usd` field**: DEPTH$1k shows `—` until the scanner enriches records with book depth. Plan does not touch the scanner.
- **Lifetime tracker is in-memory**: reset on launcher restart. Persisting to disk is phase 2.
- **Label auto-compact**: Tk render sizes depend on system fonts. The 4-level fallback is idempotent and bounded (level 3 always fits). Visual validation only.
