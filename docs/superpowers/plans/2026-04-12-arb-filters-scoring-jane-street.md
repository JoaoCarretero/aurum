# Arb Filters + Scoring Jane Street — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a composite 6-factor scoring engine to arbitrage opportunities (GO/MAYBE/SKIP) with click-to-cycle filter bar in the scanner UI and semaphore bullets on the hub rows.

**Architecture:** New `core/arb_scoring.py` module with pure scoring logic. Config constants appended to `config/params.py`. UI changes in `launcher.py` — filter bar above scanner table, SCORE column in table + arb pairs, hub bullet colors from best scores. No backend changes to `core/funding_scanner.py` or `engines/arbitrage.py`.

**Tech Stack:** Python 3.14, stdlib only (math, dataclasses). Tkinter for UI. Tests via pytest.

**Spec reference:** `docs/superpowers/specs/2026-04-12-arb-filters-scoring-jane-street-design.md`

---

## File Structure

| File | Role | Action |
|---|---|---|
| `core/arb_scoring.py` | Pure scoring engine — score_opp, score_batch, ScoreResult | Create (~120 lines) |
| `config/params.py` | ARB_SCORE_WEIGHTS, ARB_SCORE_THRESHOLDS, ARB_FILTER_DEFAULTS, ARB_VENUE_RELIABILITY, ARB_POSITION_SIZE_REF | Modify (append ~25 lines + __all__ additions) |
| `launcher.py` | Filter bar in `_funding_scanner_screen`, SCORE column in `_funding_paint`, hub semaphore in `_arb_hub_telem_update` | Modify (~80 lines) |
| `tests/test_arb_scoring.py` | Unit tests for scoring engine | Create (~100 lines) |
| `smoke_test.py` | Import check for `core.arb_scoring` | Modify (+3 lines) |

---

## Task 1: Scoring engine — core tests + implementation

**Files:**
- Create: `tests/test_arb_scoring.py`
- Create: `core/arb_scoring.py`

### Step 1 — write failing tests

Create `tests/test_arb_scoring.py`:

