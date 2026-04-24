# Grid pre-registrado — SUPERTREND FUT

**Registrada:** 2026-04-22
**Engine:** `supertrend_futures`
**Budget:** 9 configs (fixo, não expandir)
**Mecanismo:** trend-following com tripla confluência Supertrend (params hyperopt fiel ao lab freqtrade, não grid-searched)

---

## Split fixo

- **Train:** `2022-01-01` → `2024-01-01` (24 meses, inclui bear 2022)
- **Test:** `2024-01-01` → `2025-01-01` (12 meses, bull + Q4 stress)
- **Holdout:** `2025-01-01` → `2026-04-22` (≈16 meses)

## Universo

`BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT` (5 majors alta liquidez)

## Timeframe fixo

1h (fiel lab freqtrade, não grid-searched)

## Dimensões do grid

Só R:R (stoploss × initial target). Os 12 params Supertrend (6 buy + 6 sell)
ficam nos defaults hyperopt freqtrade. Justificativa: o mecanismo de
entrada/saída já foi validado externamente; o que varia aqui é só o "leverage
efetivo" do trade via stop/target, que afeta expectancy diretamente.

## Campos fixos fora do grid

| Param | Valor | Fonte |
|---|---|---|
| `SUPERTREND_BUY_M1/P1` | 4 / 8 | freqtrade hyperopt |
| `SUPERTREND_BUY_M2/P2` | 7 / 9 | freqtrade hyperopt |
| `SUPERTREND_BUY_M3/P3` | 1 / 8 | freqtrade hyperopt |
| `SUPERTREND_SELL_M1/P1` | 1 / 16 | freqtrade hyperopt |
| `SUPERTREND_SELL_M2/P2` | 3 / 18 | freqtrade hyperopt |
| `SUPERTREND_SELL_M3/P3` | 6 / 18 | freqtrade hyperopt |
| `LEVERAGE` | 2.0 | lab externo |
| `MAX_HOLD_BARS` | 120 | 5 dias @ 1h |
| `INTERVAL` | "1h" | fiel lab |

## Grid (9 configs)

| # | STOPLOSS_PCT | INITIAL_ROI_PCT | Notas |
|---|---|---|---|
| 1 | 0.20 | 0.08 | stop apertado, target curto (R:R 0.4) |
| 2 | 0.20 | 0.10 | stop apertado, target freqtrade (R:R 0.5) |
| 3 | 0.20 | 0.15 | stop apertado, target wide (R:R 0.75) |
| 4 | 0.265 | 0.08 | **STOP DEFAULT freqtrade**, target curto (R:R 0.30) |
| 5 | 0.265 | 0.10 | **DEFAULT FREQTRADE** (baseline) |
| 6 | 0.265 | 0.15 | default stop, target wide (R:R 0.57) |
| 7 | 0.35 | 0.08 | stop largo, target curto (R:R 0.23) |
| 8 | 0.35 | 0.10 | stop largo, target default (R:R 0.29) |
| 9 | 0.35 | 0.15 | stop largo, target wide (R:R 0.43) |

## Regra de parada desta bateria

Não adicionar configs após o primeiro run. Se nenhum candidato passar nos
gates de train (DSR p-value ≥ 0.95 **E** deflated Sharpe ≥ 1.5), **a tese
reaberta morre aqui** — arquiva engine como `EXPERIMENTAL_SLUGS` (stage
permanece "research" mas `quarantined_by_oos=True`).

## Gates

| Etapa | Métrica | Threshold |
|---|---|---|
| Train | DSR deflated Sharpe | ≥ 1.5 |
| Train | DSR p-value | ≥ 0.95 |
| Test | pior-de-top-3 Sharpe | ≥ 1.0 |
| Holdout | Sharpe single-config chosen | ≥ 0.8 |
