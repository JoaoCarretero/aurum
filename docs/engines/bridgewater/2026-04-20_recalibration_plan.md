# BRIDGEWATER Recalibration Plan

Date: 2026-04-20
Engine: `bridgewater`
Status: Draft

## Goal

Re-evaluate BRIDGEWATER after the recent preset/cost-model corrections and determine whether the engine still has defensible OOS edge.

## Hypothesis

Cross-sectional sentiment contrarian can work only under stricter filtering:
- higher agreement threshold
- tighter component count
- regime restriction
- optional symbol-health gating

## Frozen Mechanism

Do not change:
- signal composition
- trade lifecycle
- report logic

Only tune:
- `min_components`
- `min_dir_thresh`
- `allowed_macro_regimes`
- `post_trade_cooldown_bars`
- `symbol_health`

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

- `min_components`: `2, 3, 4`
- `min_dir_thresh`: `0.30, 0.35, 0.40, 0.45`
- `allowed_macro_regimes`: `None`, `BEAR,CHOP`, `CHOP`
- `post_trade_cooldown_bars`: `0, 4, 8`
- `symbol_health`: `off, on`

## Outputs

Write artifacts to:
- `data/audit/bridgewater_recalibration_train.json`
- `data/audit/bridgewater_recalibration_oos_bear.json`
- `data/audit/bridgewater_recalibration_oos_chop.json`
- `data/audit/bridgewater_recalibration_oos_recent.json`

## Execution

Base command:

```bash
python engines/bridgewater.py --basket bluechip --interval 1h --no-menu
```

Window commands:

```bash
python engines/bridgewater.py --basket bluechip --interval 1h --days 975 --end 2024-01-01 --no-menu
python engines/bridgewater.py --basket bluechip --interval 1h --days 360 --end 2023-01-01 --no-menu
python engines/bridgewater.py --basket bluechip --interval 1h --days 360 --end 2020-03-01 --no-menu
python engines/bridgewater.py --basket bluechip --interval 1h --days 360 --end 2026-01-01 --no-menu
```

Parameter injection rule:
- vary one frozen grid combination at a time
- record exact CLI and resulting run dir in the audit json

## Selection Rule

1. Rank on train only.
2. Carry top 3 to OOS.
3. Reject if OOS Sharpe/DD/trade count are not acceptable.

## Decision Rule

- `keep_quarantine` if OOS is defensible and stable.
- `archive` if results collapse after honest recalibration.

## Notes

- Do not modify the grid after seeing OOS.
- If cost-model changes again, restart the process from scratch.
