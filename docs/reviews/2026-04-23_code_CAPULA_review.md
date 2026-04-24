# CAPULA — Code Review (WORKFLOW TIPO 2)

- **Artifact**: `engines/capula.py` + `tests/test_capula.py` + 1-line registry entry in `config/engines.py`
- **Branch**: `experiment/capula` (worktree `.worktrees/capula`)
- **Commits**: `bdae9c6` (engine) + `4d498e1` (registry)
- **Date**: 2026-04-23
- **Reviewer**: ARBITER
- **Ticket**: AUR-9 (code review gate)

---

## Verdict: ITERATE

Engine is architecturally clean, does not touch protected files, 28/28 tests green, and style matches mature engines (PHI/GRAHAM) well. Blocked from merge by one **MAJOR** correctness issue around funding accrual cadence that, under the repo's default `INTERVAL="15m"`, silently inflates PnL by ~32×. Once that is guarded or corrected, engine is SHIP-ready at research stage.

---

## File inventory (git diff 4bf9883..HEAD)

| File | Lines | Nature |
|---|---|---|
| `engines/capula.py` | +679 | NEW — engine module |
| `tests/test_capula.py` | +388 | NEW — unit tests |
| `config/engines.py` | +1 | Registry entry only |

No other files touched. **No protected file violations.**

---

## Criterion 1 — Padrão AURUM ★ 5/5

Structurally indistinguishable from `engines/phi.py` and `engines/graham.py`:
- Module header block with hypothesis / falsification / discipline sections — matches PHI.
- Dataclass `CapulaParams` with typed defaults — matches PHI/GRAHAM/JUMP.
- Section banners (`# ═══...`) at same cadence as PHI.
- Standard imports (`argparse, json, logging, sys, defaultdict, dataclass, datetime, Path, Optional, numpy, pandas`) in the same order as PHI.
- UTF-8 stdout reconfig preamble — matches PHI (lines 52-56 vs PHI lines 39-43).
- `scan_symbol(df, symbol, params, initial_equity) → (trades, vetos)` signature — matches AURUM convention.
- `run_backtest(all_dfs, params, initial_equity) → (trades, vetos, per_sym)` — matches convention.
- `compute_summary(trades, initial_equity) → dict` — matches KEPOS/PHI (verified in tests/test_capula.py:378-389 where `win_rate` rounding matches kepos).
- Two loggers (`log` = engine, `_tl` = trades) — matches PHI.
- CLI banner, per-symbol tables, `save_run` with `trades.json` + `summary.json` — matches PHI.

No stylistic deviations.

---

## Criterion 2 — Protected Files ★ 5/5 (no violations)

Protected file list per AGENTS.md + ticket expansion:
- `core/indicators.py` — NOT TOUCHED ✓
- `core/signals.py` — NOT TOUCHED ✓
- `core/portfolio.py` — NOT TOUCHED ✓
- `core/hawkes.py` — NOT TOUCHED ✓
- existing `engines/*.py` (kepos, graham, phi, …) — NOT TOUCHED ✓
- `backtest.py`, `multistrategy.py`, `live.py`, `launcher.py` — NOT TOUCHED ✓

`config/engines.py` was modified (+1 line, pure registry append), which is expected per ticket ("integração automática via registry"). Not in protected list.

---

## Criterion 3 — Core Reuse ★ 4/5

Reuses rather than reimplements:
- `core.sentiment.fetch_funding_rate` via the thin `fetch_funding_history` wrapper (line 473).
- `core.data.fetch_all` + `core.data.validate` in `_build_dataset` (lines 598-608).
- `core.fs.atomic_write` for run persistence (line 70; `core.fs` is a compat shim to `core.ops.fs` verified at core/fs.py:1-7).
- `config.params` for cost constants (COMMISSION, SLIPPAGE, SPREAD, LEVERAGE, ACCOUNT_SIZE) — SSOT respected.

Minor: z-score (line 183) is computed inline rather than centralised. No `zscore` helper exists in `core/indicators.py` to reuse, so inline is acceptable — same pattern as other engines do small rolling-window math locally. Not a reimplementation of an existing indicator.

Minor style nit: PHI imports `from core.ops.fs import atomic_write` directly, CAPULA imports `from core.fs import atomic_write` via the compat shim. Both work; PHI's direct path is slightly preferred for clarity. **MINOR**.

---

