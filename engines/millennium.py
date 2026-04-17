"""MILLENNIUM — multi-strategy pod orchestrator.

Architecturally this is the **documented exception** to the rule stated in
CLAUDE.md that engines must not import from one another. MILLENNIUM's whole
reason for existence is to run CITADEL (and, lazily, DE SHAW / JUMP /
BRIDGEWATER / TWO SIGMA) through a shared capital-allocation and kill-switch
layer — it is the "multi-strategy" engine that the coding rule calls out by
name. The static top-of-file ``from engines.citadel import ...`` below and
the lazy ``from engines.<x> import ...`` sites further down are therefore
intentional, not violations to refactor away.
"""
import sys, math, json, random, logging
import numpy as np
import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
from config.params import _tf_params, _TF_MINUTES

from core import (
    fetch_all, validate, indicators, swing_structure, omega,
    detect_macro, build_corr_matrix, portfolio_allows,
    calc_levels, label_trade, position_size,
    prepare_htf, merge_all_htf_to_ltf,
)
from analysis.stats import equity_stats, calc_ratios
from analysis.montecarlo import monte_carlo
from analysis.walkforward import walk_forward, walk_forward_by_regime
from analysis.benchmark import bear_market_analysis, year_by_year_analysis
from analysis.plots import plot_montecarlo, plot_dashboard
from engines.citadel import scan_symbol as azoth_scan, setup_run, log

# ── FORÇAR GLOBALS PARA O TF CORRECTO ─────────────────────────
import config.params as _params
_tf_correct = _tf_params(ENTRY_TF)
_params.SLOPE_N      = _tf_correct["slope_n"]
_params.PIVOT_N      = _tf_correct["pivot_n"]
_params.MIN_STOP_PCT = _tf_correct["min_stop_pct"]
_params.MAX_HOLD     = _tf_correct["max_hold"]
_params.CHOP_S21     = _tf_correct["chop_s21"]
_params.CHOP_S200    = _tf_correct["chop_s200"]
SLOPE_N = _params.SLOPE_N
PIVOT_N = _params.PIVOT_N

# ── MULTISTRATEGY DIRS (lazy — set up in setup_multistrategy()) ──
from pathlib import Path as _Path
MS_RUN_DIR: _Path = _Path(".")
RUN_ID: str = ""


