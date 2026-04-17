# AURUM Finance — CLAUDE.md
# O disco lê a si mesmo. O universo roda em um CD. AURUM é o laser.

## Filosofia

O mercado é um CD — informação codificada em espiral de preço e volume,
ruído e sinal misturados. A maioria dos participantes está sendo lida:
reagindo ao feed, ao medo, à ganância, ao algoritmo de outra pessoa. São
o disco. São a liquidez que alguém colhe.

AURUM é o laser próprio. Soberania financeira via código.

### Princípios Herméticos no Código

- **Polaridade (0/1)**: Toda informação nasce da distinção. Sinais binários geram complexidade.
- **Gênero**: Nenhum indicador sozinho gera informação. O ensemble — Sortino × R-multiple × decay × regime — é a dança dos opostos.
- **Correspondência**: Fractal. O Ω 5D lê todas as camadas porque a estrutura se repete do 1m ao 1D.
- **Vibração**: O mercado nunca está parado. Regime detection, energia, inércia, atrito.
- **Causa e Efeito**: Cada trade tem expected value calculável. R-múltiplo. Probabilidade, não acaso.
- **Mentalismo**: "It from bit." O preço não é a realidade — é informação sobre a realidade.

### Mandamentos

1. **O disco se testa a si mesmo.** Walk-forward, Monte Carlo, ablation. Se não sobrevive ao Solve, não existe.
2. **O ruído é o inimigo.** Overfitting é desinformação. Regularização, OOS, MC — discriminação constante.
3. **O kill-switch é sagrado.** Três camadas de proteção. Drawdown velocity, exposure limits, anomaly. A húbris mata.
4. **Informação > Matéria.** Foco no processo, nunca no resultado isolado.
5. **O laser é soberano.** Nenhuma dependência externa para decisões críticas.
6. **A espiral é contínua.** Walk-forward permanente. O disco gira e se reescreve.
7. **Código é alquimia.** Limpo, documentado, modular. Cada função faz uma coisa.

---

## REGRA PERMANENTE — SESSION LOG

Ao final de cada sessão (quando o usuário disser **"para"**, **"commit final"**,
**"encerra"**, **"session log"**, ou quando o contexto estiver acabando),
gerar automaticamente o arquivo:

```
docs/sessions/YYYY-MM-DD_HHMM.md
```

Com este formato EXATO:

```markdown
# Session Log — YYYY-MM-DD HH:MM

## Resumo
[1-3 frases do que foi feito nesta sessão]

## Commits
| Hash | Mensagem | Arquivos |
|------|----------|----------|
| abc1234 | fix(newton): ... | engines/newton.py |
| def5678 | feat(launcher): ... | launcher.py |

## Mudanças Críticas
[Lista de mudanças que afetam lógica de sinais, custos, sizing, ou risco.
 Se nenhuma: "Nenhuma mudança em lógica de trading."]

## Achados
[Bugs encontrados, comportamentos inesperados, métricas suspeitas.
 Se nenhum: "Nenhum achado novo."]

## Estado do Sistema
- Smoke test: 156/156 (ou o que for)
- Backlog restante: [lista curta]
- Próximo passo sugerido: [1 frase]

## Arquivos Modificados
[Lista completa de arquivos tocados, com +/- linhas]

## Notas para o Joao
[Qualquer coisa que o Joao precisa saber, decidir, ou verificar
 antes da próxima sessão. Em português, direto.]
```

**Obrigatório:**
- Criar o diretório `docs/sessions/` se não existir
- Commitar o log junto com o último commit da sessão
- O log é para HUMANO ler, não para máquina. Clareza > completude.
- Se a sessão teve mudança em lógica de trading (sinais, custos, sizing,
  risco), destacar em **ATENÇÃO:** no markdown
- O log precisa ser autocontido — quem ler sem contexto deve entender

### REGRA COMPLEMENTAR — DAILY LOG

Além do session log, **sempre** gerar/atualizar o log do dia em:

```
docs/days/YYYY-MM-DD.md
```

Com este formato:

```markdown
# Daily Log — YYYY-MM-DD

## Sessões do dia
- HH:MM — [1 linha do que foi feito] — [link session log]
- HH:MM — [...]

## Entregas principais (consolidado)
- [3-5 bullets do que ficou de valor no dia, não commits individuais]

## Commits do dia: N

## Estado final
- Suite: X passed, Y skipped
- Mudanças em CORE de trading? SIM/NÃO
- Backlog top: [1-3 itens]

## Pendências pra amanhã
- [1-3 itens]

## Nota do dia
[1-2 frases livres — highlight, dor, ou celebração]
```

