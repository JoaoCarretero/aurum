# Arbitrage Filters + "Worth It?" Scoring — Jane Street Style

> **Fase B** of the arbitrage hub redesign backlog.
> Predecessor: Fase A (hub UI polish, merged 2026-04-12).

## Goal

Add a composite scoring engine and interactive filters to the arbitrage
scanner, so the user can instantly see which opportunities are worth
pursuing (GO/MAYBE/SKIP) and filter noise out of the scanner table.
Secondary: surface a semaphore badge on the hub rows.

## Non-Goals

- No changes to `engines/arbitrage.py` or execution logic.
- No changes to `core/funding_scanner.py` internals (scoring is a layer on top).
- No new venues (that's Fase C).
- No new arb types (that's Fase D).

---

## Architecture

Three components:

| Component | File | Role |
|-----------|------|------|
| Scoring engine | `core/arb_scoring.py` (new) | Pure function: opp/pair dict in, score dict out |
| Config | `config/params.py` | Weights, thresholds, defaults, venue reliability |
| UI | `launcher.py` | Filter bar in scanner + semaphore in hub |

Data flow:

```
FundingScanner.scan() → [FundingOpp, ...]
                          ↓
                    arb_scoring.score_opp(opp, cfg) → {score, grade, factors}
                          ↓
                    _funding_scanner_screen renders table + SCORE column
                    _arb_hub_telem_update colors hub bullets
```

---

## 1. Scoring Engine — `core/arb_scoring.py`

### Public API

```python
@dataclass
class ScoreResult:
    score: float        # 0.0 – 100.0
    grade: str          # "GO" | "MAYBE" | "SKIP"
    factors: dict       # per-factor breakdown {name: {raw, normalized, weighted}}

def score_opp(opp: dict, cfg: dict | None = None) -> ScoreResult:
    """Score a single FundingOpp or arb_pair dict."""

def score_batch(opps: list[dict], cfg: dict | None = None) -> list[ScoreResult]:
    """Score a list, returning parallel list of ScoreResults."""
```

`cfg` defaults to values from `config.params` if None.

### Six Factors

| # | Factor | Input field(s) | Normalization | Default weight |
|---|--------|---------------|---------------|----------------|
| 1 | Net APR | `apr` or `net_apr` | Linear clamp: 0% → 0, ≥100% → 100 | 0.30 |
| 2 | Volume 24h | `volume_24h` | Log scale: <100k → 0, ≥10M → 100 | 0.20 |
| 3 | Open Interest | `open_interest` | Log scale: <50k → 0, ≥5M → 100 | 0.15 |
| 4 | Risk tier | `risk` | LOW=100, MED=50, HIGH=0 | 0.15 |
| 5 | Slippage est. | `volume_24h / position_size_ref` | Ratio ≥100x → 100, ≤5x → 0, linear between | 0.10 |
| 6 | Venue reliability | venue name → uptime lookup | ≥99% → 100, ≤90% → 0, linear between | 0.10 |

Final score = Σ (normalized_i × weight_i). Weights MUST sum to 1.0;
the function normalizes them if they don't.

### Grade Thresholds

| Grade | Condition | Color (Tk) |
|-------|-----------|-----------|
| GO | score ≥ 70 | `#00ff41` (GREEN) |
| MAYBE | score ≥ 40 | AMBER (`#ffb000`) |
| SKIP | score < 40 | DIM (`#555555`) |

### Log normalization detail

For volume and OI, use `log10` mapping:

```python
def _log_norm(value, floor, ceil):
    """0 if value <= floor, 100 if value >= ceil, linear in log10 between."""
    if value <= floor:
        return 0.0
    if value >= ceil:
        return 100.0
    return (math.log10(value) - math.log10(floor)) / (math.log10(ceil) - math.log10(floor)) * 100.0
```

Volume: floor=100_000, ceil=10_000_000.
OI: floor=50_000, ceil=5_000_000.

### Missing data handling

- If a field is missing or None, that factor scores 0 and its weight is
  redistributed proportionally among the remaining factors.
- If ALL fields are missing, score = 0, grade = "SKIP".

### Arb pair scoring

For arb pairs (dicts from `scanner.arb_pairs()`), use `net_apr` for the
APR factor. Volume and OI use the *minimum* of the two legs (weakest link).
Risk uses the *worst* of the two venues. Venue reliability uses the
*minimum* of the two venues.

---

## 2. Config — `config/params.py`

Add these constants at the end of the arbitrage section:

```python
# ── Fase B: Arb scoring ──────────────────────────────────────
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
    "risk_max": "HIGH",       # "LOW", "MED", or "HIGH"
    "grade_min": "SKIP",      # "GO", "MAYBE", or "SKIP"
}

ARB_VENUE_RELIABILITY = {
    "binance": 99, "bybit": 97, "gate": 95, "bitget": 94, "bingx": 92,
    "hyperliquid": 96, "dydx": 94, "paradex": 90,
}

ARB_POSITION_SIZE_REF = 1000.0  # USD reference for slippage estimation
```

These are exported via `__all__` / `from config.params import *` as usual.

---

## 3. UI — Filter Bar in `_funding_scanner_screen`

### Layout

Above the existing table, below the header:

```
 [APR ≥20%]  [VOL ≥500K]  [OI ≥0]  [RISK ≤HIGH]  [GRADE ≥SKIP]     F:toggle
```

Each bracket is a `tk.Label` with `cursor="hand2"`. Click cycles through
predefined values:

| Filter | Cycle values |
|--------|-------------|
| APR | 5, 10, 20, 50, 100 |
| VOL | 0, 100K, 500K, 1M, 5M |
| OI | 0, 50K, 100K, 500K, 1M |
| RISK | HIGH, MED, LOW |
| GRADE | SKIP, MAYBE, GO |

### Behavior

- Filter bar visible by default. Tecla `F` toggles show/hide.
- On any filter change: re-filter the cached scan results and re-render
  the table. No new API call — filtering is client-side.
- Filter state stored in `self._arb_filters: dict` on the App instance.
  Initialized from `ARB_FILTER_DEFAULTS`. Persists for the session (not
  saved to disk).

### SCORE column

Add a new column to the scanner table, rightmost position:

```
 #  SYMBOL  VENUE       TYPE  RATE      APR    VOL(24h)  RISK  SCORE
 1  BTC     binance     CEX   +0.010%   36.5%  $42.1M    LOW   ██ 82 GO
 2  ETH     hyperliquid DEX   +0.005%   43.8%  $8.2M     LOW   ██ 71 GO
 3  SOL     dydx        DEX   -0.003%   26.3%  $1.1M     MED   █░ 55 MAYBE
 ...
```

SCORE column shows: mini-bar (2-char block), numeric score, grade text.
Color: green for GO, amber for MAYBE, dim for SKIP.

### Arb pairs table

The arb pairs section (below the main table) also gets a SCORE column,
using the pair scoring logic.

---

## 4. UI — Semaphore on Hub Rows

In `_arb_hub_telem_update`, after receiving scan results:

1. Score all opps/pairs per category (cex-cex, dex-dex, cex-dex).
2. Take the best score per category.
3. Set the row bullet `●` color:
   - Best score ≥ 70 → GREEN (`#00ff41`)
   - Best score ≥ 40 → AMBER (existing `AMBER` constant)
   - Best score < 40 or no data → DIM

This requires `_arb_hub_telem_update` to call `score_batch` on the
arb pairs it already receives. Minimal change — 5-10 lines.

---

## 5. Files Changed

| File | Action | Lines est. |
|------|--------|-----------|
| `core/arb_scoring.py` | **New** | ~120 |
| `config/params.py` | Modify (append constants) | +20 |
| `launcher.py` | Modify (`_funding_scanner_screen` + `_arb_hub_telem_update`) | +80 |
| `tests/test_arb_scoring.py` | **New** | ~80 |
| `smoke_test.py` | Modify (add import check) | +3 |

Total: ~300 lines new code.

---

## 6. Testing Strategy

### Unit tests (`tests/test_arb_scoring.py`)

- `test_score_opp_all_fields_present` — known input → expected score range
- `test_score_opp_missing_volume` — weight redistribution
- `test_score_opp_all_missing` — score=0, grade=SKIP
- `test_grade_thresholds` — boundary cases (39.9→SKIP, 40→MAYBE, 69.9→MAYBE, 70→GO)
- `test_score_batch_parallel` — list in, parallel list out
- `test_arb_pair_weakest_link` — pair uses min volume of two legs
- `test_weights_normalize` — weights that don't sum to 1.0 get normalized
- `test_log_norm_boundaries` — floor, ceil, mid values

### Smoke test

- `import core.arb_scoring` — no crash
- `score_opp({})` returns ScoreResult with score=0

### UI tests (in `tests/test_launcher_main_menu.py`)

- `test_scanner_filter_bar_renders` — filter labels exist after entering scanner
- `test_scanner_score_column_present` — SCORE header in table

---

## 7. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Scoring feels arbitrary | Weights are in params.py, user-tunable. Factors are transparent (breakdown dict). |
| Filter cycles are annoying on mobile/touch | Not applicable — desktop Tk only. |
| Volume/OI data missing for some venues | Missing data → score 0 for that factor, weight redistributed. Graceful degradation. |
| Performance on large scan results | score_opp is pure math, ~0.1ms per opp. 1000 opps = 100ms. Fine. |