def setup_multistrategy():
    """Initialise backtest runtime + multistrategy-specific dirs and logging."""
    global MS_RUN_DIR, RUN_ID
    RUN_ID, _run_dir = setup_run("multistrategy")
    MS_RUN_DIR = _Path(f"data/millennium/{RUN_ID}")
    (MS_RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
    (MS_RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (MS_RUN_DIR / "charts").mkdir(parents=True, exist_ok=True)
    _ms_fh = logging.FileHandler(MS_RUN_DIR / "logs" / "multistrategy.log", encoding="utf-8")
    _ms_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_ms_fh)

# ── MULTISTRATEGY CONFIG ──────────────────────────────────────
MAX_OPEN_POSITIONS_MS = 5

# LEGADO: pesos usados APENAS pela função ensemble_reweight() (path 2-engine
# CITADEL+RENAISSANCE, ops legadas). O path CORE OPERATIONAL (op=1) — que é
# o default "grande dia" — NÃO usa esses valores; usa BASE_CAPITAL_WEIGHTS
# logo abaixo. Mantidos para não quebrar a função legada ensemble_reweight.
CITADEL_CAPITAL_WEIGHT  = 0.65  # legacy-only (ensemble_reweight)
RENAISSANCE_CAPITAL_WEIGHT = 0.35  # legacy-only (ensemble_reweight)

CONFIRM_WINDOW        = 6
CONFIRM_SIZE_MULT     = 1.25
CONFLICT_ACTION       = "skip"
# BRIDGEWATER removida 2026-04-17 (sessão ~15:40): bateria revelou domínio
# excessivo (88-90% dos trades, 99% shorts, avg R 0.12-0.15). Decisão do
# João: só pode ser re-julgada quando houver histórico de OI/LS suficiente
# pra uma janela inteira relevante (cache de sentiment precisa cobrir 180d+
# em todos os símbolos ativos). Em paralelo, audit rodando pra detectar bug.
# 2026-04-17 ~20h: 4 bugs corrigidos em core/sentiment.py + bridgewater.py.
# Pós-fix valida em 90d BTCUSDT com Sharpe 5.18, 5/6 overfit PASS, 50/50
# direção. Mantida FORA do MILLENNIUM até baterias extras confirmarem.
OPERATIONAL_ENGINES   = ("CITADEL", "RENAISSANCE", "JUMP")
ENGINE_NATIVE_INTERVALS = {
    name: ENGINE_INTERVALS.get(name, INTERVAL)
    for name in OPERATIONAL_ENGINES
}
# Capital weights recalibrados em 2026-04-17 pós-remoção BRIDGEWATER.
# Base anterior (4 engines): JUMP 0.30 / BW 0.30 / REN 0.25 / CIT 0.15.
# Redistribuição dos 0.30 que eram BRIDGEWATER:
#   JUMP:        6/6 PASS Sharpe 4.68, OOS 3 janelas 3.15/3.19/4.27, DSR~1.0 → ganha
#   RENAISSANCE: 6/6 PASS Sharpe 6.54 mas regime-sensitive (CHOP 2019 -0.04) → ganha mais
#   CITADEL:     2/6 FAIL 180d recent (edge decay), janela deslocada OK → mantém leve
BASE_CAPITAL_WEIGHTS  = {
    "JUMP":        0.40,   # edge mais limpo, DSR~1.0; recebeu +0.10
    "RENAISSANCE": 0.40,   # alta WR + R positivo, melhor qualidade por trade; recebeu +0.15
    "CITADEL":     0.20,   # edge decay mas ainda dominante em 360d; recebeu +0.05
}
ENGINE_WEIGHT_FLOORS = {
    "JUMP":        0.20,   # piso garantido
    "RENAISSANCE": 0.10,   # pode cair em CHOP
    "CITADEL":     0.05,   # pode quase zerar em decay
}
ENGINE_WEIGHT_CAPS = {
    "JUMP":        0.50,
    "RENAISSANCE": 0.50,   # antigo 0.30; agora pode liderar em CHOP
    "CITADEL":     0.25,   # antigo 0.15; leve folga
}
ENGINE_ACTIVITY_WINDOW = 120
ENGINE_ACTIVITY_SOFT_CAP = {
    "JUMP":        0.55,
    "RENAISSANCE": 0.45,   # antigo 0.35
    "CITADEL":     0.35,   # antigo 0.30
}
ENGINE_DRAWDOWN_WINDOW = 30
ENGINE_DRAWDOWN_WARN_R = 2.0
ENGINE_DRAWDOWN_HARD_R = 4.0
ENGINE_DRAWDOWN_MIN_FACTOR = 0.45
PORTFOLIO_EXECUTION_ENABLED = False  # TEMP: F_gate_off diagnostic — revert after
# Gate config ajustada via tools/millennium_gate_grid.py 180d (2026-04-17):
# config "D_liberal" dominou baseline em Sharpe (+1.53), Sortino (+3.17),
# PnL 2.5x, +19 trades (JUMP +18, CIT +2, REN -1), custo MDD +0.5pp.
# Pesos + thresholds afrouxados pra deixar JUMP trabalhar em janelas
# curtas onde score recente ainda nao estabilizou.
PORTFOLIO_MIN_WEIGHT = {
    "JUMP":        0.25,   # antes 0.32 — JUMP raramente atingia 0.32 em
    "RENAISSANCE": 0.22,   # stretches de REN dominante
    "CITADEL":     0.18,
}
PORTFOLIO_CHALLENGER_RATIO = 0.85      # antes 0.92 — menos strict pra
                                        # challenger passar quando leader
                                        # tem vantagem marginal
# CHALLENGER_MAX_GAP compara pontos percentuais de peso (leader - challenger).
# Com ENGINE_WEIGHT_CAPS permitindo 0.50 pro leader, 0.06 gap era efetivo
# kill-switch pra CITADEL + JUMP (REN costuma liderar em BULL/BEAR = 0.40-0.50,
# gap vs CITADEL 0.20 = 0.20-0.30 >> 0.06). Elevado pra 0.25 permite
# challenger real participar quando ratio passa.
PORTFOLIO_CHALLENGER_MAX_GAP = 0.25
PORTFOLIO_GLOBAL_COOLDOWN_BARS = 1
PORTFOLIO_STRATEGY_COOLDOWN_BARS = {
    "JUMP":        2,
    "RENAISSANCE": 2,
    "CITADEL":     2,
}
PORTFOLIO_REGIME_COOLDOWN_MULT = {
    "BULL": 1.0,
    "BEAR": 1.5,
    "CHOP": 1.5,            # antes 2.0 — CHOP cooldown 4 bars matava JUMP
                            # (sinais order-flow tem validade curta)
}
PORTFOLIO_ACCEPTED_WINDOW = 80
PORTFOLIO_MIN_ACCEPTED_SHARE = {
    "CITADEL": 0.12,
    "RENAISSANCE": 0.22,
    "JUMP": 0.35,           # antes 0.25 — diversity_override mais generoso
                            # pro JUMP quando fica tempo sem passar
}
JUMP_RECENT_QUALITY_WINDOW = 30
JUMP_MIN_SCORE_BASE = 0.79       # antes 0.80 — 1pp abaixo do p25 histórico
JUMP_MIN_SCORE_WEAK = 0.80       # antes 0.82 — era kill-switch de facto
JUMP_MIN_SCORE_STRESSED = 0.81   # antes 0.84 — idem, 2% passage

# ── COOLDOWN GATES (independent of portfolio execution gate) ──────
# Rodam mesmo com PORTFOLIO_EXECUTION_ENABLED=False. Miram o padrao
# observado em 360d F_gate_off: CITADEL levou 4 LOSS consecutive em
# XRP/SUI/RENDER em 2025-07-19..22, contribuindo para o worst_dd.
SYMBOL_COOLDOWN_ENABLED = True
SYMBOL_COOLDOWN_BARS_AFTER_LOSS = 24   # 24 × 15m = 6h sem retry no mesmo symbol
ENGINE_LOSS_STREAK_ENABLED = True
ENGINE_LOSS_STREAK_THRESHOLD = 3       # N LOSS consecutive na mesma engine
ENGINE_LOSS_STREAK_SKIPS = 2           # pula proximos M trades da engine

# ── ENSEMBLE WEIGHTING ────────────────────────────────────────
ENSEMBLE_WINDOW    = 30    # trades lookback para scoring rolling
ENSEMBLE_MIN_W     = 0.20  # peso mínimo por estratégia (nunca zera)
ENSEMBLE_MAX_W     = 0.80  # peso máximo por estratégia
ENSEMBLE_STAB_WIN  = 60    # janela longa para penalidade de instabilidade
KILL_SWITCH_SORTINO= -0.5  # Sortino abaixo disto → estratégia pausada (peso=MIN_W)
KILL_SWITCH_WINDOW = 20    # trades recentes para avaliação do kill-switch
CONFIDENCE_N_MIN   = 50    # trades para confiança plena: score × sqrt(n/50)
REGIME_LAG         = 5     # lag artificial: usa regime de 5 trades atrás → quebra feedback loop

# Regime-aware: amplifica pesos baseado no macro actual
# TREND (BULL/BEAR) → CITADEL lidera | RANGE (CHOP) → RENAISSANCE lidera
REGIME_BOOST = {
    "BULL": {"CITADEL": 1.15, "RENAISSANCE": 0.90, "JUMP": 1.10},
    "BEAR": {"CITADEL": 1.05, "RENAISSANCE": 0.95, "JUMP": 0.90},
    "CHOP": {"CITADEL": 0.90, "RENAISSANCE": 1.20, "JUMP": 1.00},
}
REGIME_BOOST_WINDOW = 20   # trades para detectar regime actual (probabilístico)
R_CAP_MAX    =  5.0        # R-multiple máximo (evita outlier distorcer score)
R_CAP_MIN    = -3.0        # R-multiple mínimo
DECAY_WINDOW = 20          # trades por sub-janela para detecção de decay
DECAY_PENALTY= 0.80        # score × este factor se decay detectado

# ── STRESS TEST ───────────────────────────────────────────────
STRESS_SIMS      = 500   # simulações por cenário
STRESS_CRISIS_N  = 3     # número de janelas de crise injectadas
STRESS_CRISIS_W  = 20    # duração de cada crise (trades)
STRESS_CRISIS_MUL= 0.30  # PnL durante crise × 0.30
STRESS_SLIP_MIN  = 0.001 # slippage adicional mínimo por trade
STRESS_SLIP_MAX  = 0.004 # slippage adicional máximo por trade
STRESS_MISS_RATE = 0.15  # % trades que não executam (latência)

# ── RENAISSANCE (extracted to core/harmonics.py) ──────────────────
from core.harmonics import scan_hermes
from core.fs import atomic_write

SEP = "─"*80

def _derive_end_time_ms(all_dfs) -> int | None:
    """Extrai o timestamp do último candle (em ms) a partir de all_dfs.

    Usado para passar end_time_ms para collect_sentiment de BRIDGEWATER e
    evitar look-ahead em backtest OOS — o sentiment é fetched relativo ao
    fim da janela de dados, não à hora atual.

    Em runs com janela recente/live-like, retorna ~agora (comportamento
    idêntico ao antigo sem end_time_ms). Em runs OOS, retorna o fim do
    backtest → fetch honesto.
    """
    try:
        for df in all_dfs.values():
            if df is None or len(df) == 0 or "time" not in df.columns:
                continue
            return int(df["time"].iloc[-1].timestamp() * 1000)
    except Exception:
        pass
    return None


# ── ENSEMBLE WEIGHTING ────────────────────────────────────────
def _std(lst):
    if len(lst) < 2: return 0.0
    m = sum(lst)/len(lst)
    return (sum((x-m)**2 for x in lst)/(len(lst)-1))**0.5

def _r_multiple(t):
    """
    R-multiple = pnl / risco_em_$ do trade.
    Remove viés de tamanho de posição e leverage — mede qualidade pura do edge.
    Clamped a [R_CAP_MIN, R_CAP_MAX] para evitar que outliers dominem o score.
    """
    risk_price = abs(t.get("entry", 0) - t.get("stop", 0))
    size       = t.get("size", 0)
    risk_usd   = risk_price * size
    if risk_usd < 1e-8: return 0.0
    r = t["pnl"] / risk_usd
    return max(R_CAP_MIN, min(R_CAP_MAX, r))   # cap: evita +20R distorcer Sortino

def _adaptive_window(r_hist):
    """
    Janela adaptativa com transição suave (não binária).
    Vol recente alta → window menor (reactivo). Vol baixa → window maior (estável).
    A suavização usa EMA implícita via ratio contínuo clamped — evita oscilações.
    """
    n = len(r_hist)
    if n < 10: return ENSEMBLE_WINDOW
    # usa janela de 20 para std_recent (mais estável que 10)
    std_recent   = _std(r_hist[-20:]) if n >= 20 else _std(r_hist)
    std_longterm = _std(r_hist)
    if std_longterm < 1e-8: return ENSEMBLE_WINDOW
    # ratio contínuo clamped [0.5, 2.0] → transição suave sem saltos
    vol_ratio = max(0.5, min(std_recent / std_longterm, 2.0))
    w = ENSEMBLE_WINDOW / vol_ratio  # alta vol → window menor
    return max(KILL_SWITCH_WINDOW, min(ENSEMBLE_STAB_WIN, int(w)))

def _regime_confidence_boost(recent_trades):
    """
    Regime-aware boost PROBABILÍSTICO em vez de binário.
    Usa proporção de BULL/BEAR/CHOP nos últimos REGIME_BOOST_WINDOW trades
    como pesos — evita saltos bruscos quando o regime está a mudar.

    Ex: BULL=60%, BEAR=30%, CHOP=10%
        az_boost = 0.6×1.25 + 0.3×1.20 + 0.1×0.75 = 1.185
        he_boost = 0.6×0.75 + 0.3×0.80 + 0.1×1.25 = 0.695
    """
    biases = [t.get("macro_bias","CHOP") for t in recent_trades[-REGIME_BOOST_WINDOW:]
              if t.get("macro_bias")]
    if not biases:
        return {name: 1.0 for name in BASE_CAPITAL_WEIGHTS}, "CHOP"

    from collections import Counter
    counts = Counter(biases); total = len(biases)
    p = {r: counts.get(r, 0)/total for r in ("BULL","BEAR","CHOP")}
    dominant = max(p, key=p.get)

    boosts = {}
    for name in BASE_CAPITAL_WEIGHTS:
        boosts[name] = round(sum(p[r] * REGIME_BOOST[r][name] for r in ("BULL","BEAR","CHOP")), 3)
    return boosts, dominant

def _decay_score(r_hist):
    """
    Detecta decay estrutural via declínio do R-multiple médio.
    Usa FORÇA do declínio (slope normalizado), não só monotonicidade.

    decay_strength = (m1 - m3) / |m1|  — queda relativa ao nível original
    Decay fraco (cíclico): m1≈m3 → score baixo → penalidade mínima
    Decay forte (estrutural): m1>>m3 → score alto → penalidade real
    """
    if len(r_hist) < DECAY_WINDOW * 3: return 0.0
    chunks = [r_hist[-DECAY_WINDOW*3:-DECAY_WINDOW*2],
              r_hist[-DECAY_WINDOW*2:-DECAY_WINDOW],
              r_hist[-DECAY_WINDOW:]]
    means = [sum(c)/len(c) for c in chunks if c]
    if len(means) < 3: return 0.0
    if not (means[0] > means[1] > means[2]): return 0.0   # monotonicidade mínima

    # força do decay: queda normalizada pelo nível inicial
    baseline = max(abs(means[0]), 0.1)   # evita divisão por near-zero
    decay_strength = (means[0] - means[2]) / baseline

    # só penaliza se a queda for significativa (>20% do R original)
    return min(1.0, max(0.0, decay_strength - 0.20))

def _sortino(pnl_hist, window):
    """Sortino rolling — não penaliza volatilidade de lucro."""
    h = pnl_hist[-window:] if len(pnl_hist) >= window else pnl_hist
    if len(h) < 3: return None
    mean = sum(h)/len(h)
    losses = [p for p in h if p < 0]
    down_std = (sum(p**2 for p in losses)/max(len(losses),1))**0.5
    return (mean/down_std) if down_std else (mean * 10 if mean > 0 else 0.0)

def _ensemble_score(r_hist):
    """
    Score composto para ensemble weighting (opera sobre R-multiples capped):
      1. Sortino rolling com janela adaptativa suave
      2. Kill-switch (Sortino curto prazo < KILL_SWITCH_SORTINO)
      3. Penalidade de instabilidade (vol_recente > vol_longo_prazo)
      4. Decay detection (R-mean declina 3 sub-janelas consecutivas)

    Retorna (score: float, killed: bool)
    """
    if len(r_hist) < 3:
        return 0.5, False   # prior neutro no warm-up

    window = _adaptive_window(r_hist)

    # 1. Sortino com janela adaptativa
    s = _sortino(r_hist, window)
    if s is None: return 0.5, False
    score = max(0.0, s)

    # 2. Kill-switch
    s_kill = _sortino(r_hist, KILL_SWITCH_WINDOW)
    killed = (s_kill is not None and s_kill < KILL_SWITCH_SORTINO)
    if killed:
        return 0.0, True

    # 3. Penalidade de instabilidade
    if len(r_hist) >= ENSEMBLE_STAB_WIN:
        recent   = r_hist[-window:]
        longterm = r_hist[-ENSEMBLE_STAB_WIN:-window]
        std_r = _std(recent); std_l = _std(longterm)
        if std_l > 0 and std_r > std_l:
            stability = max(0.3, std_l / std_r)
            score *= stability

    # 4. Decay detection — edge estrutural a morrer lentamente
    decay = _decay_score(r_hist)
    if decay > 0.2:
        score *= max(DECAY_PENALTY, 1.0 - decay * 0.5)

    # 5. Confidence penalty com Bayesian shrinkage
    #    ((n+5)/(N+5))^0.5: prior implícito de 5 trades evita penalidade excessiva no arranque
    #    10 trades→0.50×  25 trades→0.74×  50+ trades→1.0×
    confidence = min(1.0, ((len(r_hist) + 5) / (CONFIDENCE_N_MIN + 5)) ** 0.5)
    score *= confidence

    return max(0.0, score), False


def _recent_drawdown_penalty(r_hist):
    """Soft-cap a strategy when recent closed-trade drawdown in R is widening."""
    if len(r_hist) < max(6, ENGINE_DRAWDOWN_WINDOW // 3):
        return 1.0, 0.0
    equity = 0.0
    peak = 0.0
    max_dd_r = 0.0
    for r in r_hist[-ENGINE_DRAWDOWN_WINDOW:]:
        equity += float(r)
        peak = max(peak, equity)
        max_dd_r = max(max_dd_r, peak - equity)
    if max_dd_r <= ENGINE_DRAWDOWN_WARN_R:
        return 1.0, max_dd_r
    if max_dd_r >= ENGINE_DRAWDOWN_HARD_R:
        return ENGINE_DRAWDOWN_MIN_FACTOR, max_dd_r
    span = max(ENGINE_DRAWDOWN_HARD_R - ENGINE_DRAWDOWN_WARN_R, 1e-9)
    slope = (max_dd_r - ENGINE_DRAWDOWN_WARN_R) / span
    factor = 1.0 - (1.0 - ENGINE_DRAWDOWN_MIN_FACTOR) * slope
    return max(ENGINE_DRAWDOWN_MIN_FACTOR, min(1.0, factor)), max_dd_r


def _bar_minutes() -> int:
    return max(int(_TF_MINUTES.get(INTERVAL, 15)), 1)


def _n_candles_for_interval(days: int, interval: str, *, with_buffer: bool = False) -> int:
    minutes = max(int(_TF_MINUTES.get(interval, _TF_MINUTES.get(INTERVAL, 15))), 1)
    candles = int(days * 24 * 60 / minutes)
    if not with_buffer:
        return candles
    if interval == "1h":
        return candles + 300
    if interval == "4h":
        return candles + 200
    if interval == "1d":
        return candles + 200
    return candles


def _load_interval_context(interval: str) -> dict:
    interval = str(interval or INTERVAL)
    n_candles = _n_candles_for_interval(SCAN_DAYS, interval)
    print(f"\n{SEP}\n  DADOS   {interval}   {n_candles:,} candles\n{SEP}")
    _fetch_syms = list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)
    all_dfs = fetch_all(_fetch_syms, interval=interval, n_candles=n_candles)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        raise RuntimeError(f"sem dados para intervalo {interval}")

    htf_stack_by_sym = {}
    if MTF_ENABLED:
        for tf in HTF_STACK:
            nc = _n_candles_for_interval(SCAN_DAYS, tf, with_buffer=True)
            print(f"\n{SEP}\n  HTF   {interval}->{tf}   {nc:,} candles\n{SEP}")
            tf_dfs = fetch_all(list(all_dfs.keys()), interval=tf, n_candles=nc)
            for sym, df_h in tf_dfs.items():
                df_h = prepare_htf(df_h, htf_interval=tf)
                htf_stack_by_sym.setdefault(sym, {})[tf] = df_h

    print(f"\n{SEP}\n  PRE-PROCESSAMENTO [{interval}]\n{SEP}")
    macro_series = detect_macro(all_dfs)
    if macro_series is not None:
        bull_n = (macro_series == "BULL").sum()
        bear_n = (macro_series == "BEAR").sum()
        chop_n = (macro_series == "CHOP").sum()
        total = bull_n + bear_n + chop_n
        print(
            f"  Macro ({MACRO_SYMBOL})    BULL {bull_n}c ({bull_n/max(total,1)*100:.0f}%)   "
            f"BEAR {bear_n}c ({bear_n/max(total,1)*100:.0f}%)   CHOP {chop_n}c ({chop_n/max(total,1)*100:.0f}%)"
        )
    corr = build_corr_matrix(all_dfs)
    return {
        "interval": interval,
        "n_candles": n_candles,
        "all_dfs": all_dfs,
        "htf_stack_by_sym": htf_stack_by_sym,
        "macro_series": macro_series,
        "corr": corr,
    }


def _load_operational_contexts() -> dict[str, dict]:
    interval_cache: dict[str, dict] = {}
    contexts: dict[str, dict] = {}
    print(f"\n{SEP}\n  CORE OPERATIONAL · TF NATIVO POR ESTRATÉGIA\n{SEP}")
    for engine_name in OPERATIONAL_ENGINES:
        interval = ENGINE_NATIVE_INTERVALS.get(engine_name, INTERVAL)
        if interval not in interval_cache:
            interval_cache[interval] = _load_interval_context(interval)
        ctx = interval_cache[interval]
        contexts[engine_name] = {
            "engine": engine_name,
            "interval": interval,
            "n_candles": ctx["n_candles"],
            "all_dfs": ctx["all_dfs"],
            "htf_stack_by_sym": ctx["htf_stack_by_sym"],
            "macro_series": ctx["macro_series"],
            "corr": ctx["corr"],
        }
        print(f"  {engine_name:12s}  ->  {interval}")
    return contexts


def _bars_since(prev_ts, cur_ts) -> float:
    if prev_ts is None or cur_ts is None:
        return float("inf")
    try:
        prev = pd.Timestamp(prev_ts)
        cur = pd.Timestamp(cur_ts)
    except Exception:
        return float("inf")
    delta_m = (cur - prev).total_seconds() / 60.0
    if delta_m < 0:
        return 0.0
    return delta_m / _bar_minutes()


def _portfolio_execution_gate(trade, strat, final_w, dominant, last_portfolio_ts,
                              last_strategy_ts, accepted_history, history):
    """Decide whether the portfolio should actually take this trade."""
    if not PORTFOLIO_EXECUTION_ENABLED:
        return True, "disabled", {}

    ts = trade.get("timestamp")
    dyn_w = float(final_w.get(strat, 0.0))
    leader = max(final_w, key=final_w.get)
    leader_w = float(final_w.get(leader, dyn_w))
    leader_gap = max(0.0, leader_w - dyn_w)

    if strat == "JUMP":
        score = float(trade.get("score") or 0.0)
        recent_r = history.get("JUMP", [])[-JUMP_RECENT_QUALITY_WINDOW:]
        avg_recent_r = (sum(recent_r) / len(recent_r)) if recent_r else 0.0
        min_score = JUMP_MIN_SCORE_BASE
        if recent_r and avg_recent_r < 0.0:
            min_score = JUMP_MIN_SCORE_STRESSED
        elif recent_r and avg_recent_r < 0.08:
            min_score = JUMP_MIN_SCORE_WEAK
        if min_score > 0.0 and score <= min_score:
            return False, "jump_quality_floor", {
                "leader": leader,
                "leader_w": leader_w,
                "dyn_w": dyn_w,
                "leader_gap": leader_gap,
                "jump_avg_recent_r": round(avg_recent_r, 3),
                "jump_min_score": round(min_score, 3),
                "score": round(score, 3),
            }

    min_w = float(PORTFOLIO_MIN_WEIGHT.get(strat, 0.0))
    if dyn_w < min_w:
        return False, "min_weight", {
            "leader": leader,
            "leader_w": leader_w,
            "dyn_w": dyn_w,
            "leader_gap": leader_gap,
        }

    if strat != leader:
        ratio = dyn_w / max(leader_w, 1e-9)
        if ratio < PORTFOLIO_CHALLENGER_RATIO or leader_gap > PORTFOLIO_CHALLENGER_MAX_GAP:
            recent = accepted_history[-PORTFOLIO_ACCEPTED_WINDOW:]
            total_recent = len(recent)
            accepted_share = (
                sum(1 for name in recent if name == strat) / total_recent
                if total_recent > 0 else 0.0
            )
            min_share = PORTFOLIO_MIN_ACCEPTED_SHARE.get(strat, 0.0)
            strategy_need = max(0.0, PORTFOLIO_STRATEGY_COOLDOWN_BARS.get(strat, 0))
            strategy_bars = _bars_since(last_strategy_ts.get(strat), ts)
            if total_recent >= 12 and accepted_share < min_share and strategy_bars >= strategy_need:
                return True, "diversity_override", {
                    "leader": leader,
                    "leader_w": leader_w,
                    "dyn_w": dyn_w,
                    "leader_gap": leader_gap,
                    "accepted_share": round(accepted_share, 3),
                    "min_share": round(min_share, 3),
                }
            return False, f"not_leader:{leader}", {
                "leader": leader,
                "leader_w": leader_w,
                "dyn_w": dyn_w,
                "leader_gap": leader_gap,
                "accepted_share": round(accepted_share, 3),
                "min_share": round(min_share, 3),
            }

    regime_mult = float(PORTFOLIO_REGIME_COOLDOWN_MULT.get(dominant, 1.0))
    global_need = max(0.0, PORTFOLIO_GLOBAL_COOLDOWN_BARS * regime_mult)
    global_bars = _bars_since(last_portfolio_ts, ts)
    if global_bars < global_need:
        return False, "portfolio_cooldown", {
            "leader": leader,
            "leader_w": leader_w,
            "dyn_w": dyn_w,
            "leader_gap": leader_gap,
            "bars_since_portfolio": round(global_bars, 2),
        }

    strategy_need = max(0.0, PORTFOLIO_STRATEGY_COOLDOWN_BARS.get(strat, 0) * regime_mult)
    strategy_bars = _bars_since(last_strategy_ts.get(strat), ts)
    if strategy_bars < strategy_need:
        return False, f"strategy_cooldown:{strat}", {
            "leader": leader,
            "leader_w": leader_w,
            "dyn_w": dyn_w,
            "leader_gap": leader_gap,
            "bars_since_strategy": round(strategy_bars, 2),
        }

    return True, "accepted", {
        "leader": leader,
        "leader_w": leader_w,
        "dyn_w": dyn_w,
        "leader_gap": leader_gap,
        "bars_since_portfolio": round(global_bars, 2),
        "bars_since_strategy": round(strategy_bars, 2),
    }

def ensemble_reweight(all_trades):
    """
    Ajusta dinamicamente os pesos CITADEL/RENAISSANCE.
    Sem lookahead: cada trade usa apenas performance ANTERIOR.

    Pipeline:
      1. Score via _ensemble_score() sobre R-multiples (não PnL raw)
      2. Normaliza scores → weights [MIN_W, MAX_W]
      3. Kill-switch → peso mínimo + log de evento
      4. Regime-aware boost: macro actual amplifica pesos naturais
      5. Escala PnL: pnl_adj = pnl × (dynamic_w / static_w)
    """
    sorted_t  = sorted(all_trades, key=lambda t: t["timestamp"])
    history   = {"CITADEL": [], "RENAISSANCE": []}   # R-multiples, não PnL raw
    kill_log  = {"CITADEL": [], "RENAISSANCE": []}
    out       = []

    for idx, t in enumerate(sorted_t):
        strat = t.get("strategy", "CITADEL")

        az_sc, az_killed = _ensemble_score(history["CITADEL"])
        he_sc, he_killed = _ensemble_score(history["RENAISSANCE"])

        if az_killed: az_sc = 0.0
        if he_killed: he_sc = 0.0
        total = az_sc + he_sc

        if total < 0.001:
            az_w = CITADEL_CAPITAL_WEIGHT
            he_w = RENAISSANCE_CAPITAL_WEIGHT
        else:
            az_w = max(ENSEMBLE_MIN_W, min(ENSEMBLE_MAX_W, az_sc / total))
            he_w = 1.0 - az_w

        if az_killed: az_w = ENSEMBLE_MIN_W; he_w = 1.0 - az_w
        if he_killed: he_w = ENSEMBLE_MIN_W; az_w = 1.0 - he_w

        # penalidade de DD simultâneo — ambas em drawdown ao mesmo tempo
        # indica falha sistémica, não individual → reduz exposição global
        az_dd = max(0.0, 1.0 - (az_sc / max(_ensemble_score(history["CITADEL"][:max(0,len(history["CITADEL"])-ENSEMBLE_WINDOW)])[0], 0.001))) if len(history["CITADEL"]) > ENSEMBLE_WINDOW else 0.0
        he_dd = max(0.0, 1.0 - (he_sc / max(_ensemble_score(history["RENAISSANCE"][:max(0,len(history["RENAISSANCE"])-ENSEMBLE_WINDOW)])[0], 0.001))) if len(history["RENAISSANCE"]) > ENSEMBLE_WINDOW else 0.0
        if az_dd > 0.3 and he_dd > 0.3:   # ambas a degradar simultaneamente
            sim_dd_mult = max(0.70, 1.0 - (az_dd + he_dd) * 0.15)
            az_w *= sim_dd_mult
            he_w *= sim_dd_mult
            # re-normaliza
            total_sim = az_w + he_w
            if total_sim > 0: az_w /= total_sim; he_w /= total_sim

        # regime-aware boost probabilístico com LAG adaptativo
        # lag maior em vol alta (mercado errático) → menos acoplamento
        # lag menor em vol baixa (mercado estável) → mais responsivo
        az_win    = _adaptive_window(history["CITADEL"]) if history["CITADEL"] else ENSEMBLE_WINDOW
        dyn_lag   = int(max(3, min(10, az_win / 10)))
        lag_idx   = max(0, idx - dyn_lag)
        boost, dominant = _regime_confidence_boost(sorted_t[:lag_idx+1])
        az_w_r = az_w * boost["CITADEL"]
        he_w_r = he_w * boost["RENAISSANCE"]
        # re-normaliza após boost + clamp
        total_r = az_w_r + he_w_r
        az_w_f  = max(ENSEMBLE_MIN_W, min(ENSEMBLE_MAX_W, az_w_r / total_r))
        he_w_f  = 1.0 - az_w_f

        static_w  = CITADEL_CAPITAL_WEIGHT if strat == "CITADEL" else RENAISSANCE_CAPITAL_WEIGHT
        dynamic_w = az_w_f if strat == "CITADEL" else he_w_f
        scale     = dynamic_w / static_w if static_w > 0 else 1.0

        out.append({**t,
            "pnl":               round(t["pnl"] * scale, 2),
            "pnl_pre_ensemble":  t["pnl"],
            "ensemble_w":        round(dynamic_w, 3),
            "az_w":              round(az_w_f, 3),
            "he_w":              round(he_w_f, 3),
            "az_killed":         az_killed,
            "he_killed":         he_killed,
            "regime_at_trade":   dominant,
            "az_decay":          round(_decay_score(history["CITADEL"]), 3),
            "he_decay":          round(_decay_score(history["RENAISSANCE"]), 3),
        })

        # log kill-switch
        for s, killed in [("CITADEL", az_killed), ("RENAISSANCE", he_killed)]:
            log = kill_log[s]
            if killed and (not log or len(log) % 2 == 0):
                log.append(t["timestamp"])
            elif not killed and log and len(log) % 2 == 1:
                log.append(t["timestamp"])

        if t["result"] in ("WIN", "LOSS"):
            history[strat].append(_r_multiple(t))

    if out: out[-1]["_kill_log"] = kill_log
    return sorted(out, key=lambda t: t["timestamp"])

def operational_core_reweight(all_trades):
    """Generic ensemble weighting for the engines in OPERATIONAL_ENGINES.

    Filters dinamicamente — qualquer engine listado em OPERATIONAL_ENGINES
    é processado; os demais pass-through. Originalmente 4 engines, reduzido
    para 3 (CITADEL + RENAISSANCE + JUMP) em 2026-04-17 após remoção do
    BRIDGEWATER pendente histórico OI/LS.
    """
    sorted_t = sorted(all_trades, key=lambda t: t["timestamp"])
    active_strats = [name for name in OPERATIONAL_ENGINES if any(t.get("strategy") == name for t in sorted_t)]
    if not active_strats:
        return sorted_t

    history = {name: [] for name in active_strats}
    kill_log = {name: [] for name in active_strats}
    gate_blocked = Counter()
    gate_accepted = Counter()
    gate_leaders = Counter()
    accepted_history = []
    out = []
    last_portfolio_ts = None
    last_strategy_ts = {}
    # Cooldown trackers (funcionam com ou sem portfolio gate).
    last_symbol_loss_ts: dict[str, object] = {}
    engine_loss_streak: dict[str, int] = {}
    engine_cooldown_skips: dict[str, int] = {}

    for idx, t in enumerate(sorted_t):
        strat = t.get("strategy", "CITADEL")
        if strat not in active_strats:
            out.append(dict(t))
            continue

        score_map = {}
        killed_map = {}
        for name in active_strats:
            sc, killed = _ensemble_score(history[name])
            score_map[name] = 0.0 if killed else sc
            killed_map[name] = killed

        total = sum(score_map.values())
        if total < 0.001:
            raw_w = {name: BASE_CAPITAL_WEIGHTS[name] for name in active_strats}
        else:
            raw_w = {name: score_map[name] / total for name in active_strats}

        killed_names = [name for name, killed in killed_map.items() if killed]
        if killed_names and len(killed_names) < len(active_strats):
            survivors = [name for name in active_strats if name not in killed_names]
            survivor_mass = 1.0 - ENSEMBLE_MIN_W * len(killed_names)
            survivor_total = sum(raw_w[name] for name in survivors)
            adj_w = {}
            for name in survivors:
                base = raw_w[name] / survivor_total if survivor_total > 0 else 1.0 / len(survivors)
                adj_w[name] = base * survivor_mass
            for name in killed_names:
                adj_w[name] = ENSEMBLE_MIN_W
            raw_w = adj_w

        max_window = max((_adaptive_window(history[name]) if history[name] else ENSEMBLE_WINDOW) for name in active_strats)
        dyn_lag = int(max(3, min(10, max_window / 10)))
        lag_idx = max(0, idx - dyn_lag)
        boost, dominant = _regime_confidence_boost(sorted_t[:lag_idx+1])
        boosted_w = {name: raw_w[name] * boost.get(name, 1.0) for name in active_strats}
        # Gate CHOP — RENAISSANCE colapsou em CHOP 2019 OOS (Sharpe -0.04 com 16 trades).
        # Zera o peso quando o regime dominante detectado é CHOP.
        if dominant == "CHOP" and "RENAISSANCE" in boosted_w:
            boosted_w["RENAISSANCE"] = ENSEMBLE_MIN_W
        recent_window = [
            tt for tt in sorted_t[max(0, idx - ENGINE_ACTIVITY_WINDOW):idx]
            if tt.get("strategy") in active_strats and tt.get("result") in ("WIN", "LOSS")
        ]
        if recent_window:
            total_recent = len(recent_window)
            for name in active_strats:
                share = sum(1 for tt in recent_window if tt.get("strategy") == name) / max(total_recent, 1)
                soft_cap = ENGINE_ACTIVITY_SOFT_CAP.get(name, 1.0)
                if share > soft_cap:
                    boosted_w[name] *= max(0.35, soft_cap / max(share, 1e-9))
        dd_penalties = {}
        dd_levels = {}
        for name in active_strats:
            dd_penalty, dd_r = _recent_drawdown_penalty(history[name])
            dd_penalties[name] = dd_penalty
            dd_levels[name] = round(dd_r, 2)
            boosted_w[name] *= dd_penalty
        total_r = sum(boosted_w.values())
        final_w = {name: (boosted_w[name] / total_r if total_r > 0 else BASE_CAPITAL_WEIGHTS[name]) for name in active_strats}
        final_w = _apply_engine_weight_caps(final_w, active_strats)
        leader = max(final_w, key=final_w.get)

        # Symbol + engine-streak cooldowns rodam INDEPENDENTE do portfolio
        # gate. Miram cluster de losses (ex: 4 LOSS em XRP em 48h) sem
        # re-enable o gate inteiro.
        sym = t.get("symbol")
        cooldown_reason = None
        if (SYMBOL_COOLDOWN_ENABLED and sym
                and sym in last_symbol_loss_ts):
            bars = _bars_since(last_symbol_loss_ts[sym], t["timestamp"])
            if bars < SYMBOL_COOLDOWN_BARS_AFTER_LOSS:
                cooldown_reason = "symbol_cooldown"
        if (cooldown_reason is None and ENGINE_LOSS_STREAK_ENABLED
                and engine_loss_streak.get(strat, 0) >= ENGINE_LOSS_STREAK_THRESHOLD
                and engine_cooldown_skips.get(strat, 0) < ENGINE_LOSS_STREAK_SKIPS):
            cooldown_reason = "engine_loss_streak"
            engine_cooldown_skips[strat] = engine_cooldown_skips.get(strat, 0) + 1

        if cooldown_reason is not None:
            gate_blocked[cooldown_reason] += 1
            if t["result"] in ("WIN", "LOSS"):
                history[strat].append(_r_multiple(t))
                if t["result"] == "LOSS":
                    if sym:
                        last_symbol_loss_ts[sym] = t["timestamp"]
                    engine_loss_streak[strat] = engine_loss_streak.get(strat, 0) + 1
                else:
                    engine_loss_streak[strat] = 0
                    engine_cooldown_skips[strat] = 0
            continue

        allow_trade, gate_reason, gate_ctx = _portfolio_execution_gate(
            t, strat, final_w, dominant, last_portfolio_ts, last_strategy_ts,
            accepted_history, history,
        )
        if not allow_trade:
            gate_blocked[gate_reason] += 1
            for s, killed in killed_map.items():
                log = kill_log[s]
                if killed and (not log or len(log) % 2 == 0):
                    log.append(t["timestamp"])
                elif not killed and log and len(log) % 2 == 1:
                    log.append(t["timestamp"])
            if t["result"] in ("WIN", "LOSS"):
                history[strat].append(_r_multiple(t))
                if t["result"] == "LOSS":
                    if sym:
                        last_symbol_loss_ts[sym] = t["timestamp"]
                    engine_loss_streak[strat] = engine_loss_streak.get(strat, 0) + 1
                else:
                    engine_loss_streak[strat] = 0
                    engine_cooldown_skips[strat] = 0
            continue

        static_w = BASE_CAPITAL_WEIGHTS.get(strat, 1.0)
        dynamic_w = final_w.get(strat, static_w)
        scale = dynamic_w / static_w if static_w > 0 else 1.0

        out.append({**t,
            "pnl": round(t["pnl"] * scale, 2),
            "pnl_pre_ensemble": t["pnl"],
            "ensemble_w": round(dynamic_w, 3),
            "ensemble_weights": {name: round(final_w[name], 3) for name in active_strats},
            "kill_states": dict(killed_map),
            "regime_at_trade": dominant,
            "portfolio_gate": gate_reason,
            "portfolio_leader": leader,
            "portfolio_leader_w": round(gate_ctx.get("leader_w", final_w.get(leader, 0.0)), 3),
            "portfolio_weight_gap": round(gate_ctx.get("leader_gap", 0.0), 3),
            "portfolio_bars_since_trade": gate_ctx.get("bars_since_portfolio"),
            "portfolio_bars_since_strategy": gate_ctx.get("bars_since_strategy"),
            "decay_scores": {name: round(_decay_score(history[name]), 3) for name in active_strats},
            "drawdown_penalties": {name: round(dd_penalties[name], 3) for name in active_strats},
            "recent_drawdown_r": dd_levels,
        })
        gate_accepted[strat] += 1
        gate_leaders[leader] += 1
        accepted_history.append(strat)
        last_portfolio_ts = t.get("timestamp")
        last_strategy_ts[strat] = t.get("timestamp")

        for s, killed in killed_map.items():
            log = kill_log[s]
            if killed and (not log or len(log) % 2 == 0):
                log.append(t["timestamp"])
            elif not killed and log and len(log) % 2 == 1:
                log.append(t["timestamp"])

        if t["result"] in ("WIN", "LOSS"):
            history[strat].append(_r_multiple(t))
            if t["result"] == "LOSS":
                if sym:
                    last_symbol_loss_ts[sym] = t["timestamp"]
                engine_loss_streak[strat] = engine_loss_streak.get(strat, 0) + 1
            else:
                engine_loss_streak[strat] = 0
                engine_cooldown_skips[strat] = 0

    if out:
        out[-1]["_kill_log"] = kill_log
        out[-1]["_portfolio_gate_stats"] = {
            "accepted_by_strategy": dict(gate_accepted),
            "leader_by_strategy": dict(gate_leaders),
            "blocked": dict(gate_blocked),
        }
    return sorted(out, key=lambda t: t["timestamp"])


def _apply_engine_weight_caps(weight_map, active_strats):
    if not active_strats:
        return {}
    weights = {name: max(0.0, float(weight_map.get(name, 0.0))) for name in active_strats}
    floors = {name: ENGINE_WEIGHT_FLOORS.get(name, 0.0) for name in active_strats}
    caps = {name: ENGINE_WEIGHT_CAPS.get(name, 1.0) for name in active_strats}
    floor_total = sum(floors.values())
    if floor_total >= 1.0:
        return {name: floors[name] / floor_total for name in active_strats}

    total = sum(weights.values())
    if total <= 0:
        weights = {name: 1.0 / len(active_strats) for name in active_strats}
    else:
        weights = {name: weights[name] / total for name in active_strats}

    projected = dict(weights)
    for _ in range(16):
        clamped = {
            name: min(caps[name], max(floors[name], projected[name]))
            for name in active_strats
        }
        locked = {
            name
            for name in active_strats
            if abs(clamped[name] - floors[name]) <= 1e-12
            or abs(clamped[name] - caps[name]) <= 1e-12
        }
        target_mass = 1.0 - sum(clamped[name] for name in locked)
        free = [name for name in active_strats if name not in locked]
        if not free:
            projected = clamped
            break
        seed_total = sum(weights[name] for name in free)
        if seed_total <= 0:
            free_seed = {name: 1.0 / len(free) for name in free}
        else:
            free_seed = {name: weights[name] / seed_total for name in free}
        projected = dict(clamped)
        for name in free:
            projected[name] = target_mass * free_seed[name]
        if all(abs(projected[name] - clamped[name]) <= 1e-12 for name in active_strats):
            break

    final_weights = {
        name: min(caps[name], max(floors[name], projected[name]))
        for name in active_strats
    }
    residual = 1.0 - sum(final_weights.values())
    if abs(residual) > 1e-12:
        if residual > 0:
            receivers = [
                name for name in active_strats
                if final_weights[name] < caps[name] - 1e-12
            ]
            capacity = sum(caps[name] - final_weights[name] for name in receivers)
            if receivers and capacity > 0:
                for name in receivers:
                    room = caps[name] - final_weights[name]
                    final_weights[name] += residual * (room / capacity)
        else:
            donors = [
                name for name in active_strats
                if final_weights[name] > floors[name] + 1e-12
            ]
            removable = sum(final_weights[name] - floors[name] for name in donors)
            if donors and removable > 0:
                for name in donors:
                    slack = final_weights[name] - floors[name]
                    final_weights[name] += residual * (slack / removable)

    total = sum(final_weights.values())
    if total <= 0:
        return {name: 1.0 / len(active_strats) for name in active_strats}
    return {name: final_weights[name] / total for name in active_strats}

def print_ensemble_stats(original, reweighted):
    """Compara métricas antes e depois do ensemble reweighting."""
    def _m(trades):
        c = [t for t in trades if t["result"] in ("WIN","LOSS")]
        if not c: return {}
        pnls = [t["pnl"] for t in c]
        eq, _, mdd, _ = equity_stats(pnls)
        r = calc_ratios(pnls, n_days=SCAN_DAYS)
        return {"n": len(c), "wr": sum(1 for t in c if t["result"]=="WIN")/len(c)*100,
                "roi": r["ret"], "mdd": mdd, "sharpe": r["sharpe"], "final": eq[-1]}

    mo = _m(original); mr = _m(reweighted)
    if not mo or not mr: return

    rows = [("ROI",    f"{mo['roi']:+.2f}%",     f"{mr['roi']:+.2f}%",     f"{mr['roi']-mo['roi']:+.2f}pp"),
            ("MaxDD",  f"{mo['mdd']:.2f}%",      f"{mr['mdd']:.2f}%",      f"{mr['mdd']-mo['mdd']:+.2f}pp"),
            ("Sharpe", str(mo['sharpe'] or '—'),  str(mr['sharpe'] or '—'), ""),
            ("WR",     f"{mo['wr']:.1f}%",        f"{mr['wr']:.1f}%",       f"{mr['wr']-mo['wr']:+.1f}pp"),
            ("$Final", f"${mo['final']:,.0f}",    f"${mr['final']:,.0f}",   f"${mr['final']-mo['final']:+,.0f}")]

    print(f"\n{SEP}\n  ENSEMBLE WEIGHTING — Estático vs Adaptativo\n{SEP}")
    print(f"  Score    : Sortino(R-multiple capped [{R_CAP_MIN},{R_CAP_MAX}], window adaptativo) + instabilidade + decay")
    print(f"  Regime   : boost probabilístico BULL/BEAR/CHOP × proporção real (window={REGIME_BOOST_WINDOW})")
    print(f"  Kill-sw  : Sortino({KILL_SWITCH_WINDOW}) < {KILL_SWITCH_SORTINO} → peso mínimo {ENSEMBLE_MIN_W:.0%}")
    print(f"  Decay    : R-mean declinante 3 sub-janelas consecutivas → score × {DECAY_PENALTY}")
    print(f"  {'─'*76}")
    print(f"  {'Métrica':12s}  {'Estático':>12s}  {'Adaptativo':>12s}  {'Δ':>10s}")
    print(f"  {'─'*52}")
    for row in rows:
        better = ""
        if row[0]=="ROI" and mr['roi']>mo['roi']: better=" ✓"
        elif row[0]=="MaxDD" and mr['mdd']<mo['mdd']: better=" ✓"
        elif row[0]=="$Final" and mr['final']>mo['final']: better=" ✓"
        print(f"  {row[0]:12s}  {row[1]:>12s}  {row[2]:>12s}  {row[3]:>10s}{better}")

    # distribuição de regime nos trades reweighted
    regimes = [t.get("regime_at_trade","?") for t in reweighted if "regime_at_trade" in t]
    if regimes:
        from collections import Counter
        rc = Counter(regimes)
        total_r = len(regimes)
        regime_str = "  ".join(f"{k}:{v/total_r*100:.0f}%" for k,v in sorted(rc.items()))
        print(f"\n  Regimes detectados: {regime_str}")

    # kill-switch events
    kill_log = {}
    for t in reversed(reweighted):
        if "_kill_log" in t: kill_log = t["_kill_log"]; break

    print(f"\n  Kill-switch eventos:")
    any_kill = False
    for strat, events in kill_log.items():
        if events:
            any_kill = True
            pairs = [(events[i], events[i+1] if i+1<len(events) else "ainda pausado")
                     for i in range(0, len(events), 2)]
            for start, end in pairs:
                end_s = str(end)[:16] if end != "ainda pausado" else end
                print(f"    {strat:8s}  pausado {str(start)[:16]}  →  recuperado {end_s}")


def print_portfolio_gate_stats(reweighted):
    gate_stats = {}
    for t in reversed(reweighted):
        gate_stats = t.get("_portfolio_gate_stats") or {}
        if gate_stats:
            break
    if not gate_stats:
        return

    accepted = gate_stats.get("accepted_by_strategy") or {}
    leaders = gate_stats.get("leader_by_strategy") or {}
    blocked = gate_stats.get("blocked") or {}
    total_live = sum(accepted.values())
    if total_live <= 0:
        return

    print(f"\n{SEP}\n  PORTFOLIO EXECUTION GATE\n{SEP}")
    print(f"  Live selection enabled  ·  accepted {total_live} trades")
    for name in OPERATIONAL_ENGINES:
        if name in accepted:
            lead_n = leaders.get(name, 0)
            print(f"  {name:12s}  accepted={accepted[name]:>4d}  leader={lead_n:>4d}")
    if blocked:
        print(f"\n  Blocked:")
        for reason, n in sorted(blocked.items(), key=lambda kv: kv[1], reverse=True)[:8]:
            print(f"    {reason:24s} {n:>5d}")

    # decay events
    decay_events = {"CITADEL": [], "RENAISSANCE": []}
    for t in reweighted:
        if t.get("strategy") == "CITADEL" and t.get("az_decay", 0) > 0.2:
            decay_events["CITADEL"].append((t["timestamp"], round(t["az_decay"],2)))
        if t.get("strategy") == "RENAISSANCE" and t.get("he_decay", 0) > 0.2:
            decay_events["RENAISSANCE"].append((t["timestamp"], round(t["he_decay"],2)))

    print(f"\n  Decay detection (R-mean declinante):")
    any_decay = False
    for strat, evs in decay_events.items():
        if evs:
            any_decay = True
            max_decay = max(e[1] for e in evs)
            print(f"    {strat:8s}  {len(evs)} trades em decay  |  máx decay score: {max_decay:.2f}")
    if not any_decay:
        print(f"    Nenhum — edge estrutural manteve-se estável nas estratégias activas")

# ── STRESS TEST ───────────────────────────────────────────────
def stress_test(pnl_list):
    """
    3 cenários de stress sobre a distribuição de PnL histórica.
    Testa resiliência do sistema a condições que o backtest não captura:

    1. Regime shift   — injecto N janelas de crise (PnL × 0.3)
    2. Slippage shock — custo adicional aleatório por trade
    3. Miss rate      — 15% dos trades não executam (latência/liquidez)
    """
    if len(pnl_list) < 10:
        print("  Stress test: amostra insuficiente."); return

    n = len(pnl_list)
    scenarios = {"Regime Shift": [], "Slippage Shock": [], "Miss Rate (15%)": [],
                 "Regime Flip (20%)": [], "Corr Shock": []}

    for _ in range(STRESS_SIMS):
        # 1. Regime shift (amplitude)
        p = list(pnl_list)
        for _ in range(STRESS_CRISIS_N):
            s = random.randint(0, max(0, n - STRESS_CRISIS_W))
            for i in range(s, min(s + STRESS_CRISIS_W, n)):
                p[i] *= STRESS_CRISIS_MUL
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Regime Shift"].append(eq)

        # 2. Slippage shock
        p = [x - abs(x) * random.uniform(STRESS_SLIP_MIN, STRESS_SLIP_MAX)
             for x in pnl_list]
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Slippage Shock"].append(eq)

        # 3. Miss rate
        p = [x if random.random() > STRESS_MISS_RATE else 0.0 for x in pnl_list]
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Miss Rate (15%)"].append(eq)

        # 4. Regime flip — inverte sinal de 20% dos trades aleatoriamente
        #    simula edge desaparecendo / regime invertendo estruturalmente
        p = [(-x if random.random() < 0.20 else x) for x in pnl_list]
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Regime Flip (20%)"].append(eq)

        # 5. Correlation shock — 30% de probabilidade de todos os trades
        #    correrem juntos (crise: diversificação colapsa)
        if random.random() < 0.30:
            shock_mult = random.uniform(0.50, 0.80)
            p = [x * shock_mult for x in pnl_list]
        else:
            p = list(pnl_list)
        eq = ACCOUNT_SIZE
        for x in p: eq += x
        scenarios["Corr Shock"].append(eq)

    print(f"\n{SEP}\n  STRESS TEST   {STRESS_SIMS}× simulações por cenário\n{SEP}")
    print(f"  {'Cenário':22s}  {'Median $':>10s}  {'p5 $':>10s}  {'% Pos':>7s}  {'RoR':>6s}  {'vs Base':>8s}")
    print(f"  {'─'*72}")

    base_median = sorted(pnl_list)  # referência simples
    base_final  = ACCOUNT_SIZE + sum(pnl_list)

    for name, finals in scenarios.items():
        finals_s = sorted(finals)
        median   = finals_s[STRESS_SIMS // 2]
        p5       = finals_s[int(STRESS_SIMS * 0.05)]
        pct_pos  = sum(1 for f in finals if f > ACCOUNT_SIZE) / STRESS_SIMS * 100
        ror      = sum(1 for f in finals if f < ACCOUNT_SIZE * 0.80) / STRESS_SIMS * 100
        delta    = median - base_final
        icon     = "ok" if pct_pos >= 70 and ror < 5 else "~~" if pct_pos >= 50 else "xx"
        print(f"  {icon} {name:20s}  ${median:>9,.0f}  ${p5:>9,.0f}  {pct_pos:>6.1f}%  {ror:>5.1f}%  ${delta:>+8,.0f}")

    print(f"\n  Base (sem stress)  ${base_final:>9,.0f}  (referência)")
    print(f"\n  Regime Shift    — 3 crises de 20 trades onde PnL × 0.3  (flash crash / estrutura quebrada)")
    print(f"  Slippage Shock  — custo adicional aleatório por trade    (mercado ilíquido)")
    print(f"  Miss Rate (15%) — 15% dos trades não executam            (latência / fills parciais)")
    print(f"  Regime Flip     — 20% dos trades com sinal invertido     (edge reverte estruturalmente)")
    print(f"  Corr Shock      — 30% prob. todos os activos caem juntos (crise de correlação)")

def cross_divergence_multiplier(azoth_trades, hermes_trades):
    """
    Cross-strategy divergence: taxa de conflitos CITADEL×RENAISSANCE como proxy
    de instabilidade de regime. Quando os dois modelos discordam muito,
    o mercado está em transição → reduzir risco global.

    Retorna multiplicador [0.5, 1.0]:
      conflito_rate < 20% → mult = 1.0 (normal)
      conflito_rate > 50% → mult = 0.5 (máx redução)
    """
    if not azoth_trades or not hermes_trades: return 1.0

    by_sym_az = defaultdict(list)
    by_sym_he = defaultdict(list)
    for t in azoth_trades: by_sym_az[t["symbol"]].append(t)
    for t in hermes_trades: by_sym_he[t["symbol"]].append(t)

    conflicts = 0; overlaps = 0
    for sym in set(by_sym_az) & set(by_sym_he):
        for ta in by_sym_az[sym]:
            for th in by_sym_he[sym]:
                dt = abs((ta["timestamp"] - th["timestamp"]).total_seconds() / 900)
                if dt <= CONFIRM_WINDOW:
                    overlaps += 1
                    if ta["direction"] != th["direction"]: conflicts += 1

    if overlaps < 5: return 1.0   # amostra insuficiente
    conflict_rate = conflicts / overlaps
    mult = max(0.5, 1.0 - conflict_rate)
    return round(mult, 3)

def auto_diagnostic(all_trades, n_windows=10):
    """
    Auto-diagnóstico sistémico: analisa Sharpe rolling do portfólio GLOBAL
    em janelas cronológicas. Detecta degradação sistémica que o monitoramento
    por estratégia não vê (ambas a falhar simultaneamente).

    Saídas:
      - health_score [0.0, 1.0]: fracção de janelas com Sharpe > 0
      - flag: SAUDAVEL / ATENCAO / CRITICO
      - trend: MELHORANDO / ESTAVEL / DEGRADANDO
    """
    closed = sorted([t for t in all_trades if t["result"] in ("WIN","LOSS")],
                    key=lambda t: t["timestamp"])
    if len(closed) < n_windows * 5: return None

    chunk = len(closed) // n_windows
    window_sharpes = []
    for i in range(n_windows):
        w = closed[i*chunk:(i+1)*chunk]
        pnls = [t["pnl"] for t in w]
        if len(pnls) < 3: continue
        mean = sum(pnls)/len(pnls)
        std  = _std(pnls)
        window_sharpes.append(mean/std if std else (1.0 if mean > 0 else -1.0))

    if not window_sharpes: return None

    health_score = sum(1 for s in window_sharpes if s > 0) / len(window_sharpes)

    # trend: compara primeira metade vs segunda metade
    mid = len(window_sharpes) // 2
    first_half  = sum(window_sharpes[:mid]) / max(mid, 1)
    second_half = sum(window_sharpes[mid:]) / max(len(window_sharpes)-mid, 1)
    if second_half > first_half + 0.1:   trend = "MELHORANDO"
    elif second_half < first_half - 0.1: trend = "DEGRADANDO"
    else:                                trend = "ESTAVEL"

    if health_score >= 0.80:   flag = "SAUDAVEL"
    elif health_score >= 0.60: flag = "ATENCAO"
    else:                      flag = "CRITICO"

    return {"health_score": round(health_score, 2), "flag": flag, "trend": trend,
            "window_sharpes": [round(s, 2) for s in window_sharpes],
            "n_windows": len(window_sharpes)}

def print_auto_diagnostic(diag, conflict_mult):
    """Display auto-diagnostic results."""
    print(f"\n{SEP}\n  AUTO-DIAGNÓSTICO — Saúde Sistémica\n{SEP}")
    if diag is None:
        print("  Amostra insuficiente para diagnóstico sistémico."); return

    icons = {"SAUDAVEL": "ok", "ATENCAO": "~~", "CRITICO": "xx"}
    icon = icons.get(diag["flag"], "~~")
    print(f"  {icon} Estado global   : {diag['flag']}  (health score {diag['health_score']:.0%})")
    print(f"  {'  ' if diag['trend']=='MELHORANDO' else '  '} Tendência       : {diag['trend']}")
    print(f"     Divergência AZ×HE : mult={conflict_mult:.2f}  {'(regime estável)' if conflict_mult > 0.85 else '(instabilidade detectada — risco reduzido)' if conflict_mult > 0.65 else '(regime muito instável)'}")

    # sparkline de Sharpe por janela
    spark = ""
    for s in diag["window_sharpes"]:
        if   s >  1.0: spark += "█"
        elif s >  0.3: spark += "▓"
        elif s >  0.0: spark += "░"
        else:          spark += "·"
    print(f"     Sharpe por janela  : [{spark}]  ({diag['n_windows']} janelas)")

    if diag["flag"] == "CRITICO":
        print(f"\n  ⚠  SISTEMA DEGRADADO — considerar pausa antes do testnet")
    elif diag["flag"] == "ATENCAO":
        print(f"\n  ~  Atenção — validar com período mais longo antes de aumentar capital")

def robustness_test(pnl_list, n_sim=200):
    """
    Suite de robustez pré-testnet — 3 testes + análise de sensibilidade.

    Testes:
      A. Noise test    — ±5% ruído nos PnLs (simula imprecisão de indicadores)
      B. Block shuffle — baralha blocos de 10 trades (testa dependência de ordem)
      C. Drop 10%      — remove aleatoriamente 10% dos trades (testa estabilidade amostral)

    Sensibilidade:
      D. R-cap: [-2,+4] vs [-3,+5] vs [-4,+6]  (impacto do capping)
      E. MC block: 15 vs 25 vs 40               (impacto da janela de autocorr)

    Interpretação:
      CV (coef. variação) < 15% → sistema robusto
      CV 15–30%            → atenção — sensível a parâmetros
      CV > 30%             → risco de overfitting
    """
    if len(pnl_list) < 20:
        print("  Robustness test: amostra insuficiente."); return

    def _run(pnls):
        if not pnls: return None
        eq = [ACCOUNT_SIZE]
        for p in pnls: eq.append(eq[-1]+p)
        n = len(pnls); mean = sum(pnls)/n
        std  = _std(pnls)
        losses = [p for p in pnls if p < 0]
        down_std = (sum(p**2 for p in losses)/max(len(losses),1))**0.5
        ret = (eq[-1]-ACCOUNT_SIZE)/ACCOUNT_SIZE*100
        pk = ACCOUNT_SIZE; mdd = 0.0
        for e in eq:
            if e>pk: pk=e
            if pk: mdd=max(mdd,(pk-e)/pk*100)
        sortino = (mean/down_std) if down_std else 0.0
        return {"roi": round(ret,2), "mdd": round(mdd,2),
                "sortino": round(sortino,3), "final": round(eq[-1],2)}

    def _stats(vals):
        if not vals: return {}
        m = sum(vals)/len(vals)
        s = _std(vals)
        cv = abs(s/m*100) if m else 0
        return {"mean": round(m,2), "std": round(s,2), "cv": round(cv,1),
                "p5": round(sorted(vals)[int(len(vals)*0.05)],2),
                "p95": round(sorted(vals)[int(len(vals)*0.95)],2)}

    n = len(pnl_list)
    results = {}

    # A. Noise ±5%
    noise_rois = []
    for _ in range(n_sim):
        p = [x * (1 + random.gauss(0, 0.05)) for x in pnl_list]
        r = _run(p)
        if r: noise_rois.append(r["roi"])
    results["Noise ±5%"] = _stats(noise_rois)

    # B. Block shuffle (blocos de 10) — mede MaxDD (sensível à ordem), não ROI (invariante)
    bsize = 10
    blocks = [pnl_list[i:i+bsize] for i in range(0, n, bsize)]
    shuffle_mdds = []
    for _ in range(n_sim):
        shuffled_blocks = blocks[:]
        random.shuffle(shuffled_blocks)
        p = [x for b in shuffled_blocks for x in b]
        r = _run(p)
        if r: shuffle_mdds.append(r["mdd"])
    results["Block Shuffle (MaxDD)"] = _stats(shuffle_mdds)

    # C. Drop 10%
    drop_rois = []
    for _ in range(n_sim):
        p = [x for x in pnl_list if random.random() > 0.10]
        r = _run(p)
        if r: drop_rois.append(r["roi"])
    results["Drop 10%"] = _stats(drop_rois)

    base_roi = _run(pnl_list)["roi"] if pnl_list else 0

    print(f"\n{SEP}\n  ROBUSTNESS TEST   {n_sim}× simulações por teste\n{SEP}")
    print(f"  Base ROI: {base_roi:+.2f}%  |  CV < 15% = robusto  |  CV > 30% = risco overfitting")
    print(f"  {'─'*74}")
    print(f"  {'Teste':20s}  {'Métrica':>8s}  {'Médio':>10s}  {'p5':>8s}  {'p95':>8s}  {'CV%':>6s}  {'Status':>8s}")
    print(f"  {'─'*74}")
    metrics_map = {"Noise ±5%": "roi", "Block Shuffle (MaxDD)": "mdd", "Drop 10%": "roi"}
    labels_map  = {"Noise ±5%": "ROI", "Block Shuffle (MaxDD)": "MaxDD", "Drop 10%": "ROI"}
    for name, st in results.items():
        if not st: continue
        cv = st["cv"]; metric = labels_map.get(name, "ROI")
        # para MaxDD: CV alto é instabilidade de path; para ROI: CV alto é fragilidade
        status = "ROBUSTO" if cv < 15 else "ATENCAO" if cv < 30 else "FRAGIL"
        icon   = "ok" if cv < 15 else "~~" if cv < 30 else "xx"
        sign   = "" if metric == "MaxDD" else "+"
        print(f"  {icon} {name:18s}  {metric:>8s}  {st['mean']:>{9}}  {st['p5']:>{8}}  {st['p95']:>{8}}  {cv:>5.1f}%  {status:>8s}")

    # D. Sensibilidade ROI a parâmetros
    print(f"\n  {'─'*74}")
    print(f"  SENSIBILIDADE DE PARÂMETROS  (impacto no ROI base)")
    print(f"  {'─'*74}")

    # D1. Slippage ×2
    slip_pnls = [x * 0.97 for x in pnl_list]  # extra 3% custo (≈ slip×2)
    r_slip = _run(slip_pnls)
    delta_slip = r_slip["roi"] - base_roi if r_slip else 0
    print(f"  Slippage ×2          ROI {r_slip['roi']:>+.2f}%   Δ {delta_slip:>+.2f}pp")

    # D2. Drop top 5% trades (remove melhores)
    sorted_pnls = sorted(enumerate(pnl_list), key=lambda x: x[1], reverse=True)
    n_drop = max(1, int(n * 0.05))
    drop_idx = set(i for i,_ in sorted_pnls[:n_drop])
    pnl_no_top = [x for i,x in enumerate(pnl_list) if i not in drop_idx]
    r_notop = _run(pnl_no_top)
    delta_notop = r_notop["roi"] - base_roi if r_notop else 0
    print(f"  Sem top 5% trades    ROI {r_notop['roi']:>+.2f}%   Δ {delta_notop:>+.2f}pp  {'ok' if abs(delta_notop) < 20 else '⚠ dependência de outliers'}")

    # D3. Latência simulada: atrasa 2 candles (miss 5% das entradas → usa close pior)
    lat_pnls = [x * 0.98 if random.random() < 0.05 else x for x in pnl_list]
    r_lat = _run(lat_pnls)
    delta_lat = r_lat["roi"] - base_roi if r_lat else 0
    print(f"  Latência 5% fills    ROI {r_lat['roi']:>+.2f}%   Δ {delta_lat:>+.2f}pp")

    print(f"\n  Interpretação: Δ < 10pp = robusto  |  Δ 10-25pp = atenção  |  Δ > 25pp = frágil")

def aggregate_signals(azoth_trades, hermes_trades):
    all_t=sorted(azoth_trades+hermes_trades, key=lambda t: t["timestamp"])
    by_sym=defaultdict(list)
    for t in all_t: by_sym[t["symbol"]].append(t)
    confirmed=[]; conflicts=0; confirmations=0
    for sym, ts in by_sym.items():
        used=set()
        for i,t1 in enumerate(ts):
            if i in used: continue
            matched=False
            for j,t2 in enumerate(ts):
                if j<=i or j in used: continue
                if t1["strategy"]==t2["strategy"]: continue
                dt=abs((t1["timestamp"]-t2["timestamp"]).total_seconds()/900)
                if dt>CONFIRM_WINDOW: continue
                if t1["direction"]==t2["direction"]:
                    t1_adj={**t1,"confirmed":True,"conf_partner":t2["strategy"],"pnl":round(t1["pnl"]*CONFIRM_SIZE_MULT,2)}
                    t2_adj={**t2,"confirmed":True,"conf_partner":t1["strategy"],"pnl":round(t2["pnl"]*CONFIRM_SIZE_MULT,2)}
                    confirmed.append(t1_adj); confirmed.append(t2_adj)
                    used.add(i); used.add(j); matched=True; confirmations+=1; break
                else:
                    if CONFLICT_ACTION=="skip":
                        used.add(i); used.add(j); matched=True; conflicts+=1; break
                    t1_adj={**t1,"confirmed":False,"conflict":True,"pnl":round(t1["pnl"]*0.5,2)}
                    confirmed.append(t1_adj); used.add(i); used.add(j); matched=True; conflicts+=1; break
            if not matched and i not in used:
                confirmed.append({**t1,"confirmed":False})
    conflict_mult = cross_divergence_multiplier(azoth_trades, hermes_trades)
    log.info(f"  Aggregator: {confirmations} confirmacoes  {conflicts} conflitos  {len(confirmed)} trades finais  div_mult={conflict_mult:.2f}")
    result = sorted(confirmed, key=lambda t: t["timestamp"])
    if result: result[0] = {**result[0], "_conflict_mult": conflict_mult}
    return result

def metrics_by_strategy(all_trades):
    by_s=defaultdict(list)
    for t in all_trades:
        s=t.get("strategy","CITADEL"); by_s[s].append(t)
        if t.get("confirmed"): by_s["CONFIRMED"].append(t)
    print(f"\n{SEP}\n  PERFORMANCE POR ESTRATEGIA\n{SEP}")
    print(f"  {'Estrategia':12s}  {'N':>4s}  {'WR':>6s}  {'Sharpe':>7s}  {'MaxDD':>6s}  {'ROI':>7s}  {'PnL':>12s}")
    print(f"  {'─'*72}")
    ordered = [name for name in OPERATIONAL_ENGINES if by_s.get(name)]
    ordered += [name for name in by_s.keys() if name not in OPERATIONAL_ENGINES and name != "CONFIRMED"]
    if by_s.get("CONFIRMED"):
        ordered.append("CONFIRMED")
    for name in ordered:
        ts = by_s[name]
        display = "CONFIRMADOS" if name == "CONFIRMED" else name
        closed=[t for t in ts if t["result"] in ("WIN","LOSS")]
        if not closed: print(f"  {display:12s}  sem trades"); continue
        w=sum(1 for t in closed if t["result"]=="WIN"); wr=w/len(closed)*100
        pnl_s=[t["pnl"] for t in closed]
        r=calc_ratios(pnl_s,n_days=SCAN_DAYS); _,_,mdd,_=equity_stats(pnl_s)
        print(f"  {display:12s}  {len(closed):>4d}  {wr:>5.1f}%  {str(r['sharpe'] or '—'):>7s}  {mdd:>5.1f}%  {r['ret']:>+6.1f}%  ${sum(pnl_s):>+10,.0f}")

def metrics_confirmations(all_trades):
    conf=[t for t in all_trades if t.get("confirmed") and t["result"] in ("WIN","LOSS")]
    norm=[t for t in all_trades if not t.get("confirmed") and t["result"] in ("WIN","LOSS")]
    if not conf: print(f"\n  Confirmacoes: 0 trades"); return
    cw=sum(1 for t in conf if t["result"]=="WIN")
    nw=sum(1 for t in norm if t["result"]=="WIN")
    print(f"\n  CONFIRMACOES CITADEL+RENAISSANCE")
    print(f"  Confirmados: {len(conf)} trades  WR {cw/len(conf)*100:.1f}%  PnL ${sum(t['pnl'] for t in conf):+,.0f}")
    if norm: print(f"  Individuais: {len(norm)} trades  WR {nw/len(norm)*100:.1f}%")
    by_pat=defaultdict(list)
    for t in conf:
        if t["strategy"]=="RENAISSANCE" and "pattern" in t: by_pat[t["pattern"]].append(t)
    if by_pat:
        print(f"  Confirmacoes por padrao RENAISSANCE:")
        for pat,ts in sorted(by_pat.items()):
            w2=sum(1 for t in ts if t["result"]=="WIN")
            print(f"    {pat:12s}  n={len(ts)}  WR={w2/len(ts)*100:.0f}%  PnL=${sum(t['pnl'] for t in ts):+,.0f}")

def print_hermes_patterns(all_trades):
    ht=[t for t in all_trades if t.get("strategy")=="RENAISSANCE" and t["result"] in ("WIN","LOSS")]
    if not ht: print(f"\n  RENAISSANCE: sem trades gerados"); return
    by_pat=defaultdict(list)
    for t in ht: by_pat[t.get("pattern","?")].append(t)
    print(f"\n  RENAISSANCE — PADROES HARMONICOS")
    print(f"  {'Padrao':12s}  {'N':>3s}  {'WR':>6s}  {'RR_med':>6s}  {'PnL':>10s}")
    print(f"  {'─'*50}")
    for pat in ["Gartley","Bat","Butterfly","Crab"]:
        ts=by_pat.get(pat,[])
        if not ts: print(f"  {pat:12s}  —"); continue
        w=sum(1 for t in ts if t["result"]=="WIN"); wr=w/len(ts)*100
        rr_m=sum(t["rr"] for t in ts)/len(ts); pnl=sum(t["pnl"] for t in ts)
        print(f"  {'ok' if wr>=50 and pnl>0 else '~' if pnl>0 else 'xx'} {pat:12s}  {len(ts):>3d}  {wr:>5.1f}%  {rr_m:>5.2f}x  ${pnl:>+8,.0f}")

def print_veredito_ms(all_trades, eq, mdd_pct, mc, wf, ratios, wf_regime=None):
    closed=[t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr=sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    exp=sum(t["pnl"] for t in closed)/max(len(closed),1)
    n_strats=len({t.get("strategy") for t in closed if t.get("strategy")})
    bear_stab=(wf_regime or {}).get("BEAR",{}).get("stable_pct")
    wf_ok=bear_stab>=60 if bear_stab else False
    wf_label=f"BEAR {bear_stab:.0f}%" if bear_stab else "global"
    checks=[
        ("Trades suficientes (>=50)",len(closed)>=50),
        ("Win Rate >= 50%",wr>=50),
        ("Expectativa positiva",exp>0),
        ("MaxDD < 20%",mdd_pct<20),
        ("Sharpe >= 1.0",ratios["sharpe"] and ratios["sharpe"]>=1.0),
        ("Monte Carlo >= 70% positivo",mc and mc["pct_pos"]>=70),
        (f"Walk-Forward estavel ({wf_label})",wf_ok),
        ("Diversificacao real (>=2 estrategias)",n_strats>=2),
    ]
    passou=sum(1 for _,v in checks if v)
    print(f"\n{SEP}\n  VEREDITO\n{SEP}")
    for nome,ok in checks: print(f"  {'✓' if ok else '✗'}  {nome}")
    verdict=("EDGE CONFIRMADO" if passou>=7 else
             "PROMISSOR" if passou>=5 else
             "FRAGIL")
    print(f"\n  {passou}/8  ·  {verdict}\n{SEP}\n")
    log.info(f"MS Veredito: {passou}/8  ROI={ratios['ret']:.2f}%  WR={wr:.1f}%  MaxDD={mdd_pct:.1f}%")

def export_ms_json(all_trades, eq, mc, ratios, mdd_pct=None):
    closed=[t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr=sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    confirmed_t=[t for t in closed if t.get("confirmed")]
    by_strategy={}
    for name in sorted({t.get("strategy") for t in closed if t.get("strategy")}):
        ts=[t for t in closed if t.get("strategy")==name]
        by_strategy[name]={
            "n":len(ts),
            "wr":round(sum(1 for t in ts if t["result"]=="WIN")/max(len(ts),1)*100,1),
            "pnl":round(sum(t["pnl"] for t in ts),2),
        }
    gate_stats = {}
    for t in reversed(all_trades):
        gate_stats = t.get("_portfolio_gate_stats") or {}
        if gate_stats:
            break
    payload={
        "version":"multistrategy-1.0","run_id":RUN_ID,
        "timestamp":datetime.now().isoformat(),
        "config":{"base_weights":BASE_CAPITAL_WEIGHTS,
                  "max_open_ms":MAX_OPEN_POSITIONS_MS,
                  "confirm_window":CONFIRM_WINDOW,
                  "confirm_size_mult":CONFIRM_SIZE_MULT,
                  "portfolio_execution_enabled": PORTFOLIO_EXECUTION_ENABLED,
                  "portfolio_min_weight": PORTFOLIO_MIN_WEIGHT,
                  "portfolio_challenger_ratio": PORTFOLIO_CHALLENGER_RATIO,
                  "portfolio_challenger_max_gap": PORTFOLIO_CHALLENGER_MAX_GAP,
                  "portfolio_global_cooldown_bars": PORTFOLIO_GLOBAL_COOLDOWN_BARS,
                  "portfolio_strategy_cooldown_bars": PORTFOLIO_STRATEGY_COOLDOWN_BARS},
        "summary":{"total":len(closed),
                   "confirmed_n":len(confirmed_t),"win_rate":round(wr,2),
                   "total_pnl":round(sum(t["pnl"] for t in closed),2),
                   "final_equity":round(eq[-1],2),
                   **{k:ratios.get(k) for k in ("sharpe","sortino","calmar","ret")}},
        "by_strategy":by_strategy,
        "portfolio_gate": gate_stats,
        "monte_carlo":{k:v for k,v in (mc or {}).items() if k not in ("paths","finals","dds")},
        "trades":[{k:(str(v) if k=="timestamp" else v) for k,v in t.items()} for t in all_trades],
        "equity":eq,
    }
    fname=str(MS_RUN_DIR/"reports"/f"multistrategy_{INTERVAL}_v1.json")
    atomic_write(Path(fname), json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print(f"  JSON -> {fname}")
    # Persist into canonical run index so MILLENNIUM shows up alongside
    # directional engines in data/index.json.
    try:
        from core.run_manager import append_to_index
        index_summary = {
            "engine":       "MILLENNIUM",
            "run_id":       RUN_ID,
            "interval":     INTERVAL,
            "period_days":  SCAN_DAYS,
            "basket":       globals().get("BASKET_NAME", "default"),
            "n_symbols":    len(globals().get("SYMBOLS", [])),
            "n_candles":    globals().get("N_CANDLES"),
            "n_trades":     len(closed),
            "win_rate":     round(wr, 2),
            "pnl":          round(sum(t["pnl"] for t in closed), 2),
            "roi_pct":      ratios.get("ret"),
            "sharpe":       ratios.get("sharpe"),
            "sortino":      ratios.get("sortino"),
            "max_dd_pct":   mdd_pct,
        }
        index_config = {
            "INTERVAL":     INTERVAL,
            "SCAN_DAYS":    SCAN_DAYS,
            "N_CANDLES":    globals().get("N_CANDLES"),
            "BASE_WEIGHTS": BASE_CAPITAL_WEIGHTS,
            "BASKET_EFFECTIVE": globals().get("BASKET_NAME", "default"),
        }
        append_to_index(MS_RUN_DIR, index_summary, index_config)
    except Exception as _e:
        print(f"  index: {_e}")
    # Auto-persist to DB
    try:
        from core.db import save_run
        save_run("multi", fname)
        print(f"  DB: run persistido")
    except Exception as _e:
        print(f"  DB: {_e}")

def _ask_periodo():
    global SCAN_DAYS, N_CANDLES, HTF_N_CANDLES_MAP
    from engines import citadel as _bt
    v=safe_input(f"\n  Periodo em dias [{SCAN_DAYS}] > ").strip()
    if v.isdigit() and 7<=int(v)<=1500:
        d=int(v)
        _bt.SCAN_DAYS=d; _bt.N_CANDLES=d*24*4
        _bt.HTF_N_CANDLES_MAP={"1h":d*24+200,"4h":d*6+100,"1d":d+100}
        SCAN_DAYS=d; N_CANDLES=d*24*4
        HTF_N_CANDLES_MAP={"1h":d*24+200,"4h":d*6+100,"1d":d+100}
        return d
    return SCAN_DAYS

def _ask_config():
    """Pergunta conta, leverage e risk. Actualiza globals do backtest e do módulo."""
    global ACCOUNT_SIZE, LEVERAGE, BASE_RISK, MAX_RISK, CONVEX_ALPHA
    from engines import citadel as _bt

    # Conta
    v = safe_input(f"  Tamanho da conta USD [{int(_bt.ACCOUNT_SIZE):,}] > ").strip().replace(",","").replace("$","")
    if v.replace(".","").isdigit() and float(v) >= 100:
        _bt.ACCOUNT_SIZE = float(v)

    # Leverage
    print(f"\n  Alavancagem  (1× = sem leverage  |  3× recomendado  |  max seguro ~5×)")
    print(f"  MaxDD escala linearmente: {_bt.ACCOUNT_SIZE:,.0f} × leverage × 4.2% ≈ MaxDD estimado")
    lv = safe_input(f"  Leverage [1] > ").strip()
    leverage = 1.0
    if lv.replace(".","").isdigit():
        leverage = max(1.0, min(float(lv), 20.0))
    _bt.LEVERAGE = leverage

    # Risk (opcional — avançado)
    print(f"\n  Risk por trade  (BASE={_bt.BASE_RISK*100:.1f}%  MAX={_bt.MAX_RISK*100:.1f}%)  [Enter = manter]")
    br = safe_input(f"  BASE_RISK % [{_bt.BASE_RISK*100:.1f}] > ").strip()
    mr = safe_input(f"  MAX_RISK  % [{_bt.MAX_RISK*100:.1f}] > ").strip()
    if br.replace(".","").isdigit(): _bt.BASE_RISK = max(0.001, min(float(br)/100, 0.05))
    if mr.replace(".","").isdigit(): _bt.MAX_RISK  = max(_bt.BASE_RISK, min(float(mr)/100, 0.10))

    # Convex sizing
    print(f"\n  Convex sizing  (quebra proporcionalidade DD/ROI com leverage)")
    print(f"  0.0 = desligado  |  0.5 = suave  |  1.0 = linear  |  2.0 = agressivo")
    cv = safe_input(f"  CONVEX_ALPHA [{_bt.CONVEX_ALPHA}] > ").strip()
    if cv.replace(".","").isdigit(): _bt.CONVEX_ALPHA = max(0.0, min(float(cv), 3.0))

    # Sync module-level globals for _load_dados, _metricas_e_export, etc.
    ACCOUNT_SIZE = _bt.ACCOUNT_SIZE; LEVERAGE = _bt.LEVERAGE
    BASE_RISK = _bt.BASE_RISK; MAX_RISK = _bt.MAX_RISK
    CONVEX_ALPHA = _bt.CONVEX_ALPHA

    return _bt.ACCOUNT_SIZE, _bt.LEVERAGE, _bt.BASE_RISK, _bt.MAX_RISK, _bt.CONVEX_ALPHA

def _ask_plots():
    return safe_input("  Gerar graficos? [s/N] > ").strip().lower() in ("s","sim","y")

def _load_dados(generate_plots):
    global GENERATE_PLOTS
    GENERATE_PLOTS=generate_plots
    print(f"\n{SEP}\n  DADOS   {INTERVAL}   {N_CANDLES:,} candles\n{SEP}")
    _fetch_syms=list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms: _fetch_syms.insert(0,MACRO_SYMBOL)
    # Use local INTERVAL/N_CANDLES (updated by _ask_periodo) instead of
    # falling back to config.params defaults. Without this, changing the
    # scan period in the menu had no effect on fetched data.
    all_dfs=fetch_all(_fetch_syms, interval=INTERVAL, n_candles=N_CANDLES)
    for sym,df in all_dfs.items(): validate(df,sym)
    if not all_dfs: print("  Sem dados."); sys.exit(1)
    htf_stack_by_sym={}
    if MTF_ENABLED:
        for tf in HTF_STACK:
            nc=HTF_N_CANDLES_MAP.get(tf,300)
            print(f"\n{SEP}\n  HTF   {tf}   {nc:,} candles\n{SEP}")
            tf_dfs=fetch_all(list(all_dfs.keys()),interval=tf,n_candles=nc)
            for sym,df_h in tf_dfs.items():
                df_h=prepare_htf(df_h,htf_interval=tf)
                htf_stack_by_sym.setdefault(sym,{})[tf]=df_h
    print(f"\n{SEP}\n  PRE-PROCESSAMENTO\n{SEP}")
    macro_series=detect_macro(all_dfs)
    if macro_series is not None:
        bull_n=(macro_series=="BULL").sum(); bear_n=(macro_series=="BEAR").sum(); chop_n=(macro_series=="CHOP").sum()
        total=bull_n+bear_n+chop_n
        print(f"  Macro ({MACRO_SYMBOL})    BULL {bull_n}c ({bull_n/total*100:.0f}%)   BEAR {bear_n}c ({bear_n/total*100:.0f}%)   CHOP {chop_n}c ({chop_n/total*100:.0f}%)")
    corr=build_corr_matrix(all_dfs)
    return all_dfs, htf_stack_by_sym, macro_series, corr

def _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr):
    print(f"\n{SEP}\n  SCAN CITADEL (trend-following fractal)\n{SEP}")
    azoth_all=[]; azoth_vetos=defaultdict(int)
    for sym,df in all_dfs.items():
        if sym not in SYMBOLS: continue
        trades,vetos=azoth_scan(df,sym,macro_series,corr,htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
        for t in trades: t["strategy"]="CITADEL"; t.setdefault("confirmed",False)
        azoth_all.extend(trades)
        for k,v in vetos.items(): azoth_vetos[k]+=v
        closed=[t for t in trades if t["result"] in ("WIN","LOSS")]
        w=sum(1 for t in closed if t["result"]=="WIN")
        chop_n=sum(1 for t in trades if t.get("chop_trade"))
        print(f"  CITADEL  {sym:12s}  n={len(trades):>4d}  WR={w/max(len(closed),1)*100:>5.1f}%  PnL=${sum(t['pnl'] for t in closed):>+9,.0f}" + (f"  [MR:{chop_n}]" if chop_n else ""))
    return azoth_all, azoth_vetos

def _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr):
    print(f"\n{SEP}\n  SCAN RENAISSANCE (harmonicos XABCD — Gartley/Bat/Butterfly/Crab)\n{SEP}")
    hermes_all=[]; hermes_vetos=defaultdict(int)
    for sym,df in all_dfs.items():
        if sym not in SYMBOLS: continue
        trades,vetos=scan_hermes(df,sym,macro_series,corr,htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
        hermes_all.extend(trades)
        for k,v in vetos.items(): hermes_vetos[k]+=v
        closed=[t for t in trades if t["result"] in ("WIN","LOSS")]
        w=sum(1 for t in closed if t["result"]=="WIN")
        by_pat=defaultdict(int)
        for t in trades: by_pat[t.get("pattern","?")]+=1
        pat_str="  ".join(f"{k}:{v}" for k,v in sorted(by_pat.items()) if v)
        print(f"  RENAISSANCE {sym:12s}  n={len(trades):>4d}  WR={w/max(len(closed),1)*100:>5.1f}%  PnL=${sum(t['pnl'] for t in closed):>+9,.0f}" + (f"  [{pat_str}]" if pat_str else ""))
    print(f"\n{SEP}\n  FILTROS RENAISSANCE\n{SEP}")
    tv=sum(hermes_vetos.values())
    for k,n in sorted(hermes_vetos.items(),key=lambda x:-x[1])[:12]:
        bar="░"*min(int(n/max(tv,1)*30),30)
        print(f"  {k:40s}  {n:>6d}  {n/max(tv,1)*100:>4.1f}%  {bar}")
    return hermes_all, hermes_vetos

def _metricas_e_export(all_trades, label="CITADEL + RENAISSANCE"):
    portfolio_trades = operational_core_reweight(all_trades) if label == "CORE OPERATIONAL" else all_trades
    closed=[t for t in portfolio_trades if t["result"] in ("WIN","LOSS")]
    if not closed: print("  Sem trades fechados."); return
    pnl_s=[t["pnl"] for t in closed]; eq,mdd,mdd_pct,ms=equity_stats(pnl_s)
    ratios=calc_ratios(pnl_s,n_days=SCAN_DAYS)
    print(f"\n{SEP}\n  METRICAS DE PORTFOLIO ({label})\n{SEP}")
    print(f"  Sharpe   {str(ratios['sharpe'] or '—'):>7s}     Sortino  {str(ratios['sortino'] or '—'):>7s}     Calmar  {str(ratios['calmar'] or '—'):>7s}")
    print(f"  Sharpe diário {str(ratios.get('sharpe_daily') or '—'):>5s}  (benchmark-comparable, ann. 252d)")
    print(f"  ROI      {ratios['ret']:>6.2f}%     MaxDD    {mdd_pct:>6.2f}%     Streak  {ms:>5d} perdas")
    print(f"  Capital  ${ACCOUNT_SIZE:>8,.0f}  ->  ${eq[-1]:>10,.0f}   (+${eq[-1]-ACCOUNT_SIZE:,.0f})")
    if label!="CITADEL":
        metrics_by_strategy(portfolio_trades); metrics_confirmations(portfolio_trades); print_hermes_patterns(portfolio_trades)
    mc=monte_carlo(pnl_s)
    print(f"\n{SEP}\n  MONTE CARLO   {MC_N}x   bloco={MC_BLOCK}\n{SEP}")
    if mc:
        rlb="SEGURO" if mc["ror"]<1 else "ATENCAO" if mc["ror"]<5 else "RISCO"
        print(f"  Positivos {mc['pct_pos']:>5.1f}%   p5 ${mc['p5']:>9,.0f}   Mediana ${mc['median']:>9,.0f}   p95 ${mc['p95']:>9,.0f}")
        print(f"  RoR       {mc['ror']:>5.1f}%   [{rlb}]   DD medio {mc['avg_dd']:.1f}%   pior {mc['worst_dd']:.1f}%")
    wf=walk_forward(portfolio_trades)
    print(f"\n{SEP}\n  WALK-FORWARD GLOBAL   {len(wf)} janelas\n{SEP}")
    if wf:
        ok=sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15); pct=ok/len(wf)*100
        print(f"  {ok}/{len(wf)} estaveis ({pct:.0f}%)   {'ESTAVEL' if pct>=60 else 'INSTAVEL'}")
        for w in wf[-10:]:
            d=w["test"]["wr"]-w["train"]["wr"]
            print(f"  {w['w']:>3d}  treino {w['train']['wr']:>5.1f}%  fora {w['test']['wr']:>5.1f}%  D {d:>+5.1f}%  {'ok' if abs(d)<=15 else 'xx'}")
    wf_regime=walk_forward_by_regime(portfolio_trades)
    print(f"\n{SEP}\n  WALK-FORWARD POR REGIME\n{SEP}")
    for regime,d in wf_regime.items():
        if d["stable_pct"] is None: print(f"  {regime:5s}  n={d['n']:>3d}  insuficiente"); continue
        print(f"  {regime:5s}  n={d['n']:>3d}  estaveis: {d['stable_pct']:.0f}%  {'ESTAVEL' if d['stable_pct']>=60 else 'INSTAVEL'}")
    yy=year_by_year_analysis(all_trades)
    if len([yr for yr,d in yy.items() if d])>=2:
        print(f"\n{SEP}\n  PERFORMANCE ANO A ANO\n{SEP}")
        for yr in sorted(yy.keys()):
            d=yy[yr]
            if not d: continue
            yr_trades=[t for t in closed if t.get("timestamp") and t["timestamp"].year==yr]
            az_n=sum(1 for t in yr_trades if t.get("strategy")=="CITADEL")
            he_n=sum(1 for t in yr_trades if t.get("strategy")=="RENAISSANCE")
            print(f"  {yr}  {d['n']:>4d}  {d['wr']:>5.1f}%  {d['roi']:>+6.1f}%  ${d['pnl']:>+8,.0f}  {d['mdd']:>5.1f}%  AZ:{az_n}  HE:{he_n}")

    # ── ROBUSTNESS TEST ───────────────────────────────────────
    robustness_test(pnl_s)

    # ── AUTO-DIAGNÓSTICO ─────────────────────────────────────
    diag = auto_diagnostic(portfolio_trades)
    conflict_mult = portfolio_trades[0].get("_conflict_mult", 1.0) if portfolio_trades else 1.0
    print_auto_diagnostic(diag, conflict_mult)

    # ── ENSEMBLE WEIGHTING ────────────────────────────────────
    if label not in ("CITADEL", "RENAISSANCE"):
        if label == "CORE OPERATIONAL":
            print_ensemble_stats(all_trades, portfolio_trades)
            print_portfolio_gate_stats(portfolio_trades)
        else:
            rew = operational_core_reweight(all_trades)
            print_ensemble_stats(all_trades, rew)

    # ── STRESS TEST ───────────────────────────────────────────
    stress_test(pnl_s)

    print_veredito_ms(portfolio_trades,eq,mdd_pct,mc,wf,ratios,wf_regime)
    export_ms_json(portfolio_trades,eq,mc,ratios,mdd_pct=mdd_pct)

    # ── CHARTS ────────────────────────────────────────────────
    if GENERATE_PLOTS:
        try:
            import matplotlib
            matplotlib.rcParams["text.usetex"] = False
            import matplotlib.pyplot as plt

            # equity curve
            fig, ax = plt.subplots(figsize=(14,5))
            ax.plot(eq, linewidth=1.5, color="#00c8a0")
            ax.fill_between(range(len(eq)), eq, eq[0], alpha=0.15, color="#00c8a0")
            ax.axhline(eq[0], color="#888", linewidth=0.8, linestyle="--")
            ax.set_title(f"CITADEL × RENAISSANCE — Equity Curve ({label})", fontsize=13)
            ax.set_xlabel("Trade #"); ax.set_ylabel("Capital $")
            ax.grid(True, alpha=0.2)
            fname_eq = str(MS_RUN_DIR / "charts" / f"equity_{INTERVAL}.png")
            fig.savefig(fname_eq, dpi=130, bbox_inches="tight"); plt.close(fig)
            print(f"  Chart → {fname_eq}")

            # monte carlo
            if mc:
                plot_montecarlo(mc, eq, run_dir=MS_RUN_DIR)
                print(f"  Chart → {MS_RUN_DIR / 'charts' / f'montecarlo_{INTERVAL}.png'}")
        except Exception as _e:
            log.warning(f"Charts error: {_e}")

    print(f"\n{SEP}\n  output  ·  {MS_RUN_DIR}/\n{SEP}\n")

def _resultados_por_simbolo(all_trades, show_he=True):
    print(f"\n{SEP}\n  RESULTADOS POR SIMBOLO\n{SEP}")
    hdr="  {:12s}  {:>4s}  {:>4s}  {:>4s}  {:>6s}  {:>12s}".format("ATIVO","N","AZ","HE","WR","PnL") if show_he else \
        "  {:12s}  {:>4s}  {:>6s}  {:>12s}".format("ATIVO","N","WR","PnL")
    print(hdr)
    by_sym=defaultdict(list)
    for t in all_trades: by_sym[t["symbol"]].append(t)
    for sym in sorted(by_sym):
        ts=by_sym[sym]; c=[t for t in ts if t["result"] in ("WIN","LOSS")]
        if not c: continue
        w=sum(1 for t in c if t["result"]=="WIN"); wr=w/len(c)*100
        if show_he:
            az=sum(1 for t in c if t.get("strategy")=="CITADEL")
            he=sum(1 for t in c if t.get("strategy")=="RENAISSANCE")
            print(f"  {sym:12s}  {len(c):>4d}  {az:>4d}  {he:>4d}  {wr:>5.1f}%  ${sum(t['pnl'] for t in c):>+10,.0f}")
        else:
            print(f"  {sym:12s}  {len(c):>4d}  {wr:>5.1f}%  ${sum(t['pnl'] for t in c):>+10,.0f}")

def _collect_operational_trades(all_dfs=None, htf_stack_by_sym=None, macro_series=None, corr=None, engine_contexts=None):
    # BRIDGEWATER removida 2026-04-17: ver nota em OPERATIONAL_ENGINES.
    # Até a re-habilitação, op=1 roda só CITADEL + RENAISSANCE + JUMP.
    engine_trades = {}
    if engine_contexts is None:
        shared_ctx = {
            "all_dfs": all_dfs,
            "htf_stack_by_sym": htf_stack_by_sym or {},
            "macro_series": macro_series,
            "corr": corr or {},
        }
        engine_contexts = {name: shared_ctx for name in OPERATIONAL_ENGINES}

    citadel_ctx = engine_contexts["CITADEL"]
    azoth_all, _ = _scan_azoth(
        citadel_ctx["all_dfs"],
        citadel_ctx.get("htf_stack_by_sym", {}),
        citadel_ctx.get("macro_series"),
        citadel_ctx.get("corr", {}),
    )
    engine_trades["CITADEL"] = azoth_all

    renaissance_ctx = engine_contexts["RENAISSANCE"]
    hermes_all, _ = _scan_hermes_all(
        renaissance_ctx["all_dfs"],
        renaissance_ctx.get("htf_stack_by_sym", {}),
        renaissance_ctx.get("macro_series"),
        renaissance_ctx.get("corr", {}),
    )
    engine_trades["RENAISSANCE"] = hermes_all

    from engines.jump import scan_mercurio
    mercurio_all = []
    jump_ctx = engine_contexts["JUMP"]
    for sym, df in jump_ctx["all_dfs"].items():
        trades, _ = scan_mercurio(df.copy(), sym, jump_ctx.get("macro_series"), jump_ctx.get("corr", {}))
        mercurio_all.extend(trades)
    engine_trades["JUMP"] = mercurio_all

    all_trades = []
    for eng, trades in engine_trades.items():
        for t in trades:
            tt = t.copy()
            tt.setdefault("strategy", eng)
            all_trades.append(tt)
    all_trades.sort(key=lambda t: t["timestamp"])
    return engine_trades, all_trades

def _menu():
    W = 50
    print(f"\n  {'─'*W}")
    print(f"  MILLENNIUM  ·  Multistrategy Backtest")
    print(f"  {'─'*W}")
    while True:
        print()
        print(f"  [1]  CORE OPERATIONAL (CITADEL + RENAISSANCE + JUMP)")
        print(f"  [2]  CITADEL")
        print(f"  [3]  RENAISSANCE")
        print(f"  [4]  NEWTON")
        print(f"  [5]  MERCURIO")
        print(f"  [6]  THOTH")
        print(f"  [7]  ALL")
        print(f"  [8]  TWO SIGMA (ML)")
        print(f"  [0]  Sair")
        print()
        op = safe_input("  > ").strip()
        if op == "0": sys.exit(0)
        if op in ("1","2","3","4","5","6","7","8"): return op
        print("  opcao invalida")

if __name__ == "__main__":
    setup_multistrategy()
    op = _menu()
    LABELS = {
        "1":"CORE OPERATIONAL", "2":"CITADEL", "3":"RENAISSANCE",
        "4":"DE SHAW", "5":"JUMP", "6":"BRIDGEWATER",
        "7":"ALL", "8":"TWO SIGMA (ML)",
    }
    days = _ask_periodo()
    acct, lev, base_r, max_r, convex = _ask_config()
    plots = _ask_plots()

    print(f"\n{SEP}")
    print(f"  {LABELS[op]}  ·  {days}d  ·  {len(SYMBOLS)} ativos  ·  {INTERVAL}")
    print(f"  ${acct:,.0f}  ·  {lev:.0f}x  ·  risk {base_r*100:.1f}–{max_r*100:.1f}%  ·  convex {convex:.1f}")
    if plots: print(f"  charts on")
    print(f"  {MS_RUN_DIR}/")
    print(SEP)
    safe_input("\n  enter para iniciar... ")
    log.info(f"AURUM op={LABELS[op]} dias={days} — {RUN_ID}")
    all_dfs, htf_stack_by_sym, macro_series, corr = _load_dados(plots)

    if op == "2":
        azoth_all, _ = _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr)
        if not azoth_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(azoth_all, show_he=False)
        _metricas_e_export(azoth_all, label="CITADEL")

    elif op == "3":
        hermes_all, _ = _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr)
        if not hermes_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(hermes_all, show_he=False)
        _metricas_e_export(hermes_all, label="RENAISSANCE")

    elif op == "4":
        from engines.deshaw import find_cointegrated_pairs, scan_pair
        print(f"\n{SEP}\n  COINTEGRATION ANALYSIS\n{SEP}")
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        newton_all.sort(key=lambda t: t["timestamp"])
        if not newton_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(newton_all, show_he=False)
        _metricas_e_export(newton_all, label="DE SHAW")

    elif op == "5":
        from engines.jump import scan_mercurio
        mercurio_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_mercurio(df.copy(), sym, macro_series, corr)
            mercurio_all.extend(trades)
        mercurio_all.sort(key=lambda t: t["timestamp"])
        if not mercurio_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(mercurio_all, show_he=False)
        _metricas_e_export(mercurio_all, label="JUMP")

    elif op == "6":
        from engines.bridgewater import scan_thoth, collect_sentiment
        print(f"\n{SEP}\n  SENTIMENT DATA\n{SEP}")
        sentiment_data = collect_sentiment(
            list(all_dfs.keys()),
            end_time_ms=_derive_end_time_ms(all_dfs),
            window_days=SCAN_DAYS,
        )
        thoth_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_thoth(df.copy(), sym, macro_series, corr,
                                   sentiment_data=sentiment_data)
            thoth_all.extend(trades)
        thoth_all.sort(key=lambda t: t["timestamp"])
        if not thoth_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(thoth_all, show_he=False)
        _metricas_e_export(thoth_all, label="BRIDGEWATER")

    elif op == "7":
        # ALL engines
        engine_trades = {}

        azoth_all, _ = _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["CITADEL"] = azoth_all

        hermes_all, _ = _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["RENAISSANCE"] = hermes_all

        from engines.deshaw import find_cointegrated_pairs, scan_pair
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        engine_trades["DE SHAW"] = newton_all

        from engines.jump import scan_mercurio
        mercurio_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_mercurio(df.copy(), sym, macro_series, corr)
            mercurio_all.extend(trades)
        engine_trades["JUMP"] = mercurio_all

        from engines.bridgewater import scan_thoth, collect_sentiment
        sentiment_data = collect_sentiment(
            list(all_dfs.keys()),
            end_time_ms=_derive_end_time_ms(all_dfs),
            window_days=SCAN_DAYS,
        )
        thoth_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_thoth(df.copy(), sym, macro_series, corr,
                                   sentiment_data=sentiment_data)
            thoth_all.extend(trades)
        engine_trades["BRIDGEWATER"] = thoth_all

        # merge all
        all_trades = []
        for eng, trades in engine_trades.items():
            for t in trades:
                t = t.copy()
                if "strategy" not in t: t["strategy"] = eng
                all_trades.append(t)
        all_trades.sort(key=lambda t: t["timestamp"])

        if not all_trades: print("  Sem trades."); sys.exit(1)

        # summary per engine
        print(f"\n{SEP}\n  RESULTADOS POR ENGINE\n{SEP}")
        for eng in ["CITADEL", "RENAISSANCE", "DE SHAW", "JUMP", "BRIDGEWATER"]:
            ts = [t for t in all_trades if t.get("strategy") == eng and t["result"] in ("WIN","LOSS")]
            if not ts: print(f"  {eng:12s}  sem trades"); continue
            w = sum(1 for t in ts if t["result"] == "WIN")
            pnl = sum(t["pnl"] for t in ts)
            print(f"  {eng:12s}  n={len(ts):>4d}  WR={w/len(ts)*100:>5.1f}%  ${pnl:>+10,.0f}")

        _metricas_e_export(all_trades, label="ALL ENGINES")

    elif op == "8":
        # TWO SIGMA (ML ensemble)
        engine_trades = {}

        azoth_all, _ = _scan_azoth(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["CITADEL"] = azoth_all

        hermes_all, _ = _scan_hermes_all(all_dfs, htf_stack_by_sym, macro_series, corr)
        engine_trades["RENAISSANCE"] = hermes_all

        from engines.deshaw import find_cointegrated_pairs, scan_pair
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        engine_trades["DE SHAW"] = newton_all

        from engines.jump import scan_mercurio
        mercurio_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_mercurio(df.copy(), sym, macro_series, corr)
            mercurio_all.extend(trades)
        engine_trades["JUMP"] = mercurio_all

        from engines.bridgewater import scan_thoth, collect_sentiment
        sentiment_data = collect_sentiment(
            list(all_dfs.keys()),
            end_time_ms=_derive_end_time_ms(all_dfs),
            window_days=SCAN_DAYS,
        )
        thoth_all = []
        for sym, df in all_dfs.items():
            trades, _ = scan_thoth(df.copy(), sym, macro_series, corr,
                                   sentiment_data=sentiment_data)
            thoth_all.extend(trades)
        engine_trades["BRIDGEWATER"] = thoth_all

        from engines.twosigma import run_prometeu
        all_trades = run_prometeu(engine_trades)

        if not all_trades: print("  Sem trades."); sys.exit(1)
        _metricas_e_export(all_trades, label="TWO SIGMA ML")

    else:
        # op == "1" — operational multi-strategy core
        engine_contexts = _load_operational_contexts()
        _, all_trades = _collect_operational_trades(engine_contexts=engine_contexts)
        if not all_trades: print("  Sem trades."); sys.exit(1)
        print(f"\n{SEP}\n  RESULTADOS POR ENGINE\n{SEP}")
        for eng in OPERATIONAL_ENGINES:
            ts = [t for t in all_trades if t.get("strategy") == eng and t["result"] in ("WIN","LOSS")]
            if not ts: print(f"  {eng:12s}  sem trades"); continue
            w = sum(1 for t in ts if t["result"] == "WIN")
            pnl = sum(t["pnl"] for t in ts)
            print(f"  {eng:12s}  n={len(ts):>4d}  WR={w/len(ts)*100:>5.1f}%  ${pnl:>+10,.0f}")
        _metricas_e_export(all_trades, label="CORE OPERATIONAL")