**Regras:**
- Se já existe log do dia, **incrementar** (adicionar a sessão nova no
  topo da lista de "Sessões do dia", atualizar consolidados)
- Se não existe, criar do zero
- Commitar junto com o session log do último trabalho do dia
- O daily log é visão macro — session logs são os granulares

---

## Arquitectura Real (Estado Actual)

### Estrutura de Ficheiros

```
aurum.finance/
├── config/
│   ├── params.py              ← SINGLE SOURCE OF TRUTH
│   ├── engines.py             ← Engine registry
│   ├── connections.json       ← Exchange connections
│   └── keys.json              ← API keys (gitignored)
├── core/                       ← Módulos reutilizáveis
│   ├── data.py                ← fetch, fetch_all, validate
│   ├── indicators.py          ← EMA, RSI, ATR, BB, swing_structure, omega
│   ├── signals.py             ← decide_direction, calc_levels, label_trade
│   ├── portfolio.py           ← detect_macro, portfolio_allows, position_size, check_aggregate_notional
│   ├── htf.py                 ← Multi-timeframe prepare & merge
│   ├── harmonics.py           ← RENAISSANCE harmonic patterns
│   ├── chronos.py             ← HMM regime, GARCH vol, Hurst
│   ├── sentiment.py           ← Funding, OI, LS ratio
│   ├── proc.py                ← Process manager (identity-verified Fase 1)
│   ├── fs.py                  ← robust_rmtree (OneDrive-safe)
│   ├── risk_gates.py          ← Fase 4 scaffold — circuit breakers
│   ├── audit_trail.py         ← Fase 4 scaffold — immutable order log
│   ├── key_store.py           ← Fase 4 scaffold — encrypted keys
│   ├── alchemy_state.py       ← Arbitrage dashboard reader
│   ├── alchemy_ui.py          ← Arbitrage TkInter cockpit
│   ├── connections.py         ← Multi-exchange connection manager
│   ├── market_data.py         ← Market data utilities (parallel fetch)
│   ├── portfolio_monitor.py   ← Real-time portfolio snapshots
│   ├── db.py                  ← SQLite persistence
│   ├── engine_base.py         ← Shared engine runtime setup
│   ├── exchange_api.py        ← Unified exchange REST API
│   └── ...
├── engines/                    ← Execution engines
│   ├── citadel.py             ← CITADEL systematic momentum
│   ├── live.py                ← Live engine (paper/demo/testnet/live)
│   ├── janestreet.py          ← JANE STREET cross-venue arbitrage
│   ├── millennium.py          ← MILLENNIUM ensemble orchestrator
│   ├── deshaw.py              ← DE SHAW pair cointegration
│   ├── bridgewater.py         ← BRIDGEWATER macro sentiment
│   ├── jump.py                ← JUMP order flow / microstructure
│   ├── twosigma.py            ← TWO SIGMA ML meta-ensemble
│   ├── aqr.py                 ← AQR evolutionary allocation
│   └── renaissance.py         ← RENAISSANCE harmonic patterns
├── analysis/                   ← Analytics, walkforward, MC, plots
├── bot/telegram.py            ← Telegram notifications + commands
├── launcher.py                ← Bloomberg-terminal TkInter GUI
├── aurum_cli.py               ← CLI interface
├── server/website/             ← React + Vite landing page
├── tests/                      ← pytest suite
├── tools/                      ← reconcile_runs.py and friends
├── docs/                       ← plans, audits, sessions
└── data/                       ← Run outputs (gitignored)
```

### Engines — Nomes e Identidades