```python
"""Tests for core.arb_scoring — composite arbitrage opportunity scoring."""
import math
import pytest


def _make_opp(**overrides):
    """Build a synthetic opp dict with sensible defaults."""
    base = {
        "symbol": "BTC",
        "venue": "binance",
        "venue_type": "CEX",
        "apr": 50.0,
        "volume_24h": 5_000_000,
        "open_interest": 2_000_000,
        "risk": "LOW",
    }
    base.update(overrides)
    return base


def _make_pair(**overrides):
    """Build a synthetic arb pair dict."""
    base = {
        "symbol": "ETH",
        "short_venue": "binance",
        "short_venue_type": "CEX",
        "short_rate": 0.0003,
        "short_interval_h": 8,
        "short_apr": 41.1,
        "long_venue": "dydx",
        "long_venue_type": "DEX",
        "long_rate": -0.0001,
        "long_interval_h": 1,
        "long_apr": -8.8,
        "net_apr": 49.9,
        "mark_price": 3200.0,
        "volume_24h_short": 8_000_000,
        "volume_24h_long": 1_200_000,
        "open_interest_short": 3_000_000,
        "open_interest_long": 800_000,
    }
    base.update(overrides)
    return base


# ── score_opp ────────────────────────────────────────────────

def test_score_opp_all_fields_present():
    from core.arb_scoring import score_opp, ScoreResult
    opp = _make_opp(apr=80.0, volume_24h=8_000_000, open_interest=3_000_000, risk="LOW")
    result = score_opp(opp)
    assert isinstance(result, ScoreResult)
    assert 0 <= result.score <= 100
    assert result.grade in ("GO", "MAYBE", "SKIP")
    assert result.score >= 70  # strong opp → GO


def test_score_opp_missing_volume():
    from core.arb_scoring import score_opp
    opp = _make_opp(volume_24h=None, open_interest=2_000_000)
    result = score_opp(opp)
    # volume factor is 0, weight redistributed → score lower but not zero
    assert 0 < result.score < 100


def test_score_opp_all_missing():
    from core.arb_scoring import score_opp
    result = score_opp({})
    assert result.score == 0.0
    assert result.grade == "SKIP"


def test_grade_threshold_boundary_skip():
    from core.arb_scoring import score_opp
    # Weak opp: low APR, low volume, HIGH risk
    opp = _make_opp(apr=2.0, volume_24h=50_000, open_interest=10_000, risk="HIGH")
    result = score_opp(opp)
    assert result.grade == "SKIP"
    assert result.score < 40


def test_grade_threshold_boundary_go():
    from core.arb_scoring import score_opp
    opp = _make_opp(apr=120.0, volume_24h=15_000_000, open_interest=6_000_000, risk="LOW")
    result = score_opp(opp)
    assert result.grade == "GO"
    assert result.score >= 70


def test_score_batch_parallel():
    from core.arb_scoring import score_batch
    opps = [_make_opp(apr=80.0), _make_opp(apr=5.0, risk="HIGH")]
    results = score_batch(opps)
    assert len(results) == 2
    assert results[0].score > results[1].score


def test_arb_pair_weakest_link():
    from core.arb_scoring import score_opp
    pair = _make_pair(
        volume_24h_short=20_000_000,
        volume_24h_long=80_000,       # weak long leg
        open_interest_short=5_000_000,
        open_interest_long=30_000,    # weak long leg
    )
    result = score_opp(pair)
    # The weak leg drags score down
    strong_pair = _make_pair(
        volume_24h_short=20_000_000,
        volume_24h_long=20_000_000,
        open_interest_short=5_000_000,
        open_interest_long=5_000_000,
    )
    strong_result = score_opp(strong_pair)
    assert result.score < strong_result.score


def test_weights_normalize():
    from core.arb_scoring import score_opp
    cfg = {
        "weights": {"net_apr": 1.0, "volume": 1.0, "oi": 1.0,
                     "risk": 1.0, "slippage": 1.0, "venue": 1.0},
        "thresholds": {"go": 70, "maybe": 40},
        "venue_reliability": {"binance": 99},
        "position_size_ref": 1000.0,
    }
    opp = _make_opp(apr=80.0, volume_24h=8_000_000, open_interest=3_000_000, risk="LOW")
    result = score_opp(opp, cfg=cfg)
    # Should still return valid score (weights normalized to sum=1)
    assert 0 <= result.score <= 100


def test_log_norm_boundaries():
    from core.arb_scoring import _log_norm
    assert _log_norm(50_000, 100_000, 10_000_000) == 0.0   # below floor
    assert _log_norm(100_000, 100_000, 10_000_000) == 0.0   # at floor
    assert _log_norm(10_000_000, 100_000, 10_000_000) == 100.0  # at ceil
    assert _log_norm(50_000_000, 100_000, 10_000_000) == 100.0  # above ceil
    mid = _log_norm(1_000_000, 100_000, 10_000_000)
    assert 40 < mid < 60  # log midpoint
```

### Step 2 — run tests, expect fail

```
python -m pytest tests/test_arb_scoring.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'core.arb_scoring'`.

### Step 3 — implement `core/arb_scoring.py`

Create `core/arb_scoring.py`:

