# Claude Battery Audit — 2026-04-17 13:22

**Scope:** audit independente das 4 operacionais (CITADEL, RENAISSANCE, JUMP, BRIDGEWATER) + DE SHAW (quarentena). Complementa o OOS multi-janela de 11:19 e o audit estrutural full-stack de hoje.

**Metodologia:**
1. Análise estática (cost model, look-ahead, tese vs implementação)
2. Bateria consolidada em snapshot único (`tools/baseline_all.py --days 180 --basket bluechip_active`)
3. Cross-check com OOS multi-janela já disponível

---

## 1. Análise estática

### 1.1 Cost model (C1+C2)

Verificado via grep em `engines/citadel.py:352-362`, `engines/jump.py:271-280`, `engines/bridgewater.py:414-423`, `core/harmonics.py:280-306`:

- `slip_exit = SLIPPAGE + SPREAD` aplicado na saída (market order)
- BULL: `entry × (1 + COMMISSION)`, `exit × (1 − COMMISSION − slip_exit)`, funding negativo
- BEAR: `entry × (1 − COMMISSION)`, `exit × (1 + COMMISSION + slip_exit)`, funding positivo
- Espelhamento bit-a-bit BULL/BEAR nas 4 operacionais ✅
- `core/signals.py:186,211` aplica slip simétrico em `calc_levels`

**Veredito:** cost model C1+C2 correto e simétrico em todas as 4 operacionais.

### 1.2 Look-ahead scan

`tools/lookahead_scan.py` (9 hits total, 0 leaks reais):

| Arquivo | Linha | Padrão | Classificação |
|---|---|---|---|
| `core/signals.py` | 185,210 | `df["open"].iloc[idx+1]` | ✅ Entry next-bar open (padrão canônico AURUM) |
| `engines/citadel.py` | 868 | `sym_rows[i+1]` | ✅ Contexto de print/report, fora do signal |
| `engines/kepos.py` | 232,276,300,460 | `iloc[t+1]` | ✅ Entry time labeling + janela fechada no t |
| `engines/medallion.py` | 438,615 | `iloc[t+1]` | ✅ Mesmo padrão |

**Engines limpos (zero hits):** RENAISSANCE, JUMP, DE SHAW, BRIDGEWATER, core/indicators, core/portfolio, core/htf, core/harmonics.

**Veredito:** nenhum look-ahead real nas 4 operacionais.

### 1.3 Tese vs implementação (pipeline check)

- **CITADEL** (Momentum fractal): `scan_symbol → indicators → swing_structure → omega → regime → decide_direction → calc_levels → portfolio_allows → position_size → label_trade` — segue tese.
- **RENAISSANCE** (Harmonic patterns): `scan_hermes → detect_pattern (Gartley/Butterfly/Bat/Crab/Cypher) → bayesian confidence → Hurst/entropy weight → entry` — segue tese.
- **JUMP** (Order flow): `scan_mercurio → CVD → CVD divergence → volume imbalance → liquidation proxy → structure align → entry` — segue tese.
- **BRIDGEWATER** (Sentiment): `scan_thoth → collect_sentiment (funding_z + oi_signal + ls_signal bounded com end_time_ms) → composite score → macro regime → entry contrarian` — segue tese. Fix do `bfill()` em `_align_oi_signal_to_candles` já aplicado (commit 5e0d29b).

---

## 2. Bateria 180d bluechip_active (snapshot único, 2026-04-17 13:13)

`python tools/baseline_all.py --days 180 --basket bluechip_active`

Macro BTC detectado: BULL/BEAR misto. 20 símbolos bluechip_active, 17.280 candles 15m por símbolo.

| Engine | Trades | WR% | Sharpe | Sortino | PnL | MaxDD% | MC% |
|---|---:|---:|---:|---:|---:|---:|---:|
| **CITADEL** | 319 | 61.4 | **6.533** | 10.044 | +6.051 | 6.6 | 99.9 |
| **RENAISSANCE** | 128 | 83.6 | **8.112** | 10.227 | +1.092 | 0.6 | 100.0 |
| **BRIDGEWATER** | 15.682 | 56.0 | **2.025** | 2.778 | +3.011 | **24.4** | 75.2 |
| **JUMP** | 1.592 | 54.0 | **0.530** | 0.739 | +473 | 20.2 | 61.6 |
| DE SHAW | 9 | 55.6 | -2.301 | -1.847 | -72 | 0.9 | 0 |

