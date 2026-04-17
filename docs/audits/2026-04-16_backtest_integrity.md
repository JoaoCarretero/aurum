# Backtest Integrity Audit — 2026-04-16

**Trust level: LOW (tending to BROKEN para os claims de Sharpe calibrado).**

## Sumário

Três riscos estruturais derrubam a credibilidade da maioria das calibrações
atuais: (1) walk-forward implementado no `analysis/walkforward.py` é falso —
usa a lista de trades já produzida com parâmetros fixos sobre o histórico
inteiro e fatia em buckets de 20-train/10-test por contagem de trades, sem
re-ajuste de parâmetros, sem OOS real, sem purge/embargo. (2) Zero correção
por múltiplos testes: `phi_sweep` (24), `phi_sweep_stage_b` (108),
`phi_stage_c` (top-4 re-run), `medallion_grid` (144+48 em duas fases),
`param_search` — todos entregam "best combo" bruto sem DSR/PBO/Bonferroni.
(3) Parâmetros tatuados em `config/params.py` com comentários `iter19
1080d WINNER`, `iter11 WINNER`, `grid 2026-04-14` — documentação explícita
de data-snooping sistemático.

## Top 3 methodology risks

1. **Walk-forward é fake.** `analysis/walkforward.py` pega a lista final de
   trades (produzida com parâmetros fixos sobre o histórico inteiro) e
   fatia em baldes de 20-train/10-test por contagem de trades. Sem re-fit
   de parâmetros, sem OOS genuíno, sem purge/embargo. Todo claim
   "Sharpe +31% a +114% WF 6/6 PASS" foi gerado assim — é
   estabilidade amostral in-sample, não walk-forward.

2. **Zero correção por múltiplos testes.** Grep por
   `deflated|pbo|bonferroni|probabilistic.*sharpe|haircut|n_trials`
   retorna nada no código (apenas falso-positivo em fontname).
   `tools/phi_sweep.py` (24 combos), `phi_sweep_stage_b.py` (108),
   `phi_stage_c.py` (top-4 re-run no universo), `medallion_grid.py`
   (144 fase-1 + 48 fase-2), mais `param_search.py` — todos entregam
   "best combo" sem haircut DSR/PBO/Bonferroni. O hill-climb de duas
   fases do MEDALLION amplifica overfit.

3. **Params tuned in-sample e re-reportados na mesma janela.**
   `config/params.py` está tatuado com `iter19 1080d WINNER`,
   `iter11 1080d WINNER`, `iter6 1080d bluechip`, `grid 2026-04-14`.
   `ENGINE_INTERVALS` / `ENGINE_BASKETS` foram post-hoc-selected de uma
   "longrun battery 2026-04-14" que reportou Sharpe em TF×basket e
   fixou os vencedores. DESHAW "+2.65 @ 1h vs -0.10 @ 15m" é um
   penhasco de 2.75 Sharpe — assinatura de seleção em ruído, não edge.

## Extra red flags

- **Survivorship:** `SYMBOLS` é lista fixa de 11 altcoins em 2026; delistadas
  (MATIC, LUNA, FTT, UST, etc) nunca aparecem em backtests de 2+ anos.
- **Monte Carlo `seed=None` default** → não reproduzível; só
  `medallion_finalize` passa `seed=42`.
- **`phi_stage_c` "universe validation of top 4 combos"** é seleção
  in-sample + pseudo-OOS report clássico; top-4 escolhidos em BNBUSDT
  sozinho nas Stages A/B.
- **Modelo de custos** (SLIPPAGE+SPREAD aplicados dos dois lados em
  `open[idx+1]`) é estruturalmente correto mas a magnitude (~7bp
  round-trip) é agressiva para altcoin small-cap em alta vol.
- **`overfit_audit._test_walk_forward`** é o mesmo fake-WF com 5 baldes
  e critério mais fraco ("positive expectancy") — 6/6 PASS não
  informa nada.

## Specific engine trust assessment

| Engine | Claim | Confiança | Razão |
|---|---|---|---|
| **KEPOS** | Sharpe 1.50 layer1 | Relativa-alta | Sem iter_N documentado, mais limpo |
| **CITADEL** | Sharpe +31% WF 6/6 | Média | Penhasco menor entre TFs, claims modestos |
| **RENAISSANCE** | Sharpe 5.65 6/6 PASS | Muito baixa | Número fantasia p/ harmonic patterns em altcoin |
| **BRIDGEWATER** | +5.06 vs -1.95 | Muito baixa | Penhasco de 7 Sharpe entre TFs |
| **DE SHAW** | +2.65 vs -0.10 | Muito baixa | Penhasco de 2.75 Sharpe; cointegração em crypto é instável |
| **JUMP** | 6/6 FROZEN, Sortino 7.84 / DD 1.69% | Muito baixa | 19 iterações documentadas; DD<2% em 730d de altcoin não é fisicamente crível sem overfit severo |
| **PHI** | novo, multi-stage A→B→C | Nula | Não dá p/ afirmar nada sem refazer Stages A/B com split de universo e DSR |
| **MEDALLION** | novo, grid 144+48 | Nula | Setup é inflator clássico de Sharpe |

## Key files

- `analysis/walkforward.py` — o fake-WF
- `analysis/overfit_audit.py` — suite de 6 testes, WF test é o mesmo fake
- `analysis/montecarlo.py` — block bootstrap, `seed=None` default
- `tools/phi_sweep.py`, `phi_sweep_stage_b.py`, `phi_stage_c.py`,
  `medallion_grid.py`, `param_search.py` — grid-search raw, zero DSR
- `config/params.py:265-430` — ENGINE_INTERVALS/BASKETS post-selected;
  comentários `iter_N WINNER` documentam data-snooping sistemático

## Recomendações priorizadas

1. **Walk-forward genuíno:** N folds cronológicos, re-fit params no
   train[k], aplicar em test[k], agregar OOS.
2. **Deflated Sharpe Ratio** (López de Prado) em todo sweep — rastrear
   `n_trials`, haircut Sharpe de acordo. Vai matar ~80% dos "winners"
   atuais.
3. **PBO** (Probability of Backtest Overfit) via CV combinatoriamente
   simétrico.
4. **Purge & embargo** ao redor do split train/test — crucial para
   features com lookback longo (spread window do DESHAW, CVD do JUMP,
   HTF do PHI).
5. **Congelar params atuais**, baixar período estritamente posterior
   à última `iter_N`, rerodar. Edge real sobrevive ≥40% do Sharpe de
   backtest em altcoin crypto; abaixo disso é overfit.
6. **Backfill de survivorship** (MATIC, LUNA, FTT, UST, etc).
7. **Forçar seed no MC**, parar de tatuar `iter_N WINNER` em
   `params.py`, reportar Sortino/Calmar/MDD/DSR como headline
   (não Sharpe).