```python
"""Composite scoring for arbitrage opportunities.

Six-factor weighted score: net_apr, volume, open_interest, risk,
slippage estimate, venue reliability. Output: 0-100 score with
GO / MAYBE / SKIP grade.

Pure functions — no side effects, no UI, no network.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# ── defaults (overridden by config.params when available) ────

_DEFAULT_WEIGHTS = {
    "net_apr": 0.30, "volume": 0.20, "oi": 0.15,
    "risk": 0.15, "slippage": 0.10, "venue": 0.10,
}
_DEFAULT_THRESHOLDS = {"go": 70, "maybe": 40}
_DEFAULT_VENUE_RELIABILITY: dict[str, float] = {
    "binance": 99, "bybit": 97, "gate": 95, "bitget": 94, "bingx": 92,
    "hyperliquid": 96, "dydx": 94, "paradex": 90,
}
_DEFAULT_POS_SIZE_REF = 1000.0


@dataclass
class ScoreResult:
    score: float = 0.0
    grade: str = "SKIP"
    factors: dict = field(default_factory=dict)


# ── helpers ──────────────────────────────────────────────────

def _log_norm(value: float, floor: float, ceil: float) -> float:
    """0 if value <= floor, 100 if value >= ceil, linear in log10 between."""
    if value is None or value <= 0 or value <= floor:
        return 0.0
    if value >= ceil:
        return 100.0
    return (math.log10(value) - math.log10(floor)) / \
           (math.log10(ceil) - math.log10(floor)) * 100.0


def _linear_clamp(value: float, floor: float, ceil: float) -> float:
    if value is None:
        return 0.0
    if value <= floor:
        return 0.0
    if value >= ceil:
        return 100.0
    return (value - floor) / (ceil - floor) * 100.0


def _resolve_cfg(cfg: dict | None) -> tuple[dict, dict, dict, float]:
    """Return (weights, thresholds, venue_reliability, pos_size_ref)."""
    if cfg is None:
        try:
            from config.params import (
                ARB_SCORE_WEIGHTS, ARB_SCORE_THRESHOLDS,
                ARB_VENUE_RELIABILITY, ARB_POSITION_SIZE_REF,
            )
            return (ARB_SCORE_WEIGHTS, ARB_SCORE_THRESHOLDS,
                    ARB_VENUE_RELIABILITY, ARB_POSITION_SIZE_REF)
        except ImportError:
            pass
        return (_DEFAULT_WEIGHTS, _DEFAULT_THRESHOLDS,
                _DEFAULT_VENUE_RELIABILITY, _DEFAULT_POS_SIZE_REF)
    return (
        cfg.get("weights", _DEFAULT_WEIGHTS),
        cfg.get("thresholds", _DEFAULT_THRESHOLDS),
        cfg.get("venue_reliability", _DEFAULT_VENUE_RELIABILITY),
        cfg.get("position_size_ref", _DEFAULT_POS_SIZE_REF),
    )


# ── public API ───────────────────────────────────────────────

def score_opp(opp: dict, cfg: dict | None = None) -> ScoreResult:
    """Score a single FundingOpp dict or arb_pair dict."""
    weights, thresholds, venue_rel, pos_ref = _resolve_cfg(cfg)

    # Normalize weights to sum=1
    w_total = sum(weights.values())
    if w_total <= 0:
        return ScoreResult()
    w = {k: v / w_total for k, v in weights.items()}

    # ── extract fields (handle both opp and pair shapes) ─────
    apr = opp.get("net_apr") or opp.get("apr")
    apr = abs(float(apr)) if apr is not None else None

    # For pairs: use weakest leg (min)
    vol = opp.get("volume_24h")
    if vol is None:
        vol_short = opp.get("volume_24h_short")
        vol_long = opp.get("volume_24h_long")
        if vol_short is not None and vol_long is not None:
            vol = min(float(vol_short), float(vol_long))
        elif vol_short is not None:
            vol = float(vol_short)
        elif vol_long is not None:
            vol = float(vol_long)
    else:
        vol = float(vol)

    oi = opp.get("open_interest")
    if oi is None:
        oi_short = opp.get("open_interest_short")
        oi_long = opp.get("open_interest_long")
        if oi_short is not None and oi_long is not None:
            oi = min(float(oi_short), float(oi_long))
        elif oi_short is not None:
            oi = float(oi_short)
        elif oi_long is not None:
            oi = float(oi_long)

    risk = opp.get("risk")
    venue = opp.get("venue")
    if venue is None:
        # pair: use the worst venue reliability
        sv = opp.get("short_venue")
        lv = opp.get("long_venue")
        if sv and lv:
            sv_rel = venue_rel.get(sv, 90)
            lv_rel = venue_rel.get(lv, 90)
            venue = sv if sv_rel <= lv_rel else lv
        else:
            venue = sv or lv

    # ── compute per-factor normalized scores ─────────────────
    raw: dict[str, float | None] = {}
    norm: dict[str, float] = {}

    # 1. Net APR
    raw["net_apr"] = apr
    norm["net_apr"] = _linear_clamp(apr, 0.0, 100.0) if apr is not None else 0.0

    # 2. Volume 24h
    raw["volume"] = vol
    norm["volume"] = _log_norm(vol, 100_000, 10_000_000) if vol is not None else 0.0

    # 3. Open Interest
    raw["oi"] = oi
    norm["oi"] = _log_norm(oi, 50_000, 5_000_000) if oi is not None else 0.0

    # 4. Risk tier
    risk_map = {"LOW": 100.0, "MED": 50.0, "HIGH": 0.0}
    raw["risk"] = risk
    norm["risk"] = risk_map.get(risk, 0.0) if risk is not None else 0.0

    # 5. Slippage estimate (volume / position_size ratio)
    raw["slippage"] = vol
    if vol is not None and vol > 0 and pos_ref > 0:
        ratio = vol / pos_ref
        norm["slippage"] = _linear_clamp(ratio, 5.0, 100.0)
    else:
        norm["slippage"] = 0.0

    # 6. Venue reliability
    v_rel = venue_rel.get(venue, 90) if venue else 0
    raw["venue"] = v_rel
    norm["venue"] = _linear_clamp(float(v_rel), 90.0, 99.0)

    # ── redistribute weight from missing factors ─────────────
    present_w = 0.0
    missing_w = 0.0
    for k in w:
        if raw.get(k) is None:
            missing_w += w[k]
        else:
            present_w += w[k]

    final_w = {}
    for k in w:
        if raw.get(k) is None:
            final_w[k] = 0.0
        elif present_w > 0:
            final_w[k] = w[k] + (w[k] / present_w) * missing_w
        else:
            final_w[k] = 0.0

    # ── weighted sum ─────────────────────────────────────────
    score = sum(norm[k] * final_w.get(k, 0) for k in norm)
    score = max(0.0, min(100.0, score))

    go_th = thresholds.get("go", 70)
    maybe_th = thresholds.get("maybe", 40)
    if score >= go_th:
        grade = "GO"
    elif score >= maybe_th:
        grade = "MAYBE"
    else:
        grade = "SKIP"

    factors = {}
    for k in norm:
        factors[k] = {
            "raw": raw.get(k),
            "normalized": round(norm[k], 1),
            "weighted": round(norm[k] * final_w.get(k, 0), 1),
        }

    return ScoreResult(score=round(score, 1), grade=grade, factors=factors)


def score_batch(opps: list[dict], cfg: dict | None = None) -> list[ScoreResult]:
    """Score a list, returning a parallel list of ScoreResults."""
    return [score_opp(o, cfg=cfg) for o in opps]
```

