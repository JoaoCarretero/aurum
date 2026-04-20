# Engine Validation Checklist - KEPOS

Copiado e preenchido em 2026-04-20 antes de nova rodada.

## Passo 1 - Hipotese mecanica

- [x] Hipotese registrada em `docs/engines/kepos/hypothesis.md`
- [x] Falsificacao escrita antes do grid

## Passo 2 - Split hardcoded

```python
TRAIN_END = "2024-01-01"
TEST_END = "2025-01-01"
HOLDOUT = "2025-01-01" ate "2026-04-20"
```

- [ ] Datas commitadas no runner da rodada
- [x] Datas absolutas definidas antes da bateria

## Passo 3 - Grid pre-registrado

- [x] Budget fechado em `docs/engines/kepos/grid.md`
- [ ] Commit feito antes da config #1

## Passo 4 - Resultados train

| # | Sharpe | Sortino | MDD | Trades |
|---|---|---|---|---|
| KEP00_baseline |  |  |  |  |
| KEP01_rsi_looser |  |  |  |  |
| KEP02_rsi_tighter |  |  |  |  |
| KEP03_cooldown_short |  |  |  |  |
| KEP04_cooldown_long |  |  |  |  |
| KEP05_hmm_looser |  |  |  |  |
| KEP06_hmm_tighter |  |  |  |  |
| KEP07_takeprofit_longer |  |  |  |  |

## Passo 5 - DSR

- n_trials:
- sharpe_best:
- sharpe_std:
- DSR p-value:
- Passou (> 0.95)? SIM / NAO

## Passo 6 - Top-3 em test

| rank | config | sharpe_train | sharpe_test | sortino_test |
|---|---|---|---|---|
| 1 |  |  |  |  |
| 2 |  |  |  |  |
| 3 |  |  |  |  |

- Pior Sharpe do top-3:
- Passou (> 1.0)? SIM / NAO

## Passo 7 - Holdout

- Config escolhido:
- Sharpe holdout:
- Passou (> 0.8)? SIM / NAO

## Passo 8 - Paper forward

- Start:
- End:
- Sharpe paper:
- Passou (> 50% do holdout)? SIM / NAO

## Decisao final

- [ ] FROZEN
- [ ] ARQUIVADO
- [ ] Motivo preenchido
