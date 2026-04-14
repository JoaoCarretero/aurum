# AURUM — Engine Briefing

> Referência operacional dos engines. Para cada um: o que faz, parâmetros de
> entrada e como rodar. Resultados e calibrações vêm de quem testar —
> o briefing só explica os knobs.

---

## CITADEL — Systematic Momentum (Ω 5D)

**Inspiração:** Citadel LLC
**Arquivo:** `engines/citadel.py`
**Pipeline:** Data → indicators → swing → omega(5D) → macro filter → entry

### O que faz
Captura tendências fortes via fractal de 5 dimensões — **struct, flow, cascade, momentum, pullback**. Só entra quando as 5 concordam: entradas raras, alta convicção. Stops em pivots de swing, target RR. Sizing Kelly × regime macro × convex × fractal.

### Parâmetros (em `config/params.py`)
| Param | O que é |
|---|---|
| `INTERVAL` / `ENTRY_TF` | Timeframe de entrada (ex: `15m`, `1h`, `4h`) |
| `SCAN_DAYS` | Horizonte do backtest em dias |
| `BASKETS[...]` | Universo de ativos (default, bluechip, majors, top12, defi, layer1...) |
| `OMEGA_WEIGHTS` | Pesos das 5 dimensões do fractal Ω |
| `SCORE_THRESHOLD` | Score Ω mínimo para disparar entrada |
| `SCORE_BY_REGIME` | Threshold por regime macro (BULL/BEAR/CHOP) |
| `RISK_SCALE_BY_REGIME` | Multiplicador de sizing por regime |
| `STOP_ATR_M` | Distância do stop em múltiplos de ATR (swing-based) |
| `TARGET_RR` | Risk-reward do target |
| `TRAIL_*` | Parâmetros de trailing multi-level após 1.5R |
| `MAX_HOLD` | Máximo de candles segurando o trade |
| `MAX_OPEN_POSITIONS` | Cap global de posições simultâneas |
| `CORR_THRESHOLD` / `CORR_SOFT_THRESHOLD` | Filtro de correlação hard/soft |

### Quando NÃO usar
- Horizontes curtos (sistema precisa de ciclo de regime)
- Mercado puramente lateral prolongado

### Como rodar
```bash
python -m engines.citadel --no-menu --days 180
```

---

## BRIDGEWATER — Macro Sentiment Contrarian

**Inspiração:** Bridgewater Associates
**Arquivo:** `engines/bridgewater.py`
**Pipeline:** Funding rate → OI delta → LS ratio → composite contrarian score

### O que faz
"Quando todos estão gananciosos, tenha medo." Quantifica sentimento da multidão (funding extremo, OI squeeze, LS ratio polarizado) e **vai contra**. Quando posicionamento fica unilateral demais, o sistema é instável e reverte.

### Parâmetros (`THOTH_*` em `config/params.py`)
| Param | O que é |
|---|---|
| `THOTH_FUNDING_WINDOW` | Períodos de 8h para calcular z-score do funding |
| `THOTH_FUNDING_ENTRY` | `|z-score|` mínimo do funding para sinal |
| `THOTH_OI_WINDOW` | Candles para delta de Open Interest |
| `THOTH_LS_CONTRARIAN` | Ratio Long/Short > N → crowd long demais (sinal short) |
| `THOTH_LS_CONTRARIAN_LOW` | Ratio Long/Short < N → crowd short demais (sinal long) |
| `THOTH_WEIGHT_FUNDING` / `_OI` / `_LS` | Pesos no composite score |
| `THOTH_MIN_SCORE` | Composite mínimo para entrada |
| `THOTH_DIRECTION_THRESHOLD` | `|sent_score|` mínimo para gerar direção |
| `THOTH_SIZE_MULT` | Multiplicador de position size |
| `ENGINE_INTERVALS["BRIDGEWATER"]` | TF override por engine (sobrescreve `INTERVAL`) |

### Quando NÃO usar
- Sem dados de funding/OI disponíveis (API instável)
- Períodos muito curtos (poucos eventos contrarians)

### Como rodar
```bash
python -m engines.bridgewater --no-menu --days 90 --basket default
```

---

## RENAISSANCE — Harmonic Patterns

**Inspiração:** Renaissance Technologies
**Arquivo:** `engines/renaissance.py` + `core/harmonics.py`
**Pipeline:** Detecção XABCD → Bayesian probability → entropy + Hurst gates

### O que faz
Padrões harmônicos clássicos (Gartley, Bat, Butterfly, Crab) filtrados por probabilidade Bayesiana. Entrada só quando entropia do mercado é baixa (estrutura ordenada) e Hurst > 0.5 (persistência). WR alto por desenho, poucos trades.

