# CAPULA — Code Re-Review (WORKFLOW TIPO 2, post-iterate)

- **Artifact**: `engines/capula.py` + `tests/test_capula.py`
- **Branch**: `experiment/capula` (worktree `.worktrees/capula`)
- **Pre-iterate HEAD**: `4d498e1` (reviewed in AUR-9)
- **Post-iterate HEAD**: `8b2a189`
- **Commits under review** (AUR-10):
  - `cf83235` fix(engines): CAPULA cadence scaling — MAJOR 1
  - `07d99d1` fix(engines): CAPULA end_time_ms on funding fetch — MAJOR 2
  - `8b2a189` chore(engines): CAPULA minor cleanups — MINOR 2
- **Date**: 2026-04-23
- **Reviewer**: ARBITER
- **Ticket**: AUR-11 (re-review gate)

---

## Verdict: SHIP

All four AUR-9 items (2 MAJOR + 2 non-regression MINORs) are resolved. The cadence-scaling regression test is tight and encodes exactly the defect path flagged in AUR-9. 29/29 tests green. No protected file touched in AUR-10 commits. Engine may merge `experiment/capula → main` at research stage, pending OOS validation per the spec's falsification criteria.

Recommendation: **merge to main** (human executes).

---

## Status of AUR-9 findings

| AUR-9 item | Status | Evidence |
|---|---|---|
| MAJOR 1 — per-bar accrual ignores bar↔funding cadence | **RESOLVED** | `cf83235` — `_infer_bar_minutes` + `funding_scale` + regression test |
| MAJOR 2 — `fetch_funding_history` without `end_time_ms` | **RESOLVED** | `07d99d1` — param threaded, `_build_dataset` anchors to last candle |
| MINOR 1 — dead `funding_interval_h` param | **RESOLVED** | wired into `funding_scale` in `cf83235`, commented |
| MINOR 2 — import via `core.fs` shim | **RESOLVED** | `8b2a189` — now `from core.ops.fs import atomic_write`, matches PHI |
| MINOR 3 — missing 15m/8h regression test | **RESOLVED** | `test_scan_symbol_scales_funding_by_bar_cadence_15m_vs_8h` |
| MINOR 4 — log.warning on `None` funding | **RESOLVED** | `_build_dataset` now logs warning per symbol (commit `07d99d1`) |

---

## Verification detail

### MAJOR 1 — cadence scaling (commit `cf83235`)

- **Implementation**: `_infer_bar_minutes(df, params)` (engines/capula.py:260-281) computes median of `time.diff()` in minutes, falls back to `_TF_MINUTES[params.interval]` with default 15. Robust to single-row / missing-column cases.
- **Placement**: `funding_scale` is computed **ONCE before the loop** (engines/capula.py:312-320), not per-bar. Zero performance penalty. ✓
- **Application**: applied in the accrual branch via `_period_funding_pnl(...) * funding_scale` (engines/capula.py:331). Single multiplication, correct location (only when a trade is open). ✓
- **Matched-cadence invariant**: for 8h bars + 8h funding, `bar_minutes = 480`, `funding_interval_min = 480`, `funding_scale = 1.0` — existing 8h-based tests (sizing, PnL-sign-matrix, oscillating scan) are unaffected, confirmed by 29/29 green including pre-existing tests.
- **Fractional case**: for 15m bars + 8h funding, `funding_scale = 15/480 = 1/32`, matching the intended correction.
- **Regression test** (`test_scan_symbol_scales_funding_by_bar_cadence_15m_vs_8h`, tests/test_capula.py:398-442):
  - Synthetic 960-bar (15m) dataset with a funding cycle forward-filled across 32-bar blocks simulating ffilled 8h publishes.
  - Generates ≥1 trade on the engineered cycle and asserts `abs(tr["gross_funding_pnl"]) < unscaled_cap / 10` per trade.
  - **Pre-fix behavior** would produce `gross_funding_pnl ≈ unscaled_cap`, failing the `< unscaled_cap/10` assertion; post-fix produces ~1/32 of that, passing comfortably — test is a true regression guard.
  - Coverage scope: one cadence pair (15m/8h). AUR-9 asked for a single regression — bar met. Additional cadence parameterisation (1h, 4h) is nice-to-have, not blocking.

### MAJOR 2 — end_time_ms (commit `07d99d1`)

