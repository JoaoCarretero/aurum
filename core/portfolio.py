"""AURUM — Portfolio management: macro detection, correlation, position sizing."""
import logging
import numpy as np
import pandas as pd
from config.params import *
from core.indicators import indicators

log = logging.getLogger("CITADEL")

def detect_macro(all_dfs: dict) -> pd.Series:
    btc = all_dfs.get(MACRO_SYMBOL)
    if btc is None:
        log.warning("BTC não disponível para macro regime — usando CHOP")
        return None
    btc = indicators(btc)
    bias = pd.Series("CHOP", index=btc.index)
    bias[btc["slope200"] > MACRO_SLOPE_BULL]  = "BULL"
    bias[btc["slope200"] < MACRO_SLOPE_BEAR]  = "BEAR"
    return bias

def build_corr_matrix(all_dfs: dict) -> dict:
    ret = {}
    for sym, df in all_dfs.items():
        ret[sym] = df["close"].pct_change().dropna()
    corr = {}
    syms = list(ret.keys())
    for i, s1 in enumerate(syms):
        for s2 in syms[i+1:]:
            common = ret[s1].align(ret[s2], join="inner")
            n = min(CORR_LOOKBACK, len(common[0]))
            if n < 30: c = 0.0
            else:
                a, b = common[0].iloc[-n:].values, common[1].iloc[-n:].values
                c    = float(np.corrcoef(a, b)[0, 1])
            corr[(s1, s2)] = corr[(s2, s1)] = round(c, 3)
    return corr

def portfolio_allows(symbol: str, open_positions: list,
                     corr: dict) -> tuple[bool, str, float]:
    """
    [U2 v3.6] Retorna (ok, motivo, size_mult).

    Comportamento:
      corr > CORR_THRESHOLD (0.80):  bloqueia totalmente
      CORR_SOFT ≤ corr ≤ CORR_THRESHOLD: size × CORR_SOFT_MULT (0.40)
      corr < CORR_SOFT:               sem penalidade
      MAX_OPEN_POSITIONS excedido:    bloqueia

    Antes (v3.5): qualquer corr > 0.80 bloqueava o trade.
    Agora (v3.6): corr 0.75-0.80 passa com 40% do size normal.
    Motivação: trades correlacionados em regime forte geralmente
    vencem juntos — bloquear era deixar dinheiro na mesa.
    """
    if not open_positions:
        return True, "ok", 1.0

    size_mult = 1.0
    for sym in open_positions:
        c = corr.get((symbol, sym), 0.0)

        if c > CORR_THRESHOLD:
            return False, f"corr_alta({sym}:{c:.2f})", 0.0

        if c > CORR_SOFT_THRESHOLD:
            size_mult = min(size_mult, CORR_SOFT_MULT)

    if len(open_positions) >= MAX_OPEN_POSITIONS:
        return False, f"max_posicoes({MAX_OPEN_POSITIONS})", 0.0

    motivo = "ok" if size_mult == 1.0 else f"corr_soft(×{size_mult:.2f})"
    return True, motivo, size_mult

def check_aggregate_notional(new_notional: float, open_pos: list,
                             account: float, leverage: float) -> tuple[bool, str]:
    """[L6 fix] Reject entries that would push combined notional over account × leverage.

    The per-trade position sizer is safe in isolation, but nothing before this
    check ever summed notionals across currently open positions. Several trades
    firing in the same bar with tight stops and a high Omega score could allocate
    combined leverage that a real exchange margin system would refuse.

    ``open_pos`` is expected as a list of ``(exit_idx, symbol, size, entry)``
    tuples — the 4-tuple shape introduced alongside this check in engines/backtest.py.
    """
    open_notional = sum(sz * en for _, _, sz, en in open_pos)
    cap = account * leverage
    if open_notional + new_notional > cap:
        return False, f"agg_cap({open_notional + new_notional:.0f}>{cap:.0f})"
    return True, "ok"

def _omega_risk_mult(score: float) -> float:
    """
    [U1 v3.6] Multiplicador de risco baseado no score Ω.

    Motivação: dados 1500 dias mostram:
      Faixa 0.53-0.59: WR 58%  →  edge moderado   → size reduzido
      Faixa 0.59-0.65: WR 78%  →  edge forte       → size aumentado
    O sistema v3.5 tratava ambos com o mesmo risco — ineficiente.
    Agora o risco escala com a qualidade do sinal, não apenas com Kelly.
    """
    for omega_min, mult in OMEGA_RISK_TABLE:
        if score >= omega_min:
            return mult
    return 0.50

def _wr(score: float) -> float:
    """Estimated win rate as continuous function of omega score.
    Maps [SCORE_THRESHOLD, 1.0] → [0.50, 0.65] linearly.
    Eliminates cliff effects from the old step function."""
    return max(0.50, min(0.65, 0.50 + (score - SCORE_THRESHOLD) *
               (0.15 / (1.0 - SCORE_THRESHOLD))))

def _global_risk_mult(macro_bias: str, direction: str) -> float:
    if (macro_bias == "BEAR" and direction == "BEARISH") or \
       (macro_bias == "BULL" and direction == "BULLISH"):
        return 1.25
    if macro_bias == "CHOP":
        return 0.75
    return 0.90

def position_size(account, entry, stop, score,
                  macro_bias="CHOP", direction="BEARISH",
                  vol_regime="NORMAL", dd_scale=1.0,
                  is_chop_trade=False, peak_equity=None):
    """Simplified position sizing: Kelly base + 2 multiplicadores.

    v3.7 — reduced from 8 multiplicadores to 3 after ablation test showed
    the stacked factors created a 7,700x range that was impossible to
    reason about. New range: ~75x (controllable, debuggable).

    Pipeline:
      1. Kelly base (continuous _wr from score)
      2. regime_dd = RISK_SCALE_BY_REGIME × dd_scale  [0.2, 1.0]
      3. convex = (account/peak)^alpha                 [0.1, 1.5]
    """
    dist = abs(entry - stop)
    if not dist: return 0.0

    wr      = _wr(score)
    kelly   = max(0.0, (wr*TARGET_RR - (1-wr)) / TARGET_RR) * KELLY_FRAC
    t       = max(0.0, (score - SCORE_THRESHOLD) / (1.0 - SCORE_THRESHOLD))
    risk    = BASE_RISK + t * (min(kelly, MAX_RISK) - BASE_RISK)

    # Factor 1: regime × drawdown (combined)
    regime_dd = RISK_SCALE_BY_REGIME.get(macro_bias, 1.0) * dd_scale
    risk *= max(0.2, min(regime_dd, 1.0))

    # Factor 2: convex sizing (equity curve shape)
    if CONVEX_ALPHA > 0.0 and peak_equity and peak_equity > 0:
        convex = (account / peak_equity) ** CONVEX_ALPHA
        risk *= max(0.1, min(convex, 1.5))

    risk = max(BASE_RISK*0.25, min(MAX_RISK, risk))
    return round(account * risk / dist, 4)