### Parâmetros
| Param | O que é |
|---|---|
| `INTERVAL` | TF de detecção dos padrões |
| `SCAN_DAYS` | Horizonte |
| `BASKETS[...]` | Universo |
| `CHRONOS_HURST_WINDOW` / `_MIN` | Gate de persistência (Hurst) |
| Gates de entropia internos ao `core/harmonics.py` | Ordem do mercado |

### Quando NÃO usar
- TFs longos (1h+): trade count cai pra sample insuficiente
- Live trading sem auditar discrepâncias de WR reportadas

### Como rodar
```bash
python -m engines.renaissance --days 180 --basket default
```

---

## DE SHAW — Statistical Arbitrage (Pairs)

**Inspiração:** D.E. Shaw
**Arquivo:** `engines/deshaw.py`
**Pipeline:** Engle-Granger cointegration → z-score do spread → mean reversion

### O que faz
Encontra pares cointegrados, opera o spread quando z-score passa do threshold, sai quando z cruza zero. Delta-neutral entre os dois ativos do par — em teoria reduz exposição direcional.

### Parâmetros (`NEWTON_*` em `config/params.py`)
| Param | O que é |
|---|---|
| `NEWTON_ZSCORE_ENTRY` | `|z-score|` mínimo para entrar no spread |
| `NEWTON_ZSCORE_EXIT` | z-score de saída (cruzamento com 0) |
| `NEWTON_ZSCORE_STOP` | `|z-score|` máximo antes de stop (spread divergindo) |
| `NEWTON_COINT_PVALUE` | p-value máximo pra considerar o par cointegrado |
| `NEWTON_HALFLIFE_MIN` / `_MAX` | Faixa aceitável de half-life do spread (em candles) |
| `NEWTON_SPREAD_WINDOW` | Rolling window para z-score |
| `NEWTON_RECALC_EVERY` | Re-testar cointegração a cada N candles |
| `NEWTON_MAX_HOLD` | Máximo de candles por trade |
| `NEWTON_SIZE_MULT` | Position size relativo ao normal |
| `NEWTON_MIN_PAIRS` | Mínimo de pares cointegrados para engine operar |

### Quando NÃO usar
- Universos sem pares estavelmente cointegrados
- TFs baixos (ruído domina a cointegração)

### Como rodar
```bash
python -m engines.deshaw --no-menu --days 90
```

---

## JUMP — Order Flow / Microstructure

**Inspiração:** Jump Trading
**Arquivo:** `engines/jump.py`
**Pipeline:** CVD divergence → volume imbalance → liquidation spike

### O que faz
Captura microestrutura — cumulative volume delta divergente do preço, imbalance long/short extremo, spikes de liquidação. Trades curtos, alta frequência.

### Parâmetros (`MERCURIO_*` em `config/params.py`)
| Param | O que é |
|---|---|
| `MERCURIO_CVD_WINDOW` | Janela para cálculo de CVD |
| `MERCURIO_CVD_DIV_BARS` | Lookback para detectar divergência CVD vs preço |
| `MERCURIO_VIMB_WINDOW` | Janela para volume imbalance |
| `MERCURIO_VIMB_LONG` | Imbalance > N → sinal bullish |
| `MERCURIO_VIMB_SHORT` | Imbalance < N → sinal bearish |
| `MERCURIO_LIQ_VOL_MULT` | Spike de volume > N× média → liquidação |
| `MERCURIO_LIQ_ATR_MULT` | Spike de ATR > N× média → liquidação |
| `MERCURIO_MIN_SCORE` | Score mínimo para entrada |
| `MERCURIO_SIZE_MULT` | Position size multiplier |

### Quando NÃO usar
- Universos sem dados de trade flow confiáveis
- TFs baixos com poucos trades

### Como rodar
```bash
python -m engines.jump --no-menu --days 90
```

---

## JANE STREET — Cross-Venue Arbitrage (Scanner)

**Inspiração:** Jane Street
**Arquivo:** `engines/janestreet.py`
**Pipeline:** Multi-venue funding/spot scan → delta-neutral opportunity ranking

### O que faz
Não é backtest direcional — é **scanner ao vivo** de oportunidades de arbitragem entre venues (Binance / Bybit / Hyperliquid / MEXC / Backpack / etc). Encontra delta-neutral spreads via funding rate diff + spot/perp basis.

