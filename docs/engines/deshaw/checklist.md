# Engine Validation Checklist - DE SHAW

Atualizado automaticamente em 2026-04-20 16:58:06.

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
| DSH01_chop_only | -0.272 | -0.261 | 0.28 | 2 |
| DSH05_chop_only_no_grace | -0.272 | -0.261 | 0.28 | 2 |
| DSH06_chop_only_tighter | -0.272 | -0.261 | 0.28 | 2 |
| DSH07_chop_only_looser | -0.272 | -0.261 | 0.28 | 2 |
| DSH00_baseline | -0.612 | -0.456 | 2.27 | 62 |
| DSH02_hmm_looser | -0.612 | -0.456 | 2.27 | 62 |
| DSH03_hmm_tighter | -0.612 | -0.456 | 2.27 | 62 |
| DSH04_no_grace | -0.612 | -0.456 | 2.27 | 62 |

## Passo 5 - DSR

- n_trials: 8
- sharpe_best: -0.272
- sharpe_std: 0.182
- DSR p-value: 0.042
- Passou (> 0.95)? NAO

## Passo 6 - Top-3 em test

| rank | config | sharpe_train | sharpe_test | sortino_test |
|---|---|---|---|---|
| 1 | DSH01_chop_only | -0.272 |  |  |
| 2 | DSH05_chop_only_no_grace | -0.272 |  |  |
| 3 | DSH06_chop_only_tighter | -0.272 |  |  |

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
