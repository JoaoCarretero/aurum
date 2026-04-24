# Trading Logic Audit — 2026-04-16

## Sumário

Counts: **0 critical, 3 high, 6 medium, 4 low.** Core protegido está intacto
(CLAUDE.md respeitada na branch feat/phi-engine). Modelo de custos C1+C2 é
replicado verbatim em 9 engines direcionais; entry em `open[idx+1]` com slip
e spread por direção em 100% deles. Zero data leakage detectado. Os três
problemas sérios são gates inertes em DE SHAW, divergência silenciosa no
floor de conta do JUMP, e engines KEPOS/MEDALLION/GRAHAM/PHI opt-out
consciente dos gates globais sem flag `EXPERIMENTAL_ENGINES` para marcá-los.

## Engine-by-engine matrix

| Engine | Custos C1+C2 | Portfolio gates | Sizing via core | Stops swing-based | Macro gate | L6/L7 | Notes |
|---|---|---|---|---|---|---|---|
| CITADEL | ✅ | ✅ | ✅ | ✅ | ✅ | ✅/✅ | FROZEN baseline |
| RENAISSANCE | ✅ | ✅ | ✅ | ✅ | ✅ | ✅/✅ | via `core/harmonics.scan_hermes` |
| BRIDGEWATER | ✅ | ✅ | ✅ | ✅ | ✅ (contextual) | ✅/✅ | full stack |
| JUMP | ✅ | ✅ | ✅ | ✅ | ⚠️ assimétrico | ✅/⚠️ | **floor removido** (H2) |
| MILLENNIUM | ✅ | ✅ | ✅ | ✅ | ✅ | ✅/✅ | herda via azoth_scan/scan_hermes |
| DE SHAW | ✅ | ⚠️ **inerte** | ✅ | ❌ hardcoded | ✅ | ❌/❌ | H1, M3, L2 |
| KEPOS | ✅ | ❌ | local | local | ❌ | ❌/❌ | opt-out docstring §Discipline |
| MEDALLION | ✅ | ❌ | local Kelly | local | ❌ | ❌/❌ | untracked, RR<1 intencional |
| GRAHAM | ✅ | ❌ | local | local | ❌ | ❌/❌ | arquivado per docstring |
| PHI | ✅ | ❌ | local | local | ❌ | ❌/❌ | `notional_cap=0.02` próprio |

## Findings

### 🟠 High

**H1 — DE SHAW importa `portfolio_allows` mas NUNCA chama.**
`engines/deshaw.py:59` tem o import, zero callsites no arquivo.
Consequência: corr gate e `MAX_OPEN_POSITIONS` inertes — N pares
cointegrados com overlap em ETH/SOL podem abrir simultâneos sem gate.
`check_aggregate_notional` é chamado mas com `[]` (linha 540), então o
cap agregado entre pares também é inerte.

**H2 — JUMP removeu floor de conta.**
`engines/jump.py:288`: `account = account + pnl`. Comentário justifica
tirar o clamp 50%, mas CITADEL (linha 354) mantém
`max(account + pnl, 0.0)`. Divergência silenciosa — conta pode ficar
negativa em backtest, distorcendo ratios.

**H3 — KEPOS, MEDALLION, GRAHAM, PHI não chamam `detect_macro`,
`portfolio_allows`, `check_aggregate_notional`, nem têm L7 liquidation.**
Inertes a LEVERAGE=1.0 default e tese defensável localmente, mas ficam
invisíveis ao agregado de portfolio. Se rodados em paralelo via launcher
ou compostos, escapam dos gates que CITADEL/JUMP/BRIDGEWATER/RENAISSANCE
respeitam. **Recomendação:** criar `EXPERIMENTAL_ENGINES` em
`config/engines.py` análogo a `FROZEN_ENGINES` pra marcar opt-out
consciente.

### 🟡 Medium

- **M1** JUMP — macro check assimétrico (linhas 184/209/218, só testa
  `!= "BEAR"` em alguns branches)
- **M2** MILLENNIUM muta `config.params` em import time (linhas 28-37) —
  singleton fragility
- **M3** DE SHAW — stop hardcoded `atr*2.0` em vez de `STOP_ATR_M`
- **M4** DE SHAW — funding `/ 32` hardcoded ignora
  `ENGINE_INTERVALS["DESHAW"]="1h"` (infla funding 4×)
- **M5** JUMP — macro gate inconsistente entre branches
- **M6** MEDALLION — TP `0.8×` stop (RR<1) fere `RR_MIN=1.5`. Tese
  documentada, mas precisa registro explícito

### 🟢 Low

- **L1** `max(score, 0.53)` literal em JUMP/BRIDGEWATER/DE SHAW em vez de
  `max(score, SCORE_THRESHOLD)` — cosmético mas drift-prone
- **L2** DE SHAW funding drift (M4 acima revisitado em low)
- **L3** PHI tem `notional_cap=0.02` próprio em vez de
  `check_aggregate_notional` (equivalente em single-position)
- **L4** `engines/medallion.py` + `tools/medallion_*` ainda untracked no
  git

## Pontos fortes

- Modelo de custos C1+C2 **replicado verbatim** em 9 engines direcionais
  (fórmula idêntica linha a linha)
- Entry `open[idx+1]` com slip+spread aplicado por direção em 100% dos
  engines
- **Zero data leakage** detectado (nenhum `shift(-N)`, nenhum indicador
  peek)
- Core protegido intacto (regra CLAUDE.md respeitada na branch
  feat/phi-engine)
- L6 (agg notional cap) + L7 (liquidation) presentes em todos os
  shared-core engines
- `ABLATION_DISABLE` flag para testes científicos sem tocar em
  `core/signals.py`

## Recomendações priorizadas

1. **DE SHAW H1** — ou chamar `portfolio_allows` de verdade, ou remover o
   import (honestidade de escopo)
2. **JUMP H2** — decidir: floor de 0 volta, ou documenta o motivo do
   drop num comentário permanente citando o backtest que motivou
3. **Criar `EXPERIMENTAL_ENGINES`** em `config/engines.py` pra marcar
   KEPOS/MEDALLION/GRAHAM/PHI — torna opt-out de gates globais
   consciente e visível
4. **DE SHAW M3/M4** — usar `STOP_ATR_M` e resolver funding por
   `ENGINE_INTERVALS`
5. **Substituir literais `0.53`** por `SCORE_THRESHOLD` em
   JUMP/BRIDGEWATER/DE SHAW
