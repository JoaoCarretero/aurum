# ☿ AURUM Finance

Plataforma quantitativa de trading algorítmico para crypto futures.

## Arquitectura

```
aurum.finance/
├── config/                     CONFIGURAÇÃO
│   ├── params.py              ← parâmetros partilhados (single source of truth)
│   ├── engines.py             ← registry canonical de engines
│   ├── paths.py               ← path constants
│   ├── risk_gates.json        ← circuit breakers por modo (paper/demo/testnet/live)
│   ├── keys.json              ← API keys (NUNCA versionar)
│   └── keys.json.example      ← template
├── core/                       MÓDULOS REUTILIZÁVEIS
│   ├── data.py                ← fetch, fetch_all, validate
│   ├── indicators.py          ← EMA, RSI, ATR, Bollinger, swing structure, omega
│   ├── signals.py             ← direction, scoring, levels, trade labeling
│   ├── portfolio.py           ← macro detection, correlation, position sizing
│   ├── htf.py                 ← multi-timeframe preparation & merge
│   ├── harmonics.py           ← RENAISSANCE harmonic patterns (library)
│   ├── chronos.py             ← HMM regime, GARCH vol, Hurst
│   ├── risk_gates.py          ← Fase 4 circuit breakers (hard/soft block)
│   ├── audit_trail.py         ← Fase 4 immutable order log (hash-chained)
│   ├── key_store.py           ← Fase 4 encrypted key vault
│   └── fs.py                  ← atomic_write, robust_rmtree (OneDrive-safe)
├── analysis/                   ANALYTICS
│   ├── stats.py               ← equity stats, ratios, conditional backtest
│   ├── montecarlo.py          ← Monte Carlo block-bootstrap
│   ├── walkforward.py         ← walk-forward validation (global + por regime)
│   ├── robustness.py          ← symbol robustness
│   ├── benchmark.py           ← BTC/SPY/XAU comparison, bear market analysis
│   ├── diagnostics.py         ← execution realism, score calibration
│   └── plots.py               ← matplotlib dashboard, MC, trade charts
├── engines/                    EXECUTION ENGINES (10 no total)
│   ├── citadel.py             ← CITADEL systematic momentum (Ω fractal 5D)
│   ├── jump.py                ← JUMP order flow (CVD divergence, microstructure)
│   ├── bridgewater.py         ← BRIDGEWATER macro sentiment (funding/OI/LS)
│   ├── renaissance.py         ← RENAISSANCE harmonic patterns (entrypoint)
│   ├── deshaw.py              ← DE SHAW pair cointegration
│   ├── twosigma.py            ← TWO SIGMA ML meta-ensemble (LightGBM)
│   ├── aqr.py                 ← AQR evolutionary allocation
│   ├── janestreet.py          ← JANE STREET cross-venue arbitrage
│   ├── millennium.py          ← MILLENNIUM ensemble orchestrator
│   └── live.py                ← LIVE execution (paper/demo/testnet/live)
├── bot/
│   └── telegram.py            ← notificações + comandos Telegram
├── server/website/             ← React landing + dashboard (Vite)
├── macro_brain/                ← Macro brain cockpit (TkInter)
├── aurum_cli.py                ← terminal entry point
├── launcher.py                 ← desktop launcher / dashboard
├── run_api.py                  ← API entry point
├── __main__.py                 ← python -m support
└── data/                       ← output de runs (gitignored)
```

## Engines

| Engine | Entry Point | Descrição |
|---|---|---|
| **CITADEL** | `python engines/citadel.py` | Systematic momentum, Ω fractal 5D, ensemble Sortino × R-multiple × regime |
| **JUMP** | `python engines/jump.py` | Order flow microstructure: CVD divergence + volume imbalance |
| **BRIDGEWATER** | `python engines/bridgewater.py` | Macro sentiment contrarian: funding + OI + long/short ratio |
| **RENAISSANCE** | `python engines/renaissance.py` | Harmonic patterns (Gartley, Bat, Butterfly) + Bayesian scoring |
| **DE SHAW** | `python engines/deshaw.py` | Statistical arb: Engle-Granger cointegration pairs |
| **TWO SIGMA** | `python engines/twosigma.py` | ML meta-ensemble (LightGBM walk-forward) |
| **AQR** | `python engines/aqr.py` | Evolutionary fitness allocation |
| **JANE STREET** | `python engines/janestreet.py --mode paper` | Delta-neutral cross-venue funding/basis arbitrage |
| **MILLENNIUM** | `python engines/millennium.py` | Multi-strategy pod — orchestrates CITADEL + RENAISSANCE |
| **LIVE** | `python engines/live.py` | Paper/Demo/Testnet/Live via Binance USDT Futures WebSocket |

## Setup

### Requisitos

- Python 3.11+
- Node.js 18+ (para o website)

### Instalar dependências Python

```bash
pip install numpy pandas matplotlib requests websockets
```

### Configurar API Keys

```bash
cp config/keys.json.example config/keys.json
# Editar keys.json com as tuas keys
```

### Executar

```bash
python aurum_cli.py                     # terminal UI
python launcher.py                      # desktop launcher (Bloomberg-terminal)
python engines/citadel.py               # backtest CITADEL (momentum)
python engines/jump.py                  # backtest JUMP (order flow)
python engines/bridgewater.py           # backtest BRIDGEWATER (macro)
python engines/millennium.py            # multi-strategy ensemble
python engines/live.py                  # live/paper/demo/testnet
python engines/janestreet.py --mode paper   # funding arbitrage
```

### Website

```bash
cd server/website
npm install
npm run dev                  # http://localhost:3000
```

## Parâmetros

Todos os parâmetros de trading partilhados vivem em `config/params.py`.
Para alterar conta, risco, símbolos, timeframes — editar **um só ficheiro**.

## Segurança

- `config/keys.json` está no `.gitignore` — NUNCA versionar
- Rotar keys regularmente
- Começar sempre em PAPER ou DEMO antes de LIVE
