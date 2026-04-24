# Migration 001 — live_runs table — APPLIED

- **Date:** 2026-04-21 01:59 UTC
- **Branch:** feat/phi-engine
- **Applied by:** Claude Opus 4.7 + Joao (execution gate)

## Schema

Table `live_runs` created in `data/aurum.db` with 15 cols + 2 indexes
(see `tools/maintenance/migrations/migration_001_live_runs.py`).

## Cleanup executed

12 moves via `tools/maintenance/cleanup_data_layout.py --apply`:

Research dirs → `data/_archive/research/`:
- `_bridgewater_compare`
- `_bridgewater_regime_filter`
- `_bridgewater_rolling_compare`
- `anti_overfit`
- `param_search`
- `perf_profile`
- `validation`

Legacy `data/runs/` → engine dirs:
- `runs/citadel_2026-04-18_153116` → `citadel/`
- `runs/citadel_2026-04-18_153218` → `citadel/`
- `runs/citadel_2026-04-18_153309` → `citadel/`
- `runs/citadel_2026-04-19_153553` → `citadel/`

DB archived:
- `nexus.db` + `nexus.db-shm` + `nexus.db-wal` → `data/_archive/db/nexus.db.2026-04-21_015945*`

## Not moved (still in `data/runs/`)

Six `multistrategy_*` dirs were skipped because `multistrategy` is not in
`_ENGINES_PRESERVED`. They stay at their original path pending a decision
on whether to:
1. Add `multistrategy` to the preserved list and consolidate under
   `data/multistrategy/`, or
2. Archive them to `data/_archive/multistrategy/`, or
3. Leave as-is.

## Backfill

`tools/maintenance/backfill_live_runs.py --apply` populated `live_runs`
with **408 rows** from existing dirs:

- live: 299 (from `data/live/` + `data/millennium_live/`)
- paper: 48 (from `data/millennium_paper/`)
- shadow: 61 (from `data/millennium_shadow/`)
- demo/testnet: 0

All marked `status=stopped` at backfill time (no active runner processes).
VPS paper/shadow runtime hooks will update rows to `running` on next tick.

## Verification

- Smoke test: 178/178 passed
- `data/_archive/` total: 26 MB
- Migration idempotent — safe to re-run

## Rollback

Every move printed an `[undo]` command. Redirect output to a file when
running `--apply` in the future to save the rollback manifest.
