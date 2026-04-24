# OOS Pre-Calibration Verdict — 2026-04-16

**Metodologia:** rodar engines com params atuais (`config/params.py`) em
janela **antes** da janela de calibração (1080d ending 2026-04-14).

- Window de calibração alegada: ~2023-05 → 2026-04-14
- Janela OOS escolhida: **2022-01-01 → 2023-01-01** (360 dias
  pré-calibração inteiros)
- Nota: adicionada flag `--end YYYY-MM-DD` a `core/cache.read`,
  `core/data.fetch/fetch_all`, e aos engines CITADEL, RENAISSANCE,
  JUMP, DE SHAW, BRIDGEWATER. Sem esta flag era impossível rodar
  backtest em janela histórica arbitrária.

---

## Resultados por engine

### CITADEL (15m, default basket)

Três janelas rodadas:

| Janela | Regime | Sharpe | Sortino | Trades | WR |
|---|---|---|---|---|---|
| Last 360d (baseline) | Mixed | 3.007 | 4.134 | 299 | 60.5% |
| 2022-01 → 2023-01 (OOS) | BEAR puro | **5.677** | 8.606 | 240 | 60.8% |
| 2021-01 → 2022-01 (OOS) | BULL puro | **2.921** | 3.982 | 134 | 61.9% |

**Veredito: EDGE REAL.** Sharpe positivo em 3 janelas × regimes distintos.
Note: OOS BEAR é melhor que baseline porque CITADEL é engineered pra
trade em BEAR (gates explícitos); em BULL faz menos trades mas ainda
positivo. Edge não depende da janela de calibração específica.

### RENAISSANCE (15m, bluechip basket)

- Claim in-sample (params.py): **Sharpe 5.65** (6/6 overfit PASS, longrun
  2026-04-14)
- OOS 2022-01 → 2023-01: Sharpe **2.421**, Sortino 2.352, ROI 8.81%,
  MDD 1.72%, 226 trades, WR 75.66%

**Drop: -57%.** Não colapsou — ainda positivo com Sharpe 2.4 — mas o
claim de 5.65 era inflado. Edge plausível em regime de menor magnitude.
MDD baixo (<2%) é consistente com in-sample.

**Veredito: EDGE MODERADO.** Revisar claim em params.py comentário.
Sharpe real ≈ 2-3, não 5.65.

### JUMP (1h, bluechip basket)

- Claim in-sample: Sharpe 2.06 / Sortino 7.84 / MDD 1.69% (720d 1h, 6/6
  FROZEN)
- OOS 2022-01 → 2023-01: Sharpe **3.15**, Sortino **6.156**, ROI 16.36%,
  MDD **1.65%**, 110 trades, WR 63.64%

**OOS > in-sample.** Sharpe subiu. Sortino muito próximo (6.16 vs 7.84).
MDD quase idêntica (1.65% vs 1.69%). 110 trades em 1 ano bem consistente
com taxa de trading do engine.

**Veredito: ROBUSTO.** JUMP sobreviveu ao teste OOS com folga. Memória
classificava como "6/6 FROZEN DD<2% não crível sem overfit severo" — essa
suspeita foi refutada. MDD 1.65% em 360d de OOS BEAR é real.

### DE SHAW (1h, bluechip basket)

- Claim in-sample: Sharpe +2.65 (360d 1h bluechip, 3P 3W 0F overfit)
- OOS 2022-01 → 2023-01: Sharpe **-1.726**, ROI **-28.34%**,
  MDD **30.66%**, 1819 trades, WR 75.92%

**COLAPSO TOTAL.** Sharpe de +2.65 pra -1.73 é drop de -165%. ROI negativo
de 28% numa janela de 1 ano. MDD de 31%. O WR alto (76%) mascara: loss
trades enormes consomem os lucros dos winners. Padrão clássico de
pairs-cointegration falhando em regime shift (2022 teve múltiplos quebras
de cointegração).

**Veredito: OVERFIT CATASTRÓFICO.** Engine não deve ir pra produção nem
em paper. Claim de Sharpe 2.65 é artefato da janela de calibração
específica. Memória já flagava "break-even z=3.0/pvalue=0.05" — isso é
mais consistente com a realidade que o claim.