| Logger        | Nome                | Inspiração     | Status OOS (2026-04-17) | Conceito |
|---------------|---------------------|----------------|-------------------------|---|
| `CITADEL`     | CITADEL v3.6        | Citadel LLC    | ✅ EDGE_DE_REGIME       | Systematic momentum, Ω fractal 5D |
| `RENAISSANCE` | RENAISSANCE         | RenTech        | ⚠️ inflado 2×, real ~2.4 | Harmonic Bayesian + entropy + Hurst |
| `JANE_STREET` | JANE STREET v5.0    | Jane Street    | ⚪ arb, não direcional  | Delta-neutral cross-venue arb |
| `DE_SHAW`     | DE SHAW             | D.E. Shaw      | 🔴 NO_EDGE              | Engle-Granger cointegration pairs |
| `BRIDGEWATER` | BRIDGEWATER         | Bridgewater    | 🔴 BUG_SUSPECT          | Macro sentiment contrarian |
| `JUMP`        | JUMP                | Jump Trading   | ✅ EDGE_DE_REGIME       | CVD divergence, imbalance, liquidation |
| `TWO_SIGMA`   | TWO SIGMA           | Two Sigma      | ⚪ fora da bateria OOS  | ML meta-ensemble LightGBM |
| `AQR`         | AQR                 | AQR Capital    | ⚪ fora da bateria OOS  | Evolutionary fitness allocation |
| `MILLENNIUM`  | MILLENNIUM          | Millennium Mgmt| orquestrador (meta)     | Multi-strategy pod orchestrator |
| `WINTON`      | WINTON              | Winton Group   | orquestrador (meta)     | HMM + GARCH + Hurst + seasonality |
| `PHI`         | PHI                 | —              | 🆕 em overfit_audit     | Fibonacci fractal, clusters multi-TF |
| `KEPOS`       | KEPOS               | Kepos Capital  | 🔴 INSUFFICIENT_SAMPLE  | Hawkes-based intensity |
| `MEDALLION`   | MEDALLION           | Medallion Fund | 🔴 NO_EDGE              | Berlekamp-Laufer 7-signal |
| `GRAHAM`      | GRAHAM              | Benjamin Graham| 🗄️ ARQUIVADO            | 4h value — overfit honesto |

### Pipeline de Sinais (CITADEL)

```
Data (Binance OHLCV+tbb)
  → indicators()           [EMA, RSI, ATR, BB, slope, vol_regime]
  → swing_structure()      [pivots, trend_struct, struct_strength]
  → omega()                [5D fractal scoring]
  → prepare_htf()          [multi-timeframe alignment]
  → detect_macro()         [BTC slope200 → BULL/BEAR/CHOP]
  → decide_direction()     [regime + chop + vol + fractal filters]
  → score_omega/chop()     [ensemble scoring]
  → calc_levels()          [entry open[idx+1], swing-stop, RR-target]
  → portfolio_allows()     [correlation + max positions]
  → position_size()        [Kelly × convex × DD scale × omega risk]
  → check_aggregate_notional()  [L6 cap — Fase 3.1]
  → label_trade()          [path-dependent: trailing, liquidation L7]
```

### Parâmetros Chave (config/params.py)

- **Universo**: 11 altcoins USDT (BNB, INJ, LINK, RENDER, NEAR, SUI, ARB, SAND, XRP, FET, OP)
- **Custos**: SLIPPAGE + SPREAD + COMMISSION + FUNDING_PER_8H (C1+C2 model)
- **Omega**: OMEGA_WEIGHTS (5D), SCORE_THRESHOLD, SCORE_BY_REGIME
- **Stops**: STOP_ATR_M (swing-based), TARGET_RR, trailing multi-level
- **Portfolio**: MAX_OPEN_POSITIONS, CORR hard/soft (0.80 / 0.75 → 40%)
- **Tesla 3·6·9**: 3 tiers × 6 backtest strategies × 9 engines

---

## Regras para Claude Code

### ⚠️ PROTOCOLO ANTI-OVERFIT (criado 2026-04-16 após OOS audit)

**Qualquer sweep, grid search, bateria, iteração de params DEVE seguir**
`docs/methodology/anti_overfit_protocol.md`. Não é opcional.

**Resumo dos 5 princípios:**

1. **Mecanismo > Iteração.** Hipótese escrita em 1 parágrafo ANTES de
   abrir código. Sem mecanismo defensável, arquiva antes de começar.
2. **Split antes de código.** Datas train/test/holdout hardcoded no topo
   do engine. Não mudam.
3. **Grid fechado.** Lista de N configs pré-registrada em
   `docs/engines/<engine>/grid.md`. Commit antes de rodar.
4. **DSR obrigatório.** Sharpe reportado SEM haircut por `n_trials` é
   mentira disfarçada. Todo sweep computa DSR.
5. **Regra de parada honra.** Falhou numa etapa → **ARQUIVA**. Sem
   "reformular universo", sem "mais um iter".

**Anti-patterns a REJEITAR:**
- Comentários `iter_N WINNER` em `config/params.py` (trocar por
  `tuned_on=[...], oos_sharpe=X`)
- "Reformular até achar edge" (é fishing expedition)
- Mesmo histórico pra tune e report
- Cherry-pick de symbol ou regime

