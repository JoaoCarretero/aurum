# KEPOS Recalibration Plan

Date: 2026-04-20
Engine: `kepos`
Status: Draft

## Goal

Determine whether KEPOS has real edge with disciplined Hawkes + extension + HMM/RSI gating, or whether it should be archived.

## Hypothesis

Critical-endogeneity fade only works when:
- `eta` threshold is realistic
- extension is meaningful
- HMM confirms chop and vetoes strong trend
- RSI confirms exhaustion
- cooldown avoids repeated bad re-entry

## Frozen Mechanism

Do not change:
- Hawkes feature construction
- cost model
- trade lifecycle
- persistence/reporting

Only tune:
- `eta_critical`
- `eta_sustained_bars`
- `price_ext_sigma`
- `atr_expansion_ratio`
- `rsi_exhaustion_level`
- `hmm_min_prob_chop`
- `hmm_max_trend_prob`
- `min_reentry_cooldown_bars`

## Windows

- Train:
  - `2021-05-01 -> 2024-01-01`
  - command window: `--days 975 --end 2024-01-01`
- OOS bear:
  - `2022-01-01 -> 2023-01-01`
  - command window: `--days 360 --end 2023-01-01`
- OOS chop:
  - `2019-06-01 -> 2020-03-01`
  - command window: `--days 360 --end 2020-03-01`
- OOS recent:
  - `2025-01-01 -> 2026-01-01`
  - command window: `--days 360 --end 2026-01-01`

Reference-only window:
- OOS bull:
  - `2020-07-01 -> 2021-07-01`
  - command window: `--days 360 --end 2021-07-01`

## Grid

- `eta_critical`: `0.70, 0.75, 0.80`
- `eta_sustained_bars`: `3, 5, 8`
- `price_ext_sigma`: `1.8, 2.0, 2.2`
- `atr_expansion_ratio`: `1.2, 1.3, 1.4`
- `rsi_exhaustion_level`: `5, 8, 12`
- `hmm_min_prob_chop`: `0.30, 0.35, 0.40`
- `hmm_max_trend_prob`: `0.50, 0.60, 0.70`
- `min_reentry_cooldown_bars`: `0, 4, 8`

## Outputs

Write artifacts to:
- `data/audit/kepos_recalibration_train.json`
- `data/audit/kepos_recalibration_oos_bear.json`
- `data/audit/kepos_recalibration_oos_chop.json`
- `data/audit/kepos_recalibration_oos_recent.json`

## Execution

Base command:

```bash
python engines/kepos.py --basket bluechip --interval 15m --no-menu
```

Window commands:

```bash
python engines/kepos.py --basket bluechip --interval 15m --days 975 --end 2024-01-01 --no-menu
python engines/kepos.py --basket bluechip --interval 15m --days 360 --end 2023-01-01 --no-menu
python engines/kepos.py --basket bluechip --interval 15m --days 360 --end 2020-03-01 --no-menu
python engines/kepos.py --basket bluechip --interval 15m --days 360 --end 2026-01-01 --no-menu
```

Parameter injection rule:
- vary one frozen grid combination at a time
- record exact CLI and resulting run dir in the audit json

## Metrics

Track:
- Sharpe
- ROI
- MDD
- trade count
- pnl by symbol
- concentration of pnl

## Decision Rule

- `keep_experimental` if edge survives OOS and is not single-symbol dependent.
- `archive` if edge remains weak, unstable, or too concentrated.

## Notes

- If HMM/enrichment fails for one symbol, do not change shared run params.
- Do not reinterpret insufficient-sample as success.
