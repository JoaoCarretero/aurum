# AURUM — Engine Briefing

> Referência operacional. Para cada engine: filosofia, melhor config validada,
> parâmetros chave e quando NÃO usar.
> Última calibração: master battery 2026-04-13.

---

## CITADEL — Systematic Momentum (Ω 5D)

**Inspiração:** Citadel LLC — quant momentum
**Arquivo:** `engines/backtest.py`
**Pipeline:** Data → indicators → swing → omega(5D) → macro filter → entry

### Meta
Captura tendências fortes via fractal de 5 dimensões: **struct, flow, cascade, momentum, pullback**. Só entra quando todas concordam — entradas raras, alta convicção. Stops em pivots de swing, target RR 2:1. Sizing Kelly × regime macro × convex × fractal.

### Melhor config (battery)
| Param | Valor | Por quê |
|---|---|---|
| TF | `15m` | Granularidade ideal pro fractal Ω |
| Período | **180 dias** | Precisa horizonte longo pra capturar regime cycle |
| Basket | `default` (11 alts) ou `bluechip` (20) | bluechip+90d=Sharpe 0.43; default+180d=4.43 |
| `RISK_SCALE_BY_REGIME` | `{BEAR:1.0, BULL:0.30, CHOP:0.50}` | Regime-adaptive — já é default via `ENGINE_RISK_SCALE_BY_REGIME["CITADEL"]` |
| `STOP_ATR_M` | `1.8` | Swing-based |
| `TARGET_RR` | `2.0` | Trailing multi-level após 1.5R |

### Resultados validados
- **180d default regime-adaptive** → Sharpe **4.43**, 256 trades, ROI +31%, MC 99%
- **90d default baseline** → Sharpe -0.58 ❌ (esperado, horizonte curto)
- **90d bluechip baseline** → Sharpe 0.43 ⚠️

### Quando NÃO usar
- Períodos < 120 dias (não captura regime)
- Mercado puramente lateral (CHOP) — RISK_SCALE corta sizing pra 50% mas ainda perde
- Alta concentração: 90% do PnL vem de 1-2 ativos (SUI, XRP, INJ)

### Como rodar
```bash
python -m engines.backtest --no-menu --days 180
```

---

## BRIDGEWATER — Macro Sentiment Contrarian

**Inspiração:** Bridgewater Associates — Ray Dalio
**Arquivo:** `engines/thoth.py`
**Pipeline:** Funding rate → OI delta → LS ratio → composite contrarian score

### Meta
"Quando todos estão gananciosos, tenha medo." Quantifica sentimento da multidão (funding extremo, OI squeeze, LS ratio polarizado) e **vai contra**. Quando posicionamento fica unilateral demais, sistema é instável e reverte.

### Melhor config (battery)
| Param | Valor | Por quê |
|---|---|---|
| TF | **`1h`** | 15m gera ruído; 4h tem poucos trades |
| Período | `90d` ou `180d` | Ambos performam |
| Basket | `default` ou `bluechip` | bluechip+1h+90d=Sharpe 10.57 |
| `THOTH_FUNDING_ENTRY` | `2.0` | z-score mínimo do funding |
| `THOTH_LS_CONTRARIAN` | `2.0` | ratio LS extremo |
| `THOTH_MIN_SCORE` | `0.30` | composite mínimo |

**TF override aplicado:** `ENGINE_INTERVALS["BRIDGEWATER"] = "1h"` em `params.py`. Roda 1h por default mesmo com `INTERVAL=15m` global.

### Resultados validados
- **1h default 90d** → Sharpe **5.06** (battery) / **11.37** (após Codex sentiment refactor), 269-1518 trades
- **1h bluechip 90d** → Sharpe **10.57**, 957 trades, MC 99%
- **1h bluechip 180d** → Sharpe **7.34**, 2090 trades, MC 99%
- **OOS walk-forward 1h 180d** → IS Sharpe 4.97, OOS 1.78 ✓
- **15m qualquer config** → Sharpe negativo ❌