CSV: `data/param_search/2026-04-17/baseline_all.csv`
Log: `data/audit/_claude_battery_180d.log`

---

## 3. Cross-check com OOS multi-janela (2026-04-17 11:19)

Dados de `docs/audits/2026-04-17_oos_revalidation.md`:

| Engine | BEAR 2022 | BULL 2020-07 | CHOP 2019 | 180d recent |
|---|---:|---:|---:|---:|
| CITADEL | 2.149 | 2.810 | 4.842 | **6.533** |
| RENAISSANCE | 6.673 | 5.949 | **−0.04** | **8.112** |
| JUMP | 3.149 | 3.187 | 4.268 | **0.530** ⚠️ |
| BRIDGEWATER | 4.934 | 8.723 | 4.981 | **2.025** |

---

## 4. Standalone overfit_audit 6/6 (TF nativo por engine)

**Descoberta crítica:** baseline_all.py roda todos em 15m global, mas cada engine tem TF nativo diferente. Rodar em TF errado **distorce tanto os números quanto o veredito de overfit**. Audit standalone corrige isso.

### Resultados standalone (180d bluechip_active, TF nativo)

| Engine | TF | Trades | Sharpe | MDD% | Overfit | Status |
|---|---|---:|---:|---:|:---:|:---:|
| **RENAISSANCE** | 15m | 135 | 6.54 | 0.77 | **6/6 PASS** | ✅ |
| **JUMP** | 1h | 107 | 4.68 | 1.22 | **6/6 PASS** | ✅ |
| **BRIDGEWATER** | 1h | 4.270 | 10.88 | 6.72 | **6/6 PASS** | ✅ |
| **CITADEL** | 15m | 266 | 2.06 | 10.9 | **3/6 + 1W + 2F** | ⚠️ |

### Detalhes overfit

**CITADEL (3/6 PASS, 1 WARN, 2 FAIL):**
- A walk-forward **FAIL** — 2/5 windows com expectancy negativa
- B sensitivity **FAIL** — cliff a score ≥ 0.560 (qualquer ajuste colapsa)
- C concentration PASS — ETH 36% do PnL
- D regime PASS — só BEAR profitable (266 trades)
- E temporal **WARN** — decay 88% (edge quase sumiu 2ª metade)
- F slippage PASS — breakeven 10bp

**RENAISSANCE (6/6 PASS):**
- Todos testes verdes; top FET 26% de PnL; decay −79% (edge holds)

**JUMP (6/6 PASS):**
- Todos testes verdes; top SAND 23%; regime BULL+BEAR profitable (CHOP só 3 trades); decay 48% (edge holds mas enfraquecendo)

**BRIDGEWATER (6/6 PASS):**
- Todos testes verdes; top INJ 20%; decay −106% (**edge se fortalecendo**)

---

## 5. Veredito final por engine

### 🚨 CITADEL — OVERFIT SUSPECT / EDGE DECAY no regime atual

- Passou OOS histórico (Sharpe 2.1/2.8/4.8 em BEAR/BULL/CHOP)
- **Falha em 180d recent:** walk-forward 2/5 windows negativas, sensitivity cliff, decay 88%
- Sharpe 2.06 (vs 6.5 do baseline_all aggregate) é o número honesto standalone
- **Diagnóstico:** não é overfit histórico — é **edge decay no regime atual**. A tese de momentum fractal parece estar morrendo no BULL crypto sustentado de 2025-10→2026-04.
- **Recomendação:** **NÃO promover live sem investigar**. Rodar janela deslocada (ex: `--end 2025-10-01 --days 180`) pra confirmar se edge só deixou de funcionar recent.

### ✅ RENAISSANCE — edge sem overfit, regime-sensitive

- 6/6 PASS standalone + OOS 3 janelas (6.7/5.9/−0.04)
- Sharpe 6.54, MDD 0.77%, 135 trades
- **Único concern conhecido:** CHOP 2019 OOS deu Sharpe −0.04 (regime CHOP é hostil)
- **Recomendação:** produção com **gate de regime** — off em CHOP detectado via HMM.

### ✅ JUMP — edge sem overfit

- 6/6 PASS standalone em TF 1h + OOS 3 janelas fortes (3.15/3.19/4.27)
- Sharpe 4.68, MDD 1.22%, 107 trades
- Decay 48% é atenção — edge enfraquecendo mas ainda válido
- **Recomendação:** produção. O 0.53 do baseline_all era artefato de TF errado (15m em vez de 1h nativo).

