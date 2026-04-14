#!/usr/bin/env python3
"""
AURUM Finance — Terminal v4
Bloomberg Terminal aesthetic. Clean, functional, no bugs.
"""
import os, sys, subprocess, threading, queue, json, time, math
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import messagebox

from code_viewer import CodeViewer
from config.engines import ENGINE_NAMES, SCRIPT_TO_KEY
from core.health import runtime_health
from core.persistence import atomic_write_json
from core.transport import RequestSpec, TransportClient

# ═══════════════════════════════════════════════════════════
# BLOOMBERG PALETTE — amber on black, minimal color
# ═══════════════════════════════════════════════════════════
BG      = "#0a0a0a"
BG2     = "#101010"
BG3     = "#181818"
PANEL   = "#0c0c0c"
BORDER  = "#1e1e1e"
AMBER   = "#ff8c00"
AMBER_D = "#7a4400"
AMBER_B = "#ffaa33"
WHITE   = "#c8c8c8"
DIM     = "#4a4a4a"
DIM2    = "#2a2a2a"
GREEN   = "#00c040"
RED     = "#e03030"

FONT    = "Consolas"

LEGACY_ENGINE_ALIASES = {
    "backtest": "citadel",
    "citadel": "citadel",
    "thoth": "bridgewater",
    "bridgewater": "bridgewater",
    "mercurio": "jump",
    "jump": "jump",
    "newton": "deshaw",
    "deshaw": "deshaw",
    "de_shaw": "deshaw",
    "prometeu": "twosigma",
    "twosigma": "twosigma",
    "two_sigma": "twosigma",
    "darwin": "aqr",
    "aqr": "aqr",
    "multistrategy": "millennium",
    "millennium": "millennium",
    "harmonics": "renaissance",
    "harmonics_backtest": "renaissance",
    "renaissance": "renaissance",
    "arbitrage": "janestreet",
    "jane_street": "janestreet",
    "janestreet": "janestreet",
}

ENGINE_PREFIX_ALIASES = (
    "citadel_", "thoth_", "bridgewater_", "newton_", "deshaw_",
    "mercurio_", "jump_", "multistrategy_", "millennium_",
    "prometeu_", "twosigma_", "renaissance_", "harmonics_",
)

def canonical_engine_key(name) -> str:
    raw = str(name or "").strip().lower().replace(" ", "_")
    return LEGACY_ENGINE_ALIASES.get(raw, raw)

def engine_display_name(name) -> str:
    key = canonical_engine_key(name)
    return ENGINE_NAMES.get(key, key.replace("_", " ").upper())

# ─── BLOOMBERG 3D MENU — tile accents ────────────────────────
TILE_MARKETS  = "#ff8c00"   # AMBER    — quote + dash
TILE_EXECUTE  = "#00c864"   # GREEN    — strategies + arb + risk
TILE_RESEARCH = "#33aaff"   # CYAN     — terminal + data
TILE_CONTROL  = "#c864c8"   # MAGENTA  — connections + command + settings
TILE_DIM_FACTOR = 0.3       # idle brightness multiplier

# ═══════════════════════════════════════════════════════════
# VPS — remote control over SSH (passwordless key auth)
# ═══════════════════════════════════════════════════════════
VPS_HOST    = "root@37.60.254.151"
VPS_PROJECT = "~/aurum.finance"

# Windows: suppress the console window that pops up on every subprocess call,
# otherwise polling every 5s makes a CMD window flash open/closed constantly.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

def _vps_cmd(cmd: str, timeout: int = 10) -> str | None:
    """Run a command on the VPS over SSH, return stdout or None on failure.
    Intended to be called from a worker thread — subprocess.run blocks."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=5",
             "-o", "BatchMode=yes",
             VPS_HOST, cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=_NO_WINDOW,
        )
        if r.returncode == 0:
            return r.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

# ═══════════════════════════════════════════════════════════
# TICKER (live prices)
# ═══════════════════════════════════════════════════════════
_TD = {}
_TL = threading.Lock()
def _fetch():
    client = TransportClient()
    while True:
        try:
            r = client.request(RequestSpec(
                method="GET",
                url="https://fapi.binance.com/fapi/v1/ticker/24hr",
                timeout=8,
            ))
            if r.status_code == 200:
                d = {t["symbol"]: t for t in r.json()}
                with _TL:
                    for s in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]:
                        if s in d: _TD[s] = {"p": float(d[s]["lastPrice"]), "c": float(d[s]["priceChangePercent"])}
        except Exception:
            runtime_health.record("launcher.ticker_fetch_failure")
        time.sleep(12)

def _ticker_str():
    with _TL:
        if not _TD: return "connecting..."
        return "   ".join(f"{s.replace('USDT','')} {_TD[s]['p']:,.2f} {'+'if _TD[s]['c']>=0 else ''}{_TD[s]['c']:.1f}%" for s in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"] if s in _TD)

# ═══════════════════════════════════════════════════════════
# MENUS
# ═══════════════════════════════════════════════════════════
from core.connections import ConnectionManager, MARKETS
from core.alchemy_state import AlchemyState
from core import alchemy_ui
_conn = ConnectionManager()

MAIN_MENU = [
    ("MARKETS",        "markets",     "Seleccionar mercado activo"),
    ("CONNECTIONS",    "connections", "Contas & exchanges"),
    ("TERMINAL",       "terminal",    "Charts, macro, research"),
    ("DATA",           "data",        "Backtests · engine logs · reports"),
    ("STRATEGIES",     "strategies",  "Backtest & live engines"),
    ("ARBITRAGE",      "alchemy",     "CEX·CEX execution + DEX·DEX / CEX·DEX scanner"),
    ("RISK",           "risk",        "Portfolio & risk console"),
    ("COMMAND CENTER", "command",     "Site, servers, admin panel"),
    ("SETTINGS",       "settings",    "Config, keys, Telegram"),
]

# ─── MAIN_GROUPS: 9 destinos agrupados em 4 tiles (Bloomberg 3D) ────
# Format: (label, key_num, color, [(child_label, method_name), ...])
# MAIN_MENU (above) kept for legacy Fibonacci fallback + descriptions.
MAIN_GROUPS = [
    ("MARKETS",  "1", TILE_MARKETS, [
        ("QUOTE BOARD", "_markets"),
        ("CRYPTO DASH", "_crypto_dashboard"),
    ]),
    ("EXECUTE",  "2", TILE_EXECUTE, [
        ("STRATEGIES",  "_strategies"),
        ("ARBITRAGE",   "_arbitrage_hub"),
        ("MACRO BRAIN", "_macro_brain_menu"),
        ("RISK",        "_risk_menu"),
    ]),
    ("RESEARCH", "3", TILE_RESEARCH, [
        ("TERMINAL", "_terminal"),
        ("DATA",     "_data_center"),
    ]),
    ("CONTROL",  "4", TILE_CONTROL, [
        ("CONNECTIONS", "_connections"),
        ("COMMAND",     "_command_center"),
        ("SETTINGS",    "_config"),
    ]),
]

# Per-feature roadmap lines for the COMMAND CENTER coming-soon screens.
COMMAND_ROADMAPS = {
    "DEPLOY": [
        "Git push (origin/main, tags)",
        "Vercel / Netlify deploy hooks",
        "Docker build + registry push",
        "VPS rsync + systemctl restart",
    ],
    "SERVERS": [
        "VPS list (Hetzner / Vultr / Linode)",
        "Inline SSH terminal",
        "Status monitor (uptime, load, disk)",
        "Tail journalctl / nginx logs",
    ],
    "DATABASES": [
        "SQLite browser (read-only schema + query)",
        "PostgreSQL connect via DSN",
        "Backup / restore snapshots",
        "Migration runner",
    ],
    "SERVICES": [
        "systemd unit list + start/stop",
        "PM2 process tree",
        "Docker containers (ps / logs / restart)",
        "Cron / scheduled tasks viewer",
    ],
    "SYSTEM": [
        "CPU / RAM / disk via psutil",
        "Network interfaces & throughput",
        "Uptime + load average",
        "Top processes",
    ],
}

SUB_MENUS = {
    "backtest": [
        ("CITADEL",      "engines/citadel.py",      "Systematic momentum — trend-following + fractal alignment"),
        ("JUMP",         "engines/jump.py",       "Order flow — CVD divergence + volume imbalance"),
        ("BRIDGEWATER",  "engines/bridgewater.py",          "Macro sentiment — funding + OI + LS ratio contrarian"),
        ("DE SHAW",      "engines/deshaw.py",         "Statistical arb — pairs cointegration + mean reversion"),
        ("MILLENNIUM",   "engines/millennium.py",  "Multi-strategy pod — ensemble orchestrator"),
        ("TWO SIGMA",    "engines/twosigma.py",       "ML meta-ensemble — LightGBM walk-forward"),
        ("RENAISSANCE",  "engines/renaissance.py", "Harmonic patterns — Bayesian + entropy + Hurst"),
    ],
    "live": [
        ("PAPER",        "engines/live.py",           "Execução simulada — sem ordens reais"),
        ("DEMO",         "engines/live.py",           "Binance Futures Demo API"),
        ("TESTNET",      "engines/live.py",           "Binance Futures Testnet"),
        ("LIVE",         "engines/live.py",           "CAPITAL REAL — extremo cuidado"),
        ("JANE STREET",  "engines/janestreet.py",      "Cross-venue arb — funding/basis multi-exchange"),
    ],
    "tools": [
        ("AQR",          "engines/aqr.py",         "Adaptive allocation — evolutionary parameter optimization"),
        ("NEXUS API",    "run_api.py",               "REST API + WebSocket (porta 8000)"),
        ("WINTON",       "core/chronos.py",           "Time-series intelligence — HMM + GARCH + Hurst"),
    ],
}

BANNER = """\
 █████╗ ██╗   ██╗██████╗ ██╗   ██╗███╗   ███╗
██╔══██╗██║   ██║██╔══██╗██║   ██║████╗ ████║
███████║██║   ██║██████╔╝██║   ██║██╔████╔██║
██╔══██║██║   ██║██╔══██╗██║   ██║██║╚██╔╝██║
██║  ██║╚██████╔╝██║  ██║╚██████╔╝██║ ╚═╝ ██║
╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝\
"""

# ═══════════════════════════════════════════════════════════
# STRATEGY BRIEFINGS — philosophy + logic before execution
# ═══════════════════════════════════════════════════════════
BANNER_PREMIUM = """\
A U R U M
F I N A N C E
"""

SYSTEM_TAGLINE = "INSTITUTIONAL QUANT TERMINAL"

BRIEFINGS = {
    "CITADEL": {
        "philosophy": "Mercados são fractais — auto-similares em todas as escalas, como a geometria de Mandelbrot. O mesmo padrão que se forma no 15m ecoa no 4h e no diário. CITADEL lê esta invariância de escala, detectando estrutura de tendência em múltiplos timeframes e entrando apenas quando a confluência matemática converge. É a segunda lei da termodinâmica aplicada: momentum tende a persistir até que uma força contrária (regime change) dissipe a energia.",
        "logic": [
            "Detectar regime macro via slope EMA200 do BTC (BULL / BEAR / CHOP)",
            "Identificar fractais de swing structure em múltiplos timeframes",
            "Pontuar sinais com Omega 5D: struct + flow + cascade + momentum + pullback",
            "Dimensionar posições com Kelly fracional + escala de drawdown",
            "Modo CHOP: mean-reversion via Bollinger + RSI quando mercado lateral",
        ],
        "edge": "Trend-following com confirmação fractal. Lucrativo em mercados direcionais.",
        "risk": "Subperforma em chop prolongado. Max drawdown histórico ~5%.",
        "best_config": {
            "TF":         "15m",
            "Período":    "180 dias (90d quase sempre negativo)",
            "Basket":     "default",
            "Risk":       "regime-adaptive (BULL=0.30, CHOP=0.50) já default",
            "Sharpe val": "4.43 · 256 trades · ROI +31% · MC 99%",
            "Status":     "✓ EDGE CONFIRMADO em 180d",
        },
    },
    "JUMP": {
        "philosophy": "O preço é a última coisa a se mover — como a onda de choque que chega depois do raio. Antes do preço romper, o volume se desloca. Pressão de taker buy/sell, delta cumulativo e imbalances de order flow revelam a intenção antes da vela fechar. É o princípio de conservação de momento: o fluxo de ordens carrega informação sobre a força resultante antes que o preço a reflita. JUMP escuta o que o mercado sussurra.",
        "logic": [
            "Calcular Cumulative Volume Delta (CVD) — taker buy menos taker sell",
            "Detectar divergência CVD: preço faz novo high mas CVD não (distribuição)",
            "Medir imbalance de volume: ratio taker buy sobre janela rolling",
            "Identificar cascatas de liquidação via spikes de volume + ATR",
            "Score composto: 30% div CVD + 25% imbalance + 30% estrutura + 15% tendência",
        ],
        "edge": "Enxerga fluxo institucional antes do varejo. Funciona em todos os regimes.",
        "risk": "Sinais falsos em mercados de baixo volume. Requer pares líquidos.",
        "best_config": {
            "TF":         "15m (1h tem 1 trade só)",
            "Período":    "90 dias",
            "Basket":     "majors",
            "Sharpe val": "-4.22 · 17 trades",
            "Status":     "✗ SEM EDGE — research lab até ML meta-layer",
        },
    },
    "BRIDGEWATER": {
        "philosophy": "Quando todos estão gananciosos, tenha medo. Quando todos têm medo, seja ganancioso. BRIDGEWATER quantifica o sentimento da multidão — funding rates, variações de open interest e ratios long/short — para encontrar extremos contrários onde a maioria está errada. É a teoria dos jogos em ação: quando o posicionamento fica unilateral demais, o sistema se torna instável e reverte — como um pêndulo no ponto máximo de deslocamento, a energia potencial se converte em cinética na direção oposta.",
        "logic": [
            "Z-score de funding rate em 30 períodos de 8h — funding extremo = reversão",
            "Delta Open Interest vs preço — OI subindo + preço caindo = venda forçada",
            "Ratio Long/Short contrário — ratio > 2.0 = muitos comprados, fade neles",
            "Composto: 40% funding + 30% OI + 30% LS ratio",
            "Direção dos extremos de sentimento, confirmada por estrutura de preço",
        ],
        "edge": "Captura reversões em extremos de sentimento. Win rate alto.",
        "risk": "Sentimento pode ficar extremo mais tempo que o esperado. Risco de timing.",
        "best_config": {
            "TF":         "1h (15m=Sharpe -1.95, 4h=poucos trades) já default",
            "Período":    "90 dias (180 também ok)",
            "Basket":     "bluechip (default também ok)",
            "Sharpe val": "10.57 (bluechip 90d) · 7.34 (bluechip 180d)",
            "OOS WF":     "IS 4.97 / OOS 1.78 — 99 trades",
            "Status":     "✓ EDGE CONFIRMADO — winner do battery",
        },
    },
    "DE SHAW": {
        "philosophy": "Dois ativos conectados que divergem devem convergir — como a lei da gravitação universal. Cointegração não é correlação — é um vínculo matemático, um atrator estável. Quando o spread entre dois pares cointegrados estica além do normal, a 'gravidade estatística' o puxa de volta à média. É a reversão à média de Ornstein-Uhlenbeck: o spread se comporta como uma mola — quanto mais se afasta do equilíbrio, maior a força restauradora. DE SHAW opera esta gravidade.",
        "logic": [
            "Teste de cointegração Engle-Granger em todos os pares de símbolos",
            "Calcular z-score do spread com estimativa rolling OLS de half-life",
            "Entrada quando |z-score| > 2.0 — spread a 2 desvios padrão da média",
            "Saída quando z-score cruza 0 — reversão à média completa",
            "Stop quando |z-score| > 3.5 — cointegração pode ter quebrado",
        ],
        "edge": "Market-neutral. Lucra independente da direção do mercado.",
        "risk": "Cointegração pode quebrar permanentemente. Requer seleção cuidadosa de pares.",
        "best_config": {
            "TF":         "4h (1h e 15m geram ruído cointegração)",
            "Período":    "90 dias",
            "Basket":     "default",
            "Z-entry":    "2.0 · Z-stop 3.5",
            "Sharpe val": "1.27 · 92 trades · MC 63%",
            "Status":     "⚠ MARGINAL — universo altcoin atual sem pares cointegrados estáveis",
        },
    },
    "MILLENNIUM": {
        "philosophy": "Nenhuma estratégia única sobrevive a todas as condições de mercado — assim como nenhuma partícula isolada explica toda a matéria. Mas um portfolio de estratégias não-correlacionadas, cada uma forte em regimes diferentes, cria um edge que persiste. É o princípio da superposição: sinais independentes combinados reduzem o ruído por √N enquanto preservam o sinal. MILLENNIUM orquestra — combinando sinais, gerenciando correlação, alocando capital onde a matemática aponta.",
        "logic": [
            "Roda todos os engines simultaneamente nos mesmos dados",
            "Agrega sinais no nível de trade — não no nível de previsão",
            "Pesa por Sortino ratio rolling por engine por regime",
            "Kill-switch: pausa qualquer engine com Sortino(20) < -0.5",
            "Gestão de drawdown no nível do portfolio em todas as posições",
        ],
        "edge": "Curva de equity mais suave. Diversificado entre estratégias.",
        "risk": "Se todas as estratégias correlacionam num crash, a diversificação falha.",
    },
    "TWO SIGMA": {
        "philosophy": "Uma máquina pode aprender qual estratégia dominará a próxima fase do mercado? TWO SIGMA usa os trades de todos os engines como dados de treino, aprendendo padrões de quando cada estratégia performa melhor — e alocando antes que o regime mude. É aprendizado por reforço aplicado a meta-alocação: o modelo observa features do mercado (volatilidade, regime HMM, Hurst exponent) e prevê o melhor executor para as próximas N operações.",
        "logic": [
            "Coletar histórico de trades de todos os engines como features",
            "Construir target: qual engine tem melhor R-múltiplo nas próximas N trades",
            "Treinar modelo gradient-boosted em regime de mercado + features de performance",
            "Prever alocação ótima por engine para condições atuais",
            "Rebalancear pesos do portfolio baseado nas previsões ML",
        ],
        "edge": "Adapta alocação proativamente, não reativamente.",
        "risk": "Overfitting de ML. Requer dados de treino diversos para generalizar.",
    },
}

BRIEFINGS["RENAISSANCE"] = {
    "philosophy": "Os mesmos padrões geométricos que governam a Natureza — proporções de Fibonacci, simetrias de Gartley, borboletas de Pesavento — repetem-se nos mercados. Não por misticismo, mas porque refletem a psicologia fractal de multidões: medo e ganância criam pontos de retração previsíveis. RENAISSANCE detecta estes padrões harmónicos com confirmação Bayesiana e mede a qualidade estatística via entropia de Shannon e expoente de Hurst. Padrões com alta simetria e baixa entropia têm maior probabilidade de completar.",
    "logic": [
        "Detectar swing pivots via threshold de ATR (zigzag adaptativo)",
        "Classificar padrões harmónicos: Gartley, Butterfly, Bat, Crab, Cypher",
        "Validar proporções de Fibonacci nos legs (XA, AB, BC, CD)",
        "Pontuar qualidade: simetria geométrica + entropia + Hurst exponent",
        "Entry na zona D (completion zone) com stop além do ponto X",
    ],
    "edge": "Reversões de alta precisão em pontos de completação harmónica. WR 85%+.",
    "risk": "Poucos sinais por período. Depende de volatilidade para gerar padrões.",
    "best_config": {
        "TF":         "15m (1h/4h reduzem trade count drasticamente)",
        "Período":    "180 dias (90d gera só ~13)",
        "Basket":     "default",
        "Sharpe val": "6.58 · 68 trades · WR 88% · MaxDD 0.4%",
        "Audit":      "⚠ WR reportado 85% vs auditado 61% — verificar antes do live",
        "Status":     "✓ EDGE CONFIRMADO (com flag de audit)",
    },
}

BRIEFINGS["PAPER"] = BRIEFINGS["DEMO"] = BRIEFINGS["TESTNET"] = BRIEFINGS["LIVE"] = {
    "philosophy": "O mercado é um sistema vivo — um processo estocástico com memória, não um gerador aleatório. Trading ao vivo é o teste final — onde algoritmos encontram a realidade da microestrutura. Cada tick é um voto, cada trade uma tese. Paper deixa observar sem risco. Demo valida execução. Live é onde convicção encontra capital.",
    "logic": [
        "Conectar à Binance Futures API (paper/demo/testnet/live)",
        "Semear dados históricos para todos os símbolos — construir estado dos indicadores",
        "Rodar ciclo de scan a cada vela de 15m — mesma lógica do backtest",
        "Executar ordens via REST API com requests assinadas HMAC",
        "Monitorar posições: trailing stops, funding, kill-switch",
    ],
    "edge": "Mesmo edge do backtest, validado na microestrutura do mercado ao vivo.",
    "risk": "Slippage, latência de API, downtime da exchange. Comece com paper/demo.",
}

BRIEFINGS["JANE STREET"] = {
    "philosophy": "Num mercado eficiente, o mesmo ativo deveria custar o mesmo em todo lugar — é a lei do preço único. Mas mercados não são eficientes — funding rates divergem, preços atrasam entre exchanges, e liquidez se fragmenta. É termodinâmica: calor flui do quente para o frio até o equilíbrio. JANE STREET captura estas ineficiências antes que o equilíbrio se restabeleça: delta-neutral, matemático, arbitragem pura.",
    "logic": [
        "Escanear 10+ venues simultâneamente: Binance, Bybit, OKX, Gate, Bitget + mais",
        "Detectar 4 tipos: arb de funding rate, basis spot-perp, spread cross-venue, interno",
        "Pontuar com Omega v2: edge × probabilidade de fill × desconto adversarial",
        "Executar ordens split (5 partes) com profiling de latência por venue",
        "Monitor de hedge garante delta-neutral o tempo todo",
    ],
    "edge": "Market-neutral. Lucra com ineficiência entre exchanges, não com direção.",
    "risk": "Risco de execução, atrasos de saque entre venues, mudanças de funding rate.",
}

BRIEFINGS["AQR"] = {
    "philosophy": "Seleção natural aplicada a estratégias de trading — evolução darwiniana literal. Cada engine é um organismo competindo por capital. Os mais aptos sobrevivem, os fracos são podados. Com o tempo, o portfolio evolui — adaptando-se ao mercado conforme ele muda. É a dinâmica de Lotka-Volterra: populações (estratégias) competem por recursos (capital) num ecossistema (mercado) que muda.",
    "logic": [
        "Avaliar fitness por engine: Sortino (40%) + Profit Factor (20%) + Win Rate (20%) + Estabilidade (20%)",
        "Rankear engines e alocar capital: top performer 35%, acima da mediana 25%, abaixo 10%",
        "Kill zone: 3 janelas negativas consecutivas → engine pausado em 5% mínimo",
        "Mutação: a cada 100 trades, perturbar parâmetros ±10% e testar melhoria",
        "Crossover: combinar DNA de dois engines de alta performance no mesmo regime",
    ],
    "edge": "Adapta alocação do portfolio automaticamente baseado em performance real.",
    "risk": "Requer histórico de trades suficiente. Pode sobre-alocar em sequências de sorte.",
}

BRIEFINGS["NEXUS API"] = {
    "philosophy": "Controle é liberdade. NEXUS abre a plataforma AURUM para o mundo — REST API, streaming WebSocket, autenticação JWT. Seu celular, seu dashboard, suas integrações. O terminal se expande além do terminal.",
    "logic": [
        "Servidor FastAPI na porta 8000 com docs Swagger em /docs",
        "Autenticação JWT com hashing bcrypt de senhas",
        "Endpoints: auth, conta, trading, analytics, WebSocket ao vivo",
        "Banco SQLite para usuários, trades, depósitos, estado dos engines",
        "Streaming em tempo real de status dos engines e eventos de trade",
    ],
    "edge": "Controle remoto. Acesso mobile. Integrações de terceiros.",
    "risk": "Expor apenas em localhost ou atrás de VPN. Nunca na internet pública sem auth.",
}

BRIEFINGS["WINTON"] = {
    "philosophy": "Indicadores tradicionais olham o que aconteceu. WINTON olha a estrutura invisível do tempo — regimes ocultos, clusters de volatilidade, decaimento de momentum, dimensões fractais. São os padrões que existem sob as velas — a mecânica quântica do mercado: estados superpostos (bull/bear/chop) com probabilidades contínuas que colapsam em regime quando observados.",
    "logic": [
        "Hidden Markov Model: P(bull), P(bear), P(chop) como probabilidades contínuas",
        "GARCH(1,1): prever volatilidade para as próximas 4-8 velas proativamente",
        "Decaimento de momentum: taxa de decaimento exponencial — detectar tendências enfraquecendo",
        "Expoente de Hurst: H>0.5 trending, H<0.5 mean-reverting, H≈0.5 random walk",
        "Sazonalidade: hora × dia-da-semana edge scoring de padrões históricos",
    ],
    "edge": "Enxerga transições de regime antes de completarem. Sizing proativo.",
    "risk": "Dependências ML (hmmlearn, arch). Fallback gracioso se não instaladas.",
}


# ═══════════════════════════════════════════════════════════
# BRIEFINGS_V2 — technical view (populated Fase 3.3, 2026-04-11)
# ═══════════════════════════════════════════════════════════
# Structured strategy briefing schema. Coexists with legacy BRIEFINGS;
# _brief prefers V2 when a matching name exists, falls back to the
# narrative dict otherwise. Every entry follows the same shape:
#
#   source_files: list of paths, first is the main file
#   main_function: (file, function_name) — auto-scroll target for CodeViewer
#   one_liner: one-sentence technical summary
#   pseudocode: multi-line Python-like block of the decision flow
#   params: list of dicts {name, default, range, unit, effect}
#   formulas: list of Unicode math strings
#   invariants: list of pre-conditions / assumptions
BRIEFINGS_V2: dict[str, dict] = {
    "CITADEL": {
        "source_files": [
            "engines/citadel.py",
            "core/signals.py",
            "core/portfolio.py",
            "core/htf.py",
        ],
        "main_function": ("engines/citadel.py", "scan_symbol"),
        "one_liner": "Omega 5D fractal trend-follower with MTF alignment "
                     "and convex Kelly sizing.",
        "pseudocode": """\
for idx in range(min_idx, len(df) - MAX_HOLD - 2):
    if in_cooldown(idx): continue
    if not portfolio_allows(symbol, active_syms, corr): continue

    direction, reason, fractal_score = decide_direction(row, macro)
    if direction is None and reason == "chop":
        direction, chop_score = score_chop(row)  # mean-reversion fallback

    score, comps = score_omega(row, direction)  # 5D ensemble
    if score < SCORE_THRESHOLD[macro]: continue

    entry, stop, target, rr = calc_levels(df, idx, direction)
    result, dur, exit_p = label_trade(df, idx+1, direction,
                                      entry, stop, target)

    size = position_size(account, entry, stop, score,
                         macro, direction, vol_r, dd_scale,
                         peak_equity=peak_equity)
    if not check_aggregate_notional(size*entry, open_pos, account, LEVERAGE):
        continue   # [L6]
    commit_trade(...)""",
        "params": [
            {"name": "SCORE_THRESHOLD", "default": 0.53, "range": "0.45-0.65",
             "unit": "—", "effect": "min omega score to fire"},
            {"name": "KELLY_FRAC",      "default": 0.5,  "range": "0.25-1.0",
             "unit": "—", "effect": "fractional Kelly multiplier on base risk"},
            {"name": "TARGET_RR",       "default": 3.0,  "range": "1.5-3.5",
             "unit": "R",  "effect": "target distance as multiple of stop"},
            {"name": "STOP_ATR_M",      "default": 2.5,  "range": "1.2-2.5",
             "unit": "ATR","effect": "stop distance floor in ATR units"},
            {"name": "MAX_HOLD",        "default": 200,  "range": "100-400",
             "unit": "bars","effect": "max bars a position can stay open"},
            {"name": "MAX_OPEN_POSITIONS","default": 3,  "range": "2-5",
             "unit": "—", "effect": "concurrency cap across symbols"},
        ],
        "formulas": [
            "Ω = 0.30·struct + 0.20·flow + 0.20·cascade + 0.15·momentum + 0.15·pullback",
            "risk = BASE_RISK + t · (min(kelly, MAX_RISK) - BASE_RISK)",
            "kelly = max(0, (WR·RR - (1-WR)) / RR) · KELLY_FRAC",
            "size = account · risk / |entry - stop|",
            "liq_price = entry · (1 ∓ 1/LEVERAGE ± 0.005)",
        ],
        "invariants": [
            "L1 no look-ahead: features read from [idx] only",
            "L2 entry fills at open[idx+1] (label_trade)",
            "L3/L4 fees + slippage applied on both legs",
            "L6 aggregate notional cap enforced post-sizing",
            "L7 liquidation check inside label_trade (path-dependent)",
            "stop is always strictly below entry for long, above for short",
        ],
    },
    "JUMP": {
        "source_files": ["engines/jump.py", "core/indicators.py"],
        "main_function": ("engines/jump.py", "scan_mercurio"),
        "one_liner": "Order-flow microstructure: CVD divergence + volume "
                     "imbalance + liquidation cascades.",
        "pseudocode": """\
for idx in range(min_idx, len(df) - MAX_HOLD - 2):
    cvd_div = cvd_div_bull[idx] or cvd_div_bear[idx]
    vimb    = volume_imbalance[idx]
    liq     = liquidation_proxy[idx]

    if not (cvd_div or vimb > IMBALANCE_THRESH or liq): continue

    direction = resolve_direction_from_flow(row)
    score = 0.30·cvd_div + 0.25·vimb + 0.30·struct + 0.15·trend
    if score < MERCURIO_MIN_SCORE: continue

    entry, stop, target, rr = calc_levels(df, idx, direction)
    result, dur, exit_p = label_trade(df, idx+1, direction, entry, stop, target)
    size = position_size(...) · MERCURIO_SIZE_MULT
    if not check_aggregate_notional(...): continue   # [L6]
    commit_trade(...)""",
        "params": [
            {"name": "MERCURIO_MIN_SCORE","default": 0.45,"range": "0.35-0.60",
             "unit": "—", "effect": "min composite score to fire"},
            {"name": "MERCURIO_SIZE_MULT","default": 1.0, "range": "0.5-1.5",
             "unit": "—", "effect": "risk multiplier vs base Kelly"},
            {"name": "MERCURIO_CVD_WINDOW","default": 50,"range": "20-100",
             "unit": "bars","effect": "rolling window for CVD divergence"},
            {"name": "MERCURIO_LIQ_VOL_MULT","default": 3.0,"range": "2-5",
             "unit": "—","effect": "volume spike multiplier for liquidation proxy"},
        ],
        "formulas": [
            "CVD[i] = Σ(taker_buy - taker_sell)[0..i]",
            "vimb  = taker_buy_ratio[i] rolling-window normalized",
            "liq_proxy = (vol/vol_ma > k) ∧ (range/atr > k)",
            "score = 0.30·cvd_div + 0.25·vimb + 0.30·struct + 0.15·trend",
        ],
        "invariants": [
            "CVD, vimb, liq_proxy all computed from [0..idx] only (causal)",
            "label_trade + L6 + L7 inherited from core",
            "L5 funding uses dynamic _funding_periods_per_8h (fixed Backlog #3)",
            "requires liquid pairs — taker volume per bar > SPEED_MIN",
        ],
    },
    "BRIDGEWATER": {
        "source_files": ["engines/bridgewater.py", "core/sentiment.py"],
        "main_function": ("engines/bridgewater.py", "scan_thoth"),
        "one_liner": "Sentiment contrarian: funding z-score + OI delta + "
                     "long/short ratio extremes.",
        "pseudocode": """\
sentiment_features = fetch_sentiment(symbol)  # funding_z, oi_delta, ls_ratio
df = merge(df, sentiment_features, on='time', how='left')

for idx in range(min_idx, len(df) - MAX_HOLD - 2):
    f_z    = funding_z[idx]
    oi_sig = oi_delta_signal[idx]
    ls_sig = ls_ratio_signal[idx]

    if abs(f_z) < 1.0 and abs(oi_sig) < 0.3 and abs(ls_sig) < 0.3:
        continue   # sentiment not extreme enough

    direction = "BEARISH" if crowded_long else "BULLISH"  # contrarian
    score = 0.40·|f_z|/2 + 0.30·|oi_sig| + 0.30·|ls_sig|
    if score < THOTH_MIN_SCORE: continue
    commit_trade(...)""",
        "params": [
            {"name": "THOTH_MIN_SCORE", "default": 0.50,"range": "0.40-0.65",
             "unit": "—", "effect": "min sentiment-composite score"},
            {"name": "THOTH_SIZE_MULT", "default": 0.8, "range": "0.5-1.2",
             "unit": "—", "effect": "risk multiplier (sentiment is sparser)"},
            {"name": "FUNDING_Z_ABS_MIN","default": 1.0,"range": "0.8-1.5",
             "unit": "σ", "effect": "min |funding z-score| to consider extreme"},
        ],
        "formulas": [
            "funding_z = (funding - μ_30d) / σ_30d",
            "oi_delta_signal = (OI[i] - OI[i-k]) / OI[i-k]",
            "ls_ratio_signal = (ls_ratio[i] - 1.0) normalized by regime",
            "contrarian: direction = opposite(crowded_side)",
        ],
        "invariants": [
            "sentiment merged via merge_asof(backward) — no future info",
            "direction is always opposite the crowded side by construction",
            "same L2-L7 guarantees via shared-core calc_levels + label_trade",
            "signals are sparse — can produce 0 trades on short horizons",
        ],
    },
    "DE SHAW": {
        "source_files": ["engines/deshaw.py"],
        "main_function": ("engines/deshaw.py", "scan_pair"),
        "one_liner": "Statistical arbitrage: cointegration-driven pair trading "
                     "with z-score mean reversion.",
        "pseudocode": """\
merged = calc_spread_zscore(df_a, df_b, beta, alpha)   # Engle-Granger
for idx in range(min_idx, len(merged) - 2):
    z = zscore[idx]

    if in_trade:
        if low[idx] <= liq_price(entry, dir): exit("LIQ")   # [Backlog #4]
        elif z crosses mean in favorable direction: exit("WIN")
        elif z hits stop threshold: exit("LOSS")
        elif hold > MAX_HOLD: exit("time")
        continue

    if abs(z) < NEWTON_ZSCORE_ENTRY: continue
    direction = "BEARISH" if z > 0 else "BULLISH"    # short/long spread
    entry = a_open[idx+1] · (1 ± slip)               # [Backlog #1]
    size  = position_size(account, entry, stop, score)
    if not check_aggregate_notional(size*entry, [], account, LEVERAGE):
        continue
    open_trade(...)""",
        "params": [
            {"name": "NEWTON_ZSCORE_ENTRY","default": 2.0,"range": "1.5-3.0",
             "unit": "σ","effect": "|z| threshold to open a spread trade"},
            {"name": "NEWTON_ZSCORE_EXIT", "default": 0.0,"range": "-0.5-0.5",
             "unit": "σ","effect": "|z| level at which winners are closed"},
            {"name": "NEWTON_ZSCORE_STOP", "default": 3.5,"range": "3.0-5.0",
             "unit": "σ","effect": "|z| level that triggers stop-out"},
            {"name": "NEWTON_COINT_PVALUE","default": 0.05,"range": "0.01-0.1",
             "unit": "p","effect": "pair filter: max ADF test p-value"},
            {"name": "NEWTON_SPREAD_WINDOW","default": 200,"range":"100-400",
             "unit": "bars","effect": "rolling window for spread z-score"},
            {"name": "NEWTON_MAX_HOLD",   "default": 150,"range": "80-300",
             "unit": "bars","effect": "max hold bars before time exit"},
        ],
        "formulas": [
            "spread = a_close - β · b_close - α",
            "z = (spread - μ_window) / σ_window",
            "pair selection: Engle-Granger cointegration, p < NEWTON_COINT_PVALUE",
            "half_life ≈ -ln(2) / ln(ρ_AR1)",
        ],
        "invariants": [
            "pair cointegration verified offline before scan loop",
            "one open spread per pair at a time (in_trade bool)",
            "entry at open[idx+1] + slippage (Backlog #1 fix)",
            "liquidation guard inside exit loop (Backlog #4 fix)",
            "L6 single-position cap enforced via check_aggregate_notional",
        ],
    },
    "MILLENNIUM": {
        "source_files": [
            "engines/millennium.py",
            "engines/citadel.py",
            "core/harmonics.py",
        ],
        "main_function": ("engines/millennium.py", "scan_multistrategy"),
        "one_liner": "Regime-weighted ensemble of CITADEL (trend) + RENAISSANCE "
                     "(harmonics), with rolling confidence-scaled weights.",
        "pseudocode": """\
citadel_trades     = scan_symbol(df, sym)          # trend
renaissance_trades = scan_hermes(df, sym)          # harmonic patterns

for trade in merge_by_timestamp(citadel, renaissance):
    regime = regime_of(trade.timestamp - REGIME_LAG·trade_interval)

    w_citadel     = base_weights[regime] · citadel_sortino_boost
    w_renaissance = base_weights[regime] · renaissance_sortino_boost
    # kill switch: rolling sortino below -0.5 → peso fixo em ENSEMBLE_MIN_W

    trade.size *= (w_citadel if trade.engine=="CITADEL" else w_renaissance)
    commit(trade)""",
        "params": [
            {"name": "CITADEL_CAPITAL_WEIGHT","default": 0.65,"range":"0.4-0.8",
             "unit": "—","effect": "base capital allocation to CITADEL"},
            {"name": "RENAISSANCE_CAPITAL_WEIGHT","default": 0.35,"range":"0.2-0.6",
             "unit": "—","effect": "base allocation to RENAISSANCE"},
            {"name": "ENSEMBLE_WINDOW", "default": 30, "range": "15-60",
             "unit": "trades","effect": "rolling window for weight recompute"},
            {"name": "KILL_SWITCH_SORTINO","default": -0.5,"range":"-1.0--0.2",
             "unit": "σ","effect": "sortino floor that pauses a sub-engine"},
            {"name": "REGIME_LAG",      "default": 5,  "range": "3-10",
             "unit": "trades","effect": "lag on regime input to break feedback"},
            {"name": "CONFIDENCE_N_MIN","default": 50, "range": "30-100",
             "unit": "trades","effect": "sample size for full-confidence score"},
        ],
        "formulas": [
            "w_i = base_w[regime] · max(ENSEMBLE_MIN_W, sortino_boost_i)",
            "confidence = min(1, sqrt(n_recent / CONFIDENCE_N_MIN))",
            "final_weight = confidence · w_i + (1-confidence) · base_w_i",
            "kill switch: sortino < -0.5 → weight = ENSEMBLE_MIN_W",
        ],
        "invariants": [
            "sub-engines run independently; no cross-signal coupling",
            "regime lag of REGIME_LAG trades breaks weight→trade feedback",
            "no sub-engine can be fully silenced (floor at ENSEMBLE_MIN_W)",
            "all per-strategy invariants (L1-L11) inherited from CITADEL + harmonics",
        ],
    },
    "TWO SIGMA": {
        "source_files": ["engines/twosigma.py"],
        "main_function": ("engines/twosigma.py", "trades_to_features"),
        "one_liner": "LightGBM meta-ensemble: predicts which engine to weight "
                     "higher given current market context at trade open.",
        "pseudocode": """\
# Training (offline, walk-forward per split)
trades_df = trades_to_features(all_prior_trades)      # AT-OPEN columns only
split     = int(len(trades_df) * train_ratio)
train     = trades_df.iloc[:split]
test      = trades_df.iloc[split:]
train["target"] = build_target(train)     # best engine next 10 trades
test["target"]  = build_target(test)      # same, test segment only
X_train = train[FEATURE_COLS]             # whitelist enforced
model   = lgb.train(params, X_train, train["target"])

# Inference (online)
features = trade_context_at_open(trade)
probs    = model.predict([features])
weights  = softmax_normalize(probs) → per-engine weight""",
        "params": [
            {"name": "retrain_every","default":500,"range":"200-2000",
             "unit": "trades","effect":"trades before model retrains"},
            {"name": "train_ratio", "default":0.7,"range":"0.5-0.8",
             "unit": "—","effect":"walk-forward split for train vs test"},
            {"name": "lookahead",   "default":10,"range":"5-30",
             "unit": "trades","effect":"target = best engine in next N trades"},
            {"name": "num_leaves",  "default":31,"range":"15-63",
             "unit": "—","effect":"LightGBM leaf count per tree"},
            {"name": "learning_rate","default":0.05,"range":"0.01-0.1",
             "unit": "—","effect":"LightGBM learning rate"},
        ],
        "formulas": [
            "target[i] = argmax_engine(mean_pnl of trades [i+1..i+N])",
            "FEATURE_COLS ⊂ AT_OPEN (strict whitelist, asserted at import)",
            "X = train[FEATURE_COLS].values  (17 features, no leakage)",
            "predict: argmax softmax(model.predict(features))",
        ],
        "invariants": [
            "no AT-EXIT field ever lands in FEATURE_COLS (module-level assert)",
            "train/test split computes targets SEPARATELY per segment (no cross-boundary leak, Backlog #2)",
            "runtime guard in .train() re-checks feature whitelist before lgb.train",
            "fallback to static equal-weight when model absent or data < 50 trades",
        ],
    },
    "JANE STREET": {
        "source_files": ["engines/janestreet.py"],
        "main_function": ("engines/janestreet.py", "ExecutionSimulator"),
        "one_liner": "Cross-venue funding + basis arbitrage across 13 CEX "
                     "venues with latency-aware fill simulation.",
        "pseudocode": """\
venues = fetch_all_venues()   # 13 CEXs in parallel
pairs  = find_mispriced_pairs(venues.funding, venues.basis)

for (venue_a, venue_b, symbol) in pairs:
    edge = |funding_a - funding_b|  # or basis diff
    if edge < MIN_EDGE_BPS: continue

    book_a = fetch_orderbook(venue_a, symbol)
    book_b = fetch_orderbook(venue_b, symbol)
    fill   = ExecutionSimulator.simulate_arb_pair(book_a, book_b, notional)
    if not fill.feasible: continue

    net_edge = edge - fill.total_slippage_bps - 2·ARB_LATENCY_BPS - 2·fee_bps
    if net_edge > MIN_NET_EDGE_BPS:
        execute_both_legs(venue_a, venue_b, notional, side_a, side_b)""",
        "params": [
            {"name": "ARB_LATENCY_BPS", "default":2.0,"range":"1-5",
             "unit": "bps","effect":"pessimistic latency markup per leg (Backlog #5)"},
            {"name": "MIN_EDGE_BPS",    "default":5,  "range":"3-10",
             "unit": "bps","effect":"minimum gross edge to consider a pair"},
            {"name": "MIN_NET_EDGE_BPS","default":2,  "range":"1-5",
             "unit": "bps","effect":"minimum net edge after costs"},
            {"name": "NOTIONAL_USD",    "default":1000,"range":"500-5000",
             "unit": "USD","effect":"size per arb pair attempt"},
            {"name": "MAX_UNFILLED_PCT","default":0.05,"range":"0.02-0.10",
             "unit": "—","effect":"max unfilled fraction before pair is skipped"},
        ],
        "formulas": [
            "gross_edge = |funding_a - funding_b| × 10_000",
            "slippage = book_walk(notional) + ARB_LATENCY_BPS per leg",
            "avg_price(BUY)  = avg_book × (1 + latency/10_000)",
            "avg_price(SELL) = avg_book × (1 - latency/10_000)",
            "feasible = unfilled < 5% on both legs",
        ],
        "invariants": [
            "funding signs respected (long pays when funding > 0)",
            "both legs must confirm before PnL accrues",
            "latency markup is pessimistic — conservative edge estimates",
            "venue latency tracked via LatencyProfiler for post-hoc analysis",
        ],
    },
}


BASKETS_UI = [
    ("DEFAULT",  "", ["BNB","INJ","LINK","RENDER","NEAR","SUI","ARB","SAND","XRP","FET","OP"]),
    ("TOP 12",   "2", ["BTC","ETH","BNB","SOL","XRP","DOGE","ADA","AVAX","LINK","DOT","MATIC","SUI"]),
    ("DEFI",     "3", ["LINK","AAVE","UNI","MKR","SNX","COMP","CRV","SUSHI","INJ","JUP"]),
    ("LAYER 1",  "4", ["BTC","ETH","SOL","AVAX","NEAR","SUI","APT","ATOM","DOT","ALGO"]),
    ("LAYER 2",  "5", ["ARB","OP","MATIC","STRK","MANTA","IMX"]),
    ("AI",       "6", ["FET","RENDER","TAO","NEAR","WLD","ARKM"]),
    ("MEME",     "7", ["DOGE","SHIB","PEPE","BONK","FLOKI","WIF"]),
    ("MAJORS",   "8", ["BTC","ETH","BNB","SOL","XRP"]),
    ("BLUECHIP", "9", ["BTC","ETH","BNB","SOL","XRP","ADA","AVAX","LINK","DOT","MATIC",
                        "ATOM","NEAR","INJ","ARB","OP","SUI","RENDER","FET","SAND","AAVE"]),
]

PERIODS_UI = [
    ("30 DIAS",   "~1 mês — validação rápida",        "30"),
    ("90 DIAS",   "~3 meses — backtest padrão",        "90"),
    ("180 DIAS",  "~6 meses — médio prazo",            "180"),
    ("365 DIAS",  "~1 ano — ciclo completo",           "365"),
]


# ═══════════════════════════════════════════════════════════
# BACKTEST LIST COLUMNS — single source of truth
# ═══════════════════════════════════════════════════════════
# (label, widget width in chars). Used by both the crypto-futures
# dashboard Backtest tab and the standalone DATA > BACKTESTS screen,
# plus the row renderer in _dash_backtest_render. Keeping the widths
# here instead of duplicating them in three places is what stopped
# the header and the rows from drifting out of alignment. Monospace
# char widths only match at the same font size AND weight, so header
# and rows both render at (FONT, 8, *).
_BT_COLS: list[tuple[str, int]] = [
    ("DATE / TIME",  19),
    ("STRATEGY",     14),
    ("TF",            5),
    ("DAYS",          5),
    ("BASKET",       10),
    ("RUN",          14),
    ("TRADES",        8),
    ("WIN%",          8),
    ("PNL",          12),
    ("SHARPE",        8),
    ("DD",            8),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AURUM Terminal")
        self.configure(bg=BG)
        self.geometry("960x660")
        self.minsize(860, 560)

        # Taskbar icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("aurum.finance.terminal")
        except: pass
        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists(): self.iconbitmap(str(ico))
        except: pass

        self.proc = None
        self.oq = queue.Queue()
        self.history = []  # nav history for back
        self._exec_progress_after_id = None
        self._exec_visual_mode = None
        self._exec_progress_value = 0.0
        self._exec_progress_target = 0.0
        self._exec_progress_pulse = 0
        self._exec_recent_lines = []
        self._exec_stage_label = None
        self._exec_file_label = None
        self._exec_pct_label = None
        self._exec_bar_canvas = None
        self._exec_recent_labels = []
        self._exec_live_tail_label = None
        self._exec_progress_last_paint = 0.0
        self._exec_last_feed_at = 0.0
        self._exec_managed_info = None

        # ─── Bloomberg 3D main menu state ────────────────
        self._start_t = time.monotonic()
        self._menu_live = {
            "markets":  {},
            "execute":  {},
            "research": {},
            "control":  {},
        }
        self._menu_focused_tile = 0      # 0..3 index into MAIN_GROUPS
        self._menu_expanded_tile = None  # None or 0..3 when drilled in
        self._menu_sub_focus = 0         # 0..2 within expanded sub-menu
        self._menu_canvas = None         # tk.Canvas handle, set on render
        self._menu_live_after_id = None  # after() handle for 5s refresh
        self._active_tile_slots = self._TILE_SLOTS         # overridden by splash
        self._active_cd_center = (self._CD_CX, self._CD_CY)  # overridden by splash

        # ─── Splash HL1 gate state ────────────────────────
        self._splash_cursor_on = True
        self._splash_pulse_after_id = None
        self._splash_canvas = None

        threading.Thread(target=_fetch, daemon=True).start()
        self._chrome()
        self._splash()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._quit)

    # ─── CHROME ──────────────────────────────────────────
    def _chrome(self):
        # Ticker
        tb = tk.Frame(self, bg=BG2, height=18); tb.pack(fill="x"); tb.pack_propagate(False)
        tbc = tk.Frame(tb, bg=BG2); tbc.pack(fill="both", expand=True, padx=10)
        self.t_lbl = tk.Label(tbc, text="", font=(FONT, 7), fg=DIM, bg=BG2); self.t_lbl.pack(side="left")
        self.t_clk = tk.Label(tbc, text="", font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG2); self.t_clk.pack(side="right")

        tk.Frame(self, bg=AMBER, height=1).pack(fill="x")

        # Header
        hd = tk.Frame(self, bg=BG, height=26); hd.pack(fill="x"); hd.pack_propagate(False)
        hc = tk.Frame(hd, bg=BG); hc.pack(fill="both", expand=True, padx=10)
        tk.Label(hc, text="AURUM", font=(FONT, 8, "bold"), fg=AMBER, bg=BG).pack(side="left")
        self.h_path = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG); self.h_path.pack(side="left", padx=(8,0))
        self.h_stat = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG); self.h_stat.pack(side="right")
        # Persistent badge that lights up while the COMMAND CENTER dev server is alive.
        self.h_site = tk.Label(hc, text="", font=(FONT, 8, "bold"), fg=GREEN, bg=BG)
        self.h_site.pack(side="right", padx=(0, 12))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        self.main = tk.Frame(self, bg=BG); self.main.pack(fill="both", expand=True)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Footer
        ft = tk.Frame(self, bg=BG2, height=20); ft.pack(fill="x"); ft.pack_propagate(False)
        fc = tk.Frame(ft, bg=BG2); fc.pack(fill="both", expand=True, padx=10)
        self.f_lbl = tk.Label(fc, text="", font=(FONT, 7), fg=DIM, bg=BG2); self.f_lbl.pack(side="right")
        tk.Label(fc, text="v2.0", font=(FONT, 7), fg=DIM2, bg=BG2).pack(side="left")

    def _clr(self):
        aid = getattr(self, "_exec_progress_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._exec_progress_after_id = None
        self._exec_visual_mode = None
        self._exec_visual = None
        self._exec_console = None
        self._exec_stage_label = None
        self._exec_file_label = None
        self._exec_pct_label = None
        self._exec_bar_canvas = None
        self._exec_recent_labels = []
        self._exec_live_tail_label = None
        self._exec_progress_last_paint = 0.0
        self._exec_last_feed_at = 0.0
        self._exec_managed_info = None
        # Crypto dashboard owns a recurring after() timer — kill it on any screen change
        aid = getattr(self, "_dash_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._dash_after_id = None
        self._dash_alive = False
        # Site console poll loop self-terminates when this flag flips false.
        # The SiteRunner subprocess itself keeps running independently.
        self._site_screen_alive = False
        # Funding scanner screen uses a self-rearming after() tick. Flip the
        # alive flag off and clear the armed flag so re-entry starts a fresh
        # chain instead of stacking.
        self._funding_alive = False
        self._funding_timer_armed = False
        for w in self.main.winfo_children(): w.destroy()

    def _clear_kb(self):
        """Clear our custom global keybindings before a screen switch.
        Renamed from `_unbind` because that name collides with tkinter's
        internal Misc._unbind method — overriding it breaks unbind_all()
        and other builtin binding APIs."""
        for k in ["<Return>","<space>","<Escape>","<BackSpace>",
                   *[f"<Key-{i}>" for i in range(10)],
                   *[f"<F{i}>" for i in range(1, 13)]]:
            try: self.unbind(k)
            except: pass
        try: self.main.unbind("<Button-1>")
        except: pass
        self._in_engine = False

    def _kb(self, key, callback):
        """Safe key bind — skips if an Entry widget has focus."""
        def wrapper(event):
            focused = self.focus_get()
            if focused and isinstance(focused, tk.Entry):
                return  # let Entry handle the keystroke
            callback()
        self.bind(key, wrapper)

    def _tick(self):
        self.t_clk.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.t_lbl.configure(text=_ticker_str(), fg=AMBER_D)
        # COMMAND CENTER site indicator (visible from any screen while server is alive)
        sr = getattr(self, "_site_runner_inst", None)
        if sr and sr.is_running():
            try:
                port = int(sr.config.get("port", 3000) or 3000)
            except (TypeError, ValueError):
                port = 3000
            self.h_site.configure(text=f"● SITE :{port}", fg=GREEN)
        else:
            self.h_site.configure(text="")
        self.after(3000, self._tick)

    # ─── Bloomberg 3D menu — live data fetchers ──────────
    # Each fetcher returns {"line1","line2","line3","line4"} of strings.
    # Any failure → "—". Never raises. Called from a worker thread.

    @staticmethod
    def _fallback_lines() -> dict:
        return {"line1": "—", "line2": "—", "line3": "—", "line4": "—"}

    def _fetch_tile_markets(self) -> dict:
        try:
            from config.params import UNIVERSE
            lines = {"line1": "—", "line2": "—", "line3": "—", "line4": "—"}
            try:
                from core.data import fetch_spot_price
                btc = fetch_spot_price("BTCUSDT")
                lines["line1"] = f"BTC {btc/1000:.1f}k" if btc else "BTC —"
            except Exception:
                lines["line1"] = "BTC —"
            try:
                from core.data import fetch_spot_price
                eth = fetch_spot_price("ETHUSDT")
                lines["line2"] = f"ETH {eth/1000:.2f}k" if eth else "ETH —"
            except Exception:
                lines["line2"] = "ETH —"
            lines["line3"] = f"{len(UNIVERSE)} pairs"
            try:
                from core.portfolio import detect_macro
                lines["line4"] = f"MACRO {detect_macro()}"
            except Exception:
                lines["line4"] = "MACRO —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_execute(self) -> dict:
        try:
            lines = self._fallback_lines()
            try:
                from core import proc
                n = len(proc.list_active()) if hasattr(proc, "list_active") else 0
                lines["line1"] = f"procs {n}"
            except Exception:
                lines["line1"] = "procs 0"
            try:
                ps = json.loads((ROOT / "config" / "paper_state.json").read_text(encoding="utf-8"))
                pnl = float(ps.get("day_pnl", 0.0))
                sign = "+" if pnl >= 0 else ""
                lines["line2"] = f"pnl {sign}{pnl:.1f}%"
                pos = ps.get("open_positions", [])
                lines["line3"] = f"{len(pos)} pos" if isinstance(pos, list) else "0 pos"
            except Exception:
                lines["line2"] = "pnl —"
                lines["line3"] = "0 pos"
            try:
                rg = json.loads((ROOT / "config" / "risk_gates.json").read_text(encoding="utf-8"))
                active = sum(1 for v in rg.values() if isinstance(v, dict) and v.get("active"))
                lines["line4"] = f"risk {active}/5"
            except Exception:
                lines["line4"] = "risk —/5"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_research(self) -> dict:
        try:
            lines = self._fallback_lines()
            idx_path = ROOT / "data" / "index.json"
            if idx_path.exists():
                try:
                    runs = json.loads(idx_path.read_text(encoding="utf-8"))
                    if isinstance(runs, list) and runs:
                        last = runs[-1] if isinstance(runs[-1], dict) else {}
                        eng = str(last.get("engine", "—"))[:4].upper()
                        sharpe = last.get("sharpe") or last.get("metrics", {}).get("sharpe")
                        lines["line1"] = f"last {eng}"
                        lines["line2"] = f"sharpe {float(sharpe):.1f}" if sharpe else "sharpe —"
                        lines["line3"] = f"{len(runs)} runs"
                    else:
                        lines["line1"] = "no runs"
                        lines["line3"] = "0 runs"
                except Exception:
                    lines["line1"] = "last —"
                    lines["line3"] = "— runs"
            else:
                lines["line1"] = "no runs"
                lines["line3"] = "0 runs"
            try:
                from core import chronos
                active = bool(getattr(chronos, "hmm_enabled", lambda: False)())
                lines["line4"] = "HMM active" if active else "HMM idle"
            except Exception:
                lines["line4"] = "HMM —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_control(self) -> dict:
        try:
            lines = self._fallback_lines()
            try:
                conn = json.loads((ROOT / "config" / "connections.json").read_text(encoding="utf-8"))
                if isinstance(conn, dict):
                    items = conn.get("connections") or list(conn.values())
                elif isinstance(conn, list):
                    items = conn
                else:
                    items = []
                total = len(items)
                up = sum(1 for c in items
                         if isinstance(c, dict) and c.get("status", "").lower() in {"up", "ok", "connected"})
                lines["line1"] = f"conn {up}/{total}" if total else "conn —"
            except Exception:
                lines["line1"] = "conn —"
            try:
                elapsed = time.monotonic() - self._start_t
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                lines["line2"] = f"up {h}h{m:02d}m"
            except Exception:
                lines["line2"] = "up —"
            try:
                from bot import telegram as tg_mod
                ok = bool(getattr(tg_mod, "is_online", lambda: False)())
                lines["line3"] = "tg ONLINE" if ok else "tg OFFLINE"
            except Exception:
                lines["line3"] = "tg —"
            lines["line4"] = "vps —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _menu_live_fetch_sync(self) -> None:
        """Populate self._menu_live in-thread. Used by tests and by the async worker."""
        self._menu_live["markets"]  = self._fetch_tile_markets()
        self._menu_live["execute"]  = self._fetch_tile_execute()
        self._menu_live["research"] = self._fetch_tile_research()
        self._menu_live["control"]  = self._fetch_tile_control()

    def _menu_live_fetch_async(self) -> None:
        """Spawn a worker thread that refreshes the cache, then schedules a repaint."""
        def _worker():
            try:
                self._menu_live_fetch_sync()
            except Exception:
                pass
            try:
                self.after(0, self._menu_live_apply)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _menu_live_apply(self) -> None:
        """Main-thread: redraw tile texts from self._menu_live if the main menu is shown."""
        if self._menu_canvas is None:
            return
        try:
            self._menu_tiles_repaint_text()
        except Exception:
            pass

    # ─── Bloomberg 3D menu — canvas renderers ────────────
    # All drawing happens on one full-frame canvas. Tiles are isometric
    # boxes built from lines/polygons; the CD at the center uses ovals/arcs.

    _TILE_SLOTS = [
        ("nw", 180, 150),
        ("ne", 640, 150),
        ("sw", 180, 380),
        ("se", 640, 380),
    ]
    # Splash screen uses the same 2x2 grid but shifted DOWN ~100px so the
    # BANNER wordmark has room at the top of the canvas.
    _SPLASH_TILE_SLOTS = [
        ("nw", 180, 250),
        ("ne", 640, 250),
        ("sw", 180, 480),
        ("se", 640, 480),
    ]
    _TILE_W = 200
    _TILE_H = 120
    _TILE_DEPTH = 16

    _CD_CX = 460
    _CD_CY = 265
    _CD_R  = 68
    # CD center on the splash canvas — sits between the shifted 2x2 grid.
    _SPLASH_CD = (460, 365)

    def _dim_color(self, hex_color: str, factor: float) -> str:
        """Scale an #rrggbb color by factor (0..1)."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = max(0, min(255, int(r * factor)))
            g = max(0, min(255, int(g * factor)))
            b = max(0, min(255, int(b * factor)))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    def _tile_rect(self, idx: int) -> tuple:
        slots = getattr(self, "_active_tile_slots", None) or self._TILE_SLOTS
        _, cx, cy = slots[idx]
        w, h = self._TILE_W, self._TILE_H
        return (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)

    def _draw_cd_center(self, canvas, r=None) -> None:
        center = getattr(self, "_active_cd_center", None) or (self._CD_CX, self._CD_CY)
        cx, cy = center
        if r is None:
            r = self._CD_R
        canvas.delete("cd")
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=AMBER, width=2, tags="cd")
        canvas.create_oval(cx - r + 10, cy - r + 10, cx + r - 10, cy + r - 10,
                           outline=AMBER_D, width=1, tags="cd")
        canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10,
                           outline=AMBER, width=1, fill=BG, tags="cd")
        angle = int((time.monotonic() * 40) % 360)
        canvas.create_arc(cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4,
                          start=angle, extent=30, outline=AMBER_B, width=2,
                          style="arc", tags="cd")
        canvas.create_text(cx, cy - 4, text="AURUM", font=(FONT, 8, "bold"),
                           fill=AMBER, tags="cd")
        canvas.create_text(cx, cy + 6, text="LASER", font=(FONT, 7),
                           fill=DIM, tags="cd")
        canvas.create_text(cx, cy + r + 10, text="φ = 1.618",
                           font=(FONT, 7), fill=DIM2, tags="cd")

    def _draw_warning_stripe(self, canvas, y: int, height: int, text: str) -> None:
        """Solid yellow bar with dark text — HL1 hazard stripe."""
        w = 920
        canvas.create_rectangle(0, y, w, y + height, fill="#ffd700",
                                outline="#ffd700", tags="warning")
        canvas.create_text(w // 2, y + height // 2,
                           text=text, font=(FONT, 7, "bold"),
                           fill="#1a1a00", tags="warning")

    def _draw_stamp(self, canvas, cx: int, cy: int, w: int, h: int, lines: list) -> None:
        """Dashed rectangular stamp with N centered text lines — HL1 clearance tags."""
        x1, y1 = cx - w // 2, cy - h // 2
        x2, y2 = cx + w // 2, cy + h // 2
        canvas.create_rectangle(x1, y1, x2, y2,
                                outline=AMBER, width=1,
                                dash=(2, 3), tags="stamp")
        n = len(lines)
        if n == 0:
            return
        line_h = h // (n + 1)
        for i, line in enumerate(lines):
            canvas.create_text(cx, y1 + line_h * (i + 1),
                               text=line, font=(FONT, 8, "bold"),
                               fill=AMBER, tags="stamp")

    def _draw_status_block(self, canvas, x: int, y: int, rows: list) -> None:
        """CRT-style status rows: '> LABEL .......... VALUE' with per-row color.

        rows is a list of (label, value, color_hex) tuples. Dots fill the
        gap between label and value to a fixed column width so the values
        align vertically.
        """
        total_width = 48
        line_step = 18
        for i, (label, value, color) in enumerate(rows):
            prefix = f"> {label} "
            value_str = f" {value}"
            dots = "." * max(2, total_width - len(prefix) - len(value_str))
            text = f"{prefix}{dots}{value_str}"
            canvas.create_text(x, y + i * line_step, anchor="w",
                               text=text, font=(FONT, 9),
                               fill=color, tags="status")

    def _draw_panel(self, canvas, x1: int, y1: int, x2: int, y2: int,
                    title: str = "", accent: str = AMBER, tag: str = "panel") -> None:
        canvas.create_rectangle(x1, y1, x2, y2, outline=BORDER, fill=PANEL, width=1, tags=tag)
        canvas.create_line(x1, y1, x2, y1, fill=accent, width=2, tags=tag)
        canvas.create_line(x1, y2, x2, y2, fill=DIM2, width=1, tags=tag)
        if title:
            canvas.create_rectangle(x1 + 14, y1 - 10, x1 + 168, y1 + 12,
                                    outline=accent, fill=BG, width=1, tags=tag)
            canvas.create_text(x1 + 22, y1 + 1, anchor="w",
                               text=title, font=(FONT, 8, "bold"),
                               fill=accent, tags=tag)

    def _draw_kv_rows(self, canvas, x: int, y: int, rows: list[tuple[str, str, str]],
                      value_x: int = 290, line_h: int = 18, tag: str = "kv") -> None:
        for i, (label, value, color) in enumerate(rows):
            yy = y + i * line_h
            canvas.create_text(x, yy, anchor="w", text=label, font=(FONT, 8),
                               fill=DIM, tags=tag)
            canvas.create_text(value_x, yy, anchor="w", text=value, font=(FONT, 8, "bold"),
                               fill=color, tags=tag)

    def _ui_page_shell(self, title: str, subtitle: str = "",
                       pad_x: int = 28, pad_y: int = 18,
                       content_width: int | None = None) -> tuple[tk.Frame, tk.Frame]:
        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True, padx=pad_x, pady=pad_y)

        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        tk.Label(head, text=title, font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        if subtitle:
            tk.Label(head, text=subtitle, font=(FONT, 8),
                     fg=DIM, bg=BG, anchor="w").pack(anchor="w", pady=(3, 0))
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 12))

        body = tk.Frame(outer, bg=BG)
        if content_width is not None:
            body.pack(fill="both", expand=True)
            canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
            sb = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
            inner = tk.Frame(canvas, bg=BG, width=content_width)
            inner.bind("<Configure>", lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=inner, anchor="nw",
                                 width=content_width)
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            def _on_wheel(event):
                canvas.yview_scroll(-1 * (event.delta // 120), "units")
            def _enter_canvas(event):
                canvas.bind_all("<MouseWheel>", _on_wheel)
            def _leave_canvas(event):
                try: canvas.unbind_all("<MouseWheel>")
                except Exception: pass
            canvas.bind("<Enter>", _enter_canvas)
            canvas.bind("<Leave>", _leave_canvas)
            canvas.bind("<Destroy>", _leave_canvas)
            return outer, inner

        body.pack(fill="both", expand=True)
        return outer, body

    def _ui_panel_frame(self, parent, title: str = "", subtitle: str = "") -> tk.Frame:
        panel = tk.Frame(parent, bg=BG)
        panel.pack(fill="x", pady=(0, 12))

        if title or subtitle:
            hdr = tk.Frame(panel, bg=BG)
            hdr.pack(fill="x", pady=(2, 8))
            if title:
                tk.Label(hdr, text=title, font=(FONT, 8, "bold"),
                         fg=AMBER_D, bg=BG, anchor="w").pack(anchor="w")
            if subtitle:
                tk.Label(hdr, text=subtitle, font=(FONT, 8),
                         fg=DIM, bg=BG, anchor="w").pack(anchor="w", pady=(2, 0))
            tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))

        return panel

    def _ui_section(self, parent, title: str, note: str | None = None,
                    badge: str | None = None) -> tk.Frame:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", pady=(0, 10))

        head = tk.Frame(wrap, bg=BG)
        head.pack(fill="x", pady=(0, 4))
        tk.Label(head, text=title, font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG, anchor="w").pack(side="left")
        if badge:
            tk.Label(head, text=f" {badge} ", font=(FONT, 7, "bold"),
                     fg=BG, bg=AMBER_D, padx=3).pack(side="left", padx=8)
        if note:
            tk.Label(head, text=note, font=(FONT, 7),
                     fg=DIM, bg=BG, anchor="e").pack(side="right")
        tk.Frame(wrap, bg=DIM2, height=1).pack(fill="x", pady=(0, 6))
        return wrap

    def _ui_action_row(self, parent, key_label: str, title: str, desc: str,
                       command=None, available: bool = True,
                       tag: str | None = None, tag_fg: str | None = None,
                       tag_bg: str | None = None, title_width: int = 20,
                       key_bg: str | None = None) -> tuple[tk.Frame, tk.Label, tk.Label]:
        row = tk.Frame(parent, bg=BG, cursor="hand2" if command else "arrow")
        row.pack(fill="x", pady=1)

        key = tk.Label(row, text=f" {key_label} ", font=(FONT, 8, "bold"),
                       fg=BG if available else WHITE,
                       bg=key_bg or (AMBER if available else DIM2),
                       width=3)
        key.pack(side="left")

        title_l = tk.Label(row, text=f"  {title}", font=(FONT, 9, "bold"),
                           fg=WHITE if available else DIM, bg=BG3,
                           anchor="w", padx=6, pady=4, width=title_width)
        title_l.pack(side="left")

        desc_l = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3,
                          anchor="w", padx=6, pady=4)
        desc_l.pack(side="left", fill="x", expand=True)

        if tag:
            tk.Label(row, text=f" {tag} ", font=(FONT, 7, "bold" if available else "normal"),
                     fg=tag_fg or (BG if available else DIM),
                     bg=tag_bg or (GREEN if available else BG2),
                     padx=4).pack(side="right", padx=4)

        if command:
            def _enter(_e=None):
                title_l.configure(fg=AMBER if available else DIM)
            def _leave(_e=None):
                title_l.configure(fg=WHITE if available else DIM)
                row.configure(bg=BG)
            for w in (row, key, title_l, desc_l):
                w.bind("<Button-1>", lambda e, c=command: c())
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

        return row, title_l, desc_l

    def _ui_kv_grid(self, parent, rows: list[tuple[str, str, str]]) -> None:
        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill="x", pady=(0, 8))
        for label, value, color in rows:
            row = tk.Frame(grid, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, font=(FONT, 8), fg=DIM, bg=BG,
                     width=16, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=(FONT, 8, "bold"), fg=color, bg=BG,
                     anchor="w").pack(side="left")

    def _ui_note(self, parent, text: str, fg: str = DIM) -> None:
        tk.Label(parent, text=text, font=(FONT, 8),
                 fg=fg, bg=BG, anchor="w", justify="left").pack(fill="x", pady=(0, 6))

    def _ui_back_row(self, parent, command, label: str = "RETURN") -> None:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", pady=(2, 0))
        self._ui_action_row(
            wrap,
            "0",
            label,
            "Return to previous routing screen",
            command=command,
            available=False,
            tag=None,
            title_width=20,
            key_bg=DIM2,
        )

    def _draw_spokes(self, canvas, focused_idx: int) -> None:
        canvas.delete("spokes")
        slots = getattr(self, "_active_tile_slots", None) or self._TILE_SLOTS
        center = getattr(self, "_active_cd_center", None) or (self._CD_CX, self._CD_CY)
        cd_cx, cd_cy = center
        for idx in range(4):
            x1, y1, x2, y2 = self._tile_rect(idx)
            _, cx, cy = slots[idx]
            anchor_x = x2 if cx < cd_cx else x1
            anchor_y = y2 if cy < cd_cy else y1
            _, _, color, _ = MAIN_GROUPS[idx]
            line_color = color if idx == focused_idx else DIM2
            width = 2 if idx == focused_idx else 1
            canvas.create_line(
                anchor_x, anchor_y, cd_cx, cd_cy,
                fill=line_color, width=width, dash=(2, 4), tags="spokes",
            )

    def _menu_tiles_repaint_text(self) -> None:
        if self._menu_canvas is None:
            return
        for idx in range(4):
            self._draw_isometric_tile(self._menu_canvas, idx, idx == self._menu_focused_tile)

    def _menu_tile_focus(self, idx: int) -> None:
        if not (0 <= idx <= 3):
            return
        prev = self._menu_focused_tile
        self._menu_focused_tile = idx
        if self._menu_canvas is None:
            return
        self._draw_isometric_tile(self._menu_canvas, prev, False)
        self._draw_isometric_tile(self._menu_canvas, idx, True)
        self._draw_spokes(self._menu_canvas, idx)

    def _menu_tile_focus_delta(self, delta: int) -> None:
        self._menu_tile_focus((self._menu_focused_tile + delta) % 4)

    def _menu_sub_focus_delta(self, delta: int) -> None:
        if self._menu_expanded_tile is None:
            return
        children = MAIN_GROUPS[self._menu_expanded_tile][3]
        self._menu_sub_focus = (self._menu_sub_focus + delta) % len(children)
        self._menu_sub_render(self._menu_expanded_tile)

    def _menu_sub_select(self, tile_idx: int, sub_idx: int) -> None:
        if not (0 <= tile_idx <= 3):
            return
        children = MAIN_GROUPS[tile_idx][3]
        if not (0 <= sub_idx < len(children)):
            return
        _, method_name = children[sub_idx]
        fn = getattr(self, method_name, None)
        if callable(fn):
            self._menu_expanded_tile = None
            self._menu_canvas = None
            fn()

    def _menu_tile_collapse(self) -> None:
        self._menu_expanded_tile = None
        self._menu_sub_focus = 0
        self._menu_main_bloomberg()

    def _menu_live_schedule(self) -> None:
        """Re-arm the 5s live-data refresh while the Bloomberg menu is active."""
        if self._menu_canvas is None:
            self._menu_live_after_id = None
            return
        self._menu_live_fetch_async()
        try:
            self._menu_live_after_id = self.after(5000, self._menu_live_schedule)
        except Exception:
            self._menu_live_after_id = None

    # ─── SPLASH (Layer 0) — HL1 Black Mesa gate ──────────
    def _splash_on_click(self) -> None:
        """Click / ENTER / space handler — cancel pulse and route to main menu."""
        if self._splash_pulse_after_id is not None:
            try:
                self.after_cancel(self._splash_pulse_after_id)
            except Exception:
                pass
            self._splash_pulse_after_id = None
        self._splash_canvas = None
        self._menu("main")

    def _cd_draw(self):
        """Animate the CD radar on the splash screen."""
        if not getattr(self, "_cd_alive", False):
            return
        cv = self._cd_canvas
        sz = self._cd_size
        self._cd_t += 0.015
        t = self._cd_t
        cx, cy = sz / 2, sz / 2
        R = sz * 0.44

        cv.delete("all")

        # Grid rings
        for pct in (0.2, 0.4, 0.6, 0.8, 1.0):
            r = R * pct
            alpha = "#2a1800" if pct < 1.0 else "#3d2200"
            cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=alpha, width=1)

        # Crosshairs
        for angle_deg in (0, 45, 90, 135):
            a = math.radians(angle_deg)
            cv.create_line(cx + math.cos(a) * R, cy + math.sin(a) * R,
                           cx - math.cos(a) * R, cy - math.sin(a) * R,
                           fill="#1a1000", width=1)

        # Data spiral — binary encoded
        N = 400
        for i in range(N):
            ang = (i / N) * math.pi * 12 + t * 0.3
            r = 6 + (i / N) * R
            x = cx + math.cos(ang) * r
            y = cy + math.sin(ang) * r
            signal = math.sin(i * 0.73 + t * 12) > 0.2
            if signal:
                # Brighter toward edge
                c = "#4d2800" if i < N * 0.5 else "#663800"
                cv.create_rectangle(x, y, x + 1, y + 1, fill=c, outline="")

        # Sweep line
        sweep = t * 1.2
        sx = cx + math.cos(sweep) * R
        sy = cy + math.sin(sweep) * R
        cv.create_line(cx, cy, sx, sy, fill="#3d2200", width=1)

        # Read head
        rr = ((t * 10) % R) + 6
        lx = cx + math.cos(sweep) * rr
        ly = cy + math.sin(sweep) * rr
        cv.create_oval(lx - 1.5, ly - 1.5, lx + 1.5, ly + 1.5,
                       fill=AMBER, outline="")

        # Center dot
        cv.create_oval(cx - 2, cy - 2, cx + 2, cy + 2,
                       fill=AMBER_D, outline="")

        # Label
        cv.create_text(cx, cy + R + 12, text="Ω  SIGNAL  TOPOLOGY",
                       font=(FONT, 7), fill=DIM2, anchor="center")

        self.after(33, self._cd_draw)  # ~30 fps

    def _splash(self):
        """Premium institutional landing screen."""
        self._clr()
        self._clear_kb()
        self.history.clear()
        self.h_path.configure(text="")
        self.h_stat.configure(text="READY", fg=AMBER_B)
        self.f_lbl.configure(text="ENTER proceed  |  CLICK proceed  |  Q quit")

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True)
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0, width=920, height=640)
        canvas.pack(fill="both", expand=True)
        self._menu_canvas = canvas
        self._splash_canvas = canvas

        canvas.create_line(48, 48, 872, 48, fill=AMBER_D, width=1)
        canvas.create_line(48, 596, 872, 596, fill=DIM2, width=1)

        self._active_cd_center = (86, 96)
        self._draw_cd_center(canvas, r=30)

        canvas.create_text(460, 162, anchor="center", text=BANNER_PREMIUM,
                           font=(FONT, 18, "bold"), fill=AMBER, tags="wordmark")
        canvas.create_text(460, 208, anchor="center", text=SYSTEM_TAGLINE,
                           font=(FONT, 9, "bold"), fill=AMBER_D, tags="subtitle")
        canvas.create_text(460, 226, anchor="center",
                           text="BLACK / GOLD / NEUTRAL  |  OPERATOR ENTRY",
                           font=(FONT, 7), fill=DIM, tags="subtitle")

        try:
            st = _conn.status_summary()
            market_val = st.get("market", "-")
        except Exception:
            market_val = "-"
        try:
            keys = self._load_json("keys.json")
            has_tg = bool(keys.get("telegram", {}).get("bot_token"))
            has_keys = bool(keys.get("demo", {}).get("api_key") or keys.get("testnet", {}).get("api_key"))
        except Exception:
            has_tg = False
            has_keys = False

        market_cell = "LIVE" if market_val and market_val != "-" else "OFFLINE"
        market_col = GREEN if market_cell == "LIVE" else DIM
        conn_cell = "BINANCE READY" if has_keys else "OFFLINE"
        conn_col = GREEN if has_keys else DIM
        tg_cell = "ONLINE" if has_tg else "OFFLINE"
        tg_col = GREEN if has_tg else DIM

        self._draw_panel(canvas, 140, 286, 780, 404, title="SESSION OVERVIEW", accent=AMBER, tag="splash")
        self._draw_kv_rows(canvas, 168, 320, [
            ("ENGINE", "AURUM CORE", WHITE),
            ("MODE", "OPERATOR CONSOLE", AMBER_B),
            ("ACCOUNT", "PAPER / MULTI-ACCOUNT", WHITE),
            ("ENVIRONMENT", "LOCAL", WHITE),
        ], value_x=316, tag="splash")
        self._draw_kv_rows(canvas, 472, 320, [
            ("MARKET FEED", market_cell, market_col),
            ("CONNECTION", conn_cell, conn_col),
            ("TELEGRAM", tg_cell, tg_col),
            ("RISK", "KILL-SWITCH ARMED", RED),
        ], value_x=640, tag="splash")
        canvas.create_line(452, 312, 452, 390, fill=DIM2, width=1, tags="splash")

        canvas.create_text(460, 462, anchor="center",
                           text="ENTER  |  ACCESS MAIN DESK",
                           font=(FONT, 11, "bold"), fill=AMBER_B, tags="prompt")
        canvas.create_text(460, 486, anchor="center",
                           text="Review system state before routing to execution, research or control",
                           font=(FONT, 7), fill=DIM, tags="prompt")

        self._splash_cursor_on = True
        canvas.create_text(460, 526, anchor="center",
                           text="[ ENTER TO ACCESS DESK ]_",
                           font=(FONT, 10, "bold"), fill=AMBER_B, tags="prompt2")

        click_handler = lambda e: self._splash_on_click()
        canvas.bind("<Button-1>", click_handler)
        self.main.bind("<Button-1>", click_handler)
        self._kb("<Return>", self._splash_on_click)
        self._kb("<space>", self._splash_on_click)
        self._bind_global_nav()
        try:
            self.focus_set()
        except Exception:
            pass
        self._splash_pulse_after_id = self.after(500, self._splash_pulse_tick)

    def _splash_pulse_tick(self):
        canvas = self._splash_canvas
        if canvas is None:
            self._splash_pulse_after_id = None
            return
        self._splash_cursor_on = not self._splash_cursor_on
        new_text = "[ ENTER TO ACCESS DESK ]_" if self._splash_cursor_on else "[ ENTER TO ACCESS DESK ] "
        new_color = AMBER_B if self._splash_cursor_on else AMBER
        try:
            canvas.itemconfig("prompt2", text=new_text, fill=new_color)
        except Exception:
            self._splash_pulse_after_id = None
            return
        try:
            self._splash_pulse_after_id = self.after(500, self._splash_pulse_tick)
        except Exception:
            self._splash_pulse_after_id = None

    def _menu_main_bloomberg(self) -> None:
        self._clr()
        self._clear_kb()
        self.history.clear()
        self._active_tile_slots = self._TILE_SLOTS
        self._active_cd_center = (self._CD_CX, self._CD_CY)
        self.h_stat.configure(text="DESK SELECT", fg=AMBER_B)
        self.h_path.configure(text="> MAIN  |  DESK ROUTER")
        self.f_lbl.configure(text="1-4 open desk  |  arrows navigate  |  enter select  |  esc landing")

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True)
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0, width=920, height=540)
        canvas.pack(fill="both", expand=True)
        self._menu_canvas = canvas

        if not any(self._menu_live.get(k) for k in ("markets", "execute", "research", "control")):
            self._menu_live_fetch_async()

        self._draw_panel(canvas, 52, 34, 868, 86, title="AURUM DESK", accent=AMBER, tag="menu")
        canvas.create_text(78, 61, anchor="w", text="PRIMARY ROUTING",
                           font=(FONT, 13, "bold"), fill=AMBER, tags="menu")
        canvas.create_text(78, 78, anchor="w",
                           text="Select a desk before entering strategy, research, market or control workflows",
                           font=(FONT, 8), fill=DIM, tags="menu")

        self._draw_cd_center(canvas)
        self._draw_spokes(canvas, self._menu_focused_tile)
        for idx in range(4):
            self._draw_isometric_tile(canvas, idx, idx == self._menu_focused_tile)

        self._draw_panel(canvas, 52, 452, 868, 512, title="SYSTEM CONTEXT", accent=AMBER_D, tag="menu")
        try:
            market_label = MARKETS.get(_conn.active_market, {}).get("label", "UNSET")
        except Exception:
            market_label = "UNSET"
        self._draw_kv_rows(canvas, 78, 482, [
            ("ENGINE", "DESK ROUTER", WHITE),
            ("MODE", "OPERATOR", WHITE),
            ("ACCOUNT", "PAPER", WHITE),
            ("MARKET", market_label.upper(), AMBER_B),
        ], value_x=218, tag="menu")
        self._draw_kv_rows(canvas, 468, 482, [
            ("BASKET", "DEFAULT", WHITE),
            ("TIMEFRAME", "15M", WHITE),
            ("ENVIRONMENT", "LOCAL", WHITE),
            ("RISK", "KILL-SWITCH ARMED", RED),
        ], value_x=630, tag="menu")

        def _canvas_click(event):
            ex, ey = event.x, event.y
            for idx in range(4):
                x1, y1, x2, y2 = self._tile_rect(idx)
                if x1 <= ex <= x2 and y1 <= ey <= y2:
                    self._menu_tile_focus(idx)
                    self._menu_tile_expand(idx)
                    return
        canvas.bind("<Button-1>", _canvas_click)

        for n in (1, 2, 3, 4):
            self._kb(f"<Key-{n}>", lambda _n=n - 1: (self._menu_tile_focus(_n), self._menu_tile_expand(_n)))
        self._kb("<Right>", lambda: self._menu_tile_focus_delta(+1))
        self._kb("<Left>", lambda: self._menu_tile_focus_delta(-1))
        self._kb("<Down>", lambda: self._menu_tile_focus_delta(+2))
        self._kb("<Up>", lambda: self._menu_tile_focus_delta(-2))
        self._kb("<Tab>", lambda: self._menu_tile_focus_delta(+1))
        self._kb("<Return>", lambda: self._menu_tile_expand(self._menu_focused_tile))
        self._kb("<Escape>", self._splash)
        self._bind_global_nav()
        self._menu_live_schedule()

    def _menu_tile_expand(self, idx: int) -> None:
        if not (0 <= idx <= 3) or self._menu_canvas is None:
            return
        self._menu_expanded_tile = idx
        self._menu_sub_focus = 0

        canvas = self._menu_canvas
        for i in range(4):
            if i != idx:
                canvas.delete(f"tile{i}")
        canvas.delete("cd")
        canvas.delete("spokes")
        canvas.delete("menu")

        label, key_num, color, children = MAIN_GROUPS[idx]
        x1, y1, x2, y2 = 80, 56, 840, 486
        canvas.delete(f"tile{idx}")
        self._draw_panel(canvas, x1, y1, x2, y2, title=f"{label} DESK", accent=color, tag=f"tile{idx}")
        canvas.create_text(110, 92, anchor="w", text=f"{label}  |  SELECT DESTINATION",
                           font=(FONT, 12, "bold"), fill=color, tags=f"tile{idx}")
        canvas.create_text(110, 112, anchor="w",
                           text="Use number keys or arrows to route the operator flow",
                           font=(FONT, 8), fill=DIM, tags=f"tile{idx}")

        self._menu_sub_render(idx)

        def _sub_click(event, _idx=idx):
            ex, ey = event.x, event.y
            _children = MAIN_GROUPS[_idx][3]
            start_y = 178
            row_h = 58
            for i in range(len(_children)):
                y1 = start_y + i * row_h
                y2 = y1 + 40
                if 122 <= ex <= 798 and y1 <= ey <= y2:
                    self._menu_sub_select(_idx, i)
                    return
        canvas.bind("<Button-1>", _sub_click)

        self._clear_kb()
        for i, (_clabel, _method) in enumerate(children):
            n = i + 1
            self._kb(f"<Key-{n}>", lambda _i=i, _tile=idx: self._menu_sub_select(_tile, _i))
        self._kb("<Down>", lambda: self._menu_sub_focus_delta(+1))
        self._kb("<Up>", lambda: self._menu_sub_focus_delta(-1))
        self._kb("<Return>", lambda _tile=idx: self._menu_sub_select(_tile, self._menu_sub_focus))
        self._kb("<Escape>", self._menu_tile_collapse)
        self._kb("<Key-0>", self._menu_tile_collapse)
        self._bind_global_nav()
        self.f_lbl.configure(text="1-N select path  |  click item  |  enter confirm  |  esc back")

    def _menu_sub_render(self, idx: int) -> None:
        if self._menu_canvas is None:
            return
        canvas = self._menu_canvas
        canvas.delete("submenu")
        _label, _key, color, children = MAIN_GROUPS[idx]
        start_y = 178
        row_h = 58
        for i, (child_label, _method) in enumerate(children):
            y1 = start_y + i * row_h
            y2 = y1 + 40
            focused = i == self._menu_sub_focus
            fill = BG2 if focused else PANEL
            outline = color if focused else BORDER
            text_color = AMBER_B if focused else WHITE
            canvas.create_rectangle(122, y1, 798, y2, outline=outline, fill=fill,
                                    width=2 if focused else 1, tags="submenu")
            canvas.create_text(154, y1 + 20, text=f"{i+1:02d}", anchor="center",
                               font=(FONT, 11, "bold"), fill=(color if focused else DIM), tags="submenu")
            canvas.create_text(198, y1 + 14, anchor="w", text=child_label,
                               font=(FONT, 11, "bold"), fill=text_color, tags="submenu")
            canvas.create_text(198, y1 + 28, anchor="w",
                               text="ENTER to open",
                               font=(FONT, 7), fill=DIM, tags="submenu")

    def _draw_isometric_tile(self, canvas, idx: int, focused: bool) -> None:
        label, key_num, color, _children = MAIN_GROUPS[idx]
        x1, y1, x2, y2 = self._tile_rect(idx)
        d = self._TILE_DEPTH
        face_color = color if focused else self._dim_color(color, TILE_DIM_FACTOR)
        panel_fill = BG2 if focused else PANEL
        text_color = WHITE if focused else "#a8a8a8"
        sub_color = AMBER_B if focused else DIM
        tag = f"tile{idx}"

        canvas.delete(tag)
        canvas.create_polygon(
            x1, y1, x2, y1, x2 + d, y1 - d, x1 + d, y1 - d,
            outline=face_color, fill=BG, width=1, tags=tag,
        )
        canvas.create_polygon(
            x2, y1, x2 + d, y1 - d, x2 + d, y2 - d, x2, y2,
            outline=face_color, fill=BG, width=1, tags=tag,
        )
        canvas.create_rectangle(x1, y1, x2, y2, outline=face_color,
                                fill=panel_fill, width=2 if focused else 1, tags=tag)
        canvas.create_rectangle(x1, y1, x2, y1 + 20, outline=face_color,
                                fill=face_color if focused else BG3, width=0, tags=tag)
        canvas.create_text(x1 + 10, y1 + 10, anchor="w",
                           text=f" {key_num}  {label}",
                           font=(FONT, 9, "bold"),
                           fill=(BG if focused else WHITE), tags=tag)
        live_key = label.lower()
        live = self._menu_live.get(live_key, {}) if hasattr(self, "_menu_live") else {}
        for i, line_key in enumerate(("line1", "line2", "line3", "line4")):
            yy = y1 + 36 + i * 18
            text = live.get(line_key, "-")
            canvas.create_text(x1 + 12, yy, anchor="w", text=text,
                               font=(FONT, 8, "bold" if i == 0 and focused else "normal"),
                               fill=text_color if i < 2 else sub_color, tags=tag)

    def _bind_global_nav(self):
        """Bind global navigation keys available on all screens."""
        self._kb("<Key-h>", lambda: self._menu("main"))
        self._kb("<Key-m>", lambda: self._menu("markets"))
        self._kb("<Key-s>", lambda: self._menu("strategies"))
        self._kb("<Key-r>", lambda: self._menu("risk"))
        self._kb("<Key-q>", self._quit)

    # ─── MENU ────────────────────────────────────────────
    def _menu(self, key):
        # Route to specialized screens
        if key in ("markets", "connections", "terminal", "risk", "settings", "alchemy", "data"):
            {
                "markets": self._markets,
                "connections": self._connections,
                "terminal": self._terminal,
                "risk": self._risk_menu,
                "settings": self._config,
                "alchemy": self._arbitrage_hub,
                "data": self._data_center,
            }[key]()
            return
        if key == "strategies":
            self._strategies(); return
        if key == "command":
            self._command_center(); return

        self._clr(); self._clear_kb()
        self.h_stat.configure(text="SELECIONAR", fg=AMBER_D)

        if key == "main":
            self.history.clear()
            items = [(n, k, d) for n, k, d in MAIN_MENU]
            title = "PRINCIPAL"
            self.h_path.configure(text="")
            self.f_lbl.configure(text="ESC sair  |  H hub  |  S strategies  |  Q quit")
            self._kb("<Escape>", self._splash)
            self._bind_global_nav()
        else:
            self.history = ["main"]
            items = [(n, s, d) for n, s, d in SUB_MENUS.get(key, [])]
            title = key.upper()
            self.h_path.configure(text=f"> {title}")
            self.f_lbl.configure(text="ESC voltar  |  número para selecionar  |  0 voltar")
            self._kb("<Escape>", lambda: self._menu("main"))
            self._kb("<BackSpace>", lambda: self._menu("main"))
            self._kb("<Key-0>", lambda: self._menu("main"))
            self._bind_global_nav()

        # ─── MAIN MENU: Fibonacci design ─────────────────
        if key == "main":
            f = tk.Frame(self.main, bg=BG); f.pack(fill="both", expand=True)

            # Fibonacci spiral overlay (canvas behind everything)
            fib_canvas = tk.Canvas(f, bg=BG, highlightthickness=0, width=800, height=500)
            fib_canvas.place(relx=0.5, rely=0.5, anchor="center")

            # Golden ratio proportions
            phi = 1.618
            cx, cy = 400, 250

            # Fibonacci arcs (subtle, decorative)
            fib_sizes = [21, 34, 55, 89, 144, 233]
            for i, r in enumerate(fib_sizes):
                opacity_hex = ["08", "06", "05", "04", "03", "02"][i]
                fib_canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                    start=90 * i, extent=90, outline=f"#ff8c00",
                    width=1, style="arc", dash=(2, 4 + i))

            # Corner ornaments — golden ratio rectangles
            for ox, oy, anchor in [(24, 24, "nw"), (776, 24, "ne"), (24, 476, "sw"), (776, 476, "se")]:
                # Small golden rect (phi proportioned)
                w, h = 34, int(34 / phi)
                x0 = ox if "w" in anchor else ox - w
                y0 = oy if "n" in anchor else oy - h
                fib_canvas.create_rectangle(x0, y0, x0 + w, y0 + h, outline=AMBER_D, width=1, dash=(1, 3))
                # Dot at corner
                dx = x0 if "w" in anchor else x0 + w
                dy = y0 if "n" in anchor else y0 + h
                fib_canvas.create_oval(dx - 2, dy - 2, dx + 2, dy + 2, fill=AMBER_D, outline="")

            # Horizontal golden lines connecting the grid
            for y_off in [-120, -48, 24, 96, 168]:
                y = cy + y_off
                fib_canvas.create_line(80, y, 720, y, fill=BORDER, width=1, dash=(1, 8))
                # Fibonacci tick marks at phi positions
                for px in [0.236, 0.382, 0.5, 0.618, 0.786]:
                    tx = 80 + px * 640
                    fib_canvas.create_line(tx, y - 3, tx, y + 3, fill=DIM2, width=1)

            # Vertical guide lines at phi ratios
            for px in [0.382, 0.618]:
                x = 80 + px * 640
                fib_canvas.create_line(x, cy - 140, x, cy + 200, fill=BORDER, width=1, dash=(1, 12))

            # Golden spiral hint (quarter arcs)
            fib_canvas.create_arc(cx - 89, cy - 89, cx + 89, cy + 89,
                start=0, extent=90, outline=AMBER_D, width=1, dash=(3, 6))
            fib_canvas.create_arc(cx - 55, cy - 55, cx + 55, cy + 55,
                start=90, extent=90, outline=AMBER_D, width=1, dash=(3, 6))
            fib_canvas.create_arc(cx - 34, cy - 34, cx + 34, cy + 34,
                start=180, extent=90, outline=AMBER_D, width=1, dash=(3, 6))

            # Phi label
            fib_canvas.create_text(cx + 100, cy - 130, text="φ = 1.618", font=(FONT, 7),
                                    fill=DIM2, anchor="w")

            # Title over canvas
            title_frame = tk.Frame(f, bg=BG)
            title_frame.place(relx=0.5, rely=0.12, anchor="center")
            tk.Label(title_frame, text="PRINCIPAL", font=(FONT, 16, "bold"), fg=AMBER, bg=BG).pack()
            tk.Label(title_frame, text="Selecionar operação", font=(FONT, 8), fg=DIM, bg=BG).pack()

            # Menu items overlaid on canvas — positioned with Fibonacci spacing
            menu_frame = tk.Frame(f, bg=BG)
            menu_frame.place(relx=0.5, rely=0.52, anchor="center")

            for i, (name, target, desc) in enumerate(items):
                num = i + 1
                row = tk.Frame(menu_frame, bg=BG, cursor="hand2")
                row.pack(fill="x", pady=2)

                # Left accent — fibonacci height (proportional)
                accent_h = max(2, int(8 / phi ** (i * 0.3)))

                tk.Label(row, text=f" {num} ", font=(FONT, 9, "bold"), fg=BG, bg=AMBER, width=3).pack(side="left")

                # Connecting dot
                tk.Label(row, text="─", font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left")

                nl = tk.Label(row, text=f" {name}", font=(FONT, 10, "bold"), fg=WHITE, bg=BG3,
                              anchor="w", padx=8, pady=5, width=14)
                nl.pack(side="left")

                dl = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3, anchor="w", padx=8, pady=5)
                dl.pack(side="left", fill="x", expand=True)

                # Right phi indicator
                tk.Label(row, text="›", font=(FONT, 10), fg=DIM2, bg=BG3, padx=6).pack(side="right")

                cmd = lambda t=target: self._menu(t)

                for w in [row, nl, dl]:
                    w.bind("<Enter>", lambda e, r=row, n=nl: (r.configure(bg=BG3), n.configure(fg=AMBER)))
                    w.bind("<Leave>", lambda e, r=row, n=nl: (r.configure(bg=BG), n.configure(fg=WHITE)))
                    w.bind("<Button-1>", lambda e, c=cmd: c())

                self._kb(f"<Key-{num}>", cmd)

        # ─── SUBMENUS: clean list ─────────────────────────
        else:
            f = tk.Frame(self.main, bg=BG); f.pack(expand=True)

            # Hermes cameo background for backtest submenu
            if key == "backtest":
                _HERMES = (
                    "                ╭──────╮          \n"
                    "             ╭──╯░░░░░░╰──╮       \n"
                    "          ╭──╯░░░░░░░░░░░░╰─╮     \n"
                    "    ──── ╱░░░░░░░░░░░░░░░░░░│     \n"
                    "   ────╱░░░░░░░▓▓░░░░░░░░░░░│     \n"
                    "       │░░░░░▓▓▓▓▓░░░░░░░░░╱      \n"
                    "       │░░░░░▓▓▓▓░░░░░░░░╱        \n"
                    "       │░░░░░░▓▓░░░░░░░╱          \n"
                    "       │░░░░░░░░░░▒▒░╱            \n"
                    "       │░░░░░░░░▒▒▒╱              \n"
                    "       │░░░░░░░░▒▒│               \n"
                    "       ╰╮░░░░░░░░╱                \n"
                    "        ╰╮░░░░░╱                  \n"
                    "         ╰╮░░╱                    \n"
                    "          ╰╱                      \n"
                    "      φ = 1.618                   \n"
                )
                tk.Label(f, text=_HERMES, font=(FONT, 7), fg="#1a1a2e",
                         bg=BG, justify="right", anchor="e").place(relx=0.92, rely=0.5, anchor="e")

            tk.Label(f, text=title, font=(FONT, 14, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 6))
            tk.Label(f, text="Selecionar engine", font=(FONT, 8), fg=DIM, bg=BG).pack(pady=(0, 16))

            for i, (name, target, desc) in enumerate(items):
                num = i + 1
                row = tk.Frame(f, bg=BG, cursor="hand2")
                row.pack(fill="x", padx=60, pady=1)

                tk.Label(row, text=f" {num} ", font=(FONT, 9, "bold"), fg=BG, bg=AMBER, width=3).pack(side="left")
                nl = tk.Label(row, text=f"  {name}", font=(FONT, 10, "bold"), fg=WHITE, bg=BG3, anchor="w", padx=6, pady=4, width=14)
                nl.pack(side="left")
                dl = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3, anchor="w", padx=6, pady=4)
                dl.pack(side="left", fill="x", expand=True)

                cmd = lambda n=name, t=target, d=desc, k=key: self._brief(n, t, d, k)

                for w in [row, nl, dl]:
                    w.bind("<Enter>", lambda e, r=row, n=nl: (r.configure(bg=BG3), n.configure(fg=AMBER)))
                    w.bind("<Leave>", lambda e, r=row, n=nl: (r.configure(bg=BG), n.configure(fg=WHITE)))
                    w.bind("<Button-1>", lambda e, c=cmd: c())

                self._kb(f"<Key-{num}>", cmd)

            # Back row
            tk.Frame(f, bg=BG, height=10).pack()
            brow = tk.Frame(f, bg=BG, cursor="hand2"); brow.pack(fill="x", padx=60, pady=1)
            tk.Label(brow, text=" 0 ", font=(FONT, 9, "bold"), fg=WHITE, bg=DIM2, width=3).pack(side="left")
            bl = tk.Label(brow, text="  VOLTAR", font=(FONT, 10), fg=DIM, bg=BG3, anchor="w", padx=6, pady=4)
            bl.pack(side="left", fill="x", expand=True)
            for w in [brow, bl]:
                w.bind("<Button-1>", lambda e: self._menu("main"))

    # ─── STRATEGY BRIEFING ──────────────────────────────
    def _brief(self, name, script, desc, parent_menu):
        """Half-Life 2 / Bloomberg terminal aesthetic: dense, single-column,
        amber-on-black, monospace. Cuts cruft (technical V2 panel, model
        governance, meta operacional) in favor of the 4 things that matter:
        identity, best config, pipeline, edge/risk."""
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name}")
        self.h_stat.configure(text="BRIEFING", fg=AMBER_D)
        self.f_lbl.configure(text="ENTER executar  |  ESC voltar")

        brief = BRIEFINGS.get(name, {})

        _outer, f = self._ui_page_shell(name, desc, content_width=720)

        # Bloomberg-style section header — amber bar + label + thin rule
        def _section(parent, title):
            tk.Frame(parent, bg=BG, height=14).pack()
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x")
            tk.Frame(row, bg=AMBER, width=3).pack(side="left", fill="y")
            tk.Label(row, text=f" {title} ", font=(FONT, 8, "bold"),
                     fg=AMBER, bg=BG, anchor="w", padx=6).pack(side="left", fill="x", expand=True)
            tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))

        # ── HEADER bar: BRIEFING badge + 1-line desc + amber rule ──
        hdr = tk.Frame(f, bg=BG)
        hdr.pack(fill="x", pady=(0, 4))
        tk.Label(hdr, text=" BRIEFING ", font=(FONT, 7, "bold"),
                 fg=BG, bg=AMBER, padx=6, pady=2).pack(side="left")
        tk.Label(hdr, text=f"  {desc}", font=(FONT, 8), fg=DIM, bg=BG,
                 anchor="w").pack(side="left", fill="x", expand=True)
        tk.Frame(f, bg=AMBER_D, height=1).pack(fill="x", pady=(4, 0))

        # Philosophy as a single italic block (no panel chrome)
        if brief.get("philosophy"):
            tk.Frame(f, bg=BG, height=10).pack()
            tk.Label(f, text=brief["philosophy"], font=(FONT, 8, "italic"),
                     fg=AMBER_D, bg=BG, wraplength=680, justify="left",
                     anchor="w").pack(fill="x")

        # ── BEST CONFIG (most actionable, render first) ──
        bc = brief.get("best_config")
        if bc:
            _section(f, "BEST CONFIG · BATTERY VALIDATED")
            for k, v in bc.items():
                row = tk.Frame(f, bg=BG)
                row.pack(fill="x", pady=0)
                tk.Label(row, text=f"  {k.upper():<14}", font=(FONT, 8, "bold"),
                         fg=AMBER_D, bg=BG, anchor="w", width=16).pack(side="left")
                # Status row gets emoji-aware color
                v_str = str(v)
                _fg = (GREEN if "✓" in v_str else
                       RED   if "✗" in v_str else
                       AMBER if "⚠" in v_str else WHITE)
                tk.Label(row, text=v_str, font=(FONT, 8),
                         fg=_fg, bg=BG, anchor="w",
                         wraplength=540, justify="left").pack(side="left", fill="x", expand=True)

        # ── PIPELINE (numbered, no panel chrome) ──
        if brief.get("logic"):
            _section(f, "PIPELINE")
            for i, step in enumerate(brief["logic"], start=1):
                row = tk.Frame(f, bg=BG)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=f"  {i:02d}", font=(FONT, 7, "bold"),
                         fg=AMBER, bg=BG, width=4, anchor="w").pack(side="left")
                tk.Label(row, text=step, font=(FONT, 8), fg=WHITE, bg=BG,
                         wraplength=620, justify="left",
                         anchor="w").pack(side="left", fill="x", expand=True)

        # ── EDGE / RISK (color-tagged inline pills) ──
        if brief.get("edge") or brief.get("risk"):
            _section(f, "EDGE / RISK")
            if brief.get("edge"):
                row = tk.Frame(f, bg=BG)
                row.pack(fill="x", pady=2)
                tk.Label(row, text="  EDGE  ", font=(FONT, 7, "bold"),
                         fg=BG, bg=GREEN, padx=4).pack(side="left")
                tk.Label(row, text="  " + brief["edge"], font=(FONT, 8),
                         fg=WHITE, bg=BG, anchor="w",
                         wraplength=580, justify="left").pack(side="left", fill="x", expand=True)
            if brief.get("risk"):
                row = tk.Frame(f, bg=BG)
                row.pack(fill="x", pady=2)
                tk.Label(row, text="  RISK  ", font=(FONT, 7, "bold"),
                         fg=BG, bg=RED, padx=4).pack(side="left")
                tk.Label(row, text="  " + brief["risk"], font=(FONT, 8),
                         fg=DIM, bg=BG, anchor="w",
                         wraplength=580, justify="left").pack(side="left", fill="x", expand=True)

        tk.Frame(f, bg=BG, height=20).pack()

        is_bt = parent_menu == "backtest"
        is_live = parent_menu == "live"

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack()

        if is_bt:
            next_fn = lambda: self._config_backtest(name, script, desc, parent_menu)
            btn_text = "  CONFIGURAR & RODAR  "
        elif is_live:
            next_fn = lambda: self._config_live(name, script, desc, parent_menu)
            btn_text = "  SELECIONAR MODO & RODAR  "
        else:
            next_fn = lambda: self._exec(name, script, desc, parent_menu, [])
            btn_text = "  EXECUTAR  "

        run_btn = tk.Label(btn_f, text=btn_text, font=(FONT, 10, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2", padx=12, pady=4)
        run_btn.pack(side="left", padx=4)
        run_btn.bind("<Button-1>", lambda e: next_fn())
        self._kb("<Return>", next_fn)

        # VER CÓDIGO — opens engine source. Uses BRIEFINGS_V2 main_function
        # when available (richer entry point), falls back to script + scan_symbol.
        _v2 = BRIEFINGS_V2.get(name, None)
        _v2_files = _v2.get("source_files") if _v2 else None
        _v2_main  = _v2.get("main_function") if _v2 else None
        def _open_code(_e=None, _script=script,
                       _files=_v2_files, _main=_v2_main):
            try:
                files = _files if _files else [_script]
                main  = _main  if _main  else (_script, "scan_symbol")
                CodeViewer(self, source_files=files, main_function=main)
            except Exception as exc:
                messagebox.showerror("CodeViewer", f"{type(exc).__name__}: {exc}")

        code_btn = tk.Label(btn_f, text="  VER CÓDIGO  ", font=(FONT, 10, "bold"),
                            fg=AMBER, bg=BG3, cursor="hand2", padx=12, pady=4)
        code_btn.pack(side="left", padx=4)
        code_btn.bind("<Button-1>", _open_code)
        self._kb("<F2>", _open_code)

        back_btn = tk.Label(btn_f, text="  VOLTAR  ", font=(FONT, 10), fg=DIM, bg=BG3,
                            cursor="hand2", padx=12, pady=4)
        back_btn.pack(side="left", padx=4)
        back_btn.bind("<Button-1>", lambda e: self._menu(parent_menu))
        self._kb("<Escape>", lambda: self._menu(parent_menu))
        return


    # ─── BACKTEST CONFIG (clickable inputs) ──────────────
    def _config_backtest(self, name, script, desc, parent_menu):
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name} > CONFIG")
        self.h_stat.configure(text="CONFIGURAR", fg=AMBER_D)
        self.f_lbl.configure(text="Clique nas opções  |  ENTER rodar com seleções")

        # State
        self._cfg_period = "90"
        self._cfg_basket = ""  # empty = default
        self._cfg_plots = "s"
        self._cfg_leverage = ""

        _outer, f = self._ui_page_shell(
            f"{name} · BACKTEST CONFIG",
            "Configure run horizon, basket and execution options before launch",
            content_width=920,
        )

        # ── PERIOD ──
        tk.Label(f, text="PERÍODO", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))
        per_f = tk.Frame(f, bg=BG)
        per_f.pack(fill="x", pady=(0, 14))

        self._per_btns = []
        for label, hint, val in PERIODS_UI:
            btn = tk.Label(per_f, text=f" {label} ", font=(FONT, 9, "bold"),
                           fg=BG if val == "90" else DIM, bg=AMBER if val == "90" else BG3,
                           cursor="hand2", padx=10, pady=4)
            btn.pack(side="left", padx=2)
            self._per_btns.append((btn, val))

            def select_period(event, v=val):
                self._cfg_period = v
                for b, bv in self._per_btns:
                    b.configure(fg=BG if bv == v else DIM, bg=AMBER if bv == v else BG3)
            btn.bind("<Button-1>", select_period)

        # ── BASKET ──
        tk.Label(f, text="CESTA DE ATIVOS", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))

        # Basket buttons — row 1
        bsk_f = tk.Frame(f, bg=BG)
        bsk_f.pack(fill="x")

        self._bsk_btns = []
        self._bsk_assets = {b[1]: b[2] for b in BASKETS_UI}  # val -> asset list

        for label, val, assets in BASKETS_UI[:5]:
            btn = tk.Label(bsk_f, text=f" {label} ", font=(FONT, 8, "bold"),
                           fg=BG if val == "" else DIM, bg=AMBER if val == "" else BG3,
                           cursor="hand2", padx=8, pady=3)
            btn.pack(side="left", padx=2)
            self._bsk_btns.append((btn, val))
            btn.bind("<Button-1>", lambda e, v=val: self._select_basket(v))

        # Row 2
        bsk_f2 = tk.Frame(f, bg=BG)
        bsk_f2.pack(fill="x", pady=(2, 0))
        for label, val, assets in BASKETS_UI[5:]:
            btn = tk.Label(bsk_f2, text=f" {label} ", font=(FONT, 8, "bold"),
                           fg=DIM, bg=BG3, cursor="hand2", padx=8, pady=3)
            btn.pack(side="left", padx=2)
            self._bsk_btns.append((btn, val))
            btn.bind("<Button-1>", lambda e, v=val: self._select_basket(v))

        # Preview bar — shows selected assets
        self._bsk_preview_f = tk.Frame(f, bg=BG)
        self._bsk_preview_f.pack(fill="x", pady=(6, 14))
        self._bsk_preview_count = tk.Label(self._bsk_preview_f, text="", font=(FONT, 7, "bold"),
                                            fg=AMBER_D, bg=BG, padx=6)
        self._bsk_preview_count.pack(side="left", pady=4)
        self._bsk_preview_lbl = tk.Label(self._bsk_preview_f, text="", font=(FONT, 7),
                                          fg=DIM, bg=BG, anchor="w", padx=4)
        self._bsk_preview_lbl.pack(side="left", fill="x", expand=True, pady=4)
        tk.Frame(self._bsk_preview_f, bg=DIM2, height=1).pack(fill="x", side="bottom")

        # Show default basket on load
        self._select_basket("")

        # ── OPTIONS ──
        opt_f = tk.Frame(f, bg=BG)
        opt_f.pack(fill="x", pady=(0, 14))

        # Charts toggle
        self._plot_btn = tk.Label(opt_f, text=" GRÁFICOS ON ", font=(FONT, 8, "bold"),
                                   fg=BG, bg=GREEN, cursor="hand2", padx=8, pady=3)
        self._plot_btn.pack(side="left", padx=2)
        def toggle_plots(event):
            self._cfg_plots = "s" if self._cfg_plots == "n" else "n"
            on = self._cfg_plots == "s"
            self._plot_btn.configure(text=" GRÁFICOS ON " if on else " GRÁFICOS OFF ",
                                      fg=BG if on else DIM, bg=GREEN if on else BG3)
        self._plot_btn.bind("<Button-1>", toggle_plots)

        # Leverage
        tk.Label(opt_f, text="  LEVERAGE:", font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG).pack(side="left", padx=(12, 4))
        self._lev_btns = []
        for lev in ["1.0", "2.0", "3.0", "5.0"]:
            btn = tk.Label(opt_f, text=f" {lev}x ", font=(FONT, 8, "bold"),
                           fg=BG if lev == "1.0" else DIM, bg=AMBER if lev == "1.0" else BG3,
                           cursor="hand2", padx=6, pady=3)
            btn.pack(side="left", padx=1)
            self._lev_btns.append((btn, lev))
            def select_lev(event, v=lev):
                self._cfg_leverage = "" if v == "1.0" else v
                for b, bv in self._lev_btns:
                    b.configure(fg=BG if bv == v else DIM, bg=AMBER if bv == v else BG3)
            btn.bind("<Button-1>", select_lev)

        tk.Frame(f, bg=BG, height=10).pack()

        # Summary
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(0, 10))

        # Run button
        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack()

        def do_run():
            # Build BOTH stdin auto-inputs (legacy) AND CLI args (preferred).
            # Engines that parse argparse use CLI; engines with interactive
            # prompts read stdin. Modern engines respect --no-menu and CLI
            # args, falling back to stdin only when --no-menu is absent.
            inputs = [self._cfg_period, self._cfg_basket]
            if name == "CITADEL":
                inputs.append(self._cfg_plots)
            inputs.append(self._cfg_leverage)
            inputs.append("")  # enter to start

            # CLI args — works for CITADEL/BRIDGEWATER/JUMP/DE SHAW/RENAISSANCE
            cli = []
            try:
                _days = int(str(self._cfg_period).strip()) if str(self._cfg_period).strip() else 0
                if _days >= 7:
                    cli += ["--days", str(_days)]
            except (ValueError, TypeError):
                pass
            _basket = str(self._cfg_basket or "").strip()
            # _cfg_basket may be a numeric index ("1","2"...) or basket name
            if _basket and not _basket.isdigit():
                cli += ["--basket", _basket]
            elif _basket.isdigit():
                # Resolve index → basket name
                from config.params import BASKETS
                _bnames = [k for k in BASKETS if k != "custom"]
                _idx = int(_basket) - 1
                if 0 <= _idx < len(_bnames):
                    cli += ["--basket", _bnames[_idx]]
            try:
                _lev = float(str(self._cfg_leverage).replace("x", "").strip()) if str(self._cfg_leverage).strip() else 0
                if 0.1 <= _lev <= 125:
                    cli += ["--leverage", str(_lev)]
            except (ValueError, TypeError):
                pass
            cli += ["--no-menu"]
            self._exec(name, script, desc, parent_menu, inputs, cli_args=cli)

        run_btn = tk.Label(btn_f, text="  RODAR BACKTEST  ", font=(FONT, 11, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2", padx=16, pady=5)
        run_btn.pack(side="left", padx=4)
        run_btn.bind("<Button-1>", lambda e: do_run())
        self._kb("<Return>", do_run)

        back_btn = tk.Label(btn_f, text="  VOLTAR  ", font=(FONT, 10), fg=DIM, bg=BG3,
                            cursor="hand2", padx=12, pady=5)
        back_btn.pack(side="left", padx=4)
        back_btn.bind("<Button-1>", lambda e: self._brief(name, script, desc, parent_menu))
        self._kb("<Escape>", lambda: self._brief(name, script, desc, parent_menu))

    # ─── LIVE CONFIG (clickable mode select) ───────────
    def _config_live(self, name, script, desc, parent_menu):
        """Config screen for live engines — select mode then run."""
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name} > CONFIG")
        self.h_stat.configure(text="CONFIGURAR", fg=AMBER_D)
        self.f_lbl.configure(text="Selecionar modo e RODAR  |  ESC voltar ao briefing")

        # For arbitrage vs live, different modes
        is_arb = "arbitrage" in script
        if is_arb:
            modes = [
                ("DASHBOARD", "1", "Escanear venues e mostrar oportunidades"),
                ("PAPER",     "2", "Simulado — sem ordens reais"),
                ("DEMO",      "3", "Exchange demo/sandbox API"),
                ("LIVE",      "4", "CAPITAL REAL — extremo cuidado"),
            ]
        else:
            modes = [
                ("PAPER",    "1", "Execução simulada — observar sem risco"),
                ("DEMO",     "2", "Binance Futures Demo API — book real, dinheiro fictício"),
                ("TESTNET",  "3", "Binance Testnet — ambiente de teste"),
                ("LIVE",     "4", "CAPITAL REAL — seu dinheiro em jogo"),
            ]

        self._live_mode = modes[0][1]  # default to first

        _outer, f = self._ui_page_shell(
            f"{name} · MODE SELECT",
            "Select execution environment before starting the engine",
            content_width=920,
        )

        self._mode_btns = []
        for label, val, hint in modes:
            row = tk.Frame(f, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=2)

            color = RED if "LIVE" == label else AMBER if "DEMO" == label else GREEN
            is_default = val == self._live_mode

            btn = tk.Label(row, text=f" {label} ", font=(FONT, 9, "bold"),
                           fg=BG if is_default else DIM, bg=color if is_default else BG3,
                           cursor="hand2", padx=10, pady=4)
            btn.pack(side="left", padx=2)

            hl = tk.Label(row, text=f"  {hint}", font=(FONT, 8), fg=DIM, bg=BG, anchor="w", padx=4)
            hl.pack(side="left")

            self._mode_btns.append((btn, val, color))

            def select_mode(event, v=val):
                self._live_mode = v
                for b, bv, c in self._mode_btns:
                    b.configure(fg=BG if bv == v else DIM, bg=c if bv == v else BG3)
            btn.bind("<Button-1>", select_mode)
            hl.bind("<Button-1>", select_mode)

        tk.Frame(f, bg=BG, height=16).pack()
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(0, 10))

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack()

        def do_run():
            self._exec(name, script, desc, parent_menu, [self._live_mode])

        run_btn = tk.Label(btn_f, text="  INICIAR ENGINE  ", font=(FONT, 11, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2", padx=16, pady=5)
        run_btn.pack(side="left", padx=4)
        run_btn.bind("<Button-1>", lambda e: do_run())
        self._kb("<Return>", do_run)

        back_btn = tk.Label(btn_f, text="  VOLTAR  ", font=(FONT, 10), fg=DIM, bg=BG3,
                            cursor="hand2", padx=12, pady=5)
        back_btn.pack(side="left", padx=4)
        back_btn.bind("<Button-1>", lambda e: self._brief(name, script, desc, parent_menu))
        self._kb("<Escape>", lambda: self._brief(name, script, desc, parent_menu))

    def _try_results(self, parent):
        try:
            self._show_results(parent)
        except Exception as e:
            self._p(f"\n  Erro no dashboard de resultados: {e}\n", "r")
            self._p("  Use o menu DADOS para navegar relatórios manualmente.\n", "d")

    # ─── RESULTS DASHBOARD (Overview + Trade Inspector) ──────
    def _show_results(self, parent_menu):
        """Parse latest backtest JSON and show a tabbed dashboard.
        Tab 1 = Overview (metrics / equity / MC / regime).
        Tab 2 = Trade Inspector (list + matplotlib chart + data panel)."""
        self._clr(); self._clear_kb()
        self._results_parent_menu = parent_menu
        self.h_stat.configure(text="RESULTADOS", fg=GREEN)
        self.f_lbl.configure(
            text="ESC voltar  |  1 overview  2 trades  |  ← → navegar trade")
        self._kb("<Escape>", lambda: self._menu(parent_menu))
        self._kb("<Key-1>", lambda: self._results_render_tab("overview"))
        self._kb("<Key-2>", lambda: self._results_render_tab("trades"))
        self._kb("<Left>",  lambda: self._results_prev_trade())
        self._kb("<Up>",    lambda: self._results_prev_trade())
        self._kb("<Right>", lambda: self._results_next_trade())
        self._kb("<Down>",  lambda: self._results_next_trade())

        # Locate the latest run + its exported JSON.
        # New layout (preferred): data/runs/<run_id>/<engine>_*.json  (run_dir = parent)
        # Legacy layout (fallback): data/<engine>/<run_id>/reports/<engine>_*.json
        report = None
        run_dir = None
        skip_names = {"config.json", "equity.json", "index.json", "overfit.json", "price_data.json", "summary.json", "trades.json"}

        runs_root = ROOT / "data" / "runs"
        if runs_root.exists():
            run_dirs = sorted(
                [d for d in runs_root.iterdir() if d.is_dir()],
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            for rd in run_dirs:
                candidates = sorted(
                    [p for p in rd.glob("*.json") if p.name not in skip_names],
                    key=lambda p: p.stat().st_mtime, reverse=True,
                )
                if candidates:
                    report = candidates[0]
                    run_dir = rd
                    break

        if report is None:
            data_dir = ROOT / "data"
            legacy = sorted(
                [
                    p for p in data_dir.rglob("*.json")
                    if p.name not in skip_names and "reports" in str(p.parent)
                ],
                key=lambda p: p.stat().st_mtime, reverse=True
            )
            for r in legacy:
                report = r
                run_dir = r.parent.parent
                break

        if report is None:
            f = tk.Frame(self.main, bg=BG); f.pack(expand=True)
            tk.Label(f, text="Nenhum relatório encontrado.", font=(FONT, 10),
                     fg=DIM, bg=BG).pack(pady=20)
            return

        try:
            with open(report, "r", encoding="utf-8") as fj:
                data = json.load(fj)
        except Exception as e:
            f = tk.Frame(self.main, bg=BG); f.pack(expand=True)
            tk.Label(f, text=f"Erro ao ler relatório: {e}", font=(FONT, 9),
                     fg=RED, bg=BG).pack(pady=20)
            return

        self._results_data = data
        self._results_report = report
        self._results_run_dir = run_dir

        # Load OHLC (optional — older runs may not have it)
        self._price_data = {}
        price_path = self._results_run_dir / "price_data.json"
        if price_path.exists():
            try:
                with open(price_path, "r", encoding="utf-8") as pf:
                    self._price_data = json.load(pf)
            except Exception:
                self._price_data = {}

        all_trades = data.get("trades", [])
        closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
        self._results_trades = closed
        self._results_filtered = list(range(len(closed)))
        self._results_active_idx = 0
        self._results_filter = "all"
        self._results_tab = "overview"
        self._results_tab_btns = {}
        self._results_item_widgets = {}
        self._results_canvas = None
        self._results_chart_frame = None
        self._results_data_panel = None
        self._results_list_canvas = None
        self._results_list_inner = None
        self._results_counter = None
        self._results_stats = None

        # Outer layout: title bar + tab strip + tab body
        root = tk.Frame(self.main, bg=BG); root.pack(fill="both", expand=True)

        title = tk.Frame(root, bg=BG); title.pack(fill="x", padx=20, pady=(10, 4))
        tk.Label(title, text="RESULTADOS DO BACKTEST",
                 font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(side="left")
        meta = f"{data.get('version','')}  ·  {data.get('run_id','')}"
        tk.Label(title, text=meta, font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=10)
        n_closed = len(closed)
        wr = (sum(1 for t in closed if t.get("result") == "WIN") / n_closed * 100) if n_closed else 0
        tk.Label(title, text=f"{n_closed}t  WR {wr:.1f}%",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG).pack(side="right")

        # Tab strip
        strip = tk.Frame(root, bg=BG, height=30); strip.pack(fill="x")
        strip.pack_propagate(False)
        for tab_id, label in [("overview", "1 OVERVIEW"), ("trades", "2 TRADES")]:
            btn = tk.Label(strip, text=f" {label} ", font=(FONT, 9, "bold"),
                           fg=DIM, bg=BG, padx=14, pady=5, cursor="hand2")
            btn.pack(side="left", padx=(0, 10), pady=1)
            btn.bind("<Button-1>", lambda e, t=tab_id: self._results_render_tab(t))
            self._results_tab_btns[tab_id] = btn

        tk.Frame(root, bg=DIM2, height=1).pack(fill="x")
        self._results_body = tk.Frame(root, bg=BG)
        self._results_body.pack(fill="both", expand=True)

        self._results_render_tab("overview")

    def _results_render_tab(self, tab):
        if not hasattr(self, "_results_body") or not self._results_body.winfo_exists():
            return
        for w in self._results_body.winfo_children():
            try: w.destroy()
            except Exception: pass
        self._results_tab = tab
        for tab_id, btn in self._results_tab_btns.items():
            if tab_id == tab:
                btn.configure(bg=BG, fg=AMBER)
            else:
                btn.configure(bg=BG, fg=DIM)
        if tab == "overview":
            self._results_build_overview(self._results_body)
        else:
            self._results_build_trades(self._results_body)

    # ── OVERVIEW TAB ──────────────────────────────────────
    def _results_build_overview(self, parent):
        data = self._results_data
        report = self._results_report
        s  = data.get("summary", {})
        mc = data.get("monte_carlo", {})
        bm = data.get("bear_market", {})
        eq = data.get("equity", [])

        f = tk.Frame(parent, bg=BG); f.pack(fill="both", expand=True)
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(f, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        # Scroll only while cursor is over this canvas (no global bleed-through)
        def _on_enter(_e=None, c=canvas):
            c.bind_all("<MouseWheel>",
                       lambda ev: c.yview_scroll(-1 * (ev.delta // 120), "units"))
        def _on_leave(_e=None, c=canvas):
            try: c.unbind_all("<MouseWheel>")
            except Exception: pass
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)

        pad = 24

        # ── KEY METRICS ──
        met_f = tk.Frame(sf, bg=BG); met_f.pack(fill="x", padx=pad, pady=(12, 8))
        pnl = s.get("total_pnl", 0) or 0
        roi = s.get("ret", 0) or 0
        pnl_color = GREEN if pnl >= 0 else RED
        metrics = [
            (f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}", "PnL TOTAL", pnl_color),
            (f"{roi:+.1f}%", "ROI", pnl_color),
            (f"{s.get('sharpe', 0) or 0:.2f}",  "SHARPE",    AMBER),
            (f"{s.get('sortino', 0) or 0:.2f}", "SORTINO",   AMBER),
            (f"{s.get('win_rate', 0) or 0:.1f}%","TX ACERTO", WHITE),
            (f"{s.get('total_trades', 0) or 0}", "TRADES",    WHITE),
        ]
        for val, label, color in metrics:
            mf = tk.Frame(met_f, bg=BG3, padx=12, pady=8)
            mf.pack(side="left", padx=2, fill="x", expand=True)
            tk.Label(mf, text=val, font=(FONT, 16, "bold"), fg=color, bg=BG3).pack()
            tk.Label(mf, text=label, font=(FONT, 7, "bold"), fg=DIM, bg=BG3).pack()

        def _fit_points(series, width, height, pad_x=10, pad_y=10, mn=None, mx=None):
            if not series or len(series) < 2:
                return []
            mn = min(series) if mn is None else mn
            mx = max(series) if mx is None else mx
            rng = (mx - mn) or 1
            pts = []
            for i, v in enumerate(series):
                x = pad_x + (width - pad_x * 2) * i / max(len(series) - 1, 1)
                y = height - pad_y - (height - pad_y * 2) * (v - mn) / rng
                pts.append((x, y))
            return pts

        def _draw_line_chart(widget, series, line_color, fill_color=None,
                             min_label=None, max_label=None, end_label=None):
            widget.delete("all")
            w = widget.winfo_width() or 700
            h = int(widget.cget("height")) or 120
            if not series or len(series) < 2:
                return
            mn, mx = min(series), max(series)
            pts = _fit_points(series, w, h, mn=mn, mx=mx)
            if fill_color:
                fill_pts = [(pts[0][0], h - 10)] + pts + [(pts[-1][0], h - 10)]
                widget.create_polygon(*[c for p in fill_pts for c in p], fill=fill_color, outline="")
            widget.create_line(*[c for p in pts for c in p], fill=line_color, width=1.8, smooth=True)
            if max_label is not None:
                widget.create_text(8, 8, text=max_label, font=(FONT, 7), fill=DIM, anchor="nw")
            if min_label is not None:
                widget.create_text(8, h - 8, text=min_label, font=(FONT, 7), fill=DIM, anchor="sw")
            if end_label is not None:
                widget.create_text(w - 8, 8, text=end_label, font=(FONT, 7, "bold"),
                                   fill=line_color, anchor="ne")

        # ── EQUITY CURVE ──
        if eq and len(eq) > 2:
            tk.Label(sf, text="CURVA DE EQUITY", font=(FONT, 8, "bold"),
                     fg=AMBER_D, bg=BG).pack(anchor="w", padx=pad, pady=(8, 4))
            eq_canvas = tk.Canvas(sf, bg=PANEL, highlightthickness=0, height=140)
            eq_canvas.pack(fill="x", padx=pad, pady=(0, 8))

            def draw_equity(event=None):
                _draw_line_chart(
                    eq_canvas,
                    eq,
                    AMBER,
                    fill_color="#1a1400",
                    min_label=f"${min(eq):,.0f}",
                    max_label=f"${max(eq):,.0f}",
                    end_label=f"FINAL ${eq[-1]:,.0f}",
                )
            eq_canvas.bind("<Configure>", draw_equity)

        # ── MONTE CARLO ──
        if mc:
            tk.Label(sf, text="MONTE CARLO  (1000 simulações)",
                     font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG
                     ).pack(anchor="w", padx=pad, pady=(8, 4))
            mc_f = tk.Frame(sf, bg=BG); mc_f.pack(fill="x", padx=pad, pady=(0, 8))
            mc_items = [
                (f"{mc.get('pct_pos', 0):.1f}%",  "POSITIVO",
                 GREEN if mc.get('pct_pos', 0) > 50 else RED),
                (f"${mc.get('p5', 0):,.0f}",      "P5 (PIOR)",    DIM),
                (f"${mc.get('median', 0):,.0f}",  "MEDIANA",      AMBER),
                (f"${mc.get('p95', 0):,.0f}",     "P95 (MELHOR)", GREEN),
                (f"{mc.get('ror', 0):.1f}%",      "RISCO RUÍNA",
                 GREEN if mc.get('ror', 0) == 0 else RED),
            ]
            for val, label, color in mc_items:
                mf = tk.Frame(mc_f, bg=BG3, padx=10, pady=6)
                mf.pack(side="left", padx=2, fill="x", expand=True)
                tk.Label(mf, text=val, font=(FONT, 12, "bold"),
                         fg=color, bg=BG3).pack()
                tk.Label(mf, text=label, font=(FONT, 7), fg=DIM, bg=BG3).pack()

            mc_paths = mc.get("paths") or []
            if mc_paths:
                mc_canvas = tk.Canvas(sf, bg=PANEL, highlightthickness=0, height=150)
                mc_canvas.pack(fill="x", padx=pad, pady=(0, 8))

                def draw_mc_paths(event=None):
                    mc_canvas.delete("all")
                    w = mc_canvas.winfo_width() or 700
                    h = int(mc_canvas.cget("height")) or 150
                    valid = [p for p in mc_paths if p and len(p) > 1]
                    if not valid:
                        return
                    mn = min(min(p) for p in valid)
                    mx = max(max(p) for p in valid)
                    for path in valid[:120]:
                        pts = _fit_points(path, w, h, mn=mn, mx=mx)
                        if len(pts) >= 2:
                            mc_canvas.create_line(*[c for p in pts for c in p],
                                                  fill="#274d3d", width=1)
                    median_path = sorted(valid, key=lambda p: p[-1])[len(valid) // 2]
                    median_pts = _fit_points(median_path, w, h, mn=mn, mx=mx)
                    if len(median_pts) >= 2:
                        mc_canvas.create_line(*[c for p in median_pts for c in p],
                                              fill=AMBER, width=2.0, smooth=True)
                    base_line = [eq[0]] * len(valid[0]) if eq else [0] * len(valid[0])
                    base_pts = _fit_points(base_line, w, h, mn=mn, mx=mx)
                    if len(base_pts) >= 2:
                        mc_canvas.create_line(*[c for p in base_pts for c in p],
                                              fill=DIM2, width=1, dash=(4, 3))
                    mc_canvas.create_text(8, 8, text=f"${mx:,.0f}",
                                          font=(FONT, 7), fill=DIM, anchor="nw")
                    mc_canvas.create_text(8, h - 8, text=f"${mn:,.0f}",
                                          font=(FONT, 7), fill=DIM, anchor="sw")
                    mc_canvas.create_text(w - 8, 8, text="PATHS + MEDIANA",
                                          font=(FONT, 7, "bold"), fill=AMBER, anchor="ne")
                mc_canvas.bind("<Configure>", draw_mc_paths)

            mc_finals = mc.get("finals") or []
            if mc_finals:
                dist_canvas = tk.Canvas(sf, bg=PANEL, highlightthickness=0, height=110)
                dist_canvas.pack(fill="x", padx=pad, pady=(0, 8))

                def draw_mc_distribution(event=None):
                    dist_canvas.delete("all")
                    w = dist_canvas.winfo_width() or 700
                    h = int(dist_canvas.cget("height")) or 110
                    if len(mc_finals) < 2:
                        return
                    vals = mc_finals
                    mn = min(vals)
                    mx = max(vals)
                    rng = (mx - mn) or 1
                    bins = min(28, max(8, len(vals) // 25))
                    counts = [0] * bins
                    for v in vals:
                        idx = min(bins - 1, int((v - mn) / rng * bins))
                        counts[idx] += 1
                    top = max(counts) or 1
                    usable_w = w - 20
                    bar_w = usable_w / bins
                    for i, ct in enumerate(counts):
                        x0 = 10 + i * bar_w
                        x1 = x0 + max(bar_w - 2, 1)
                        y1 = h - 12
                        y0 = y1 - (h - 28) * ct / top
                        dist_canvas.create_rectangle(x0, y0, x1, y1, fill="#2c3e34", outline="")

                    def _mark(value, color, label):
                        x = 10 + usable_w * ((value - mn) / rng)
                        dist_canvas.create_line(x, 10, x, h - 10, fill=color, width=1)
                        dist_canvas.create_text(x + 4, 8, text=label, font=(FONT, 7),
                                                fill=color, anchor="nw")

                    _mark(mc.get("p5", mn), RED, "P5")
                    _mark(mc.get("median", vals[len(vals) // 2]), AMBER, "MED")
                    _mark(mc.get("p95", mx), GREEN, "P95")
                    dist_canvas.create_text(8, h - 8, text=f"${mn:,.0f}",
                                            font=(FONT, 7), fill=DIM, anchor="sw")
                    dist_canvas.create_text(w - 8, h - 8, text=f"${mx:,.0f}",
                                            font=(FONT, 7), fill=DIM, anchor="se")
                    dist_canvas.create_text(w - 8, 8, text="DISTRIBUICAO FINAL",
                                            font=(FONT, 7, "bold"), fill=WHITE, anchor="ne")
                dist_canvas.bind("<Configure>", draw_mc_distribution)

        # ── REGIME PERFORMANCE ──
        if bm:
            tk.Label(sf, text="PERFORMANCE POR REGIME",
                     font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG
                     ).pack(anchor="w", padx=pad, pady=(8, 4))
            for regime, rd in bm.items():
                if not rd: continue
                rf = tk.Frame(sf, bg=BG3); rf.pack(fill="x", padx=pad, pady=1)
                rc = GREEN if regime == "BULL" else RED if regime == "BEAR" else AMBER
                tk.Label(rf, text=f" {regime} ", font=(FONT, 8, "bold"),
                         fg=BG, bg=rc, padx=4).pack(side="left", padx=4, pady=4)
                tk.Label(rf, text=(f"{rd.get('n',0)} trades  "
                                   f"WR {rd.get('wr',0):.1f}%  "
                                   f"Sharpe {rd.get('sharpe',0):.2f}  "
                                   f"DD {rd.get('max_dd',0):.1f}%"),
                         font=(FONT, 8), fg=WHITE, bg=BG3, padx=8
                         ).pack(side="left", pady=4)
                pnl_r = rd.get("pnl", 0)
                tk.Label(rf, text=f"${pnl_r:+,.0f}", font=(FONT, 9, "bold"),
                         fg=GREEN if pnl_r >= 0 else RED, bg=BG3, padx=8
                         ).pack(side="right", pady=4)

        # ── ACTIONS ──
        tk.Frame(sf, bg=DIM2, height=1).pack(fill="x", padx=pad, pady=(12, 8))
        act_f = tk.Frame(sf, bg=BG); act_f.pack(padx=pad, pady=(0, 16))

        report_html = self._results_run_dir / "report.html"
        if report_html.exists():
            oh = tk.Label(act_f, text="  ABRIR HTML  ", font=(FONT, 9, "bold"),
                          fg=BG, bg=AMBER, cursor="hand2", padx=10, pady=3)
            oh.pack(side="left", padx=4)
            oh.bind("<Button-1>", lambda e: self._open_file(report_html))

        ti = tk.Label(act_f, text="  TRADE INSPECTOR →  ",
                      font=(FONT, 9, "bold"), fg=BG, bg=GREEN,
                      cursor="hand2", padx=10, pady=3)
        ti.pack(side="left", padx=4)
        ti.bind("<Button-1>", lambda e: self._results_render_tab("trades"))

        bk = tk.Label(act_f, text="  VOLTAR  ", font=(FONT, 9),
                      fg=DIM, bg=BG3, cursor="hand2", padx=10, pady=3)
        bk.pack(side="left", padx=4)
        bk.bind("<Button-1>", lambda e: self._menu(self._results_parent_menu))

    # ── TRADES TAB (inspector) ─────────────────────────────
    def _results_build_trades(self, parent):
        if not self._results_trades:
            tk.Label(parent, text="Sem trades fechadas neste run.",
                     font=(FONT, 10), fg=DIM, bg=BG).pack(pady=40)
            return

        outer = tk.Frame(parent, bg=BG); outer.pack(fill="both", expand=True)
        top_row = tk.Frame(outer, bg=BG); top_row.pack(fill="both", expand=True)

        # Left sidebar: trade list + filters
        side = tk.Frame(top_row, bg=PANEL, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._results_build_list(side)

        tk.Frame(top_row, bg=DIM2, width=1).pack(side="left", fill="y")

        # Right: chart + data panel
        right = tk.Frame(top_row, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        self._results_chart_frame = tk.Frame(right, bg="#0d1117", height=320)
        self._results_chart_frame.pack(fill="x", pady=(0, 8))
        self._results_chart_frame.pack_propagate(False)

        self._results_data_panel = tk.Frame(right, bg=PANEL)
        self._results_data_panel.pack(fill="both", expand=True)

        # Bottom nav bar
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x")
        nav = tk.Frame(outer, bg=BG, height=28); nav.pack(fill="x")
        nav.pack_propagate(False)

        prev_btn = tk.Label(nav, text="  ◄ prev  ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG, cursor="hand2", padx=8, pady=6)
        prev_btn.pack(side="left", padx=4)
        prev_btn.bind("<Button-1>", lambda e: self._results_prev_trade())

        self._results_counter = tk.Label(nav, text="", font=(FONT, 8),
                                         fg=DIM, bg=BG)
        self._results_counter.pack(side="left", padx=8)

        next_btn = tk.Label(nav, text="  next ►  ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG, cursor="hand2", padx=8, pady=6)
        next_btn.pack(side="left", padx=4)
        next_btn.bind("<Button-1>", lambda e: self._results_next_trade())

        self._results_stats = tk.Label(nav, text="", font=(FONT, 8),
                                       fg=DIM, bg=BG2)
        self._results_stats.pack(side="right", padx=8)

        # Initial render
        if self._results_filtered:
            self._results_active_idx = min(self._results_active_idx,
                                           len(self._results_filtered) - 1)
            self._results_inspect(self._results_filtered[self._results_active_idx])
        else:
            self._results_update_nav()

    def _results_build_list(self, parent):
        # Filter row
        filt = tk.Frame(parent, bg=BG2); filt.pack(fill="x")
        for tag in ("all", "win", "loss"):
            label = tag.upper()
            active = self._results_filter == tag
            btn = tk.Label(filt, text=f" {label} ", font=(FONT, 7, "bold"),
                           fg=BG if active else DIM,
                           bg=AMBER if active else BG3,
                           padx=8, pady=3, cursor="hand2")
            btn.pack(side="left", padx=2, pady=4)
            btn.bind("<Button-1>", lambda e, t=tag: self._results_filter_set(t))

        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x")

        # Scrollable list
        list_outer = tk.Frame(parent, bg=PANEL)
        list_outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_outer, bg=PANEL, highlightthickness=0)
        sb = tk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        self._results_list_inner = tk.Frame(canvas, bg=PANEL)
        self._results_list_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._results_list_inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def _on_enter(_e=None, c=canvas):
            c.bind_all("<MouseWheel>",
                       lambda ev: c.yview_scroll(-1 * (ev.delta // 120), "units"))
        def _on_leave(_e=None, c=canvas):
            try: c.unbind_all("<MouseWheel>")
            except Exception: pass
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)

        self._results_list_canvas = canvas
        self._results_build_list_items()

    def _results_build_list_items(self):
        if self._results_list_inner is None:
            return
        for w in self._results_list_inner.winfo_children():
            try: w.destroy()
            except Exception: pass

        self._results_item_widgets = {}
        for list_idx, trade_idx in enumerate(self._results_filtered):
            t = self._results_trades[trade_idx]
            is_win = t.get("result") == "WIN"
            is_long = t.get("direction") == "BULLISH"
            side = "LONG" if is_long else "SHORT"
            result = "WIN" if is_win else "LOSS"
            pnl = float(t.get("pnl", 0) or 0)
            active = list_idx == self._results_active_idx
            bg = BG3 if active else PANEL

            row = tk.Frame(self._results_list_inner, bg=bg, cursor="hand2")
            row.pack(fill="x")

            accent = tk.Frame(row, bg=AMBER if active else PANEL, width=3)
            accent.pack(side="left", fill="y")

            body = tk.Frame(row, bg=bg)
            body.pack(side="left", fill="x", expand=True, padx=6, pady=4)

            head = tk.Label(body, text=f"#{trade_idx + 1}", font=(FONT, 7),
                            fg=DIM, bg=bg, anchor="w")
            head.pack(fill="x")

            sym_short = str(t.get("symbol", "?")).replace("USDT", "")
            mid = tk.Label(body, text=sym_short, font=(FONT, 10, "bold"),
                           fg=AMBER, bg=bg, anchor="w")
            mid.pack(fill="x")

            srl = tk.Label(body, text=f"{side} {result}",
                           font=(FONT, 7, "bold"),
                           fg=GREEN if is_win else RED, bg=bg, anchor="w")
            srl.pack(fill="x")

            pnl_l = tk.Label(body,
                             text=f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",
                             font=(FONT, 9, "bold"),
                             fg=GREEN if pnl >= 0 else RED, bg=bg, anchor="w")
            pnl_l.pack(fill="x")

            def _click(_e=None, idx=trade_idx):
                if idx in self._results_filtered:
                    self._results_active_idx = self._results_filtered.index(idx)
                self._results_inspect(idx)

            widgets = (row, accent, body, head, mid, srl, pnl_l)
            for w in widgets:
                w.bind("<Button-1>", _click)
            self._results_item_widgets[list_idx] = (row, accent, body,
                                                    [head, mid, srl, pnl_l])

    def _results_repaint_list(self):
        for list_idx, (row, accent, body, labels) in self._results_item_widgets.items():
            active = list_idx == self._results_active_idx
            bg = BG3 if active else PANEL
            try:
                row.configure(bg=bg)
                accent.configure(bg=AMBER if active else PANEL)
                body.configure(bg=bg)
                for l in labels:
                    l.configure(bg=bg)
            except Exception:
                pass
        # Scroll the active item into view
        canvas = self._results_list_canvas
        if canvas is not None and self._results_filtered:
            try:
                n = len(self._results_filtered)
                frac = self._results_active_idx / max(n - 1, 1)
                canvas.yview_moveto(max(0.0, frac - 0.15))
            except Exception:
                pass

    def _results_filter_set(self, kind):
        self._results_filter = kind
        trades = self._results_trades
        if kind == "win":
            self._results_filtered = [i for i, t in enumerate(trades)
                                      if t.get("result") == "WIN"]
        elif kind == "loss":
            self._results_filtered = [i for i, t in enumerate(trades)
                                      if t.get("result") == "LOSS"]
        else:
            self._results_filtered = list(range(len(trades)))
        self._results_active_idx = 0
        self._results_render_tab("trades")

    def _results_next_trade(self):
        if self._results_tab != "trades" or not self._results_filtered:
            return
        n = len(self._results_filtered)
        self._results_active_idx = (self._results_active_idx + 1) % n
        self._results_inspect(self._results_filtered[self._results_active_idx])

    def _results_prev_trade(self):
        if self._results_tab != "trades" or not self._results_filtered:
            return
        n = len(self._results_filtered)
        self._results_active_idx = (self._results_active_idx - 1) % n
        self._results_inspect(self._results_filtered[self._results_active_idx])

    def _results_inspect(self, trade_idx):
        if trade_idx < 0 or trade_idx >= len(self._results_trades):
            return
        trade = self._results_trades[trade_idx]
        self._results_render_chart(trade)
        self._results_render_data_panel(trade)
        self._results_repaint_list()
        self._results_update_nav()

    def _results_update_nav(self):
        if self._results_counter is not None:
            try:
                n = len(self._results_filtered)
                pos = self._results_active_idx + 1 if n else 0
                self._results_counter.configure(text=f"{pos} / {n}")
            except Exception: pass
        if self._results_stats is not None:
            try:
                trades = [self._results_trades[i] for i in self._results_filtered]
                total = len(trades)
                wins = sum(1 for t in trades if t.get("result") == "WIN")
                wr = (wins / total * 100) if total else 0
                pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
                sharpe = self._results_data.get("summary", {}).get("sharpe") or 0
                self._results_stats.configure(
                    text=f"WR {wr:.1f}%   PnL ${pnl:+,.0f}   Sharpe {sharpe:.2f}")
            except Exception: pass

    # ── CHART RENDER (matplotlib via FigureCanvasTkAgg) ──
    def _results_render_chart(self, trade):
        # Destroy previous canvas (releases the Figure)
        for w in self._results_chart_frame.winfo_children():
            try: w.destroy()
            except Exception: pass
        self._results_canvas = None

        sym = trade.get("symbol", "")
        ohlc = self._price_data.get(sym) if self._price_data else None
        if not ohlc or "close" not in ohlc:
            tk.Label(self._results_chart_frame,
                     text="OHLC data não disponível para este run",
                     font=(FONT, 9), fg=DIM, bg="#0d1117").pack(expand=True)
            return

        try:
            # Import locally so the launcher only loads matplotlib when
            # the Trade Inspector is actually used.
            from matplotlib.figure import Figure
            from matplotlib.patches import Rectangle
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        except Exception as e:
            tk.Label(self._results_chart_frame,
                     text=f"matplotlib indisponível: {e}",
                     font=(FONT, 9), fg=RED, bg="#0d1117").pack(expand=True)
            return

        idx = int(trade.get("entry_idx", 0) or 0)
        dur = max(1, int(trade.get("duration", 1) or 1))
        total = len(ohlc["close"])
        start = max(0, idx - 30)
        end   = min(total, idx + dur + 15)
        if end - start < 2:
            tk.Label(self._results_chart_frame, text="Janela OHLC insuficiente",
                     font=(FONT, 9), fg=DIM, bg="#0d1117").pack(expand=True)
            return

        o = ohlc["open"][start:end]
        h = ohlc["high"][start:end]
        l = ohlc["low"][start:end]
        c = ohlc["close"][start:end]
        n = len(c)

        fig = Figure(figsize=(8, 3.6), dpi=90, facecolor="#0d1117")
        ax = fig.add_subplot(111, facecolor="#0d1117")

        # Candlesticks
        for i in range(n):
            oi, hi, li, ci = o[i], h[i], l[i], c[i]
            col = "#26d47c" if ci >= oi else "#e85d5d"
            ax.plot([i, i], [li, hi], color=col, linewidth=0.8)
            body_lo = min(oi, ci)
            body_hi = max(oi, ci)
            body_h  = max(body_hi - body_lo, (hi - li) * 0.02 if hi > li else 0)
            ax.add_patch(Rectangle(
                (i - 0.35, body_lo), 0.7, body_h,
                facecolor=col, edgecolor=col, linewidth=0.5))

        local_entry = idx - start
        local_exit  = min(idx + dur - start, n - 1)

        entry_p  = float(trade.get("entry", 0) or 0)
        stop_p   = float(trade.get("stop", entry_p) or entry_p)
        target_p = float(trade.get("target", entry_p) or entry_p)
        exit_p   = float(trade.get("exit_p", entry_p) or entry_p)

        ax.axhline(entry_p,  color="#ff8c00", linewidth=1.2)
        ax.axhline(stop_p,   color="#e85d5d", linewidth=1.0, linestyle="--")
        ax.axhline(target_p, color="#26d47c", linewidth=1.0, linestyle="--")
        ax.axhline(exit_p,   color="#ffffff", linewidth=0.8, linestyle=":", alpha=0.7)

        is_win  = trade.get("result") == "WIN"
        is_long = trade.get("direction") == "BULLISH"
        shade = "#26d47c" if is_win else "#e85d5d"
        ax.axvspan(local_entry, local_exit, alpha=0.06, color=shade)

        # Entry arrow (points toward stop)
        dy = (stop_p - entry_p) * 0.6
        try:
            ax.annotate("",
                        xy=(local_entry, entry_p),
                        xytext=(local_entry, entry_p + dy),
                        arrowprops=dict(arrowstyle="->", color="#ff8c00", lw=2))
        except Exception:
            pass

        # Exit marker
        exit_color = "#26d47c" if is_win else "#e85d5d"
        ax.plot(local_exit, exit_p, "o", color=exit_color,
                markersize=8, zorder=5)

        # Right-side labels
        x_lbl = n + 0.5
        ax.text(x_lbl, entry_p,  f"E {entry_p:.4f}", fontsize=7,
                color="#ff8c00", va="center", fontfamily="monospace")
        ax.text(x_lbl, stop_p,   f"S {stop_p:.4f}",  fontsize=7,
                color="#e85d5d", va="center", fontfamily="monospace")
        ax.text(x_lbl, target_p, f"T {target_p:.4f}", fontsize=7,
                color="#26d47c", va="center", fontfamily="monospace")
        ax.text(x_lbl, exit_p,   f"X {exit_p:.4f}",  fontsize=7,
                color="#ffffff", va="center", fontfamily="monospace", alpha=0.7)

        ax.tick_params(colors="#8b949e", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#1b2028")
        ax.grid(True, color="#1b2028", linestyle="--", alpha=0.3)
        ax.set_xlim(-1, n + 7)

        side   = "LONG" if is_long else "SHORT"
        result = trade.get("result", "?")
        pnl    = float(trade.get("pnl", 0) or 0)
        score  = float(trade.get("score", 0) or 0)
        fig.suptitle(
            f"{sym}  {side}  {result}  ${pnl:+,.2f}  Ω={score:.3f}",
            fontsize=10, color="#ff8c00",
            fontfamily="monospace", fontweight="bold")

        fig.subplots_adjust(left=0.09, right=0.88, top=0.90, bottom=0.12)
        fig.text(0.88, 0.02, "AURUM · CITADEL",
                 fontsize=7, color="#1b2028",
                 fontfamily="monospace", ha="right")

        canvas = FigureCanvasTkAgg(fig, master=self._results_chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        # Keep reference so gc doesn't collect the figure while it's visible
        self._results_canvas = canvas

    def _results_render_data_panel(self, trade):
        for w in self._results_data_panel.winfo_children():
            try: w.destroy()
            except Exception: pass

        inner = tk.Frame(self._results_data_panel, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=12, pady=8)

        tk.Label(inner, text="TRADE DATA", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x")
        tk.Frame(inner, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))

        entry   = float(trade.get("entry", 0) or 0)
        stop    = float(trade.get("stop", 0) or 0)
        exit_p  = float(trade.get("exit_p", 0) or 0)
        target  = float(trade.get("target", 0) or 0)
        pnl     = float(trade.get("pnl", 0) or 0)
        is_long = trade.get("direction") == "BULLISH"
        risk    = abs(entry - stop)
        if risk > 0:
            move = (exit_p - entry) if is_long else (entry - exit_p)
            rmult = move / risk
        else:
            rmult = 0.0
        pnl_col = GREEN if pnl >= 0 else RED
        rm_col  = GREEN if rmult >= 0 else RED

        grid = tk.Frame(inner, bg=PANEL); grid.pack(fill="x")

        fields = [
            ("Symbol",   str(trade.get("symbol", "?")),              WHITE),
            ("Score Ω",  f"{float(trade.get('score', 0) or 0):.3f}", AMBER),
            ("Side",     "LONG" if is_long else "SHORT",             WHITE),
            ("Regime",   str(trade.get("macro_bias", "?")),          WHITE),
            ("Entry",    f"${entry:,.4f}",                           WHITE),
            ("Stop",     f"${stop:,.4f}",                            RED),
            ("Exit",     f"${exit_p:,.4f}",                          WHITE),
            ("Target",   f"${target:,.4f}",                          GREEN),
            ("PnL",      f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",    pnl_col),
            ("R-Mult",   f"{rmult:+.2f}R",                           rm_col),
            ("Duration", f"{int(trade.get('duration', 0) or 0)} candles", DIM),
            ("RR Plan",  f"{float(trade.get('rr', 0) or 0):.2f}x",   DIM),
            ("Vol",      str(trade.get("vol_regime", "?")),          DIM),
            ("DD Scale", f"{float(trade.get('dd_scale', 1) or 1):.2f}", DIM),
        ]
        for i, (label, value, col) in enumerate(fields):
            r, c = divmod(i, 2)
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 24), pady=2)
            tk.Label(cell, text=label, font=(FONT, 7),
                     fg=DIM, bg=PANEL, width=10, anchor="w").pack(side="left")
            tk.Label(cell, text=value, font=(FONT, 9, "bold"),
                     fg=col, bg=PANEL, anchor="w").pack(side="left", padx=4)

        # Omega component bars
        tk.Frame(inner, bg=PANEL, height=10).pack()
        tk.Label(inner, text="Ω COMPONENTS", font=(FONT, 7, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x")
        tk.Frame(inner, bg=DIM2, height=1).pack(fill="x", pady=(2, 4))

        omega_rows = [
            ("STRUCT",   "omega_struct"),
            ("FLOW",     "omega_flow"),
            ("CASCADE",  "omega_cascade"),
            ("MOMENTUM", "omega_momentum"),
            ("PULLBACK", "omega_pullback"),
        ]
        for name, key in omega_rows:
            val = float(trade.get(key, 0) or 0)
            row = tk.Frame(inner, bg=PANEL); row.pack(fill="x", pady=1)
            tk.Label(row, text=name, font=(FONT, 7), fg=DIM, bg=PANEL,
                     width=10, anchor="w").pack(side="left")
            bar_bg = tk.Frame(row, bg=BG3, height=8, width=160)
            bar_bg.pack(side="left", padx=4)
            bar_bg.pack_propagate(False)
            fill_w = max(1, int(160 * min(max(val, 0.0), 1.0)))
            tk.Frame(bar_bg, bg=AMBER, height=8, width=fill_w).pack(side="left")
            tk.Label(row, text=f"{val:.2f}", font=(FONT, 7, "bold"),
                     fg=WHITE, bg=PANEL).pack(side="left", padx=6)

    def _open_file(self, path):
        if sys.platform == "win32": os.startfile(str(path))
        elif sys.platform == "darwin": subprocess.run(["open", str(path)])
        else: subprocess.run(["xdg-open", str(path)])

    def _select_basket(self, val):
        """Update basket selection — highlight button + show asset preview."""
        self._cfg_basket = val
        # Update button highlights
        for b, bv in self._bsk_btns:
            b.configure(fg=BG if bv == val else DIM, bg=AMBER if bv == val else BG3)
        # Update preview
        assets = self._bsk_assets.get(val, [])
        if assets:
            count = len(assets)
            asset_str = "  ".join(assets)
            self._bsk_preview_count.configure(text=f" {count} ATIVOS ")
            self._bsk_preview_lbl.configure(text=asset_str)
        else:
            self._bsk_preview_count.configure(text="")
            self._bsk_preview_lbl.configure(text="")

    # ─── EXECUTE ENGINE ──────────────────────────────────
    def _exec(self, name, script, desc, parent_menu, auto_inputs, cli_args=None):
        self._clr(); self._clear_kb()
        self._exec_parent = parent_menu  # save for results screen
        self.oq = queue.Queue()
        is_bt = parent_menu == "backtest"
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name}")
        self.h_stat.configure(text="RODANDO", fg=GREEN)
        self.f_lbl.configure(
            text="M mapa de install  |  C console runtime  |  ENTER enviar  |  vazio = aceitar padrão"
            if is_bt else
            "Digite abaixo + ENTER  |  vazio = aceitar padrão"
        )

        f = tk.Frame(self.main, bg=BG); f.pack(fill="both", expand=True)

        # Top bar
        top = tk.Frame(f, bg=BG2); top.pack(fill="x")
        tk.Label(top, text=f" {name} ", font=(FONT, 8, "bold"), fg=BG, bg=AMBER).pack(side="left", padx=6, pady=3)
        tk.Label(top, text=desc, font=(FONT, 8), fg=DIM, bg=BG2, padx=6).pack(side="left", pady=3)

        tk.Button(top, text=" STOP ", font=(FONT, 7, "bold"), fg=RED, bg=BG2, border=0, cursor="hand2",
                  activeforeground=WHITE, activebackground=BG3, command=self._stop).pack(side="right", padx=4, pady=3)
        tk.Button(top, text=" BACK ", font=(FONT, 7, "bold"), fg=DIM, bg=BG2, border=0, cursor="hand2",
                  activeforeground=WHITE, activebackground=BG3,
                  command=lambda: (self._stop(), self._menu(parent_menu))).pack(side="right", pady=3)
        if is_bt:
            tk.Button(top, text=" CMD ", font=(FONT, 7, "bold"), fg=AMBER, bg=BG2, border=0, cursor="hand2",
                      activeforeground=WHITE, activebackground=BG3,
                      command=lambda: self._exec_show_view("console")).pack(side="right", padx=(0, 4), pady=3)
            tk.Button(top, text=" MAPA ", font=(FONT, 7, "bold"), fg=GREEN, bg=BG2, border=0, cursor="hand2",
                      activeforeground=WHITE, activebackground=BG3,
                      command=lambda: self._exec_show_view("visual")).pack(side="right", padx=(0, 4), pady=3)

        tk.Frame(f, bg=AMBER_D, height=1).pack(fill="x")

        body = tk.Frame(f, bg=BG)
        body.pack(fill="both", expand=True)
        self._exec_body = body

        if is_bt:
            self._exec_visual = tk.Frame(body, bg=BG)
            self._exec_visual.pack(fill="both", expand=True)
            self._exec_init_progress_ui(self._exec_visual, name, desc)
        else:
            self._exec_visual = None

        # Console
        cf = tk.Frame(body, bg=PANEL)
        if not is_bt:
            cf.pack(fill="both", expand=True)
        self._exec_console = cf
        sb = tk.Scrollbar(cf, bg=BG, troughcolor=BG, highlightthickness=0, bd=0)
        sb.pack(side="right", fill="y")
        self.con = tk.Text(cf, bg=PANEL, fg=WHITE, font=(FONT, 9), wrap="word",
                           borderwidth=0, highlightthickness=0, insertbackground=AMBER,
                           padx=10, pady=6, state="disabled", cursor="arrow",
                           yscrollcommand=sb.set)
        self.con.pack(fill="both", expand=True)
        sb.config(command=self.con.yview)
        self.con.tag_configure("a", foreground=AMBER)
        self.con.tag_configure("g", foreground=GREEN)
        self.con.tag_configure("r", foreground=RED)
        self.con.tag_configure("d", foreground=DIM)
        self.con.tag_configure("w", foreground=WHITE)
        if is_bt:
            self._exec_show_view("visual")
            self._kb("<Key-c>", lambda: self._exec_show_view("console"))
            self._kb("<Key-m>", lambda: self._exec_show_view("visual"))

        # Input bar
        tk.Frame(f, bg=AMBER, height=1).pack(fill="x")
        ib = tk.Frame(f, bg=BG2, height=34); ib.pack(fill="x"); ib.pack_propagate(False)

        self._inp_lbl = tk.Label(ib, text=" ENTRADA ", font=(FONT, 7, "bold"), fg=BG, bg=AMBER)
        self._inp_lbl.pack(side="left", padx=(6,4), pady=5)

        tk.Label(ib, text=">", font=(FONT, 10, "bold"), fg=AMBER, bg=BG2).pack(side="left")
        self.inp = tk.Entry(ib, bg=BG3, fg=WHITE, font=(FONT, 10), insertbackground=AMBER,
                             border=0, highlightthickness=1, highlightcolor=AMBER_D, highlightbackground=BORDER)
        self.inp.pack(side="left", fill="x", expand=True, padx=4, pady=5, ipady=1)
        self.inp.focus_set()
        self.inp.bind("<Return>", self._send)
        if is_bt:
            self.inp.configure(state="disabled")

        tk.Label(
            ib,
            text="BACKGROUND MANAGED | live log only" if is_bt else "ENTER send | empty=default",
            font=(FONT, 7), fg=DIM2, bg=BG2
        ).pack(side="right", padx=6)

        # Blink indicator
        self._blink = True
        def blink():
            if not hasattr(self, '_inp_lbl') or not self._inp_lbl.winfo_exists(): return
            if self._exec_is_running():
                self._blink = not self._blink
                self._inp_lbl.configure(bg=AMBER if self._blink else BG2, fg=BG if self._blink else AMBER)
            else:
                self._inp_lbl.configure(text=" DONE ", bg=DIM2, fg=DIM)
            self.after(500, blink)
        blink()

        # Print header
        self._p(f" {name}  {desc}  {datetime.now().strftime('%H:%M:%S')}\n", "a")
        self._p("─"*60 + "\n", "d")

        # Launch
        path = ROOT / script
        if not path.exists():
            self._p(f"ERROR: {path} not found\n", "r"); return

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"; env["PYTHONUTF8"] = "1"
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0

        try:
            if is_bt:
                proc_key = self._exec_script_to_proc_key(script)
                if proc_key is None:
                    self._p(f"FAILED: background mapping not found for {script}\n", "r")
                    return
                from core.proc import spawn
                info = spawn(proc_key, stdin_lines=auto_inputs or None,
                             cli_args=cli_args or None)
                if not info:
                    self._p(f"FAILED: {name} already running in background or could not start\n", "r")
                    self._p("Open TERMINAL > ENGINE LOGS to inspect existing managed runs.\n", "d")
                    return
                self._exec_managed_info = info
                self.h_stat.configure(text="BACKGROUND", fg=GREEN)
                self._p(f"  managed pid {info['pid']}  ·  background active\n", "g")
                self._p(f"  log {info['log_file']}\n", "d")
                threading.Thread(
                    target=self._read_managed_log,
                    args=(Path(info["log_file"]), info),
                    daemon=True,
                ).start()
                self._poll()
                return

            _cmd = [sys.executable, "-X", "utf8", "-u", str(path)]
            if cli_args:
                _cmd.extend(cli_args)
            self.proc = subprocess.Popen(
                _cmd, cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, env=env)
            threading.Thread(target=self._read, daemon=True).start()
            self._poll()

            # Auto-send configured inputs (from clickable config)
            if auto_inputs:
                def _auto():
                    time.sleep(0.8)
                    for val in auto_inputs:
                        if self.proc and self.proc.poll() is None and self.proc.stdin:
                            try:
                                self.proc.stdin.write(val + "\n")
                                self.proc.stdin.flush()
                                time.sleep(0.4)
                            except: break
                threading.Thread(target=_auto, daemon=True).start()

        except Exception as e:
            self._exec_progress_target = self._exec_progress_value
            if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                self._exec_stage_label.configure(text="launcher failed to start process")
            self._p(f"FAILED: {e}\n", "r")

    def _exec_script_to_proc_key(self, script: str) -> str | None:
        proc_by_key = {
            "citadel": "backtest",
            "jump": "mercurio",
            "bridgewater": "thoth",
            "deshaw": "newton",
            "millennium": "multi",
            "twosigma": "prometeu",
            "renaissance": "renaissance",
        }
        canon_key = canonical_engine_key(SCRIPT_TO_KEY.get(script.replace("\\", "/"), ""))
        return proc_by_key.get(canon_key)

    def _exec_is_running(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        info = getattr(self, "_exec_managed_info", None)
        if info:
            try:
                from core.proc import _is_alive
                return _is_alive(int(info["pid"]), expected=info)
            except Exception:
                return False
        return False

    def _exec_init_progress_ui(self, parent, name, desc):
        self._exec_progress_value = 2.0
        self._exec_progress_target = 7.0
        self._exec_progress_pulse = 0
        self._exec_recent_lines = []

        self._exec_progress_last_paint = 0.0
        self._exec_last_feed_at = 0.0

        wrap = tk.Frame(parent, bg=BG, padx=30, pady=26)
        wrap.pack(fill="both", expand=True)

        hdr = tk.Frame(wrap, bg=BG)
        hdr.pack(fill="x", pady=(0, 18))
        tk.Label(hdr, text=name.upper(), font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG).pack(anchor="w")
        tk.Label(hdr, text=f"{name}  ·  institutional build pipeline  ·  {desc}",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=(3, 0))
        tk.Label(hdr, text=desc,
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=(4, 0))

        top = tk.Frame(wrap, bg=BG)
        top.pack(fill="x", pady=(0, 12))

        left = tk.Frame(top, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True)

        left_head = tk.Frame(left, bg=PANEL)
        left_head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(left_head, text="BACKTEST", font=(FONT, 8, "bold"),
                 fg=BG, bg=AMBER, padx=6, pady=2).pack(side="left")
        self._exec_pct_label = tk.Label(left_head, text="2%", font=(FONT, 12, "bold"),
                                        fg=AMBER_B, bg=PANEL)
        self._exec_pct_label.pack(side="right")

        self._exec_stage_label = tk.Label(left, text="preparing backtest runtime",
                                          font=(FONT, 10, "bold"), fg=WHITE, bg=PANEL,
                                          anchor="w")
        self._exec_stage_label.pack(fill="x", padx=14)
        self._exec_file_label = tk.Label(left, text="waiting for first engine event",
                                         font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w")
        self._exec_file_label.pack(fill="x", padx=14, pady=(4, 8))

        self._exec_bar_canvas = tk.Canvas(left, bg=BG2, highlightthickness=0, height=34)
        self._exec_bar_canvas.pack(fill="x", padx=14, pady=(0, 12))

        hints = tk.Frame(left, bg=PANEL)
        hints.pack(fill="x", padx=14, pady=(0, 12))
        for lbl, txt, col in [
            ("route", "local subprocess attached to launcher runtime", AMBER_D),
            ("view",  "M visual map  ·  C cmd console", DIM),
            ("mode",  "no separate cmd pop-up during backtests", GREEN),
        ]:
            row = tk.Frame(hints, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=lbl.upper(), font=(FONT, 7, "bold"), fg=col, bg=PANEL,
                     width=8, anchor="w").pack(side="left")
            tk.Label(row, text=txt, font=(FONT, 7), fg=WHITE if lbl == "mode" else DIM,
                     bg=PANEL, anchor="w").pack(side="left")

        right = tk.Frame(top, bg=PANEL, width=220, highlightbackground=BORDER, highlightthickness=1)
        right.pack(side="left", fill="both", padx=(12, 0))
        right.pack_propagate(False)

        tk.Label(right, text="LIVE", font=(FONT, 8, "bold"),
                 fg=BG, bg=GREEN, padx=6, pady=2).pack(anchor="nw", padx=12, pady=(12, 8))
        self._exec_recent_labels = []
        for _ in range(2):
            lbl = tk.Label(right, text="",
                           font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w", justify="left",
                           wraplength=235)
            lbl.pack(fill="x", padx=12, pady=2)
            self._exec_recent_labels.append(lbl)

        note = tk.Frame(wrap, bg=BG)
        note.pack(fill="x")
        tk.Label(note, text="Visual by default. Open CMD only when needed.",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(anchor="w")
        actions = tk.Frame(note, bg=BG)
        actions.pack(anchor="w", pady=(8, 0))
        live_cmd = tk.Label(actions, text="  ABRIR CMD AO VIVO  ", font=(FONT, 8, "bold"),
                            fg=BG, bg=GREEN, cursor="hand2", padx=8, pady=4)
        live_cmd.pack(side="left")
        live_cmd.bind("<Button-1>", lambda e: self._exec_open_live_cmd())
        live_cmd.bind("<Enter>", lambda e: live_cmd.configure(bg="#36d86b"))
        live_cmd.bind("<Leave>", lambda e: live_cmd.configure(bg=GREEN))
        back_map = tk.Label(actions, text="  VOLTAR PRO MAPA  ", font=(FONT, 8),
                            fg=DIM, bg=BG3, cursor="hand2", padx=8, pady=4)
        back_map.pack(side="left", padx=(8, 0))
        back_map.bind("<Button-1>", lambda e: self._exec_show_view("visual"))
        back_map.bind("<Enter>", lambda e: back_map.configure(fg=AMBER))
        back_map.bind("<Leave>", lambda e: back_map.configure(fg=DIM))

        self._exec_progress_tick()

    def _exec_show_view(self, mode):
        self._exec_visual_mode = mode
        visual = getattr(self, "_exec_visual", None)
        console = getattr(self, "_exec_console", None)
        if visual is None or console is None:
            return
        visual.pack_forget()
        console.pack_forget()
        if mode == "console":
            console.pack(fill="both", expand=True)
            self.h_stat.configure(text="CMD VIEW", fg=AMBER_D)
        else:
            visual.pack(fill="both", expand=True)
            self.h_stat.configure(text="INSTALL MAP", fg=GREEN)

    def _exec_open_live_cmd(self):
        self._exec_show_view("console")
        if hasattr(self, "inp") and self.inp.winfo_exists():
            try:
                self.inp.focus_set()
            except Exception:
                pass

    def _exec_progress_feed(self, clean: str):
        low = clean.strip().lower()
        if not low:
            return

        targets = [
            (("iniciado", "started"), 10, "allocating launch package"),
            (("dados", "fetch", "loading"), 24, "downloading candle archives"),
            (("sentiment", "funding", "open interest", "long/short"), 40, "installing sentiment bundles"),
            (("scan", "scanning"), 58, "building route graph and trade cache"),
            (("total:", "resultados", "wr=", "pnl="), 74, "compiling execution manifests"),
            (("metricas", "metrics", "sharpe", "sortino"), 86, "verifying institutional metrics"),
            (("monte", "walk", "robust", "json"), 94, "packing report artifacts"),
            (("backtest complete", "loading results dashboard"), 100, "installation complete"),
        ]
        for keys, target, stage in targets:
            if any(k in low for k in keys):
                self._exec_progress_target = max(self._exec_progress_target, float(target))
                if self._exec_stage_label is not None:
                    self._exec_stage_label.configure(text=stage)
                break
        else:
            self._exec_progress_target = min(88.0, self._exec_progress_target + 0.2)

        if self._exec_file_label is not None:
            token = low.replace("  ", " ")[:56]
            self._exec_file_label.configure(text=token)

        now = time.monotonic()
        if now - getattr(self, "_exec_last_feed_at", 0.0) < 0.18:
            return
        self._exec_last_feed_at = now

        self._exec_recent_lines.append(clean.strip())
        self._exec_recent_lines = self._exec_recent_lines[-3:]
        tail = "  |  ".join(self._exec_recent_lines[-2:])
        live_lbl = getattr(self, "_exec_live_tail_label", None)
        if live_lbl is not None and live_lbl.winfo_exists():
            live_lbl.configure(text=tail[:180])

        if self._exec_recent_labels:
            first = self._exec_recent_labels[0]
            if first.winfo_exists():
                first.configure(text=tail[:80] or " ", fg=WHITE if tail else DIM)
            for lbl in self._exec_recent_labels[1:]:
                if lbl.winfo_exists():
                    lbl.configure(text=" ", fg=DIM)

    def _exec_progress_tick(self):
        canvas = getattr(self, "_exec_bar_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            self._exec_progress_after_id = None
            return

        if self._exec_is_running():
            self._exec_progress_value = min(
                self._exec_progress_target,
                self._exec_progress_value + max(0.4, (self._exec_progress_target - self._exec_progress_value) * 0.08)
            )
        elif self._exec_progress_target >= 100.0:
            self._exec_progress_value = 100.0
        elif self._exec_progress_value < self._exec_progress_target:
            self._exec_progress_value = min(
                self._exec_progress_target,
                self._exec_progress_value + max(0.8, (self._exec_progress_target - self._exec_progress_value) * 0.2)
            )
        now = time.monotonic()
        if now - getattr(self, "_exec_progress_last_paint", 0.0) < 0.12:
            self._exec_progress_after_id = self.after(120, self._exec_progress_tick)
            return
        self._exec_progress_last_paint = now

        self._exec_progress_pulse = (self._exec_progress_pulse + 5) % 300
        pct = max(0, min(100, int(round(self._exec_progress_value))))

        w = max(canvas.winfo_width(), 10)
        h = max(canvas.winfo_height(), 10)
        pad = 2
        bar_w = w - pad * 2
        fill_w = int(bar_w * (pct / 100))

        canvas.delete("all")
        canvas.create_rectangle(pad, pad, w - pad, h - pad, outline=BORDER, width=1, fill=BG2)
        if fill_w > 0:
            canvas.create_rectangle(pad + 1, pad + 1, pad + fill_w, h - pad - 1,
                                    outline="", fill=GREEN)
            shine_x = pad + (self._exec_progress_pulse % max(fill_w, 16))
            canvas.create_rectangle(max(pad + 1, shine_x - 6), pad + 1,
                                    min(pad + fill_w, shine_x + 6), h - pad - 1,
                                    outline="", fill=AMBER_B)

        if self._exec_pct_label is not None and self._exec_pct_label.winfo_exists():
            self._exec_pct_label.configure(text=f"{pct}%")

        if self._exec_is_running() or self._exec_progress_value < self._exec_progress_target:
            self._exec_progress_after_id = self.after(140, self._exec_progress_tick)
        else:
            self._exec_progress_after_id = None

    def _send(self, ev=None):
        t = self.inp.get(); self.inp.delete(0, "end")
        if self.proc and self.proc.poll() is None and self.proc.stdin:
            try:
                self.proc.stdin.write(t + "\n"); self.proc.stdin.flush()
                self._p(f"> {t}\n", "a")
            except: pass

    def _read(self):
        try:
            for line in iter(self.proc.stdout.readline, ""):
                if line: self.oq.put(line)
            self.proc.stdout.close()
        except: pass
        self.oq.put(None)

    def _read_managed_log(self, log_path: Path, info: dict):
        from core.proc import _is_alive

        last = 0
        while True:
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last)
                    chunk = f.read()
                    last = f.tell()
                if chunk:
                    for line in chunk.splitlines(True):
                        self.oq.put(line)
            except OSError:
                pass

            if not _is_alive(int(info["pid"]), expected=info):
                time.sleep(0.2)
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last)
                        chunk = f.read()
                    if chunk:
                        for line in chunk.splitlines(True):
                            self.oq.put(line)
                except OSError:
                    pass
                break
            time.sleep(0.15)

        self.oq.put(None)

    def _poll(self):
        try:
            for _ in range(32):
                line = self.oq.get_nowait()
                if line is None:
                    rc = self.proc.poll() if self.proc else -1
                    if self._exec_managed_info is not None:
                        rc = 0
                    self._exec_progress_target = 100.0
                    if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                        self._exec_stage_label.configure(
                            text="installation complete" if rc == 0 else f"installation failed  ·  exit {rc}"
                        )
                    self._p(f"\n{'─'*60}\n", "d")
                    self._p(f"  EXIT {rc}\n", "g" if rc == 0 else "r")
                    self.h_stat.configure(text="DONE" if rc == 0 else f"EXIT {rc}", fg=GREEN if rc == 0 else RED)
                    self.proc = None
                    self._exec_managed_info = None
                    # Show results dashboard for backtests
                    parent = getattr(self, '_exec_parent', 'main')
                    if parent == "backtest" and rc == 0:
                        self._p("\n  >> BACKTEST COMPLETE — loading results dashboard...\n", "a")
                        self.after(2000, lambda: self._try_results(parent))
                    return
                self._p(line)
        except queue.Empty: pass
        self.after(80 if self._exec_is_running() else 140, self._poll)

    def _p(self, text, tag="w"):
        import re
        # Strip ANSI escape codes for clean output
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        if hasattr(self, "con") and self.con.winfo_exists():
            self.con.configure(state="normal")
            self.con.insert("end", clean, tag)
            self.con.see("end")
            self.con.configure(state="disabled")
        if getattr(self, "_exec_visual", None) is not None:
            self._exec_progress_feed(clean)

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            self._exec_progress_target = max(self._exec_progress_target, self._exec_progress_value)
            if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                self._exec_stage_label.configure(text="operator stopped installation")
            self._p("\n  >> SIGTERM\n", "r")
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except: self.proc.kill()
            self._p("  >> STOPPED\n", "r")
            self.h_stat.configure(text="STOPPED", fg=RED)
            self.proc = None
        elif self._exec_managed_info is not None:
            self._exec_progress_target = max(self._exec_progress_target, self._exec_progress_value)
            if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                self._exec_stage_label.configure(text="operator stopped installation")
            try:
                from core.proc import stop_proc
                stop_proc(int(self._exec_managed_info["pid"]), expected=self._exec_managed_info)
                self._p(f"\n  >> BACKGROUND STOP {self._exec_managed_info['pid']}\n", "r")
            except Exception as e:
                self._p(f"\n  >> STOP FAILED: {e}\n", "r")
            self.h_stat.configure(text="STOPPED", fg=RED)
            self._exec_managed_info = None

    # ─── MARKETS (Layer 2) ───────────────────────────────
    def _markets(self):
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> MARKETS"); self.h_stat.configure(text="SELECT", fg=AMBER_D)
        self.f_lbl.configure(text="ESC return  |  ENTER keep current  |  H hub")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._kb("<Return>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell(
            "MARKETS",
            "Select active market routing and environment context",
        )

        for i, (mk, info) in enumerate(MARKETS.items()):
            num = i + 1
            is_active = mk == _conn.active_market
            avail = info["available"]
            row = tk.Frame(body, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=1)
            tk.Label(
                row, text=f" {num} ", font=(FONT, 9, "bold"),
                fg=BG, bg=AMBER if avail else DIM2, width=3
            ).pack(side="left")
            nl = tk.Label(
                row, text=f"  {info['label']}", font=(FONT, 10, "bold"),
                fg=AMBER if is_active else (WHITE if avail else DIM),
                bg=BG3, anchor="w", padx=6, pady=4, width=18
            )
            nl.pack(side="left")
            dl = tk.Label(
                row, text=info["desc"], font=(FONT, 8), fg=DIM,
                bg=BG3, anchor="w", padx=6, pady=4
            )
            dl.pack(side="left", fill="x", expand=True)

            if is_active:
                tk.Label(row, text=" ACTIVE ", font=(FONT, 7, "bold"),
                         fg=BG, bg=GREEN, padx=4).pack(side="right", padx=4)
            elif not avail:
                tk.Label(row, text=" COMING SOON ", font=(FONT, 7),
                         fg=DIM, bg=BG2, padx=4).pack(side="right", padx=4)

            if avail:
                def sel_market(event=None, k=mk):
                    _conn.active_market = k
                    if k == "crypto_futures":
                        self._crypto_dashboard()
                    else:
                        self._markets()  # refresh
                for w in [row, nl, dl]:
                    w.bind("<Button-1>", sel_market)
                    w.bind("<Enter>", lambda e, n=nl: n.configure(fg=AMBER))
                    w.bind("<Leave>", lambda e, n=nl, a=is_active: n.configure(fg=AMBER if a else WHITE))
                self._kb(f"<Key-{num}>", sel_market)
            else:
                def show_coming(event=None, label=info["label"]):
                    self.h_stat.configure(text=f"{label} | COMING SOON", fg=AMBER_D)
                for w in [row, nl, dl]:
                    w.bind("<Button-1>", show_coming)
                self._kb(f"<Key-{num}>", show_coming)

        tk.Frame(body, bg=BG, height=12).pack()
        current_label = MARKETS.get(_conn.active_market, {}).get("label", "?")
        tk.Label(body, text=f"Current market: {current_label}",
                 font=(FONT, 9, "bold"), fg=AMBER, bg=BG).pack(anchor="w")
        tk.Label(body, text="[enter] keep current    [0] return",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=(4, 0))

    # ─── CONNECTIONS (Layer 2) ────────────────────────────
    def _connections(self):
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> CONNECTIONS"); self.h_stat.configure(text="ROUTING", fg=GREEN)
        self.f_lbl.configure(text="ESC return  |  number select  |  H hub")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell(
            "CONNECTIONS",
            "Exchange, broker, data-provider and notification endpoints",
        )
        panel = self._ui_panel_frame(
            body,
            "ACCESS MATRIX",
            "Configured services and setup entry points",
        )

        sections = [
            ("CRYPTO EXCHANGES", [
                ("1", "binance_futures", "Binance Futures"),
                ("2", "binance_spot", "Binance Spot"),
                ("3", "bybit", "Bybit"),
                ("4", "okx", "OKX"),
                ("5", "hyperliquid", "Hyperliquid"),
                ("6", "gate", "Gate.io"),
            ]),
            ("BROKERS", [
                ("7", "mt5", "MetaTrader 5 — Forex, CFDs, Indices"),
                ("8", "ib", "Interactive Brokers — Equities, Options"),
                ("9", "alpaca", "Alpaca — Commission-free US equities"),
            ]),
            ("DATA PROVIDERS", [
                ("A", "coinglass", "CoinGlass — OI, liquidations"),
                ("B", "glassnode", "Glassnode — on-chain"),
                ("C", "cftc", "CFTC COT — public API (no key)"),
                ("D", "fred", "FRED — macro data (no key)"),
                ("E", "yahoo", "Yahoo Finance — equities (no key)"),
            ]),
            ("NOTIFICATIONS", [
                ("T", "telegram", "Telegram Bot"),
                ("W", "discord", "Discord Webhook"),
            ]),
        ]

        # Scrollable
        canvas = tk.Canvas(panel, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=(0, 14))
        sb.pack(side="right", fill="y", padx=(0, 14), pady=(0, 14))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        for section_name, items in sections:
            sec = self._ui_section(sf, section_name)

            for key_label, provider, desc in items:
                conn = _conn.get(provider)
                is_conn = conn.get("connected", False)
                is_public = conn.get("public", False)

                if is_conn:
                    tag = "PUBLIC API" if is_public else "CONNECTED"
                    tag_fg = BG
                    tag_bg = GREEN
                else:
                    tag = "OFFLINE"
                    tag_fg = DIM
                    tag_bg = BG2
                # Click handler — only binance_futures and telegram are actionable
                if provider == "binance_futures":
                    cmd = lambda: self._cfg_keys()
                elif provider == "telegram":
                    cmd = lambda: self._cfg_tg()
                else:
                    def _coming(event=None, d=desc):
                        self.h_stat.configure(text=f"{d} — setup coming soon", fg=AMBER_D)
                    cmd = _coming

                self._ui_action_row(
                    sec, key_label, provider.upper(), desc,
                    command=cmd,
                    tag=tag, tag_fg=tag_fg, tag_bg=tag_bg, title_width=20,
                )

        # Visible BACK row at the bottom of the scrollable list
        self._ui_back_row(sf, lambda: self._menu("main"))

    # ─── ARBITRAGE (Layer 2) ──────────────────────────────
    def _alchemy_enter(self):
        """Render the ARBITRAGE cockpit inside the launcher main frame."""
        self._clr()
        self._clear_kb()
        self.history.append("main")

        # Initialize state reader + tick driver
        self._alch_state = AlchemyState(stale_seconds=10)
        self._alch_tick = alchemy_ui.TickDriver(self, interval_ms=2000)
        self._alch_log_buf = []
        self._alch_engine_mode = None

        # Load fonts
        alchemy_ui.load_fonts(self)

        # Paint cockpit in-terminal (inside self.main)
        alchemy_ui.render_cockpit(self)

        self.bind("<Escape>", self._alchemy_exit)
        try:
            self.h_path.configure(text="ARBITRAGE")
            self.h_stat.configure(text="HEV ONLINE", fg=alchemy_ui.HEV_AMBER_B)
        except Exception:
            pass

        # Start the tick
        self._alch_tick.start(lambda: self._alch_state.read())

    def _alchemy_exit(self, event=None):
        """Exit the cockpit. Confirm if engine is running."""
        if self.proc and self.proc.poll() is None:
            from tkinter import messagebox
            if not messagebox.askyesno(
                "ARBITRAGE",
                "Engine is still running. Stop it before exiting?",
                parent=self):
                return
            self._stop()

        try:
            self._alch_tick.stop()
        except Exception:
            pass
        try:
            self.unbind("<Escape>")
        except Exception:
            pass

        self._menu("main")

    # ═══════════════════════════════════════════════════════════════
    # ARBITRAGE HUB — MP3-style router
    # Five legs of funding/basis arbitrage, one minimalist menu:
    #   C  CEX ↔ CEX  → JANE STREET cockpit (execution)
    #   D  DEX ↔ DEX  → funding scanner (observation)
    #   X  CEX ↔ DEX  → funding scanner (observation)
    #   B  BASIS TRADE → spot-perp basis screen
    #   S  SPOT ↔ SPOT → cross-venue spot spread screen
    # ═══════════════════════════════════════════════════════════════
    _ARB_HUB_ITEMS = [
        ("C", "CEX  \u2194  CEX",
         "jane street execution cockpit",
         "_alchemy_enter"),
        ("D", "DEX  \u2194  DEX",
         "pure cross-dex funding spread",
         ("_funding_scanner_screen", "dex-dex")),
        ("X", "CEX  \u2194  DEX",
         "cex/dex spread  \u2014  biggest apr",
         ("_funding_scanner_screen", "cex-dex")),
        ("B", "BASIS  TRADE",
         "spot-perp basis  \u00b7  execution ready",
         "_arb_basis_screen"),
        ("S", "SPOT  \u2194  SPOT",
         "cross-venue spot spread",
         "_arb_spot_screen"),
    ]

    def _arbitrage_hub(self):
        """HL2 + Bloomberg minimalist hub: 5 clickable rows with live data.

        Rows: CEX-CEX (Jane Street execution), DEX-DEX (scanner),
        CEX-DEX (scanner), BASIS TRADE (spot-perp), SPOT-SPOT (spread).
        Click or C/D/X/B/S keyboard shortcuts. Hover highlights the row.
        ESC returns to the main menu.
        """
        self._clr(); self._clear_kb()
        self.history.append("main")
        self.h_path.configure(text="> ARBITRAGE DESK")
        self.h_stat.configure(text="HUB", fg=AMBER_D)
        self.f_lbl.configure(
            text="click row  |  C D X B S direct  |  \u2191\u2193 ENTER  |  ESC back"
        )
        self._kb("<Escape>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, outer = self._ui_page_shell(
            "ARBITRAGE DESK",
            "Funding, basis and spread routing across execution and scanner modes",
        )

        # ── Header bar (minimal: section label + clock) ──
        header = tk.Frame(outer, bg=BG, height=24)
        header.pack(fill="x", pady=(0, 6))
        header.pack_propagate(False)
        tk.Label(header, text="ROUTER",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG).pack(side="left")
        self._arb_hub_clock = tk.Label(header, text="",
                                        font=(FONT, 8),
                                        fg=DIM, bg=BG)
        self._arb_hub_clock.pack(side="right")
        try:
            self._arb_hub_clock.configure(
                text=datetime.now().strftime("%H:%M:%S  UTC"))
        except Exception:
            pass

        # ── Title block ──
        title_frame = tk.Frame(outer, bg=BG)
        title_frame.pack(fill="x", pady=(40, 0))
        tk.Label(title_frame, text="A R B I T R A G E",
                 font=(FONT, 18, "bold"), fg=AMBER, bg=BG).pack()
        tk.Frame(title_frame, bg=AMBER_D, height=1, width=220).pack(pady=(4, 4))
        tk.Label(title_frame, text="funding  \u00b7  basis  \u00b7  spread",
                 font=(FONT, 8), fg=DIM, bg=BG).pack()

        # ── Rows area ──
        summary = tk.Frame(outer, bg=BG)
        summary.pack(fill="x", pady=(0, 10))
        self._arb_hub_sum_cex = tk.Label(summary, text="CEX  OFFLINE", font=(FONT, 8, "bold"),
                                         fg=AMBER_D, bg=BG, anchor="w")
        self._arb_hub_sum_cex.pack(side="left")
        self._arb_hub_sum_dex = tk.Label(summary, text="DEX  OFFLINE", font=(FONT, 8),
                                         fg=DIM, bg=BG, anchor="w")
        self._arb_hub_sum_dex.pack(side="left", padx=(20, 0))
        self._arb_hub_sum_best = tk.Label(summary, text="TOP APR  WAITING", font=(FONT, 8),
                                          fg=DIM, bg=BG, anchor="w")
        self._arb_hub_sum_best.pack(side="left", padx=(20, 0))
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 10))

        rows_frame = tk.Frame(outer, bg=BG)
        rows_frame.pack(fill="x", pady=(8, 0), padx=28)

        self._arb_hub_idx = 0
        self._arb_hub_row_widgets: list[dict] = []

        # Row definitions — match self._ARB_HUB_ITEMS order
        exec_sec = self._ui_section(rows_frame, "EXECUTION", note="operator-routed")
        scan_sec = self._ui_section(rows_frame, "SCANNERS", note="observation and research")
        row_defs = [
            (exec_sec, "CEX  \u2194  CEX", "JANE ST",    "execution  \u00b7  \u2014"),
            (scan_sec, "DEX  \u2194  DEX", "\u2014 VENUES", "observation  \u00b7  \u2014"),
            (scan_sec, "CEX  \u2194  DEX", "\u2014 VENUES", "observation  \u00b7  \u2014"),
            (scan_sec, "BASIS TRADE", "SPOT\u21c4PERP", "spot-perp basis  \u00b7  \u2014"),
            (scan_sec, "SPOT  \u2194  SPOT", "2 VENUES", "spot spread  \u00b7  \u2014"),
        ]

        for i, (parent, big_label, meta, sub) in enumerate(row_defs):
            row_frame = tk.Frame(parent, bg=BG, cursor="hand2", height=62)
            row_frame.pack(fill="x", pady=(0, 6))
            row_frame.pack_propagate(False)

            top_line = tk.Frame(row_frame, bg=BG)
            top_line.pack(fill="x", pady=(8, 0))

            bullet_lbl = tk.Label(top_line, text=str(i + 1),
                                  font=(FONT, 8, "bold"),
                                  fg=AMBER_D, bg=BG, width=3, anchor="w")
            bullet_lbl.pack(side="left")

            label_lbl = tk.Label(top_line, text=big_label,
                                 font=(FONT, 11, "bold"),
                                 fg=WHITE, bg=BG, anchor="w")
            label_lbl.pack(side="left", padx=(2, 0))

            meta_lbl = tk.Label(top_line, text=meta,
                                font=(FONT, 8, "bold"),
                                fg=AMBER_D, bg=BG, anchor="e")
            meta_lbl.pack(side="right", padx=(0, 8))

            sub_lbl = tk.Label(row_frame, text=sub,
                               font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
            sub_lbl.pack(fill="x", padx=(28, 8), pady=(4, 0))
            tk.Frame(row_frame, bg=DIM2, height=1).pack(fill="x", side="bottom", pady=(6, 0))

            widgets = {
                "frame":  row_frame,
                "top":    top_line,
                "bullet": bullet_lbl,
                "label":  label_lbl,
                "meta":   meta_lbl,
                "sub":    sub_lbl,
            }
            self._arb_hub_row_widgets.append(widgets)

            # Bind hover + click on frame AND all child labels
            targets = (row_frame, top_line, bullet_lbl, label_lbl, meta_lbl, sub_lbl)
            for t in targets:
                t.bind("<Enter>",    lambda _e, _i=i: self._arb_hub_hover_enter(_i))
                t.bind("<Leave>",    lambda _e, _i=i: self._arb_hub_hover_leave(_i))
                t.bind("<Button-1>", lambda _e, _i=i: self._arb_hub_pick(_i))

        # ── Keyboard shortcuts (preserved) ──
        self._kb("<Key-c>", lambda: self._arb_hub_pick(0))
        self._kb("<Key-d>", lambda: self._arb_hub_pick(1))
        self._kb("<Key-x>", lambda: self._arb_hub_pick(2))
        self._kb("<Key-b>", lambda: self._arb_hub_pick(3))
        self._kb("<Key-s>", lambda: self._arb_hub_pick(4))
        self._kb("<Up>",    lambda: self._arb_hub_move(-1))
        self._kb("<Down>",  lambda: self._arb_hub_move(1))
        self._kb("<Return>", lambda: self._arb_hub_pick(self._arb_hub_idx))
        self._kb("<space>",  lambda: self._arb_hub_pick(self._arb_hub_idx))

        self._arb_hub_repaint()

        # ── Footer hint ──
        footer = tk.Frame(outer, bg=BG)
        footer.pack(fill="x", pady=(12, 0))
        tk.Label(footer,
                 text="execution and scanner routes  \u00b7  C D X B S direct  \u00b7  ESC back",
                 font=(FONT, 7), fg=DIM2, bg=BG).pack(anchor="w", pady=(6, 0))

        # ── Kick off async scan for live data ──
        self._arb_hub_scan_async()

    def _arb_hub_move(self, delta: int):
        rows = getattr(self, "_arb_hub_row_widgets", None)
        if not rows:
            return
        self._arb_hub_idx = (self._arb_hub_idx + delta) % len(rows)
        self._arb_hub_repaint()

    def _arb_hub_repaint(self):
        """Repaint all 3 rows based on self._arb_hub_idx (keyboard cursor)."""
        rows = getattr(self, "_arb_hub_row_widgets", None) or []
        for i, w in enumerate(rows):
            if i == self._arb_hub_idx:
                w["frame"].configure(bg=BG3)
                w["top"].configure(bg=BG3)
                w["bullet"].configure(fg=AMBER, bg=BG3)
                w["label"].configure(fg=AMBER, bg=BG3)
                w["meta"].configure(fg=AMBER, bg=BG3)
                w["sub"].configure(fg=AMBER_D, bg=BG3)
            else:
                w["frame"].configure(bg=BG)
                w["top"].configure(bg=BG)
                w["bullet"].configure(fg=AMBER_D, bg=BG)
                w["label"].configure(fg=WHITE, bg=BG)
                w["meta"].configure(fg=AMBER_D, bg=BG)
                w["sub"].configure(fg=DIM, bg=BG)

    def _arb_hub_hover_enter(self, idx: int) -> None:
        """Mouse hover enters row idx — same visual as keyboard focus."""
        if not (0 <= idx < len(getattr(self, "_arb_hub_row_widgets", []))):
            return
        self._arb_hub_idx = idx
        self._arb_hub_repaint()

    def _arb_hub_hover_leave(self, idx: int) -> None:
        """Mouse hover leaves row idx — no-op.

        Cursor stays on last-hovered row (Bloomberg-style). If the user
        enters another row, that row's <Enter> fires and repaints.
        """
        pass

    def _arb_hub_pick(self, idx: int):
        if idx < 0 or idx >= len(self._ARB_HUB_ITEMS):
            return
        target = self._ARB_HUB_ITEMS[idx][3]
        if isinstance(target, tuple):
            method, arg = target
            getattr(self, method)(arg)
        else:
            getattr(self, target)()

    # ── Background scan: populates telemetry strip without blocking Tk ─
    def _arb_hub_scan_async(self):
        """Kick off a funding_scanner.scan() in a daemon thread, then
        marshal the result back to the UI via self.after(0, ...).

        The scanner itself is cached (CACHE_TTL) so hitting the hub
        repeatedly doesn't hammer venue APIs.
        """
        import threading
        try:
            from core.funding_scanner import FundingScanner
        except Exception as e:
            rows = getattr(self, "_arb_hub_row_widgets", None)
            if rows:
                rows[0]["sub"].configure(
                    text=f"scanner unavailable: {str(e)[:40]}", fg=RED)
            return
        scanner = getattr(self, "_funding_scanner", None)
        if scanner is None:
            scanner = FundingScanner()
            self._funding_scanner = scanner

        def _worker():
            try:
                opps = scanner.scan()
                stats = scanner.stats()
                arb_dd = scanner.arb_pairs(mode="dex-dex", min_spread_apr=5.0)
                arb_cd = scanner.arb_pairs(mode="cex-dex", min_spread_apr=5.0)
                # snapshot top signed APR across all
                top = opps[0] if opps else None
                self.after(0, lambda: self._arb_hub_telem_update(
                    stats, top, arb_dd, arb_cd))
            except Exception as e:
                def _fail(err=e):
                    rs = getattr(self, "_arb_hub_row_widgets", None)
                    if rs:
                        try:
                            rs[0]["sub"].configure(
                                text=f"scan failed: {str(err)[:40]}", fg=RED)
                        except Exception:
                            pass
                self.after(0, _fail)

        threading.Thread(target=_worker, daemon=True).start()

    def _arb_hub_telem_update(self, stats, top, arb_dd, arb_cd):
        """Populate the 5 hub rows with live data from the scanner.

        stats: dict with dex_online, cex_online, total from FundingScanner.stats()
        top:   FundingOpp or None — single best observation across all venues
        arb_dd: list of dex-dex spread pairs from scanner.arb_pairs("dex-dex")
        arb_cd: list of cex-dex spread pairs from scanner.arb_pairs("cex-dex")
        Rows 3-4 (BASIS TRADE, SPOT-SPOT) are updated separately via
        scanner.basis_pairs() / scanner.spot_arb_pairs() when available.
        """
        rows = getattr(self, "_arb_hub_row_widgets", None)
        if not rows:
            return
        try:
            dex_on = stats.get("dex_online", 0)
            cex_on = stats.get("cex_online", 0)
            if hasattr(self, "_arb_hub_sum_cex"):
                self._arb_hub_sum_cex.configure(text=f"CEX  {cex_on}")
            if hasattr(self, "_arb_hub_sum_dex"):
                self._arb_hub_sum_dex.configure(text=f"DEX  {dex_on}")

            # Row 0 — CEX ↔ CEX (Jane Street execution)
            top_s = "\u2014"
            if top is not None and getattr(top, "apr", None) is not None:
                try:
                    top_s = f"top {float(top.apr):+.1f}%"
                except Exception:
                    top_s = "\u2014"
            if hasattr(self, "_arb_hub_sum_best"):
                self._arb_hub_sum_best.configure(text=f"TOP APR  {top_s}")
            rows[0]["meta"].configure(text="JANE ST")
            rows[0]["sub"].configure(
                text=f"execution  \u00b7  {top_s}  \u00b7  24 pairs")

            # Row 1 — DEX ↔ DEX
            rows[1]["meta"].configure(text=f"{dex_on} VENUES")
            if arb_dd:
                a = arb_dd[0]
                try:
                    best_s = f"best {float(a.get('net_apr', 0)):+.1f}%"
                    venue_s = str(a.get("long_venue") or a.get("short_venue") or "\u2014")
                except Exception:
                    best_s = "\u2014"
                    venue_s = "\u2014"
                rows[1]["sub"].configure(
                    text=f"observation  \u00b7  {best_s}  \u00b7  {venue_s}")
            else:
                rows[1]["sub"].configure(
                    text="observation  \u00b7  \u2014  \u00b7  \u2014")

            # Row 2 — CEX ↔ DEX
            rows[2]["meta"].configure(text=f"{dex_on + cex_on} VENUES")
            if arb_cd:
                a = arb_cd[0]
                try:
                    best_s = f"best {float(a.get('net_apr', 0)):+.1f}%"
                    venue_s = str(a.get("long_venue") or a.get("short_venue") or "\u2014")
                except Exception:
                    best_s = "\u2014"
                    venue_s = "\u2014"
                rows[2]["sub"].configure(
                    text=f"observation  \u00b7  {best_s}  \u00b7  {venue_s}")
            else:
                rows[2]["sub"].configure(
                    text="observation  \u00b7  \u2014  \u00b7  \u2014")

            # ── Semaphore bullets (best score per category) ──────
            from core.arb_scoring import score_opp, score_batch
            GREEN_SEM = "#00ff41"

            # Row 0 — CEX-CEX: score the top opp if available
            if top is not None:
                top_d = top.to_dict() if hasattr(top, "to_dict") else {
                    "symbol": getattr(top, "symbol", ""),
                    "venue": getattr(top, "venue", ""),
                    "apr": getattr(top, "apr", 0),
                    "volume_24h": getattr(top, "volume_24h", 0),
                    "open_interest": getattr(top, "open_interest", 0),
                    "risk": getattr(top, "risk", "HIGH"),
                }
                cex_sc = score_opp(top_d)
                if cex_sc.grade == "GO":
                    rows[0]["bullet"].configure(fg=GREEN_SEM)
                elif cex_sc.grade == "MAYBE":
                    rows[0]["bullet"].configure(fg=AMBER)
                else:
                    rows[0]["bullet"].configure(fg=DIM)

            # Row 1 — DEX-DEX
            if arb_dd:
                dd_scores = score_batch(arb_dd)
                best_dd = max(dd_scores, key=lambda s: s.score)
                if best_dd.grade == "GO":
                    rows[1]["bullet"].configure(fg=GREEN_SEM)
                elif best_dd.grade == "MAYBE":
                    rows[1]["bullet"].configure(fg=AMBER)
                else:
                    rows[1]["bullet"].configure(fg=DIM)

            # Row 2 — CEX-DEX
            if arb_cd:
                cd_scores = score_batch(arb_cd)
                best_cd = max(cd_scores, key=lambda s: s.score)
                if best_cd.grade == "GO":
                    rows[2]["bullet"].configure(fg=GREEN_SEM)
                elif best_cd.grade == "MAYBE":
                    rows[2]["bullet"].configure(fg=AMBER)
                else:
                    rows[2]["bullet"].configure(fg=DIM)
        except Exception:
            pass

        # Row 3 — BASIS TRADE (spot-perp)
        try:
            if hasattr(self, "_funding_scanner") and self._funding_scanner:
                bp = self._funding_scanner.basis_pairs(min_basis_bps=5)
                if bp:
                    best = bp[0]
                    rows[3]["sub"].configure(
                        text=f"spot-perp basis  \u00b7  {best['symbol']} {best['basis_bps']:+.0f}bps  \u00b7  {best['venue_perp']}")
                    rows[3]["meta"].configure(text=f"{len(bp)} PAIRS")
        except Exception:
            pass

        # Row 4 — SPOT ↔ SPOT
        try:
            if hasattr(self, "_funding_scanner") and self._funding_scanner:
                sp = self._funding_scanner.spot_arb_pairs(min_spread_bps=3)
                if sp:
                    best = sp[0]
                    rows[4]["sub"].configure(
                        text=f"spot spread  \u00b7  {best['symbol']} {best['spread_bps']:.0f}bps  \u00b7  {best['venue_a']}\u21c4{best['venue_b']}")
                    rows[4]["meta"].configure(text=f"{len(sp)} PAIRS")
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════
    # BASIS TRADE SCREEN — spot-perp basis opportunities
    # ═══════════════════════════════════════════════════════════════
    def _arb_basis_screen(self):
        """Spot-perp basis trade screen — shows basis opportunities."""
        self._clr(); self._clear_kb()
        self.history.append("_arbitrage_hub")
        self.h_path.configure(text="> ARBITRAGE > BASIS TRADE")
        self.h_stat.configure(text="SCANNING\u2026", fg=AMBER_D)
        self.f_lbl.configure(text="R refresh  |  ESC back")

        self._kb("<Escape>", lambda: self._arbitrage_hub())
        self._kb("<Key-r>", lambda: self._arb_basis_screen())
        self._bind_global_nav()

        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=12)

        tk.Label(outer, text="B A S I S    T R A D E", font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG).pack(anchor="center")
        tk.Label(outer, text="spot-perp basis  \u00b7  buy spot, short perp",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="center", pady=(1, 4))
        tk.Frame(outer, bg=AMBER_D, height=1).pack(fill="x", pady=(6, 4))

        # Table
        cols = [("#", 3, "e"), ("SYMBOL", 8, "w"), ("PERP", 10, "w"),
                ("SPOT", 10, "w"), ("MARK", 10, "e"), ("SPOT$", 10, "e"),
                ("BASIS", 8, "e"), ("APR", 8, "e")]
        hrow = tk.Frame(outer, bg=BG); hrow.pack(fill="x")
        for label, w, anchor in cols:
            tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=w, anchor=anchor).pack(side="left")
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="both", expand=True)

        # Fetch basis pairs in background
        import threading
        def _worker():
            try:
                from core.funding_scanner import FundingScanner
                scanner = getattr(self, "_funding_scanner", None)
                if scanner is None:
                    scanner = FundingScanner()
                    self._funding_scanner = scanner
                scanner.scan()
                scanner.scan_spot()
                pairs = scanner.basis_pairs(min_basis_bps=5)[:20]
                self.after(0, lambda: self._arb_basis_paint(inner, cols, pairs))
            except Exception as e:
                self.after(0, lambda: tk.Label(inner,
                    text=f"  scan failed: {e}", font=(FONT, 8), fg=RED, bg=BG).pack())
        threading.Thread(target=_worker, daemon=True).start()

    def _arb_basis_paint(self, inner, cols, pairs):
        for w in inner.winfo_children():
            w.destroy()
        try:
            self.h_stat.configure(text=f"{len(pairs)} BASIS", fg=AMBER)
        except Exception:
            pass
        if not pairs:
            tk.Label(inner, text="  \u2014 no basis opportunities above 5bps \u2014",
                     font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)
            return
        for i, p in enumerate(pairs, 1):
            bg = BG if i % 2 == 1 else BG2
            rf = tk.Frame(inner, bg=bg); rf.pack(fill="x")
            basis_fg = GREEN if abs(p["basis_bps"]) >= 20 else (AMBER if abs(p["basis_bps"]) >= 10 else DIM)
            cells = [
                (f"{i:>3}", DIM), (p["symbol"], WHITE),
                (p["venue_perp"], AMBER_D), (p["venue_spot"], AMBER_D),
                (f"${p['mark_price']:,.2f}", DIM),
                (f"${p['spot_price']:,.2f}", DIM),
                (f"{p['basis_bps']:+.0f}bps", basis_fg),
                (f"{p['basis_apr']:.0f}%", basis_fg),
            ]
            for (txt, fg), (_, w, anchor) in zip(cells, cols):
                tk.Label(rf, text=txt, font=(FONT, 8), fg=fg, bg=bg,
                         width=w, anchor=anchor).pack(side="left")

    # ═══════════════════════════════════════════════════════════════
    # SPOT ↔ SPOT SCREEN — cross-venue spot price divergence
    # ═══════════════════════════════════════════════════════════════
    def _arb_spot_screen(self):
        """Spot-spot spread screen — cross-venue spot price divergence."""
        self._clr(); self._clear_kb()
        self.history.append("_arbitrage_hub")
        self.h_path.configure(text="> ARBITRAGE > SPOT \u2194 SPOT")
        self.h_stat.configure(text="SCANNING\u2026", fg=AMBER_D)
        self.f_lbl.configure(text="R refresh  |  ESC back")

        self._kb("<Escape>", lambda: self._arbitrage_hub())
        self._kb("<Key-r>", lambda: self._arb_spot_screen())
        self._bind_global_nav()

        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=12)

        tk.Label(outer, text="S P O T    S P R E A D", font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG).pack(anchor="center")
        tk.Label(outer, text="cross-venue spot price divergence",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="center", pady=(1, 4))
        tk.Frame(outer, bg=AMBER_D, height=1).pack(fill="x", pady=(6, 4))

        cols = [("#", 3, "e"), ("SYMBOL", 8, "w"), ("VENUE A", 10, "w"),
                ("VENUE B", 10, "w"), ("PRICE A", 12, "e"), ("PRICE B", 12, "e"),
                ("SPREAD", 10, "e")]
        hrow = tk.Frame(outer, bg=BG); hrow.pack(fill="x")
        for label, w, anchor in cols:
            tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=w, anchor=anchor).pack(side="left")
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="both", expand=True)

        import threading
        def _worker():
            try:
                from core.funding_scanner import FundingScanner
                scanner = getattr(self, "_funding_scanner", None)
                if scanner is None:
                    scanner = FundingScanner()
                    self._funding_scanner = scanner
                scanner.scan_spot()
                pairs = scanner.spot_arb_pairs(min_spread_bps=3)[:20]
                self.after(0, lambda: self._arb_spot_paint(inner, cols, pairs))
            except Exception as e:
                self.after(0, lambda: tk.Label(inner,
                    text=f"  scan failed: {e}", font=(FONT, 8), fg=RED, bg=BG).pack())
        threading.Thread(target=_worker, daemon=True).start()

    def _arb_spot_paint(self, inner, cols, pairs):
        for w in inner.winfo_children():
            w.destroy()
        try:
            self.h_stat.configure(text=f"{len(pairs)} SPREADS", fg=AMBER)
        except Exception:
            pass
        if not pairs:
            tk.Label(inner, text="  \u2014 no spot spreads above 3bps \u2014",
                     font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)
            return
        for i, p in enumerate(pairs, 1):
            bg = BG if i % 2 == 1 else BG2
            rf = tk.Frame(inner, bg=bg); rf.pack(fill="x")
            spread_fg = GREEN if p["spread_bps"] >= 15 else (AMBER if p["spread_bps"] >= 8 else DIM)
            cells = [
                (f"{i:>3}", DIM), (p["symbol"], WHITE),
                (p["venue_a"], AMBER_D), (p["venue_b"], AMBER_D),
                (f"${p['price_a']:,.4f}", DIM), (f"${p['price_b']:,.4f}", DIM),
                (f"{p['spread_bps']:.1f}bps", spread_fg),
            ]
            for (txt, fg), (_, w, anchor) in zip(cells, cols):
                tk.Label(rf, text=txt, font=(FONT, 8), fg=fg, bg=bg,
                         width=w, anchor=anchor).pack(side="left")

    # ═══════════════════════════════════════════════════════════════
    # FUNDING SCANNER SCREEN — shared between DEX-DEX and CEX-DEX modes
    # ═══════════════════════════════════════════════════════════════
    def _funding_scanner_screen(self, mode: str = "dex-dex"):
        """Live cross-venue funding rate observer.

        mode:
            "dex-dex"  — show only DEX opps, arb pairs filtered to DEX-DEX
            "cex-dex"  — show top of everything, arb pairs require mix

        Layout is intentionally LCD/MP3-player minimal: monochrome amber,
        one thin divider per section, no heavy borders. Auto-refresh every
        60 seconds via self.after; manual refresh with R. Scan runs in a
        background thread so the Tk loop never blocks.
        """
        assert mode in ("dex-dex", "cex-dex")
        self._clr(); self._clear_kb()
        self._funding_alive = True
        self._funding_mode = mode

        if mode == "dex-dex":
            title_text = "D E X    F U N D I N G"
            subtitle = "pure cross-dex  \u00b7  hyperliquid  \u00b7  dydx  \u00b7  paradex"
            self.h_path.configure(text="> ARBITRAGE > DEX\u2194DEX")
        else:
            title_text = "C E X    \u2194    D E X    S P R E A D"
            subtitle = "cex/dex funding differential  \u00b7  biggest historical apr"
            self.h_path.configure(text="> ARBITRAGE > CEX\u2194DEX")

        self.h_stat.configure(text="SCANNING\u2026", fg=AMBER_D)
        self.f_lbl.configure(
            text="R refresh  |  C jane  |  D dex\u2194dex  |  X cex\u2194dex  |  ESC back"
        )

        self._kb("<Escape>", lambda: self._arbitrage_hub())
        self._kb("<Key-r>", lambda: self._funding_refresh(force=True))
        self._kb("<Key-c>", lambda: self._alchemy_enter())
        self._kb("<Key-d>", lambda: self._funding_scanner_screen("dex-dex"))
        self._kb("<Key-x>", lambda: self._funding_scanner_screen("cex-dex"))
        self._kb("<Key-f>", lambda: self._funding_filter_toggle())
        self._bind_global_nav()

        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=12)

        # ── Title block ─────────────────────────────────────────
        tk.Label(outer, text=title_text, font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG).pack(anchor="center")
        tk.Label(outer, text=subtitle, font=(FONT, 7),
                 fg=DIM, bg=BG).pack(anchor="center", pady=(1, 4))

        self._funding_meta = tk.Label(
            outer, text="  last scan \u2014\u2014  \u00b7  \u2014 venues  ",
            font=(FONT, 7), fg=DIM2, bg=BG)
        self._funding_meta.pack(anchor="center")

        tk.Frame(outer, bg=AMBER_D, height=1).pack(fill="x", pady=(6, 4))

        # ── Filter bar ──────────────────────────────────────────
        try:
            from config.params import ARB_FILTER_DEFAULTS
        except (ImportError, AttributeError):
            ARB_FILTER_DEFAULTS = {
                "min_apr": 20.0, "min_volume": 500_000,
                "min_oi": 0, "risk_max": "HIGH", "grade_min": "SKIP",
            }
        if not hasattr(self, "_arb_filters"):
            self._arb_filters = dict(ARB_FILTER_DEFAULTS)

        _APR_OPTS    = [5, 10, 20, 50, 100]
        _VOL_OPTS    = [0, 100_000, 500_000, 1_000_000, 5_000_000]
        _OI_OPTS     = [0, 50_000, 100_000, 500_000, 1_000_000]
        _RISK_OPTS   = ["HIGH", "MED", "LOW"]
        _GRADE_OPTS  = ["SKIP", "MAYBE", "GO"]

        def _fmt_filter(key, val):
            if key == "min_apr":
                return f"APR \u2265{int(val)}%"
            if key == "min_volume":
                if val == 0:
                    return "VOL \u2265OFF"
                if val >= 1_000_000:
                    return f"VOL \u2265{int(val/1_000_000)}M"
                return f"VOL \u2265{int(val/1_000)}K"
            if key == "min_oi":
                if val == 0:
                    return "OI \u2265OFF"
                if val >= 1_000_000:
                    return f"OI \u2265{int(val/1_000_000)}M"
                return f"OI \u2265{int(val/1_000)}K"
            if key == "risk_max":
                return f"RISK \u2264{val}"
            if key == "grade_min":
                return f"GRADE \u2265{val}"
            return f"{key}={val}"

        def _cycle_filter(key, opts):
            cur = self._arb_filters.get(key)
            try:
                idx = opts.index(cur)
            except ValueError:
                idx = 0
            nxt = opts[(idx + 1) % len(opts)]
            self._arb_filters[key] = nxt
            lbl = self._arb_filter_labels.get(key)
            if lbl:
                lbl.configure(text=_fmt_filter(key, nxt))
            self._funding_repaint_filtered()

        fbar = tk.Frame(outer, bg=BG2)
        fbar.pack(fill="x", pady=(0, 3))
        self._funding_filter_bar = fbar

        self._arb_filter_labels = {}
        _filter_defs = [
            ("min_apr",    _APR_OPTS),
            ("min_volume", _VOL_OPTS),
            ("min_oi",     _OI_OPTS),
            ("risk_max",   _RISK_OPTS),
            ("grade_min",  _GRADE_OPTS),
        ]
        for fkey, fopts in _filter_defs:
            cur_val = self._arb_filters.get(fkey)
            lbl = tk.Label(
                fbar, text=_fmt_filter(fkey, cur_val),
                font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG2,
                cursor="hand2", padx=6,
            )
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda e, k=fkey, o=fopts: _cycle_filter(k, o))
            self._arb_filter_labels[fkey] = lbl

        tk.Label(fbar, text="F:toggle", font=(FONT, 6), fg=DIM2, bg=BG2,
                 padx=4).pack(side="right")

        # ── Table header ────────────────────────────────────────
        cols = [
            ("#",       3,  "e"),
            ("SYMBOL",  10, "w"),
            ("VENUE",   12, "w"),
            ("TYPE",    4,  "w"),
            ("RATE",    12, "e"),
            ("APR",     9,  "e"),
            ("VOL",     10, "e"),
            ("RISK",    5,  "w"),
            ("SCORE",   10, "w"),
        ]
        hrow = tk.Frame(outer, bg=BG); hrow.pack(fill="x")
        for label, w, anchor in cols:
            tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=w, anchor=anchor).pack(side="left")
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        # ── Scrollable row container ────────────────────────────
        table_wrap = tk.Frame(outer, bg=BG, height=280)
        table_wrap.pack(fill="both", expand=False)
        table_wrap.pack_propagate(False)

        canvas = tk.Canvas(table_wrap, bg=BG, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(table_wrap, orient="vertical",
                              command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))

        def _on_wheel(event, c=canvas):
            try: c.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError: pass
        canvas.bind("<Enter>",
                    lambda e, c=canvas: c.bind_all("<MouseWheel>", _on_wheel))
        canvas.bind("<Leave>",
                    lambda e, c=canvas: c.unbind_all("<MouseWheel>"))

        self._funding_table_inner = inner
        self._funding_cols = cols

        # ── Arb spreads strip ───────────────────────────────────
        tk.Frame(outer, bg=AMBER_D, height=1).pack(fill="x", pady=(8, 4))
        tk.Label(outer, text="\u25ba  ARB  SPREADS  (same symbol, venues diverging)",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(
                     fill="x")
        self._funding_arb_frame = tk.Frame(outer, bg=BG)
        self._funding_arb_frame.pack(fill="x", pady=(2, 0))

        # ── First load ──────────────────────────────────────────
        self._funding_refresh(force=False)

    def _funding_refresh(self, force: bool = False):
        """Fire a background scan and repaint on completion."""
        if not getattr(self, "_funding_alive", False):
            return
        import threading
        from core.funding_scanner import FundingScanner

        scanner = getattr(self, "_funding_scanner", None)
        if scanner is None:
            scanner = FundingScanner()
            self._funding_scanner = scanner

        try:
            self.h_stat.configure(text="SCANNING\u2026", fg=AMBER_D)
        except Exception:
            pass

        mode = getattr(self, "_funding_mode", "dex-dex")

        def _worker():
            try:
                scanner.scan(force=force)
                stats = scanner.stats()
                if mode == "dex-dex":
                    rows = scanner.top(n=40, min_apr=5.0, venue_type="DEX")
                else:
                    rows = scanner.top(n=40, min_apr=20.0)
                arb = scanner.arb_pairs(mode=mode, min_spread_apr=5.0)[:5]
                # fire optional telegram alerts for the biggest opps
                try:
                    from core.funding_scanner import maybe_alert_telegram
                    maybe_alert_telegram(rows, apr_threshold=100.0)
                except Exception:
                    pass
                self.after(0, lambda: self._funding_paint(rows, arb, stats))
            except Exception as e:
                self.after(0, lambda: self._funding_fail(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

        # schedule next auto-refresh (60s) — only once per screen
        if not getattr(self, "_funding_timer_armed", False):
            self._funding_timer_armed = True
            def _tick():
                if not getattr(self, "_funding_alive", False):
                    return
                self._funding_refresh(force=False)
                try:
                    self.after(60_000, _tick)
                except tk.TclError:
                    pass
            self.after(60_000, _tick)

    def _funding_paint(self, rows, arb, stats):
        from datetime import datetime
        if not getattr(self, "_funding_alive", False):
            return
        inner = getattr(self, "_funding_table_inner", None)
        if inner is None:
            return

        # cache for filter repaint
        self._funding_cached = (rows, arb, stats)

        # ── Scoring & filtering ──────────────────────────────────
        try:
            from core.arb_scoring import score_opp, score_batch
            _scoring_ok = True
        except Exception:
            _scoring_ok = False

        filters = getattr(self, "_arb_filters", None)

        # Build score list for all rows (parallel)
        row_scores = None
        if _scoring_ok:
            try:
                opp_dicts = [o.to_dict() for o in rows]
                row_scores = score_batch(opp_dicts)
            except Exception:
                row_scores = None

        # Apply filters
        if filters and rows:
            _RISK_ORDER  = {"LOW": 0, "MED": 1, "HIGH": 2}
            _GRADE_ORDER = {"GO": 0, "MAYBE": 1, "SKIP": 2}
            risk_max_ord  = _RISK_ORDER.get(filters.get("risk_max", "HIGH"), 2)
            grade_min_ord = _GRADE_ORDER.get(filters.get("grade_min", "SKIP"), 2)
            min_apr    = filters.get("min_apr", 0)
            min_volume = filters.get("min_volume", 0)
            min_oi     = filters.get("min_oi", 0)

            filtered_rows   = []
            filtered_scores = []
            for idx, o in enumerate(rows):
                if abs(o.apr) < min_apr:
                    continue
                if min_volume and o.volume_24h < min_volume:
                    continue
                if min_oi and o.open_interest < min_oi:
                    continue
                if _RISK_ORDER.get(o.risk, 2) < risk_max_ord:
                    # row risk is stricter than allowed max — include it
                    pass
                elif _RISK_ORDER.get(o.risk, 2) > risk_max_ord:
                    continue
                sr = row_scores[idx] if row_scores else None
                if sr is not None:
                    if _GRADE_ORDER.get(sr.grade, 2) > grade_min_ord:
                        continue
                filtered_rows.append(o)
                filtered_scores.append(sr)
            rows      = filtered_rows
            row_scores = filtered_scores

        # rebuild rows
        for w in inner.winfo_children():
            w.destroy()

        for i, o in enumerate(rows, 1):
            bg = BG if i % 2 == 1 else BG2
            rf = tk.Frame(inner, bg=bg)
            rf.pack(fill="x")

            # APR color classes
            apr_abs = abs(o.apr)
            if apr_abs >= 100:
                apr_fg = GREEN
            elif apr_abs >= 50:
                apr_fg = AMBER
            else:
                apr_fg = DIM
            risk_fg = RED if o.risk == "HIGH" else (AMBER_D if o.risk == "MED" else DIM)
            sym_fg = WHITE
            venue_fg = AMBER_D

            # SCORE cell
            sr = row_scores[i - 1] if row_scores else None
            if sr is not None:
                sc = int(sr.score)
                if sr.grade == "GO":
                    score_txt = f"\u2588\u2588 {sc:>2} GO"
                    score_fg  = GREEN
                elif sr.grade == "MAYBE":
                    score_txt = f"\u2588\u2591 {sc:>2} MAYBE"
                    score_fg  = AMBER
                else:
                    score_txt = f"\u2591\u2591 {sc:>2} SKIP"
                    score_fg  = DIM2
            else:
                score_txt = ""
                score_fg  = DIM2

            cells = [
                (f"{i:>3}", DIM),
                (o.symbol, sym_fg),
                (o.venue, venue_fg),
                (o.venue_type, DIM2),
                (f"{o.rate*100:+.3f}%/{o.interval_h:.0f}h", DIM),
                (f"{o.apr:+.0f}%", apr_fg),
                (f"${o.volume_24h/1e6:.1f}M", DIM),
                (o.risk, risk_fg),
                (score_txt, score_fg),
            ]
            for (txt, fg), (_lbl, w, anchor) in zip(cells, self._funding_cols):
                tk.Label(rf, text=txt, font=(FONT, 8),
                         fg=fg, bg=bg, width=w, anchor=anchor).pack(side="left")

        if not rows:
            tk.Label(inner, text="  \u2014 no opportunities above threshold \u2014  ",
                     font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)

        # arb pairs strip
        arb_frame = getattr(self, "_funding_arb_frame", None)
        if arb_frame:
            for w in arb_frame.winfo_children():
                w.destroy()
            if arb:
                for a in arb:
                    # score arb pair
                    arb_score_tag = ""
                    if _scoring_ok:
                        try:
                            asr = score_opp(a)
                            if asr.grade == "GO":
                                arb_score_tag = f"  \u2588\u2588{int(asr.score):>2}GO"
                            elif asr.grade == "MAYBE":
                                arb_score_tag = f"  \u2588\u2591{int(asr.score):>2}MAYBE"
                            else:
                                arb_score_tag = f"  \u2591\u2591{int(asr.score):>2}SKIP"
                        except Exception:
                            arb_score_tag = ""
                    line = (
                        f"   {a['symbol']:8s}  "
                        f"SHORT {a['short_venue']:<11s} ({a['short_apr']:+6.1f}%)  "
                        f"\u2192  "
                        f"LONG {a['long_venue']:<11s} ({a['long_apr']:+6.1f}%)  "
                        f"net {a['net_apr']:+6.0f}%"
                        f"{arb_score_tag}"
                    )
                    net_fg = GREEN if abs(a["net_apr"]) >= 50 else AMBER
                    tk.Label(arb_frame, text=line, font=(FONT, 8),
                             fg=net_fg, bg=BG, anchor="w").pack(fill="x")
            else:
                tk.Label(arb_frame,
                         text="   \u2014 no cross-venue spreads above 5% APR \u2014",
                         font=(FONT, 8), fg=DIM2, bg=BG, anchor="w").pack(fill="x")

        # meta strip
        try:
            now = datetime.now().strftime("%H:%M:%S")
            total = stats.get("total", 0)
            dex_on = stats.get("dex_online", 0)
            cex_on = stats.get("cex_online", 0)
            errs = stats.get("errors") or {}
            err_tag = f"  \u00b7  {len(errs)} failed" if errs else ""
            self._funding_meta.configure(
                text=f"  last scan {now}  \u00b7  "
                     f"{dex_on} dex  {cex_on} cex  "
                     f"\u00b7  {total} perps{err_tag}  ",
                fg=DIM,
            )
            self.h_stat.configure(text="LIVE", fg=GREEN)
        except Exception:
            pass

    def _funding_fail(self, reason: str):
        if not getattr(self, "_funding_alive", False):
            return
        try:
            self.h_stat.configure(text="SCAN FAILED", fg=RED)
            meta = getattr(self, "_funding_meta", None)
            if meta:
                meta.configure(text=f"  scan failed: {reason[:80]}  ", fg=RED)
        except Exception:
            pass

    def _funding_repaint_filtered(self):
        """Re-run _funding_paint with cached data (called on filter change)."""
        cached = getattr(self, "_funding_cached", None)
        if cached is None:
            return
        rows, arb, stats = cached
        self._funding_paint(rows, arb, stats)

    def _funding_filter_toggle(self):
        """Toggle filter bar visibility (bound to F key)."""
        fbar = getattr(self, "_funding_filter_bar", None)
        if fbar is None:
            return
        try:
            if fbar.winfo_ismapped():
                fbar.pack_forget()
            else:
                fbar.pack(fill="x", pady=(0, 3))
        except tk.TclError:
            pass

    # ─── TERMINAL (Layer 2) ───────────────────────────────
    def _terminal(self):
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> TERMINAL"); self.h_stat.configure(text="DATA", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  H hub  |  S strategies")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell("TERMINAL", "Data, charts and research routing")
        panel = self._ui_panel_frame(body, "RESEARCH ROUTER", "Available and planned market intelligence modules")

        sections = [
            ("MARKET DATA", [
                ("1", "Price Monitor",       "Watchlist ao vivo com múltiplos TFs", False),
                ("2", "Orderbook Depth",     "L2 data, bid/ask heatmap", False),
                ("3", "Funding Rates",       "Cross-exchange funding comparison", False),
                ("4", "Liquidation Map",     "Estimated liquidation levels", False),
            ]),
            ("MACRO & FUNDAMENTAL", [
                ("5", "COT Report",          "CFTC Commitment of Traders", False),
                ("6", "Economic Calendar",   "Fed, CPI, PMI, NFP, FOMC", False),
                ("7", "Macro Dashboard",     "DXY, yields, M2, fear & greed", False),
                ("8", "Token Fundamentals",  "TVL, supply, unlocks, revenue", False),
            ]),
            ("RESEARCH", [
                ("9", "Correlation Matrix",  "Cross-asset correlation radar", False),
                ("A", "Regime Detector",     "Current market regime (HMM/GARCH)", False),
                ("B", "Seasonality",         "Hour/day/month patterns", False),
            ]),
            ("LOCAL DATA", [
                ("D", "Reports & Logs",      "Browse backtest reports", True),
                ("P", "Processes",           "Manage running engines", True),
            ]),
        ]

        for section_name, items in sections:
            sec = self._ui_section(panel, section_name)

            for key_label, name, desc, available in items:
                tag = None if available else "COMING SOON"

                if name == "Reports & Logs":
                    cmd = lambda: self._data()
                elif name == "Processes":
                    cmd = lambda: self._procs()
                elif available:
                    cmd = lambda n=name: self.h_stat.configure(text=f"{n}", fg=AMBER_D)
                else:
                    cmd = lambda n=name: self.h_stat.configure(text=f"{n} — COMING SOON", fg=DIM)

                self._ui_action_row(
                    sec, key_label, name, desc,
                    command=cmd,
                    available=available, tag=tag, tag_fg=DIM, tag_bg=BG2, title_width=22,
                )

        self._ui_back_row(panel, lambda: self._menu("main"))

    # ─── DATA CENTER (hub) ─────────────────────────────────
    def _data_center(self):
        """Unified entry point for everything data: backtest metrics,
        running/finished engine logs, and raw report files.

        The hub has three cards. Each card opens a focused screen:

          BACKTESTS  →  crypto-futures dashboard routed to its Backtest tab
                        (reuses _dash_backtest_render + detail panel with
                        OPEN HTML / DELETE buttons).
          ENGINE LOGS → _data_engines (new screen with proc list +
                        live log tail streaming).
          REPORTS    →  legacy _data raw JSON/log file browser.
        """
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> DATA")
        self.h_stat.configure(text="CENTER", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  B backtests  |  E engines  |  R reports  |  X export")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell(
            "DATA CENTER",
            "Backtests, engine logs, reports and export surfaces",
        )
        panel = self._ui_panel_frame(body, "DATA ROUTING", "Primary storage and review workflows")

        # Quick counts for each card so the user sees signal, not just titles.
        bt_count = self._data_count_backtests()
        eng_running, eng_total = self._data_count_procs()
        rep_count = self._data_count_reports()
        summary = tk.Frame(panel, bg=BG)
        summary.pack(fill="x", pady=(0, 10))
        tk.Label(summary, text=f"RUNS  {bt_count}", font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG).pack(side="left")
        tk.Label(summary, text=f"ENGINES  {eng_running}/{eng_total}", font=(FONT, 8),
                 fg=DIM, bg=BG).pack(side="left", padx=(18, 0))
        tk.Label(summary, text=f"FILES  {rep_count}", font=(FONT, 8),
                 fg=DIM, bg=BG).pack(side="left", padx=(18, 0))
        tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", pady=(0, 10))
        self._ui_note(
            panel,
            "Use DATA as the review desk: validated runs first, raw artifacts second, export only when sending outside the terminal.",
            fg=DIM,
        )

        sections = [
            ("PRIMARY ROUTES", [
                ("B", "BACKTESTS", "validated runs, metrics and run-level inspection",
                 f"{bt_count} runs on disk", lambda: self._data_backtests()),
                ("E", "ENGINE LOGS", "running and recent engines with live tail",
                 f"{eng_running} running · {eng_total} total", lambda: self._data_engines()),
            ]),
            ("ARTIFACTS", [
                ("R", "REPORT INDEX", "raw JSON and persisted report artifact browser",
                 f"{rep_count} files indexed", lambda: self._data()),
            ]),
            ("EXTERNAL REVIEW", [
                ("X", "EXPORT ANALYSIS", "single-file snapshot for external analysis workflows",
                 "< 2 MB JSON", lambda: self._export_analysis()),
            ]),
        ]

        for section_name, items in sections:
            sec = self._ui_section(panel, section_name)
            for key_label, name, desc, stat, cmd in items:
                row, name_lbl, desc_lbl = self._ui_action_row(
                    sec, key_label, name, desc,
                    command=cmd,
                    title_width=20,
                    tag=stat,
                    tag_fg=AMBER_D,
                    tag_bg=BG,
                )
                for w in (row, name_lbl, desc_lbl):
                    w.bind("<Enter>", lambda e, n=name_lbl: n.configure(fg=AMBER))
                    w.bind("<Leave>", lambda e, n=name_lbl: n.configure(fg=WHITE))

                key_bind = f"<Key-{key_label.lower()}>"
                self._kb(key_bind, cmd)

        self._ui_back_row(panel, lambda: self._menu("main"))

    # ── Counts used by the DATA CENTER cards ──────────────────
    def _data_count_backtests(self) -> int:
        try:
            runs_dir = ROOT / "data" / "runs"
            if runs_dir.exists():
                return sum(1 for d in runs_dir.iterdir() if d.is_dir())
        except OSError:
            pass
        return 0

    def _data_count_procs(self) -> tuple[int, int]:
        try:
            from core.proc import list_procs
            procs = list_procs()
            running = sum(1 for p in procs if p.get("alive"))
            return running, len(procs)
        except Exception:
            return 0, 0

    def _data_count_reports(self) -> int:
        total = 0
        try:
            dd = ROOT / "data"
            if not dd.exists():
                return 0
            for sub in ("runs", "darwin", "arbitrage",
                        "mercurio", "newton", "thoth",
                        "prometeu", "multistrategy", "live"):
                p = dd / sub
                if p.exists():
                    total += sum(1 for _ in p.rglob("*.json"))
        except OSError:
            pass
        return total

    # ─── DATA > EXPORT ANALYSIS (single-file snapshot) ────────
    def _export_analysis(self):
        """Generate a single-file analysis snapshot for external review.

        Runs the aggregation off the Tk main thread because walking
        ``data/runs`` on a populated OneDrive mirror can take a couple
        of seconds. The status bar reflects progress/result; on success
        we also copy the absolute path to the clipboard so the user can
        just Ctrl+V into a Claude.ai upload dialog.
        """
        import threading
        from datetime import datetime
        try:
            self.h_stat.configure(text="GERANDO EXPORT...", fg=AMBER_D)
        except Exception:
            pass

        def _worker():
            try:
                from core.analysis_export import export_analysis
                ts = datetime.now().strftime("%Y-%m-%d_%H%M")
                out_dir = ROOT / "data" / "exports"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"analysis_{ts}.json"
                export_analysis(output_path=out_path)
                try:
                    size_mb = out_path.stat().st_size / (1024 * 1024)
                except Exception:
                    size_mb = 0.0
                self.after(0, lambda: self._export_analysis_done(out_path, size_mb))
            except Exception as e:
                self.after(0, lambda: self._export_analysis_failed(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _export_analysis_done(self, out_path, size_mb: float):
        try:
            self.h_stat.configure(
                text=f"EXPORT OK · {size_mb:.2f} MB",
                fg=AMBER,
            )
        except Exception:
            pass
        # Best-effort clipboard copy of the absolute path.
        try:
            self.clipboard_clear()
            self.clipboard_append(str(out_path))
        except Exception:
            pass
        try:
            from tkinter import messagebox
            messagebox.showinfo(
                "Analysis Export",
                f"Arquivo gerado ({size_mb:.2f} MB):\n\n{out_path}\n\n"
                "Caminho copiado pro clipboard. "
                "Anexa no Claude.ai e pede pra analisar.",
            )
        except Exception:
            pass

    def _export_analysis_failed(self, reason: str):
        try:
            self.h_stat.configure(text="EXPORT FALHOU", fg=AMBER_D)
        except Exception:
            pass
        try:
            from tkinter import messagebox
            messagebox.showerror("Analysis Export", f"Falhou:\n\n{reason}")
        except Exception:
            pass

    def _open_backtest_metrics(self):
        """Legacy shortcut: jump to the crypto-futures dashboard > Backtest tab.

        Kept for any code path that still wants the tabbed dashboard view.
        The new primary entry for DATA > BACKTESTS is the standalone
        _data_backtests screen — same list, same detail panel, same DELETE
        button, but decoupled from Markets > Crypto Futures navigation.
        """
        self._crypto_dashboard()
        self.after(0, lambda: self._dash_render_tab("backtest"))

    # ─── DATA > BACKTESTS (standalone) ────────────────────────
    def _data_backtests(self):
        """Standalone backtest browser, decoupled from the crypto-futures tab.

        Reuses the existing dashboard rendering functions
        (_dash_backtest_render, _dash_backtest_select, _dash_backtest_delete)
        by registering the local widgets into self._dash_widgets under the
        same keys the dashboard uses. Zero code duplication — the click
        handlers, detail panel, and DELETE button already work against
        (bt_list, bt_count, bt_detail) keys.

        Reached from DATA CENTER > BACKTESTS (or keyboard B at the hub).
        """
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> DATA > BACKTESTS")
        self.h_stat.configure(text="BROWSE", fg=AMBER_D)
        self.f_lbl.configure(
            text="ESC voltar  |  click run for details  |  DELETE to remove")
        self._kb("<Escape>", lambda: self._data_center())

        # Ensure _dash_widgets exists — the standalone screen owns this
        # instance attr when it's used outside the dashboard build path.
        self._dash_widgets = getattr(self, "_dash_widgets", {})

        _outer, outer = self._ui_page_shell(
            "BACKTEST RUNS",
            "Indexed historical runs reconciled against data/index.json",
        )
        hdr = tk.Frame(outer, bg=BG); hdr.pack(fill="x")
        count_l = tk.Label(hdr, text="", font=(FONT, 8), fg=DIM, bg=BG)
        count_l.pack(side="right")
        self._dash_widgets[("bt_count",)] = count_l
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(4, 10))

        split = tk.Frame(outer, bg=BG)
        split.pack(fill="both", expand=True)

        # ── LEFT: run list ──
        left = tk.Frame(split, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        hrow = tk.Frame(left, bg=BG); hrow.pack(fill="x")
        for label, width in _BT_COLS:
            tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=width, anchor="w").pack(side="left")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        # Scrollable inner frame for the row list
        canvas_wrap = tk.Frame(left, bg=BG); canvas_wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_wrap, bg=BG, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(canvas_wrap, orient="vertical",
                              command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e, c=canvas: c.configure(scrollregion=c.bbox("all")))

        # Mouse wheel — scoped to the list (not bind_all, which would leak)
        def _on_wheel(event, c=canvas):
            try: c.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError: pass
        def _enter(_e=None, c=canvas):
            c.bind_all("<MouseWheel>", _on_wheel)
        def _leave(_e=None, c=canvas):
            try: c.unbind_all("<MouseWheel>")
            except tk.TclError: pass
        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)
        inner.bind("<Enter>", _enter)
        inner.bind("<Leave>", _leave)

        self._dash_widgets[("bt_list",)] = inner
        self._dash_widgets[("bt_canvas",)] = canvas

        # ── RIGHT: detail panel ──
        right = tk.Frame(split, bg=PANEL, width=340)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        tk.Label(right, text="DETAILS", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(anchor="nw",
                                                        padx=10, pady=(10, 4))
        tk.Frame(right, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))

        # Scrollable inner area — metric blocks (PERFORMANCE/TRADES/CONFIG)
        # can overflow the panel height on smaller windows. Wrapping the
        # detail body in a Canvas + Scrollbar lets the content grow without
        # clipping, while the "[ DETAILS ]" badge above stays pinned.
        scroll_wrap = tk.Frame(right, bg=PANEL)
        scroll_wrap.pack(fill="both", expand=True, padx=6, pady=(2, 6))

        d_canvas = tk.Canvas(scroll_wrap, bg=PANEL, bd=0,
                             highlightthickness=0)
        d_scroll = tk.Scrollbar(scroll_wrap, orient="vertical",
                                command=d_canvas.yview)
        d_canvas.configure(yscrollcommand=d_scroll.set)
        d_canvas.pack(side="left", fill="both", expand=True)
        d_scroll.pack(side="right", fill="y")

        detail_body = tk.Frame(d_canvas, bg=PANEL)
        d_canvas.create_window((0, 0), window=detail_body, anchor="nw",
                               width=300)
        detail_body.bind("<Configure>",
                         lambda e, c=d_canvas:
                         c.configure(scrollregion=c.bbox("all")))

        def _on_dwheel(event, c=d_canvas):
            try: c.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError: pass
        def _d_enter(_e=None, c=d_canvas):
            c.bind_all("<MouseWheel>", _on_dwheel)
        def _d_leave(_e=None, c=d_canvas):
            try: c.unbind_all("<MouseWheel>")
            except tk.TclError: pass
        d_canvas.bind("<Enter>", _d_enter)
        d_canvas.bind("<Leave>", _d_leave)
        detail_body.bind("<Enter>", _d_enter)
        detail_body.bind("<Leave>", _d_leave)

        self._dash_widgets[("bt_detail",)] = detail_body

        # Placeholder — overwritten by auto-select below when the index
        # has any runs. Kept as a fallback for the empty-index case.
        tk.Label(detail_body,
                 text="\n  click any run on the left\n  to load metrics + actions",
                 font=(FONT, 9, "bold"), fg=AMBER_D, bg=PANEL,
                 justify="left").pack(anchor="w")

        # Bottom bar: back + jump to engine logs
        tk.Frame(outer, bg=BG, height=10).pack()
        bottom = tk.Frame(outer, bg=BG); bottom.pack(fill="x")

        back_btn = tk.Label(bottom, text="  VOLTAR  ",
                            font=(FONT, 9), fg=DIM, bg=BG,
                            cursor="hand2", padx=10, pady=3)
        back_btn.pack(side="left")
        back_btn.bind("<Button-1>", lambda e: self._data_center())
        back_btn.bind("<Enter>", lambda e: back_btn.configure(fg=AMBER))
        back_btn.bind("<Leave>", lambda e: back_btn.configure(fg=DIM))

        eng_btn = tk.Label(bottom, text="  ENGINE LOGS  ",
                           font=(FONT, 9, "bold"), fg=AMBER_D, bg=BG,
                           cursor="hand2", padx=10, pady=3)
        eng_btn.pack(side="left", padx=(6, 0))
        eng_btn.bind("<Button-1>", lambda e: self._data_engines())
        eng_btn.bind("<Enter>", lambda e: eng_btn.configure(fg=AMBER))
        eng_btn.bind("<Leave>", lambda e: eng_btn.configure(fg=AMBER_D))

        # Trigger the initial render — this reads data/index.json, sorts
        # by timestamp desc, renders up to 50 rows with click handlers.
        self._dash_backtest_render()

        # Auto-select the most recent run so the detail panel is never
        # empty on first open. The user was getting confused when the
        # only visible thing in the right pane was "[ DETAILS ]" plus a
        # dim placeholder — it looked like nothing clickable existed.
        # With auto-select the detail panel always shows real metrics,
        # OPEN HTML + DELETE buttons immediately. Clicking other rows
        # still swaps the selection as before.
        try:
            newest = getattr(self, "_bt_recent_run_id", None)
            if newest:
                self.after(0, lambda rid=newest:
                           self._dash_backtest_select(rid))
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    # ─── ENGINE LOGS (live proc list + log tail) ──────────────
    def _data_engines(self):
        """Live engine control & log tail view.

        Implements part of Fase 2 from the professional-fund-readiness plan:
        two-column layout with a proc list on the left (auto-refresh 2s) and
        a live log tail stream on the right for the currently selected proc.

        Backed by core.proc.list_procs (identity-aware, safe against PID
        recycling) and stop_proc (raises PidRecycledError on mismatch rather
        than taskkilling the wrong process).
        """
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> DATA > ENGINES")
        self.h_stat.configure(text="LIVE", fg=GREEN)
        self.f_lbl.configure(text="ESC voltar  |  click proc to tail  |  STOP / PURGE")
        self._kb("<Escape>", lambda: self._data_center())

        # State for this screen — held as instance attrs so the worker thread
        # and the UI poll can reach them. Cleaned up on screen exit.
        self._eng_selected_pid: int | None = None
        self._eng_tail_stop: threading.Event = threading.Event()
        self._eng_tail_thread: threading.Thread | None = None
        self._eng_log_queue: queue.Queue = queue.Queue()
        self._eng_after_id: str | None = None

        _outer, outer = self._ui_page_shell(
            "ENGINE LOGS",
            "Running and recent engines with live log tail and verified stop control",
        )

        split = tk.Frame(outer, bg=BG)
        split.pack(fill="both", expand=True)

        # ── LEFT: proc list ──────────────────────────────────
        left = tk.Frame(split, bg=BG, width=420)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)

        tk.Label(left, text="PROCS", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=BG, anchor="w").pack(anchor="w", pady=(0, 4))

        hrow = tk.Frame(left, bg=BG); hrow.pack(fill="x")
        for label, width in [("STATE", 7), ("ENGINE", 10), ("PID", 7),
                             ("STARTED", 12)]:
            tk.Label(hrow, text=label, font=(FONT, 7, "bold"), fg=DIM, bg=BG,
                     width=width, anchor="w").pack(side="left")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        list_wrap = tk.Frame(left, bg=BG)
        list_wrap.pack(fill="both", expand=True)
        self._eng_list_wrap = list_wrap

        # Bottom action bar for the list
        actions_l = tk.Frame(left, bg=BG); actions_l.pack(fill="x", pady=(6, 0))

        def _do_stop():
            pid = self._eng_selected_pid
            if pid is None:
                self.h_stat.configure(text="NO PROC SELECTED", fg=RED)
                self.after(1200, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
                return
            try:
                from core.proc import stop_proc, PidRecycledError
                ok = stop_proc(pid)
                msg = f"STOPPED {pid}" if ok else f"{pid} NOT RUNNING"
                self.h_stat.configure(text=msg, fg=GREEN if ok else AMBER_D)
            except PidRecycledError as e:
                self.h_stat.configure(text=f"REFUSED: PID REUSE", fg=RED)
                messagebox.showerror("PID recycling detected",
                                     f"stop_proc refused:\n\n{e}")
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            self._eng_refresh()

        def _do_purge():
            try:
                from core.proc import purge_finished
                n = purge_finished()
                self.h_stat.configure(text=f"PURGED {n}", fg=AMBER)
            except Exception as e:
                self.h_stat.configure(text=f"PURGE FAILED: {str(e)[:30]}", fg=RED)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            self._eng_refresh()

        # SPAWN dropdown — needs a popup menu rather than a simple onclick
        # because the user picks an engine from a list. Attaches a Tk.Menu
        # populated from core.proc.ENGINES at click time.
        def _do_spawn(engine_name: str):
            try:
                from core.proc import spawn
                info = spawn(engine_name)
            except Exception as e:
                self.h_stat.configure(
                    text=f"SPAWN ERR: {str(e)[:30]}", fg=RED)
                info = None
            if info:
                self.h_stat.configure(
                    text=f"SPAWNED {engine_name} pid={info['pid']}",
                    fg=GREEN)
                # Auto-select the newly-spawned proc so its log tail
                # immediately starts streaming.
                self.after(300, lambda p=info: self._eng_select(p))
            else:
                self.h_stat.configure(
                    text=f"SPAWN FAILED: {engine_name}", fg=RED)
            self.after(2000,
                       lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            self._eng_refresh()

        try:
            from core.proc import ENGINES as _ENGINES
        except Exception:
            _ENGINES = {}
        spawn_menu = tk.Menu(actions_l, tearoff=0,
                             bg=BG3, fg=AMBER,
                             activebackground=AMBER, activeforeground=BG,
                             font=(FONT, 8))
        try:
            from config.params import FROZEN_ENGINES as _FROZEN
        except Exception:
            _FROZEN = []
        for eng_name in sorted(_ENGINES.keys()):
            _frozen = eng_name.upper() in [f.upper() for f in _FROZEN]
            _label  = f"{eng_name.upper()} [FROZEN]" if _frozen else eng_name.upper()
            _fg     = DIM if _frozen else AMBER
            spawn_menu.add_command(
                label=_label,
                foreground=_fg,
                command=lambda n=eng_name: _do_spawn(n))

        def _popup_spawn(event, m=spawn_menu):
            try:
                m.tk_popup(event.x_root, event.y_root)
            finally:
                m.grab_release()

        spawn_btn = tk.Label(actions_l, text="  SPAWN ▸  ",
                             font=(FONT, 7, "bold"),
                             fg=GREEN, bg=BG3, cursor="hand2",
                             padx=6, pady=3)
        spawn_btn.pack(side="left", padx=(0, 6))
        spawn_btn.bind("<Button-1>", _popup_spawn)
        spawn_btn.bind("<Enter>", lambda e: spawn_btn.configure(bg=GREEN, fg=BG))
        spawn_btn.bind("<Leave>", lambda e: spawn_btn.configure(bg=BG3, fg=GREEN))

        for label, cmd, color in [
                ("STOP",  _do_stop,  RED),
                ("PURGE", _do_purge, AMBER_D),
                ("REFRESH", lambda: self._eng_refresh(), AMBER)]:
            b = tk.Label(actions_l, text=f"  {label}  ", font=(FONT, 7, "bold"),
                         fg=color, bg=BG3, cursor="hand2", padx=6, pady=3)
            b.pack(side="left", padx=2)
            b.bind("<Button-1>", lambda e, c=cmd: c())

        # ── RIGHT: log tail viewer ───────────────────────────
        right = tk.Frame(split, bg=PANEL)
        right.pack(side="right", fill="both", expand=True)

        tk.Label(right, text="LOG TAIL", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(anchor="nw", padx=8, pady=(8, 2))
        tk.Frame(right, bg=DIM2, height=1).pack(fill="x", padx=8, pady=(0, 4))

        self._eng_log_header = tk.Label(
            right, text=" — select a proc to stream its log — ",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w")
        self._eng_log_header.pack(fill="x", padx=8)

        self._eng_log_text = tk.Text(
            right, wrap="none", bg=BG, fg=WHITE, font=(FONT, 8),
            insertbackground=WHITE, padx=6, pady=6,
            borderwidth=0, highlightthickness=0)
        self._eng_log_text.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self._eng_log_text.config(state="disabled")

        # Initial list render + auto-refresh tick
        self._eng_refresh()
        self._eng_poll_logs()

    def _eng_refresh(self):
        """Rebuild the proc list and reschedule the 2s auto-refresh tick."""
        if not hasattr(self, "_eng_list_wrap"):
            return
        try:
            if not self._eng_list_wrap.winfo_exists():
                return
        except Exception:
            return

        for w in self._eng_list_wrap.winfo_children():
            try: w.destroy()
            except Exception: pass

        try:
            from core.proc import list_procs
            procs = list_procs()
        except Exception as e:
            tk.Label(self._eng_list_wrap,
                     text=f"  list_procs failed: {e}",
                     font=(FONT, 7), fg=RED, bg=BG,
                     anchor="w").pack(fill="x")
            procs = []

        if not procs:
            tk.Label(self._eng_list_wrap,
                     text="  — no tracked engines —",
                     font=(FONT, 7), fg=DIM, bg=BG,
                     anchor="w").pack(fill="x", pady=8)
        else:
            for p in procs:
                self._eng_render_row(p)

        # Reschedule
        try:
            if getattr(self, "_eng_after_id", None):
                self.after_cancel(self._eng_after_id)
        except Exception:
            pass
        try:
            self._eng_after_id = self.after(2000, self._eng_refresh)
        except Exception:
            pass

    def _eng_render_row(self, proc: dict):
        alive = bool(proc.get("alive"))
        pid = proc.get("pid")
        engine = proc.get("engine", "?")
        started = str(proc.get("started", ""))[:16].replace("T", " ")
        state = "LIVE" if alive else "done"
        state_color = GREEN if alive else DIM

        row = tk.Frame(self._eng_list_wrap, bg=BG, cursor="hand2")
        row.pack(fill="x", pady=0)

        cells = [
            (state,   7,  state_color, "bold"),
            (engine, 10,  WHITE,       "bold"),
            (str(pid), 7, AMBER_D,     "normal"),
            (started, 12, DIM,         "normal"),
        ]
        labels = []
        for text, width, color, weight in cells:
            lbl = tk.Label(row, text=text, font=(FONT, 7, weight),
                           fg=color, bg=BG, width=width, anchor="w")
            lbl.pack(side="left")
            labels.append(lbl)

        def _select(_e=None, p=proc):
            self._eng_select(p)
        def _hover_on(_e=None, labels=labels):
            for l in labels:
                try: l.configure(bg=BG3)
                except Exception: pass
        def _hover_off(_e=None, labels=labels, p=proc):
            bg = BG3 if self._eng_selected_pid == p.get("pid") else BG
            for l in labels:
                try: l.configure(bg=bg)
                except Exception: pass

        for w in (row, *labels):
            w.bind("<Button-1>", _select)
            w.bind("<Enter>", _hover_on)
            w.bind("<Leave>", _hover_off)

        if self._eng_selected_pid == pid:
            for l in labels:
                try: l.configure(bg=BG3)
                except Exception: pass

    def _eng_select(self, proc: dict):
        """Stop old log tail, start a new one for the selected proc."""
        pid = proc.get("pid")
        self._eng_selected_pid = pid

        # Stop old tail worker if any
        if self._eng_tail_thread is not None:
            self._eng_tail_stop.set()
            self._eng_tail_thread = None
        self._eng_tail_stop = threading.Event()

        # Clear the text widget and reset header
        try:
            self._eng_log_text.config(state="normal")
            self._eng_log_text.delete("1.0", "end")
            self._eng_log_text.config(state="disabled")
        except tk.TclError:
            return

        log_file = proc.get("log_file") or ""
        engine = proc.get("engine", "?")
        self._eng_log_header.configure(
            text=f"  {engine} · pid {pid} · {log_file}", fg=AMBER_D)

        if not log_file:
            return

        log_path = ROOT / log_file if not Path(log_file).is_absolute() else Path(log_file)
        t = threading.Thread(
            target=self._eng_tail_worker,
            args=(log_path, self._eng_tail_stop),
            daemon=True)
        t.start()
        self._eng_tail_thread = t
        # Trigger list re-render so the new selection highlights
        self._eng_refresh()

    def _eng_tail_worker(self, log_path: Path, stop_event: threading.Event):
        """Read the log file tail-f style, push new lines into the queue.

        Starts by reading the LAST ~500 lines so the viewer isn't empty on
        open, then follows appends. The queue is consumed by the UI thread
        in _eng_poll_logs.
        """
        if not log_path.exists():
            self._eng_log_queue.put(("SYSTEM",
                                     f"(log file not found: {log_path})"))
            return
        try:
            # Seed with last ~500 lines for context
            with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
                for line in lines[-500:]:
                    self._eng_log_queue.put(("LINE", line.rstrip("\n")))
                fh.seek(0, 2)  # EOF

                while not stop_event.is_set():
                    line = fh.readline()
                    if not line:
                        if stop_event.wait(0.25):
                            break
                        continue
                    self._eng_log_queue.put(("LINE", line.rstrip("\n")))
        except OSError as e:
            self._eng_log_queue.put(("SYSTEM", f"(log read error: {e})"))

    def _eng_poll_logs(self):
        """UI-thread poll: drain the queue, append to the Text widget,
        cap at 1000 lines to keep memory bounded, reschedule tick."""
        try:
            if not hasattr(self, "_eng_log_text"):
                return
            if not self._eng_log_text.winfo_exists():
                return
        except Exception:
            return

        drained = 0
        max_drain = 200  # don't block the UI if logs burst
        new_lines: list[str] = []
        try:
            while drained < max_drain:
                kind, line = self._eng_log_queue.get_nowait()
                new_lines.append(line)
                drained += 1
        except queue.Empty:
            pass

        if new_lines:
            try:
                self._eng_log_text.config(state="normal")
                self._eng_log_text.insert("end", "\n".join(new_lines) + "\n")
                # Cap to 1000 lines — delete oldest
                total_lines = int(self._eng_log_text.index("end-1c").split(".")[0])
                if total_lines > 1000:
                    self._eng_log_text.delete("1.0",
                                              f"{total_lines - 1000}.0")
                self._eng_log_text.see("end")
                self._eng_log_text.config(state="disabled")
            except tk.TclError:
                return

        try:
            self.after(200, self._eng_poll_logs)
        except Exception:
            pass

    # ─── STRATEGIES (Layer 2) ─────────────────────────────
    def _strategies(self):
        self._clr(); self._clear_kb()
        market_label = MARKETS.get(_conn.active_market, {}).get("label", "UNKNOWN")
        self.h_path.configure(text=f"> STRATEGIES"); self.h_stat.configure(text=market_label, fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  1-4 tabs  |  item key to open  |  H hub")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell(
            "STRATEGIES",
            f"Execution and research engines routed for {market_label}",
        )
        panel = self._ui_panel_frame(body, "ENGINE ROUTER", "Backtest, testnet, live and meta-engine entry points")
        summary = tk.Frame(panel, bg=BG)
        summary.pack(fill="x", pady=(0, 8))
        tk.Label(summary, text=f"MARKET  {market_label}", font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG, anchor="w").pack(side="left")
        tk.Label(summary, text="LANES 4   ROUTES 4   ENGINES 11",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(side="left", padx=(16, 0))
        tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))

        live_items = SUB_MENUS.get("live", [])
        self._strategies_sections = [
            ("BACKTEST", SUB_MENUS.get("backtest", []), "backtest"),
            ("TESTNET", [item for item in live_items if item[0] in {"PAPER", "DEMO", "TESTNET"}], "live"),
            ("LIVE", [item for item in live_items if item[0] in {"LIVE", "JANE STREET"}], "live"),
            ("META", SUB_MENUS.get("tools", []), "tools"),
        ]
        self._strategies_tab_btns = {}

        strip = tk.Frame(panel, bg=BG, height=30)
        strip.pack(fill="x", pady=(0, 6))
        strip.pack_propagate(False)
        for idx, (tab_id, _items, _parent_key) in enumerate(self._strategies_sections, start=1):
            btn = tk.Label(
                strip, text=f" {idx} {tab_id} ",
                font=(FONT, 9, "bold"),
                fg=DIM, bg=BG, padx=10, pady=5, cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 10), pady=1)
            btn.bind("<Button-1>", lambda e, t=tab_id: self._strategies_render_tab(t))
            self._strategies_tab_btns[tab_id] = btn
            self._kb(f"<Key-{idx}>", lambda t=tab_id: self._strategies_render_tab(t))

        tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))
        self._strategies_inner = tk.Frame(panel, bg=BG)
        self._strategies_inner.pack(fill="both", expand=True)
        self._strategies_render_tab("BACKTEST")

        self._ui_back_row(panel, lambda: self._menu("main"))

    def _strategies_render_tab(self, tab):
        if not hasattr(self, "_strategies_inner") or self._strategies_inner is None:
            return

        self._clear_kb()
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        for idx, (tab_id, _items, _parent_key) in enumerate(getattr(self, "_strategies_sections", []), start=1):
            self._kb(f"<Key-{idx}>", lambda t=tab_id: self._strategies_render_tab(t))

        for tab_id, btn in getattr(self, "_strategies_tab_btns", {}).items():
            btn.configure(fg=AMBER if tab_id == tab else DIM, bg=BG)

        for w in self._strategies_inner.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        items = []
        parent_key = "backtest"
        for section_name, section_items, section_parent in getattr(self, "_strategies_sections", []):
            if section_name == tab:
                items = section_items
                parent_key = section_parent
                break

        sec = self._ui_section(self._strategies_inner, tab, note=f"{len(items)} routes")
        for num, (name, script, desc) in enumerate(items, start=1):
            if num <= 9:
                key_label = str(num)
                key_bind = f"<Key-{num}>"
            else:
                letter_idx = num - 10
                if letter_idx < 26:
                    key_label = chr(ord("a") + letter_idx)
                    key_bind = f"<Key-{key_label}>"
                else:
                    key_label = " "
                    key_bind = None

            cmd = lambda n=name, s=script, d=desc, k=parent_key: self._brief(n, s, d, k)
            row, nl, dl = self._ui_action_row(
                sec, key_label, name, desc,
                command=cmd,
                title_width=16,
            )

            if key_bind:
                self._kb(key_bind, cmd)

    # ─── RISK (Layer 2) ──────────────────────────────────
    def _macro_brain_menu(self):
        """Macro Brain dashboard — autonomous CIO layer (separate from trade engines)."""
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> MACRO BRAIN")
        self.h_stat.configure(text="CIO", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  refresh button atualiza")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()
        try:
            from macro_brain.dashboard_view import render as _macro_render
            _macro_render(self.main, app=self)
        except Exception as e:
            tk.Label(self.main, text=f"Macro Brain failed to render:\n{e}",
                     font=(FONT, 10), fg=RED, bg=BG).pack(pady=40)

    def _risk_menu(self):
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> RISK"); self.h_stat.configure(text="CONSOLE", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  H hub")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell("RISK CONSOLE", "Portfolio and risk management surfaces")
        panel = self._ui_panel_frame(body, "RISK ROUTER", "Current and planned monitoring modules")

        sections = [
            ("PORTFOLIO", [
                ("1", "Open Positions",     "All active positions across venues"),
                ("2", "P&L Today",          "Real-time daily P&L"),
                ("3", "P&L History",        "Historical equity curve"),
                ("4", "Exposure Map",       "Sector/asset heatmap"),
            ]),
            ("RISK METRICS", [
                ("5", "VaR Calculator",     "Value at Risk (1d, 5d, 30d)"),
                ("6", "Drawdown Monitor",   "Current DD + historical worst"),
                ("7", "Correlation Risk",   "Portfolio correlation exposure"),
                ("8", "Kill Switch Status", "3-layer kill switch state"),
            ]),
            ("STRESS TEST", [
                ("9", "Market Crash",       "-20% BTC in 1h scenario"),
                ("A", "Liquidity Crisis",   "Spread blowout + slippage spike"),
                ("B", "Black Swan",         "Custom shock parameters"),
            ]),
        ]

        for section_name, items in sections:
            sec = self._ui_section(panel, section_name)

            for key_label, name, desc in items:
                self._ui_action_row(
                    sec, key_label, name, desc,
                    available=False, tag="COMING SOON", tag_fg=DIM, tag_bg=BG2, title_width=22,
                )

        self._ui_note(panel, "Risk console modules are in development.", fg=DIM)
        self._ui_note(panel, "Backtest stress tests remain available in STRATEGIES > MILLENNIUM.", fg=AMBER_D)
        self._ui_back_row(panel, lambda: self._menu("main"))

    # ─── SPECIAL SCREENS ─────────────────────────────────
    def _special(self, key):
        if key == "data":    self._data()
        elif key == "procs": self._procs()
        elif key == "config": self._config()

    def _data(self):
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> DATA"); self.h_stat.configure(text="BROWSE", fg=AMBER_D)
        self.f_lbl.configure(text="ESC back  |  click to open file  |  latest 200 indexed artifacts")
        self._kb("<Escape>", lambda: self._menu("main"))

        _outer, body = self._ui_page_shell("DATA & REPORTS", "Indexed JSON and report artifacts across the data tree")
        panel = self._ui_panel_frame(body, "ARTIFACT INDEX", "Recent persisted files across runs and legacy engine directories")

        # Walk every known data tree and tag each file with the section it
        # came from. Previous filter `"reports" in str(r) or "darwin" in str(r)`
        # ignored the entire data/runs/ modern layout and left this screen
        # empty for every backtest run after the write-path refactor. [Fase 0.1 / D1]
        reports: list[tuple[Path, object, str]] = []  # (path, stat, section)
        dd = ROOT / "data"

        def _collect(root: Path, section: str, pattern: str = "*.json"):
            if not root.exists():
                return
            for r in root.rglob(pattern):
                try:
                    reports.append((r, r.stat(), section))
                except (OSError, FileNotFoundError):
                    continue

        if dd.exists():
            _collect(dd / "runs",      "RUNS")       # modern backtest runs
            _collect(dd / "darwin",    "DARWIN")     # darwin evolution logs
            _collect(dd / "arbitrage", "ARBITRAGE")  # arbitrage session reports
            # Legacy per-engine dirs
            for legacy in ("mercurio", "newton", "thoth", "prometeu",
                           "multistrategy", "live"):
                _collect(dd / legacy, legacy.upper())
            # Legacy dated reports tree (data/YYYY-MM-DD/reports/*.json)
            for dated in dd.iterdir() if dd.exists() else []:
                if dated.is_dir() and dated.name[:4].isdigit() and (dated / "reports").exists():
                    _collect(dated / "reports", "LEGACY")
            reports.sort(key=lambda rs: rs[1].st_mtime, reverse=True)

        counts: dict[str, int] = {}
        for _r, _st, section in reports:
            counts[section] = counts.get(section, 0) + 1

        meta = tk.Frame(panel, bg=BG)
        meta.pack(fill="x", pady=(0, 8))
        tk.Label(meta, text=f"TOTAL  {len(reports)}", font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG).pack(side="left")
        for sec_name in ("RUNS", "ARBITRAGE", "DARWIN", "LEGACY"):
            n = counts.get(sec_name, 0)
            if n:
                tk.Label(meta, text=f"{sec_name}  {n}", font=(FONT, 8),
                         fg=DIM, bg=BG).pack(side="left", padx=(16, 0))
        tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))
        self._ui_note(
            panel,
            "Artifact index is chronological. Open BACKTESTS for validated run review; use this screen for raw persisted files.",
            fg=DIM,
        )

        routes = self._ui_section(panel, "ROUTES", note="review and drill-down")
        self._ui_action_row(
            routes, "B", "BACKTESTS", "Open validated run browser with metrics and detail panel",
            command=self._data_backtests, tag="PRIMARY", tag_fg=AMBER_D, tag_bg=BG, title_width=18,
        )
        self._ui_action_row(
            routes, "E", "ENGINE LOGS", "Open running-engine log tail and process inspection",
            command=self._data_engines, tag="OPERATIONS", tag_fg=AMBER_D, tag_bg=BG, title_width=18,
        )
        self._kb("<Key-b>", self._data_backtests)
        self._kb("<Key-e>", self._data_engines)

        canvas = tk.Canvas(panel, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=(0, 14))
        sb.pack(side="right", fill="y", padx=(0, 14), pady=(0, 14))

        tk.Label(sf, text=f"  {'SECTION':<10} {'FILE':<60} {'DATE':<15} {'SIZE':>8}",
                 font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(fill="x")
        tk.Frame(sf, bg=DIM2, height=1).pack(fill="x", pady=1)

        if not reports:
            tk.Label(sf, text="  No reports found.", font=(FONT, 9), fg=DIM, bg=BG).pack(anchor="w", pady=8)
            return

        # Section → color for the badge
        sec_color = {
            "RUNS":      AMBER,
            "DARWIN":    GREEN,
            "ARBITRAGE": AMBER_B,
            "LEGACY":    DIM,
        }

        for r, st, section in reports[:200]:
            try:
                rel = str(r.relative_to(ROOT))
            except ValueError:
                rel = str(r)
            mt = datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M")
            sz = f"{st.st_size/1024:.0f}K" if st.st_size < 1024*1024 else f"{st.st_size/(1024*1024):.1f}M"
            col = sec_color.get(section, WHITE)

            row = tk.Frame(sf, bg=BG, cursor="hand2")
            row.pack(fill="x")
            sec_lbl = tk.Label(row, text=f" {section:<9}", font=(FONT, 7, "bold"),
                               fg=col, bg=BG, width=10, anchor="w")
            sec_lbl.pack(side="left")
            name_lbl = tk.Label(row, text=f" {rel:<60}",
                                font=(FONT, 7), fg=DIM, bg=BG, anchor="w")
            name_lbl.pack(side="left")
            date_lbl = tk.Label(row, text=f" {mt:<15}",
                                font=(FONT, 7), fg=DIM, bg=BG, anchor="w")
            date_lbl.pack(side="left")
            size_lbl = tk.Label(row, text=f" {sz:>8}",
                                font=(FONT, 7), fg=DIM, bg=BG, anchor="e")
            size_lbl.pack(side="left")
            tk.Frame(row, bg=DIM2, height=1).pack(side="bottom", fill="x")

            labels = (sec_lbl, name_lbl, date_lbl, size_lbl)

            def _enter(_e=None, labels=labels):
                for l in labels:
                    try: l.configure(bg=BG3)
                    except tk.TclError: pass
                try: name_lbl.configure(fg=WHITE)
                except tk.TclError: pass
            def _leave(_e=None, labels=labels):
                for l in labels:
                    try: l.configure(bg=BG)
                    except tk.TclError: pass
                try: name_lbl.configure(fg=DIM)
                except tk.TclError: pass

            for w in (row, *labels):
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)
                w.bind("<Button-1>", lambda e, p=r: self._open_file(p))

        self._ui_back_row(panel, lambda: self._menu("main"))

    def _procs(self):
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> PROCS"); self.h_stat.configure(text="MANAGE", fg=GREEN)
        self.f_lbl.configure(text="ESC back  |  R refresh")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-r>", self._procs)

        _outer, body = self._ui_page_shell("PROCESSES", "Running engine processes and control actions", content_width=820)
        panel = self._ui_panel_frame(body, "PROCESS CONTROL", "Live engines currently registered in the local process index")
        try:
            from core.proc import list_procs, stop_proc
            ps = [p for p in list_procs() if p.get("alive")]
        except Exception:
            ps = []
            stop_proc = None  # type: ignore
        if not ps:
            self._ui_note(panel, "No engines running.", fg=DIM)

        def _safe_stop(pid):
            """stop_proc can raise on dead PIDs or permission errors — catch
            everything and re-render so the list stays in sync."""
            if pid is None or stop_proc is None:
                return
            try:
                stop_proc(int(pid))
            except Exception as e:
                self.h_stat.configure(text=f"STOP FAILED: {str(e)[:30]}", fg=RED)
            self.after(200, self._procs)

        for p in ps:
            row = tk.Frame(panel, bg=BG3); row.pack(fill="x", padx=14, pady=2)
            tk.Label(row, text=f" {p.get('engine','?').upper()} ", font=(FONT, 8, "bold"), fg=BG, bg=GREEN).pack(side="left")
            tk.Label(row, text=f"  PID {p.get('pid','?')}", font=(FONT, 9), fg=WHITE, bg=BG3, padx=6, pady=4).pack(side="left")
            tk.Button(row, text="STOP", font=(FONT, 7, "bold"), fg=RED, bg=BG3, border=0, cursor="hand2",
                      command=lambda pid=p.get("pid"): _safe_stop(pid)).pack(side="right", padx=4, pady=2)
        self._ui_back_row(panel, lambda: self._menu("main"))

    def _config(self):
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> SETTINGS"); self.h_stat.configure(text="CONFIG", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  H hub")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell("SETTINGS", "Configuration surfaces for credentials, deploy and operator defaults")
        panel = self._ui_panel_frame(body, "CONFIGURATION ROUTER", "Editable and planned configuration modules")

        cfgs = [
            ("API KEYS",           "Exchange & broker credentials",      self._cfg_keys,  True),
            ("MACRO BRAIN APIS",   "FRED, NewsAPI (data sources)",       self._cfg_macro_keys, True),
            ("TELEGRAM",           "Bot token & chat ID",                self._cfg_tg,    True),
            ("RISK PARAMETERS",    "Account size, max risk, leverage",   None,            False),
            ("STRATEGY DEFAULTS",  "Timeframes, symbols, baskets",      None,            False),
            ("DISPLAY",            "Theme, font size, ticker symbols",   None,            False),
            ("DATA DIRECTORY",     "Where reports & logs are stored",    None,            False),
            ("VPS / DEPLOY",       "Remote server SSH connection",       self._cfg_vps,   True),
            ("BACKUP / RESTORE",   "Export/import all settings",         None,            False),
        ]
        for i, (name, desc, cmd, available) in enumerate(cfgs):
            self._ui_action_row(
                panel, str(i + 1), name, desc,
                command=cmd if available else None,
                available=available,
                tag=None if available else "COMING SOON",
                tag_fg=DIM, tag_bg=BG2, title_width=20,
            )
            if cmd and available:
                self._kb(f"<Key-{i+1}>", cmd)

        self._ui_back_row(panel, lambda: self._menu("main"))
        # <Key-0> is already bound at the top of _config; no rebind here.

    # ─── CONFIG EDITORS ──────────────────────────────────
    def _cfg_edit(self, title, fields, load_fn, save_fn, back_fn=None):
        back = back_fn or self._config
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> CONFIG > {title}")
        self.f_lbl.configure(text="ESC back  |  CTRL+S save")
        self._kb("<Escape>", back)

        _outer, body = self._ui_page_shell(title, "Edit and persist configuration values", content_width=860)
        panel = self._ui_panel_frame(body, "CONFIG EDITOR", "Fields are persisted immediately on save")

        data = load_fn()
        entries = {}
        for key, label, hint, masked in fields:
            row = tk.Frame(panel, bg=BG); row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, width=16, anchor="w").pack(side="left")
            e = tk.Entry(row, bg=BG3, fg=WHITE, font=(FONT, 9), insertbackground=AMBER, border=0,
                         highlightthickness=1, highlightcolor=AMBER_D, highlightbackground=BORDER, width=48)
            e.pack(side="left", fill="x", expand=True, padx=4, ipady=3)
            val = data.get(key, "")
            if val: e.insert(0, str(val))
            if masked: e.configure(show="*")
            if hint: tk.Label(row, text=hint, font=(FONT, 7), fg=DIM2, bg=BG).pack(side="right", padx=4)
            entries[key] = e

        tk.Frame(panel, bg=BG, height=14).pack()
        br = tk.Frame(panel, bg=BG); br.pack(anchor="w")

        def save():
            vals = {k: e.get().strip() for k, e in entries.items()}
            save_fn(vals)
            self.h_stat.configure(text="SAVED", fg=GREEN)
            self.after(1500, lambda: self.h_stat.configure(text="", fg=DIM))
            # Clear Entry widgets so masked values (API keys, tokens) don't
            # linger in the form. User can re-navigate to this screen to see
            # what was stored (load_fn() will re-read from disk).
            for entry_w in entries.values():
                try: entry_w.delete(0, "end")
                except tk.TclError: pass

        sv = tk.Label(br, text="  SAVE  ", font=(FONT, 10, "bold"), fg=BG, bg=GREEN, cursor="hand2", padx=12, pady=3)
        sv.pack(side="left", padx=4); sv.bind("<Button-1>", lambda e: save())
        cn = tk.Label(br, text="  CANCEL  ", font=(FONT, 10), fg=DIM, bg=BG3, cursor="hand2", padx=12, pady=3)
        cn.pack(side="left", padx=4); cn.bind("<Button-1>", lambda e: back())
        self._kb("<Control-s>", save)
        self._ui_note(panel, "CTRL+S saves immediately to the local configuration store.", fg=DIM)

    def _load_json(self, name):
        p = ROOT / "config" / name
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f: return json.load(f)
            except Exception:
                runtime_health.record("launcher.config_load_failure")
        return {}

    def _save_json(self, name, data):
        p = ROOT / "config" / name; p.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_write_json(p, data, indent=4)
        except OSError:
            runtime_health.record("launcher.config_save_failure")
            with open(p, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)

    def _cfg_keys(self):
        def load():
            k = self._load_json("keys.json")
            return {"demo_key": k.get("demo",{}).get("api_key",""), "demo_sec": k.get("demo",{}).get("api_secret",""),
                    "test_key": k.get("testnet",{}).get("api_key",""), "test_sec": k.get("testnet",{}).get("api_secret",""),
                    "live_key": k.get("live",{}).get("api_key",""), "live_sec": k.get("live",{}).get("api_secret","")}
        def save(v):
            k = self._load_json("keys.json")
            k.setdefault("demo",{})["api_key"]=v["demo_key"]; k["demo"]["api_secret"]=v["demo_sec"]
            k.setdefault("testnet",{})["api_key"]=v["test_key"]; k["testnet"]["api_secret"]=v["test_sec"]
            k.setdefault("live",{})["api_key"]=v["live_key"]; k["live"]["api_secret"]=v["live_sec"]
            self._save_json("keys.json", k)
        self._cfg_edit("API KEYS", [
            ("demo_key","DEMO KEY","",True), ("demo_sec","DEMO SECRET","",True),
            ("test_key","TESTNET KEY","",True), ("test_sec","TESTNET SECRET","",True),
            ("live_key","LIVE KEY","REAL $",True), ("live_sec","LIVE SECRET","REAL $",True),
        ], load, save)

    def _cfg_macro_keys(self):
        """Macro Brain API keys — free/freemium data sources."""
        def load():
            k = self._load_json("keys.json"); m = k.get("macro_brain", {})
            return {
                "fred":    m.get("fred_api_key", ""),
                "newsapi": m.get("newsapi_key", ""),
            }
        def save(v):
            k = self._load_json("keys.json")
            k.setdefault("macro_brain", {})
            k["macro_brain"]["fred_api_key"] = v["fred"]
            k["macro_brain"]["newsapi_key"]  = v["newsapi"]
            self._save_json("keys.json", k)
        self._cfg_edit("MACRO BRAIN APIS", [
            ("fred",    "FRED API KEY",    "free @ stlouisfed.org",       True),
            ("newsapi", "NEWSAPI KEY",     "free 500/day @ newsapi.org",  True),
        ], load, save)

    def _cfg_tg(self):
        def load():
            k = self._load_json("keys.json"); t = k.get("telegram",{})
            return {"token": t.get("bot_token",""), "chat": t.get("chat_id","")}
        def save(v):
            k = self._load_json("keys.json"); k.setdefault("telegram",{})
            k["telegram"]["bot_token"]=v["token"]; k["telegram"]["chat_id"]=v["chat"]
            self._save_json("keys.json", k)
        self._cfg_edit("TELEGRAM", [
            ("token","BOT TOKEN","@BotFather",True), ("chat","CHAT ID","@userinfobot",False),
        ], load, save)

    def _cfg_vps(self):
        self._cfg_edit("VPS — SSH", [
            ("host","HOST / IP","",False), ("port","PORT","22",False),
            ("user","USER","root",False), ("key_path","SSH KEY","path to id_rsa",False),
            ("remote_dir","REMOTE DIR","/opt/aurum",False),
        ], lambda: self._load_json("vps.json"), lambda v: self._save_json("vps.json", v))

    def _cfg_vpn(self):
        self._cfg_edit("VPN", [
            ("type","TYPE","wireguard/openvpn",False), ("config_path","CONFIG FILE",".conf/.ovpn",False),
            ("server","SERVER IP","",False), ("private_key","PRIVATE KEY","",True),
            ("dns","DNS","1.1.1.1",False),
        ], lambda: self._load_json("vpn.json"), lambda v: self._save_json("vpn.json", v))

    # ─── CRYPTO FUTURES DASHBOARD ─────────────────────────
    def _crypto_dashboard(self):
        """Bloomberg-style dashboard for the crypto futures market.
        Runs all HTTP fetches in a worker thread, refreshes every 30s,
        and is cleaned up automatically by _clr() on any screen change."""
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> MARKETS > CRYPTO FUTURES")
        self.h_stat.configure(text="CONECTANDO...", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  H hub  |  R refresh")

        # Lazy imports — fail soft if a module is missing
        try:
            from core.market_data import MarketDataFetcher
            from config.params import SYMBOLS as _SYMS
        except Exception as e:
            tk.Label(self.main, text=f"Erro ao iniciar dashboard: {e}",
                     font=(FONT, 9), fg=RED, bg=BG).pack(pady=20)
            self._kb("<Escape>", lambda: self._menu("markets"))
            self._bind_global_nav()
            return

        # Symbol set: ensure BTC is always present so the footer can show its price
        syms = list(_SYMS[:8])
        if "BTCUSDT" not in syms:
            syms = ["BTCUSDT"] + syms[:7]
        self._dash_symbols = syms
        self._dash_fetcher = MarketDataFetcher(syms)
        self._dash_widgets: dict = {}
        self._dash_latency = None
        self._dash_balance = None
        self._dash_alive   = True
        self._dash_after_id = None
        # Tab state
        self._dash_tab = "home"
        self._dash_tab_btns: dict = {}
        self._dash_inner = None
        self._dash_portfolio_account = "paper"  # safe default — always loads
        self._dash_trades_filter = {"result": "all", "symbol": "all"}
        self._dash_trades_page = 0
        # HOME tab aggregated snapshot (populated by _dash_home_fetch_async)
        self._dash_home_snap: dict = {}
        # COCKPIT tab state (VPS remote control)
        self._dash_cockpit_snap: dict = {}
        self._dash_cockpit_stream = None      # subprocess.Popen handle while streaming
        self._dash_cockpit_streaming = False  # bool

        # Navigation
        self._kb("<Escape>", self._dash_exit_to_markets)
        self._bind_global_nav()
        self._kb("<Key-r>", self._dash_force_refresh)  # override global R
        # Keys 1-6 switch tabs
        self._kb("<Key-1>", lambda: self._dash_render_tab("home"))
        self._kb("<Key-2>", lambda: self._dash_render_tab("market"))
        self._kb("<Key-3>", lambda: self._dash_render_tab("portfolio"))
        self._kb("<Key-4>", lambda: self._dash_render_tab("trades"))
        self._kb("<Key-5>", lambda: self._dash_render_tab("backtest"))
        self._kb("<Key-6>", lambda: self._dash_render_tab("cockpit"))

        # Layout: sidebar + separator + main column (tab strip + body inner)
        root = tk.Frame(self.main, bg=BG); root.pack(fill="both", expand=True)

        side = tk.Frame(root, bg=PANEL, width=200); side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._dash_build_sidebar(side)

        tk.Frame(root, bg=BORDER, width=1).pack(side="left", fill="y")

        body = tk.Frame(root, bg=BG); body.pack(side="left", fill="both", expand=True)
        self._dash_build_tabs(body)

        # Mark this market active so the rest of the app sees the choice
        try:
            _conn.active_market = "crypto_futures"
        except Exception: pass

        # First tab render kicks off its own fetch loop
        self._dash_render_tab("home")

    # ── DASHBOARD: SIDEBAR ────────────────────────────────
    def _dash_build_sidebar(self, parent):
        """CS 1.6 style sidebar — connection status only, no balance placeholders.
        Two sections: DATA FEEDS (exchanges) and ACCOUNTS (paper/testnet/demo/live)."""

        def section(title):
            tk.Frame(parent, bg=PANEL, height=8).pack(fill="x")
            tk.Label(parent, text=f"[ {title} ]",
                     font=(FONT, 7, "bold"), fg=AMBER, bg=PANEL,
                     anchor="w").pack(fill="x", padx=10)
            tk.Frame(parent, bg=AMBER_D, height=1).pack(fill="x", padx=10, pady=(1, 3))

        # === DATA FEEDS ===
        section("DATA FEEDS")

        exchanges = MARKETS.get("crypto_futures", {}).get("exchanges", [])
        for ex_key in exchanges:
            info = _conn.get(ex_key) or {}
            label = info.get("label", ex_key).upper().replace("BINANCE ", "BINANCE\n")
            is_conn = info.get("connected", False)

            row = tk.Frame(parent, bg=PANEL, cursor="hand2")
            row.pack(fill="x", padx=10, pady=1)

            status_l = tk.Label(row, text="●" if is_conn else "○",
                                font=(FONT, 9, "bold"),
                                fg=GREEN if is_conn else DIM2, bg=PANEL, width=2)
            status_l.pack(side="left")
            name_l = tk.Label(row, text=info.get("label", ex_key).upper(),
                              font=(FONT, 7, "bold"),
                              fg=WHITE if is_conn else DIM, bg=PANEL,
                              anchor="w")
            name_l.pack(side="left", fill="x", expand=True)
            lat_l = tk.Label(row, text="—",
                             font=(FONT, 7), fg=DIM2, bg=PANEL,
                             anchor="e", width=6)
            lat_l.pack(side="right")

            self._dash_widgets[("ex_status",  ex_key)] = status_l
            self._dash_widgets[("ex_name",    ex_key)] = name_l
            self._dash_widgets[("ex_latency", ex_key)] = lat_l

            if ex_key == "binance_futures":
                def _goto_conn(_e=None):
                    self._dash_alive = False
                    self._connections()
                for w in (row, name_l, status_l, lat_l):
                    w.bind("<Button-1>", _goto_conn)
                    w.bind("<Enter>", lambda e, n=name_l: n.configure(fg=AMBER))
                    w.bind("<Leave>", lambda e, n=name_l, c=is_conn:
                           n.configure(fg=WHITE if c else DIM))

        # === ACCOUNTS ===
        section("ACCOUNTS")

        pm = self._get_portfolio_monitor()
        acc_colors = {"paper": AMBER_D, "testnet": GREEN,
                      "demo": AMBER, "live": RED}
        for acc in ("paper", "testnet", "demo", "live"):
            status = pm.status(acc)
            has_keys = status != "no_keys"
            icon = "●" if (has_keys or acc == "paper") else "○"
            icon_col = acc_colors[acc] if (has_keys or acc == "paper") else DIM2

            row = tk.Frame(parent, bg=PANEL, cursor="hand2")
            row.pack(fill="x", padx=10, pady=1)

            status_l = tk.Label(row, text=icon, font=(FONT, 9, "bold"),
                                fg=icon_col, bg=PANEL, width=2)
            status_l.pack(side="left")
            name_l = tk.Label(row, text=acc.upper(), font=(FONT, 7, "bold"),
                              fg=WHITE if (has_keys or acc == "paper") else DIM,
                              bg=PANEL, anchor="w")
            name_l.pack(side="left", fill="x", expand=True)
            hint = "active" if acc == "paper" else ("keys" if has_keys else "—")
            hint_l = tk.Label(row, text=hint, font=(FONT, 7),
                              fg=DIM2, bg=PANEL, anchor="e", width=6)
            hint_l.pack(side="right")
            self._dash_widgets[("acc_status", acc)] = status_l
            self._dash_widgets[("acc_name",   acc)] = name_l
            self._dash_widgets[("acc_hint",   acc)] = hint_l

            def _pick(_e=None, a=acc):
                self._dash_portfolio_account = a
                self._dash_render_tab("portfolio")
            for w in (row, status_l, name_l, hint_l):
                w.bind("<Button-1>", _pick)
                w.bind("<Enter>", lambda e, n=name_l: n.configure(fg=AMBER))
                w.bind("<Leave>", lambda e, n=name_l, h=(has_keys or acc == "paper"):
                       n.configure(fg=WHITE if h else DIM))

        # === MARKET footer ===
        tk.Frame(parent, bg=PANEL).pack(fill="both", expand=True)
        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", padx=10)
        st = _conn.status_summary()
        tk.Label(parent, text=f"market: {st['market']}",
                 font=(FONT, 7), fg=AMBER_D, bg=PANEL,
                 anchor="w").pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(parent, text="R refresh   ESC back",
                 font=(FONT, 7), fg=DIM2, bg=PANEL,
                 anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        # Start a background sidebar pinger that updates latencies every 15s
        self._dash_sidebar_ping_start()

    def _dash_sidebar_ping_start(self):
        """Background thread that pings binance_futures every 15s and updates
        the sidebar widgets on the main thread. Stops when dashboard dies."""
        def _alive_widget(key):
            """Return widget only if it's still packed and usable."""
            w = self._dash_widgets.get(key) if self._dash_widgets is not None else None
            if w is None:
                return None
            try:
                if w.winfo_exists():
                    return w
            except Exception:
                pass
            return None

        def loop():
            while getattr(self, "_dash_alive", False):
                try:
                    lat = _conn.ping("binance_futures")
                except Exception:
                    lat = None
                def apply(lat=lat):
                    if not getattr(self, "_dash_alive", False):
                        return
                    status_l = _alive_widget(("ex_status", "binance_futures"))
                    lat_l    = _alive_widget(("ex_latency", "binance_futures"))
                    name_l   = _alive_widget(("ex_name", "binance_futures"))
                    try:
                        if lat is not None:
                            if status_l: status_l.configure(text="●", fg=GREEN)
                            if lat_l:    lat_l.configure(text=f"{int(lat)}ms", fg=DIM)
                            if name_l:   name_l.configure(fg=WHITE)
                        else:
                            if status_l: status_l.configure(text="○", fg=RED)
                            if lat_l:    lat_l.configure(text="—", fg=DIM2)
                    except tk.TclError:
                        # Widget was destroyed between winfo_exists and configure
                        pass
                try: self.after(0, apply)
                except Exception: pass
                # Sleep 15s in small chunks so we exit quickly when _dash_alive flips
                for _ in range(30):
                    if not getattr(self, "_dash_alive", False):
                        return
                    time.sleep(0.5)

        threading.Thread(target=loop, daemon=True).start()

    # ── DASHBOARD: MAIN COLUMN ────────────────────────────
    def _dash_section_header(self, parent, text):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(0, 3))
        tk.Label(head, text=text, font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG, anchor="w").pack(side="left")
        tk.Frame(head, bg=DIM2, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0), pady=(6, 0))

    def _dash_build_market_tab(self, parent):
        inner = tk.Frame(parent, bg=BG); inner.pack(fill="both", expand=True, padx=14, pady=10)

        # === MARKET OVERVIEW ===
        self._dash_section_header(inner, "MARKET OVERVIEW")
        ov = tk.Frame(inner, bg=BG); ov.pack(fill="x", pady=(2, 8))
        for sym in self._dash_symbols:
            row = tk.Frame(ov, bg=BG, cursor="hand2"); row.pack(fill="x", pady=1)
            short = sym.replace("USDT", "")
            sym_l   = tk.Label(row, text=short, font=(FONT, 9, "bold"),
                               fg=AMBER, bg=BG, width=8, anchor="w")
            sym_l.pack(side="left")
            price_l = tk.Label(row, text="loading...", font=(FONT, 9),
                               fg=DIM, bg=BG, width=14, anchor="w")
            price_l.pack(side="left")
            pct_l   = tk.Label(row, text="—", font=(FONT, 9),
                               fg=DIM, bg=BG, width=10, anchor="w")
            pct_l.pack(side="left")
            bar_l   = tk.Label(row, text="░" * 10, font=(FONT, 9),
                               fg=DIM, bg=BG, anchor="w")
            bar_l.pack(side="left")
            extra_l = tk.Label(row, text="", font=(FONT, 8),
                               fg=DIM, bg=BG, anchor="w")
            extra_l.pack(side="left", padx=(8, 0))

            self._dash_widgets[("ticker", sym)] = {
                "row": row, "sym": sym_l, "price": price_l,
                "pct": pct_l, "bar": bar_l, "extra": extra_l,
            }

            def _flash(_e=None, l=sym_l):
                l.configure(fg=AMBER_B)
                self.after(180, lambda: l.configure(fg=AMBER))
            for w in (row, sym_l, price_l, pct_l, bar_l, extra_l):
                w.bind("<Button-1>", _flash)
                w.bind("<Enter>", lambda e, r=row: r.configure(bg=BG3))
                w.bind("<Leave>", lambda e, r=row: r.configure(bg=BG))

        # === TOP MOVERS ===
        self._dash_section_header(inner, "TOP MOVERS (24h)")
        movers = tk.Frame(inner, bg=BG); movers.pack(fill="x", pady=(2, 8))
        up_l = tk.Label(movers, text="↑ —", font=(FONT, 8),
                        fg=GREEN, bg=BG, anchor="w")
        up_l.pack(fill="x")
        dn_l = tk.Label(movers, text="↓ —", font=(FONT, 8),
                        fg=RED, bg=BG, anchor="w")
        dn_l.pack(fill="x")
        self._dash_widgets[("movers_up",)] = up_l
        self._dash_widgets[("movers_dn",)] = dn_l

        # === SENTIMENTO ===
        self._dash_section_header(inner, "SENTIMENTO")
        sent = tk.Frame(inner, bg=BG); sent.pack(fill="x", pady=(2, 8))

        fng_l = tk.Label(sent, text="Fear & Greed: —",
                         font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        fng_l.pack(fill="x")
        self._dash_widgets[("fng",)] = fng_l

        dom_l = tk.Label(sent, text="BTC Dominance: — (requer CoinGlass API)",
                         font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        dom_l.pack(fill="x")
        self._dash_widgets[("dom",)] = dom_l

        fund_l = tk.Label(sent, text="Funding AVG: —",
                          font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        fund_l.pack(fill="x")
        self._dash_widgets[("fund",)] = fund_l

        oi_l = tk.Label(sent, text="OI Total: — (requer CoinGlass API)",
                        font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        oi_l.pack(fill="x")
        self._dash_widgets[("oi",)] = oi_l

        ls_l = tk.Label(sent, text="Long/Short Ratio: —",
                        font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        ls_l.pack(fill="x")
        self._dash_widgets[("ls",)] = ls_l

        # === COMING SOON ===
        self._dash_section_header(inner, "COMING SOON")
        cs = tk.Frame(inner, bg=BG); cs.pack(fill="x", pady=(2, 8))
        items = [
            "News Feed (crypto headlines)",
            "Liquidation Heatmap",
            "Correlation Matrix real-time",
            "Volatility Surface (ATR por TF)",
            "On-chain Metrics (Glassnode)",
            "Order Flow Imbalance (bookmap-style)",
        ]
        for item in items:
            row = tk.Frame(cs, bg=BG, cursor="hand2"); row.pack(fill="x")
            l = tk.Label(row, text=f"  □ {item}", font=(FONT, 8),
                         fg=DIM, bg=BG, anchor="w")
            l.pack(fill="x")
            def _coming(_e=None, label=l):
                self.h_stat.configure(text="Em desenvolvimento", fg=AMBER_D)
                label.configure(fg=AMBER_D)
                self.after(700, lambda: label.configure(fg=DIM))
            for w in (row, l):
                w.bind("<Button-1>", _coming)
                w.bind("<Enter>", lambda e, x=l: x.configure(fg=AMBER))
                w.bind("<Leave>", lambda e, x=l: x.configure(fg=DIM))

    # ── DASHBOARD: ASYNC FETCH + APPLY ────────────────────
    def _dash_fetch_async(self):
        """Run market data fetch + ping in a daemon thread, then post results to UI."""
        if not getattr(self, "_dash_alive", False):
            return

        def worker():
            try:
                self._dash_fetcher.fetch_all()
            except Exception:
                pass
            try:
                self._dash_latency = _conn.ping("binance_futures")
            except Exception:
                self._dash_latency = None
            try:
                self._dash_balance = _conn.get_balance("binance_futures")
            except Exception:
                self._dash_balance = None
            if getattr(self, "_dash_alive", False):
                try:
                    self.after(0, self._dash_apply)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_apply(self):
        """Apply the latest snapshot to the UI. Runs on the main thread.
        Only touches the MARKET tab widgets — silently no-ops if the user
        has switched tabs (the widgets registered in _dash_widgets were
        destroyed by the rebuild)."""
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "market") != "market":
            return

        snap = self._dash_fetcher.snapshot()
        tickers = snap["tickers"]
        fng     = snap["fear_greed"]

        # ── header status ──
        if tickers:
            self.h_stat.configure(text="LIVE", fg=GREEN)
        else:
            self.h_stat.configure(text="OFFLINE", fg=RED)

        # ── sidebar: binance status + latency ──
        bf_status = self._dash_widgets.get(("ex_status", "binance_futures"))
        bf_lat    = self._dash_widgets.get(("ex_latency", "binance_futures"))
        bf_name   = self._dash_widgets.get(("ex_name", "binance_futures"))
        if bf_status and bf_lat:
            if self._dash_latency is not None:
                bf_status.configure(text="●", fg=GREEN)
                bf_lat.configure(text=f"{int(self._dash_latency)}ms", fg=DIM)
                if bf_name: bf_name.configure(fg=WHITE)
            else:
                bf_status.configure(text="○", fg=RED)
                bf_lat.configure(text="—", fg=DIM2)

        # Balance/wallets widgets were removed from the sidebar — nothing to update.

        # ── market overview rows ──
        for sym in self._dash_symbols:
            w = self._dash_widgets.get(("ticker", sym))
            if not w:
                continue
            t = tickers.get(sym)
            if t:
                sign  = "+" if t["pct"] >= 0 else ""
                color = GREEN if t["pct"] >= 0 else RED
                w["price"].configure(text=f"${t['price']:,.4f}".rstrip("0").rstrip(".") if t['price'] < 10 else f"${t['price']:,.2f}", fg=WHITE)
                w["pct"].configure(text=f"{sign}{t['pct']:.2f}%", fg=color)
                clamp = max(-1.0, min(1.0, t["pct"] / 5.0))
                n_filled = int(round((clamp + 1) / 2 * 10))
                w["bar"].configure(text="█" * n_filled + "░" * (10 - n_filled), fg=color)
                vol_b = t["vol"] / 1e9
                extra = f"vol24h ${vol_b:.2f}B" if vol_b >= 1 else f"vol24h ${t['vol']/1e6:.0f}M"
                w["extra"].configure(text=extra, fg=DIM)
            else:
                w["price"].configure(text="—", fg=DIM)
                w["pct"].configure(text="offline", fg=DIM)
                w["bar"].configure(text="░" * 10, fg=DIM)
                w["extra"].configure(text="")

        # ── top movers ──
        sorted_t = sorted(tickers.items(), key=lambda kv: kv[1]["pct"], reverse=True)
        up3 = sorted_t[:3]
        dn3 = sorted_t[-3:][::-1] if len(sorted_t) >= 3 else []

        def _fmt_movers(items, prefix):
            if not items:
                return f"{prefix} —"
            parts = []
            for sym, t in items:
                short = sym.replace("USDT", "")
                sign = "+" if t["pct"] >= 0 else ""
                parts.append(f"{short} {sign}{t['pct']:.1f}%")
            return f"{prefix}  " + "    ".join(parts)

        up_l = self._dash_widgets.get(("movers_up",))
        dn_l = self._dash_widgets.get(("movers_dn",))
        if up_l: up_l.configure(text=_fmt_movers(up3, "↑"))
        if dn_l: dn_l.configure(text=_fmt_movers(dn3, "↓"))

        # ── sentimento ──
        fng_l = self._dash_widgets.get(("fng",))
        if fng_l:
            if fng:
                v = fng["value"]; c = fng["classification"]
                n_filled = max(0, min(10, int(round(v / 10))))
                bar = "█" * n_filled + "░" * (10 - n_filled)
                color = GREEN if v >= 60 else (RED if v <= 40 else AMBER)
                fng_l.configure(text=f"Fear & Greed: {v} ({c})  {bar}", fg=color)
            else:
                fng_l.configure(text="Fear & Greed: — (offline)", fg=DIM)

        fund_l = self._dash_widgets.get(("fund",))
        if fund_l:
            avg = self._dash_fetcher.funding_avg()
            if avg is not None:
                sign = "+" if avg >= 0 else ""
                tone = ("ligeiramente bullish" if avg > 0 else
                        "ligeiramente bearish" if avg < 0 else "neutro")
                fund_l.configure(
                    text=f"Funding AVG: {sign}{avg*100:.4f}% ({tone})",
                    fg=GREEN if avg >= 0 else RED)
            else:
                fund_l.configure(text="Funding AVG: —", fg=DIM)

        ls_l = self._dash_widgets.get(("ls",))
        if ls_l:
            ls = snap["ls_ratio"]
            if ls is not None:
                tone  = ("mais longs"  if ls > 1.05 else
                         "mais shorts" if ls < 0.95 else "equilibrado")
                color = GREEN if ls > 1.05 else (RED if ls < 0.95 else AMBER)
                ls_l.configure(text=f"Long/Short Ratio: {ls:.2f} ({tone})", fg=color)
            else:
                ls_l.configure(text="Long/Short Ratio: —", fg=DIM)

        # ── footer summary ──
        btc_t = tickers.get("BTCUSDT")
        btc_str = f"BTC ${btc_t['price']:,.0f}" if btc_t else "BTC —"
        fng_str = f"Fear {fng['value']}" if fng else "Fear —"
        upd     = (snap["last_update"].strftime("%H:%M:%S")
                   if snap["last_update"] else "—")
        self.f_lbl.configure(
            text=(f"CRYPTO FUTURES · {len(self._dash_symbols)} ativos · "
                  f"{btc_str} · {fng_str} · upd {upd} · refresh 30s · "
                  f"ESC voltar  R refresh")
        )

        # ── schedule next market refresh (only while still on this tab) ──
        if getattr(self, "_dash_alive", False) and getattr(self, "_dash_tab", "market") == "market":
            aid = getattr(self, "_dash_after_id", None)
            if aid:
                try: self.after_cancel(aid)
                except Exception: pass
            self._dash_after_id = self.after(30000, self._dash_tick_refresh)

    def _dash_tick_refresh(self):
        """Tab-aware periodic refresher. Each tab uses its own interval and
        the per-tab apply functions schedule the next call."""
        if not getattr(self, "_dash_alive", False):
            return
        self._dash_after_id = None
        tab = getattr(self, "_dash_tab", "home")
        if tab == "home":
            self._dash_home_fetch_async()
        elif tab == "market":
            self._dash_fetch_async()
        elif tab == "portfolio":
            self._dash_portfolio_fetch_async()
        elif tab == "trades":
            self._dash_trades_render()
            self._dash_after_id = self.after(30000, self._dash_tick_refresh)
        elif tab == "cockpit":
            self._dash_cockpit_fetch_async()

    def _dash_force_refresh(self):
        if not getattr(self, "_dash_alive", False):
            return
        self.h_stat.configure(text="REFRESHING...", fg=AMBER_D)
        aid = getattr(self, "_dash_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._dash_after_id = None
        tab = getattr(self, "_dash_tab", "home")
        if tab == "home":
            self._dash_home_fetch_async()
        elif tab == "market":
            self._dash_fetch_async()
        elif tab == "portfolio":
            self._dash_portfolio_fetch_async()
        elif tab == "trades":
            self._dash_trades_render()
        elif tab == "backtest":
            self._dash_backtest_render()
        elif tab == "cockpit":
            self._dash_cockpit_fetch_async()

    # ── DASHBOARD: TABS (MARKET / PORTFOLIO / TRADES / ENGINES) ──
    def _get_portfolio_monitor(self):
        pm = getattr(self, "_dash_pm", None)
        if pm is None:
            from core.portfolio_monitor import PortfolioMonitor
            pm = PortfolioMonitor()
            self._dash_pm = pm
        return pm

    def _dash_build_tabs(self, parent):
        """Build the tab strip + an empty body_inner the tabs render into."""
        strip = tk.Frame(parent, bg=BG, height=30); strip.pack(fill="x")
        strip.pack_propagate(False)

        tabs = [
            ("home",      "HOME",      "1"),
            ("market",    "MARKET",    "2"),
            ("portfolio", "PORTFOLIO", "3"),
            ("trades",    "TRADES",    "4"),
            ("backtest",  "BACKTEST",  "5"),
            ("cockpit",   "COCKPIT",   "6"),
        ]
        self._dash_tab_btns = {}
        for tab_id, label, key in tabs:
            btn = tk.Label(
                strip, text=f" {key} {label} ",
                font=(FONT, 9, "bold"),
                fg=DIM, bg=BG, padx=10, pady=5, cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 10), pady=1)
            btn.bind("<Button-1>", lambda e, t=tab_id: self._dash_render_tab(t))
            self._dash_tab_btns[tab_id] = btn

        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x")
        self._dash_inner = tk.Frame(parent, bg=BG)
        self._dash_inner.pack(fill="both", expand=True)

    def _dash_render_tab(self, tab):
        """Switch active tab: clear body_inner, set state, build the tab body,
        kick off its initial fetch + reschedule under the new tab."""
        if not getattr(self, "_dash_alive", False):
            return
        if self._dash_inner is None:
            return

        # Cancel any pending refresh from the previous tab
        aid = getattr(self, "_dash_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._dash_after_id = None

        self._dash_tab = tab

        # Repaint tab buttons
        for tab_id, btn in self._dash_tab_btns.items():
            if tab_id == tab:
                btn.configure(bg=BG, fg=AMBER)
            else:
                btn.configure(bg=BG, fg=DIM)

        # Reset widget registry per tab so apply() never writes into stale handles
        self._dash_widgets = {}

        for w in self._dash_inner.winfo_children():
            try: w.destroy()
            except Exception: pass

        # Kill any in-flight log stream if user leaves cockpit
        if tab != "cockpit":
            self._dash_cockpit_kill_stream()
        # Note: backtest mousewheel is scoped via Enter/Leave on its canvas,
        # so no global unbind is needed on tab switch.

        if tab == "home":
            self._dash_build_home_tab(self._dash_inner)
            self._dash_home_fetch_async()
        elif tab == "market":
            self._dash_build_market_tab(self._dash_inner)
            # Kick off background fetch — apply() schedules the next refresh.
            self._dash_fetch_async()
        elif tab == "portfolio":
            self._dash_build_portfolio_tab(self._dash_inner)
            self._dash_portfolio_fetch_async()
        elif tab == "trades":
            self._dash_build_trades_tab(self._dash_inner)
            self._dash_after_id = self.after(30000, self._dash_tick_refresh)
        elif tab == "backtest":
            self._dash_build_backtest_tab(self._dash_inner)
            # On-demand refresh only — no periodic loop.
        elif tab == "cockpit":
            self._dash_build_cockpit_tab(self._dash_inner)
            self._dash_cockpit_fetch_async()

    # ── PORTFOLIO TAB ─────────────────────────────────────
    def _dash_build_portfolio_tab(self, parent):
        pm = self._get_portfolio_monitor()

        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True)

        # Inner accounts column
        col = tk.Frame(wrap, bg=PANEL, width=170); col.pack(side="left", fill="y")
        col.pack_propagate(False)

        tk.Label(col, text=" ACCOUNTS ", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=10, pady=(10, 4))
        tk.Frame(col, bg=DIM2, height=1).pack(fill="x", padx=10)

        accounts = [
            ("testnet", "TESTNET", GREEN),
            ("demo",    "DEMO",    AMBER),
            ("live",    "LIVE",    RED),
            ("paper",   "PAPER",   DIM),
        ]
        self._dash_widgets[("portfolio_account_btns",)] = {}
        for acc_id, label, color in accounts:
            status = pm.status(acc_id)
            row = tk.Frame(col, bg=PANEL, cursor="hand2")
            row.pack(fill="x", padx=8, pady=(6, 0))
            icon = "●" if status in ("live", "paper") else "○"
            icon_color = color if status in ("live", "paper") else DIM

            top_l = tk.Label(row, text=f"{icon} {label}", font=(FONT, 9, "bold"),
                             fg=WHITE if status in ("live", "paper") else DIM,
                             bg=PANEL, anchor="w")
            top_l.pack(fill="x")
            tk.Label(row, text=icon, font=(FONT, 7), fg=icon_color,
                     bg=PANEL).place(in_=top_l, x=-2, y=2)

            sub_l = tk.Label(row, text="…",
                             font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w")
            sub_l.pack(fill="x")
            self._dash_widgets[("portfolio_account_btns",)][acc_id] = (row, top_l, sub_l)

            def _click(_e=None, a=acc_id):
                self._dash_portfolio_account = a
                self._dash_portfolio_fetch_async()
                self._dash_portfolio_repaint_account_btns()
            for w in (row, top_l, sub_l):
                w.bind("<Button-1>", _click)
                w.bind("<Enter>", lambda e, l=top_l, s=status:
                       l.configure(fg=AMBER))
                w.bind("<Leave>", lambda e, l=top_l, s=status:
                       l.configure(fg=WHITE if s in ("live", "paper") else DIM))

        self._dash_portfolio_repaint_account_btns()

        # Right details panel — built/refreshed by _dash_portfolio_render
        details = tk.Frame(wrap, bg=BG)
        details.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        self._dash_widgets[("portfolio_details",)] = details

        # Cached-first: if we have a snapshot for the active account, render it
        # immediately instead of showing a "Loading..." placeholder. The async
        # refresh will replace it as soon as fresh data arrives.
        mode = getattr(self, "_dash_portfolio_account", "paper")
        if pm.get_cached(mode) is not None:
            # Defer render so the details frame is fully packed first
            self.after(0, self._dash_portfolio_render)
        else:
            tk.Label(details, text="Loading account…",
                     font=(FONT, 9), fg=DIM, bg=BG).pack(pady=20)

    def _dash_portfolio_repaint_account_btns(self):
        btns = self._dash_widgets.get(("portfolio_account_btns",)) or {}
        active = getattr(self, "_dash_portfolio_account", "paper")
        pm = self._get_portfolio_monitor()
        for acc_id, (row, top_l, sub_l) in btns.items():
            cached = pm.get_cached(acc_id) or {}
            status = pm.status(acc_id)
            if status == "no_keys":
                sub_l.configure(text="sem keys", fg=DIM)
            elif status == "paper":
                eq = cached.get("equity", 0) or 0
                sub_l.configure(text=f"${eq:,.0f}", fg=AMBER_D)
            else:
                eq = cached.get("equity")
                if eq is None:
                    sub_l.configure(text="…", fg=DIM)
                else:
                    sub_l.configure(text=f"${eq:,.2f}", fg=GREEN)
            row.configure(bg=BG3 if acc_id == active else PANEL)
            top_l.configure(bg=BG3 if acc_id == active else PANEL)
            sub_l.configure(bg=BG3 if acc_id == active else PANEL)

    def _dash_portfolio_fetch_async(self):
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "market") != "portfolio":
            return
        mode = getattr(self, "_dash_portfolio_account", "paper")
        pm = self._get_portfolio_monitor()

        def worker():
            try:
                pm.refresh(mode)
            except Exception:
                pass
            if getattr(self, "_dash_alive", False):
                try: self.after(0, self._dash_portfolio_render)
                except Exception: pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_portfolio_render(self):
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "market") != "portfolio":
            return

        pm = self._get_portfolio_monitor()
        mode = getattr(self, "_dash_portfolio_account", "paper")
        data = pm.get_cached(mode) or {}
        details = self._dash_widgets.get(("portfolio_details",))
        if details is None:
            return
        try:
            if not details.winfo_exists():
                return
        except Exception:
            return

        for w in details.winfo_children():
            try: w.destroy()
            except Exception: pass

        self._dash_portfolio_repaint_account_btns()

        status = data.get("status", pm.status(mode))

        # Empty / no-keys placeholder
        if status == "no_keys":
            box = tk.Frame(details, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1)
            box.pack(pady=24, padx=20, ipadx=24, ipady=20)
            tk.Label(box, text=mode.upper(), font=(FONT, 14, "bold"),
                     fg=AMBER, bg=PANEL).pack(pady=(0, 10))
            tk.Label(box, text="○ Sem API keys configuradas",
                     font=(FONT, 9), fg=DIM, bg=PANEL).pack(pady=2)
            tk.Label(box, text="Configura em:", font=(FONT, 8),
                     fg=DIM, bg=PANEL).pack(pady=(8, 2))
            tk.Label(box, text=f"SETTINGS > API KEYS > {mode.upper()}",
                     font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL).pack(pady=(0, 10))
            btn = tk.Label(box, text=" IR PARA SETTINGS ",
                           font=(FONT, 9, "bold"), fg=BG, bg=AMBER,
                           cursor="hand2", padx=12, pady=4)
            btn.pack(pady=(8, 0))
            btn.bind("<Button-1>", lambda e: self._config())
            self._dash_after_id = self.after(15000, self._dash_tick_refresh)
            return

        # === Header card ===
        head = tk.Frame(details, bg=PANEL,
                        highlightbackground=BORDER, highlightthickness=1)
        head.pack(fill="x", pady=(0, 8))
        head_title = " PAPER · simulated " if mode == "paper" else f" {mode.upper()} · Binance Futures "
        tk.Label(head, text=head_title,
                 font=(FONT, 8, "bold"), fg=BG, bg=AMBER).pack(side="left", padx=8, pady=4)

        # Paper-only: EDIT button opens editable-state dialog
        if mode == "paper":
            edit_btn = tk.Label(head, text=" EDIT ",
                                font=(FONT, 7, "bold"),
                                fg=BG, bg=AMBER_D, cursor="hand2",
                                padx=6, pady=2)
            edit_btn.pack(side="right", padx=(0, 8), pady=4)
            edit_btn.bind("<Button-1>", lambda e: self._dash_paper_edit_dialog())
            edit_btn.bind("<Enter>", lambda e, b=edit_btn: b.configure(bg=AMBER))
            edit_btn.bind("<Leave>", lambda e, b=edit_btn: b.configure(bg=AMBER_D))
            # Show last-modified timestamp
            lm = data.get("last_modified", "")
            if lm:
                try: lm = lm.split("T")[0] + "  " + lm.split("T")[1][:8]
                except Exception: pass
                tk.Label(head, text=f"modified: {lm}",
                         font=(FONT, 7), fg=DIM2, bg=PANEL,
                         anchor="e").pack(side="right", padx=(0, 8))

        balance = float(data.get("balance", 0) or 0)
        equity  = float(data.get("equity", 0) or 0)
        unr     = float(data.get("unrealized_pnl", 0) or 0)
        today   = float(data.get("today_pnl", 0) or 0)
        m_used  = float(data.get("margin_used", 0) or 0)
        m_free  = float(data.get("margin_free", 0) or 0)
        unr_color = GREEN if unr >= 0 else RED
        today_color = GREEN if today >= 0 else RED
        margin_pct = (m_used / equity * 100) if equity > 0 else 0

        grid = tk.Frame(head, bg=PANEL); grid.pack(fill="x", padx=12, pady=8)
        cells = [
            ("Balance", f"${balance:,.2f}", WHITE),
            ("Equity",  f"${equity:,.2f}",  WHITE),
            ("Unreal",  f"{'+'  if unr >= 0 else ''}${unr:,.2f}", unr_color),
            ("Today",   f"{'+'  if today >= 0 else ''}${today:,.2f}", today_color),
            ("Margin",  f"${m_used:,.0f}  ({margin_pct:.0f}%)", AMBER_D),
            ("Free",    f"${m_free:,.2f}", DIM),
        ]
        for i, (lbl, val, col) in enumerate(cells):
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 18), pady=2)
            tk.Label(cell, text=lbl, font=(FONT, 7), fg=DIM, bg=PANEL,
                     anchor="w").pack(anchor="w")
            tk.Label(cell, text=val, font=(FONT, 10, "bold"),
                     fg=col, bg=PANEL, anchor="w").pack(anchor="w")

        # === Open positions ===
        positions = data.get("positions") or []
        pos_box = tk.Frame(details, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1)
        pos_box.pack(fill="x", pady=(0, 8))
        tk.Label(pos_box, text=f" POSIÇÕES ABERTAS ({len(positions)}) ",
                 font=(FONT, 8, "bold"), fg=AMBER, bg=PANEL,
                 anchor="w").pack(fill="x", padx=8, pady=(6, 2))
        tk.Frame(pos_box, bg=DIM2, height=1).pack(fill="x", padx=8)
        if not positions:
            tk.Label(pos_box, text="  (no open positions)",
                     font=(FONT, 8), fg=DIM, bg=PANEL,
                     anchor="w").pack(fill="x", padx=8, pady=4)
        else:
            for p in positions[:8]:
                pl = float(p.get("pnl", 0) or 0)
                pl_col = GREEN if pl >= 0 else RED
                row = tk.Frame(pos_box, bg=PANEL); row.pack(fill="x", padx=8, pady=1)
                tk.Label(row, text=p.get("symbol", "?"), font=(FONT, 9, "bold"),
                         fg=AMBER, bg=PANEL, width=12, anchor="w").pack(side="left")
                tk.Label(row, text=p.get("side", "?"), font=(FONT, 8),
                         fg=WHITE, bg=PANEL, width=6, anchor="w").pack(side="left")
                tk.Label(row, text=f"size {p.get('size', 0):.4f}", font=(FONT, 8),
                         fg=DIM, bg=PANEL, width=14, anchor="w").pack(side="left")
                tk.Label(row, text=f"@ {p.get('entry', 0):,.4f}", font=(FONT, 8),
                         fg=DIM, bg=PANEL, width=16, anchor="w").pack(side="left")
                tk.Label(row, text=f"PnL {'+' if pl >= 0 else ''}${pl:,.2f}",
                         font=(FONT, 9, "bold"), fg=pl_col, bg=PANEL,
                         anchor="w").pack(side="left")
            tk.Frame(pos_box, bg=PANEL, height=4).pack()

        # === Equity curve canvas (paper account or income-based) ===
        eq_curve = data.get("equity_curve") or []
        if not eq_curve and data.get("income_7d"):
            # Build a cumulative curve out of income history
            cum = float(data.get("equity", 0) or 0)
            eq_curve = []
            running = 0.0
            for row in data["income_7d"]:
                try:
                    running += float(row.get("income", 0) or 0)
                    eq_curve.append(round(cum - running, 2))
                except (TypeError, ValueError):
                    continue
            eq_curve.reverse()
            if eq_curve:
                eq_curve.append(cum)

        eq_box = tk.Frame(details, bg=PANEL,
                          highlightbackground=BORDER, highlightthickness=1)
        eq_box.pack(fill="x", pady=(0, 8))
        tk.Label(eq_box, text=" EQUITY CURVE ", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=8, pady=(6, 2))
        tk.Frame(eq_box, bg=DIM2, height=1).pack(fill="x", padx=8)
        canvas = tk.Canvas(eq_box, bg=PANEL, height=140,
                           highlightthickness=0, bd=0)
        canvas.pack(fill="x", padx=8, pady=(4, 6))
        canvas.bind("<Configure>",
                    lambda e, c=canvas, eq=eq_curve:
                    self._dash_draw_equity_canvas(c, eq))

        # === Recent trades ===
        recent = (data.get("recent_trades") or [])[:5]
        rb = tk.Frame(details, bg=PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
        rb.pack(fill="x", pady=(0, 8))
        tk.Label(rb, text=" ÚLTIMOS 5 TRADES ", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=8, pady=(6, 2))
        tk.Frame(rb, bg=DIM2, height=1).pack(fill="x", padx=8)
        if not recent:
            tk.Label(rb, text="  (no trade history)",
                     font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w"
                     ).pack(fill="x", padx=8, pady=4)
        else:
            for i, t in enumerate(recent):
                pnl = float(t.get("pnl", 0) or 0)
                col = GREEN if pnl >= 0 else RED
                sym  = t.get("symbol", "?")
                side = t.get("direction") or t.get("side") or t.get("buyer", "?")
                if isinstance(side, bool):
                    side = "BUY" if side else "SELL"
                result = t.get("result", "")
                row = tk.Frame(rb, bg=PANEL); row.pack(fill="x", padx=8, pady=1)
                tk.Label(row, text=f"#{i + 1}", font=(FONT, 8),
                         fg=DIM, bg=PANEL, width=4).pack(side="left")
                tk.Label(row, text=sym.replace("USDT", ""),
                         font=(FONT, 9, "bold"), fg=AMBER, bg=PANEL,
                         width=8, anchor="w").pack(side="left")
                tk.Label(row, text=str(side)[:5], font=(FONT, 8),
                         fg=WHITE, bg=PANEL, width=6, anchor="w").pack(side="left")
                tk.Label(row, text=str(result), font=(FONT, 8),
                         fg=col, bg=PANEL, width=6, anchor="w").pack(side="left")
                tk.Label(row, text=f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",
                         font=(FONT, 9, "bold"), fg=col, bg=PANEL, width=12,
                         anchor="w").pack(side="left")
            tk.Frame(rb, bg=PANEL, height=4).pack()

        # === Rolling metrics (paper summary if available) ===
        summary = data.get("summary") or {}
        if summary:
            mb = tk.Frame(details, bg=PANEL,
                          highlightbackground=BORDER, highlightthickness=1)
            mb.pack(fill="x", pady=(0, 4))
            tk.Label(mb, text=" MÉTRICAS ", font=(FONT, 8, "bold"),
                     fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=8, pady=(6, 2))
            tk.Frame(mb, bg=DIM2, height=1).pack(fill="x", padx=8)
            cells = [
                ("WR",     f"{summary.get('win_rate', 0):.1f}%"),
                ("Sharpe", f"{summary.get('sharpe', 0) or 0:.2f}"),
                ("Sortino",f"{summary.get('sortino', 0) or 0:.2f}"),
                ("MaxDD",  f"{summary.get('max_dd_pct', 0):.1f}%"),
                ("Trades", str(summary.get('n_trades', 0))),
                ("PnL",    f"${summary.get('pnl', 0) or 0:,.2f}"),
            ]
            grid = tk.Frame(mb, bg=PANEL); grid.pack(fill="x", padx=12, pady=8)
            for i, (lbl, val) in enumerate(cells):
                cell = tk.Frame(grid, bg=PANEL)
                cell.grid(row=0, column=i, sticky="w", padx=(0, 18))
                tk.Label(cell, text=lbl, font=(FONT, 7), fg=DIM, bg=PANEL,
                         anchor="w").pack(anchor="w")
                tk.Label(cell, text=val, font=(FONT, 9, "bold"),
                         fg=WHITE, bg=PANEL, anchor="w").pack(anchor="w")

        # === RUNNING ENGINES (controls) ===
        try:
            from core.proc import list_procs, stop_proc
            procs = list_procs()
        except Exception:
            procs = []

        eb = tk.Frame(details, bg=PANEL,
                      highlightbackground=BORDER, highlightthickness=1)
        eb.pack(fill="x", pady=(0, 8))

        eb_head = tk.Frame(eb, bg=PANEL); eb_head.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(eb_head, text=f" RUNNING ENGINES ({sum(1 for p in procs if p.get('alive'))}) ",
                 font=(FONT, 8, "bold"), fg=AMBER, bg=PANEL,
                 anchor="w").pack(side="left")
        start_btn = tk.Label(eb_head, text=" + START NEW ",
                             font=(FONT, 7, "bold"),
                             fg=BG, bg=AMBER, cursor="hand2",
                             padx=6, pady=2)
        start_btn.pack(side="right")
        def _goto_strategies(_e=None):
            self._dash_alive = False
            self._menu("strategies")
        for w in (start_btn,):
            w.bind("<Button-1>", _goto_strategies)
            w.bind("<Enter>", lambda e, b=start_btn: b.configure(bg=AMBER_B))
            w.bind("<Leave>", lambda e, b=start_btn: b.configure(bg=AMBER))
        tk.Frame(eb, bg=DIM2, height=1).pack(fill="x", padx=8)

        engines_known = [
            "backtest", "live", "arb", "newton", "mercurio",
            "thoth", "prometeu", "darwin", "chronos", "multi",
        ]
        seen: dict[str, dict] = {}
        for p in procs:
            seen[p.get("engine", "?")] = p

        any_running = False
        for eng in engines_known:
            info = seen.get(eng)
            is_alive = bool(info and info.get("alive"))
            if not is_alive:
                continue  # skip stopped engines — keep UI clean
            any_running = True

            row = tk.Frame(eb, bg=PANEL); row.pack(fill="x", padx=8, pady=2)
            tk.Label(row, text="●", font=(FONT, 9, "bold"),
                     fg=GREEN, bg=PANEL, width=2).pack(side="left")
            tk.Label(row, text=eng.upper(), font=(FONT, 9, "bold"),
                     fg=AMBER, bg=PANEL, width=12,
                     anchor="w").pack(side="left")
            pid = info.get("pid", 0)
            started = str(info.get("started", ""))[:19].replace("T", " ")
            tk.Label(row, text=f"PID {pid}", font=(FONT, 7),
                     fg=DIM, bg=PANEL, width=10,
                     anchor="w").pack(side="left")
            tk.Label(row, text=started, font=(FONT, 7),
                     fg=DIM2, bg=PANEL, anchor="w").pack(side="left", padx=(4, 0))

            stop_l = tk.Label(row, text=" STOP ",
                              font=(FONT, 7, "bold"),
                              fg=BG, bg=RED, cursor="hand2", padx=6)
            stop_l.pack(side="right")

            def _stop(_e=None, p=pid, eng_name=eng):
                try:
                    ok = stop_proc(int(p))
                except Exception:
                    ok = False
                self.h_stat.configure(
                    text=f"{'STOPPED' if ok else 'STOP FAILED'} {eng_name.upper()}",
                    fg=GREEN if ok else RED)
                # Re-render portfolio to reflect new proc state
                self.after(600, self._dash_portfolio_render)
            stop_l.bind("<Button-1>", _stop)
            stop_l.bind("<Enter>", lambda e, b=stop_l: b.configure(bg="#ff5050"))
            stop_l.bind("<Leave>", lambda e, b=stop_l: b.configure(bg=RED))

        if not any_running:
            tk.Label(eb, text="  ○ no engines running  ·  click START NEW to launch",
                     font=(FONT, 8), fg=DIM, bg=PANEL,
                     anchor="w").pack(fill="x", padx=8, pady=4)

        # Footer summary
        upd = data.get("ts", "")
        if upd:
            try:
                upd = upd.split("T")[1][:8]
            except Exception:
                pass
        self.f_lbl.configure(
            text=f"PORTFOLIO · {mode.upper()} · upd {upd} · "
                 f"1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit"
        )

        # Schedule next refresh
        if getattr(self, "_dash_alive", False) and self._dash_tab == "portfolio":
            aid = getattr(self, "_dash_after_id", None)
            if aid:
                try: self.after_cancel(aid)
                except Exception: pass
            self._dash_after_id = self.after(15000, self._dash_tick_refresh)

    def _dash_draw_equity_canvas(self, canvas, eq):
        try:
            canvas.delete("all")
            w = canvas.winfo_width() or 600
            h = canvas.winfo_height() or 140
        except Exception:
            return
        if not eq or len(eq) < 2:
            try:
                canvas.create_text(w // 2, h // 2, text="(no equity data)",
                                   fill=DIM, font=(FONT, 9))
            except Exception:
                pass
            return
        pad_l, pad_r, pad_t, pad_b = 56, 14, 10, 16
        inner_w = max(1, w - pad_l - pad_r)
        inner_h = max(1, h - pad_t - pad_b)
        try:
            vmin = min(eq) * 0.998
            vmax = max(eq) * 1.002
        except (TypeError, ValueError):
            return
        vspan = (vmax - vmin) or 1.0
        n = len(eq)

        # Grid + Y labels
        for i in range(5):
            frac = i / 4
            v = vmax - frac * vspan
            y = pad_t + frac * inner_h
            canvas.create_line(pad_l, y, w - pad_r, y, fill=DIM2)
            canvas.create_text(pad_l - 4, y, text=f"${v:,.0f}",
                               fill=DIM, font=(FONT, 7), anchor="e")

        # Polyline
        coords = []
        for i, v in enumerate(eq):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            x = pad_l + (i / max(n - 1, 1)) * inner_w
            y = pad_t + (1 - (fv - vmin) / vspan) * inner_h
            coords.extend([x, y])
        if len(coords) >= 4:
            canvas.create_line(coords, fill="#58a6ff", width=2)

        # High water mark
        try:
            hwm = max(eq)
            y_hwm = pad_t + (1 - (hwm - vmin) / vspan) * inner_h
            canvas.create_line(pad_l, y_hwm, w - pad_r, y_hwm,
                               fill=GREEN, dash=(4, 4))
        except Exception:
            pass

    # ── TRADES TAB ─────────────────────────────────────────
    def _dash_build_trades_tab(self, parent):
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=12, pady=10)

        # Filter row
        filt = tk.Frame(wrap, bg=BG); filt.pack(fill="x", pady=(0, 6))
        tk.Label(filt, text="FILTROS:", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=BG).pack(side="left", padx=(0, 6))

        for tag in ("all", "win", "loss"):
            label = tag.upper()
            btn = tk.Label(filt, text=f" {label} ", font=(FONT, 8, "bold"),
                           fg=BG if self._dash_trades_filter["result"] == tag else DIM,
                           bg=AMBER if self._dash_trades_filter["result"] == tag else BG3,
                           padx=8, pady=2, cursor="hand2")
            btn.pack(side="left", padx=2)
            def _click(_e=None, t=tag):
                self._dash_trades_filter["result"] = t
                self._dash_trades_page = 0
                self._dash_render_tab("trades")
            btn.bind("<Button-1>", _click)

        tk.Label(filt, text="  Conta:", font=(FONT, 8),
                 fg=DIM, bg=BG).pack(side="left", padx=(10, 4))
        accs = ("paper", "testnet", "demo", "live")
        for a in accs:
            active = self._dash_portfolio_account == a
            btn = tk.Label(filt, text=f" {a.upper()} ", font=(FONT, 8, "bold"),
                           fg=BG if active else DIM,
                           bg=AMBER if active else BG3,
                           padx=6, pady=2, cursor="hand2")
            btn.pack(side="left", padx=1)
            def _aclick(_e=None, x=a):
                self._dash_portfolio_account = x
                # Make sure we have data for this account
                pm = self._get_portfolio_monitor()
                if pm.get_cached(x) is None:
                    threading.Thread(target=lambda m=x: pm.refresh(m), daemon=True).start()
                self._dash_trades_page = 0
                self._dash_render_tab("trades")
            btn.bind("<Button-1>", _aclick)

        # Table
        tbl = tk.Frame(wrap, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1)
        tbl.pack(fill="both", expand=True)
        self._dash_widgets[("trades_table",)] = tbl

        # Footer (page nav)
        nav = tk.Frame(wrap, bg=BG); nav.pack(fill="x", pady=(6, 0))
        prev_btn = tk.Label(nav, text=" ◄ prev ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG3, padx=8, pady=2, cursor="hand2")
        prev_btn.pack(side="left", padx=2)
        prev_btn.bind("<Button-1>", lambda e: self._dash_trades_page_change(-1))
        page_lbl = tk.Label(nav, text="", font=(FONT, 8), fg=DIM, bg=BG)
        page_lbl.pack(side="left", padx=8)
        next_btn = tk.Label(nav, text=" next ► ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG3, padx=8, pady=2, cursor="hand2")
        next_btn.pack(side="left", padx=2)
        next_btn.bind("<Button-1>", lambda e: self._dash_trades_page_change(+1))
        stats_lbl = tk.Label(nav, text="", font=(FONT, 8), fg=DIM, bg=BG)
        stats_lbl.pack(side="right")
        self._dash_widgets[("trades_page",)]  = page_lbl
        self._dash_widgets[("trades_stats",)] = stats_lbl

        # Initial render
        self._dash_trades_render()

    def _dash_trades_page_change(self, delta):
        self._dash_trades_page = max(0, self._dash_trades_page + delta)
        self._dash_trades_render()

    def _dash_trades_render(self):
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "market") != "trades":
            return
        tbl = self._dash_widgets.get(("trades_table",))
        page_lbl = self._dash_widgets.get(("trades_page",))
        stats_lbl = self._dash_widgets.get(("trades_stats",))
        if tbl is None:
            return
        try:
            if not tbl.winfo_exists():
                return
        except Exception:
            return

        for w in tbl.winfo_children():
            try: w.destroy()
            except Exception: pass

        pm = self._get_portfolio_monitor()
        mode = getattr(self, "_dash_portfolio_account", "paper")
        cached = pm.get_cached(mode)
        if cached is None:
            # Background refresh, render placeholder
            threading.Thread(target=lambda m=mode: pm.refresh(m), daemon=True).start()
            tk.Label(tbl, text="Loading…", font=(FONT, 9), fg=DIM,
                     bg=PANEL).pack(pady=20)
            return

        trades_raw = cached.get("trades") or cached.get("recent_trades") or []
        trades = []
        for t in trades_raw:
            res = t.get("result")
            if res not in ("WIN", "LOSS"):
                # Live API trades may not have result; derive sign-of-pnl as proxy
                pnl = float(t.get("pnl", 0) or 0)
                res = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else None
            t = dict(t)
            t["_result"] = res or "?"
            trades.append(t)

        # Apply filter
        f = self._dash_trades_filter["result"]
        if f == "win":
            trades = [t for t in trades if t["_result"] == "WIN"]
        elif f == "loss":
            trades = [t for t in trades if t["_result"] == "LOSS"]

        # Pagination
        per_page = 18
        total = len(trades)
        pages = max(1, (total + per_page - 1) // per_page)
        if self._dash_trades_page >= pages:
            self._dash_trades_page = max(0, pages - 1)
        page = self._dash_trades_page
        slice_ = trades[page * per_page:(page + 1) * per_page]

        # Header row
        hdr = tk.Frame(tbl, bg=BG3); hdr.pack(fill="x")
        cols = [("#", 4), ("SYMBOL", 12), ("SIDE", 6), ("RSLT", 5),
                ("PnL", 12), ("R-MULT", 8), ("SCORE", 7), ("TIME", 10)]
        for label, w in cols:
            tk.Label(hdr, text=label, font=(FONT, 7, "bold"),
                     fg=AMBER, bg=BG3, width=w, anchor="w",
                     padx=4, pady=3).pack(side="left")
        tk.Frame(tbl, bg=DIM2, height=1).pack(fill="x")

        for i, t in enumerate(slice_):
            row = tk.Frame(tbl, bg=PANEL); row.pack(fill="x")
            sym = (t.get("symbol") or "?").replace("USDT", "")
            side = t.get("direction") or t.get("side") or "?"
            if isinstance(side, str):
                side = "LONG" if side.upper() in ("BULLISH", "BUY", "LONG") else "SHORT"
            res = t["_result"]
            pnl = float(t.get("pnl", 0) or 0)
            pnl_col = GREEN if pnl >= 0 else RED
            entry = float(t.get("entry", 0) or 0)
            stop  = float(t.get("stop", 0) or 0)
            exit_p = float(t.get("exit_p", t.get("exit", 0)) or 0)
            risk = abs(entry - stop)
            if risk > 0:
                move = (exit_p - entry) if side == "LONG" else (entry - exit_p)
                rmult = move / risk
            else:
                rmult = 0.0
            score = float(t.get("score", 0) or 0)
            tstr  = str(t.get("time", t.get("timestamp", "")))[:10]

            vals = [
                (str(page * per_page + i + 1), DIM),
                (sym, AMBER),
                (side, WHITE),
                (res, GREEN if res == "WIN" else RED),
                (f"{'+' if pnl >= 0 else ''}${pnl:,.2f}", pnl_col),
                (f"{rmult:+.2f}R", GREEN if rmult >= 0 else RED),
                (f"{score:.2f}" if score else "—", DIM),
                (tstr, DIM),
            ]
            for (val, col), (_, w) in zip(vals, cols):
                tk.Label(row, text=val, font=(FONT, 8),
                         fg=col, bg=PANEL, width=w, anchor="w",
                         padx=4, pady=2).pack(side="left")

        if not slice_:
            # Context-aware empty state so the user knows WHY the table is empty.
            if total == 0:
                if mode == "paper":
                    empty_msg = ("paper account has no trades yet\n"
                                 "trades placed in paper mode will appear here")
                elif cached.get("status") == "no_keys":
                    empty_msg = (f"{mode.upper()} account has no API keys\n"
                                 "configure in SETTINGS > API KEYS")
                else:
                    empty_msg = f"no trades on {mode.upper()} account (last 50)"
            else:
                empty_msg = f"no trades match filter '{f.upper()}'\n(total: {total})"
            tk.Label(tbl, text=empty_msg, font=(FONT, 8),
                     fg=DIM, bg=PANEL, justify="center").pack(pady=14)

        if page_lbl:
            page_lbl.configure(text=f"Página {page + 1}/{pages}")
        if stats_lbl:
            wins = sum(1 for t in trades if t["_result"] == "WIN")
            wr = (wins / total * 100) if total else 0
            tot_pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
            stats_lbl.configure(
                text=f"Total: {total}  WR {wr:.1f}%  PnL ${tot_pnl:,.0f}")

        self.f_lbl.configure(
            text=f"TRADES · {mode.upper()} · {total} trades · "
                 f"1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit")

        if getattr(self, "_dash_alive", False) and self._dash_tab == "trades":
            aid = getattr(self, "_dash_after_id", None)
            if aid:
                try: self.after_cancel(aid)
                except Exception: pass
            self._dash_after_id = self.after(30000, self._dash_tick_refresh)

    # ── HOME TAB (personal snapshot) ───────────────────────
    def _dash_build_home_tab(self, parent):
        """CS 1.6 style HOME: connection status + account management + engines.
        No heavy aggregations — only what's immediately actionable.
        Renders instantly with cached state; background refresh is lightweight."""
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=14, pady=8)

        # ── HUD header ──
        hdr = tk.Frame(wrap, bg=BG); hdr.pack(fill="x")
        tk.Label(hdr, text="[ HOME ]", font=(FONT, 9, "bold"),
                 fg=AMBER, bg=BG).pack(side="left")
        tk.Label(hdr, text="personal control panel",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=(8, 0))
        clock_l = tk.Label(hdr, text="", font=(FONT, 7), fg=DIM2, bg=BG)
        clock_l.pack(side="right")
        self._dash_widgets[("home_clock",)] = clock_l
        tk.Frame(wrap, bg=AMBER_D, height=1).pack(fill="x", pady=(2, 8))

        # ── CONNECTIONS box ──
        def box(title, parent_):
            f = tk.Frame(parent_, bg=PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
            tk.Label(f, text=f" [ {title} ] ",
                     font=(FONT, 7, "bold"), fg=BG, bg=AMBER,
                     padx=6, pady=2).pack(side="top", anchor="nw", padx=6, pady=(6, 2))
            return f

        conn_box = box("CONNECTIONS", wrap)
        conn_box.pack(fill="x", pady=(0, 6))
        conn_inner = tk.Frame(conn_box, bg=PANEL)
        conn_inner.pack(fill="x", padx=10, pady=(0, 8))
        self._dash_widgets[("home_conn",)] = conn_inner

        # ── ACCOUNTS box ──
        acc_box = box("ACCOUNTS", wrap)
        acc_box.pack(fill="x", pady=(0, 6))
        acc_inner = tk.Frame(acc_box, bg=PANEL)
        acc_inner.pack(fill="x", padx=10, pady=(0, 8))
        self._dash_widgets[("home_accs",)] = acc_inner

        # ── ENGINES box ──
        eng_box = box("RUNNING ENGINES", wrap)
        eng_box.pack(fill="x", pady=(0, 6))
        eng_inner = tk.Frame(eng_box, bg=PANEL)
        eng_inner.pack(fill="x", padx=10, pady=(0, 8))
        self._dash_widgets[("home_engines",)] = eng_inner

        self.f_lbl.configure(
            text="HOME · connections + accounts + engines · "
                 "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit · R refresh"
        )

        # Show a brief "connecting..." placeholder inside each panel until the
        # first fetch completes and populates real data. Avoids a blank flash
        # on tab switch.
        for key in ("home_conn", "home_accs", "home_engines"):
            inner = self._dash_widgets.get((key,))
            if inner is not None:
                tk.Label(inner, text="  connecting...",
                         font=(FONT, 8), fg=DIM2, bg=PANEL,
                         anchor="w").pack(fill="x", pady=2)
        # First real render comes from _dash_home_fetch_async which is
        # invoked by _dash_render_tab right after this build method returns.

    def _dash_home_fetch_async(self):
        """Lightweight background refresh: only ping exchange + list_procs.
        Does NOT call PortfolioMonitor.refresh for live accounts (too slow) —
        only loads the paper state locally, which is instant."""
        if not getattr(self, "_dash_alive", False):
            return

        def worker():
            snap: dict = {}
            # Paper state: local file read — instant
            try:
                from core.portfolio_monitor import PortfolioMonitor
                snap["paper"] = PortfolioMonitor.paper_state_load()
            except Exception:
                snap["paper"] = None
            # Exchange latency
            try:
                snap["latency"] = _conn.ping("binance_futures")
            except Exception:
                snap["latency"] = None
            # Running engines
            try:
                from core.proc import list_procs
                snap["procs"] = list_procs()
            except Exception:
                snap["procs"] = []
            # Check which accounts have keys (instant — reads keys.json)
            try:
                pm = self._get_portfolio_monitor()
                snap["has_keys"] = {m: pm.has_keys(m)
                                    for m in ("testnet", "demo", "live")}
            except Exception:
                snap["has_keys"] = {}

            self._dash_home_snap = snap
            if getattr(self, "_dash_alive", False):
                try: self.after(0, self._dash_home_render)
                except Exception: pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_home_render(self):
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "home") != "home":
            return

        snap    = getattr(self, "_dash_home_snap", {}) or {}
        latency = snap.get("latency")
        procs   = snap.get("procs") or []
        has_keys = snap.get("has_keys") or {}
        paper_state = snap.get("paper") or {}

        # ── clock ──
        clock_l = self._dash_widgets.get(("home_clock",))
        if clock_l:
            clock_l.configure(text=datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))

        # ── CONNECTIONS panel ──
        conn = self._dash_widgets.get(("home_conn",))
        if conn:
            for w in conn.winfo_children():
                try: w.destroy()
                except Exception: pass

            # Binance Futures (the one we actively ping)
            rows = [
                ("BINANCE FUTURES", latency is not None,
                 f"{int(latency)}ms" if latency is not None else "offline"),
                ("FEAR & GREED API", True,  "public"),
                ("BINANCE PUBLIC",   True,  "public"),
            ]
            for name, ok, detail in rows:
                r = tk.Frame(conn, bg=PANEL); r.pack(fill="x", pady=1)
                tk.Label(r, text="●" if ok else "○",
                         font=(FONT, 10, "bold"),
                         fg=GREEN if ok else RED, bg=PANEL,
                         width=3).pack(side="left")
                tk.Label(r, text=name, font=(FONT, 8, "bold"),
                         fg=WHITE if ok else DIM, bg=PANEL,
                         width=20, anchor="w").pack(side="left")
                tk.Label(r, text=detail, font=(FONT, 8),
                         fg=DIM if ok else DIM2, bg=PANEL,
                         anchor="w").pack(side="left", padx=(4, 0))

        # ── ACCOUNTS panel (clickable rows + action buttons) ──
        accs = self._dash_widgets.get(("home_accs",))
        if accs:
            for w in accs.winfo_children():
                try: w.destroy()
                except Exception: pass

            pm = self._get_portfolio_monitor()
            account_defs = [
                ("paper",   "PAPER",   AMBER_D),
                ("testnet", "TESTNET", GREEN),
                ("demo",    "DEMO",    AMBER),
                ("live",    "LIVE",    RED),
            ]
            for acc_id, label, color in account_defs:
                if acc_id == "paper":
                    is_on = True
                    detail = f"${paper_state.get('current_balance', 0):,.2f}"
                    sub    = f"trades {len(paper_state.get('trades') or [])}"
                    action = "EDIT"
                else:
                    is_on = has_keys.get(acc_id, False)
                    if is_on:
                        cached = pm.get_cached(acc_id) or {}
                        eq = cached.get("equity")
                        detail = f"${eq:,.2f}" if eq is not None else "— syncing"
                        sub = "keys ok"
                    else:
                        detail = "no keys"
                        sub    = ""
                    action = "OPEN" if is_on else "CONFIG"

                r = tk.Frame(accs, bg=PANEL); r.pack(fill="x", pady=2)
                tk.Label(r, text="●" if is_on else "○",
                         font=(FONT, 10, "bold"),
                         fg=color if is_on else DIM2, bg=PANEL,
                         width=3).pack(side="left")
                tk.Label(r, text=label, font=(FONT, 9, "bold"),
                         fg=WHITE if is_on else DIM, bg=PANEL,
                         width=10, anchor="w").pack(side="left")
                tk.Label(r, text=detail, font=(FONT, 9, "bold"),
                         fg=color if is_on else DIM, bg=PANEL,
                         width=16, anchor="w").pack(side="left")
                tk.Label(r, text=sub, font=(FONT, 7),
                         fg=DIM2, bg=PANEL, anchor="w").pack(side="left")

                # Action button (right)
                btn = tk.Label(r, text=f" {action} ",
                               font=(FONT, 7, "bold"),
                               fg=BG, bg=color if is_on else DIM2,
                               cursor="hand2", padx=6, pady=2)
                btn.pack(side="right", padx=(0, 4))

                def _act(_e=None, a=acc_id, on=is_on):
                    if a == "paper":
                        self._dash_paper_edit_dialog()
                    elif on:
                        self._dash_portfolio_account = a
                        self._dash_render_tab("portfolio")
                    else:
                        # No keys — jump to settings
                        self._dash_alive = False
                        self._config()

                for w in (r, btn):
                    w.bind("<Button-1>", _act)
                    w.bind("<Enter>", lambda e, b=btn: b.configure(bg=AMBER_B))
                    w.bind("<Leave>", lambda e, b=btn, c=color, on=is_on:
                           b.configure(bg=c if on else DIM2))

        # ── ENGINES panel ──
        eng = self._dash_widgets.get(("home_engines",))
        if eng:
            for w in eng.winfo_children():
                try: w.destroy()
                except Exception: pass

            alive = [p for p in procs if p.get("alive")]
            summary = tk.Frame(eng, bg=PANEL); summary.pack(fill="x", pady=(0, 2))
            tk.Label(summary,
                     text=f"{len(alive)} running  ·  {len(procs) - len(alive)} finished",
                     font=(FONT, 7), fg=DIM, bg=PANEL,
                     anchor="w").pack(side="left")

            if not alive:
                tk.Label(eng, text="○ no engines running",
                         font=(FONT, 8), fg=DIM, bg=PANEL,
                         anchor="w").pack(fill="x", pady=2)
                tk.Label(eng, text="go to PORTFOLIO (3) or COCKPIT (6) to start",
                         font=(FONT, 7), fg=DIM2, bg=PANEL,
                         anchor="w").pack(fill="x")
            else:
                for p in alive[:6]:
                    eng_name = str(p.get("engine", "?")).upper()
                    pid  = p.get("pid", "?")
                    started = str(p.get("started", ""))[:19].replace("T", " ")
                    r = tk.Frame(eng, bg=PANEL); r.pack(fill="x", pady=1)
                    tk.Label(r, text="●", font=(FONT, 10, "bold"),
                             fg=GREEN, bg=PANEL, width=3).pack(side="left")
                    tk.Label(r, text=eng_name, font=(FONT, 8, "bold"),
                             fg=AMBER, bg=PANEL, width=14,
                             anchor="w").pack(side="left")
                    tk.Label(r, text=f"PID {pid}", font=(FONT, 7),
                             fg=DIM, bg=PANEL, width=10,
                             anchor="w").pack(side="left")
                    tk.Label(r, text=started, font=(FONT, 7),
                             fg=DIM2, bg=PANEL,
                             anchor="w").pack(side="left")

        # Header status
        if latency is not None:
            self.h_stat.configure(text="ONLINE", fg=GREEN)
        else:
            self.h_stat.configure(text="OFFLINE", fg=RED)

        # Reschedule — HOME refresh is lightweight, 10s is fine
        if getattr(self, "_dash_alive", False) and self._dash_tab == "home":
            aid = getattr(self, "_dash_after_id", None)
            if aid:
                try: self.after_cancel(aid)
                except Exception: pass
            self._dash_after_id = self.after(10000, self._dash_tick_refresh)

    # ── BACKTEST TAB (browse data/runs/) ───────────────────
    def _dash_build_backtest_tab(self, parent):
        """Two-column browser: list of runs (left) + detail panel (right).
        Click a row to show its real metrics from summary.json inline.
        Detail panel has a secondary button to open report.html in a browser."""
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=14, pady=8)

        hdr = tk.Frame(wrap, bg=BG); hdr.pack(fill="x")
        tk.Label(hdr, text="[ BACKTEST ]", font=(FONT, 9, "bold"),
                 fg=AMBER, bg=BG).pack(side="left")
        count_l = tk.Label(hdr, text="", font=(FONT, 7), fg=DIM, bg=BG)
        count_l.pack(side="right")
        self._dash_widgets[("bt_count",)] = count_l
        tk.Frame(wrap, bg=AMBER_D, height=1).pack(fill="x", pady=(2, 8))

        # Main split: list (left, 60%) + detail (right, 40%)
        split = tk.Frame(wrap, bg=BG); split.pack(fill="both", expand=True)

        # ── LEFT: run list ──
        left = tk.Frame(split, bg=BG)
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))

        # Column headers — widths pulled from _BT_COLS so header and row
        # widgets always render at the same character positions. Same
        # font size (8, bold dim) as the rows in _dash_backtest_render,
        # otherwise monospace char widths desync and the whole list
        # skews by a few pixels per column.
        hrow = tk.Frame(left, bg=BG); hrow.pack(fill="x")
        for label, width in _BT_COLS:
            tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=width,
                     anchor="w").pack(side="left")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        # Scrollable list (Canvas + inner frame)
        canvas_wrap = tk.Frame(left, bg=BG)
        canvas_wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_wrap, bg=BG, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=inner, anchor="nw")
        def _on_configure(event, c=canvas): c.configure(scrollregion=c.bbox("all"))
        inner.bind("<Configure>", _on_configure)

        # Mouse wheel — scoped: only active while the mouse is over the list.
        # Using bind_all would leak the handler to every other tab.
        def _on_wheel(event, c=canvas):
            try: c.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError: pass
        def _enter(_e=None, c=canvas):
            c.bind_all("<MouseWheel>", _on_wheel)
        def _leave(_e=None, c=canvas):
            try: c.unbind_all("<MouseWheel>")
            except tk.TclError: pass
        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)
        inner.bind("<Enter>", _enter)
        inner.bind("<Leave>", _leave)

        self._dash_widgets[("bt_list",)] = inner
        self._dash_widgets[("bt_canvas",)] = canvas

        # ── RIGHT: detail panel ──
        right = tk.Frame(split, bg=PANEL,
                         highlightbackground=BORDER, highlightthickness=1,
                         width=300)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        tk.Label(right, text=" [ DETAILS ] ",
                 font=(FONT, 7, "bold"), fg=BG, bg=AMBER,
                 padx=6, pady=2).pack(anchor="nw", padx=6, pady=(6, 2))

        detail_body = tk.Frame(right, bg=PANEL)
        detail_body.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._dash_widgets[("bt_detail",)] = detail_body

        # Initial placeholder
        tk.Label(detail_body,
                 text="\n← click a run to load its metrics",
                 font=(FONT, 8), fg=DIM, bg=PANEL,
                 justify="left").pack(anchor="w")

        self.f_lbl.configure(
            text="BACKTEST · click row for details · "
                 "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit · R refresh"
        )

        self._dash_backtest_render()

    @staticmethod
    def _bt_fmt_timestamp(ts_raw) -> str:
        """Format a run timestamp as 'YYYY-MM-DD  HH:MM'. Accepts:
        - ISO string: '2026-04-10T11:50:23.123'
        - Unix seconds: 1712745023 (int or float)
        - Unix milliseconds: 1712745023000 (int or float)
        - None / empty / unparseable → '—'"""
        if ts_raw is None or ts_raw == "":
            return "—"
        # Numeric (unix timestamp)
        if isinstance(ts_raw, (int, float)):
            try:
                # Treat values > 1e12 as milliseconds, otherwise seconds
                t = float(ts_raw)
                if t > 1e12:
                    t /= 1000.0
                return datetime.fromtimestamp(t).strftime("%Y-%m-%d  %H:%M")
            except (ValueError, OSError, OverflowError):
                return "—"
        # String
        try:
            dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d  %H:%M")
        except (ValueError, TypeError):
            return str(ts_raw)[:16].replace("T", " ")

    def _bt_read_json(self, path: Path) -> dict:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError):
            return {}

    def _bt_legacy_engine_dirs(self) -> list[Path]:
        # Engine-specific run dirs use institutional names (post-rename
        # commit). Skip set covers shared/non-engine dirs that should
        # never be treated as engine runs by the dashboard scanner.
        data_dir = ROOT / "data"
        skip = {
            ".proc_logs", "runs", "audit", "exports",
            "funding_scanner", "live", "param_search", "validation",
            "janestreet",  # scanner snapshots, not backtests
            "aqr",          # aggregator, reads from other engines
        }
        try:
            return sorted(
                [
                    p for p in data_dir.iterdir()
                    if p.is_dir() and p.name not in skip and not p.name[:4].isdigit()
                ]
            )
        except OSError:
            return []

    def _bt_report_candidates(self, run_dir: Path) -> list[Path]:
        rep_dir = run_dir / "reports"
        if not rep_dir.exists():
            return []
        skip_names = {
            "config.json", "equity.json", "index.json", "overfit.json",
            "price_data.json", "summary.json", "trades.json",
            "simulate_historical.json",
        }
        try:
            files = [
                p for p in rep_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".json" and p.name not in skip_names
            ]
        except OSError:
            return []
        files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        return files

    def _bt_entry_from_report(self, engine_dir: Path, run_dir: Path, report_path: Path) -> dict:
        report = self._bt_read_json(report_path)
        engine_name = str(report.get("engine") or engine_dir.name).strip()
        engine_slug = canonical_engine_key(engine_name)
        raw_run_id = str(report.get("run_id") or run_dir.name).strip() or run_dir.name
        run_id = raw_run_id if raw_run_id.startswith(f"{engine_slug}_") else f"{engine_slug}_{raw_run_id}"
        account_size = report.get("account_size")
        final_equity = report.get("final_equity")
        pnl = report.get("pnl")
        if pnl is None and account_size is not None and final_equity is not None:
            try:
                pnl = float(final_equity) - float(account_size)
            except (TypeError, ValueError):
                pnl = None

        report_html = run_dir / "report.html"
        if not report_html.exists():
            try:
                html_candidates = [p for p in (run_dir / "reports").iterdir() if p.suffix.lower() == ".html"]
            except OSError:
                html_candidates = []
            if html_candidates:
                html_candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
                report_html = html_candidates[0]

        return {
            "run_id": run_id,
            "engine": engine_slug,
            "timestamp": report.get("timestamp"),
            "interval": report.get("interval"),
            "period_days": report.get("period_days"),
            "basket": report.get("basket", "default"),
            "n_symbols": report.get("n_symbols"),
            "n_candles": report.get("n_candles"),
            "n_trades": report.get("n_trades"),
            "win_rate": report.get("win_rate"),
            "pnl": pnl,
            "roi_pct": report.get("roi_pct", report.get("roi")),
            "sharpe": report.get("sharpe"),
            "sortino": report.get("sortino"),
            "max_dd_pct": report.get("max_dd_pct", report.get("max_dd")),
            "account_size": account_size,
            "leverage": report.get("leverage"),
            "final_equity": final_equity,
            "summary_path": str(report_path),
            "config_path": str(run_dir / "config.json"),
            "report_html_path": str(report_html) if report_html.exists() else "",
            "run_dir": str(run_dir),
            "source": "legacy",
        }

    def _bt_collect_runs(self) -> list[dict]:
        idx_path = ROOT / "data" / "index.json"
        runs_by_id: dict[str, dict] = {}

        # engine slug → actual data dir (for post-rename paths)
        _SLUG_TO_DIR = {
            "citadel":     ROOT / "data" / "runs",
            "bridgewater": ROOT / "data" / "bridgewater",
            "jump":        ROOT / "data" / "jump",
            "deshaw":      ROOT / "data" / "deshaw",
            "renaissance": ROOT / "data" / "renaissance",
            "janestreet":  ROOT / "data" / "janestreet",
            "millennium":  ROOT / "data" / "millennium",
            "twosigma":    ROOT / "data" / "twosigma",
            "aqr":         ROOT / "data" / "aqr",
        }

        if idx_path.exists():
            try:
                rows = json.loads(idx_path.read_text(encoding="utf-8"))
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        run_id = str(row.get("run_id") or "").strip()
                        if not run_id:
                            continue
                        # Resolve run_dir via engine slug — run_ids are now
                        # prefixed (e.g. "bridgewater_2026-04-14_1029")
                        engine_slug = str(row.get("engine") or "").lower()
                        base_dir = _SLUG_TO_DIR.get(engine_slug, ROOT / "data" / "runs")
                        # Strip engine prefix from run_id to get folder name
                        folder = run_id
                        if engine_slug and folder.startswith(f"{engine_slug}_"):
                            folder = folder[len(engine_slug) + 1:]
                        run_dir = base_dir / folder
                        # Citadel keeps the prefixed form as folder name
                        if engine_slug == "citadel" and not run_dir.exists():
                            run_dir = base_dir / run_id
                        entry = dict(row)
                        entry.setdefault("run_dir", str(run_dir))
                        entry.setdefault("summary_path", str(run_dir / "summary.json"))
                        entry.setdefault("config_path", str(run_dir / "config.json"))
                        report_html = run_dir / "report.html"
                        entry.setdefault("report_html_path", str(report_html) if report_html.exists() else "")
                        entry.setdefault("source", "index")
                        # Fallback: read summary.json for fields that might be
                        # missing in older index entries (basket, period_days...)
                        if not entry.get("basket"):
                            try:
                                _sj = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
                                entry["basket"] = _sj.get("basket") or "default"
                                if not entry.get("period_days"):
                                    entry["period_days"] = _sj.get("period_days")
                                if not entry.get("interval"):
                                    entry["interval"] = _sj.get("interval")
                            except (OSError, json.JSONDecodeError):
                                pass
                        runs_by_id[run_id] = entry
            except (json.JSONDecodeError, OSError, TypeError):
                pass

        runs_root = ROOT / "data" / "runs"
        if runs_root.exists():
            try:
                for run_dir in runs_root.iterdir():
                    if not run_dir.is_dir():
                        continue
                    run_id = run_dir.name
                    summary_path = run_dir / "summary.json"
                    config_path = run_dir / "config.json"
                    summary = self._bt_read_json(summary_path)
                    config = self._bt_read_json(config_path)
                    entry = runs_by_id.get(run_id, {}).copy()
                    entry.setdefault("run_id", run_id)
                    entry.setdefault("engine", str(entry.get("engine") or run_id.split("_", 1)[0]).lower())
                    entry.setdefault("timestamp", summary.get("timestamp"))
                    entry.setdefault("interval", summary.get("interval", config.get("INTERVAL", config.get("ENTRY_TF"))))
                    entry.setdefault("period_days", summary.get("period_days", config.get("SCAN_DAYS")))
                    entry.setdefault("basket", summary.get("basket", config.get("BASKET_EFFECTIVE", "default")))
                    entry.setdefault("n_symbols", summary.get("n_symbols"))
                    entry.setdefault("n_candles", summary.get("n_candles", config.get("N_CANDLES")))
                    entry.setdefault("n_trades", summary.get("n_trades"))
                    entry.setdefault("win_rate", summary.get("win_rate"))
                    entry.setdefault("pnl", summary.get("pnl", summary.get("total_pnl")))
                    entry.setdefault("roi_pct", summary.get("roi_pct", summary.get("roi")))
                    entry.setdefault("sharpe", summary.get("sharpe"))
                    entry.setdefault("sortino", summary.get("sortino"))
                    entry.setdefault("max_dd_pct", summary.get("max_dd_pct", summary.get("max_dd")))
                    entry.setdefault("account_size", summary.get("account_size", config.get("ACCOUNT_SIZE")))
                    entry.setdefault("leverage", summary.get("leverage", config.get("LEVERAGE")))
                    entry.setdefault("final_equity", summary.get("final_equity"))
                    entry["run_dir"] = str(run_dir)
                    entry["summary_path"] = str(summary_path)
                    entry["config_path"] = str(config_path)
                    report_html = run_dir / "report.html"
                    entry["report_html_path"] = str(report_html) if report_html.exists() else entry.get("report_html_path", "")
                    entry.setdefault("source", "runs")
                    runs_by_id[run_id] = entry
            except OSError:
                pass

        for engine_dir in self._bt_legacy_engine_dirs():
            try:
                run_dirs = [p for p in engine_dir.iterdir() if p.is_dir()]
            except OSError:
                continue
            for run_dir in run_dirs:
                report_files = self._bt_report_candidates(run_dir)
                if not report_files:
                    continue
                entry = self._bt_entry_from_report(engine_dir, run_dir, report_files[0])
                runs_by_id.setdefault(entry["run_id"], entry)

        runs = list(runs_by_id.values())
        runs.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
        self._bt_run_map = {str(r.get("run_id")): r for r in runs if r.get("run_id")}
        self._bt_recent_run_id = runs[0]["run_id"] if runs else None
        return runs

    def _bt_resolve_run(self, run_id: str) -> dict:
        cache = getattr(self, "_bt_run_map", {}) or {}
        row = cache.get(run_id)
        if row:
            return row
        for row in self._bt_collect_runs():
            if row.get("run_id") == run_id:
                return row
        return {}

    def _dash_backtest_render(self):
        list_wrap = self._dash_widgets.get(("bt_list",))
        count_l   = self._dash_widgets.get(("bt_count",))
        if list_wrap is None:
            return
        try:
            if not list_wrap.winfo_exists():
                return
        except Exception:
            return

        for w in list_wrap.winfo_children():
            try: w.destroy()
            except Exception: pass

        runs = self._bt_collect_runs()

        if count_l:
            count_l.configure(text=f"{len(runs)} runs")

        if not runs:
            tk.Label(list_wrap, text="  — no runs found in data/runs/ —",
                     font=(FONT, 8), fg=DIM, bg=BG,
                     anchor="w").pack(fill="x", pady=10)
            return

        def _fmt_n(v, suffix=""): return f"{v:.2f}{suffix}" if v is not None else "—"
        def _fmt_m(v): return f"${v:+,.0f}" if v is not None else "—"
        # Code-name → institutional-name (battery/marketing taxonomy).
        # Maps both legacy lowercase file names (thoth, mercurio, newton)
        # and uppercase variants. Falls back to upper() for unknowns.
        _ENGINE_NAMES = {
            "backtest":      "CITADEL",
            "citadel":       "CITADEL",
            "thoth":         "BRIDGEWATER",
            "bridgewater":   "BRIDGEWATER",
            "mercurio":      "JUMP",
            "jump":          "JUMP",
            "newton":        "DE SHAW",
            "deshaw":        "DE SHAW",
            "de_shaw":       "DE SHAW",
            "prometeu":      "TWO SIGMA",
            "twosigma":      "TWO SIGMA",
            "two_sigma":     "TWO SIGMA",
            "darwin":        "AQR",
            "aqr":           "AQR",
            "multistrategy": "MILLENNIUM",
            "millennium":    "MILLENNIUM",
            "harmonics":     "RENAISSANCE",
            "harmonics_backtest": "RENAISSANCE",
            "renaissance":   "RENAISSANCE",
            "arbitrage":     "JANE STREET",
            "jane_street":   "JANE STREET",
            "janestreet":    "JANE STREET",
        }
        def _fmt_engine(v):
            raw = str(v or "—").strip().lower()
            name = _ENGINE_NAMES.get(raw, raw.replace("_", " ").upper())
            return name[:13]

        # [Backlog #7] Pre-L6 warning badge for engines whose pre-fix
        # reports are potentially inflated. Runs written before commit
        # ea1f6ba (2026-04-11) are tagged in the RUN column with a "⚠"
        # prefix. All five engines that only got the aggregate notional
        # cap in that commit are flagged; historical runs of citadel
        # (backtest.py) are untagged because L6 landed earlier there.
        _L6_FIX_DATE = "2026-04-11"
        _L6_AFFECTED = {"mercurio", "thoth", "harmonics", "newton",
                         "multistrategy"}

        for run in runs[:50]:
            run_id = run.get("run_id", "?")
            engine = str(run.get("engine") or "").lower()
            ts_raw = run.get("timestamp") or ""
            ts     = self._bt_fmt_timestamp(ts_raw)
            tf     = str(run.get("interval") or "—")
            days   = run.get("period_days")
            days_s = f"{int(days)}" if days else "—"
            basket = str(run.get("basket") or "—")[:9]
            n_tr   = run.get("n_trades") or 0
            wr     = run.get("win_rate")
            pnl    = run.get("pnl")
            sh     = run.get("sharpe")
            dd     = run.get("max_dd_pct")

            pre_l6 = (engine in _L6_AFFECTED
                      and isinstance(ts_raw, str)
                      and ts_raw < _L6_FIX_DATE)

            row = tk.Frame(list_wrap, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=0)

            pnl_col = GREEN if (pnl or 0) > 0 else (RED if (pnl or 0) < 0 else DIM)
            short_id = run_id
            for prefix in (
                "citadel_", "thoth_", "bridgewater_", "newton_", "deshaw_",
                "mercurio_", "jump_", "multistrategy_", "millennium_",
                "prometeu_", "twosigma_", "renaissance_", "harmonics_",
            ):
                if short_id.startswith(prefix):
                    short_id = short_id[len(prefix):]
                    break
            if pre_l6:
                short_id = ("! " + short_id)[:13]
            else:
                short_id = short_id[:13]

            # Widths pulled from _BT_COLS to guarantee header ↔ row parity.
            (_dw, _ew, _tfw, _dyw, _bkw, _rw, _tw, _ww, _pw, _shw, _ddw) = [w for _, w in _BT_COLS]
            # Pre-L6 runs render the RUN cell in RED to match the "!"
            # prefix; the rest of the row keeps its normal coloring so
            # the PnL/Sharpe contrast still works.
            run_col = RED if pre_l6 else AMBER
            cells = [
                (ts,                  _dw,  WHITE,   "normal"),
                (_fmt_engine(engine), _ew,  AMBER,   "bold"),
                (tf,                  _tfw, AMBER_D, "normal"),
                (days_s,              _dyw, WHITE,   "normal"),
                (basket,              _bkw, WHITE,   "normal"),
                (short_id,            _rw,  run_col, "bold"),
                (f"{n_tr}",           _tw,  WHITE,   "normal"),
                (_fmt_n(wr),          _ww,  WHITE,   "normal"),
                (_fmt_m(pnl),         _pw,  pnl_col, "bold"),
                (_fmt_n(sh),          _shw, WHITE,   "normal"),
                (_fmt_n(dd, "%"),     _ddw,
                 RED if (dd or 0) > 5 else DIM, "normal"),
            ]
            row_labels = []
            for text, width, color, weight in cells:
                lbl = tk.Label(row, text=text,
                               font=(FONT, 8, weight),
                               fg=color, bg=BG, width=width, anchor="w")
                lbl.pack(side="left")
                row_labels.append(lbl)

            def _select(_e=None, rid=run_id):
                self._dash_backtest_select(rid)
            def _enter(_e=None, labels=row_labels):
                for l in labels:
                    try: l.configure(bg=BG3)
                    except Exception: pass
            def _leave(_e=None, labels=row_labels):
                for l in labels:
                    try: l.configure(bg=BG)
                    except Exception: pass

            for w in (row, *row_labels):
                w.bind("<Button-1>", _select)
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

    def _dash_backtest_select(self, run_id: str):
        """Load the full summary.json for a run and populate the detail panel."""
        body = self._dash_widgets.get(("bt_detail",))
        if body is None:
            return
        try:
            if not body.winfo_exists():
                return
        except Exception:
            return

        for w in body.winfo_children():
            try: w.destroy()
            except Exception: pass

        run_meta = self._bt_resolve_run(run_id)
        run_dir = Path(run_meta.get("run_dir")) if run_meta.get("run_dir") else (ROOT / "data" / "runs" / run_id)
        summary_path = Path(run_meta.get("summary_path")) if run_meta.get("summary_path") else (run_dir / "summary.json")
        config_path  = Path(run_meta.get("config_path")) if run_meta.get("config_path") else (run_dir / "config.json")

        # Index entry for timestamp + period_days fallback
        idx_entry = dict(run_meta) if run_meta else {}

        summary: dict = {}
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        config: dict = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        # Header: run_id + timestamp
        tk.Label(body, text=run_id, font=(FONT, 9, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w",
                 wraplength=270, justify="left").pack(fill="x")
        ts_raw = idx_entry.get("timestamp") or summary.get("timestamp") or ""
        tk.Label(body, text=self._bt_fmt_timestamp(ts_raw),
                 font=(FONT, 8), fg=DIM, bg=PANEL,
                 anchor="w").pack(fill="x", pady=(0, 4))
        tk.Frame(body, bg=DIM2, height=1).pack(fill="x", pady=(0, 6))

        # === PRIMARY ACTIONS — at the top of the detail panel ===
        # Buttons render here FIRST, right after the header. The metric
        # blocks below can be as tall as they want; OPEN HTML and DELETE
        # are always visible regardless of window height or right-panel
        # overflow. Previously they lived at the bottom of the panel and
        # were clipped off-screen when the metric content was taller than
        # the window — user saw "no buttons" even though they were wired
        # correctly, just rendered below the fold.
        actions = tk.Frame(body, bg=PANEL)
        actions.pack(fill="x", anchor="w", pady=(0, 4))

        report = run_dir / "report.html"
        if report.exists():
            btn = tk.Label(actions, text="  OPEN HTML  ",
                           font=(FONT, 8, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2",
                           padx=8, pady=5)
            btn.pack(side="left", padx=(0, 4))
            btn.bind("<Button-1>", lambda e: self._dash_backtest_open(run_id))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=AMBER_B))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=AMBER))

        del_btn = tk.Label(actions, text="  DELETE  ",
                           font=(FONT, 8, "bold"),
                           fg=WHITE, bg=RED, cursor="hand2",
                           padx=8, pady=5)
        del_btn.pack(side="left")
        del_btn.bind("<Button-1>", lambda e: self._dash_backtest_delete(run_id))
        del_btn.bind("<Enter>", lambda e, b=del_btn: b.configure(bg="#c00000"))
        del_btn.bind("<Leave>", lambda e, b=del_btn: b.configure(bg=RED))

        tk.Frame(body, bg=DIM2, height=1).pack(fill="x", pady=(8, 4))

        if not summary and not idx_entry:
            tk.Label(body, text="\n✗ summary.json missing",
                     font=(FONT, 8), fg=RED, bg=PANEL).pack(anchor="w")
            return

        # Metric rows — use summary first, fall back to index entry
        def g(key, default=None):
            return summary.get(key, idx_entry.get(key, default))

        pnl   = g("pnl", g("total_pnl"))
        roi   = g("roi_pct", g("roi"))
        dd    = g("max_dd_pct", g("max_dd"))
        wr    = g("win_rate")
        sh    = g("sharpe")
        so    = g("sortino")
        ca    = g("calmar")
        ntr   = g("n_trades")
        ns    = g("n_symbols")
        nc    = g("n_candles")
        pd    = g("period_days")
        interval = g("interval")
        fe    = g("final_equity")
        acct  = g("account_size")
        lev   = g("leverage")

        def row(label, value, color=WHITE, bold=False):
            r = tk.Frame(body, bg=PANEL); r.pack(fill="x", pady=1)
            tk.Label(r, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, width=12,
                     anchor="w").pack(side="left")
            tk.Label(r, text=value,
                     font=(FONT, 8, "bold" if bold else "normal"),
                     fg=color, bg=PANEL, anchor="w").pack(side="left")

        def _fn(v, suf="", digits=2):
            if v is None: return "—"
            try: return f"{float(v):.{digits}f}{suf}"
            except (TypeError, ValueError): return "—"
        def _fm(v):
            if v is None: return "—"
            try: return f"${float(v):+,.2f}"
            except (TypeError, ValueError): return "—"

        pnl_col = GREEN if (pnl or 0) > 0 else (RED if (pnl or 0) < 0 else DIM)

        # === PERFORMANCE block ===
        tk.Label(body, text="PERFORMANCE", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(fill="x", pady=(4, 2))
        row("PnL",       _fm(pnl),            pnl_col, bold=True)
        row("ROI",       _fn(roi, "%"),       pnl_col, bold=True)
        row("Sharpe",    _fn(sh),             WHITE)
        row("Sortino",   _fn(so),             WHITE)
        row("Calmar",    _fn(ca),             WHITE)
        row("Max DD",    _fn(dd, "%"),
            RED if (dd or 0) > 5 else AMBER_D)

        # === TRADES block ===
        tk.Label(body, text="TRADES", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(fill="x", pady=(8, 2))
        row("Total",      str(ntr) if ntr is not None else "—")
        row("Win rate",   _fn(wr, "%"))
        row("Symbols",    str(ns) if ns is not None else "—")
        row("Candles",    f"{nc:,}" if isinstance(nc, (int, float)) else "—")

        # === CONFIG block ===
        tk.Label(body, text="CONFIG", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(fill="x", pady=(8, 2))
        row("Interval",   str(interval or "—"))
        row("Period",     f"{pd} days" if pd else "—")
        row("Account",    _fm(acct) if acct else "—")
        row("Leverage",   f"{lev}x" if lev else "—")
        row("Final eq",   _fm(fe))

        # Config hash (small) — last entry in the metric stack. The
        # action buttons are already rendered at the top of the panel,
        # so there's nothing below this line.
        ch = g("config_hash")
        if ch:
            tk.Label(body, text=f"hash  {str(ch)[:16]}...",
                     font=(FONT, 6), fg=DIM2, bg=PANEL,
                     anchor="w").pack(fill="x", pady=(8, 0))

    def _dash_backtest_delete(self, run_id: str):
        """Delete a backtest run — index row first, disk second.

        Ordering matters: we remove the row from data/index.json BEFORE
        trying to rmtree the directory. The JSON write is atomic and
        always succeeds; the filesystem delete can fail transiently on
        Windows + OneDrive when the sync engine has a handle on
        freshly-closed files. Doing the index edit first means:

        - The run disappears from the user's UI immediately (the row is
          re-rendered without it).
        - If the disk delete fails, the run is effectively tombstoned —
          hidden from all UI code paths — and reconcile_runs.py can
          clean up the leftover directory later.
        - The user never sees "I clicked DELETE, nothing happened" — the
          worst case is "deleted from view, disk cleanup deferred" with
          an explicit messagebox explaining what to do.

        Any exception is caught and surfaced via messagebox.showerror so
        silent failures (previous bug) can't hide behind a 2s h_stat flash.
        """
        if not messagebox.askyesno(
                "Delete backtest",
                f"Apagar definitivamente o run\n\n  {run_id}\n\n"
                f"Todos os ficheiros em data/runs/{run_id}/ serão removidos."):
            return

        try:
            from core.fs import robust_rmtree
            idx_path = ROOT / "data" / "index.json"
            run_dir = Path((getattr(self, "_bt_run_map", {}) or {}).get(run_id, {}).get("run_dir") or (ROOT / "data" / "runs" / run_id))

            # ── Step 1: remove the row from index.json (atomic). ──
            index_removed = False
            if idx_path.exists():
                try:
                    idx = json.loads(idx_path.read_text(encoding="utf-8"))
                    if isinstance(idx, list):
                        before = len(idx)
                        idx = [r for r in idx if r.get("run_id") != run_id]
                        if len(idx) != before:
                            atomic_write_json(idx_path, idx, indent=2)
                            index_removed = True
                except (json.JSONDecodeError, OSError) as e:
                    messagebox.showerror(
                        "Delete failed — index.json",
                        f"Could not update data/index.json:\n\n{e}")
                    return

            # ── Step 2: clear the detail panel + refresh the list. ──
            body = self._dash_widgets.get(("bt_detail",))
            if body is not None:
                try:
                    for w in body.winfo_children():
                        w.destroy()
                    tk.Label(body, text="  — deleted —",
                             font=(FONT, 8), fg=DIM, bg=PANEL,
                             anchor="w").pack(fill="x", pady=10)
                except tk.TclError:
                    pass
            self._dash_backtest_render()

            # ── Step 3: disk delete (best-effort, robust against locks). ──
            disk_removed = True
            if run_dir.exists():
                disk_removed = robust_rmtree(run_dir)

            # ── Step 4: report. ──
            if index_removed and disk_removed:
                self.h_stat.configure(text=f"DELETED {run_id[:20]}", fg=AMBER)
                self.after(2000,
                           lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            elif index_removed and not disk_removed:
                # The most common failure mode: OneDrive lock on an empty
                # charts/ or similar. The run is already hidden; we just
                # surface the disk leftover so the user knows to retry.
                self.h_stat.configure(text="DELETED (disk cleanup deferred)",
                                      fg=AMBER_D)
                self.after(3000,
                           lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
                messagebox.showinfo(
                    "Disk cleanup deferred",
                    f"The run has been removed from the backtest list.\n\n"
                    f"However, the directory\n\n"
                    f"  data/runs/{run_id}/\n\n"
                    f"could not be deleted right now — usually OneDrive / "
                    f"antivirus is still holding a handle on a file inside.\n\n"
                    f"Run `python tools/reconcile_runs.py --apply` in a "
                    f"minute or two and it will be cleaned up automatically.")
            else:
                # Neither index nor disk changed — the run_id probably
                # wasn't in the index and the directory is already gone
                # or locked. Say so clearly.
                self.h_stat.configure(text="NOTHING TO DELETE", fg=AMBER_D)
                self.after(2000,
                           lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
        except Exception as e:
            # Last-resort: any unexpected exception goes to a messagebox
            # instead of being swallowed. Silent failures are what got us
            # here in the first place.
            messagebox.showerror(
                "Delete failed — unexpected error",
                f"{type(e).__name__}: {e}")

    def _dash_backtest_open(self, run_id: str):
        """Open the HTML report for a given run in the default browser."""
        run_meta = self._bt_resolve_run(run_id)
        report_path = str(run_meta.get("report_html_path") or "")
        report = Path(report_path) if report_path else (ROOT / "data" / "runs" / run_id / "report.html")
        if not report.exists():
            self.h_stat.configure(text="NO REPORT", fg=RED)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            return
        try:
            import webbrowser
            webbrowser.open(report.as_uri())
            self.h_stat.configure(text="OPENED", fg=GREEN)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
        except Exception:
            self.h_stat.configure(text="OPEN FAILED", fg=RED)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))

    # ── COCKPIT TAB (VPS remote control over SSH) ─────────
    def _dash_build_cockpit_tab(self, parent):
        """VPS remote cockpit: screen session status, positions, controls, logs."""
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=14, pady=10)

        # ── Header ──
        hdr = tk.Frame(wrap, bg=BG); hdr.pack(fill="x", pady=(0, 6))
        tk.Label(hdr, text="VPS REMOTE COCKPIT", font=(FONT, 9, "bold"),
                 fg=AMBER, bg=BG).pack(side="left")
        reach_l = tk.Label(hdr, text="○ checking VPS...",
                           font=(FONT, 8), fg=DIM, bg=BG)
        reach_l.pack(side="right")
        self._dash_widgets[("cp_reach",)] = reach_l
        tk.Frame(wrap, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))

        # ── STATUS row: VPS info + engine status, side-by-side ──
        row1 = tk.Frame(wrap, bg=BG); row1.pack(fill="x", pady=(0, 8))

        vps_box = tk.Frame(row1, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1)
        vps_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        tk.Label(vps_box, text=" VPS ", font=(FONT, 7, "bold"),
                 fg=BG, bg=AMBER).pack(side="top", anchor="nw", padx=8, pady=4)
        vps_inner = tk.Frame(vps_box, bg=PANEL); vps_inner.pack(fill="x", padx=12, pady=(0, 10))
        tk.Label(vps_inner, text=f"host:     {VPS_HOST}",
                 font=(FONT, 8), fg=WHITE, bg=PANEL,
                 anchor="w").pack(fill="x")
        tk.Label(vps_inner, text=f"project:  {VPS_PROJECT}",
                 font=(FONT, 8), fg=WHITE, bg=PANEL,
                 anchor="w").pack(fill="x")
        vps_check_l = tk.Label(vps_inner, text="last check: —",
                               font=(FONT, 7), fg=DIM2, bg=PANEL, anchor="w")
        vps_check_l.pack(fill="x", pady=(4, 0))
        self._dash_widgets[("cp_check",)] = vps_check_l

        eng_box = tk.Frame(row1, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1)
        eng_box.pack(side="left", fill="both", expand=True, padx=(6, 0))
        tk.Label(eng_box, text=" ENGINE ", font=(FONT, 7, "bold"),
                 fg=BG, bg=AMBER).pack(side="top", anchor="nw", padx=8, pady=4)
        eng_inner = tk.Frame(eng_box, bg=PANEL); eng_inner.pack(fill="x", padx=12, pady=(0, 10))
        eng_state_l = tk.Label(eng_inner, text="○ checking...",
                               font=(FONT, 13, "bold"), fg=DIM, bg=PANEL,
                               anchor="w")
        eng_state_l.pack(anchor="w")
        eng_sub_l = tk.Label(eng_inner, text="screen session: —",
                             font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w")
        eng_sub_l.pack(anchor="w", pady=(2, 0))
        self._dash_widgets[("cp_engine_state",)] = eng_state_l
        self._dash_widgets[("cp_engine_sub",)]   = eng_sub_l

        # ── POSITIONS card ──
        pos_box = tk.Frame(wrap, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1)
        pos_box.pack(fill="x", pady=(0, 8))
        pos_head = tk.Label(pos_box, text=" OPEN POSITIONS (0) ",
                            font=(FONT, 7, "bold"), fg=BG, bg=AMBER)
        pos_head.pack(side="top", anchor="nw", padx=8, pady=4)
        pos_inner = tk.Frame(pos_box, bg=PANEL); pos_inner.pack(fill="x", padx=12, pady=(0, 8))
        self._dash_widgets[("cp_pos_head",)]  = pos_head
        self._dash_widgets[("cp_pos_inner",)] = pos_inner

        # ── CONTROLS row ──
        ctrl_box = tk.Frame(wrap, bg=PANEL,
                            highlightbackground=BORDER, highlightthickness=1)
        ctrl_box.pack(fill="x", pady=(0, 8))
        tk.Label(ctrl_box, text=" CONTROLS ", font=(FONT, 7, "bold"),
                 fg=BG, bg=AMBER).pack(side="top", anchor="nw", padx=8, pady=4)
        ctrl_inner = tk.Frame(ctrl_box, bg=PANEL); ctrl_inner.pack(fill="x", padx=12, pady=(0, 10))

        buttons = [
            ("START DEMO", GREEN, self._dash_cockpit_start_demo),
            ("STOP",       RED,   self._dash_cockpit_stop),
            ("DEPLOY",     AMBER, self._dash_cockpit_deploy),
            ("STREAM LOGS", AMBER_B, self._dash_cockpit_toggle_stream),
        ]
        for label, color, cmd in buttons:
            btn = tk.Label(ctrl_inner, text=f"  {label}  ",
                           font=(FONT, 8, "bold"),
                           fg=BG, bg=color, cursor="hand2",
                           padx=8, pady=4)
            btn.pack(side="left", padx=(0, 8))
            btn.bind("<Button-1>", lambda e, c=cmd: c())
            btn.bind("<Enter>", lambda e, b=btn, c=color:
                     b.configure(bg=AMBER_B if c != AMBER_B else "#ffd166"))
            btn.bind("<Leave>", lambda e, b=btn, c=color: b.configure(bg=c))
            if label == "STREAM LOGS":
                self._dash_widgets[("cp_stream_btn",)] = btn

        result_l = tk.Label(ctrl_inner, text="", font=(FONT, 7),
                            fg=DIM, bg=PANEL, anchor="w")
        result_l.pack(side="left", padx=(10, 0))
        self._dash_widgets[("cp_action",)] = result_l

        # ── LIVE LOG card (Text widget + scrollbar) ──
        log_box = tk.Frame(wrap, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1)
        log_box.pack(fill="both", expand=True, pady=(0, 0))
        log_head = tk.Label(log_box, text=" LIVE LOG (polled every 5s) ",
                            font=(FONT, 7, "bold"), fg=BG, bg=AMBER)
        log_head.pack(side="top", anchor="nw", padx=8, pady=4)
        self._dash_widgets[("cp_log_head",)] = log_head

        log_frame = tk.Frame(log_box, bg=PANEL)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        scroll = tk.Scrollbar(log_frame, bg=PANEL)
        scroll.pack(side="right", fill="y")
        log_text = tk.Text(log_frame, bg=BG, fg=WHITE,
                           font=(FONT, 8), bd=0, highlightthickness=0,
                           insertbackground=AMBER, wrap="none",
                           yscrollcommand=scroll.set)
        log_text.pack(side="left", fill="both", expand=True)
        scroll.configure(command=log_text.yview)
        log_text.insert("1.0", "— waiting for first log fetch —\n")
        log_text.configure(state="disabled")
        self._dash_widgets[("cp_log_text",)] = log_text

        self.f_lbl.configure(
            text="COCKPIT · VPS remote · "
                 "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit"
        )
        self.h_path.configure(text="> MARKETS > CRYPTO FUTURES > COCKPIT")

    def _dash_cockpit_fetch_async(self):
        """Single SSH round-trip for full status: screen, logs, positions."""
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "") != "cockpit":
            return

        # Combine multiple checks into one SSH invocation — reduces latency
        # from ~3 round-trips to 1. Markers let us split stdout into sections.
        combined = (
            "echo '---SCREEN---'; screen -ls 2>&1 || true; "
            "echo '---LOG---'; tail -5 ~/aurum.finance/data/live/*/logs/live.log 2>/dev/null || true; "
            "echo '---POS---'; cat ~/aurum.finance/data/live/*/state/positions.json 2>/dev/null || true; "
            "echo '---END---'"
        )

        def worker():
            import time as _time
            t0 = _time.time()
            out = _vps_cmd(combined, timeout=8)
            lat_ms = int((_time.time() - t0) * 1000)

            snap = {"reachable": out is not None, "latency_ms": lat_ms,
                    "screen_running": False, "screen_raw": "",
                    "log_lines": [], "positions": [], "positions_raw": "",
                    "ts": datetime.now().strftime("%H:%M:%S")}

            if out:
                parts = {"SCREEN": "", "LOG": "", "POS": ""}
                current = None
                for line in out.splitlines():
                    m = line.strip()
                    if m == "---SCREEN---": current = "SCREEN"; continue
                    if m == "---LOG---":    current = "LOG";    continue
                    if m == "---POS---":    current = "POS";    continue
                    if m == "---END---":    current = None;     continue
                    if current:
                        parts[current] += line + "\n"

                snap["screen_raw"] = parts["SCREEN"].strip()
                snap["screen_running"] = "aurum" in parts["SCREEN"]
                snap["log_lines"] = [l for l in parts["LOG"].splitlines() if l.strip()]
                snap["positions_raw"] = parts["POS"].strip()
                try:
                    if parts["POS"].strip():
                        pos_data = json.loads(parts["POS"])
                        if isinstance(pos_data, list):
                            snap["positions"] = pos_data
                        elif isinstance(pos_data, dict):
                            # Common shape: {"BTCUSDT": {...}, "ETHUSDT": {...}}
                            snap["positions"] = [
                                {"symbol": k, **(v if isinstance(v, dict) else {"value": v})}
                                for k, v in pos_data.items()
                            ]
                except (json.JSONDecodeError, TypeError):
                    pass

            self._dash_cockpit_snap = snap
            if getattr(self, "_dash_alive", False):
                try: self.after(0, self._dash_cockpit_render)
                except Exception: pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_cockpit_render(self):
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "") != "cockpit":
            return

        snap = getattr(self, "_dash_cockpit_snap", {}) or {}

        # ── reachability ──
        reach_l = self._dash_widgets.get(("cp_reach",))
        if reach_l:
            if snap.get("reachable"):
                reach_l.configure(
                    text=f"● reachable  ·  {snap.get('latency_ms', '?')}ms",
                    fg=GREEN)
                self.h_stat.configure(text="VPS OK", fg=GREEN)
            else:
                reach_l.configure(text="○ unreachable", fg=RED)
                self.h_stat.configure(text="VPS DOWN", fg=RED)

        check_l = self._dash_widgets.get(("cp_check",))
        if check_l:
            check_l.configure(text=f"last check: {snap.get('ts', '—')}")

        # ── engine state ──
        state_l = self._dash_widgets.get(("cp_engine_state",))
        sub_l   = self._dash_widgets.get(("cp_engine_sub",))
        if state_l and sub_l:
            if not snap.get("reachable"):
                state_l.configure(text="○ UNKNOWN", fg=DIM)
                sub_l.configure(text="VPS not reachable", fg=DIM2)
            elif snap.get("screen_running"):
                state_l.configure(text="● RUNNING", fg=GREEN)
                # Extract PID/name from screen -ls output if possible
                first_line = next(
                    (l for l in snap.get("screen_raw", "").splitlines()
                     if "aurum" in l), "")
                sub_l.configure(
                    text=f"screen: {first_line.strip() or 'aurum'}",
                    fg=DIM)
            else:
                state_l.configure(text="○ STOPPED", fg=AMBER_D)
                sub_l.configure(text="no aurum screen session", fg=DIM)

        # ── positions ──
        pos_head  = self._dash_widgets.get(("cp_pos_head",))
        pos_inner = self._dash_widgets.get(("cp_pos_inner",))
        if pos_inner:
            for w in pos_inner.winfo_children():
                try: w.destroy()
                except Exception: pass
            positions = snap.get("positions") or []
            if pos_head:
                pos_head.configure(text=f" OPEN POSITIONS ({len(positions)}) ")

            if not positions:
                if snap.get("positions_raw") and snap.get("reachable"):
                    tk.Label(pos_inner,
                             text="  — state/positions.json parse failed —",
                             font=(FONT, 8), fg=DIM, bg=PANEL,
                             anchor="w").pack(fill="x", pady=2)
                else:
                    tk.Label(pos_inner, text="  — no open positions —",
                             font=(FONT, 8), fg=DIM, bg=PANEL,
                             anchor="w").pack(fill="x", pady=2)
            else:
                for p in positions[:10]:
                    sym  = str(p.get("symbol", "?"))
                    side = str(p.get("side", p.get("direction", "")))
                    try:
                        size  = float(p.get("size", p.get("qty", 0)) or 0)
                        entry = float(p.get("entry", p.get("entry_price", 0)) or 0)
                        pnl   = float(p.get("pnl", p.get("unrealized_pnl", 0)) or 0)
                    except (TypeError, ValueError):
                        size = entry = pnl = 0
                    pnl_col = GREEN if pnl >= 0 else RED

                    r = tk.Frame(pos_inner, bg=PANEL); r.pack(fill="x", pady=1)
                    tk.Label(r, text=sym, font=(FONT, 9, "bold"),
                             fg=AMBER, bg=PANEL, width=12,
                             anchor="w").pack(side="left")
                    tk.Label(r, text=side.upper()[:5], font=(FONT, 8),
                             fg=WHITE, bg=PANEL, width=6,
                             anchor="w").pack(side="left")
                    tk.Label(r, text=f"{size:g}", font=(FONT, 8),
                             fg=DIM, bg=PANEL, width=10,
                             anchor="w").pack(side="left")
                    tk.Label(r, text=f"@ {entry:,.4f}".rstrip("0").rstrip("."),
                             font=(FONT, 8), fg=DIM, bg=PANEL, width=14,
                             anchor="w").pack(side="left")
                    tk.Label(r,
                             text=f"PnL {'+' if pnl >= 0 else ''}${pnl:,.2f}",
                             font=(FONT, 9, "bold"), fg=pnl_col, bg=PANEL,
                             anchor="w").pack(side="left")

        # ── live log (only update when not streaming) ──
        if not self._dash_cockpit_streaming:
            log_text = self._dash_widgets.get(("cp_log_text",))
            if log_text:
                lines = snap.get("log_lines") or []
                log_text.configure(state="normal")
                log_text.delete("1.0", "end")
                if lines:
                    log_text.insert("1.0", "\n".join(lines) + "\n")
                elif snap.get("reachable"):
                    log_text.insert("1.0", "— log file not found or empty —\n")
                else:
                    log_text.insert("1.0", "— VPS unreachable —\n")
                log_text.configure(state="disabled")

        # ── schedule next tick ──
        if getattr(self, "_dash_alive", False) and self._dash_tab == "cockpit":
            aid = getattr(self, "_dash_after_id", None)
            if aid:
                try: self.after_cancel(aid)
                except Exception: pass
            self._dash_after_id = self.after(5000, self._dash_tick_refresh)

    def _dash_cockpit_action(self, label: str, cmd: str,
                             success_msg: str = "ok", timeout: int = 15):
        """Run an SSH command in a worker thread, flash a status message."""
        action_l = self._dash_widgets.get(("cp_action",))
        if action_l:
            action_l.configure(text=f"→ {label}...", fg=AMBER_D)

        def worker():
            out = _vps_cmd(cmd, timeout=timeout)
            def apply():
                if not getattr(self, "_dash_alive", False):
                    return
                if action_l:
                    if out is not None:
                        action_l.configure(text=f"✓ {label}: {success_msg}", fg=GREEN)
                    else:
                        action_l.configure(text=f"✗ {label}: failed", fg=RED)
                # Trigger an immediate status refresh to reflect the action
                self._dash_cockpit_fetch_async()
            try: self.after(0, apply)
            except Exception: pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_cockpit_start_demo(self):
        cmd = ("screen -dmS aurum bash -c "
               "'cd ~/aurum.finance && python3 -m engines.live demo "
               "2>&1 | tee /tmp/aurum.log'")
        self._dash_cockpit_action("START DEMO", cmd, "engine spawned")

    def _dash_cockpit_stop(self):
        # $'\003' is bash ANSI-C quoting for Ctrl+C — graceful shutdown
        cmd = r"screen -S aurum -X stuff $'\003'"
        self._dash_cockpit_action("STOP", cmd, "Ctrl+C sent")

    def _dash_cockpit_deploy(self):
        cmd = "cd ~/aurum.finance && git pull"
        self._dash_cockpit_action("DEPLOY", cmd, "git pull done", timeout=30)

    def _dash_cockpit_toggle_stream(self):
        """Toggle live streaming of the log file via `ssh ... tail -f`."""
        if self._dash_cockpit_streaming:
            self._dash_cockpit_kill_stream()
            btn = self._dash_widgets.get(("cp_stream_btn",))
            if btn: btn.configure(text="  STREAM LOGS  ", bg=AMBER_B)
            head = self._dash_widgets.get(("cp_log_head",))
            if head: head.configure(text=" LIVE LOG (polled every 5s) ")
            return

        # Start stream
        log_text = self._dash_widgets.get(("cp_log_text",))
        if log_text:
            log_text.configure(state="normal")
            log_text.delete("1.0", "end")
            log_text.insert("1.0", "— starting live stream... —\n")
            log_text.configure(state="disabled")

        try:
            self._dash_cockpit_stream = subprocess.Popen(
                ["ssh", "-o", "StrictHostKeyChecking=no",
                 "-o", "ConnectTimeout=5",
                 "-o", "BatchMode=yes",
                 VPS_HOST,
                 "tail -f ~/aurum.finance/data/live/*/logs/live.log 2>/dev/null"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                creationflags=_NO_WINDOW,
            )
        except (FileNotFoundError, OSError) as e:
            if log_text:
                log_text.configure(state="normal")
                log_text.insert("end", f"— stream failed: {e} —\n")
                log_text.configure(state="disabled")
            return

        self._dash_cockpit_streaming = True
        btn = self._dash_widgets.get(("cp_stream_btn",))
        if btn: btn.configure(text="  STOP STREAM  ", bg=RED)
        head = self._dash_widgets.get(("cp_log_head",))
        if head: head.configure(text=" LIVE LOG (streaming) ")

        def reader():
            proc = self._dash_cockpit_stream
            if proc is None or proc.stdout is None:
                return
            try:
                # readline() instead of `for line in proc.stdout:` because the
                # iterator buffers aggressively and can hang even after the
                # process is terminated. readline returns '' on EOF.
                while self._dash_cockpit_streaming:
                    try:
                        line = proc.stdout.readline()
                    except (ValueError, OSError):
                        # pipe closed underneath us
                        break
                    if not line:  # EOF
                        break
                    if not self._dash_cockpit_streaming:
                        break
                    def append(l=line):
                        if not getattr(self, "_dash_alive", False):
                            return
                        lt = self._dash_widgets.get(("cp_log_text",))
                        if lt is None: return
                        try:
                            if not lt.winfo_exists(): return
                            lt.configure(state="normal")
                            lt.insert("end", l)
                            # Trim to last 500 lines to prevent memory growth
                            total = int(lt.index("end-1c").split(".")[0])
                            if total > 500:
                                lt.delete("1.0", f"{total - 500}.0")
                            lt.see("end")
                            lt.configure(state="disabled")
                        except tk.TclError:
                            pass
                    try: self.after(0, append)
                    except Exception: return
            except Exception:
                pass

        threading.Thread(target=reader, daemon=True).start()

    def _dash_cockpit_kill_stream(self):
        """Idempotent — safe to call multiple times even if no stream exists.
        Explicitly closes stdout to unblock the reader thread."""
        self._dash_cockpit_streaming = False
        proc = self._dash_cockpit_stream
        self._dash_cockpit_stream = None  # clear handle first so kill is idempotent
        if proc is None:
            return
        # Close stdout before terminating — this unblocks any reader
        # thread that's sitting in readline() waiting for input.
        if proc.stdout is not None:
            try: proc.stdout.close()
            except (OSError, ValueError): pass
        try:
            proc.terminate()
            try: proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                try: proc.wait(timeout=1)
                except subprocess.TimeoutExpired: pass
        except (OSError, ValueError):
            pass

    # ── PAPER: edit dialog ────────────────────────────────
    def _dash_paper_edit_dialog(self):
        """Modal-ish dialog to edit the persistent paper account state.
        Lets the user set balance, deposit, withdraw, or reset."""
        from core.portfolio_monitor import PortfolioMonitor
        state = PortfolioMonitor.paper_state_load()
        current = float(state.get("current_balance", 0) or 0)
        initial = float(state.get("initial_balance", 0) or 0)

        dlg = tk.Toplevel(self)
        dlg.title("Edit Paper Account")
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        # Center over parent
        try:
            self.update_idletasks()
            x = self.winfo_rootx() + (self.winfo_width()  // 2) - 220
            y = self.winfo_rooty() + (self.winfo_height() // 2) - 180
            dlg.geometry(f"440x360+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            dlg.geometry("440x360")
        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists(): dlg.iconbitmap(str(ico))
        except Exception: pass

        # Header
        tk.Label(dlg, text=" EDIT PAPER ACCOUNT ",
                 font=(FONT, 9, "bold"), fg=BG, bg=AMBER,
                 padx=10, pady=6).pack(fill="x", padx=16, pady=(16, 0))
        tk.Frame(dlg, bg=AMBER_D, height=1).pack(fill="x", padx=16)

        info = tk.Frame(dlg, bg=BG); info.pack(fill="x", padx=16, pady=(10, 6))
        tk.Label(info, text=f"Current balance:  ${current:,.2f}",
                 font=(FONT, 9), fg=WHITE, bg=BG,
                 anchor="w").pack(fill="x")
        tk.Label(info, text=f"Initial balance:  ${initial:,.2f}",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(fill="x")
        tk.Label(info,
                 text=f"Deposits: ${state.get('total_deposits', 0):,.2f}  ·  "
                      f"Withdraws: ${state.get('total_withdraws', 0):,.2f}",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(fill="x")
        tk.Label(info,
                 text=f"Realized PnL: ${state.get('realized_pnl', 0):,.2f}  ·  "
                      f"Trades: {len(state.get('trades') or [])}",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(fill="x")

        tk.Frame(dlg, bg=DIM2, height=1).pack(fill="x", padx=16, pady=(8, 6))

        # Input row
        form = tk.Frame(dlg, bg=BG); form.pack(fill="x", padx=16, pady=(2, 4))
        tk.Label(form, text="New balance  $", font=(FONT, 9),
                 fg=AMBER, bg=BG).pack(side="left")
        entry = tk.Entry(form, font=(FONT, 10, "bold"),
                         fg=WHITE, bg=BG3, insertbackground=AMBER,
                         bd=0, relief="flat", width=14)
        entry.pack(side="left", padx=(4, 0), ipady=4)
        entry.insert(0, f"{current:.2f}")
        entry.select_range(0, "end")
        entry.focus_set()

        note_f = tk.Frame(dlg, bg=BG); note_f.pack(fill="x", padx=16, pady=(2, 8))
        tk.Label(note_f, text="Note         ", font=(FONT, 8),
                 fg=DIM, bg=BG).pack(side="left")
        note_entry = tk.Entry(note_f, font=(FONT, 8),
                              fg=WHITE, bg=BG3, insertbackground=AMBER,
                              bd=0, relief="flat")
        note_entry.pack(side="left", fill="x", expand=True, ipady=3)
        note_entry.insert(0, "manual adjust")

        # Status line
        status_l = tk.Label(dlg, text="", font=(FONT, 7),
                            fg=DIM, bg=BG, anchor="w")
        status_l.pack(fill="x", padx=16, pady=(0, 6))

        def _invalidate_paper_cache():
            """Clear stale cached paper snapshot so the next portfolio render
            re-reads from the (just-updated) paper_state.json file. Avoids a
            race where a concurrent refresh() would overwrite the edit."""
            pm = self._get_portfolio_monitor()
            try:
                with pm._lock:
                    pm._cache.pop("paper", None)
            except Exception:
                pass

        def _apply():
            raw = entry.get().strip().replace(",", "").replace("$", "")
            try:
                val = float(raw)
            except ValueError:
                status_l.configure(text="✗ invalid amount", fg=RED)
                return
            if val < 0:
                status_l.configure(text="✗ balance cannot be negative", fg=RED)
                return
            note = note_entry.get().strip() or "manual adjust"
            PortfolioMonitor.paper_set_balance(val, note=note)
            _invalidate_paper_cache()
            delta = val - current
            status_l.configure(
                text=f"✓ saved  ·  {'+'  if delta >= 0 else ''}${delta:,.2f}  →  ${val:,.2f}",
                fg=GREEN)
            self.after(500, dlg.destroy)
            # Re-render current tab (portfolio or home) to show fresh data
            self.after(550, self._dash_force_refresh)

        def _reset():
            PortfolioMonitor.paper_reset()
            _invalidate_paper_cache()
            status_l.configure(text="✓ reset to default $10,000", fg=GREEN)
            self.after(500, dlg.destroy)
            self.after(550, self._dash_force_refresh)

        # Buttons
        btns = tk.Frame(dlg, bg=BG); btns.pack(fill="x", padx=16, pady=(6, 14))

        def _mkbtn(parent, label, color, cmd):
            b = tk.Label(parent, text=f"  {label}  ",
                         font=(FONT, 8, "bold"),
                         fg=BG, bg=color, cursor="hand2",
                         padx=8, pady=5)
            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", lambda e: b.configure(bg=AMBER_B))
            b.bind("<Leave>", lambda e: b.configure(bg=color))
            return b

        _mkbtn(btns, "APPLY",  GREEN, _apply).pack(side="left", padx=(0, 6))
        _mkbtn(btns, "RESET",  RED,   _reset).pack(side="left", padx=6)
        _mkbtn(btns, "CANCEL", DIM2,  dlg.destroy).pack(side="right")

        # Quick-action buttons (deposit/withdraw shortcuts)
        quick = tk.Frame(dlg, bg=BG); quick.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(quick, text="Quick:", font=(FONT, 7),
                 fg=DIM, bg=BG).pack(side="left", padx=(0, 6))
        for label, amt in [("+$1K", 1000), ("+$5K", 5000),
                           ("-$1K", -1000), ("-$5K", -5000)]:
            def _q(_e=None, a=amt):
                new = max(0, current + a)
                entry.delete(0, "end")
                entry.insert(0, f"{new:.2f}")
                note_entry.delete(0, "end")
                note_entry.insert(0, f"quick {'+' if a >= 0 else ''}${a}")
            qb = tk.Label(quick, text=f" {label} ",
                          font=(FONT, 7, "bold"),
                          fg=AMBER, bg=BG3, cursor="hand2",
                          padx=5, pady=2)
            qb.pack(side="left", padx=2)
            qb.bind("<Button-1>", _q)

        dlg.bind("<Return>", lambda e: _apply())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

    def _dash_exit_to_markets(self):
        self._dash_alive = False
        self._dash_cockpit_kill_stream()
        aid = getattr(self, "_dash_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._dash_after_id = None
        self._markets()

    # ─── COMMAND CENTER ──────────────────────────────────
    def _get_site_runner(self):
        """Lazily instantiate the singleton SiteRunner."""
        sr = getattr(self, "_site_runner_inst", None)
        if sr is None:
            from core.site_runner import SiteRunner
            sr = SiteRunner()
            self._site_runner_inst = sr
        return sr

    def _command_center(self):
        self._clr(); self._clear_kb()
        # Don't clobber the existing nav stack — other screens may have
        # pushed entries. Only seed it if truly empty.
        if not self.history:
            self.history = ["main"]
        self.h_path.configure(text="> COMMAND CENTER")
        self.h_stat.configure(text="MANAGE", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  número para selecionar  |  H hub")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        _outer, body = self._ui_page_shell(
            "COMMAND CENTER",
            "Administrative routing for local site, deploy and system control",
        )
        panel = self._ui_panel_frame(body, "CONTROL SURFACES", "Operational and infrastructure workflows")

        sr = self._get_site_runner()
        site_running = sr.is_running()

        items = [
            ("SITE LOCAL", "Dev server (npm/vite/next)",
             True, self._site_local, "● RUNNING" if site_running else None),
            ("DEPLOY",     "Push to production",         False,
             lambda: self._command_coming_soon("DEPLOY"),    None),
            ("SERVERS",    "VPS status & SSH",           False,
             lambda: self._command_coming_soon("SERVERS"),   None),
            ("DATABASES",  "Connections & backups",      False,
             lambda: self._command_coming_soon("DATABASES"), None),
            ("SERVICES",   "Background processes",       False,
             lambda: self._command_coming_soon("SERVICES"),  None),
            ("SYSTEM",     "CPU, RAM, disk, network",    False,
             lambda: self._command_coming_soon("SYSTEM"),    None),
        ]

        self._ui_note(
            panel,
            "Local site control is active. Remaining surfaces stay documented until implementation is wired.",
            fg=DIM,
        )

        for i, (name, desc, available, cmd, tag) in enumerate(items):
            num = i + 1
            row, nl, dl = self._ui_action_row(
                panel, str(num), name, desc,
                available=available,
                tag=tag or ("COMING SOON" if not available else None),
                tag_fg=BG if tag else DIM,
                tag_bg=GREEN if tag else BG2,
                title_width=18,
            )

            for w in [row, nl, dl]:
                w.bind("<Button-1>", lambda e, c=cmd: c())
                if available:
                    w.bind("<Enter>", lambda e, n=nl: n.configure(fg=AMBER))
                    w.bind("<Leave>", lambda e, n=nl: n.configure(fg=WHITE))
            self._kb(f"<Key-{num}>", cmd)

        self._ui_back_row(panel, lambda: self._menu("main"))

    def _command_coming_soon(self, name):
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> COMMAND CENTER > {name}")
        self.h_stat.configure(text="ROADMAP", fg=DIM)
        self.f_lbl.configure(text="ESC voltar  |  H hub")
        self._kb("<Escape>", self._command_center)
        self._kb("<Key-0>", self._command_center)
        self._bind_global_nav()

        roadmap = COMMAND_ROADMAPS.get(name, ["Coming soon"])

        _outer, body = self._ui_page_shell(name, "Roadmap placeholder for command-center pipeline")
        box = self._ui_panel_frame(body, "ROADMAP", f"{name} implementation plan")
        for item in roadmap:
            self._ui_note(box, f"[ ] {item}", fg=DIM)
        self._ui_back_row(box, lambda: self._command_center())

    # ── COMMAND CENTER · SITE LOCAL ──────────────────────
    def _site_local(self):
        self._clr(); self._clear_kb()
        self.history = ["main", "command"]
        self.h_path.configure(text="> COMMAND CENTER > SITE LOCAL")
        self.f_lbl.configure(text="ESC voltar  |  H hub")
        self._kb("<Escape>", self._command_center)
        self._bind_global_nav()

        sr = self._get_site_runner()
        if sr.is_running():
            self._site_running_screen(sr)
        else:
            self._site_config_screen(sr)

    def _site_config_screen(self, sr):
        self.h_stat.configure(text="● STOPPED", fg=RED)

        _outer, body = self._ui_page_shell(
            "SITE LOCAL",
            "Local site runner configuration and launch controls",
            content_width=860,
        )
        box = self._ui_panel_frame(body, "SITE RUNNER", "Resolved local app command and operator settings")

        framework_d, command_d = sr.resolved_command()
        info = [
            ("Project Dir", sr.config.get("project_dir") or "(not set)"),
            ("Framework",   f"{sr.config.get('framework','auto')}  →  {framework_d}"),
            ("Port",        str(sr.config.get("port", 3000))),
            ("Command",     command_d),
            ("Auto-open",   "yes" if sr.config.get("auto_open_browser") else "no"),
        ]
        for label, value in info:
            row = tk.Frame(box, bg=BG); row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=14, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=(FONT, 9),
                     fg=WHITE, bg=BG, anchor="w").pack(side="left", padx=4)

        self._ui_note(box, "Status: stopped", fg=RED)

        bf = tk.Frame(box, bg=BG); bf.pack(fill="x", pady=(8, 4))
        def mkbtn(text, color, fg, cmd):
            btn = tk.Label(bf, text=text, font=(FONT, 10, "bold"),
                           fg=fg, bg=color, cursor="hand2", padx=14, pady=5)
            btn.pack(side="left", padx=4)
            btn.bind("<Button-1>", lambda e: cmd())
            return btn

        mkbtn(" START ",        GREEN, BG,    self._site_start)
        mkbtn(" CONFIG ",       AMBER, BG,    self._site_config_edit)
        mkbtn(" OPEN BROWSER ", BG3,   AMBER, self._site_open_browser)
        mkbtn(" VOLTAR ",       BG3,   DIM,   self._command_center)

        if not sr.config.get("project_dir"):
            self._ui_note(box, "Warning: configure PROJECT_DIR before START.", fg=AMBER_D)

    def _site_running_screen(self, sr):
        self.h_stat.configure(text="● RUNNING", fg=GREEN)
        framework, command = sr.resolved_command()
        port = sr.config.get("port", 3000)

        _outer, body = self._ui_page_shell(
            "SITE LOCAL",
            "Local runner status, console stream and browser routing",
        )
        top = self._ui_panel_frame(body, "SITE RUNNER", f"Running on {framework}  ·  port {port}")
        meta = tk.Frame(top, bg=BG)
        meta.pack(fill="x", pady=(0, 8))
        tk.Label(meta, text="Status: running", font=(FONT, 8, "bold"),
                 fg=GREEN, bg=BG).pack(side="left")
        self._site_uptime_lbl = tk.Label(
            meta, text=f"PID {sr.proc.pid if sr.proc else '?'}   uptime {sr.uptime()}",
            font=(FONT, 7), fg=DIM, bg=BG)
        self._site_uptime_lbl.pack(side="left", padx=12)
        url_lbl = tk.Label(meta, text=sr.url(), font=(FONT, 7),
                           fg=AMBER_D, bg=BG, cursor="hand2")
        url_lbl.pack(side="right", padx=8)
        url_lbl.bind("<Button-1>", lambda e: self._site_open_browser())

        cf = tk.Frame(body, bg=PANEL)
        cf.pack(fill="both", expand=True)
        sb = tk.Scrollbar(cf, bg=BG, troughcolor=BG, highlightthickness=0, bd=0)
        sb.pack(side="right", fill="y")
        self.site_con = tk.Text(cf, bg=PANEL, fg=WHITE, font=(FONT, 9), wrap="word",
                                borderwidth=0, highlightthickness=0,
                                padx=10, pady=6, state="disabled", cursor="arrow",
                                yscrollcommand=sb.set)
        self.site_con.pack(fill="both", expand=True)
        sb.config(command=self.site_con.yview)
        self.site_con.tag_configure("a", foreground=AMBER)
        self.site_con.tag_configure("g", foreground=GREEN)
        self.site_con.tag_configure("r", foreground=RED)
        self.site_con.tag_configure("d", foreground=DIM)
        self.site_con.tag_configure("w", foreground=WHITE)

        bf = tk.Frame(body, bg=BG)
        bf.pack(fill="x", pady=(8, 0))
        def mkbtn(text, fg, cmd):
            btn = tk.Label(bf, text=text, font=(FONT, 9, "bold"),
                           fg=fg, bg=BG, cursor="hand2", padx=10, pady=5)
            btn.pack(side="left", padx=2, pady=2)
            btn.bind("<Button-1>", lambda e: cmd())
        mkbtn(" STOP ",         RED,   self._site_stop)
        mkbtn(" OPEN BROWSER ", AMBER, self._site_open_browser)
        mkbtn(" CLEAR ",        DIM,   self._site_clear_console)
        mkbtn(" BACK ",         DIM,   self._command_center)

        # Reset poll cursor + start polling. Buffer dump happens on first tick.
        self._site_seen_idx = 0
        self._site_screen_alive = True
        self._site_poll()

    def _site_print(self, line, default_tag="w"):
        if not hasattr(self, "site_con"):
            return
        try:
            if not self.site_con.winfo_exists():
                return
        except Exception:
            return
        import re
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
        low = clean.lower()
        tag = default_tag
        if "✓" in clean or "ready in" in low or "compiled" in low:
            tag = "g"
        elif "✗" in clean or "error" in low or "failed" in low or "sigterm" in low:
            tag = "r"
        elif "warn" in low:
            tag = "a"
        try:
            self.site_con.configure(state="normal")
            self.site_con.insert("end", clean, tag)
            self.site_con.see("end")
            self.site_con.configure(state="disabled")
        except Exception:
            pass

    def _site_poll(self):
        if not getattr(self, "_site_screen_alive", False):
            return
        sr = getattr(self, "_site_runner_inst", None)
        if sr is None:
            return

        new_idx, lines = sr.lines_after(getattr(self, "_site_seen_idx", 0))
        for line in lines:
            self._site_print(line)
        self._site_seen_idx = new_idx

        # Refresh uptime/pid line
        try:
            if hasattr(self, "_site_uptime_lbl") and self._site_uptime_lbl.winfo_exists():
                pid = sr.proc.pid if sr.proc else "?"
                self._site_uptime_lbl.configure(
                    text=f"PID {pid}   uptime {sr.uptime()}")
        except Exception:
            pass

        if not sr.is_running():
            self._site_print("\n  >> PROCESS EXITED\n", "r")
            self._site_screen_alive = False
            self.after(800, self._site_local)
            return

        self.after(150, self._site_poll)

    def _site_start(self):
        sr = self._get_site_runner()
        if sr.is_running():
            self.h_stat.configure(text="ALREADY RUNNING", fg=AMBER_D); return
        if not (sr.config.get("project_dir") or "").strip():
            self.h_stat.configure(text="DEFINE PROJECT_DIR FIRST", fg=RED)
            return
        if not Path(sr.config["project_dir"]).is_dir():
            self.h_stat.configure(text="DIR NOT FOUND", fg=RED)
            return
        ok, msg = sr.start()
        if not ok:
            self.h_stat.configure(text=f"FAIL: {msg[:32]}", fg=RED)
            return
        if sr.config.get("auto_open_browser"):
            try:
                import webbrowser
                self.after(1500, lambda: webbrowser.open(sr.url()))
            except Exception:
                pass
        # Re-render — picks up the running state and builds the console screen.
        self._site_local()

    def _site_stop(self):
        sr = getattr(self, "_site_runner_inst", None)
        if sr and sr.is_running():
            try: sr.stop()
            except Exception: pass
        self._site_screen_alive = False
        self.after(200, self._site_local)

    def _site_open_browser(self):
        sr = self._get_site_runner()
        if not sr.is_running():
            self.h_stat.configure(text="server not running", fg=AMBER_D)
            return
        try:
            import webbrowser
            webbrowser.open(sr.url())
            self.h_stat.configure(text="opened", fg=GREEN)
        except Exception as e:
            self.h_stat.configure(text=f"browser fail: {str(e)[:24]}", fg=RED)

    def _site_clear_console(self):
        try:
            if hasattr(self, "site_con") and self.site_con.winfo_exists():
                self.site_con.configure(state="normal")
                self.site_con.delete("1.0", "end")
                self.site_con.configure(state="disabled")
        except Exception:
            pass
        # Skip ahead so we don't redump the buffer that was just cleared.
        sr = getattr(self, "_site_runner_inst", None)
        if sr is not None:
            self._site_seen_idx = sr.total_emitted

    def _site_config_edit(self):
        sr = self._get_site_runner()
        def load():
            return {
                "project_dir": sr.config.get("project_dir", ""),
                "framework":   sr.config.get("framework", "auto"),
                "port":        str(sr.config.get("port", 3000)),
                "command":     sr.config.get("command", ""),
                "auto_open":   "yes" if sr.config.get("auto_open_browser", True) else "no",
            }
        def save(v):
            try:
                raw = (v.get("port") or "").strip()
                port = int(raw) if raw else 3000
            except ValueError:
                port = 3000
            sr.save_config(
                project_dir=(v.get("project_dir") or "").strip(),
                framework=((v.get("framework") or "auto").strip() or "auto"),
                port=port,
                command=(v.get("command") or "").strip(),
                auto_open_browser=((v.get("auto_open") or "").strip().lower()
                                   in ("yes", "y", "true", "1")),
            )
            self.after(1500, self._site_local)
        self._cfg_edit("SITE LOCAL", [
            ("project_dir", "PROJECT DIR",  "absolute path",                                 False),
            ("framework",   "FRAMEWORK",    "auto/next/vite/nuxt/gatsby/django/static/custom", False),
            ("port",        "PORT",         "default 3000",                                  False),
            ("command",     "COMMAND",      "override (optional)",                           False),
            ("auto_open",   "AUTO BROWSER", "yes/no",                                        False),
        ], load, save, back_fn=self._site_local)

    # ─── QUIT ────────────────────────────────────────────
    def _quit(self):
        if self.proc and self.proc.poll() is None:
            r = messagebox.askyesnocancel("AURUM", "Engine running. Stop before closing?")
            if r is None: return
            if r:
                self.proc.terminate()
                try: self.proc.wait(timeout=3)
                except: self.proc.kill()
        elif self._exec_managed_info is not None:
            r = messagebox.askyesnocancel("AURUM", "Background backtest running. Stop before closing?")
            if r is None: return
            if r:
                try:
                    from core.proc import stop_proc
                    stop_proc(int(self._exec_managed_info["pid"]), expected=self._exec_managed_info)
                except Exception:
                    pass
        sr = getattr(self, "_site_runner_inst", None)
        if sr and sr.is_running():
            r = messagebox.askyesnocancel("AURUM", "Dev server running. Stop before closing?")
            if r is None: return
            if r:
                try: sr.stop()
                except Exception: pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