### Quando NÃO usar
- TF 15m (ruído de funding domina sinal)
- Períodos < 30 dias (poucos eventos contrarians)
- Sem dados de funding/OI (binance API instável às vezes)

### Como rodar
```bash
python engines/thoth.py --no-menu --days 90 --basket default
```

---

## RENAISSANCE — Harmonic Patterns

**Inspiração:** Renaissance Technologies — Jim Simons
**Arquivo:** `engines/harmonics_backtest.py` (standalone) + `core/harmonics.py`
**Pipeline:** Detecção XABCD harmônicos → Bayesian probability → entropy + Hurst gates

### Meta
Padrões harmônicos clássicos (Gartley, Bat, Butterfly, Crab) filtrados por probabilidade Bayesiana. Entrada só quando entropia do mercado é baixa (estrutura ordenada) e Hurst > 0.5 (persistência). WR muito alto, poucos trades.

### Melhor config (battery)
| Param | Valor | Por quê |
|---|---|---|
| TF | `15m` | 1h e 4h reduzem trade count drasticamente |
| Período | `180d` | 90d gera 13 trades, 180d gera 68 |
| Basket | `default` | bluechip não foi testado |

### Resultados validados
- **15m default 180d** → Sharpe **6.58**, 68 trades, WR 88.2%, MaxDD 0.4% ✓
- **15m default 90d** → ~88 trades, Sharpe 4.7
- **1h / 4h** → trade count cai pra 3-13, sample size insuficiente

### Audit flag ⚠️
Inconsistência: artifact reporta **WR 85.23%**, audit do trade list mostra **61.36%**. Investigar `renaissance_audit.md` antes de live capital.

### Quando NÃO usar
- Live trading sem auditar discrepância de WR primeiro
- TFs > 1h (não há trades suficientes)

### Como rodar
```bash
python -m engines.harmonics_backtest --days 180 --basket default
```

---

## DE SHAW — Statistical Arbitrage (Pairs)

**Inspiração:** D.E. Shaw — David Shaw
**Arquivo:** `engines/newton.py`
**Pipeline:** Engle-Granger cointegration → z-score do spread → mean reversion

### Meta
Encontra pares cointegrados, opera spread quando z-score > 2σ, sai quando z cruza zero. Delta-neutral entre os dois ativos do par. Em teoria reduz exposição direcional.

### Melhor config (battery, mas SEM EDGE)
| Param | Valor | Resultado |
|---|---|---|
| TF | `4h` | 1h e 15m geram ruído cointegração |
| Período | `90d` | |
| `NEWTON_ZSCORE_ENTRY` | `2.0` | Sharpe 1.27, 92 trades |
| `NEWTON_ZSCORE_STOP` | `3.5` | |
| `NEWTON_HALFLIFE_MAX` | `500` | half-life máximo do spread |

### Resultados validados
- **Melhor:** stop=2.0 entry=2.0 4h 90d → Sharpe 1.27, MC 63% ⚠️
- **Bluechip:** 4h 90d → Sharpe 0.23, 232 trades, MC 56% ⚠️
- **Restante do grid:** 14 configs, todas Sharpe negativo ❌

### Status: operacional sem edge
Engine roda end-to-end mas universo de altcoins atual não tem pares estavelmente cointegrados. **Roadmap:** rolling cointegration (recalcular pares por janela em vez de fixo).

### Como rodar
```bash
python -m engines.newton --no-menu --days 90
```

---

## JUMP — Order Flow / Microstructure

**Inspiração:** Jump Trading
**Arquivo:** `engines/mercurio.py`
**Pipeline:** CVD divergence → volume imbalance → liquidation spike

### Meta
Captura microestrutura: cumulative volume delta divergente do preço, imbalance long/short extremo, spikes de liquidação. Trades curtos, alta frequência.

### Status: operacional sem edge
Battery mostrou Sharpe negativo em todas configs testadas:
- `majors 1h 90d` → 1 trade, sample insuficiente
- `majors 15m 90d` → 17 trades, Sharpe -4.22 ❌

