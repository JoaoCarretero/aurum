# BRIDGEWATER Forensics — 2026-04-17 11:21

This note is additive to `docs/audits/2026-04-17_oos_revalidation.md`. It does
not replace the Block 0 verdict; it documents the dedicated BRIDGEWATER
forensic session that followed the checkpoint.

## Scope

- Identify the bug or artifact inflating BRIDGEWATER.
- Check whether any real edge remains once the safe local issue is removed.
- Decide the honest operational status of the engine.

## Root Cause

### Safe local bug

- `engines/bridgewater.py::_align_oi_signal_to_candles` used `bfill()` after a
  backward asof merge. That let candles before the first OI observation inherit
  the first future `oi_signal`, which is a temporal leak.
- The local fix was to keep the pre-series gap at `0.0`.

### Dominant residual artifact

- In the current environment, `fetch_open_interest` and
  `fetch_long_short_ratio` fail with `HTTP 400` across almost the entire
  supported universe.
- As a result, BRIDGEWATER runs with `oi_signal=0.0` and `ls_signal=0.0` in
  100% of recorded trades, despite the strategy thesis depending on funding +
  OI + long/short positioning.
- The engine is therefore being evaluated as funding-only while still reporting
  very high Sharpe/ROI numbers.

## Validation

- Contract tests:
  - `pytest tests/test_bridgewater_contracts.py -q` → `2 passed`
- Comparable reruns executed with `--basket bluechip`:
  - `BEAR`: `--days 360 --end 2023-01-01`
  - `BULL`: `--days 360 --end 2021-07-01`
  - `CHOP`: `--days 300 --end 2020-03-01`

## Before vs After

### Comparable windows

| Regime | Before | After local fix | Read |
| --- | --- | --- | --- |
| BEAR | `4037 trades / ROI 80.66% / Sharpe 4.934` | identical | local OI fix had no measurable impact |
| BULL | `3390 trades / ROI 145.67% / Sharpe 8.723` | identical | local OI fix had no measurable impact |
| CHOP | `1526 trades / ROI 48.34% / Sharpe 4.981` | `1411 / 60.06% / 6.045` | not a clean delta; older raw was mislabeled with `--days 360` |

### Important note on CHOP

- The old persisted CHOP raw from Block 0 was labeled `2019-06 -> 2020-03`, but
  its payload used `--days 360`.
- The rerun in this session used the intended `--days 300`, so the CHOP delta
  should be read as a methodology correction, not as an effect of the OI fix.

## Trade-Level Read

- `BEAR`: 100% funding-only; top PnL concentration was `AVAXUSDT ~61%`.
- `BULL`: 100% funding-only; top contributors were `ADAUSDT`, `BNBUSDT`,
  `NEARUSDT`.
- `CHOP`: 100% funding-only; `ATOMUSDT` contributed `~68%` of PnL.

The concentration rotates by regime, but the more important point is that the
strategy still posts very high metrics without the OI/LS legs that supposedly
justify the thesis.

## Interpretation

- The local OI alignment bug is real and was worth fixing.
- It does not rehabilitate BRIDGEWATER, because the dominant problem now is the
  upstream OI/LS sentiment pipeline being absent or unusable for the tested
  windows.
- Without a functioning OI/LS path, the current OOS does not validate the
  intended strategy design.
- No robust edge was established.

## Final Status

- “O bug era: o pre-series de OI podia herdar o primeiro `oi_signal` futuro via
  `bfill()` em `_align_oi_signal_to_candles`, caracterizando leak temporal
  local.”
- “O impacto estimado era: real no código, mas irrelevante para os reruns OOS
  comparáveis atuais, porque `oi_signal` e `ls_signal` ficaram zerados em 100%
  dos trades devido a falhas `HTTP 400` no pipeline de OI/LS.”
- “Após correção, o BRIDGEWATER ficou com: `BEAR 4037 / 80.66% / 4.934`,
  `BULL 3390 / 145.67% / 8.723`, `CHOP 1411 / 60.06% / 6.045`, ainda sem OI/LS
  efetivos e ainda sem plausibilidade econômica.”
- “Status honesto final: `CORRIGIR E REVALIDAR EM OUTRA SESSÃO`.”
