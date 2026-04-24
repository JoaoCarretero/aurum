# CONTEXT.md — O mapa do território AURUM

> **Propósito:** onde tudo vive, como as peças se encaixam, o que roda
> onde. Lido pra entender arquitetura antes de mexer em qualquer módulo.
> Para regras e fatos permanentes, ver `MEMORY.md`.
> Para quem opera o código, ver `AGENTS.md`.
> Para quando usar cada workflow, ver `SKILLS.md`.

---

## 1. Filosofia (resumo — completo em CLAUDE.md)

> O mercado é um CD. A maioria está sendo lida. AURUM é o laser.

- **Polaridade**: sinais binários → complexidade
- **Gênero**: ensemble Sortino × R-multiple × decay × regime
- **Correspondência**: fractal Ω 5D do 1m ao 1D
- **Vibração**: regime detection constante
- **Causa/Efeito**: R-múltiplo, probabilidade > acaso
- **Mentalismo**: preço é informação sobre realidade, não a realidade

**Mandamentos:** Walk-forward > promessa. Ruído é o inimigo. Kill-switch é sagrado. Informação > matéria. Soberania > dependência. Espiral contínua. Código é alquimia.

---

## 2. Árvore de diretórios — o que vive onde

```
aurum.finance/
├── CLAUDE.md                    ← regras profundas de trabalho (lidas pelo Claude Code)
├── AGENTS.md                    ← quem opera o repo
├── MEMORY.md                    ← fatos permanentes, CORE, keys.json, status engines
├── CONTEXT.md                   ← ESTE — arquitetura
├── SKILLS.md                    ← workflows e quando invocar
├── README.md                    ← entry point humano
│
├── config/                      CONFIG (single source of truth)
│   ├── params.py                ← SST — trading params, custos, thresholds
│   ├── engines.py               ← registry canônico de engines
│   ├── paths.py                 ← path constants
│   ├── risk_gates.json          ← circuit breakers por modo (paper/demo/testnet/live)
│   ├── runtime.py               ← runtime config
│   ├── macro_params.py          ← macro_brain params
│   ├── janestreet_defaults.py   ← arb scanner defaults
│   ├── paper_state.json         ← estado persistido do paper trading
│   ├── connections.json         ← multi-exchange (Binance, Bybit, HL, MEXC, Backpack...)
│   ├── keys.json                ← INTOCÁVEL (gitignored)
│   └── keys.json.example        ← template de referência
│
├── core/                        MÓDULOS REUTILIZÁVEIS
│   ├── indicators.py            ← 🔒 EMA, RSI, ATR, BB, swing_structure, omega
│   ├── signals.py               ← 🔒 decide_direction, calc_levels, label_trade
│   ├── portfolio.py             ← 🔒 Kelly, position_size, aggregate notional
│   ├── data.py                  ← fetch, fetch_all, validate (via data/)
│   ├── htf.py                   ← multi-timeframe prepare & merge
│   ├── harmonics.py             ← RENAISSANCE harmonic patterns library
│   ├── chronos.py               ← HMM regime, GARCH vol, Hurst
│   ├── sentiment.py             ← funding, OI, LS ratio (cache reprodutível)
│   ├── hawkes.py                ← Hawkes endogeneity (KEPOS, GRAHAM arquivados)
│   ├── cache.py                 ← JSON cache (era pickle → eliminou RCE)
│   ├── engine_base.py           ← shared engine runtime setup
│   ├── engine_picker.py         ← engine selection
│   ├── exchange_api.py          ← unified REST API
│   ├── market_data.py           ← parallel fetch utilities
│   ├── portfolio_monitor.py     ← real-time portfolio snapshots (deepcopy safe)
│   ├── db.py                    ← SQLite persistence
│   ├── db_live_runs.py          ← live_runs table ops
│   ├── proc.py                  ← process manager (identity-verified)
│   ├── fs.py                    ← atomic_write, robust_rmtree (OneDrive-safe)
│   ├── alchemy_state.py         ← arbitrage dashboard state reader
│   ├── alchemy_ui.py            ← arbitrage TkInter cockpit
│   ├── connections.py           ← lazy multi-exchange connection manager
│   ├── funding_scanner.py       ← JANE STREET scanner core
│   ├── shadow_contract.py       ← shadow trade validation
│   ├── evolution.py             ← AQR evolutionary fitness
│   ├── health.py                ← system health checks
│   ├── hmm_cache.py             ← HMM regime cache
│   ├── htf_filter.py            ← HTF alignment filter
│   ├── metrics_helpers.py       ← analytics helpers
│   ├── fixture_capture.py       ← test fixture generation
│   ├── failure_policy.py        ← error handling policy
│   ├── persistence.py           ← state persistence
│   ├── run_manager.py           ← file lock + unique run IDs
│   ├── transport.py             ← network transport
│   ├── versioned_state.py       ← versioned state mgmt
│   ├── site_runner.py           ← site runner
│   ├── mt5.py                   ← MetaTrader 5 adapter
│   ├── ui/                      ← TkInter UI widgets
│   ├── ui_palette.py            ← color palette
│   ├── risk/                    ← risk/
│   │   ├── key_store.py         ← encrypted keys (use load_runtime_keys)
│   │   └── audit_trail.py       ← immutable order log (hash-chained)
│   ├── risk_gates.py            ← circuit breakers (hard/soft block)
│   ├── arb/                     ← arbitrage utilities
│   ├── arb_scoring.py           ← arb opportunity scoring
│   ├── ops/                     ← ops/
│   │   └── run_manager.py       ← run lifecycle
│   ├── data/                    ← data access layer
│   ├── analysis/                ← embedded analysis tools
│   └── analysis_export.py       ← export helpers
│
├── engines/                     EXECUTION ENGINES (12 vivos)
│   ├── citadel.py               ← systematic momentum Ω fractal 5D ✅
│   ├── jump.py                  ← order flow microstructure ✅
│   ├── bridgewater.py           ← macro sentiment contrarian ⚠️ quarentena
│   ├── renaissance.py           ← harmonic Bayesian
│   ├── phi.py                   ← Fibonacci 0.618 confluence 🆕
│   ├── janestreet.py            ← cross-venue arb scanner
│   ├── millennium.py            ← multi-strategy orchestrator (meta)
│   ├── millennium_live.py       ← millennium live bootstrap
│   ├── twosigma.py              ← ML LightGBM meta (meta)
│   ├── aqr.py                   ← evolutionary allocation (meta)
│   ├── graham.py                ← endogenous momentum 🗄️ archived
│   ├── supertrend_futures.py    ← supertrend strategy
│   ├── live.py                  ← paper/demo/testnet/live execution
│   └── _archive/                ← deshaw, kepos, medallion, ornstein (deleted 2026-04-23)
│
├── analysis/                    ANALYTICS
│   ├── stats.py                 ← equity stats, ratios, conditional
│   ├── montecarlo.py            ← MC block-bootstrap
│   ├── walkforward.py           ← walk-forward global + por regime
│   ├── robustness.py            ← symbol robustness
│   ├── benchmark.py             ← BTC/SPY/XAU comparison, bear analysis
│   ├── diagnostics.py           ← execution realism, score calibration
│   ├── dsr.py                   ← Deflated Sharpe Ratio (anti-overfit)
│   └── plots.py                 ← matplotlib dashboard, MC, trade charts
│
├── api/                         REST server
│   ├── auth.py                  ← authentication
│   ├── routes.py                ← endpoints
│   ├── risk_check.py            ← pre-trade validation
│   └── models.py                ← Pydantic schemas
│
├── bot/
│   └── telegram.py              ← notificações + comandos
│
├── launcher.py                  DESKTOP LAUNCHER (~7.4k LOC após Fase 3)
├── launcher_support/            MÓDULOS DO LAUNCHER
│   ├── bootstrap.py             ← startup sequence
│   ├── engines_live_view.py     ← live engines viewer
│   ├── engines_sidebar.py       ← sidebar lateral
│   ├── execution.py             ← exec dispatcher
│   ├── menu_data.py             ← menu content
│   ├── cockpit_tab.py           ← cockpit tab
│   ├── cockpit_client.py        ← cockpit API client
│   ├── dashboard_controls.py    ← dashboard controls
│   ├── command_center.py        ← command center
│   ├── deploy_pipeline.py       ← deploy UI
│   ├── briefings.py             ← briefing display
│   ├── engine_logs_view.py      ← logs viewer
│   ├── runs_history.py          ← runs history
│   ├── shadow_poller.py         ← shadow trade poll
│   ├── signal_detail_popup.py   ← signal detail popup
│   ├── ssh_tunnel.py            ← SSH tunnel mgmt
│   ├── tunnel_registry.py       ← tunnel registry
│   ├── screens/                 ← screen modules (arbitrage_hub, dash_home, etc)
│   ├── research_desk/           ← 🆕 RESEARCH DESK cockpit (branch feat/research-desk)
│   │   ├── agent_view.py        ← detail modal 720x720
│   │   ├── agent_stats.py       ← SQLite stats + ratio
│   │   ├── activity_feed.py     ← issues + artifacts + branches
│   │   ├── live_runs.py         ← heartbeat streaming 3s
│   │   ├── paperclip_client.py  ← Paperclip API client (127.0.0.1:3100)
│   │   ├── cost_dashboard.py    ← sparklines + alerts
│   │   └── ... (25 módulos total)
│   ├── engines_live/            ← (deleted 2026-04-23 salvage)
│   ├── engines_live_helpers.py
│   └── audio.py
│
├── macro_brain/                 STANDALONE COCKPIT
│   ├── brain.py                 ← main thesis engine
│   ├── dashboard_view.py        ← TkInter cockpit
│   ├── bots/                    ← automated agents
│   ├── ml_engine/               ← LightGBM, classification
│   ├── thesis/                  ← thesis generation
│   └── position/                ← position management
│
├── aurum_cli.py                 CLI entry point (~1k LOC)
├── smoke_test.py                smoke suite (156-178/178)
├── build.py                     PyInstaller build
├── AURUM.spec                   PyInstaller spec
├── run_api.py                   API entry point
├── __main__.py                  python -m support
│
├── deploy/                      VPS DEPLOY
│   ├── install_shadow_vps.sh
│   └── millennium_shadow.service
│
├── server/website/              REACT + VITE landing/dashboard
│
├── tests/                       pytest suite (1666+ pass)
├── tools/                       UTILITIES
│   ├── reconcile_runs.py        ← reconciliar data/index.json
│   ├── oos_revalidate.py        ← orquestrador multi-janela + DSR
│   ├── lookahead_scan.py        ← scanner estático
│   ├── prewarm_sentiment_cache.py
│   ├── anti_overfit_grid.py
│   ├── maintenance/             ← verify_keys, backup_keys
│   ├── operations/              ← millennium_paper, etc
│   └── debug/                   ← 🆕 debug tools (uncommitted)
│
├── docs/                        DOCUMENTAÇÃO (PT-BR)
│   ├── sessions/                ← session logs
│   ├── days/                    ← daily logs
│   ├── audits/                  ← audits pontuais + veredictos
│   ├── engines/                 ← hypothesis.md, grid.md, checklist.md por engine
│   ├── methodology/             ← anti_overfit_protocol.md, TEMPLATE
│   ├── plans/                   ← planos mestres
│   ├── superpowers/             ← specs + plans skill-driven
│   ├── contracts/               ← sacred-logic-contract.md
│   ├── architecture/            ← screen_manager.md
│   ├── reviews/                 ← code reviews
│   ├── deploy/                  ← runbooks VPS
│   ├── testing/                 ← phase-c-characterization
│   ├── migrations/              ← migrations
│   └── macro/                   ← macro_brain docs
│
└── data/                        RUN OUTPUTS (gitignored)
    ├── <engine>/                ← runs por engine
    ├── anti_overfit/            ← pre-registered validation manifests
    ├── aurum.db                 ← SQLite (research_desk_stats, etc)
    └── index.json               ← canonical run index

🔒 = CORE protegido (ver MEMORY.md)
```