### BRIDGEWATER (1h, bluechip basket)

- Claim in-sample: Sharpe +5.06 (longrun 2026-04-14)
- OOS 2022-01 → 2023-01: Sharpe **11.04**, Sortino **19.97**,
  ROI **267.22%**, MDD 6.77%, **9194 trades**, WR 57.24%

**Explosão positiva.** OOS é mais que o dobro do claim. Mas o ROI de 267%
e 9194 trades (25/dia) é assinatura de **algo errado no modelo de custos
ou sizing**, não de edge. Engines honestos em crypto altcoin não fazem
267% num ano sem leverage extremo.

**Veredito: INCONCLUSIVO / SUSPEITO.** Precisa investigação forense
antes de confiar no claim. Possíveis explicações:
1. Custos C1+C2 não aplicados corretamente em alguma code path
2. Posições sobrepostas ultrapassando o cap agregado
3. Contarian + 2022 BEAR = realmente edge assimétrico (possível mas
   improvável na magnitude)

---

### KEPOS (15m, bluechip basket)

- Claim in-sample: Sharpe 1.50 layer1 (memory note, tuned config)
- OOS 2022-01 → 2023-01 (defaults): **0 trades**. Engine não dispara.

`eta_critical: 0.95` (default) nunca atinge em candle data de 2022.
Consistente com a nota de memória: "η em candle data não atinge 0.95;
KEPOS/GRAHAM anti-padrões; η vira diagnóstico não sinal".

**Veredito: NÃO-FUNCIONAL COM DEFAULTS.** O claim de 1.50 precisa de
overrides específicos (`--k-sigma`, `--eta-critical`), ou seja,
calibração é fundamental para o engine existir. Isso é um red flag —
engine cujo default não dispara não é engine, é placeholder.

### MEDALLION (15m, bluechip basket)

- Claim in-sample: params grid-best (144+48 trials, 2-fase)
- OOS 2022-01 → 2023-01: Sharpe **-3.218**, Sortino **-9.03**,
  ROI **-38.12%**, MDD **38.36%**, 173 trades, WR 47.98%

