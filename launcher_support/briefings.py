"""Strategy briefings — narrative (BRIEFINGS) and technical (BRIEFINGS_V2).

Extracted verbatim from launcher.py so the ~640 lines of strategy-specific
copy and metadata don't bloat the main launcher module. Consumed by
launcher_support.screens.brief.render and by launcher.App._brief.

Schema is stable: BRIEFINGS is narrative (what/philosophy/logic/edge/risk),
BRIEFINGS_V2 is technical (source_files/main_function/pseudocode/params/
formulas/invariants). Coexist: _brief prefers V2 when a matching name
exists, falls back to the narrative dict.
"""
from __future__ import annotations

BRIEFINGS = {
    "CITADEL": {
        "what": "Cross-timeframe momentum with fractal swing-structure confirmation. Entries require BTC macro regime alignment, multi-TF O 5D score, and adaptive risk sizing.",
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
        "what": "Order-flow microstructure engine. Cumulative Volume Delta divergences, rolling taker-imbalance, and liquidation-cascade detection provide positional front-running signals.",
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
        "what": "Cross-sectional sentiment contrarian. Fades statistically extreme positioning via weighted composite of funding z-score, open-interest delta, and long/short ratio.",
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
        "what": "Statistical arbitrage via Engle-Granger pairs cointegration. Delta-neutral exposure to mean-reverting spread dynamics; rolling OLS half-life estimation.",
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
            "Status":     "? MARGINAL — universo altcoin atual sem pares cointegrados estáveis",
        },
    },
    "MILLENNIUM": {
        "what": "Multi-strategy portfolio orchestrator. Aggregates trade-level signals across all engines, applies rolling-Sortino performance weights, and enforces kill-switch discipline on underperformers.",
        "philosophy": "Nenhuma estratégia única sobrevive a todas as condições de mercado — assim como nenhuma partícula isolada explica toda a matéria. Mas um portfolio de estratégias não-correlacionadas, cada uma forte em regimes diferentes, cria um edge que persiste. É o princípio da superposição: sinais independentes combinados reduzem o ruído por vN enquanto preservam o sinal. MILLENNIUM orquestra — combinando sinais, gerenciando correlação, alocando capital onde a matemática aponta.",
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
        "what": "LightGBM meta-allocator. Forecasts engine-level relative performance conditioned on regime features (HMM states, Hurst exponent, realized volatility).",
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

BRIEFINGS["KEPOS"] = {
    "what": "Critical endogeneity fade. Identifies self-exciting Hawkes regimes via branching ratio ? = 0.95 and counter-trades exhaustion moves with ATR-based risk.",
    "philosophy": "O mercado é um processo auto-excitante — trades geram trades, como cascatas de decaimento radioativo. O branching ratio ? mede este feedback: ??1 é o ponto crítico, onde pequenos choques desencadeiam avalanches. KEPOS lê este estado de criticidade e fade o movimento — quando a multidão está convicta demais, a reversão é iminente. Física de Filimonov-Sornette aplicada a candle data: ? sustentado em regime crítico + overshoot de preço + expansão de ATR = reversão probabilística.",
    "logic": [
        "Calcular Hawkes ? rolling (branching ratio auto-excitante)",
        "Gate 1: ? sustentado = 0.95 por N barras",
        "Gate 2: preço overextended (|cum return| > 2s em janela curta)",
        "Gate 3: ATR expandindo vs baseline (confirma climax)",
        "Entry: fade do movimento · stop 1.2× ATR · tp 1.8× ATR",
    ],
    "edge": "Fade preciso em tops/bottoms locais com volatilidade climax confirmada.",
    "risk": "? em candle data não atinge 0.95 frequentemente — poucos sinais. Research lab.",
    "best_config": {
        "TF":         "15m · 1h",
        "Basket":     "layer1 (Sharpe 1.50)",
        "Status":     "? ? diagnóstico · sinais raros em candles",
    },
}

BRIEFINGS["GRAHAM"] = {
    "what": "Endogenous momentum engine. Trend-following exposures gated by Hawkes branching ratio; trades only when ? indicates sustainable internally-driven momentum.",
    "philosophy": "Nem toda tendência é igual. Algumas são empurradas por eventos externos (news, macro) — frágeis, efêmeras. Outras são endógenas: o mercado se auto-organiza numa direção por forças internas (order flow, posicionamento). Hawkes ? distingue os dois regimes. GRAHAM trada só tendências endógenas: quando ? está na banda ENDO (0.60-0.85), o momentum é sustentável. Fora dessa banda, stand aside.",
    "logic": [
        "Detectar regime Hawkes via ? (endogeneity ratio)",
        "Gate: ? entre ENDO_LOWER e ENDO_UPPER (banda de endogeneidade)",
        "Identificar breakout de estrutura de swing + slope EMA",
        "Entry na direção do trend · stop na estrutura · trail ATR",
        "Exit: ? sai da banda ou reversão de estrutura",
    ],
    "edge": "Momentum filtrado — evita false breakouts e chop.",
    "risk": "Banda ENDO é difícil de calibrar em candles — signals podem sumir inteiramente.",
    "best_config": {
        "TF":         "15m",
        "Status":     "? research lab · calibração ENDO ativa",
    },
}

BRIEFINGS["MEDALLION"] = {
    "what": "Short-horizon ensemble with Kelly-based sizing. Aggregates seven orthogonal micro-signals (return z-score, volume surge, EMA deviation, rolling autocorrelation, RSI extreme, intraday seasonality, HMM chop probability). Direction set empirically based on observed autocorrelation regime.",
    "philosophy": "O mercado é ruído com pequenos fios de sinal — cada indicador isolado explica quase nada. Mas o agregado de muitos sinais fracos, cada um independente, levanta a razão sinal-ruído por vN. É a lei dos grandes números aplicada à alocação: edge individual de 0.7% por trade torna-se retorno robusto quando multiplicado por milhares de operações, dimensionadas por Kelly. MEDALLION honra a metodologia Berlekamp-Laufer 1988-90: curto horizonte, regime verificado empiricamente antes da entrada, ensemble de sinais fracos, saída rápida — e coragem matemática para testar as duas direções (fade ou momentum) e seguir a que a evidência aponta.",
    "logic": [
        "Overshoot detector: z-score de retorno cumulativo em 10 barras",
        "Ensemble 7-D: z-return · z-volume · EMA deviation · autocorrelation · RSI · hour-of-day seasonality · HMM chop probability",
        "Gate de regime: exige autocorrelação rolling = 0 (mean-reversion regime ativo)",
        "Direção: fade por default; --invert ativa momentum (calibrado pra cripto 1h)",
        "Sizing Kelly fracional rolling empirical, fallback em priors, hard cap 2% equity",
        "Exit: stop/TP ATR-based, time stop 8 barras, signal-flip exit",
    ],
    "edge": "Sharpe 2.54 · ROI +51% · MC 100% positivo · 5/6 overfit PASS · edge distribuído em 20 ativos e 365 dias.",
    "risk": "Kelly ramp-up: primeiras ~30 trades com priors, edge só estabiliza depois. Regime-dependent — se autocorrelação virar positiva, engine vai veta por design.",
    "best_config": {
        "TF":         "1h (15m majors não tem edge pós-custos)",
        "Período":    "365 dias",
        "Basket":     "bluechip (20 ativos)",
        "Direção":    "invert=True (momentum em cripto, não fade)",
        "Sharpe val": "2.54 · 225 trades · ROI +51% · DD 7%",
        "MC 1000":    "100% cenários positivos · median +$5k · RoR 0%",
        "Walk-fwd":   "15/20 janelas teste positivas (75%)",
        "Audit":      "5/6 PASS · 1 SKIP (regime) · 0 FAIL · breakeven 14bp",
        "Status":     "✓ EDGE VALIDADO · backtest-ready · live requer aprovação",
    },
}

BRIEFINGS["PHI"] = {
    "what": "Multi-timeframe Fibonacci confluence. Looks for 0.618 retracement agreement across 1D/4H/1H/15m/5m and executes only on a micro trigger with rejection + volume.",
    "philosophy": "Mercados repetem geometria em escalas diferentes. PHI tenta capturar isso sem misticismo: quando várias camadas fractais convergem no mesmo retracement de Fibonacci e o micro-timeframe confirma rejeição real, a entrada deixa de ser um chute isolado e vira uma tese geométrica multi-escala.",
    "logic": [
        "Calcular pivots confirmados e fibs locais em 5 timeframes",
        "Alinhar HTFs ao 5m sem lookahead",
        "Detectar cluster de confluência em torno do 0.618",
        "Filtrar por regime, rejeição, volume e tendência",
        "Entrar só quando O_PHI supera o limiar configurado",
    ],
    "edge": "Pode capturar pullbacks geométricos limpos em ativos muito líquidos quando múltiplas escalas concordam.",
    "risk": "Engine pesado e ainda research-only. Default pode ficar rígido demais; combo solto pode overfit fácil.",
    "best_config": {
        "TF": "5m base · 15m/1h/4h/1d contexto",
        "Status": "? research-only · validar majors/OOS antes de promover",
    },
}

BRIEFINGS["RENAISSANCE"] = {
    "what": "Harmonic pattern recognition. Detects Gartley, Butterfly, Bat, Crab, and Cypher formations via Fibonacci ratios; Bayesian confidence scoring on entropy and Hurst-weighted completion probability.",
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
        "Audit":      "? WR reportado 85% vs auditado 61% — verificar antes do live",
        "Status":     "✓ EDGE CONFIRMADO (com flag de audit)",
    },
}

