# Engine Validation Report

- Generated at: `2026-04-13T15:55:21`
- Days: `90`
- Basket: `default`
- Leverage: `1.0x`
- Python: `C:\Users\Joao\AppData\Local\Python\pythoncore-3.14-64\python.exe`

## Current Risk/Sizing Context

- `_wr()` is continuous/linear in `core/portfolio.py`.
- `position_size()` is the simplified 3-factor version in `core/portfolio.py`.

## Results

### CITADEL
- Status: `ok`
- Trades: `101`
- WR: `52.5%`
- PnL: `$-354.07`
- Sharpe: `-0.911`
- Sortino: `-1.090`
- MaxDD: `7.2%`
- Final equity: `$9645.93`
- HTML report present: `yes`
- Run dir: `data\runs\citadel_2026-04-13_1548`
- Notes: Backtest CLI supports --days/--basket/--leverage/--no-menu.

### DE SHAW
- Status: `failed`
- Notes: CLI supports --days/--basket/--no-menu for deterministic diagnostic runs.
- Failure summary: No valid cointegrated pairs found for the current 90d/default universe.
- Return code: `1`

### JUMP
- Status: `ok`
- Trades: `190`
- WR: `50.0%`
- PnL: `$-947.27`
- Sharpe: `-4.439`
- Sortino: `-5.334`
- MaxDD: `9.6%`
- Final equity: `$9052.73`
- Artifact: `data\mercurio\2026-04-13_1550\reports\mercurio_15m_v1.json`
- Notes: Interactive prompts accepted with default values.

### BRIDGEWATER
- Status: `failed`
- Notes: CLI supports --days/--basket/--no-menu for deterministic diagnostic runs.
- Failure summary: Run completed but produced no closed trades.
- Return code: `1`

### RENAISSANCE
- Status: `ok`
- Trades: `88`
- WR: `85.2%`
- PnL: `$346.14`
- Sharpe: `4.705`
- Sortino: `4.801`
- MaxDD: `0.6%`
- Final equity: `$10346.14`
- Artifact: `data\renaissance\2026-04-13_1554\reports\renaissance_15m_v1.json`
- Notes: Standalone backtest wrapper around scan_hermes().

### TWO SIGMA
- Status: `blocked`
- Notes: Blocked: requires trade history from 2+ validated engines; standalone script is advisory only.

### JANE STREET
- Status: `ok`
- Total opportunities: `241`
- Profitable count: `241`
- Average APR: `95.57%`
- Estimated monthly income on $1000: `$79.64`
- Best venue: `{'venue': 'mexc', 'avg_apr': 112.92, 'n': 74}`
- Worst venue: `{'venue': 'backpack', 'avg_apr': 40.99, 'n': 2}`
- Artifact: `data\arbitrage\2026-04-13_1555\reports\simulate_historical.json`
- Notes: Snapshot-based scanner report; not a trade backtest.