### ✅ BRIDGEWATER — edge sem overfit, o mais forte agora

- 6/6 PASS standalone + OOS 3 janelas (4.9/8.7/5.0)
- Sharpe 10.88, MDD 6.72%, 4.270 trades
- Decay −106% significa edge **está se fortalecendo** na segunda metade
- Bug OI (commit 5e0d29b) + fail-closed (9f5f38e) ambos aplicados
- **Recomendação:** produção. MDD 6.7% é tolerável; muito diferente do 24% do baseline_all (novamente artefato de TF errado).

### 🔴 DE SHAW — quarentena confirmada

- 9 trades em 180d, Sharpe −2.3
- Não operacional neste regime
- **Recomendação:** manter em EXPERIMENTAL_SLUGS.

---

## 6. Flags pro portfólio MILLENNIUM (revisado pós 6/6)

Com os números standalone corretos (TF nativo), o reweight precisa ser **o oposto** do que eu sugeri antes:

1. **BRIDGEWATER** deve ter o maior peso do portfolio (Sharpe 10.88, 6/6 PASS, edge se fortalecendo)
2. **RENAISSANCE** peso médio + gate off em CHOP (6/6 PASS, MDD 0.77% excepcional)
3. **JUMP** peso médio (6/6 PASS, edge sólido em TF 1h nativo)
4. **CITADEL** peso **reduzido ou excluído temporariamente** até resolver edge decay (2/6 FAIL, walk-forward negativo)

Caps atuais do Codex C em `engines/millennium.py:88`:
- CITADEL: 0.45 → **reduzir pra ≤ 0.15** (ou excluir)
- RENAISSANCE: 0.30 → manter
- JUMP: 0.30 → manter
- BRIDGEWATER: 0.25 → **aumentar pra ≥ 0.35**

---

## 7. Achados independentes desta sessão (finais)

1. **CITADEL NÃO é o mais seguro para deploy.** Contrário ao que audits anteriores sugeriam. Standalone 180d mostra walk-forward 2/5 negativas + sensitivity cliff + decay 88%. Edge histórico era real mas **está decaindo no regime atual**. Isso é muito mais perigoso que overfit clássico porque os OOS históricos mostram edge passado.

2. **Baseline_all.py é ferramenta útil mas não conclusiva.** Rodar engines em TF global (15m) em vez do nativo distorce Sharpe e o veredito de overfit. Para audit final, standalone individual é obrigatório.

3. **BRIDGEWATER é o engine mais sólido agora**, não apenas "operacional com ressalva". 6/6 PASS + 4270 trades + decay −106% (edge se fortalecendo) + Sharpe 10.88. Bug OI + fail-closed fixados.

4. **JUMP edge é real no TF 1h nativo.** Meu diagnóstico anterior de "JUMP perdeu edge" foi errado — era artefato de TF.

5. **Regra metodológica a adotar:** todo engine **deve** ser testado em TF nativo (`ENGINE_INTERVALS`). Qualquer bateria consolidada que misture TFs perde validade.

---

## 8. Deploy readiness final (2026-04-17)

| Engine | Deploy? | Condição |
|---|:---:|---|
| BRIDGEWATER | ✅ YES | TF 1h, sizing base |
| JUMP | ✅ YES | TF 1h, sizing base |
| RENAISSANCE | ✅ YES | TF 15m, gate regime: OFF em CHOP |
| CITADEL | ❌ HOLD | Investigar edge decay antes de live |
| DE SHAW | 🔴 NO | Quarentena |

**Resposta direta à pergunta "todas as 4 estão com edge sem overfit?":**
**Não — 3 das 4 estão. CITADEL não passou standalone.**

---

## 9. Pendências

- [ ] Rodar CITADEL em janela deslocada (`--end 2025-10-01 --days 180`) pra confirmar edge decay vs overfit histórico
- [ ] Decisão MERCURIO_SIZE_MULT 0.47→0.35 (Codex) — Joao review
- [ ] Rebalancear `ENGINE_WEIGHT_CAPS` na MILLENNIUM — atual está invertido vs números reais

---

