# Phase C Characterization Map

This document records the current characterization-test boundary for the sacred
logic contract and defines the minimum authentic-input capture plan for the
remaining uncovered sacred paths.

Reference:
- [Sacred Logic Contract](../contracts/sacred-logic-contract.md)

## 1. Current Coverage

### Locked now

Backtest:
- `core.analysis_export._collect_run(...)` projection of the recorded run
  `data/runs/citadel_2026-04-10_1122`
- Recorded backtest artifact outputs:
  - summary fields
  - trade count
  - win/loss count
  - first trade payload
  - last trade payload
  - equity curve length
- Recorded veto counts parsed from the saved HTML report:
  - `score_baixo`
  - `macro_bull_veto_short`
  - `macro_bear_veto_long`
  - `vol_extreme`
  - `mercado_lento`
  - `streak_cooldown`

Live:
- `engines.live.SignalEngine.build_signal_dict`
  - baseline output shape and rounding
  - drift size penalty path
  - symbol-rank veto path
- `engines.live.LiveEngine._startup_reconcile`
  - empty broker / empty local -> continue
  - broker/local mismatch -> `killed=True`

Arbitrage:
- `engines.arbitrage.omega_score`
  - zero-score gates
  - positive scoring cases
- `engines.arbitrage.scan_all`
  - active venue set
  - opportunity construction
  - ranking order across:
    - `PERP_PERP`
    - `SPOT_PERP`
    - `PRICE_ARB`
    - `INTERNAL`

### Tests currently providing that coverage

- [tests/test_phase_c_backtest_characterization.py](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/test_phase_c_backtest_characterization.py)
- [tests/test_phase_c_live_characterization.py](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/test_phase_c_live_characterization.py)
- [tests/test_phase_c_arbitrage_characterization.py](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/test_phase_c_arbitrage_characterization.py)

### Existing fixtures and snapshots

- [tests/fixtures/phase_c/backtest/citadel_2026-04-10_1122_snapshot.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/backtest/citadel_2026-04-10_1122_snapshot.json)
- [tests/fixtures/phase_c/live/build_signal_dict_base.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/live/build_signal_dict_base.json)
- [tests/fixtures/phase_c/live/build_signal_dict_drift_penalty.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/live/build_signal_dict_drift_penalty.json)
- [tests/fixtures/phase_c/live/broker_positions_empty.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/live/broker_positions_empty.json)
- [tests/fixtures/phase_c/live/broker_positions_btc_only.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/live/broker_positions_btc_only.json)
- [tests/fixtures/phase_c/arbitrage/omega_score_snapshot.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/arbitrage/omega_score_snapshot.json)
- [tests/fixtures/phase_c/arbitrage/scan_all_snapshot.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/arbitrage/scan_all_snapshot.json)
- [tests/fixtures/phase_c/capture_manifest.json](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/fixtures/phase_c/capture_manifest.json)

Support utilities:
- [core/fixture_capture.py](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/core/fixture_capture.py)
- [tools/phase_c_capture_report.py](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tools/phase_c_capture_report.py)
- [tests/test_fixture_capture.py](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/tests/test_fixture_capture.py)

## 2. Uncovered Sacred Surfaces

Still uncovered:
- `engines.backtest.scan_symbol`
- `engines.live.SignalEngine.check_signal`
- `engines.live.LiveEngine._reconciliation_loop`
- `engines.arbitrage.Engine._open`
- `engines.arbitrage.Engine._close`

Not yet covered in this phase:
- live kill-switch escalation paths driven by reconciliation or execution failures
- arbitrage kill-switch escalation linked to hedge breaks / fill failures

## 3. Blockers Caused By Missing Authentic Inputs

### `engines.backtest.scan_symbol`

What the function actually requires:
- A full LTF dataframe with at least:
  - `time`
  - `open`
  - `high`
  - `low`
  - `close`
  - `vol`
  - `tbb`
- Enough bars to satisfy warmup:
  - minimum uses `max(200, W_NORM, PIVOT_N*3) + 5`
- `macro_bias_series`
- `corr`
- optional `htf_stack_dfs` when MTF is enabled

What exists in-repo now:
- saved `price_data.json` for recorded runs

What is missing:
- recorded `time`
- recorded `vol`
- recorded `tbb`
- recorded `macro_bias_series`
- recorded `corr`
- recorded HTF stack inputs

Why this blocks safe characterization:
- reconstructing the missing fields would require synthetic inference, which
  would no longer be a characterization of the current system.

### `engines.live.SignalEngine.check_signal`

What the function actually requires:
- a real `CandleBuffer` window convertible to a dataframe with:
  - `time`
  - `open`
  - `high`
  - `low`
  - `close`
  - `vol`
  - `tbb`
- `macro_series`
- `corr`
- `open_positions`
- optional `htf_dfs`
- `account`
- `peak_equity`

What exists in-repo now:
- live state files for positions
- logs