### Step 4 — run tests, expect pass

```
python -m pytest tests/test_arb_scoring.py -v
```

Expected: all 10 tests PASS.

### Step 5 — smoke test

```
python smoke_test.py --quiet
```

Expected: 169/169 (the new module isn't yet in smoke — that's Task 2).

### Step 6 — commit

```
git add core/arb_scoring.py tests/test_arb_scoring.py
git commit -m "feat(core): arb_scoring — 6-factor composite scoring engine with tests"
```

---

## Task 2: Config constants in `params.py` + smoke check

**Files:**
- Modify: `config/params.py:76` (`__all__` list) and append after line 421
- Modify: `smoke_test.py` (add import check)

### Step 1 — add constants to `config/params.py`

Append to `__all__` list (before the closing `]` at line 77), add these entries:

```python
    # Arb scoring (Fase B)
    "ARB_SCORE_WEIGHTS", "ARB_SCORE_THRESHOLDS", "ARB_FILTER_DEFAULTS",
    "ARB_VENUE_RELIABILITY", "ARB_POSITION_SIZE_REF",
```

Append after line 421 (end of file):

```python

# ── Fase B: Arb scoring ──────────────────────���───────────────
ARB_SCORE_WEIGHTS = {
    "net_apr": 0.30,
    "volume": 0.20,
    "oi": 0.15,
    "risk": 0.15,
    "slippage": 0.10,
    "venue": 0.10,
}
ARB_SCORE_THRESHOLDS = {"go": 70, "maybe": 40}

ARB_FILTER_DEFAULTS = {
    "min_apr": 20.0,
    "min_volume": 500_000,
    "min_oi": 0,
    "risk_max": "HIGH",
    "grade_min": "SKIP",
}

ARB_VENUE_RELIABILITY = {
    "binance": 99, "bybit": 97, "gate": 95, "bitget": 94, "bingx": 92,
    "hyperliquid": 96, "dydx": 94, "paradex": 90,
}

ARB_POSITION_SIZE_REF = 1000.0
```

### Step 2 — add smoke check for `core.arb_scoring`

Find the imports section in `smoke_test.py` where other `core.*` modules are import-checked. Add:

```python
    call("import core.arb_scoring", lambda: __import__("core.arb_scoring"))
```

### Step 3 — run smoke test

```
python smoke_test.py --quiet
```

Expected: 170/170 (or +1 from previous count).

### Step 4 — run scoring tests (verify config integration)

