# Longrun Battery Report — 2026-04-14

**Objetivo:** validar edge + robustez de todos engines em período longo (360d+) antes de paper trading. Descobrir TF/basket sweet-spot por engine. Documentar como vencedores ou condenados.

**Metodologia:**
- Bateria sequencial/paralela de 5 engines
- Período: 360d (bluechip/default) + 720d confirmação (JUMP)
- Basket: `bluechip` (20 symbols) e `default` (11 altcoins)
- Robustness: 6 overfit tests (walk-forward, sensitivity, concentration, regime, temporal, slippage)

---

## Roster consolidado (TFs/baskets calibrados)

Persistido em `config/params.py` — `ENGINE_INTERVALS` + `ENGINE_BASKETS`.

| Engine | TF | Basket | Sharpe | ROI% | MaxDD% | Trades | Overfit | Status |
|---|---|---|---|---|---|---|---|---|
| 🏆 **RENAISSANCE** | 15m | bluechip | **+5.65** | +17.3 | 0.76 | 208 | **6/6 PASS** | Premium |
| 🏆 **JUMP** | 1h | bluechip (720d) | **+2.06** | +12.0 | 1.90 | 49 | **6/6 PASS** | Premium |
| 🏆 **DE SHAW** | 1h | bluechip | **+2.65** | +108.6 | 11.49 | 2486 | 3P 3W 0F | Forte |
| ✓ **CITADEL** | 15m | default | +1.38 | +10.8 | 9.87 | 501 | 3P 1W 2F | OK |
| ~ **BRIDGEWATER** | 1h | bluechip | +0.87 | +11.4 | 17.74 | 4101 | 3P 3F | Modesto |

---

## Achados por engine

### RENAISSANCE 🏆 (TF 15m · bluechip · 360d)
Sharpe 5.65, 6/6 overfit tests PASS. Walk-forward: 5/5 janelas com expectancy positiva. Decay temporal -31% (edge MELHORA ao longo do tempo). Breakeven slippage 22bp. **Não tocar em params.**

### JUMP 🏆 (TF 1h · bluechip · 720d)
Descoberta crítica: engine estava quebrado em 15m (Sharpe -2.95) por ruído no order flow. Em 1h, sinal limpa e vira +2.06 Sharpe com 6/6 overfit PASS em 720d. Breakeven 36bp. Seletivo — 49 trades em 2 anos, mas todos de alta convicção. **Não tocar.**

### DE SHAW 🏆 (TF 1h · bluechip · 360d)
TF original testado (15m) era errado — pairs cointegration precisa de half-life maior. Em 1h: Sharpe 2.65, 3 PASS 3 WARN 0 FAIL. ROI +108%. DOTUSDT representa 56% do PnL (warning de concentração). Decay 83% (edge afinando lentamente). **Não tocar. Monitorar concentração.**

### CITADEL ✓ (TF 15m · default · 360d)
Hipótese "bluechip era basket errado" confirmada. Em `default` (11 altcoins originais) Sharpe vira +1.38 (era -0.35 em bluechip). Concentração SUIUSDT 51% (WARN). Reproduzibilidade agora determinística (fix em `core/data.py`).

### BRIDGEWATER ~ (TF 1h · bluechip · 360d)
Único engine que já estava calibrado corretamente (TF 1h em `ENGINE_INTERVALS`). Sharpe +0.87 modesto mas positivo. 3 PASS / 3 FAIL — regime só BEAR lucrativo, concentração XRPUSDT, slippage breakeven 3bp (frágil). Útil como macro sentiment backup.

---

## Bugs descobertos + fixes aplicados

| # | Bug | Fix | Commit |
|---|---|---|---|
| 1 | RENAISSANCE/JUMP não geravam `overfit.json` | Adicionado `run_audit()` + `overfit_results=` param em ambos engines | pendente |
| 2 | DE SHAW/JUMP não aceitavam `--interval` flag | Argparse estendido; INTERVAL override aplicado antes de N_CANDLES | pendente |
| 3 | `fetch_all` omitia símbolos silenciosamente (quebra determinismo) | Retry 3x com backoff em exceções/5xx; log ERROR + print loud de símbolos missing | pendente |
| 4 | `RUN_ID` precisão de minuto causava colisão entre runs simultâneos | **NÃO CORRIGIDO** — mitigação: staggering 60s entre lançamentos paralelos do mesmo engine | backlog |
| 5 | JUMP `exit_reason` gravado como "?" em 100% trades | **NÃO CORRIGIDO** — requer mudança em `core/signals.py label_trade()` que afeta outros engines | backlog |

---

## Next steps — Fase 3 (paper readiness)

1. **Commit das mudanças** (engines modificados + config/params.py + report)
2. **Fix backlog bug #4** — upgrade `create_run_dir` pra precisão de segundos/micros
3. **Fix backlog bug #5** — estender `label_trade()` pra retornar exit_reason tupla
4. **Consolidar paper-mode config** — allocations entre os 5 engines, risk caps per engine, kill-switch thresholds
5. **Integration test** — rodar launcher GUI + verificar que todos engines pegam configs do `ENGINE_INTERVALS`/`ENGINE_BASKETS` corretamente
6. **MILLENNIUM + AQR + TWO SIGMA** — meta-ensembles que consumem outputs; validar se conseguem compor os 5 vencedores

---

## Dados-fonte

Run dirs consultados:

```
data/runs/citadel_2026-04-14_1804    (CITADEL default 15m 360d — reprod 1)
data/runs/citadel_2026-04-14_1805    (CITADEL default 15m 360d — reprod 2)
data/renaissance/2026-04-14_1710     (RENAISSANCE bluechip 15m 360d)
data/deshaw/2026-04-14_1710          (DE SHAW bluechip 1h 360d)
data/deshaw/2026-04-14_1714          (DE SHAW bluechip 4h 360d)
data/jump/2026-04-14_1710            (JUMP bluechip 15m 360d — condenado)
data/jump/2026-04-14_1804            (JUMP default 1h 360d)
data/jump/2026-04-14_1805            (JUMP bluechip 1h 720d — premium)
data/bridgewater/2026-04-14_1658     (BRIDGEWATER bluechip 1h 360d)
```

Manifest central: `data/exports/longrun_battery_2026-04-14_1633/manifest.json`
