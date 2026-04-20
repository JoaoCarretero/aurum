# DE SHAW Recalibration Plan

Date: 2026-04-20
Engine: `deshaw`
Status: Draft

## Goal

Test whether DE SHAW only works when pair entries are restricted to favorable macro/HMM regimes and stricter revalidation discipline.

## Hypothesis

Pairs mean-reversion is only viable in:
- `CHOP`
- possibly `CHOP+BULL`

And should be vetoed when:
- HMM chop confidence is weak
- trend-state confidence is too strong

## Frozen Mechanism

Do not change:
- pair discovery method
- spread math
- pnl math
- execution timing

Only tune:
- `allowed_macro_entry`
- `min_hmm_chop_prob`
- `max_hmm_trend_prob`
- `max_revalidation_misses`

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

- `allowed_macro_entry`: `CHOP`, `CHOP+BULL`
- `min_hmm_chop_prob`: `0.30, 0.35, 0.40, 0.45`
- `max_hmm_trend_prob`: `0.45, 0.55, 0.65`
- `max_revalidation_misses`: `1, 2`

## Outputs

Write artifacts to:
- `data/audit/deshaw_recalibration_train.json`
- `data/audit/deshaw_recalibration_oos_bear.json`
- `data/audit/deshaw_recalibration_oos_chop.json`
- `data/audit/deshaw_recalibration_oos_recent.json`

## Execution

Base command:

```bash
python engines/deshaw.py --basket bluechip --interval 1h --no-menu
```

Window commands:

```bash
python engines/deshaw.py --basket bluechip --interval 1h --days 975 --end 2024-01-01 --no-menu
python engines/deshaw.py --basket bluechip --interval 1h --days 360 --end 2023-01-01 --no-menu
python engines/deshaw.py --basket bluechip --interval 1h --days 360 --end 2020-03-01 --no-menu
python engines/deshaw.py --basket bluechip --interval 1h --days 360 --end 2026-01-01 --no-menu
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
- veto breakdown
- regime distribution

## Decision Rule

- `keep_experimental` if OOS improves without trade-count collapse.
- `archive` if the engine remains regime-fragile or collapses OOS.

## Notes

- Do not loosen the hypothesis after bad OOS.
- Revalidation grace must remain explicit and documented.
