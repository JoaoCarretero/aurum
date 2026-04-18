# ORNSTEIN v2 — Validation Report (2026-04-17)

> Resultado da execução do protocolo em `docs/superpowers/specs/2026-04-17-ornstein-v2-validation-design.md`.

## Contexto

Preset `robust` + wrapper `engines/ornstein_v2.py` foram adicionados na
sessão Claude+Codex de 2026-04-17. 5 params novos em `OrnsteinParams`.
Codex rodou `ornstein_v2 --basket bluechip_active --days 360` e obteve
0 trades. Este doc valida/arquiva a variante com evidência honesta.

## Etapa 1 — Baseline (v1 default / bluechip_active / 360d)

Run dir: `PLACEHOLDER_BASELINE_RUN_DIR`

| Métrica | Valor |
|---------|-------|
| N_trades | — |
| Sharpe | — |
| MaxDD | — |
| WinRate | — |
| Expectancy (R) | — |
| Total return | — |
| DSR (n_trials=1) | — |

## Etapa 2 — Reprodução do Codex (v2 robust / bluechip_active / 360d)

Run dir: `PLACEHOLDER_V2_REPRO_RUN_DIR`

| Métrica | Valor |
|---------|-------|
| N_trades | — |
| Top 5 vetos | — |

Distribuição completa de vetos:

```
(colar output do _print_summary aqui)
```

## Etapa 3 — Ablation (majors / 180d)

Universo: `BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`.
CSV: `data/ornstein_v2/ablation_2026-04-17/results.csv`.

| Variant | N_trades | Sharpe | MaxDD | WinRate | Δ Sharpe vs B_MAJORS |
|---------|----------|--------|-------|---------|----------------------|
| B_MAJORS | — | — | — | — | 0.00 |
| R0 robust_full | — | — | — | — | — |
| R1 no_hurst | — | — | — | — | — |
| R2 no_bb | — | — | — | — | — |
| R3 no_min_dev | — | — | — | — | — |
| R4 no_target_dist | — | — | — | — | — |
| R5 no_div_flip | — | — | — | — | — |
| R6 no_stop_lock | — | — | — | — | — |

Best variant por score `Sharpe / (1 + MaxDD)` com `N_trades >= 20`: PLACEHOLDER.

## Etapa 4 — Final comparison (best variant / bluechip_active / 360d)

Run dir: `PLACEHOLDER_FINAL_RUN_DIR`

| Métrica | v1 default (Etapa 1) | best variant |
|---------|----------------------|---------------|
| N_trades | — | — |
| Sharpe | — | — |
| MaxDD | — | — |
| DSR (n_trials=7) | — | — |

## Decisão

PLACEHOLDER: promote | remove_guard:X | archive

Justificativa em 1-3 parágrafos quando preenchido.

Próximos passos:

- (se promote) overfit_audit 6/6 em janelas OOS distintas via `tools/ornstein_overfit_audit.py`.
- (se remove_guard) atualizar preset `robust` removendo guard X, re-testar.
- (se archive) commit de revert completo.