What is missing:
- recorded per-symbol candle-buffer snapshots at decision time
- recorded `macro_series`
- recorded `corr`
- recorded HTF decision inputs
- recorded `open_positions`, `account`, and `peak_equity` aligned to the same
  decision tick

Current capture status:
- support-only caller instrumentation is now in place in
  `LiveEngine.on_candle_close(...)`
- authentic fixtures will be produced on the next live run when capture is
  explicitly enabled

### `engines.live.LiveEngine._reconciliation_loop`

What the function actually requires:
- repeated broker snapshots from `_fetch_broker_snapshot()`:
  - `equity`
  - `positions[symbol] -> {size, direction, entry}`
- repeated local engine state at the same timestamps:
  - `self.account`
  - `self.positions`
  - `self.running`
  - `self._kill_switch_active`
- audit trail side effects
- enough consecutive ticks to prove:
  - no drift
  - one-off drift
  - clearing after drift
  - hard break after 3 consecutive drifts

What exists in-repo now:
- startup local position state

What is missing:
- authentic repeated broker snapshots
- aligned local expected-state snapshots across the same reconciliation cadence
- captured drift streak examples

### `engines.arbitrage.Engine._open`

What the function actually requires:
- a real ranked `opp` payload
- regime and execution context:
  - `regime`
  - venue latency measurements
  - slippage estimate
  - fill probability
  - flow analysis
  - competition analysis
- venue objects containing:
  - prices
  - cost
  - quantity rounding
  - leverage setters
  - order execution paths
- engine state:
  - account
  - peak
  - positions
  - sizer
  - audit trail
  - latency profiler
  - hedge monitor

What exists in-repo now:
- saved arbitrage session summaries
- saved empty/non-empty state files

What is missing:
- authentic opportunity payload selected for open
- authentic venue price maps at that moment
- authentic leg fill quantities and ordering
- audit trail rows generated for that open
- resulting position object state after open

### `engines.arbitrage.Engine._close`

What the function actually requires:
- an authentic open `Position`
- the closing reason
- current venue prices for both legs
- execution fills for closing legs
- account and closed-trade side effects
- audit trail fill row

What exists in-repo now:
- saved arbitrage session summaries and coarse position-state files

What is missing:
- authentic pre-close position object snapshot
- authentic current venue prices at close
- authentic close leg fills
- resulting account / closed payload / audit row bundle

## 4. Minimum Real-Input Capture Plan

The next capture pass should prefer support-only instrumentation and should not
modify sacred formulas, thresholds, filters, sizing, exits, ranking, or call
order.

### A. `engines.backtest.scan_symbol`

Exact inputs required:
- `symbol`
- raw input dataframe before `indicators(...)`
- `macro_bias_series`
- `corr`
- `htf_stack_dfs`
- selected config context:
  - interval
  - run id
  - MTF enabled flag

Current source:
- backtest launcher / run orchestration just before calling `scan_symbol(...)`

What is missing in repo:
- the full dataframe and associated support inputs for any recorded symbol run

Safest capture method:
- support-only capture immediately before invoking `scan_symbol(...)`
- write one capture file per symbol/run without mutating the call arguments

Can support-only instrumentation do it:
- yes

Recommended fixture after capture:
- `tests/fixtures/phase_c/captures/backtest_scan_symbol/{run_id}_{symbol}.json`

Recommended payload fields:
- `symbol`
- `run_id`
- `interval`
- `df_records`
- `macro_bias_series`
- `corr`
- `htf_stack_dfs`

### B. `engines.live.SignalEngine.check_signal`

Exact inputs required:
- `symbol`
- `buffer.to_df(symbol)` source window as candle records
- `macro_series`
- `corr`
- `open_positions`
- `htf_dfs`
- `account`
- `peak_equity`
- timestamp of the decision

Current source:
- live loop immediately before calling `check_signal(...)`

What is missing in repo:
- authentic aligned decision snapshots at the moment a signal is checked

Safest capture method:
- support-only capture wrapper in the non-sacred caller around
  `self.signal_e.check_signal(...)`
- capture the already-computed caller inputs, not derived post-hoc data

Can support-only instrumentation do it:
- yes

Recommended fixtures after capture:
- `tests/fixtures/phase_c/captures/live_check_signal/{run_id}_{symbol}_{ts}.json`

Recommended payload fields:
- `symbol`
- `run_id`
- `candle_window`
- `macro_series`
- `corr`
- `open_positions`
- `htf_dfs`
- `account`
- `peak_equity`
- `result_tuple`
- `last_veto`

Enable capture for this surface:
- set `AURUM_PHASE_C_CAPTURE_SURFACES=live_check_signal`
- set `AURUM_PHASE_C_CAPTURE_MAX_PER_SURFACE=1` or higher
- run the live engine normally

Capture write path:
- `tests/fixtures/phase_c/captures/live_check_signal/*.json`

Inspect capture status:
- `C:\Users\Joao\AppData\Local\Python\pythoncore-3.14-64\python.exe tools\phase_c_capture_report.py`