```
python -m pytest tests/test_arb_scoring.py -v
```

Expected: all pass (scoring now picks up params.py constants by default).

### Step 5 — commit

```
git add config/params.py smoke_test.py
git commit -m "feat(config): ARB_SCORE_WEIGHTS + filter defaults for Fase B scoring"
```

---

## Task 3: Filter bar in `_funding_scanner_screen`

**Files:**
- Modify: `launcher.py:3636` (`_funding_scanner_screen`) — insert filter bar after title block
- Modify: `launcher.py:3799` (`_funding_paint`) — add filter + SCORE column
- Modify: `tests/test_launcher_main_menu.py` — append 1 test

### Step 1 — append failing test

Append to `tests/test_launcher_main_menu.py`:

```python


def test_scanner_filter_bar_renders():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._funding_scanner_screen("dex-dex")
        app.update_idletasks()
        assert hasattr(app, "_arb_filters")
        assert "min_apr" in app._arb_filters
        assert hasattr(app, "_arb_filter_labels")
        assert len(app._arb_filter_labels) == 5
    finally:
        app._funding_alive = False
        app.destroy()
```

### Step 2 — run test, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_scanner_filter_bar_renders -v
```

Expected: FAIL — `AttributeError: 'App' object has no attribute '_arb_filters'`.

### Step 3 — add filter bar to `_funding_scanner_screen`

In `launcher.py`, find `_funding_scanner_screen`. After the `_funding_meta` label and divider line (after line 3688), insert the filter bar block:

```python
        # ── Filter bar (click-to-cycle) ─────────────────────────
        from config.params import ARB_FILTER_DEFAULTS
        self._arb_filters = dict(ARB_FILTER_DEFAULTS)
        filter_bar = tk.Frame(outer, bg=BG)
        filter_bar.pack(fill="x", padx=0, pady=(2, 0))
        self._arb_filter_bar = filter_bar

        filter_cycles = {
            "min_apr":    [5.0, 10.0, 20.0, 50.0, 100.0],
            "min_volume": [0, 100_000, 500_000, 1_000_000, 5_000_000],
            "min_oi":     [0, 50_000, 100_000, 500_000, 1_000_000],
            "risk_max":   ["HIGH", "MED", "LOW"],
            "grade_min":  ["SKIP", "MAYBE", "GO"],
        }
        self._arb_filter_cycles = filter_cycles

        def _fmt_filter(key, val):
            if key == "min_apr":
                return f"APR \u2265{val:.0f}%"
            elif key == "min_volume":
                if val >= 1_000_000:
                    return f"VOL \u2265{val/1e6:.0f}M"
                elif val >= 1_000:
                    return f"VOL \u2265{val/1e3:.0f}K"
                else:
                    return "VOL \u2265OFF"
            elif key == "min_oi":
                if val >= 1_000_000:
                    return f"OI \u2265{val/1e6:.0f}M"
                elif val >= 1_000:
                    return f"OI \u2265{val/1e3:.0f}K"
                else:
                    return "OI \u2265OFF"
            elif key == "risk_max":
                return f"RISK \u2264{val}"
            elif key == "grade_min":
                return f"GRADE \u2265{val}"
            return str(val)

        self._arb_filter_fmt = _fmt_filter
        self._arb_filter_labels: dict[str, tk.Label] = {}

        for key in ["min_apr", "min_volume", "min_oi", "risk_max", "grade_min"]:
            val = self._arb_filters[key]
            lbl = tk.Label(filter_bar, text=f" {_fmt_filter(key, val)} ",
                           font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG2,
                           cursor="hand2", padx=6)
            lbl.pack(side="left", padx=(0, 6))
            self._arb_filter_labels[key] = lbl

            def _cycle(event=None, k=key):
                cyc = self._arb_filter_cycles[k]
                cur = self._arb_filters[k]
                try:
                    idx = cyc.index(cur)
                except ValueError:
                    idx = -1
                nxt = cyc[(idx + 1) % len(cyc)]
                self._arb_filters[k] = nxt
                self._arb_filter_labels[k].configure(
                    text=f" {self._arb_filter_fmt(k, nxt)} ")
                self._funding_repaint_filtered()
            lbl.bind("<Button-1>", _cycle)

        hint = tk.Label(filter_bar, text="F:toggle", font=(FONT, 6),
                        fg=DIM2, bg=BG)
        hint.pack(side="right")

        def _toggle_filter_bar(event=None):
            if filter_bar.winfo_viewable():
                filter_bar.pack_forget()
            else:
                filter_bar.pack(fill="x", padx=0, pady=(2, 0),
                                after=self._funding_meta)
        self._kb("<Key-f>", _toggle_filter_bar)
