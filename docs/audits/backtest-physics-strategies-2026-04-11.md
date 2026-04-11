# Backtest Physics Audit — per-strategy (2026-04-11)

**Generated:** 2026-04-11
**Scope:** All 7 strategies in `SUB_MENUS` + RENAISSANCE (dependency of MILLENNIUM).
**Prior audit:** `docs/audits/backtest-physics-core-2026-04-10.md` (the shared core: `engines/backtest.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`, `core/htf.py`).

This document extends the core audit with a per-strategy layer. Each strategy section applies the L1-L12 invariant checklist to **its own decision flow** — things the shared-core audit cannot cover because they live inside the strategy-specific scan loop.

Invariants (from the master plan):

| # | Invariant | Severity |
|---|---|---|
| L1 | No look-ahead in decision features | CRÍTICO |
| L2 | Execution delay: order at `idx` fills `open[idx+1]` | CRÍTICO |
| L3 | Fees applied on both legs | ALTO |
| L4 | Slippage applied on entry + exit | ALTO |
| L5 | Funding rate accounted with correct sign | ALTO |
| L6 | Aggregate notional ≤ account × leverage | ALTO |
| L7 | Liquidation is path-dependent (inside label_trade) | MÉDIO |
| L8 | Indicators causal (no negative shift) | CRÍTICO |
| L9 | Warmup: loop starts at min_idx ≥ warmup | MÉDIO |
| L10 | MTF alignment without ffill look-ahead | ALTO |
| L11 | Stop/target geometry coherent | ALTO |
| L12 | Symbol universe free of survivorship bias | INFO |

Statuses: `✓ PASS` · `⚠️ SMELL` · `✗ FAIL` · `n/a` · `inherit` (inherited from core audit)

---

## Summary table

| Strategy | Main file | L1 | L2 | L3 | L4 | L5 | L6 | L7 | L8 | L9 | L10 | L11 | L12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **CITADEL**     | `engines/backtest.py`      | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ fixed | ✓ fixed | ✓ | ✓ | ✓ | ✓ | n/a |
| **JUMP**        | `engines/mercurio.py`      | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ **fixed (material)** | ✓ inherit | ✓ | ✓ | n/a | ✓ | n/a |
| **BRIDGEWATER** | `engines/thoth.py`         | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ fixed | ✓ inherit | ✓ | ✓ | n/a | ✓ | n/a |
| **DE SHAW**     | `engines/newton.py`        | ✓ | ⚠️ | ✓ | ⚠️ | ✓ | ✓ single-pos | ✓ inherit | ✓ | ✓ | n/a | ⚠️ | n/a |
| **MILLENNIUM**  | `engines/multistrategy.py` | inherit | inherit | inherit | inherit | inherit | inherit | inherit | inherit | inherit | inherit | inherit | n/a |
| **RENAISSANCE** | `core/harmonics.py`        | ✓ | ✓ | ✓ | ✓ | ⚠️ | ✓ fixed | ✓ inherit | ✓ | ✓ | ⚠️ | ✓ | n/a |
| **TWO SIGMA**   | `engines/prometeu.py`      | ⚠️ leakage-risk | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| **JANE STREET** | `engines/arbitrage.py`     | n/a | ⚠️ | ✓ | ✓ | ✓ | n/a | n/a | ✓ | ✓ | n/a | n/a | n/a |

**Totals:** 4 SMELL, 0 FAIL across 8 audited targets. Two of the SMELLs are
`n/a` → `⚠️` transitions because the strategy has a domain-specific variant
of the invariant (newton's execution delay, arbitrage's fill model, prometeu's
feature leakage).

---

## CITADEL — `engines/backtest.py` · `scan_symbol`

**Source files audited:** `engines/backtest.py` (lines 90-330), `core/signals.py` (shared).
**Main function:** `scan_symbol(df, symbol, macro_bias_series, htf_stack_dfs, all_dfs)`
**Scan loop:** lines 139-319 (per-bar iteration).

### Findings

- **L1-L5:** All inherited from the core audit. CITADEL is the only strategy
  whose decision path was written BY the core audit — every other strategy
  is measured against it. Row features are read from pre-extracted numpy
  arrays at `[idx]`, `label_trade` runs from `entry_idx=idx+1`, fees/slippage/
  funding applied in the standard C1/C2 pattern at lines 280-290.
- **L6:** ✓ fixed in commit `4f8679d` — `open_pos` is now 4-tuple,
  `check_aggregate_notional` runs after sizing. Regression backtest shows zero
  `agg_cap` vetoes at `LEVERAGE=1.0` (the cap is never approached by the
  base risk fractions).