### Parâmetros (`ARB_*` em `config/params.py`)
| Param | O que é |
|---|---|
| `ARB_SCORE_WEIGHTS` | Pesos de cada componente no score final |
| `ARB_SCORE_THRESHOLDS` | Thresholds `go` / `maybe` para classificar oportunidade |
| `ARB_FILTER_DEFAULTS` | Filtros default aplicados no scan (APR mínimo, liquidez, etc) |
| `ARB_VENUE_RELIABILITY` | Peso de reliability por venue |
| `ARB_POSITION_SIZE_REF` | Tamanho de posição referência para cálculo de PnL esperado |

### Modo
Scanner real-time. Não tem "config vencedora" — é leitura de mercado.

### Como rodar
```bash
python -m engines.janestreet   # menu interativo
```

---

## Meta-Engines (não testáveis standalone)

### TWO SIGMA — ML Meta-Ensemble
**Arquivo:** `engines/twosigma.py`
LightGBM walk-forward em cima dos trades de outros engines. **Bloqueado por design** — precisa histórico de 2+ engines individuais antes de treinar.

### AQR — Evolutionary Allocation
**Arquivo:** `engines/aqr.py`
Aloca capital dinamicamente entre engines via fitness evolutivo. Lê trades existentes em `data/`. Roda **depois** dos engines individuais.

**Parâmetros (`DARWIN_*`):**
| Param | O que é |
|---|---|
| `DARWIN_EVAL_WINDOW` | Trades por janela de avaliação |
| `DARWIN_MUTATION_CYCLE` | Trades entre tentativas de mutação |
| `DARWIN_MUTATION_RANGE` | Perturbação ± de parâmetros |
| `DARWIN_MUTATION_MIN_IMPR` | Melhoria mínima para adoptar mutação |
| `DARWIN_KILL_WINDOWS` | Janelas negativas consecutivas → pause do engine |
| `DARWIN_ALLOC_TOP` / `_ABOVE` / `_BELOW` / `_KILLED` | Alocação de capital por tier de performance |

### MILLENNIUM — Multi-Strategy Pod
**Arquivo:** `engines/millennium.py`
Orquestrador interativo. Opção 7 = ALL engines em paralelo. GUI-driven (sem `--no-menu`).

---

## Parâmetros compartilhados (todos os engines)

**Single source of truth:** `config/params.py`

**Universo & timeframe**
- `BASKETS` — dicionário de universos (default, bluechip, majors, top12, defi, layer1, layer2, ai, meme, custom)
- `SYMBOLS` — universo default
- `INTERVAL` / `ENTRY_TF` — timeframe de entrada global
- `SCAN_DAYS` — dias de histórico
- `ENGINE_INTERVALS` — override de TF por engine
- `HTF_STACK` / `MTF_ENABLED` — stack de timeframes superiores

**Conta & risco**
- `ACCOUNT_SIZE`, `BASE_RISK`, `MAX_RISK`, `LEVERAGE`, `KELLY_FRAC`, `CONVEX_ALPHA`

**Custos (C1+C2 model)**
- `SLIPPAGE`, `SPREAD`, `COMMISSION`, `FUNDING_PER_8H`

**Portfolio & correlação**
- `MAX_OPEN_POSITIONS`, `CORR_THRESHOLD`, `CORR_SOFT_THRESHOLD`, `CORR_SOFT_MULT`, `CORR_LOOKBACK`

**Macro regime**
- `MACRO_SYMBOL`, `MACRO_SLOPE_BULL`, `MACRO_SLOPE_BEAR`
- `RISK_SCALE_BY_REGIME`, `SCORE_BY_REGIME`
- `ENGINE_RISK_SCALE_BY_REGIME` — override por engine

**Volatilidade & chop**
- `VOL_WINDOW`, `VOL_LOW_PCT`, `VOL_HIGH_PCT`, `VOL_RISK_SCALE`
- `CHOP_*` — parâmetros do regime lateral

**Drawdown & cooldown**
- `DD_RISK_SCALE`, `STREAK_COOLDOWN`, `SYM_LOSS_COOLDOWN`
- `REGIME_TRANS_*` — detecção de transição de regime

**MC & walk-forward**
- `MC_N`, `MC_BLOCK`, `WF_TRAIN`, `WF_TEST`

---

## Como testar um engine

1. Ajustar os parâmetros do engine em `config/params.py`
2. Rodar o comando `--no-menu` do engine com `--days` e `--basket`
3. Output vai para `data/<engine>/<YYYY-MM-DD_HHMM>/` com logs, reports JSON e HTML
4. Reports visuais: abrir `reports/*.html`
5. Reconciliar índice: `python -m tools.reconcile_runs`

**Regra:** cada mudança em parâmetro → rodar backtest → medir → decidir. Não assuma config — teste.