```

### Step 4 — add `_funding_repaint_filtered` method

Insert after `_funding_paint` method (around line 3880):

```python
    def _funding_repaint_filtered(self):
        """Re-filter cached scan results with current filter state and repaint."""
        cached = getattr(self, "_funding_cached", None)
        if cached is None:
            return
        rows, arb, stats = cached
        self._funding_paint(rows, arb, stats)
```

### Step 5 — cache scan results in `_funding_paint`

At the very start of `_funding_paint` (line 3799), add:

```python
        self._funding_cached = (rows, arb, stats)
```

### Step 6 — add filtering logic + SCORE column to `_funding_paint`

In `_funding_paint`, after the line `self._funding_cached = (rows, arb, stats)` and before the `# rebuild rows` comment, insert:

```python
        # ── Apply filters ────────────────────────────────────────
        from core.arb_scoring import score_opp, score_batch
        filters = getattr(self, "_arb_filters", None)
        if filters:
            risk_order = {"LOW": 0, "MED": 1, "HIGH": 2}
            grade_order = {"GO": 0, "MAYBE": 1, "SKIP": 2}
            risk_max = risk_order.get(filters.get("risk_max", "HIGH"), 2)
            grade_min = grade_order.get(filters.get("grade_min", "SKIP"), 2)

            scored = score_batch([o.to_dict() if hasattr(o, "to_dict") else o for o in rows])
            filtered = []
            scored_filtered = []
            for o, sc in zip(rows, scored):
                apr_val = abs(o.apr) if hasattr(o, "apr") else abs(o.get("apr", 0))
                vol_val = o.volume_24h if hasattr(o, "volume_24h") else o.get("volume_24h", 0)
                oi_val = o.open_interest if hasattr(o, "open_interest") else o.get("open_interest", 0)
                risk_val = o.risk if hasattr(o, "risk") else o.get("risk", "HIGH")
                if apr_val < filters.get("min_apr", 0):
                    continue
                if vol_val < filters.get("min_volume", 0):
                    continue
                if oi_val < filters.get("min_oi", 0):
                    continue
                if risk_order.get(risk_val, 2) > risk_max:
                    continue
                if grade_order.get(sc.grade, 2) > grade_min:
                    continue
                filtered.append(o)
                scored_filtered.append(sc)
            rows = filtered
            row_scores = scored_filtered
        else:
            row_scores = score_batch([o.to_dict() if hasattr(o, "to_dict") else o for o in rows])
```

Then update the `cols` definition used by `_funding_scanner_screen` to include SCORE. In `_funding_scanner_screen`, change the cols list at line 3691:

```python
        cols = [
            ("#",       3,  "e"),
            ("SYMBOL",  10, "w"),
            ("VENUE",   12, "w"),
            ("TYPE",    4,  "w"),
            ("RATE",    12, "e"),
            ("APR",     9,  "e"),
            ("VOL",     10, "e"),
            ("RISK",    5,  "w"),
            ("SCORE",   10, "w"),
        ]
```

In `_funding_paint`, after the existing cells list for each row, append the SCORE cell. Replace the cell-building loop with:

```python
            score_r = row_scores[i - 1] if (i - 1) < len(row_scores) else None
            if score_r:
                bar = "\u2588\u2588" if score_r.score >= 70 else ("\u2588\u2591" if score_r.score >= 40 else "\u2591\u2591")
                score_fg = GREEN if score_r.grade == "GO" else (AMBER if score_r.grade == "MAYBE" else DIM2)
                score_txt = f"{bar} {score_r.score:.0f} {score_r.grade}"
            else:
                score_fg = DIM2
                score_txt = "\u2014"
            cells.append((score_txt, score_fg))
```

### Step 7 — also score arb pairs

In the arb pairs rendering section of `_funding_paint`, after `if arb:`, score each pair and append score to the line:

```python
            if arb:
                arb_scores = score_batch(arb)
                for a, sc in zip(arb, arb_scores):
                    bar = "\u2588\u2588" if sc.score >= 70 else ("\u2588\u2591" if sc.score >= 40 else "\u2591\u2591")
                    sc_fg = GREEN if sc.grade == "GO" else (AMBER if sc.grade == "MAYBE" else DIM2)
                    line = (
                        f"   {a['symbol']:8s}  "
                        f"SHORT {a['short_venue']:<11s} ({a['short_apr']:+6.1f}%)  "
                        f"\u2192  "
                        f"LONG {a['long_venue']:<11s} ({a['long_apr']:+6.1f}%)  "
                        f"net {a['net_apr']:+6.0f}%  "
                        f"{bar} {sc.score:.0f} {sc.grade}"
                    )
                    net_fg = GREEN if abs(a["net_apr"]) >= 50 else AMBER
                    tk.Label(arb_frame, text=line, font=(FONT, 8),
                             fg=net_fg, bg=BG, anchor="w").pack(fill="x")
```

### Step 8 — run test, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_scanner_filter_bar_renders -v
```

Expected: PASS.

### Step 9 — smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0.

### Step 10 — commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): filter bar + SCORE column in funding scanner"
```

---

## Task 4: Hub semaphore bullets

**Files:**
- Modify: `launcher.py:3573` (`_arb_hub_telem_update`)
- Modify: `launcher.py:3528` (`_arb_hub_scan_async`) — pass scores to telem_update
- Modify: `tests/test_launcher_main_menu.py` — append 1 test

### Step 1 — append failing test

Append to `tests/test_launcher_main_menu.py`:

```python


def test_arbitrage_hub_semaphore_colors_bullets():
    mod = _load_launcher()
    app = mod.App()
    app.withdraw()
    try:
        app._arbitrage_hub()
        # Synthetic scan result with high-scoring dex-dex pair
        stats = {"dex_online": 3, "cex_online": 5, "total": 100}

        class FakeTop:
            symbol = "BTC"
            apr = 80.0
            venue = "binance"
        top = FakeTop()
        arb_dd = [{
            "symbol": "ETH", "net_apr": 85.0,
            "short_venue": "dydx", "short_venue_type": "DEX",
            "long_venue": "hyperliquid", "long_venue_type": "DEX",
            "short_apr": 50.0, "long_apr": -35.0,
            "short_rate": 0.0003, "long_rate": -0.0002,
            "short_interval_h": 8, "long_interval_h": 1,
            "mark_price": 3200.0,
            "volume_24h_short": 8_000_000, "volume_24h_long": 5_000_000,
            "open_interest_short": 3_000_000, "open_interest_long": 2_000_000,
        }]
        arb_cd = []
        app._arb_hub_telem_update(stats, top, arb_dd, arb_cd)
        app.update_idletasks()

        rows = app._arb_hub_row_widgets
        # Row 1 = DEX-DEX — bullet should be green (high score pair)
        bullet_fg = rows[1]["bullet"].cget("fg")
        assert bullet_fg == "#00ff41", f"expected green bullet, got {bullet_fg}"
    finally:
        app.destroy()
```

### Step 2 — run test, expect fail

```
python -m pytest tests/test_launcher_main_menu.py::test_arbitrage_hub_semaphore_colors_bullets -v
```

Expected: FAIL — bullet is still AMBER (default), not green.

### Step 3 — update `_arb_hub_telem_update` to color bullets

In `launcher.py`, find `_arb_hub_telem_update` (line 3573). After the existing row population logic, add semaphore coloring at the end of the `try` block (before the `except Exception: pass`):