## Criterion 4 — Codex Anti-patterns ★ 4/5

### Clean ✓
- **No `center=True` in rolling windows.** `compute_features` uses `rolling(z_window, min_periods=…)` without center — correct.
- **No lookahead in z-score.** `compute_features` (engines/capula.py:181-184): `roll_mean = fr.rolling(w, min_periods).mean().shift(1)` and same for std, then `z = (fr - roll_mean) / roll_std`. The comparison is *current value vs history up to previous bar* — no peek at future. Verified by `test_compute_features_zscore_nan_during_warmup`.
- **Entry bar has no exit.** `resolve_exit` (engines/capula.py:235-236) explicitly returns None on `t <= trade["entry_idx"]` — stops the trivial "close same bar for free carry" exploit. Covered by `test_resolve_exit_not_on_entry_bar`.
- **Entry bar has no funding accrual.** `scan_symbol` accrues *before* checking exit/entry inside each `t` loop, and the new-entry branch re-initializes `accrued_funding = 0.0` (line 351). First accrual happens on `t+1`. Realistic.
- **Sign-match guard** (`decide_direction` lines 214-218): refuses to enter when `z` sign contradicts current `rate` sign — kills one-bar flip noise. Tested.
- **Kill-switch** on both entry and exit paths (lines 211, 240).
- **28/28 tests** cover: sizing edge cases (NaN, negative, zero-fraction), PnL sign matrix (short/long × positive/negative funding + wrong-side), cost linearity, z-score warmup NaN, missing-column abstention, all 4 exit precedences, entry-bar no-exit, scan with flat funding = 0 trades, scan with oscillating funding = trades with full schema, backtest aggregation, summary with empty and non-empty trade lists.

### MAJOR — per-bar funding accrual ignores bar↔funding cadence mismatch
`scan_symbol` accrues `_period_funding_pnl(direction, notional, rate)` on **every** bar where a position is open (lines 281-290). `rate` comes from the forward-filled `funding_rate` column produced by `join_funding_to_candles` (line 497, `merge_asof(..., direction="backward")`). Funding is published every 8h on Binance; candles default to 15m (`config/params.py:182-183`: `ENTRY_TF = "15m"`, `INTERVAL = ENTRY_TF`).

Net effect:
- Default invocation `python engines/capula.py --days 90` runs at 15m.
- For each 8h funding event, the rate is forward-filled onto 32 consecutive 15m candles.
- Scan accrues `rate × notional` on all 32 → PnL inflated by ~32×.
- `CapulaParams.funding_interval_h = 8.0` exists (line 102) but is **never referenced** anywhere in the code — declared intent, missing implementation.

The entire test suite uses 8h bars (`_df_with_funding(freq="8h")`), so this is invisible to tests.

**Remediation options**:
1. Preferred: scale per-bar PnL by `(bar_minutes / (funding_interval_h × 60))` so each bar only accrues its fractional share, OR
2. Only accrue on bars where the underlying funding timestamp actually changed (detect edge via `funding_rate.diff() != 0 | new publication timestamp`), OR
3. Hard-guard `scan_symbol` to require `bar_freq == funding_interval_h` and raise on mismatch, OR
4. Down-sample the dataset to 8h before feeding into `scan_symbol`.

Without at least a guard, any out-of-sample backtest at 15m/1h will report a fake positive edge and mislead the SHIP/KILL decision the spec's falsification rule hinges on.

### MAJOR — `fetch_funding_history` does not pass `end_time_ms`
Line 473-474: `fetch_funding_rate(symbol, limit=limit)`. `core.sentiment.fetch_funding_rate` supports `end_time_ms` explicitly to prevent look-ahead in backtests (docstring at core/sentiment.py:173-178: *"Without it, the API returns the most recent `limit` rates ending NOW, introducing look-ahead."*).

For a live run or a *fresh* warmup this is fine. For a backtest over an old date range, the engine will fetch the latest N funding events and `merge_asof(backward)` will return NaN for candles older than the funding window, making those candles abstain. So the practical effect is **silent data-gap / missing-history** rather than true forward look-ahead — but it breaks reproducibility (rerun tomorrow, different rates joined) and violates the stated discipline in the spec.

**Remediation**: derive `end_time_ms` from the candle DataFrame's max time and pass through; also lift `limit` ceiling so full scan range is covered.