- **Signature extension**: `fetch_funding_history(symbol, limit=500, end_time_ms: Optional[int] = None)` (engines/capula.py:503-505) — optional with backward-compatible default. ✓
- **Pass-through**: `fetch_funding_rate(symbol, limit=limit, end_time_ms=end_time_ms)` (engines/capula.py:524-525) — plumbs through to the underlying core.sentiment API. ✓
- **Anchor**: `_build_dataset` derives `end_time_ms` from `df["time"].iloc[-1]` in ns→ms conversion (engines/capula.py:657-660). Correct, deterministic, and guards missing `time` column / empty df via the `if "time" in df.columns and len(df)` check. ✓
- **Operator visibility on abstention**: `log.warning("%s: funding fetch returned None — symbol will abstain (missing funding_rate column)", sym)` (engines/capula.py:668-672). Breaks the silent-abstention path flagged in AUR-9 MINOR 4. ✓
- **Live/fresh callers**: omit `end_time_ms` → preserves "most recent N" behavior. No regression for warmup/live paths.

### MINOR 2 — core.ops.fs import (commit `8b2a189`)

- Single-line change: `from core.fs import atomic_write` → `from core.ops.fs import atomic_write`. Matches PHI, GRAHAM, KEPOS direct import style. No behavioral change (same underlying function — `core.fs` was a shim). ✓

---

## Criterion 7 — Padrão AURUM (new commits only)

- Docstrings on `_infer_bar_minutes` and the updated `scan_symbol` / `fetch_funding_history` include AUR-10 ticket breadcrumbs ("AUR-10 MAJOR 1/2") — traceable, consistent.
- Inline comments reference the ticket rather than over-explaining. Matches repo convention (git-blame lookup flow).
- `funding_interval_h` field now has a descriptive comment preserving the field's purpose (prevents future "looks unused, let me drop it" mistakes). Idiomatic.
- Section-banner discipline intact (no new `# ═══` headers introduced unnecessarily; one new helper lives inside the existing scan section).
- No stylistic drift.

## Criterion 8 — Protected files (re-verified)

`git diff 4d498e1..8b2a189 --stat`:
```
 engines/capula.py    | 81 +++++++++++
 tests/test_capula.py | 54 +++++++++++++
```
Zero touches to:
- `core/*` (indicators, signals, portfolio, hawkes, sentiment, data, ops/*, params) ✓
- existing `engines/*.py` (kepos, graham, phi, jump, ornstein, …) ✓
- `backtest.py`, `multistrategy.py`, `live.py`, `launcher.py`, `aurum_cli.py`, `config/engines.py` ✓

**No protected file violations.** Clean.

## Criterion 6 — Side-effects on existing tests

28 pre-existing tests (now 29 with regression) continue to pass unchanged. The matched-cadence invariant (`funding_scale = 1.0` when `bar_minutes == funding_interval_h × 60`) is the mechanism that preserves behavior — verified empirically by the green run on pre-existing 8h-based fixtures.

No test ajustado post-hoc (I re-read the test diff: only additions, zero modifications to existing test bodies). ✓

---

## Residual / out-of-scope notes (non-blocking)

1. **Cadence parameterisation for the regression test**: the test covers 15m↔8h. Extending to 1h↔8h / 4h↔8h would harden the scaling against venues with different funding cadences (Bybit 1h, dYdX 1h). Not blocking — current test encodes the defect path faithfully.
2. **`_infer_bar_minutes` edge case**: if a dataframe has exactly one row and no usable `time` diff, the function falls back to `_TF_MINUTES.get(params.interval, 15)`. If `params.interval` is a custom string not in `_TF_MINUTES` (e.g. `"2h"`), it silently defaults to 15. Low risk — `scan_symbol` requires at least `z_window` bars before any accrual happens, so the 1-row case cannot produce a trade. Worth a future assertion but not now.
3. **Network-boundary test for `fetch_funding_history(end_time_ms=...)`**: still uncovered (intentionally, per AUR-9 — network boundary). OK.

All three are captured for future hardening; none should block merge.

---

## Scorecard (re-review)

| Criterion | Score |
|---|---|
| 1. Padrão AURUM | 5/5 |
| 2. Protected Files | 5/5 |
| 3. Core Reuse | 5/5 *(up from 4/5 — shim-routing fixed)* |
| 4. Codex Anti-patterns | 5/5 *(up from 4/5 — cadence inflation fixed, reproducibility restored)* |
| 5. Integração Automática | 5/5 |
| 6. Test Coverage | 5/5 *(up from 4/5 — regression added)* |
| **Overall** | **SHIP** |

---

## Merge path

**SHIP — merge `experiment/capula → main`** (human executes). No further iterate required.

Post-merge, engine carries `stage="research"`, `live_ready=False`; next gate is OOS validation per CAPULA spec falsification criteria (Sharpe vs shuffled-funding baseline on bluechip perps, |z| ≥ 2). That is a separate ticket.

---

*ARBITER — AUR-11 | 2026-04-23*
