# Engine Validation Checklist - MEDALLION

Atualizado automaticamente em 2026-04-22 15:40:01.

## Passo 1 - Hipotese mecanica

- [x] Hipotese registrada em `docs/engines/medallion/hypothesis.md`
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

- [x] Budget fechado em `docs/engines/medallion/grid.md`
- [ ] Commit feito antes da config #1

## Passo 4 - Resultados train

| # | Sharpe | Sortino | MDD | Trades |
|---|---|---|---|---|
| MED02_entry_looser | 1.961 | 5.576 | 13.310 | 511 |
| MED04_threshold_looser | 1.863 | 4.965 | 12.670 | 535 |
| MED00_baseline | 1.673 | 4.474 | 12.430 | 531 |
| MED05_components_tighter | 1.673 | 4.474 | 12.430 | 531 |
| MED07_hmm_exit_earlier | 1.673 | 4.474 | 14.730 | 531 |
| MED01_entry_tighter | 1.656 | 5.193 | 14.400 | 475 |
| MED06_kelly_lower | 1.624 | 3.832 | 12.940 | 574 |
| MED03_threshold_tighter | 0.822 | 2.450 | 17.880 | 459 |

## Passo 5 - DSR

- n_trials: 8
- sharpe_best: 1.961
- sharpe_std: 0.343
- DSR p-value: 1.000
- Passou (> 0.95)? SIM

## Passo 6 - Top-3 em test

| rank | config | sharpe_train | sharpe_test | sortino_test |
|---|---|---|---|---|
| 1 | MED02_entry_looser | 1.961 | -3.469 | -9.708 |
| 2 | MED04_threshold_looser | 1.863 | -4.369 | -11.796 |
| 3 | MED00_baseline | 1.673 | -4.319 | -12.131 |

- Pior Sharpe do top-3: -4.369
- Passou (> 1.0)? NAO

## Passo 7 - Holdout

- Config escolhido: MED04_threshold_looser
- Sharpe holdout: -2.431
- Passou (> 0.8)? NAO

## Passo 8 - Paper forward

- Start:
- End:
- Sharpe paper:
- Passou (> 50% do holdout)? SIM / NAO

## Decisao final

- [ ] FROZEN
- [x] ARQUIVADO
- [x] Motivo preenchido

**Motivo (2026-04-22):** Overfit canonico. 7/8 configs passaram DSR train
com folga (Sharpe 1.6-1.96, DSR p=1.0), mas **8/8 configs NEGATIVOS em
test** (Sharpe -3.4 a -4.8) e **8/8 negativos em holdout** (-1.8 a -3.0).
Train gate PASSOU, test gate FALHOU catastroficamente. Engine bem
calibrado in-sample, zero edge out-of-sample. Nao deve ir para paper/live.
Ver `docs/engines/medallion/audit_verdict.md`.