- **L7:** ✓ fixed in the same commit — liquidation is now path-dependent
  inside `label_trade` via `_liq_prices` with `MAINTENANCE_MARGIN_RATIO=0.005`.
  Post-hoc 90%/95% clamp removed.
- **L8-L10:** Inherit from core. All indicators in `core/indicators.py` are
  forward-causal; HTF merge is backward-only `merge_asof`; warmup defended
  by `min_idx = max(200, W_NORM, PIVOT_N*3) + 5`.
- **L11:** `calc_levels` geometry asserted at lines 196-197 of `signals.py`
  — refuses setups where `stop >= entry` (long) or `stop <= entry` (short).
- **L12:** n/a — symbol universe is constructed by the caller (baskets
  in `config/params.py`), not by CITADEL itself.

### Verdict

No open issues. CITADEL is the reference implementation for the L1-L12
checklist in this repo.

---

## JUMP — `engines/mercurio.py` · `scan_mercurio`

**Source files audited:** `engines/mercurio.py` (lines 70-310).
**Main function:** `scan_mercurio(df, symbol, macro_bias_series, htf_stack_dfs, all_dfs)`
**Scan loop:** lines 109-280.

### Findings

- **L1:** ✓ — decision features (`cvd_div_bull`, `vimb`, `liq_proxy`, `rsi`,
  `atr`) are read from pre-extracted numpy arrays at `[idx]`. No lookahead.
- **L2:** ✓ — `label_trade(df, idx+1, ...)` delegates to the shared core
  function at line 202. Entry is `open[idx+1]` via `calc_levels`.
- **L3-L5:** ✓ — fees, slippage, and funding applied in the standard C1/C2
  pattern at lines 214-225. Funding sign respects direction (long pays
  when funding > 0, short receives).
- **L6:** ✓ **fixed in commit `ea1f6ba` — this is the MATERIAL one.**
  Pre-fix regression at `LEVERAGE=1.0` showed `agg_cap(15047 > 9990)` vetoes
  — meaning JUMP was opening concurrent positions whose combined notional
  exceeded `account × leverage`, and the backtest reported PnL on phantom
  margin a real exchange would have refused. Historical MERCURIO runs are
  all **potentially inflated** until re-run with the fix. See the "Material
  findings" section at the bottom.
- **L7:** ✓ inherited — `label_trade` now contains the `_liq_prices` check.
  JUMP uses `label_trade` unchanged.
- **L8-L11:** ✓ — shared-core primitives.
- **L12:** n/a.

### Verdict

Fixed in this audit. Historical backtests need re-run before being used
for any forward decision.

---

## BRIDGEWATER — `engines/thoth.py` · `scan_thoth`

**Source files audited:** `engines/thoth.py` (lines 130-320).
**Main function:** `scan_thoth(df, symbol, macro_bias_series, ...)`
**Scan loop:** lines 160-305.

### Findings

- **L1:** ✓ — sentiment features (`funding_z`, `oi_signal`, `ls_ratio_signal`)
  come from `core/sentiment.py` which is read-only and writes features into
  the dataframe BEFORE the scan loop. Row access is `[idx]` only.
- **L2-L5:** ✓ — same shared-core pattern as JUMP.
- **L6:** ✓ fixed in commit `ea1f6ba`. 7-day regression produced zero
  trades (sentiment signals are sparse at short horizons), so no `agg_cap`
  vetoes are observed. The check is wired correctly and will fire if a
  longer-horizon run produces concurrent entries.
- **L7-L11:** ✓ shared core.
- **L12:** n/a.

### Verdict

Clean. L6 fix is inert at short horizons; longer runs will prove its
effect once we have the material to compare.

---

## DE SHAW — `engines/newton.py` · `scan_pair`

**Source files audited:** `engines/newton.py` (lines 177-430).
**Main function:** `scan_pair(df_a, df_b, sym_a, sym_b, pair_info, macro_bias_series, corr)`
**Scan loop:** lines 218-427.

### Findings

- **L1:** ✓ — spread z-score, correlation, and indicators are computed on
  the full merged dataframe BEFORE the loop; per-bar reads are `[idx]` only.
- **L2:** ⚠️ **SMELL — execution delay is implicit, not explicit.**
  Newton does not use `calc_levels`/`label_trade`. Entry price is captured
  as `price = a_close[idx]` at line 220 and stored as `trade_entry_price`.
  This is the CLOSE of bar `idx`, not `open[idx+1]`. The spread mean-reversion
  logic is intrinsically end-of-bar, but it means the backtest sees the
  same bar it decided on — a 1-bar implicit lookahead compared to the other
  engines. **Severity:** MÉDIO. Not look-ahead in the L1 sense (nothing from
  `idx+1` is read), but the execution model is optimistic.
  **Fix:** use `open[idx+1]` as `trade_entry_price`, aligned with the other
  engines. Estimated effort: ~5 lines in scan_pair.
