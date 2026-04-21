# Grid pre-registrado - PHI reopen 2026-04-21

- Universo: `BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT`
- Split fixo:
  - Train: `2023-01-01` -> `2024-01-01`
  - Test: `2024-01-01` -> `2025-01-01`
  - Holdout: `2025-01-01` -> `2026-04-21`
- Budget: 16 configs
- Mecanismo testado: continuation em majors liquidos com filtros simples e relaxados
- Campos fixos fora do grid:
  - `adx_min=10.0`
  - `wick_ratio_min=0.382`
  - `volume_mult=1.272`
  - `entry_mode="continuation"`

| # | cluster_min_confluences | cluster_atr_tolerance | omega_phi_entry | ema200_distance_atr |
|---|---|---|---|---|
| 1 | 1 | 0.5 | 0.382 | 0.200 |
| 2 | 1 | 0.5 | 0.382 | 0.382 |
| 3 | 1 | 0.5 | 0.500 | 0.200 |
| 4 | 1 | 0.5 | 0.500 | 0.382 |
| 5 | 1 | 1.0 | 0.382 | 0.200 |
| 6 | 1 | 1.0 | 0.382 | 0.382 |
| 7 | 1 | 1.0 | 0.500 | 0.200 |
| 8 | 1 | 1.0 | 0.500 | 0.382 |
| 9 | 2 | 0.5 | 0.382 | 0.200 |
| 10 | 2 | 0.5 | 0.382 | 0.382 |
| 11 | 2 | 0.5 | 0.500 | 0.200 |
| 12 | 2 | 0.5 | 0.500 | 0.382 |
| 13 | 2 | 1.0 | 0.382 | 0.200 |
| 14 | 2 | 1.0 | 0.382 | 0.382 |
| 15 | 2 | 1.0 | 0.500 | 0.200 |
| 16 | 2 | 1.0 | 0.500 | 0.382 |

## Regra de parada desta reabertura
Nao adicionar configs apos o primeiro run. Se nenhum candidato passar nos gates de train, a tese reaberta morre aqui.