---

## 3. Pipeline canônico de sinais (CITADEL — replicado por outros)

```
Data (Binance OHLCV+tbb)
  → core.data.fetch_all()
  → core.indicators()            [EMA, RSI, ATR, BB, slope, vol_regime]
  → core.indicators.swing_structure()  [pivots, trend_struct, struct_strength]
  → core.indicators.omega()      [5D fractal: struct, flow, cascade, momentum, pullback]
  → core.htf.prepare_htf()       [multi-timeframe alignment]
  → core.portfolio.detect_macro() [BTC slope200 → BULL/BEAR/CHOP]
  → core.signals.decide_direction()    [regime + chop + vol + fractal filters]
  → core.signals.score_omega/chop()    [ensemble scoring]
  → core.signals.calc_levels()   [entry open[idx+1], swing-stop, RR-target]
  → core.portfolio.portfolio_allows()  [correlation + max positions]
  → core.portfolio.position_size()     [Kelly × convex × DD scale × omega risk]
  → core.portfolio.check_aggregate_notional()  [L6 cap Fase 3.1]
  → core.signals.label_trade()   [path-dependent: trailing, liquidation L7]
```

---

## 4. Parâmetros chave (config/params.py)

**Universo**: 11 altcoins USDT (BNB, INJ, LINK, RENDER, NEAR, SUI, ARB, SAND, XRP, FET, OP) + baskets alternativos (bluechip, majors, top12, defi, layer1, layer2, ai, meme, custom)

