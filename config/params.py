"""
☿ AURUM Finance — Parâmetros Partilhados
==========================================
Single source of truth para todos os engines.
Qualquer constante usada por mais de um módulo vive aqui.
"""
import math

# Exportar tudo incluindo nomes com _ (necessário para `from config.params import *`)
__all__ = [
    # Universo
    "SYMBOLS", "BASKETS", "select_symbols", "safe_input",
    # Timeframes
    "ENTRY_TF", "INTERVAL", "SCAN_DAYS", "N_CANDLES",
    "HTF_STACK", "MTF_ENABLED", "HTF_N_CANDLES_MAP",
    # Conta & Risco
    "ACCOUNT_SIZE", "BASE_RISK", "MAX_RISK", "LEVERAGE", "CONVEX_ALPHA", "KELLY_FRAC",
    # Custos
    "SLIPPAGE", "SPREAD", "COMMISSION", "FUNDING_PER_8H",
    # Indicadores
    "EMA_SPANS", "RSI_PERIOD", "ATR_PERIOD", "W_NORM", "PIVOT_N", "MIN_SWINGS", "TAKER_WINDOW",
    # RSI
    "RSI_BULL_MIN", "RSI_BULL_MAX", "RSI_BEAR_MIN", "RSI_BEAR_MAX",
    "PULLBACK_ATR_MAX", "CASCADE_MIN",
    # Omega & Score
    "REGIME_MIN_STRENGTH", "SCORE_THRESHOLD", "OMEGA_MIN_COMPONENT",
    "OMEGA_WEIGHTS", "OMEGA_WEIGHTS_FOREX", "BASKETS_FOREX",
    "STOP_ATR_M", "TARGET_RR", "RR_MIN", "MAX_HOLD",
    "TRAIL_BE_MULT", "TRAIL_ACTIVATE_MULT", "TRAIL_DISTANCE_MULT",
    "SCORE_BY_REGIME", "RISK_SCALE_BY_REGIME", "BULL_LONG_MIN_PULLBACK_ATR",
    # Drawdown & Cooldown
    "DD_RISK_SCALE", "REGIME_TRANS_WINDOW", "REGIME_TRANS_ATR_JUMP", "REGIME_TRANS_SIZE_MULT",
    "STREAK_COOLDOWN", "SYM_LOSS_COOLDOWN",
    # Volatilidade
    "SCORE_THRESHOLD_HIGH_VOL", "VOL_WINDOW", "VOL_LOW_PCT", "VOL_HIGH_PCT", "VOL_RISK_SCALE",
    # Portfolio
    "MAX_OPEN_POSITIONS", "CORR_THRESHOLD", "CORR_SOFT_THRESHOLD", "CORR_SOFT_MULT", "CORR_LOOKBACK",
    # Macro
    "MACRO_SYMBOL", "MACRO_SLOPE_BULL", "MACRO_SLOPE_BEAR",
    # MC & WF
    "MC_N", "MC_BLOCK", "WF_TRAIN", "WF_TEST", "VETO_HOURS_UTC",
    # Chop
    "CHOP_BB_PERIOD", "CHOP_BB_STD", "CHOP_RSI_LONG", "CHOP_RSI_SHORT",
    "CHOP_RR", "CHOP_SIZE_MULT", "CHOP_MAX_SLOPE_ABS",
    # Live/Backtest parity filters
    "SPEED_MIN", "SPEED_WINDOW", "SESSION_BLOCK_HOURS", "SESSION_BLOCK_ACTIVE",
    # Omega Risk Table
    "OMEGA_RISK_TABLE",
    # TF Scaling (underscore-prefixed — precisa de __all__ para exportar)
    "_TF_MINUTES", "_tf_params", "_TFP",
    "MIN_STOP_PCT", "SLOPE_N", "CHOP_S21", "CHOP_S200",
    # Newton
    "NEWTON_ZSCORE_ENTRY", "NEWTON_ZSCORE_EXIT", "NEWTON_ZSCORE_STOP",
    "NEWTON_COINT_PVALUE", "NEWTON_HALFLIFE_MIN", "NEWTON_HALFLIFE_MAX",
    "NEWTON_SPREAD_WINDOW", "NEWTON_RECALC_EVERY", "NEWTON_MAX_HOLD",
    "NEWTON_SIZE_MULT", "NEWTON_MIN_PAIRS",
    # Mercurio
    "MERCURIO_CVD_WINDOW", "MERCURIO_CVD_DIV_BARS",
    "MERCURIO_VIMB_WINDOW", "MERCURIO_VIMB_LONG", "MERCURIO_VIMB_SHORT",
    "MERCURIO_LIQ_VOL_MULT", "MERCURIO_LIQ_ATR_MULT",
    "MERCURIO_MIN_SCORE", "MERCURIO_SIZE_MULT",
    # Thoth
    "THOTH_FUNDING_WINDOW", "THOTH_FUNDING_ENTRY",
    "THOTH_OI_WINDOW", "THOTH_LS_CONTRARIAN", "THOTH_LS_CONTRARIAN_LOW",
    "THOTH_WEIGHT_FUNDING", "THOTH_WEIGHT_OI", "THOTH_WEIGHT_LS",
    "THOTH_MIN_SCORE", "THOTH_DIRECTION_THRESHOLD", "THOTH_SIZE_MULT",
    # Darwin
    "DARWIN_EVAL_WINDOW", "DARWIN_MUTATION_CYCLE", "DARWIN_MUTATION_RANGE",
    "DARWIN_MUTATION_MIN_IMPR", "DARWIN_KILL_WINDOWS",
    "DARWIN_ALLOC_TOP", "DARWIN_ALLOC_ABOVE", "DARWIN_ALLOC_BELOW", "DARWIN_ALLOC_KILLED",
    # Chronos
    "CHRONOS_HMM_REGIMES", "CHRONOS_HMM_LOOKBACK",
    "CHRONOS_GARCH_HORIZON", "CHRONOS_GARCH_LOOKBACK",
    "CHRONOS_HURST_WINDOW", "CHRONOS_HURST_MIN", "CHRONOS_SEASON_MIN_SAMPLES",
    # HMM gate — observation-only until manually enabled
    "HMM_GATE_ENABLED", "HMM_MIN_CONFIDENCE", "HMM_BLOCK_REGIMES",
    # Arb scoring (Fase B)
    "ARB_SCORE_WEIGHTS", "ARB_SCORE_THRESHOLDS", "ARB_FILTER_DEFAULTS",
    "ARB_VENUE_RELIABILITY", "ARB_POSITION_SIZE_REF",
    # Frozen engines
    "FROZEN_ENGINES",
    # Ablation
    "ABLATION_DISABLE",
    # Per-engine winning configs (from longrun battery 2026-04-14)
    "ENGINE_INTERVALS", "ENGINE_RISK_SCALE_BY_REGIME", "ENGINE_BASKETS",
]