- **L3:** ✓ — fees applied at lines 288-296 in both BULLISH and BEARISH
  branches.
- **L4:** ⚠️ **SMELL — slippage only on exit.** Lines 289/294 apply
  `slip_exit = SLIPPAGE + SPREAD` to the exit price, but the entry price at
  line 220 is raw `a_close[idx]` — no slippage adjustment. Combined with
  the L2 issue, the entry is optimistic by `slippage_in + 1-bar delay`.
  **Fix:** `entry_p = price * (1 + slip)` for BULLISH, `* (1 - slip)` for
  BEARISH. Matches the pattern in `calc_levels`.
- **L5:** ✓ — funding applied at lines 290-295, correct sign per direction.
- **L6:** ✓ single-position guard added in commit `ea1f6ba`. Inline
  `check_aggregate_notional(size*entry_p, [], account, LEVERAGE)` runs before
  committing the new trade.
- **L7:** ✓ inherited via `label_trade` — BUT newton does not call
  `label_trade`. It has its own exit logic at lines 249-278 (z-score
  thresholds + max hold). The L7 liquidation check does NOT apply here.
  **Action required:** for consistency, newton should simulate a liquidation
  check against the raw price adverse excursion inside its exit loop.
  **Severity:** LOW at current leverage (1.0) where liquidation never
  triggers, but MÉDIO if leverage is raised above ~3x.
- **L8-L11:** ✓ indicators causal, warmup set at `min_idx = max(200,
  NEWTON_SPREAD_WINDOW + 50)` line 201.
- **L11:** ⚠️ **SMELL** — stop/target are implicit (z-score thresholds),
  not geometric price levels. The `target_price` and `stop_price` computed
  at lines 315-320 are ONLY for RR reporting, not actual exit logic. A
  trade can exit at a z-score level whose price is farther from the
  expected `target` or `stop`. Report RR is misleading for this engine.
  **Fix:** document explicitly that newton's RR is z-score-based. Rename
  `rr` in the trade dict to avoid confusion with the geometric RR used
  by other engines.
- **L12:** n/a — pairs are selected by caller cointegration filter.

### Verdict

Three medium-severity smells:
1. **L2 + L4 together**: entry price is optimistic (no slippage, same-bar
   close). Compounds into a favorable bias in reported PnL.
2. **L11**: RR reported is z-score based, not price-based — inconsistent
   with other engines' reports.
3. **L7**: no liquidation simulation — inert at low leverage but a footgun
   if the user raises leverage for stress tests.

None are blocking; all should be fixed before any live capital is allocated
to DE SHAW.

---

## MILLENNIUM — `engines/multistrategy.py` · ensemble orchestrator

**Source files audited:** `engines/multistrategy.py` (lines 1-200 + orchestration).
**Role:** not a scan engine — calls `azoth_scan` (CITADEL) and `scan_hermes`
(RENAISSANCE) and merges results with regime-weighted ensemble.

### Findings

- **L1-L11:** inherited from CITADEL and RENAISSANCE. MILLENNIUM does not
  touch raw market data; it composes trade lists from its two sub-strategies.
- **Ensemble-specific invariants:**
  - `REGIME_LAG = 5` at line 73 — the regime used to weight sub-strategies
    is the regime of 5 trades ago. This defends against feedback loop
    (weight → trade → trade shifts weight → feedback). **✓ PASS.**
  - `KILL_SWITCH_SORTINO = -0.5` at line 70 — a sub-strategy whose rolling
    Sortino drops below -0.5 is pinned at `ENSEMBLE_MIN_W=0.20`. **✓ PASS** —
    defensive cap on failing strategies.
  - `ENSEMBLE_WINDOW = 30` at line 66 — weights recomputed on rolling 30
    trades. Could in principle be gamed by a strategy with a burst of
    lucky wins, but `CONFIDENCE_N_MIN = 50` at line 72 scales the score
    by `sqrt(n/50)` so small samples can't dominate. **✓ PASS.**
  - Regime boost map at lines 77-81 — CITADEL boosted in trending regimes,
    RENAISSANCE boosted in CHOP. Hand-tuned but documented. **✓ PASS.**

### Verdict

No new findings. MILLENNIUM inherits all invariants from its two
sub-strategies. Ensemble math is defensive and the regime lag correctly
breaks the feedback loop.