**Regra meta:** 3 engines consecutivos arquivados → **PAUSAR e revisar
método**, não continuar batendo.

**Status OOS 2026-04-16 (referência):**
- ✅ CITADEL, JUMP — edge real confirmado
- ⚠️ RENAISSANCE — inflado 2×, real ~2.4
- ⚠️ BRIDGEWATER — bug-suspect
- 🔴 DE SHAW, KEPOS, MEDALLION — colapsaram ou não-funcionais
- Ver `docs/audits/2026-04-16_oos_verdict.md`

---

### ⚠️ CORE DE TRADING PROTEGIDO (qualquer agente: Claude, Codex, outros)

**Estes 4 arquivos NÃO podem ser modificados sem aprovação explícita do Joao:**

- `core/indicators.py` — EMA, RSI, ATR, BB, swing_structure, omega
- `core/signals.py` — decide_direction, calc_levels, label_trade
- `core/portfolio.py` — Kelly, position_size, check_aggregate_notional
- `config/params.py` — SLIPPAGE, COMMISSION, SIZE_MULT, thresholds

**Por quê:** backtests walk-forward calibrados (CITADEL, BRIDGEWATER,
DE SHAW, JUMP — Sharpe +31% a +114%) dependem do comportamento exato
desses módulos. Mudar a fórmula do RSI, o detector de pivots, ou os
custos **invalida todas as calibrações** e requer re-rodar grid search
+ walk-forward 6/6 do zero.

**Regra de ouro:** se um teste sintético não reproduz o comportamento
esperado, **AJUSTE o teste** (threshold, fixture, skip com reason).
NÃO ajuste o código real pra fazer teste passar. Isso é circular e
destrutivo — o teste existe pra caracterizar o código, não o contrário.

**Se for necessário tocar nesses 4 arquivos**, antes:
1. Explicitar a mudança + motivação ao Joao.
2. Apresentar plano de re-calibração dos backtests afetados.
3. Só mexer após aprovação explícita.

Incidente 2026-04-15: Codex tentou trocar RSI (EWM→rolling+tanh) e
swing_structure (backward→centered pivots) pra fazer asserts de
contract tests passarem. Claude detectou e reverteu. Pra nunca mais.

### NUNCA

1. Reestruturar sem pedido explícito. O sistema funciona. Aprender primeiro.
2. Renomear engines, loggers, ou variáveis. Os nomes têm história.
3. Remover código "morto" sem confirmar — pode ser feature flag.
4. Mudar `params.py` sem medir impacto no backtest (ver regra CORE acima).
5. Criar ficheiros paralelos (`utils2.py`). Usar estrutura existente.
6. Ignorar o modelo de custos C1+C2. Backtest sem custos é mentira.
7. **Tocar em código de live trading sem ler antes** (aprender > mexer).
8. **Modificar código real pra fazer teste passar** (ver regra CORE acima).

### SEMPRE

1. LER o ficheiro ANTES de editar.
2. TESTAR após mudança: `python smoke_test.py --quiet`
3. RESPEITAR single source of truth: `params.py` + `core/`
4. PRESERVAR imports: engines importam de `core.*` e `config.params`, nunca entre si (exceção documentada: `multistrategy` importa `engines/backtest.py`).
5. DOCUMENTAR em português. Engines em inglês.
6. MEDIR antes e depois em mudanças de sinais / indicadores / custos.
7. **Gerar session log ao final** (ver regra permanente acima).

### Convenções

- `from config.params import *` no topo de cada engine
- Run dirs: `data/{engine}/{YYYY-MM-DD_HHMM}/` com logs/, reports/, state/
- Índice canônico: `data/index.json` (reconciled via `tools/reconcile_runs.py`)
- Reports: JSON (machine) + HTML (visual)
- UTF-8 sempre. Platform: Windows-first (OneDrive, PyInstaller .exe)
- Commits atômicos com mensagem descritiva (subject + body)
- Mudanças destrutivas: confirmar com usuário antes

---

## Contexto

- **Dev**: Joao (PT-BR), Windows 11, Python 3.14, VPS Linux para live
- **Exchange primária**: Binance Futures USDT-M
- **Total**: ~26,000+ linhas de código Python, 9 engines, launcher GUI, CLI, website
- **Filosofia**: Hermetismo como scaffolding conceitual — não decoração
- **Plano mestre ativo**: `docs/superpowers/plans/2026-04-11-aurum-professional-fund-readiness.md`

> "Quem está lendo e quem está sendo lido? AURUM lê. O varejo é lido."
