# DE SHAW Diagnostic

- Date: `2026-04-13`
- Engine: `DE SHAW` / `engines/newton.py`
- Validation run: `python tools/engine_validation.py --days 90 --basket default --leverage 1.0`
- Outcome: `failed`

## Observed Run Result

- Universe: `default`
- Assets: `11`
- Possible pairs tested: `55`
- Valid cointegrated pairs found: `0`
- Engine exit condition reached: `len(pairs) < NEWTON_MIN_PAIRS`
- Failure summary: `No valid cointegrated pairs found for the current 90d/default universe.`

## Code-Level Findings

- Cointegration test: `statsmodels.tsa.stattools.coint` via Engle-Granger.
- P-value filter: `NEWTON_COINT_PVALUE = 0.05`
- Half-life filter: `NEWTON_HALFLIFE_MIN = 5`, `NEWTON_HALFLIFE_MAX = 500`
- Minimum pairs required to proceed: `NEWTON_MIN_PAIRS = 2`
- Entry / stop context:
  - `NEWTON_ZSCORE_ENTRY = 2.0`
  - `NEWTON_ZSCORE_STOP = 3.5`

## Relevant Code References

- [engines/newton.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/newton.py:70): pair scan and Engle-Granger test
- [engines/newton.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/newton.py:103): rejects pairs when `pvalue > NEWTON_COINT_PVALUE`
- [engines/newton.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/newton.py:132): rejects pairs outside half-life bounds
- [engines/newton.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/newton.py:147): logs `testados` vs `validos`
- [engines/newton.py](/C:/Users/Joao/OneDrive/aurum.finance/engines/newton.py:770): hard stop when pair count is below minimum
- [config/params.py](/C:/Users/Joao/OneDrive/aurum.finance/config/params.py:358): `NEWTON_COINT_PVALUE = 0.05`
- [config/params.py](/C:/Users/Joao/OneDrive/aurum.finance/config/params.py:359): `NEWTON_HALFLIFE_MIN = 5`
- [config/params.py](/C:/Users/Joao/OneDrive/aurum.finance/config/params.py:360): `NEWTON_HALFLIFE_MAX = 500`
- [config/params.py](/C:/Users/Joao/OneDrive/aurum.finance/config/params.py:365): `NEWTON_MIN_PAIRS = 2`

## Interpretation

- The engine is operational in the narrow sense that data fetch, pair enumeration, and the cointegration scan complete successfully.
- The blocker is not a crash. The blocker is that the current `90d/default` universe does not produce even `2` pairs that survive the current statistical filters.
- That means the current status should be read as `diagnostic failure`, not `runtime failure`.

## What This Implies

- If some pair p-values are clustered just above `0.05`, the issue is likely threshold strictness.
- If most candidate pairs are far above `0.05`, the issue is structural: this universe/window does not contain stable cointegration for the strategy.
- Because the run artifact only exposed aggregate counts, the exact per-pair p-value distribution is still not captured in a saved artifact from this Codex pass.

## Classification Today

- Status: `⚠ diagnostic`
- Plain-language status: `engine runs, but current 90d/default universe yields 0 valid cointegrated pairs`
- Not attempted here:
  - no threshold changes
  - no universe changes
  - no period extension to `180d`
  - no optimization work
