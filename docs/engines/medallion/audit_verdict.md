# MEDALLION — Overfit Audit Verdict

**Data:** 2026-04-22
**Engine:** `medallion` (Berlekamp-Laufer 7-signal ensemble, 15m, bluechip)
**Verdict:** **ARCHIVE** (mantido em `EXPERIMENTAL_SLUGS`)
**Stopped at:** Passo 6 (test gate)
**Protocolo:** anti-overfit 8-passos
**Bateria:** `tools/anti_overfit_grid.py medallion --phase all`
**Report:** `data/anti_overfit/medallion/2026-04-22_151629/manifest.json`

---

## Setup

- **Universe:** bluechip (16 symbols: BTC, ETH, BNB, ADA, AVAX, LINK, DOT, ATOM, NEAR, INJ, ARB, OP, SUI, RENDER, FET, SAND, AAVE)
- **TF:** 15m
- **Splits:**
  - Train: 1095 days → 2024-01-01 (3 anos, mixed bull/bear)
  - Test: 2024-01-01 → 2025-01-01 (bull + Q4 stress)
  - Holdout: 2025-01-01 → 2026-04-20 (≈16 meses)
- **Grid:** 8 configs pre-registrado (`docs/engines/medallion/grid.md`)

---

## Resultado completo

| # | Variant | train sharpe | train pnl | **test sharpe** | **test pnl** | **holdout sharpe** | **holdout pnl** |
|---|---|---|---|---|---|---|---|
| 1 | MED02_entry_looser | 1.961 | +$8,500 | **-3.469** | -$3,618 | -2.965 | -$4,724 |
| 2 | MED04_threshold_looser | 1.863 | +$8,054 | -4.369 | -$4,273 | **-2.431 (chosen)** | -$4,088 |
| 3 | MED00_baseline | 1.673 | +$7,148 | -4.319 | -$4,267 | -2.024 | -$3,740 |
| 4 | MED05_components_tighter | 1.673 | +$7,148 | -4.319 | -$4,267 | -2.024 | -$3,740 |
| 5 | MED07_hmm_exit_earlier | 1.673 | +$7,148 | -4.319 | -$4,267 | -2.024 | -$3,740 |
| 6 | MED01_entry_tighter | 1.656 | +$6,855 | -4.779 | -$4,675 | -1.828 | -$3,719 |
| 7 | MED06_kelly_lower | 1.624 | +$6,585 | -4.314 | -$4,262 | -2.037 | -$3,718 |
| 8 | MED03_threshold_tighter | 0.822 | +$3,240 | -4.113 | -$4,203 | -1.985 | -$3,970 |

---

## Gates

| Gate | Threshold | Resultado | Status |
|---|---|---|---|
| Train DSR p-value | ≥ 0.95 | 1.000 (7/8 configs) | ✅ PASS |
| Train Sharpe (best) | ≥ 1.5 | 1.961 | ✅ PASS |
| **Test worst-of-top-3 Sharpe** | **≥ 1.0** | **-4.369** | ❌ **FAIL** |
| Holdout Sharpe | ≥ 0.8 | -2.431 | ❌ FAIL |

---

## Diagnóstico

### Padrão observado

- **Train perfeito** → **Test catastrófico** → **Holdout ruim mas menos pior**
- Spread entre train e test: ~5-6 unidades de Sharpe. Isso é **overfit canônico**.
- Note-se a degradação sequencial: train +8.5k, test -3.6k, holdout -4.7k (engine
  piora ainda mais no período mais recente).

### Interpretação mecânica

MEDALLION é ensemble Berlekamp-Laufer de 7 sinais mean-reverting de curto
prazo. A hipótese é capturar mean-reversion intra-hora em altcoins. Em
2022-2024 (train) o padrão funcionou (Sharpe 1.9), mas **o regime de
crypto mudou em 2024-2025** e o ensemble não generalizou:
- 2022-2023: menos ATH rallies, volatilidade alta com mean-reversion clara
- 2024-2025: bull run pós-halving, crypto em trend sustentado → mean-rev
  morre, shorts queimam, longs sairam cedo demais

### Configs idênticas

MED00, MED05, MED07 tiveram resultados **exatamente iguais** (Sharpe 1.673
× 3). Isso significa que min_components=5 e hmm_exit_trend_prob=0.65 não
tiveram efeito nenhum — ou os dados nunca acionaram esses filtros, ou os
parâmetros estão dead-code. Vale investigar antes de qualquer re-abertura.

### Por que passou DSR e ainda assim é overfit

DSR penaliza pelo número de trials (N=8) e pelo σ dos Sharpes no grid. No
caso: σ=0.34, E[max] ≈ 0.5. Sharpe best=1.96 >> E[max] → DSR p=1.0. **A
matemática diz que 1.96 é estatisticamente raro em 8 random trials em
janela de 3 anos.** Isso não garante edge OOS — garante só que o fit
in-sample não foi sorte num espaço de busca de 8 configs. Se expandíssemos
o grid pra 100 configs, DSR apertaria. Mas mesmo com DSR=1, o edge pode
não existir fora da janela — e aqui não existe.

**Lição metodológica:** DSR é necessária mas NÃO suficiente. Test gate
fora-de-sample é onde o veredito real acontece.

---

## Decisão

1. **Engine arquivado** em `EXPERIMENTAL_SLUGS` (`config/engines.py`).
2. Já estava na quarentena antes (Smoke last-360d Sharpe -3.69). Agora
   confirmado com protocolo disciplinado + dados OOS mais recentes.
3. Atualizar comentário no `EXPERIMENTAL_SLUGS` com evidência 2026-04-22.
4. **Implementação fica no repo** — reprodutibilidade total via
   `tools/anti_overfit_grid.py medallion`.
5. Stage permanece `experimental`, `live_ready=False`.

---

## Re-abertura (se alguém quiser)

Aceitável se:
- **Nova hipótese mecânica** explicando por que o edge sumiu em 2024+.
  Ex: "filtro de regime de trend pra desligar em bull sustentado".
- Grid pequeno (≤10 configs), novo, pré-registrado.
- Mesmos splits (não mover datas).
- Meta-gate: expected Sharpe OOS ≥ 0.5 (não overfitting ambitious).

Não aceitar:
- "Vamos tentar outro grid, talvez encontre algo" — fishing expedition.
- "Só bluechip mais estreita" — cherry-pick universo.
- "Só 2022-2023" — cherry-pick janela.
- Re-calibrar parâmetros mantendo hipótese antiga sem explicar mecanismo
  de mudança de regime.

---

## Lições pra outros engines

**Este protocolo matou a ilusão.** A versão "grid-best" antiga de MEDALLION
(via `medallion_grid.py`) reportava Sharpe alto e parecia promissor, mas
era single-window. Forçar 3-window split + DSR revelou que tudo era
overfit.

Aplicar mesmo rigor aos engines em stage "research":
- PHI (em curso)
- TWO SIGMA, AQR (nunca rodados OOS)

Se não passam 3-window + DSR → não passam. Ponto.
