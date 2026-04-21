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

### Comandos

```powershell
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -m engines.ornstein --preset default --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --days 180 --end 2025-10-21 --no-menu
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -m engines.ornstein --preset exploratory --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --days 180 --end 2025-10-21 --out data/ornstein_grid/O01 --no-menu
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -m engines.ornstein --preset exploratory --disable-divergence --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --days 180 --end 2025-10-21 --out data/ornstein_grid/O02 --no-menu
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -m engines.ornstein --preset exploratory --disable-divergence --rsi-long-max 35 --rsi-short-min 65 --omega-entry 55 --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --days 180 --end 2025-10-21 --out data/ornstein_grid/O03 --no-menu
& 'C:\Program Files\FreeCAD 1.1\bin\python.exe' -m engines.ornstein --preset exploratory --disable-divergence --adf-pvalue 0.10 --halflife-max 50 --omega-entry 60 --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --days 180 --end 2025-10-21 --out data/ornstein_grid/O04 --no-menu
```

### Train results

| ID | N | Sharpe | PF | Exp(R) | MaxDD | Top vetos / leitura |
|---|---:|---:|---:|---:|---:|---|
| O00 | 0 | 0.000 | 0.000 | 0.000 | 0.00% | `no_divergence 42835`, `rsi_block 39833`, `hurst_block 4801` |
| O01 | 2115 | -31.979 | 0.307 | -0.468 | 8.92% | sample abriu, mas virou anti-edge severo; `rsi_block 36494`, `no_divergence 15840`, `adf_block 14799` |
| O02 | 0 | 0.000 | 0.000 | 0.000 | 0.00% | `disable_divergence` funcional, mas ainda travado por `rsi_block 55030`, `adf_block 16878`, `omega_low 10526` |
| O03 | 0 | 0.000 | 0.000 | 0.000 | 0.00% | versao menos frouxa de O02 piora o choke; `rsi_block 71406` domina |
| O04 | 0 | 0.000 | 0.000 | 0.000 | 0.00% | relaxar ADF e half-life nao salva; continua sem trades |

### DSR e promocao

- `n_trials = 5`
- Menos de 3 configs com `N >= 30`
- Melhor config por Sharpe com sample foi O01, mas com Sharpe fortemente negativo
- DSR util para promocao: `N/A`, porque nao ha candidato com edge positivo nem base minima para top-3

### Decisao

**ARCHIVE.**

Justificativa:

1. A hipotese central foi falsificada no train. Tornar `disable_divergence`
   funcional nao revelou pocket mean-reverting robusto.
2. O engine continua preso no mesmo binario observado em 2026-04-17/18:
   filtro apertado = `0 trades`; filtro solto = muito trade ruim.
3. A regra de parada do protocolo disparou antes de test/holdout. Rodar
   OOS agora seria desrespeitar o desenho pre-registrado.