**Gerado por:** esta sessão (Claude Opus 4.7), em 2026-04-17 13:40, audit independente cruzando análise estática + bateria consolidada + standalone overfit 6/6. Output completo em `data/{engine}/<run_id>/overfit.json` + `data/runs/citadel_2026-04-17_133746/overfit.json`.

---

## 10. Retificação pós-forensics Codex (2026-04-17 14:15)

Codex rodou forensics dedicada em BRIDGEWATER em paralelo e achou fato crítico que muda meu veredito #3:

**Binance rejeita `startTime`/`endTime` nos endpoints `openInterestHist` e `globalLongShortAccountRatio`** (erro -1130 "parameter endTime is invalid"). Portanto BRIDGEWATER rodando OOS histórico **não consegue obter OI/LS** e cai em modo funding-only silencioso — o que inflava artificialmente os Sharpe históricos (BEAR 4.9 / BULL 8.7 / CHOP 5.0 do OOS revalidation).

Commits do Codex:
- `9f5f38e` — fail-closed quando OI/LS histórico indisponível
- `10e8c4f` — cache local de sentiment reprodutível
- `15cf92d` — CLI prewarm
- `f44e933` — fail-closed per-symbol
- `830e422` — fetch_all short-window fix

### Verificação do meu run 180d

Checado o payload `data/bridgewater/2026-04-17_133749/reports/bridgewater_1h_v1.json`:
- 4270 trades total
- **Apenas 422 (9.9%)** com `oi_signal=0 AND ls_signal=0`
- 90.1% com sentiment **válido** (via live data atual cobrindo janela recent)

Isso significa que meu 6/6 PASS do BRIDGEWATER é válido **para janela recent (2025-10 → 2026-04)**, mas **NÃO é extrapolável para OOS histórico**. A janela caiu dentro do range que a API live da Binance cobre naturalmente, então OI/LS estavam disponíveis.

### Veredito retificado BRIDGEWATER

| Janela | Sentiment válido? | Edge? |
|---|:---:|:---:|
| **180d recent (2025-10→2026-04)** | ✅ 90% válido | ✅ 6/6 PASS Sharpe 10.88 — edge real |
| **OOS BEAR 2022** | 🔴 100% funding-only | ❌ INVALID — número era artefato |
| **OOS BULL 2020** | 🔴 100% funding-only | ❌ INVALID — número era artefato |
| **OOS CHOP 2019** | 🔴 100% funding-only | ❌ INVALID — número era artefato |

### Tabela final revisada (deploy readiness honesto)

| Engine | 180d recent | OOS histórico | Deploy? |
|---|:---:|:---:|:---:|
| **CITADEL** | 3/6 FAIL (edge decay) | ✅ 2.1/2.8/4.8 (válido, mas DSR borda no BEAR) | ⚠️ HOLD |
| **RENAISSANCE** | 6/6 PASS Sharpe 6.54 | ✅ 6.7/5.9/**−0.04** (frágil em CHOP) | ✅ com gate regime |
| **JUMP** | 6/6 PASS Sharpe 4.68 | ✅ 3.15/3.19/4.27 | ✅ |
| **BRIDGEWATER** | 6/6 PASS Sharpe 10.88 (válido) | 🔴 INVALID (sentiment não reproduzível) | ⚠️ forward-only (sem OOS histórico) |

### Implicação prática

- **JUMP permanece único com edge confirmado OOS histórico + recent + 6/6.**
- **BRIDGEWATER pode rodar LIVE** com sentiment atual via cache, mas qualquer claim de "backtest histórico" fica preso ao prewarm acumulando dados daqui pra frente. **Não há base pra validar BEAR 2022 com a API atual.**
- **CITADEL** tem o problema inverso — OOS histórico válido mas edge decaindo em 180d recent.
- **RENAISSANCE** tem edge mas regime-sensitive.

### Mudança de recomendação

Originalmente recomendei BRIDGEWATER como "o mais sólido agora". **Isso tá errado** — é o mais sólido *forward-only*, mas sem validação histórica reproduzível. Pra deploy de capital real, **JUMP é o único que passa simultaneamente em:** análise estática + 6/6 standalone + OOS multi-janela.

Ranking honesto pra live hoje:
1. **JUMP** — edge real, OOS + recent + 6/6 PASS
2. **RENAISSANCE** — edge real com gate CHOP
3. **BRIDGEWATER** — edge recent, mas sem histórico comparável (forward-only, precisa prewarm contínuo)
4. **CITADEL** — hold (edge decay no regime atual)
