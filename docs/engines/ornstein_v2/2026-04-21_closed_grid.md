# ORNSTEIN closed grid - 2026-04-21

Registrado antes da primeira execucao desta sessao.

## Split hardcoded

- Universo fixo: `BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`
- Train: 180d terminando em `2025-10-21`
- Test: 90d terminando em `2026-01-19`
- Holdout: 92d terminando em `2026-04-21`

## Budget

- 5 configs fechados
- Nenhum config novo entra depois da primeira rodada train

## Grid pre-registrado

| ID | Base | Overrides | Intencao |
|---|---|---|---|
| O00 | `default` | none | baseline historico; espera-se sample muito baixo |
| O01 | `exploratory` | none | baseline permissivo do proprio engine |
| O02 | `exploratory` | `disable_divergence=True` | testar direcao pelo desvio assinado + bateria estatistica |
| O03 | `exploratory` | `disable_divergence=True`, `rsi_long_max=35`, `rsi_short_min=65`, `omega_entry=55` | versao menos frouxa do O02 |
| O04 | `exploratory` | `disable_divergence=True`, `adf_pvalue_max=0.10`, `halflife_max=50`, `omega_entry=60` | pedir mais disciplina estatistica apos remover divergencia |

## Regras de decisao

1. Rodar os 5 configs so no train.
2. Calcular Sharpe, PF, expectancy e DSR com `n_trials=5`.
3. Se menos de 3 configs tiverem `N >= 30`, arquiva por falta de base.
4. Se o melhor DSR do train nao passar, arquiva.
5. Se passar, levar top-3 por DSR para test e reportar o pior dos 3.
6. So o config sobrevivente unico vai para holdout.

## Resultados

Preenchido apos a bateria desta sessao.
