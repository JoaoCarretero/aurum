# Autonomous Battery — Final Report

**Session:** `2026-04-14_1410`
**Duration:** 36.3min
**Total runs:** 94 (CITADEL 22 · DE SHAW 34 · JUMP 38)
**CSV:** `data/param_search/2026-04-14/autonomous_battery.csv`

---

## Mission

Achar edge em **CITADEL**, **JUMP** e **DE SHAW** via grid tuning em múltiplos períodos/baskets. Verificar se edge persiste em janelas longas (90d→360d).

---

## Veredito por engine

### 🟢 CITADEL — Edge forte, melhor config nova encontrada

**Winner:** `stop-wide` (STOP_ATR_M=2.5, TARGET_RR=3.0) @ 15m/180d/default
- **Sharpe 6.33** (antes: baseline 4.60)
- 307 trades · WR 65.5% · ROI +47% · DD 3.9% · MC 100% · WF **79%** estável
- Config melhora Sharpe +38% sobre baseline atual

**Top 5 CITADEL:**
| Config | Sharpe | Trades | WR | MC | WF |
|---|---|---|---|---|---|
| **stop-wide** | **6.33** | 307 | 65% | 100% | 79% ⭐ |
| score-058 | 5.80 | 291 | 62% | 100% | 56% |
| score-058+adaptive | 5.80 | 291 | 62% | 100% | 56% |
| score-060 | 5.79 | 291 | 62% | 100% | 56% |
| regime-adaptive (atual default) | 5.12 | 282 | 61% | 100% | 62% |

**Persistência em 360d:** `stop-wide` mantém Sharpe **4.79** (592 trades, MC 100%). Edge robusto em janela longa.

**Recomendação:** aplicar `stop-wide` como novo default CITADEL.
```python
STOP_ATR_M = 2.5  # era 1.8
TARGET_RR  = 3.0  # era 2.0
```

---

### 🟡 DE SHAW — Primeira luz, edge ainda em sample pequeno

**Winner técnico:** `pval-tight` (NEWTON_COINT_PVALUE=0.01) @ 4h/90d/bluechip
- **Sharpe 3.00** · 35 trades · WR 74% · DD 1.8% · MC **0%** ⚠️
- MC 0% é suspeito — pouco sample, Monte Carlo não validou

**Mais robusto:** `baseline` @ 4h/360d/default
- Sharpe **1.60** · 132 trades · WR 69% · DD 7.9% · MC **92%** ✅ ← edge validado

**Top 5 DE SHAW:**
| Config | TF | Period | Basket | Sharpe | Trades | MC |
|---|---|---|---|---|---|---|
| pval-tight | 4h | 90d | bluechip | 3.00 | 35 | 0% ⚠ |
| z-1.5/3.0 | 4h | 90d | bluechip | 1.86 | 218 | 78% |
| **baseline** | **4h** | **360d** | **default** | **1.60** | **132** | **92%** ✅ |
| hl-500 | 4h | 90d | bluechip | 1.59 | 139 | 84% |
| z-2.5/4.0 | 4h | 90d | bluechip | 1.56 | 89 | 88% |

**Recomendação:** promover DE SHAW de "no edge" pra **operational marginal** com config:
- TF 4h
- Período 360d mínimo
- Basket default ou bluechip
- Params atuais (ou z-entry 1.5 se quiser mais sample)

**Próximo passo:** rolling cointegration (recalcular pares por janela) pra tentar subir Sharpe acima de 2.

---

### 🔴 JUMP — Sem edge, todas configs negativas

**Best of worst:** `baseline` @ 15m/360d/default → Sharpe -3.05

**Todas 38 configs testadas retornaram Sharpe negativo.** MC 0-2% em quase tudo.

Grid testou: MIN_SCORE (0.40/0.60/0.70), VIMB thresholds, LIQ_VOL_MULT, SIZE_MULT. Nenhum toggle salvou.

**Veredito:** JUMP na sua forma atual não tem edge em altcoins. CVD + volume imbalance + liquidações não está gerando sinal lucrativo no universo testado.

**Caminhos possíveis:**
1. Mudar universo — talvez edge só exista em BTC/ETH puro
2. Rewrite do pipeline — CVD sozinho é ruído, precisa combinar com outro estimador
3. Classificar como **research-lab permanente** — feeder pra TWO SIGMA (ML meta-ensemble)

**Recomendação:** não investir mais bateria no JUMP atual. Arquivar e retomar só se reescrevermos o pipeline.

---

## Insights gerais

1. **Período importa muito:** CITADEL 180d default domina 90d. Edge precisa de ciclo de regime.
2. **Default basket > bluechip** em quase tudo — exceto JUMP (todos ruins) e DE SHAW 90d (bluechip vence mas pode ser overfit).
3. **STOP_ATR_M=2.5 é um insight novo:** stops mais largos capturam mais swing em tendências fortes, reduzindo stop-outs prematuros.
4. **TARGET_RR=3.0** complementa stops largos — mantém expectancy positiva.
5. **regime-adaptive vs regime-aggressive** deram mesmo Sharpe 5.12 — no universo testado, regime filter não está fazendo diferença (BULL+BEAR rodaram em 60d do período, CHOP minoritário).

---

## Ações recomendadas (ordem de prioridade)

### P0 — imediato
- [ ] Aplicar `stop-wide` como default CITADEL (`STOP_ATR_M=2.5`, `TARGET_RR=3.0`)
- [ ] Documentar DE SHAW 4h/360d/default como config "marginal edge" no BRIEFING

### P1 — curto prazo
- [ ] Validar `stop-wide` em 720d / 1500d (teste de estresse em janela longa)
- [ ] Rodar CITADEL ensemble BRIDGEWATER + stop-wide em paper trading
- [ ] Investigar por que JUMP não tem edge (rewrite ou archive)

### P2 — médio prazo
- [ ] Rolling cointegration pra DE SHAW
- [ ] Reescrever JUMP se quiser manter como engine ativa
- [ ] TWO SIGMA (ML meta) alimentado por CITADEL + BRIDGEWATER + RENAISSANCE

---

## Grid detalhado (referência)

### CITADEL (22 runs)
- 6 baselines (90/180/360 × default/bluechip)
- 16 tuning: regime-adaptive, regime-aggressive, score-058/060, stop-tight/wide, rr-3x, score-058+adaptive × 2 periods × default basket

### DE SHAW (34 runs)
- 6 baselines (90/180/360 × default/bluechip) @ 4h
- 28 tuning: z-1.5/3.0, z-2.0/3.5, z-2.5/4.0, hl-100/500, pval-tight/loose × 2 periods × 2 baskets

### JUMP (38 runs)
- 6 baselines (90/180/360 × default/bluechip) @ 15m
- 32 tuning: 8 configs × 2 periods × 2 baskets

---

## Filosofia

> "Nada é perfeito, só queremos seguir a harmonia do universo dentro do mercado."

CITADEL encontrou ressonância em stops largos + RR 3:1. DE SHAW precisa de tempo longo pra cointegração emergir. JUMP, na configuração atual, não escuta o mercado certo — ou o mercado atual não está falando a língua que JUMP sabe ouvir.