# ── UNIVERSO ──────────────────────────────────────────────────
SYMBOLS = [
    "BNBUSDT", "INJUSDT", "LINKUSDT", "RENDERUSDT", "NEARUSDT",
    "SUIUSDT",  "ARBUSDT", "SANDUSDT", "XRPUSDT",   "FETUSDT", "OPUSDT",
]

def safe_input(prompt: str = "", default: str = "") -> str:
    """input() that handles EOF/pipe gracefully — returns default on error."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return default

# ── BASKETS DE ATIVOS ────────────────────────────────────────
BASKETS = {
    "default":   SYMBOLS,
    "top12":     ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
                  "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "SUIUSDT"],
    "defi":      ["LINKUSDT", "AAVEUSDT", "UNIUSDT", "MKRUSDT", "SNXUSDT", "COMPUSDT",
                  "CRVUSDT", "SUSHIUSDT", "INJUSDT", "JUPUSDT"],
    "layer1":    ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "NEARUSDT", "SUIUSDT",
                  "APTUSDT", "ATOMUSDT", "DOTUSDT", "ALGOUSDT"],
    "layer2":    ["ARBUSDT", "OPUSDT", "MATICUSDT", "STRKUSDT", "MANTAUSDT", "IMXUSDT"],
    "ai":        ["FETUSDT", "RENDERUSDT", "TAOUSDT", "NEARUSDT", "WLDUSDT", "ARKMUSDT"],
    "meme":      ["DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "BONKUSDT", "FLOKIUSDT", "WIFUSDT"],
    "majors":    ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
    "bluechip":  ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
                  "AVAXUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT", "ATOMUSDT", "NEARUSDT",
                  "INJUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT", "RENDERUSDT", "FETUSDT",
                  "SANDUSDT", "AAVEUSDT"],
    "custom":    [],  # preenchido interativamente
}

# ── BASKETS MT5 (Forex, Equities, Commodities, Indices) ─────
# Exact symbol names depend on the MT5 broker — these are the most common.
# Verify with mt5.symbols() after connecting.
BASKETS_FOREX = {
    "majors":   ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"],
    "crosses":  ["EURJPY", "GBPJPY", "EURGBP", "AUDNZD", "CADJPY", "EURAUD"],
    "metals":   ["XAUUSD", "XAGUSD"],
    "indices":  ["US500", "US30", "GER40", "UK100", "JPN225"],
    "energy":   ["XTIUSD", "XNGUSD"],
}

def select_symbols(current: list | None = None) -> list:
    """
    Interactive basket selector. Returns selected symbols list.
    Called at engine startup to let user choose asset basket.
    """
    if current is None:
        current = SYMBOLS
    print(f"\n  BASKETS DE ATIVOS:")
    _keys = [k for k in BASKETS if k != "custom"]
    for i, k in enumerate(_keys):
        syms = BASKETS[k]
        n = len(syms)
        preview = ", ".join(s.replace("USDT", "") for s in syms[:5])
        if n > 5:
            preview += f", ... (+{n-5})"
        label = f"    [{i+1}] {k:<12} {n:>2} ativos  —  {preview}"
        if k == "default":
            label += "  (atual)"
        print(label)
    print(f"    [{len(_keys)+1}] custom      digitar simbolos manualmente")
    print(f"    [enter]              manter atual ({len(current)} ativos)")

    choice = safe_input("\n  basket > ").strip()
    if not choice:
        return current
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(_keys):
            selected = BASKETS[_keys[idx]]
            print(f"  → {_keys[idx]}: {len(selected)} ativos")
            return selected
        elif idx == len(_keys):
            # custom
            raw = safe_input("  simbolos (separados por virgula, ex: BTC,ETH,SOL) > ").strip()
            if raw:
                syms = []
                for s in raw.split(","):
                    s = s.strip().upper()
                    if not s.endswith("USDT"):
                        s += "USDT"
                    syms.append(s)
                print(f"  → custom: {len(syms)} ativos — {', '.join(s.replace('USDT','') for s in syms)}")
                return syms
    return current

# ── TIMEFRAMES ────────────────────────────────────────────────
ENTRY_TF   = "15m"
INTERVAL   = ENTRY_TF
SCAN_DAYS  = 90
N_CANDLES  = SCAN_DAYS * 24 * 4

HTF_STACK    = ["1h", "4h", "1d"]   # full stack (usado quando MTF_ENABLED=True)
MTF_ENABLED  = False                 # desligado por default — backtest roda sem fractal

HTF_N_CANDLES_MAP = {
    "1h":  SCAN_DAYS * 24 + 300,
    "4h":  SCAN_DAYS *  6 + 200,
    "1d":  SCAN_DAYS      + 200,
}

# ── CONTA & RISCO ─────────────────────────────────────────────
ACCOUNT_SIZE   = 10_000.0
BASE_RISK      = 0.005
MAX_RISK       = 0.015
LEVERAGE       = 1.0       # multiplicador de alavancagem (aplicado ao PnL)
CONVEX_ALPHA   = 0.0       # convex sizing: 0=desligado  0.5=suave  1.0=linear  2.0=agressivo
KELLY_FRAC     = 0.5

# ── CUSTOS ────────────────────────────────────────────────────
SLIPPAGE       = 0.0002
SPREAD         = 0.0001
COMMISSION     = 0.0004
FUNDING_PER_8H = 0.0001

# ── INDICADORES ───────────────────────────────────────────────
EMA_SPANS      = [9, 21, 50, 100, 200]
RSI_PERIOD     = 14
ATR_PERIOD     = 14
W_NORM         = 120
PIVOT_N        = 5
MIN_SWINGS     = 3
TAKER_WINDOW   = 20

# ── RSI FILTROS ───────────────────────────────────────────────
RSI_BULL_MIN, RSI_BULL_MAX = 42, 68
RSI_BEAR_MIN, RSI_BEAR_MAX = 28, 60
PULLBACK_ATR_MAX            = 1.5
CASCADE_MIN                 = 1

# ── OMEGA & SCORE ─────────────────────────────────────────────
REGIME_MIN_STRENGTH = 0.25
SCORE_THRESHOLD     = 0.53    # 0.55 seria ótimo (Sharpe 4.49 grid) mas fica na beira do cliff 0.56 (overfit FAIL); 0.53 é a zona estável
OMEGA_MIN_COMPONENT = 0.15
OMEGA_WEIGHTS       = {
    "struct": 0.25, "flow": 0.25,
    "cascade": 0.20, "momentum": 0.15, "pullback": 0.15,
}
# Forex/CFD: flow disabled (no taker aggression data in decentralized FX)
# Edge comes from struct/cascade/momentum/pullback only
OMEGA_WEIGHTS_FOREX = {
    "struct": 0.35, "flow": 0.00,
    "cascade": 0.30, "momentum": 0.20, "pullback": 0.15,
}
STOP_ATR_M          = 2.8    # grid 2026-04-14 · stops mais largos + SCORE 0.55 → Sharpe 4.49
TARGET_RR           = 3.0
RR_MIN              = 1.5
MAX_HOLD            = 48

# Trailing stop phases
TRAIL_BE_MULT       = 1.0    # move 1.0x risk → stop to breakeven
TRAIL_ACTIVATE_MULT = 1.5    # move 1.5x risk → activate trailing
TRAIL_DISTANCE_MULT = 0.3    # trailing stop distance (grid 2026-04-14: 0.3 gives Sharpe 5.60 vs 5.25 @ 0.5)

SCORE_BY_REGIME: dict[str, float] = {
    "BEAR": 0.53,
    "BULL": 0.55,
    "CHOP": 0.63,
}
RISK_SCALE_BY_REGIME: dict[str, float] = {
    "BEAR": 1.00,
    "BULL": 0.85,
    "CHOP": 0.45,
}
BULL_LONG_MIN_PULLBACK_ATR = 0.15

# ── PER-ENGINE WINNING CONFIGS ─────────────────────────────────
# Configs vencedoras consolidadas.
# ENGINE_INTERVALS + ENGINE_BASKETS = sweet-spot por engine validado por bateria
# longa (360d+, bluechip/default, 6 overfit tests robustness).
# Ver docs/longrun_battery_report_2026-04-14.md.
ENGINE_INTERVALS: dict[str, str] = {
    "CITADEL":     "15m",  # Sharpe +1.38 @ 15m default (360d, longrun 2026-04-14)
    "RENAISSANCE": "15m",  # Sharpe +5.65 @ 15m bluechip (6/6 overfit PASS, longrun 2026-04-14)
    "DESHAW":      "1h",   # Sharpe +2.65 @ 1h vs -0.10 @ 15m (longrun 2026-04-14 bluechip)
    "JUMP":        "1h",   # Sharpe +2.06 @ 1h/720d (6/6 overfit PASS) vs -2.95 @ 15m
    "BRIDGEWATER": "1h",   # Sharpe 5.06 @ 1h vs -1.95 @ 15m (master battery 2026-04-13)
}
# Basket calibrado por engine (universe onde o edge é mais robusto).
# Default fallback = SYMBOLS (11 altcoins). Key engines below have specific tuning.
ENGINE_BASKETS: dict[str, str] = {
    "CITADEL":     "default",   # Sharpe +1.38 default vs -0.35 bluechip (360d 15m)
    "RENAISSANCE": "bluechip",  # Sharpe +5.65, 6/6 overfit PASS (360d 15m)
    "DESHAW":      "bluechip",  # Sharpe +2.65 (360d 1h, 3P 3W 0F overfit)
    "JUMP":        "bluechip",  # Sharpe +2.06 (720d 1h, 6/6 overfit PASS)
    "BRIDGEWATER": "bluechip",  # Sharpe +0.87 (360d 1h)
}
ENGINE_RISK_SCALE_BY_REGIME: dict[str, dict[str, float]] = {
    # CITADEL regime-adaptive: Sharpe 4.43 vs 0.39 com default (180d)
    "CITADEL": {"BEAR": 1.00, "BULL": 0.30, "CHOP": 0.50},
}

# ── DRAWDOWN & COOLDOWN ──────────────────────────────────────
DD_RISK_SCALE: dict[float, float] = {
    0.15: 0.00,
    0.10: 0.25,
    0.07: 0.50,
    0.04: 0.75,
}

REGIME_TRANS_WINDOW     = 8
REGIME_TRANS_ATR_JUMP   = 1.50
REGIME_TRANS_SIZE_MULT  = 0.40

STREAK_COOLDOWN: dict[int, int] = {
    7:  16,
    5:  8,
    3:  4,
    2:  2,
}
SYM_LOSS_COOLDOWN = 3

# ── VOLATILIDADE ──────────────────────────────────────────────
SCORE_THRESHOLD_HIGH_VOL = 0.58

VOL_WINDOW    = 100
VOL_LOW_PCT   = 0.20
VOL_HIGH_PCT  = 0.80
VOL_RISK_SCALE = {
    "LOW":     0.85,
    "NORMAL":  1.00,
    "HIGH":    0.70,
    "EXTREME": 0.00,
}

# ── PORTFOLIO ─────────────────────────────────────────────────
MAX_OPEN_POSITIONS   = 3
CORR_THRESHOLD       = 0.80
CORR_SOFT_THRESHOLD  = 0.75
CORR_SOFT_MULT       = 0.40
CORR_LOOKBACK        = 120

# ── MACRO ─────────────────────────────────────────────────────
MACRO_SYMBOL         = "BTCUSDT"
MACRO_SLOPE_BULL     =  0.05
MACRO_SLOPE_BEAR     = -0.05

# ── MONTE CARLO & WALK-FORWARD ────────────────────────────────
MC_N, MC_BLOCK = 1000, 25
WF_TRAIN, WF_TEST = 20, 10

# EMPIRICAL — validate OOS: 20-24h UTC tem WR=47.5% (diagnostico 190 trades)
# REVERTIDO para baseline — re-testar uma correcção de cada vez (§4)
VETO_HOURS_UTC = []

# ── CHOP MODE ─────────────────────────────────────────────────
CHOP_BB_PERIOD     = 20
CHOP_BB_STD        = 2.0
CHOP_RSI_LONG      = 32
CHOP_RSI_SHORT     = 68
CHOP_RR            = 1.5
CHOP_SIZE_MULT     = 0.40
CHOP_MAX_SLOPE_ABS = 0.025

# ── LIVE/BACKTEST PARITY FILTERS ─────────────────────────────
# Filtros partilhados por live e backtest para garantir trades idênticos.
# Single source of truth — evita drift entre os dois engines.
SPEED_MIN            = 0.002         # range_pct médio mínimo (<mercado muito lento = sem edge>)
SPEED_WINDOW         = 5             # candles para média de speed
SESSION_BLOCK_HOURS  = {2, 3, 4, 5}  # UTC: Ásia baixa liquidez
SESSION_BLOCK_ACTIVE = False         # off por default — backtest e live ambos desligados

# ── OMEGA RISK TABLE ─────────────────────────────────────────
# Graduated risk table — score alto = mais confiança = mais risco
OMEGA_RISK_TABLE: list[tuple[float, float]] = [
    (0.65, 1.20),
    (0.59, 1.00),
    (0.53, 0.80),
    (0.00, 0.50),
]

# ── TIMEFRAME SCALING ─────────────────────────────────────────
_TF_MINUTES: dict[str, int] = {
    "1m":1, "3m":3, "5m":5, "15m":15, "30m":30,
    "1h":60, "2h":120, "4h":240, "6h":360,
    "8h":480, "12h":720, "1d":1440,
}

def _tf_params(interval: str) -> dict:
    m   = _TF_MINUTES.get(interval, 240)
    r   = m / 240
    sr  = math.sqrt(r)
    return {
        "min_stop_pct":  max(0.002, round(0.008 * sr, 4)),
        "slope_n":       max(3, min(80, round(1200 / m))),
        "chop_s21":      round(0.030 * sr, 5),
        "chop_s200":     round(0.010 * sr, 5),
        "pivot_n":       max(5, min(30, round(360 / m))),
        "max_hold":      max(24, min(200, round(11520 / m))),
    }

# ── NEWTON — Statistical Mean Reversion (Pairs Trading) ──────
NEWTON_ZSCORE_ENTRY    = 2.0       # |z-score| > N para entrar
NEWTON_ZSCORE_EXIT     = 0.0       # z-score cruza 0 para sair
NEWTON_ZSCORE_STOP     = 3.5       # |z-score| > N para stop
NEWTON_COINT_PVALUE    = 0.05      # p-value máximo para cointegração válida
NEWTON_HALFLIFE_MIN    = 5         # half-life mínimo (candles)
NEWTON_HALFLIFE_MAX    = 500       # half-life máximo (candles) — ~5d em 15m
NEWTON_SPREAD_WINDOW   = 90        # rolling window para z-score do spread
NEWTON_RECALC_EVERY    = 120       # recalcular cointegração a cada N candles
NEWTON_MAX_HOLD        = 96        # max candles por trade (2× o normal)
NEWTON_SIZE_MULT       = 0.30      # position size relativo ao normal (grid 2026-04-14: 0.30 domina 0.50/0.70 em Sharpe e DD)
NEWTON_MIN_PAIRS       = 2         # mínimo de pares cointegrados para operar

# ── MERCURIO — Order Flow / Microstructure ────────────────────
MERCURIO_CVD_WINDOW     = 20       # janela para CVD divergence
MERCURIO_CVD_DIV_BARS   = 10       # lookback para detectar divergência
MERCURIO_VIMB_WINDOW    = 10       # janela para volume imbalance
MERCURIO_VIMB_LONG      = 0.60     # imbalance > N = bullish
MERCURIO_VIMB_SHORT     = 0.40     # imbalance < N = bearish
MERCURIO_LIQ_VOL_MULT   = 3.0     # spike volume > N× média = liquidação
MERCURIO_LIQ_ATR_MULT   = 2.0     # spike ATR > N× média = liquidação
MERCURIO_MIN_SCORE      = 0.50     # score mínimo para entrada
MERCURIO_SIZE_MULT      = 0.60     # position size multiplier

# ── THOTH — Sentiment Quantificado ───────────────────────────
THOTH_FUNDING_WINDOW    = 30       # períodos de 8h para z-score do funding
THOTH_FUNDING_ENTRY     = 2.0      # |z-score| > N para sinal
THOTH_OI_WINDOW         = 20       # candles para delta OI
THOTH_LS_CONTRARIAN     = 2.0      # ratio > N = crowd long demais
THOTH_LS_CONTRARIAN_LOW = 0.5      # ratio < N = crowd short demais
THOTH_WEIGHT_FUNDING    = 0.40     # peso funding no composite score
THOTH_WEIGHT_OI         = 0.30     # peso OI no composite score
THOTH_WEIGHT_LS         = 0.30     # peso LS ratio no composite score
THOTH_MIN_SCORE         = 0.20     # score mínimo para entrada (grid 2026-04-14: Sharpe 2.71 vs 0.87 @ 0.30)
THOTH_DIRECTION_THRESHOLD = 0.20   # |sent_score| > N para gerar direção
THOTH_SIZE_MULT         = 0.35     # position size multiplier (grid 2026-04-14: Sharpe 7.32 vs 3.41 @ 0.50; MaxDD 18%→6%)

# ── DARWIN — Adaptive Strategy Evolution ─────────────────────
DARWIN_EVAL_WINDOW      = 30      # trades por janela de avaliação
DARWIN_MUTATION_CYCLE    = 100     # trades entre tentativas de mutação
DARWIN_MUTATION_RANGE    = 0.10    # ±10% perturbação de parâmetros
DARWIN_MUTATION_MIN_IMPR = 0.05    # 5% melhoria mínima para adoptar
DARWIN_KILL_WINDOWS      = 3       # janelas negativas consecutivas → pause
DARWIN_ALLOC_TOP         = 0.35    # capital para top performer
DARWIN_ALLOC_ABOVE       = 0.25    # capital para acima da mediana
DARWIN_ALLOC_BELOW       = 0.10    # capital para abaixo da mediana
DARWIN_ALLOC_KILLED      = 0.05    # capital mínimo (engine pausado)

# ── CHRONOS — Time-Series Intelligence ──────────────────────
CHRONOS_HMM_REGIMES     = 3       # número de regimes no HMM
CHRONOS_HMM_LOOKBACK    = 500     # candles para fit do HMM
CHRONOS_GARCH_HORIZON   = 8       # candles de forecast GARCH
CHRONOS_GARCH_LOOKBACK  = 500     # candles para fit GARCH
CHRONOS_HURST_WINDOW    = 100     # janela rolling Hurst
CHRONOS_HURST_MIN       = 50      # min períodos para Hurst
CHRONOS_SEASON_MIN_SAMPLES = 30   # min samples por slot de seasonality

# ── HMM GATE — observação → bloqueio seletivo ───────────────
# Quando HMM_GATE_ENABLED=False (default) o HMM é só observação —
# rótulos aparecem nos trades e no regime_analysis, mas nenhum trade
# é bloqueado pelo HMM. Ligar manualmente só depois de analisar a
# tabela regime_analysis de um backtest longo e decidir quais
# combinações (engine, regime) são tóxicas.
HMM_GATE_ENABLED    = False
HMM_MIN_CONFIDENCE  = 0.60                       # confiança mínima para gate
HMM_BLOCK_REGIMES: dict[str, list[str]] = {}     # ex: {"CHOP": ["CITADEL"]}

# Derived params para o ENTRY_TF default
_TFP            = _tf_params(ENTRY_TF)
MIN_STOP_PCT    = _TFP["min_stop_pct"]
SLOPE_N         = _TFP["slope_n"]
CHOP_S21        = _TFP["chop_s21"]
CHOP_S200       = _TFP["chop_s200"]
# Override PIVOT_N e MAX_HOLD com os valores derivados do TF
PIVOT_N         = _TFP["pivot_n"]
MAX_HOLD        = _TFP["max_hold"]

# ── Fase B: Arb scoring ──────────────────────────────────────
ARB_SCORE_WEIGHTS = {
    "net_apr": 0.30,
    "volume": 0.20,
    "oi": 0.15,
    "risk": 0.15,
    "slippage": 0.10,
    "venue": 0.10,
}
ARB_SCORE_THRESHOLDS = {"go": 70, "maybe": 40}

ARB_FILTER_DEFAULTS = {
    "min_apr": 20.0,
    "min_volume": 500_000,
    "min_oi": 0,
    "risk_max": "HIGH",
    "grade_min": "SKIP",
}

ARB_VENUE_RELIABILITY = {
    "binance": 99, "bybit": 97, "gate": 95, "bitget": 94, "bingx": 92,
    "hyperliquid": 96, "dydx": 94, "paradex": 90,
}

ARB_POSITION_SIZE_REF = 1000.0

# ── Frozen engines ────────────────────────────────────────────
# Engines that are code-complete but should NOT be executed until
# their prerequisites are met. PROMETEU needs 1000+ trades,
# DARWIN needs performance data from other engines, RENAISSANCE
# needs statistical validation of harmonic patterns.
FROZEN_ENGINES = ["PROMETEU", "DARWIN", "RENAISSANCE"]

# ── Ablation testing ─────────────────────────────────────────
# Set to a component name to disable it during ablation runs.
# Valid: "", "struct", "flow", "cascade", "momentum", "pullback"
ABLATION_DISABLE = ""