### MINOR — dead parameter
`CapulaParams.funding_interval_h` (line 102) is declared and defaulted but referenced nowhere. Either wire it into the accrual scaling (see Major #1) or remove.

### MINOR — silent `pragma: no cover` on network path
Line 476 marks the `except Exception` around `fetch_funding_rate` as `pragma: no cover` — acceptable for a network boundary, but the fallthrough returns `None` and upstream `join_funding_to_candles` then short-circuits to "no `funding_rate` column" — which then causes `scan_symbol` to abstain cleanly. Worth a log.warning at the orchestration layer (`_build_dataset`) so the operator knows the scan will produce zero trades, not just an empty result.

---

## Criterion 5 — Integração Automática ★ 5/5

Registry entry (config/engines.py:22) follows PHI pattern exactly:
```python
"capula": {"script": "engines/capula.py", "display": "CAPULA",
           "desc": "Funding-rate carry — …", "module": "BACKTEST",
           "stage": "research", "sort_weight": 82, "live_ready": False}
```
- `stage="research"` + `live_ready=False` — matches PHI (stage="research", live_ready=False). Correct for pre-OOS engines.
- `sort_weight=82` between PHI (78) and janestreet (90) — reasonable.
- Launcher `SCRIPT_TO_KEY` discovery picks this up without further changes.
- No modification of `aurum_cli.py`, `FROZEN_ENGINES`, or `ENGINE_INTERVALS` — matches anti-overfit discipline (deferred until OOS validation).

No manual integration step required.

---

## Criterion 6 — Test Coverage ★ 4/5

**Strong coverage**:
- All sizing primitives: default, bad inputs (NaN/negative/zero), Kelly>1 clamp.
- PnL sign matrix: short/long × positive/negative funding × correct-side/wrong-side.
- Cost linearity.
- Feature NaN warmup + missing-column behavior.
- `decide_direction`: threshold, kill-switch, sign-mismatch, NaN.
- `resolve_exit`: reversion, max_hold, kill_switch, no-exit-on-entry-bar, no-exit-in-band.
- `scan_symbol`: empty df (too_few_bars veto), flat funding (no trades), oscillating funding (trades with required schema), missing funding column (abstention).
- `run_backtest`: multi-symbol aggregation.
- `compute_summary`: empty + non-empty.

**Gaps (MINOR)**:
- No test of the **bar↔funding cadence mismatch** (the MAJOR above). Adding a regression test — synthetic 15m candles with 8h funding ffilled — would have caught it.
- No test exercising `join_funding_to_candles` directly (the forward-fill path).
- No test of `fetch_funding_history` with mocked `core.sentiment` (network boundary — acceptable skip).
- No test of `save_run` / JSON round-trip (`_trades_to_serializable` handles Timestamp conversion — low risk but untested).

---

## Merge path recommendation

**ITERATE — one tightening loop required before merge.**

Required before SHIP:
1. **[MAJOR]** Fix or guard the per-bar funding accrual vs funding-cadence mismatch. Minimum acceptable: hard-assert `bar_freq == funding_interval_h` at `scan_symbol` entry and raise with an actionable error. Preferred: proper fractional scaling so any bar resolution works.
2. **[MAJOR]** Plumb `end_time_ms` through `fetch_funding_history` from the dataset build path so backtest runs are reproducible against past periods.
3. **[MINOR]** Remove dead `funding_interval_h` or wire it into #1.
4. **[MINOR]** Add `log.warning` in `_build_dataset` when a symbol returns `None` funding (explicit abstention signal for operators).
5. **[MINOR, optional]** Add one regression test with 15m bars + 8h funding proving per-bar-notional correctness.

After those, engine can merge into main as research-stage, pending OOS validation per the spec's falsification criteria (Sharpe vs shuffled-funding baseline on bluechip perps, |z| ≥ 2).

No issue is a protected-file violation; no issue blocks KILL. The engine's architecture, style, and test discipline are solid — this is a correctness tightening, not a rewrite.

---

## Scorecard

| Criterion | Score |
|---|---|
| 1. Padrão AURUM | 5/5 |
| 2. Protected Files | 5/5 |
| 3. Core Reuse | 4/5 |
| 4. Codex Anti-patterns | 4/5 |
| 5. Integração Automática | 5/5 |
| 6. Test Coverage | 4/5 |
| **Overall** | **ITERATE** |

---

*Reviewed by ARBITER at 2026-04-23. Worktree left untouched (read-only review).*