---

## RENAISSANCE — `core/harmonics.py` · `scan_hermes`

**Source files audited:** `core/harmonics.py` (full file, ~350 lines).
**Main function:** `scan_hermes(df, symbol, macro_bias_series, corr)`
**Scan loop:** lines 195-320.

### Findings

- **L1:** ✓ — harmonic patterns are detected in a pre-pass at lines 182-194
  that iterates `alt[k..k+4]` pivot windows. Each pattern's `D["i"]` (the
  "prediction bar") is checked at the time of that bar's iteration in the
  main loop — no future pivots read at decision time.
- **L2:** ✓ — entry at line 250-251 uses `raw = float(open_a[idx+1])` with
  slippage applied. Same pattern as CITADEL.
- **L3-L4:** ✓ — fees and slippage at lines 262-268.
- **L5:** ⚠️ **SMELL** — funding is applied at line 264/268 but with the
  same `/ 32` hardcoded constant as the other engines. The shared core
  uses `_funding_periods_per_8h = 8*60/_TF_MINUTES.get(INTERVAL, 15)`; the
  `/ 32` works out to `= 8*60/15 = 32` only for 15-minute intervals. On
  any other `INTERVAL`, funding accrual is wrong. **Fix:** import
  `_TF_MINUTES` and compute the denominator dynamically. Matches core
  engine behavior after commit `c91d6b8` already addressed this in
  backtest.py; harmonics and mercurio/thoth still have the hardcoded `/32`.
- **L6:** ✓ fixed in commit `ea1f6ba` — 4-tuple `open_pos` + aggregate cap.
- **L7:** ✓ inherited via `label_trade`.
- **L8:** ✓ — harmonic ratio checks and indicators are causal.
- **L9:** ✓ — `min_idx = max(200, H_PIVOT_N*3)` at setup.
- **L10:** ⚠️ **SMELL** — `scan_hermes` reads `df[f"htf{i}_struct"].iloc[idx]`
  at lines 226-228. This assumes the HTF merge already embedded the HTF
  features into the LTF dataframe. If the caller forgets to run
  `merge_all_htf_to_ltf`, these reads return NaN and the strategy
  silently skips everything under `hermes_fractal_misalign`. **Fix:** add
  an assert at the top of `scan_hermes` that `htf{len(HTF_STACK)}_struct`
  is in `df.columns` if `MTF_ENABLED`.
- **L11:** ✓ — geometry asserted at lines 253-254.
- **L12:** n/a.

### Verdict

Two medium-severity smells (funding constant, HTF precondition). Neither
affects current-default behavior (15m interval, MTF always enabled), but
both should be cleaned up before live.

---

## TWO SIGMA — `engines/prometeu.py` · ML meta-ensemble

**Source files audited:** `engines/prometeu.py` (lines 70-290).
**Role:** ML filter. Takes trades from other engines, trains a LightGBM model
on walk-forward windows, predicts which trades to keep. **Not a scan engine.**

### Findings

- **L1:** ⚠️ **SMELL — feature leakage risk in trade-based training.**
  `trades_to_features` at line 71 converts trade dicts to a feature matrix.
  Walk-forward training at line 147 splits trades into train/test by index
  (70/30). The concern: features derived from the TRADE itself (exit reason,
  duration, final PnL, R-multiple) are KNOWN ONLY AT EXIT, not at the time
  the trade was opened. If any of those features end up in the model input,
  the model learns from post-hoc information and produces inflated OOS
  scores. **Action required:** audit `trades_to_features` specifically and
  confirm only AT-OPEN features are used (entry price, entry score, regime,
  indicators at entry_idx). If any AT-EXIT features leak in, the model needs
  a retrain with a stricter feature set.

- **L2-L12:** n/a. Prometeu doesn't touch market data directly; it consumes
  trade records produced by other engines. L1-L12 for it should be read as
  ML-specific: no data leakage, no target leakage, proper train/test split,
  no sample reuse across folds.

### Verdict

**One open SMELL that needs a focused audit of `trades_to_features`.**
Blocking for live use of TWO SIGMA until clarified. Cheap fix if
confirmed: whitelist-only feature construction + regression test that
asserts no AT-EXIT columns present in training matrix.

---

## JANE STREET — `engines/arbitrage.py` · cross-venue basis/funding

**Source files audited:** `engines/arbitrage.py` (lines 1-600 + executor).
**Role:** cross-venue crypto-futures arbitrage. Different domain from the
directional strategies — no `calc_levels`/`label_trade`. The invariants
checklist is reinterpreted for the arb context.

