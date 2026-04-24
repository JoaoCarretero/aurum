# GRAHAM Recalibration - 2026-04-21

## Executive summary

Decision: `archive confirmed`.

The reopening round did not find defensible edge. The closed train grid
produced zero trades in all 8 variants on the registered split, so the engine
failed before test/holdout. A follow-up diagnostic showed the root cause was
not the exit lifecycle alone: in the stable `4h` universe, `eta_smooth` never
reached the 0.65 lower gate before `2024-06-01`. There is no honest way to
claim edge when the gate is absent on the train window.

## Hypothesis

The only admissible reopening thesis was lifecycle coherence:

- prior manual run relaxed `eta_lower` to `0.65`;
- exits still used `eta_exit_lower=0.75`;
- this could have been clipping otherwise valid endogenous-trend trades.

Expected falsifiable outcome:
- if lifecycle incoherence was the real problem, coherent exit-floor variants
  should generate train trades, improve train Sharpe, and survive DSR;
- if train still produced no edge, archive stands.

## Registered split

Hardcoded in [engines/graham.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/graham.py:95) and mirrored in
[docs/engines/graham/hypothesis.md](/C:/Users/Joao/OneDrive/aurum.finance/docs/engines/graham/hypothesis.md:1):

- `TRAIN_END = 2024-06-01T00:00:00`
- `TEST_END = 2025-04-01T00:00:00`
- `HOLDOUT_END = 2026-04-20T20:00:00`

Universe fixed for this round:
- `bluechip_4h_stable`
- symbols: `BTC, ETH, BNB, SOL, XRP, ADA, AVAX, LINK, DOT, ATOM, NEAR, INJ, ARB, OP, SUI, FET, SAND, AAVE`

## Closed grid

Registered in [docs/engines/graham/grid.md](/C:/Users/Joao/OneDrive/aurum.finance/docs/engines/graham/grid.md:1).

| Variant | eta_lower | eta_upper | eta_exit_lower | eta_exit_sustained | slope_min_abs | structure_min_count |
|---|---:|---:|---:|---:|---:|---:|
| GR00_baseline_incoherent | 0.65 | 0.90 | 0.75 | 2 | 0.0008 | 2 |
| GR01_exit_floor_match | 0.65 | 0.90 | 0.65 | 2 | 0.0008 | 2 |
| GR02_exit_floor_buffer | 0.65 | 0.90 | 0.62 | 2 | 0.0008 | 2 |
| GR03_exit_floor_match_exit3 | 0.65 | 0.90 | 0.65 | 3 | 0.0008 | 2 |
| GR04_exit_floor_buffer_exit3 | 0.65 | 0.90 | 0.62 | 3 | 0.0008 | 2 |
| GR05_match_stronger_slope | 0.65 | 0.90 | 0.65 | 3 | 0.0012 | 2 |
| GR06_match_stronger_structure | 0.65 | 0.90 | 0.65 | 3 | 0.0008 | 3 |
| GR07_tighter_upper_match | 0.65 | 0.85 | 0.65 | 3 | 0.0012 | 2 |

## Commands run

Test suite:

```powershell
& 'C:\Users\Joao\AppData\Local\Python\pythoncore-3.14-64\Scripts\pytest.exe' tests/engines/test_graham.py
```

Train battery:

```powershell
@'
# precompute cached 4h features once, then evaluate the 8 registered variants
# on the train window using scan_symbol_window(...)
'@ | & 'C:\Users\Joao\AppData\Local\Python\pythoncore-3.14-64\python.exe' -
```

Forensic diagnostic:

```powershell
@'
# inspect eta_smooth coverage and overlap with trend trigger before TRAIN_END
'@ | & 'C:\Users\Joao\AppData\Local\Python\pythoncore-3.14-64\python.exe' -
```

## Metrics by stage

### Train

All 8 variants returned the same result:

| Variant | Trades | PnL | ROI % | Sharpe | Sortino | Max DD % | DSR |
|---|---:|---:|---:|---:|---:|---:|---:|
| GR00_baseline_incoherent | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |
| GR01_exit_floor_match | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |
| GR02_exit_floor_buffer | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |
| GR03_exit_floor_match_exit3 | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |
| GR04_exit_floor_buffer_exit3 | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |
| GR05_match_stronger_slope | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |
| GR06_match_stronger_structure | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |
| GR07_tighter_upper_match | 0 | 0.00 | 0.00 | 0.000 | 0.000 | 0.00 | 0.5000 |

Stop rule triggered:
- no train trades;
- no train Sharpe above threshold;
- no DSR pass;
- no promotion to test.

### Test

Not run.

Reason:
- protocol stop at train because the grid produced no candidate with
  `Sharpe_train >= 1.5` or `DSR > 0.95`.

### Holdout

Not run.

Reason:
- test stage was never reached.

## Forensic notes

The train failure was structural, not just poor returns.

Diagnostic on the stable train window:

- `eta_in_band_bars = 0` for all 18 symbols at `0.65 <= eta < 0.90`
- `overlap_bars = 0` for all 18 symbols between Hawkes gate and trend trigger
- pre-train `eta_max` highlights:
  - `FETUSDT`: `0.6344`
  - `ADAUSDT`: `0.5590`
  - `BNBUSDT`: `0.5563`
  - `AVAXUSDT`: `0.5199`
  - `OPUSDT`: `0.5160`
  - `BTCUSDT`: `0.4358`

Interpretation:
- the lifecycle mismatch was real in later runs, but it was not the primary
  blocker on the registered train split;
- before `2024-06-01`, the Hawkes gate itself was absent in this universe;
- without gate occurrence in train, there is nothing to tune honestly.

## Files changed

- [engines/graham.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/graham.py:1)
- [tests/engines/test_graham.py](/C:/Users/Joao/OneDrive/aurum.finance/tests/engines/test_graham.py:1)
- [docs/engines/graham/hypothesis.md](/C:/Users/Joao/OneDrive/aurum.finance/docs/engines/graham/hypothesis.md:1)
- [docs/engines/graham/grid.md](/C:/Users/Joao/OneDrive/aurum.finance/docs/engines/graham/grid.md:1)
- [docs/audits/2026-04-21_graham_recalibration.md](/C:/Users/Joao/OneDrive/aurum.finance/docs/audits/2026-04-21_graham_recalibration.md:1)

## Objective verdict

No edge found.

Binary decision:
- `archive confirmed`

What would justify reopening again:
- a new signal base with a different mechanical thesis;
- or a new Hawkes calibration regime that shows non-zero gate incidence in
  train before any parameter tuning starts.