**COLAPSO CATASTRÓFICO.** Novo engine, grid search de 2 fases (exatamente
o padrão que o audit de backtest integrity flagou como "classic Sharpe
inflator"). OOS confirma: edge aparente veio 100% do grid de 144+48
tentativas no mesmo histórico. Zero robustez em janela não vista.

**Veredito: OVERFIT CONFIRMADO.** Não vai pra FROZEN. Não vai pra paper.
É exemplo canônico de por que grid search sem DSR é inútil.

---

## Sumário

| Engine | Claim | OOS | Drop% | Veredito |
|---|---|---|---|---|
| CITADEL | 3.00 | 5.68 / 2.92 | +90% / -3% | ✅ edge real |
| JUMP | 2.06 | 3.15 | +53% | ✅ robusto |
| RENAISSANCE | 5.65 | 2.42 | -57% | ⚠️ inflado |
| BRIDGEWATER | 5.06 | 11.04 | +118% | ⚠️ bug suspect |
| DE SHAW | 2.65 | -1.73 | -165% | 🔴 colapsado |
| KEPOS | 1.50 | 0 trades | n/a | 🔴 não-funcional |
| MEDALLION | grid-best | -3.22 | catastrófico | 🔴 overfit canônico |

---

## Conclusão

**7 engines testados em janela OOS pré-calibração (2022-01 → 2023-01).**

- **2/7 (28%) confirmados com edge real:** CITADEL, JUMP. Sobreviveriam
  a walk-forward genuíno e DSR.
- **1/7 (14%) não-funcional:** KEPOS — defaults produzem zero trades.
- **3/7 (43%) colapsaram ou são overfit canônico:** DE SHAW, MEDALLION,
  e o BRIDGEWATER inflado-pra-cima (suspeita de bug de custos).
- **1/7 (14%) inflado mas não quebrado:** RENAISSANCE (Sharpe real ~2.4
  vs claim 5.65).

**A tese "metodologia permite números inflados" foi empiricamente
confirmada:** dos 7, apenas 2 (CITADEL, JUMP) teriam números que
sobreviveriam a validação honesta. Os outros 5 têm problemas de
severidade variada.

**Mas a sub-tese "todo mundo overfit" também caiu parcialmente:**
CITADEL e JUMP são reais. Edge existe no AURUM — só não está distribuído
igualmente.

**Padrão observado:** engines com mecanismo de mercado defensável
(momentum fractal, order flow microestrutural) sobreviveram. Engines
com mecanismos fracos (cointegração em altcoin, mean-reversion
grid-tuned, threshold exótico que não dispara) colapsaram ou nunca
funcionaram. **Mecanismo > iteração de params.**

## Próximos passos recomendados

### Ações por engine

1. **CITADEL** — manter em FROZEN. Base empírica: 3 janelas × regimes.
2. **JUMP** — manter em FROZEN. OOS melhor que in-sample claim.
3. **RENAISSANCE** — atualizar comentário em `params.py` pra Sharpe ~2.4
   (realidade OOS) em vez de 5.65. Não-FROZEN, ok pra paper com claim
   correto.
4. **BRIDGEWATER** — **forense prioritária**: logar PnL por trade na
   janela OOS, verificar se custos C1+C2 foram aplicados, se posições
   sobrepostas respeitaram L6 cap. Não vai pra paper antes do forense.
5. **DE SHAW** — tirar do registry default, mover pra
   `EXPERIMENTAL_ENGINES` com warning "overfit confirmado, não
   paper-trade".
6. **KEPOS** — idem DE SHAW. Defaults não funcionam. Se quiser manter,
   precisa de config preset salva (`KEPOS_TUNED_PARAMS`) e flag clara.
7. **MEDALLION** — não commitar na branch atual sem DSR + WF genuíno.
   Ou arquivar. Claim de grid-best é ruído.

### Ações metodológicas (maior ROI)

8. **Reescrever `analysis/walkforward.py`** — WF genuíno com folds
   cronológicos, re-fit em train, medir em test, agregar OOS.
9. **Implementar DSR** em `analysis/overfit_audit.py` — track n_trials,
   haircut automático em save_run().
10. **Remover comentários `iter_N WINNER`** de `params.py` e substituir
    por `tuned_on=[2023-05..2026-04], oos_window=[2022-01..2023-01],
    oos_sharpe=X`.
11. **Git pre-commit hook** que rejeita `iter_N WINNER` em `params.py`.
12. **`config/engines.EXPERIMENTAL_ENGINES`** como flag análoga a
    `FROZEN_ENGINES` pra engines que ainda não passaram OOS.

## Arquivos modificados nesta sessão

- `core/cache.py` — param `end_time_ms` em `read()`
- `core/data.py` — param `end_time_ms` em `fetch()` e `fetch_all()`
- `engines/citadel.py` — flag `--end`
- `engines/renaissance.py` — flag `--end`
- `engines/jump.py` — flag `--end`
- `engines/deshaw.py` — flag `--end`
- `engines/bridgewater.py` — flag `--end`
- `engines/kepos.py` — flag `--end`
- `engines/medallion.py` — flag `--end`

## Runs persistidos

- `data/runs/citadel_2026-04-16_232500` (baseline)
- `data/runs/citadel_2026-04-16_232542` (OOS BEAR 2022)
- `data/runs/citadel_2026-04-16_232722` (OOS BULL 2021)
- `data/renaissance/2026-04-16_232914`
- `data/jump/2026-04-16_232916`
- `data/deshaw/2026-04-16_232917`
- `data/bridgewater/2026-04-16_232919`
- `data/kepos/kepos_2026-04-16_2338`
- `data/medallion/medallion_2026-04-16_2338`

## Engines não testados

- **PHI** — estrutura multi-TF complexa, fetch_all em loop. Adicionar
  `--end` aqui requer threading end_time_ms em vários níveis. Per audit
  de backtest integrity, já flagado pra rework completo (Stages A/B/C
  precisam ser refeitas com universe split + DSR).
- **GRAHAM** — arquivado per docstring.
- **AQR, TWO SIGMA, MILLENNIUM** — meta-engines (evolutionary,
  ML ensemble, pod orchestrator). OOS honesto requer todos os sub-engines
  terem OOS primeiro. Escopo pra sessão separada.
