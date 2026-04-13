# Baseline Checkpoint

- Date: `2026-04-13`
- Commit: `613001d`
- Source report: `data/validation/2026-04-13/REPORT.md`
- Validation command: `python tools/engine_validation.py --days 90 --basket default --leverage 1.0`
- Smoke test: `not rerun in this checkpoint`

## Engine Status

### CITADEL
- Status: `ok`
- Trades: `101`
- WR: `52.5%`
- PnL: `$-354.07`
- Sharpe: `-0.911`
- Sortino: `-1.090`
- MaxDD: `7.2%`
- HTML report: `generated`
- Note: operational, but currently negative and over-filtered relative to the original mission context.

### DE SHAW
- Status: `failed`
- Result: `0` valid cointegrated pairs out of `55` tested on `90d/default`
- Note: engine runs, fetches data, and completes the scan, but does not produce a tradable pair set in the current universe/window.

### JUMP
- Status: `ok`
- Trades: `190`
- WR: `50.0%`
- PnL: `$-947.27`
- Sharpe: `-4.439`
- Sortino: `-5.334`
- MaxDD: `9.6%`
- Note: operational after UTF-8 stdout/stderr hardening on Windows.

### BRIDGEWATER
- Status: `failed`
- Result: `0` closed trades
- Note: engine runs but external OI fetch still returns `HTTP 202` / timeout errors for multiple symbols, so the run ends without realizable trades.

### RENAISSANCE
- Status: `ok`
- Trades: `88`
- WR: `85.2%`
- PnL: `$346.14`
- Sharpe: `4.705`
- Sortino: `4.801`
- MaxDD: `0.6%`
- Note: first standalone backtest entrypoint is now operational.

### TWO SIGMA
- Status: `blocked`
- Note: meta-ensemble depends on pre-existing trade history from `2+` validated engines and does not emit comparable standalone backtest metrics.

### JANE STREET
- Status: `ok`
- Mode: `scanner report`
- Total opportunities: `241`
- Profitable count: `241`
- Average APR: `95.57%`
- Estimated monthly income on `$1000`: `$79.64`
- Best venue: `mexc`
- Worst venue: `backpack`
- Note: this is an operational snapshot scanner, not a trade backtest.

## Snapshot Summary

- Operational: `CITADEL`, `JUMP`, `RENAISSANCE`, `JANE STREET`
- Diagnostic failure: `DE SHAW`, `BRIDGEWATER`
- Blocked by design: `TWO SIGMA`

## Next Constraint

- Do not optimize thresholds, weights, or sizing from this checkpoint.
- Use this snapshot as the comparison point for future engine-unblocking work.