Sentiment/flow signals não estão produzindo edge tradable. Classificar como **research-lab** até ML meta-layer (TWO SIGMA).

### Como rodar
```bash
python -m engines.mercurio --no-menu --days 90
```

---

## JANE STREET — Cross-Venue Arbitrage (Scanner)

**Inspiração:** Jane Street
**Arquivo:** `engines/arbitrage.py`
**Pipeline:** Multi-venue funding/spot scan → delta-neutral opportunity ranking

### Meta
Não é backtest direcional — é **scanner ao vivo** de oportunidades de arbitragem entre venues (Binance/Bybit/Hyperliquid/etc). Encontra delta-neutral spreads via funding rate diff + spot/perp basis.

### Resultado snapshot (último scan)
- Total opportunities: **241**
- Avg APR: **95.57%**
- Estimated monthly em $1k: **$79.64**
- Best venue: `mexc` · Worst: `backpack`

### Modo
Scanner real-time. Não tem "config vencedora" — é leitura de mercado.

### Como rodar
```bash
python -m engines.arbitrage   # menu interativo
```

---

## Meta-Engines (não testáveis standalone)

### TWO SIGMA — ML Meta-Ensemble
**Arquivo:** `engines/prometeu.py`
LightGBM walk-forward em cima dos trades de outros engines. **Bloqueado por design** — precisa histórico de 2+ engines validados primeiro.

### AQR — Evolutionary Allocation
**Arquivo:** `engines/darwin.py`
Aloca capital dinamicamente entre engines via fitness evolutivo. Lê trades existentes em `data/`. Roda **depois** dos engines individuais.

### MILLENNIUM — Multi-Strategy Pod
**Arquivo:** `engines/multistrategy.py`
Orquestrador interativo. Opção 7 = ALL engines em paralelo. Sem `--no-menu`, é GUI-driven.

---

## Tabela Síntese — onde rodar cada engine

| Engine | TF | Dias | Basket | Sharpe | Status |
|---|---|---|---|---|---|
| **CITADEL regime-adaptive** | 15m | **180** | default | **4.43** | ✅ edge |
| **BRIDGEWATER** | **1h** | 90 | bluechip | **10.57** | ✅ edge |
| **BRIDGEWATER** | **1h** | 180 | bluechip | **7.34** | ✅ edge |
| **RENAISSANCE** | 15m | 180 | default | **6.58** | ✅ edge ⚠️audit |
| DE SHAW | 4h | 90 | default | 1.27 | ⚠️ marginal |
| JUMP | 15m | 90 | majors | -4.22 | ❌ sem edge |
| JANE STREET | — | — | — | scanner | ✅ ops |

---

## Onde mexer parâmetros

**Single source of truth:** `config/params.py`

- Universo: `BASKETS` dict (default, bluechip, top12, defi, layer1...)
- TF override por engine: `ENGINE_INTERVALS`
- Risk override por engine: `ENGINE_RISK_SCALE_BY_REGIME`
- Custos: `SLIPPAGE`, `SPREAD`, `COMMISSION`, `FUNDING_PER_8H`
- Omega weights: `OMEGA_WEIGHTS` (5D)
- Stops/targets globais: `STOP_ATR_M`, `TARGET_RR`, `MAX_HOLD`
- Per-engine: prefixo `THOTH_*`, `NEWTON_*`, `MERCURIO_*`, `DARWIN_*`, `CHRONOS_*`

**Não mude global sem rodar nova bateria** — por isso o sistema tem `ENGINE_INTERVALS` / `ENGINE_RISK_SCALE_BY_REGIME` per-engine.

---

## Como rodar bateria nova

```bash
python -m tools.master_battery   # all engines × all configs × all TFs
# Output: data/param_search/YYYY-MM-DD/battery_full.csv
```

Após rodar, atualize este briefing + `ENGINE_INTERVALS` / `ENGINE_RISK_SCALE_BY_REGIME` em `params.py` com winners.
