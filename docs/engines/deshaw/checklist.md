# Engine Validation Checklist - DE SHAW

Atualizado automaticamente em 2026-04-21 20:16:57.

## Passo 1 - Hipotese mecanica

- [x] Hipotese registrada em `docs/engines/deshaw/hypothesis.md`
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

- [x] Budget fechado em `docs/engines/deshaw/grid.md`
- [ ] Commit feito antes da config #1

## Passo 4 - Resultados train

| # | Sharpe | Sortino | MDD | Trades |
|---|---|---|---|---|
| DSH01_chop_only | -0.460 | -0.362 | 0.380 | 4 |
| DSH00_baseline | -0.726 | -0.484 | 4.530 | 96 |

## Passo 5 - DSR

- n_trials: 8
- sharpe_best: -0.460
- sharpe_std: 0.188
- DSR p-value: 0.000
- Passou (> 0.95)? NAO

## Passo 6 - Top-3 em test

| rank | config | sharpe_train | sharpe_test | sortino_test |
|---|---|---|---|---|
|  |  |  |  |  |

- Pior Sharpe do top-3: 
- Passou (> 1.0)? PENDENTE

## Passo 7 - Holdout

- Config escolhido: 
- Sharpe holdout: 
- Passou (> 0.8)? PENDENTE

## Passo 8 - Paper forward

- Start:
- End:
- Sharpe paper:
- Passou (> 50% do holdout)? SIM / NAO

## Decisao final

- [ ] FROZEN
- [ ] ARQUIVADO
- [ ] Motivo preenchido
