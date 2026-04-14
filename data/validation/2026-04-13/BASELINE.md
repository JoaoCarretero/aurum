# Baseline Checkpoint

- Date: `2026-04-13`
- Commit anchor: `6fae1e2`
- Source report: `data/validation/2026-04-13/REPORT.md`
- Master battery: `data/param_search/2026-04-13/battery_full.csv`
- Validation command: `python tools/engine_validation.py --days 90 --basket default --leverage 1.0`
- Smoke test: `172/172`

## Engine Status

### CITADEL
- Status: `edge confirmed (regime-adaptive)`
- Best config: `RISK_SCALE_BY_REGIME = {BEAR:1.0, BULL:0.30, CHOP:0.50}` @ 15m / 180d / default basket
- Trades: `256`
- WR: `62.5%`
- PnL: `$3,119.02`
- Sharpe: `4.434`
- Sortino: `6.303`
- MaxDD: `4.87%`
- MC% positive: `99.4%`
- Note: default config (BULL:0.85) produced Sharpe 0.39. Regime-adaptive applied as default in `ENGINE_RISK_SCALE_BY_REGIME["CITADEL"]`.

### DE SHAW
- Status: `operational, no edge in current universe`
- Best config: `stop=2.0 entry=2.0 @ 4h / 90d / default` — Sharpe 1.27, 92 trades, WR 18.5%, but MC% only 63.5
- Bluechip fallback: `4h / 90d / bluechip` — Sharpe 0.23, 232 trades, MC% 56.4
- Note: engine runs end-to-end after fixes; cointegration pair set is weak on current altcoin universe. Rolling cointegration is roadmap.

### JUMP
- Status: `operational, no edge`
- Best config: `majors @ 15m / 90d` — 17 trades, Sharpe -4.22
- Note: sentiment/flow signals not producing tradable edge. Classify as research-lab until ML meta-layer.

### BRIDGEWATER
- Status: `edge confirmed (1h)`
- Best config: `default basket @ 1h / 90d` — Sharpe 5.06, 269 trades, WR 63.2%, MC% 94.8
- Extended validation: `bluechip @ 1h / 180d` — Sharpe 7.34, 2090 trades, MC% 99
- OOS (formal walk-forward): `1h / 180d` FULL Sharpe 4.97, OOS 1.78 on 99 trades
- Note: 15m config is decisively negative (Sharpe -1.95). 1h applied as default via `ENGINE_INTERVALS["BRIDGEWATER"]`.

### RENAISSANCE
- Status: `edge confirmed`
- Best config: `default @ 15m / 180d` — Sharpe 6.58, 68 trades, WR 88.2%, MC% 100
- Note: `renaissance_audit.md` flagged a reporting inconsistency (`85.23%` headline vs `61.36%` audited) — review before committing live capital.

### TWO SIGMA
- Status: `blocked by design`
- Note: meta-ensemble depends on trade history from 2+ validated engines; does not emit standalone backtest metrics.

### JANE STREET
- Status: `operational (scanner only)`
- Mode: `scanner report`
- Total opportunities: `241` — all profitable at snapshot
- Avg APR: `95.57%` · Est. monthly on $1k: `$79.64`
- Note: not a trade backtest; operational delta-neutral funding scanner.

## Snapshot Summary

- **Edge confirmed**: `CITADEL` (regime-adaptive), `BRIDGEWATER` (1h), `RENAISSANCE`
- **Operational, no edge**: `DE SHAW`, `JUMP`
- **Blocked by design**: `TWO SIGMA`
- **Scanner**: `JANE STREET`
- **Audit flag**: `RENAISSANCE` win_rate reporting

## Applied Changes (this checkpoint)

- `ENGINE_INTERVALS["BRIDGEWATER"] = "1h"` — thoth.py reads per-engine TF override
- `ENGINE_RISK_SCALE_BY_REGIME["CITADEL"]` — backtest.py + live.py pass adaptive regime scale
- `position_size()` now accepts `regime_scale` kwarg; default behavior unchanged for other engines

## Next Constraint

- Do not further optimize thresholds/weights from this checkpoint without new battery evidence.
- Future battery results should feed into `ENGINE_INTERVALS` / `ENGINE_RISK_SCALE_BY_REGIME` dicts in `config/params.py`.
