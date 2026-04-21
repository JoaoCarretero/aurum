# Engine Validation Checklist - BRIDGEWATER

Atualizado automaticamente em 2026-04-21 18:05:48.

## Passo 1 - Hipotese mecanica

- [x] Hipotese registrada em `docs/engines/bridgewater/hypothesis.md`
- [x] Falsificacao escrita antes do grid

## Passo 2 - Split hardcoded

```python
TRAIN_END = "2026-03-31"
TEST_END = "2026-04-10"
HOLDOUT = "2026-04-10" ate "2026-04-20"
```

- [ ] Datas commitadas no runner da rodada
- [x] Datas absolutas definidas antes da bateria

## Passo 3 - Grid pre-registrado

- [x] Budget fechado em `docs/engines/bridgewater/grid.md`
- [ ] Commit feito antes da config #1

## Passo 4 - Resultados train

| # | Sharpe | Sortino | MDD | Trades |
|---|---|---|---|---|
| BW04_health_on | 10.569 | 15.192 | 1.69 | 60 |
| BW07_thresh_035_health_on | 10.569 | 15.192 | 1.69 | 60 |
| BW00_baseline | 10.425 | 14.653 | 1.89 | 60 |
| BW01_thresh_035 | 10.425 | 14.653 | 1.89 | 60 |
| BW02_thresh_040 | 10.425 | 14.653 | 1.89 | 60 |
| BW03_components_3 | 10.425 | 14.653 | 1.89 | 60 |
| BW06_thresh_035_components_3 | 10.425 | 14.653 | 1.89 | 60 |
| BW05_cooldown_4 | 1.967 | 2.667 | 2.04 | 41 |

## Passo 5 - DSR

- n_trials: 8
- sharpe_best: 10.569
- sharpe_std: 3.006
- DSR p-value: 1.000
- Passou (> 0.95)? SIM

## Passo 6 - Top-3 em test

| rank | config | sharpe_train | sharpe_test | sortino_test |
|---|---|---|---|---|
| 1 | BW04_health_on | 10.569 |  |  |
| 2 | BW07_thresh_035_health_on | 10.569 |  |  |
| 3 | BW00_baseline | 10.425 |  |  |

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