**Timeframe**: `INTERVAL` / `ENTRY_TF` global, `ENGINE_INTERVALS[<engine>]` override, `HTF_STACK` / `MTF_ENABLED` stack superior

**Conta & risco**: `ACCOUNT_SIZE`, `BASE_RISK`, `MAX_RISK`, `LEVERAGE`, `KELLY_FRAC`, `CONVEX_ALPHA`

**Custos C1+C2**: `SLIPPAGE`, `SPREAD`, `COMMISSION`, `FUNDING_PER_8H`

**Portfolio**: `MAX_OPEN_POSITIONS`, `CORR_THRESHOLD` (0.80), `CORR_SOFT_THRESHOLD` (0.75 → 40%), `CORR_LOOKBACK`

**Macro regime**: `MACRO_SYMBOL`, `MACRO_SLOPE_BULL/BEAR`, `RISK_SCALE_BY_REGIME`, `SCORE_BY_REGIME`, `ENGINE_RISK_SCALE_BY_REGIME`

**Omega**: `OMEGA_WEIGHTS` (5D), `SCORE_THRESHOLD`, `SCORE_BY_REGIME`

**Stops**: `STOP_ATR_M` (swing-based), `TARGET_RR`, `TRAIL_*` (multi-level)

**Drawdown**: `DD_RISK_SCALE`, `STREAK_COOLDOWN`, `SYM_LOSS_COOLDOWN`, `REGIME_TRANS_*`

