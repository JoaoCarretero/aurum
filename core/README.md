# `core/` — módulos reutilizáveis do AURUM

Pós-reorganização Lane 1 (2026-04-18). Todo path antigo (`core/X.py`)
continua importável via **shim `sys.modules`** — código legado e
backtests calibrados não quebram.

## Subpacotes (6)

| Subpacote | Papel | Módulos |
|---|---|---|
| `core/data/` | Ingestão de mercado | base, cache, connections, exchange_api, htf, htf_filter, market_data, transport |
| `core/risk/` | Proteção de capital | audit_trail, failure_policy, key_store, **portfolio** ⚠️, risk_gates |
| `core/ops/` | Infra de execução | db, engine_base, engine_picker, fixture_capture, fs, health, mt5, persistence, proc, run_manager, site_runner, versioned_state |
| `core/ui/` | Widgets do launcher | alchemy_ui, funding_scanner, portfolio_monitor, ui_palette |
| `core/arb/` | Arbitragem | alchemy_state, arb_scoring |
| `core/analysis/` | Telemetria/fitness | analysis_export, evolution |

⚠️ `core/risk/portfolio.py` é **CORE PROTEGIDO** — ver CLAUDE.md.

## Módulos FLAT (em `core/` raiz)

Ficam fora de subpacote por **design**, não por esquecimento:

### Protegidos (CLAUDE.md — não mexer sem aprovação)

- `core/signals.py` — `decide_direction`, `calc_levels`, `label_trade`
- `core/indicators.py` — EMA, RSI, ATR, BB, `swing_structure`, `omega`

### Signal-adjacent (FLAT por acoplamento ao pipeline de sinais)

- `core/chronos.py` — HMM regime, GARCH vol, Hurst
- `core/harmonics.py` — harmonic patterns (RENAISSANCE)
- `core/hawkes.py` — Hawkes intensity (KEPOS)
- `core/sentiment.py` — funding, OI, LS

### Por quê signals/indicators NÃO viraram subpacote

`core/data/htf.py` faz **runtime monkey-patch** via
`sys.modules["core.signals"].CHOP_S21 = ...` antes de chamar
`indicators()`, `swing_structure()`, `omega()`. Mover esses arquivos
pra subpacote quebra o contrato — as patches cairiam no namespace do
`__init__.py`, não no namespace onde as funções leem as constantes.

Tentativa alternativa com shim via `importlib` também falhou: Python
3.14 escolhe o arquivo `.py` sobre o dir homônimo, tornando o shim
dead-code.

Decisão: signals/indicators **ficam FLAT** pra preservar 100% da
semântica de trading. Os outros signal-adjacent (chronos, harmonics,
hawkes, sentiment) seguem a mesma regra por precaução — calibração dos
engines depende do comportamento atual.

Referência: commit `dd6c14d` (removeu subpacote `core/signals/`
dead-code) + session log `docs/sessions/2026-04-18_1056.md`.

## Import policy

```python
# ambos funcionam — o primeiro é canônico pós-Lane 1
from core.data import cache
from core import cache  # shim, redireciona via sys.modules
```

Código novo **deve** usar o caminho canônico do subpacote. Shims
existem pra estabilidade operacional, não pra preferência.

## Quebrou algo depois da Lane 1?

- Suite `pytest` completa verde (1151 passed, 7 skipped)
- Smoke test 178/178 em todos os checkpoints
- Backtest CITADEL 30d idêntico ao baseline pré-Lane 1

Se um import parar de funcionar, provavelmente é cache Python.
Deletar `__pycache__` recursivamente resolve na maioria dos casos.