### C. `engines.live.LiveEngine._reconciliation_loop`

Exact inputs required:
- each broker snapshot returned by `_fetch_broker_snapshot()`
- corresponding local expected state:
  - `account`
  - `positions`
  - `running`
  - `_kill_switch_active`
- enough consecutive ticks to preserve streak behavior

Current source:
- inside `_reconciliation_loop()` after broker snapshot fetch and before drift
  evaluation

What is missing in repo:
- authentic multi-tick reconciliation payloads

Safest capture method:
- support-only snapshotting of:
  - broker snapshot
  - local expected projection
  - consecutive drift count
- write one file per reconciliation tick

Can support-only instrumentation do it:
- yes

Recommended fixtures after capture:
- `tests/fixtures/phase_c/captures/live_reconciliation_loop/{run_id}_tick_{n}.json`

Recommended payload fields:
- `broker_snapshot`
- `expected_local`
- `consecutive_drift_before`
- `mode`
- `tick_ts`

### D. `engines.arbitrage.Engine._open`

Exact inputs required:
- the chosen `opp`
- regime/execution context:
  - `regime`
  - `slippage_bps`
  - `p_fill`
  - `flow_analysis`
  - `comp`
  - latency context
- venue price/cost state for `v_a` and `v_b`
- resulting fills for each leg
- resulting engine-side position/account state

Current source:
- arbitrage engine immediately before order execution and immediately after leg
  execution completes

What is missing in repo:
- authentic pre-open input bundle
- authentic per-leg fill results
- resulting open-position state

Safest capture method:
- support-only capture in non-sacred orchestration around `_open(...)`:
  - pre-open input bundle
  - post-open result bundle
- do not alter `opp`, venue objects, or leg call order

Can support-only instrumentation do it:
- yes, but capture should be strictly observational

Recommended fixtures after capture:
- `tests/fixtures/phase_c/captures/arbitrage_open/{run_id}_{symbol}_{ts}_pre.json`
- `tests/fixtures/phase_c/captures/arbitrage_open/{run_id}_{symbol}_{ts}_post.json`

Recommended payload fields:
- pre:
  - `opp`
  - `regime`
  - `slippage_bps`
  - `p_fill`
  - `flow_analysis`
  - `comp`
  - `venue_state`
- post:
  - `fills`
  - `positions`
  - `account`
  - `peak`
  - `audit_refs`

### E. `engines.arbitrage.Engine._close`

Exact inputs required:
- the live `Position` before close
- `reason`
- current venue prices
- closing leg fills
- resulting `closed` entry
- resulting `account` / `peak`
- audit fill row context

Current source:
- arbitrage engine immediately before and after `_close(...)`

What is missing in repo:
- authentic close bundles tying together position, prices, fills, and final PnL

Safest capture method:
- support-only pre/post close capture around `_close(...)`
- preserve the exact closing sequence and only serialize observed state

Can support-only instrumentation do it:
- yes

Recommended fixtures after capture:
- `tests/fixtures/phase_c/captures/arbitrage_close/{run_id}_{symbol}_{ts}_pre.json`
- `tests/fixtures/phase_c/captures/arbitrage_close/{run_id}_{symbol}_{ts}_post.json`

Recommended payload fields:
- pre:
  - `position`
  - `reason`
  - `venue_prices`
- post:
  - `closed_tail`
  - `account`
  - `peak`
  - `audit_refs`

## 5. Safe Instrumentation Added In This Batch

Added support-only helper:
- [core/fixture_capture.py](/abs/path/C:/Users/Joao/OneDrive/aurum.finance/core/fixture_capture.py)

What it does:
- writes versioned Phase C capture payloads
- writes a versioned capture manifest
- does not hook into sacred logic by itself

Safe because:
- no sacred logic imports were modified
- no runtime call order was changed
- no formulas, thresholds, filters, sizing, exits, ranking, or reconciliation
  semantics were touched

## 6. Next Capture Files To Create

Minimum next fixtures to collect:
- `tests/fixtures/phase_c/captures/backtest_scan_symbol/{run_id}_{symbol}.json`
- `tests/fixtures/phase_c/captures/live_check_signal/{run_id}_{symbol}_{ts}.json`
- `tests/fixtures/phase_c/captures/live_reconciliation_loop/{run_id}_tick_{n}.json`
- `tests/fixtures/phase_c/captures/arbitrage_open/{run_id}_{symbol}_{ts}_pre.json`
- `tests/fixtures/phase_c/captures/arbitrage_open/{run_id}_{symbol}_{ts}_post.json`
- `tests/fixtures/phase_c/captures/arbitrage_close/{run_id}_{symbol}_{ts}_pre.json`
- `tests/fixtures/phase_c/captures/arbitrage_close/{run_id}_{symbol}_{ts}_post.json`

These should only be generated from authentic runtime inputs, never from
reconstructed or synthetic execution traces.