**MC & WF**: `MC_N`, `MC_BLOCK`, `WF_TRAIN`, `WF_TEST`

**Engine-prefixed params:**
- `THOTH_*` → BRIDGEWATER (funding/OI/LS)
- `MERCURIO_*` → JUMP (order flow)
- `NEWTON_*` → DE SHAW (cointegration, archived)
- `DARWIN_*` → AQR (evolutionary)
- `CHRONOS_*` → WINTON time-series
- `ARB_*` → JANE STREET

---

## 5. Stack de execução

**Exchanges primárias**: Binance Futures USDT-M (main), Bybit, Hyperliquid, MEXC, Backpack (arb scanner)

**Python**: 3.11+ (migrado 2026-04-23 de 3.14). Venv local em `.venv/`, não mais OneDrive.

**GUI**: TkInter (launcher.py + research_desk + cockpits). Web via Vite+React (server/website).

**Persistência**: SQLite (`data/aurum.db`). Run artifacts em `data/<engine>/YYYY-MM-DD_HHMM/`.

**VPS**: Linux + systemd. 12 services active. Deploy via `deploy/install_shadow_vps.sh`. Cockpit API em `/etc/aurum/cockpit_api.env`. Paperclip API em `127.0.0.1:3100`.

**Notifications**: Telegram bot (`bot/telegram.py`).

---

## 6. Comandos essenciais

```bash
# Smoke + testes
python smoke_test.py --quiet                # 156-178/178
pytest -n 6                                 # paralelo opt-in (26s)
pytest                                      # sequential

# Maintenance
python tools/maintenance/verify_keys_intact.py
python tools/maintenance/backup_keys.py
python -m tools.reconcile_runs

# Backtest por engine
python -m engines.citadel --no-menu --days 180
python -m engines.jump --no-menu --days 90
python -m engines.bridgewater --no-menu --days 90 --basket default

# Live / Paper
python engines/live.py                      # paper/demo/testnet/live
python engines/janestreet.py --mode paper   # arb scanner

# Entry points
python launcher.py                          # desktop Bloomberg-terminal
python aurum_cli.py                         # terminal UI
python run_api.py                           # REST API

# Website
cd server/website && npm install && npm run dev  # localhost:3000
```

---

## 7. Estado atual da branch (2026-04-24)

- **Branch ativa**: `feat/research-desk`
- **Último commit**: `de7ef0f refactor(engines): polish live cockpit sidebar`
- **Uncommitted**: `launcher_support/engines_live_view.py`, `launcher_support/engines_sidebar.py`, `tests/test_engines_sidebar.py`
- **Untracked**: `docs/audits/engines/`, `tools/debug/`
- **launcher.py**: 7,406 LOC (foi 13k → 7.4k em 2026-04-23, −43%)
- **Suite**: 1666 pass / 8-13 flakes pre-existing / 8-9 skip

---

## 8. Filosofia de código

1. Cada função faz **uma coisa**.
2. Código em EN. Docs em PT-BR.
3. Imports: `core.*` + `config.params` — nunca entre engines.
4. `from config.params import *` no topo de engines (SST pattern).
5. Run dirs: `data/{engine}/{YYYY-MM-DD_HHMM}/` com `logs/`, `reports/`, `state/`.
6. UTF-8. Windows-first. OneDrive-safe via `core/fs.py`.
7. Comments só quando o **por quê** é não-óbvio. Nome de identificador já explica o quê.
8. Commits atômicos: subject + body descritivo. Nunca force-push em main.
