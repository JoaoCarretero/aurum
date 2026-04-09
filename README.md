# ☿ AURUM Finance

Plataforma quantitativa de trading algorítmico para crypto futures.

## Arquitectura

```
aurum.finance/
├── config/                     CONFIGURAÇÃO
│   ├── params.py              ← parâmetros partilhados (single source of truth)
│   ├── keys.json              ← API keys (NUNCA versionar)
│   └── keys.json.example      ← template
├── core/                       MÓDULOS REUTILIZÁVEIS
│   ├── data.py                ← fetch, fetch_all, validate
│   ├── indicators.py          ← EMA, RSI, ATR, Bollinger, swing structure, omega
│   ├── signals.py             ← direction, scoring, levels, trade labeling
│   ├── portfolio.py           ← macro detection, correlation, position sizing
│   └── htf.py                 ← multi-timeframe preparation & merge
├── analysis/                   ANALYTICS
│   ├── stats.py               ← equity stats, ratios, conditional backtest
│   ├── montecarlo.py          ← Monte Carlo block-bootstrap
│   ├── walkforward.py         ← walk-forward validation (global + por regime)
│   ├── robustness.py          ← symbol robustness
│   ├── benchmark.py           ← BTC/SPY/XAU comparison, bear market analysis
│   └── plots.py               ← matplotlib dashboard, MC, trade charts
├── engines/                    EXECUTION ENGINES
│   ├── backtest.py            ← AZOTH v3.6 scan + main loop
│   ├── live.py                ← WebSocket live/paper (Binance Futures)
│   ├── arbitrage.py           ← 13-venue funding rate arbitrage
│   └── multistrategy.py       ← AZOTH×HERMES ensemble
├── bot/
│   └── telegram.py            ← notificações + comandos Telegram
├── server/website/             ← React landing + dashboard (Vite)
├── run_backtest.py             ← entry point
├── run_live.py                 ← entry point
├── run_arb.py                  ← entry point
├── run_multi.py                ← entry point
├── backtest.py                 ← backward compatibility (re-imports)
└── data/                       ← output de runs (gitignored)
```

## Engines

| Engine | Entry Point | Descrição |
|---|---|---|
| **AZOTH v3.6** | `python run_backtest.py` | Ω fractal 5D, ensemble Sortino + R-multiple + regime-aware |
| **AZOTH×HERMES** | `python run_multi.py` | Multi-strategy: trend-following × harmónicos Fibonacci |
| **Live Engine** | `python run_live.py` | Paper/Demo/Testnet/Live — Binance USDT Futures via WebSocket |
| **Arbitrage** | `python run_arb.py` | Delta-neutral funding rate capture em 13 exchanges |

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
python run_backtest.py       # backtest AZOTH v3.6
python run_multi.py          # multistrategy AZOTH×HERMES
python run_live.py           # live engine (menu interactivo)
python run_arb.py            # arbitrage engine
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