### Findings

- **L1:** n/a — no look-ahead in the directional sense. Signals are based on
  real-time funding and order book state at scan time.
- **L2:** ⚠️ **SMELL — execution delay approximated by `simulate_fill`.**
  Lines 541-564 implement `simulate_fill` which walks the order book and
  returns an average price + slippage bps. Good. BUT: the fill happens in
  the same tick as the signal — no latency modelling. Real arb needs to
  account for the 50-200ms round-trip to send the order after observing
  the quote. **Fix:** add a configurable `LATENCY_MS` parameter and
  simulate a price drift proportional to it.
- **L3:** ✓ — fees per-venue modelled in `simulate_fill` return dict.
- **L4:** ✓ — slippage is explicit (the point of `simulate_fill`).
- **L5:** ✓ — funding rates are the actual signal source (lines 92-430
  of the venue adapters). Funding sign respected in PnL accrual.
- **L6-L11:** n/a — different domain.
- **L12:** n/a.

### Verdict

One SMELL (latency modelling absent). Not a correctness bug but a
favourable bias on reported arbitrage edge. Fix before attributing any
real-capital PnL decisions to the backtest.

---

## Material findings (flagged for re-runs and cleanup)

### 1. MERCURIO / JUMP historical reports are potentially inflated

Regression backtest of `engines/mercurio.py` at `LEVERAGE=1.0` (default)
immediately after landing commit `ea1f6ba` produced dozens of `agg_cap`
vetoes with values like `agg_cap(15047 > 9990)` — meaning the engine WAS
opening concurrent positions whose combined notional exceeded
`account × leverage`. Pre-fix, those positions were allowed and their
PnL was summed into the reported metrics. **Every MERCURIO row in
`data/index.json` dated before 2026-04-11 is suspect.**

Recommended: add a filter to `_data_backtests` that tags pre-`ea1f6ba`
MERCURIO runs with a `⚠ pre-L6` badge so the user knows not to trust
them. Alternatively, re-run the same seeds/configs with the fix and
compare.

### 2. NEWTON / DE SHAW reports are optimistically biased

L2 + L4 combined: entry price uses `close[idx]` with no slippage, and
execution is same-bar. Both historical and current reports are
systematically better than a fair simulation would produce. Less severe
than the MERCURIO issue (no margin violation) but still material for
any forward decision that compares newton's Sharpe against other engines.

### 3. HARMONICS / RENAISSANCE funding is wrong at non-15m intervals

Hardcoded `/ 32` at lines 264/268 assumes 15m. Any run with a different
`INTERVAL` (1h, 4h, 1d) accrues funding at the wrong rate. Fixing is a
3-line change.

### 4. TWO SIGMA feature leakage not yet verified

Open action: audit `trades_to_features` in `engines/prometeu.py:71` and
confirm feature construction is AT-OPEN only. Block TWO SIGMA use until
verified.

### 5. JANE STREET has no latency model

Arb engines report optimistic edge because `simulate_fill` assumes
instantaneous execution. Not a bug, a modelling gap.

---

## Cross-cutting recommendations

Based on the above, the prioritized fix list (in addition to the L6/L7
work already done) is:

| # | Fix | Engine(s) | Severity | Effort |
|---|---|---|---|---|
| 1 | Entry slippage + 1-bar delay in `scan_pair` | newton | MÉDIO | 5 lines |
| 2 | TWO SIGMA feature whitelist audit | prometeu | MÉDIO (blocking) | 1h |
| 3 | Dynamic funding denominator in harmonics + mercurio + thoth | 3 engines | MÉDIO | 10 lines |
| 4 | z-score exit liquidation guard in newton | newton | BAIXO | 10 lines |
| 5 | Latency model in arbitrage simulate_fill | arbitrage | MÉDIO | 15 lines |
| 6 | HTF precondition assert in scan_hermes | harmonics | BAIXO | 3 lines |
| 7 | Pre-L6 badge on historical MERCURIO runs | launcher | UX | 20 lines |

All items above can be landed as independent commits without breaking
any current functionality. None are blocking for Fase 4 work —
they are strategy-specific refinements that tighten confidence in each
engine's reported PnL.

---

## Changelog

- **2026-04-11** — Initial audit. 4 SMELLs flagged (newton L2+L4 combo,
  harmonics L5 funding, harmonics L10 precondition, prometeu L1 leakage,
  arbitrage L2 latency). L6 rollout via commit `ea1f6ba` closed the
  L6 gap on all strategies with concurrent positions. CITADEL unchanged
  (already audited in the core doc).