```python
            # ── Semaphore bullets (best score per category) ──────
            from core.arb_scoring import score_batch
            GREEN_SEM = "#00ff41"

            # Row 0 — CEX-CEX: score the top opp if available
            if top is not None:
                top_d = top.to_dict() if hasattr(top, "to_dict") else {
                    "symbol": getattr(top, "symbol", ""),
                    "venue": getattr(top, "venue", ""),
                    "apr": getattr(top, "apr", 0),
                    "volume_24h": getattr(top, "volume_24h", 0),
                    "open_interest": getattr(top, "open_interest", 0),
                    "risk": getattr(top, "risk", "HIGH"),
                }
                from core.arb_scoring import score_opp
                cex_sc = score_opp(top_d)
                if cex_sc.grade == "GO":
                    rows[0]["bullet"].configure(fg=GREEN_SEM)
                elif cex_sc.grade == "MAYBE":
                    rows[0]["bullet"].configure(fg=AMBER)
                else:
                    rows[0]["bullet"].configure(fg=DIM)

            # Row 1 — DEX-DEX
            if arb_dd:
                dd_scores = score_batch(arb_dd)
                best_dd = max(dd_scores, key=lambda s: s.score)
                if best_dd.grade == "GO":
                    rows[1]["bullet"].configure(fg=GREEN_SEM)
                elif best_dd.grade == "MAYBE":
                    rows[1]["bullet"].configure(fg=AMBER)
                else:
                    rows[1]["bullet"].configure(fg=DIM)

            # Row 2 — CEX-DEX
            if arb_cd:
                cd_scores = score_batch(arb_cd)
                best_cd = max(cd_scores, key=lambda s: s.score)
                if best_cd.grade == "GO":
                    rows[2]["bullet"].configure(fg=GREEN_SEM)
                elif best_cd.grade == "MAYBE":
                    rows[2]["bullet"].configure(fg=AMBER)
                else:
                    rows[2]["bullet"].configure(fg=DIM)
```

### Step 4 — run test, expect pass

```
python -m pytest tests/test_launcher_main_menu.py::test_arbitrage_hub_semaphore_colors_bullets -v
```

Expected: PASS.

### Step 5 — run full test suite

```
python -m pytest tests/test_launcher_main_menu.py tests/test_arb_scoring.py -v
```

Expected: all pass (modulo known Tcl flake).

### Step 6 — smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0.

### Step 7 — commit

```
git add launcher.py tests/test_launcher_main_menu.py
git commit -m "feat(launcher): hub semaphore bullets colored by best arb score"
```

---

## Task 5: Final validation + merge

**Files:**
- No new code changes

### Step 1 — run full test suite

```
python -m pytest tests/test_arb_scoring.py tests/test_launcher_main_menu.py -v
```

Expected: all green.

### Step 2 — smoke test

```
python smoke_test.py --quiet
```

Expected: exit 0.

### Step 3 — AST parse

```
python -c "import ast; ast.parse(open('launcher.py', encoding='utf-8').read()); print('OK')"
python -c "import ast; ast.parse(open('core/arb_scoring.py', encoding='utf-8').read()); print('OK')"
```

Expected: OK, OK.

### Step 4 — manual UI walkthrough

Run `python launcher.py` and verify:

1. Splash → main menu → ARBITRAGE → hub renders with 3 rows.
2. Within ~5s, hub bullets change color based on scan scores (green/amber/dim).
3. Click DEX-DEX → scanner renders with filter bar at top.
4. Filter bar shows: `[APR ≥20%]  [VOL ≥500K]  [OI ≥OFF]  [RISK ≤HIGH]  [GRADE ≥SKIP]`.
5. Click `[APR ≥20%]` → cycles to `[APR ≥50%]` → table re-renders with fewer rows.
6. Click again → `[APR ≥100%]` → even fewer rows.
7. Click `[GRADE ≥SKIP]` → cycles to `[GRADE ���MAYBE]` → SKIP-graded rows disappear.
8. Table has SCORE column showing `██ 82 GO` / `█░ 55 MAYBE` / `░░ 12 SKIP` style.
9. Arb pairs section also shows scores.
10. Press `F` → filter bar hides. Press `F` again → filter bar reappears.
11. Press `R` → manual refresh works, filters persist.
12. ESC → back to hub. Bullets still colored.
13. Press `X` → CEX-DEX scanner. Same filter bar + SCORE column.

---

## Verification Checklist

- [ ] `python -m pytest tests/test_arb_scoring.py` — all 10 tests pass
- [ ] `python -m pytest tests/test_launcher_main_menu.py` — all tests pass (modulo Tcl flake)
- [ ] `python smoke_test.py --quiet` — exit 0
- [ ] Manual UI walkthrough (13 steps) completed
- [ ] Scoring engine returns correct grades for known inputs
- [ ] Filter bar cycles values on click
- [ ] SCORE column renders with colored mini-bars
- [ ] Hub bullets change color based on best scan score
- [ ] No modifications to `core/funding_scanner.py` or `engines/arbitrage.py`
- [ ] `F` key toggles filter bar visibility
- [ ] Filters persist across manual refresh (R key)
