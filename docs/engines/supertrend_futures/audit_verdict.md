# SUPERTREND FUT — Overfit Audit Verdict

**Data:** 2026-04-22
**Engine:** `supertrend_futures` v1.0 (port FSupertrendStrategy freqtrade)
**Verdict:** **ARCHIVE** (added to `EXPERIMENTAL_SLUGS`)
**Stopped at:** Passo 5 (train gate)

---

## Setup

- **Protocolo:** `docs/methodology/anti_overfit_protocol.md` 8-passos
- **Grid:** 9 configs (stop × roi), `docs/engines/supertrend_futures/grid.md`
- **Universe:** BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT (5 majors)
- **TF:** 1h · **Leverage:** 2x · **CAN_SHORT:** True
- **Splits:**
  - Train: 2022-01-01 → 2024-01-01 (730d, inclui bear 2022)
  - Test: 2024-01-01 → 2025-01-01
  - Holdout: 2025-01-01 → 2026-04-22
- **Bateria:** `tools/batteries/supertrend_audit.py`
- **Report:** `data/supertrend_futures/audit/supertrend_audit_2026-04-22_145107.json`

---

## Resultado (train-only, gates falharam)

| cfg | stop | roi | trades | sharpe | defl_sh | dsr_p | pnl |
|---|---|---|---|---|---|---|---|
| sf_08 | 0.350 | 0.100 | 4750 | **-0.071** | -0.346 | 0.000 | -$4,583 |
| sf_05 | 0.265 | 0.100 | 4751 | -0.102 | -0.377 | 0.000 | -$6,594 |
| sf_02 | 0.200 | 0.100 | 4761 | -0.239 | -0.514 | 0.000 | -$15,526 |
| sf_06 | 0.265 | 0.150 | 4610 | -0.285 | -0.560 | 0.000 | -$18,708 |
| sf_03 | 0.200 | 0.150 | 4614 | -0.318 | -0.593 | 0.000 | -$20,806 |
| sf_09 | 0.350 | 0.150 | 4609 | -0.359 | -0.634 | 0.000 | -$24,071 |
| sf_07 | 0.350 | 0.080 | 4846 | -0.467 | -0.742 | 0.000 | -$29,529 |
| sf_04 | 0.265 | 0.080 | 4847 | -0.483 | -0.758 | 0.000 | -$30,379 |
| sf_01 | 0.200 | 0.080 | 4857 | -0.678 | -0.953 | 0.000 | -$42,844 |

- **E[max sharpe] = 0.275** — DSR haircut leve porque grid é pequeno
- **9/9 configs Sharpe negativo** em train 2022-2024
- **Best config (sf_08):** stop largo (-35%) + target default (10%), ainda -$4.5k / 2 anos
- **Train gate:** FAIL em todos (DSR deflated < 1.5, p-value < 0.95)

Não prosseguiu pra test set nem holdout — protocolo manda arquivar.

---

## Diagnóstico

### Por que falhou

1. **Whipsaw em exit.** 141/150 exits em smoke (BTCUSDT 90d) foram
   `supertrend_flip`. Só 5/150 hit target. O sell-side ST2 (`m=3, p=18`)
   flipa rápido em pullbacks normais — engine "sai no ruído" antes do
   trend respirar.
2. **R:R desfavorável.** Stop -26.5% vs target +10% = R:R 0.38. Preciso de
   WR > 72% pra break-even. Com whipsaw dominando (141/150 flips),
   nenhum config chega perto.
3. **Grid não salvou.** Alargar stop (0.35) ou apertar target (0.08) não
   muda o diagnóstico de fundo — engine não tem edge direcional em 5
   majors liquidos com params hyperopt freqtrade.
4. **Lab externo era otimista.** Lab reportou Sharpe 0.55 OOS 2024 em
   BTC/ETH/SOL. Aqui: 0.1 trades × 5 majors × 2 anos de bear+bull → -0.07.

### O que o lab externo pegou e AURUM não

Lab freqtrade roda com ROI **decay table** (minute 0: +10%, minute 10: +5%,
minute 40: +2%, minute 120: +1%, depois: 0%). Engine AURUM aqui usa
**target FIXO +10%** — muito mais difícil de hit. Se a gente port'ar o ROI
decay, pode ser que o engine vira profitável.

**MAS:** isso é "reformular protocolo" pós-falha, que é exatamente o
anti-pattern que o protocolo proíbe. Se quiser re-testar com ROI decay,
isso é **nova hipótese** (não "mais um iter" em cima do fracasso).

---

## Decisão

1. **Engine arquivado** em `EXPERIMENTAL_SLUGS` (`config/engines.py`).
2. **Implementação fica no repo** (engine + tests unit + bateria
   reproducível). Se alguém quiser re-abrir (com hipótese **nova**,
   não "mais um iter"), tem tudo em mãos.
3. **Stage = "experimental"**, `live_ready=False`, `quarantined_by_oos=True`
   (implícito via `EXPERIMENTAL_SLUGS`).

---

## Re-abertura (se alguém quiser)

Aceitável se:
- Nova hipótese escrita (não "vou tunar mais um param")
- Grid NOVO pré-registrado
- Mesmos splits (não mover datas pra "ver como fica")

Candidatos plausíveis pra re-abertura futura:
- **Port do ROI decay table** (mudança estrutural de exit logic). Nova
  hipótese. Novo grid pequeno.
- **Entry com RSI ou volume filter extra** (reduzir whipsaw). Nova
  hipótese. Requer re-port do `populate_entry_trend` completo.

Não aceitar:
- "Grid 27 configs varrendo params Supertrend" — fishing expedition.
- "Só BTC+ETH" — cherry-pick de universo.
- "Só 2024 bull" — cherry-pick de janela.