BRIEFINGS["PAPER"] = BRIEFINGS["DEMO"] = BRIEFINGS["TESTNET"] = BRIEFINGS["LIVE"] = {
    "what": "Production execution layer. Deploys validated backtest logic via Binance Futures API across paper, demo, testnet, and live environments with microstructure and slippage controls.",
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
    "what": "Cross-venue basis arbitrage. Delta-neutral capture of funding-rate divergence, spot-perpetual basis, and inter-exchange spread dislocations with latency-aware execution.",
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
        "Expoente de Hurst: H>0.5 trending, H<0.5 mean-reverting, H˜0.5 random walk",
        "Sazonalidade: hora × dia-da-semana edge scoring de padrões históricos",
    ],
    "edge": "Enxerga transições de regime antes de completarem. Sizing proativo.",
    "risk": "Dependências ML (hmmlearn, arch). Fallback gracioso se não instaladas.",
}


# -----------------------------------------------------------
# BRIEFINGS_V2 — technical view (populated Fase 3.3, 2026-04-11)
# -----------------------------------------------------------
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
            "core/risk/portfolio.py",
            "core/data/htf.py",
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
            "O = 0.30·struct + 0.20·flow + 0.20·cascade + 0.15·momentum + 0.15·pullback",
            "risk = BASE_RISK + t · (min(kelly, MAX_RISK) - BASE_RISK)",
            "kelly = max(0, (WR·RR - (1-WR)) / RR) · KELLY_FRAC",
            "size = account · risk / |entry - stop|",
            "liq_price = entry · (1 ± 1/LEVERAGE ± 0.005)",
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
            "CVD[i] = S(taker_buy - taker_sell)[0..i]",
            "vimb  = taker_buy_ratio[i] rolling-window normalized",
            "liq_proxy = (vol/vol_ma > k) ? (range/atr > k)",
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
             "unit": "s", "effect": "min |funding z-score| to consider extreme"},
        ],
        "formulas": [
            "funding_z = (funding - µ_30d) / s_30d",
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
             "unit": "s","effect": "|z| threshold to open a spread trade"},
            {"name": "NEWTON_ZSCORE_EXIT", "default": 0.0,"range": "-0.5-0.5",
             "unit": "s","effect": "|z| level at which winners are closed"},
            {"name": "NEWTON_ZSCORE_STOP", "default": 3.5,"range": "3.0-5.0",
             "unit": "s","effect": "|z| level that triggers stop-out"},
            {"name": "NEWTON_COINT_PVALUE","default": 0.05,"range": "0.01-0.1",
             "unit": "p","effect": "pair filter: max ADF test p-value"},
            {"name": "NEWTON_SPREAD_WINDOW","default": 200,"range":"100-400",
             "unit": "bars","effect": "rolling window for spread z-score"},
            {"name": "NEWTON_MAX_HOLD",   "default": 150,"range": "80-300",
             "unit": "bars","effect": "max hold bars before time exit"},
        ],
        "formulas": [
            "spread = a_close - ß · b_close - a",
            "z = (spread - µ_window) / s_window",
            "pair selection: Engle-Granger cointegration, p < NEWTON_COINT_PVALUE",
            "half_life ˜ -ln(2) / ln(?_AR1)",
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
             "unit": "s","effect": "sortino floor that pauses a sub-engine"},
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
            "FEATURE_COLS ? AT_OPEN (strict whitelist, asserted at import)",
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
