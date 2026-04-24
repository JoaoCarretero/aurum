# Engine Validation Checklist - BRIDGEWATER

Atualizado automaticamente em 2026-04-21 19:18:23.

## Passo 1 - Hipotese mecanica

- [x] Hipotese registrada em `docs/engines/bridgewater/hypothesis.md`
- [x] Falsificacao escrita antes do grid

## Passo 2 - Split hardcoded

```python
TRAIN_END = "2026-04-01T19:00:00"
TEST_END = "2026-04-10"
HOLDOUT = "2026-04-10" ate "2026-04-20T19:00:00"
```

- [ ] Datas commitadas no runner da rodada
- [x] Datas absolutas definidas antes da bateria

## Passo 3 - Grid pre-registrado

- [x] Budget fechado em `docs/engines/bridgewater/grid.md`
- [ ] Commit feito antes da config #1

## Passo 4 - Resultados train

| # | Sharpe | Sortino | MDD | Trades |
|---|---|---|---|---|
| BW05_cooldown_4 | -5.756 | -6.135 | 0.380 | 5 |
| BW00_baseline | -1.033 | -1.402 | 0.380 | 7 |
| BW01_thresh_035 | -1.033 | -1.402 | 0.380 | 7 |
| BW02_thresh_040 | -1.033 | -1.402 | 0.380 | 7 |
| BW03_components_3 | -1.033 | -1.402 | 0.380 | 7 |
| BW04_health_on | -1.033 | -1.402 | 0.380 | 7 |
| BW06_thresh_035_components_3 | -1.033 | -1.402 | 0.380 | 7 |
| BW07_thresh_035_health_on | -1.033 | -1.402 | 0.380 | 7 |

## Passo 5 - DSR

- n_trials: 8
- sharpe_best: -5.756
- sharpe_std: 1.670
- DSR p-value: 0.000
- Passou (> 0.95)? NAO

## Passo 6 - Top-3 em test

| rank | config | sharpe_train | sharpe_test | sortino_test |
|---|---|---|---|---|
| 1 | BW05_cooldown_4 | -5.756 |  |  |
| 2 | BW00_baseline | -1.033 |  |  |
| 3 | BW01_thresh_035 | -1.033 |  |  |

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
