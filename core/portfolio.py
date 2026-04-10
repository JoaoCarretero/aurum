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
    if score >= 0.65: return 0.60
    if score >= 0.59: return 0.55
    return 0.50

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
    """
    [U1 v3.6] position_size() agora incorpora Ω como multiplicador direto.

    Pipeline de multiplicadores (ordem de aplicação):
      1. Kelly base (score → WR estimada)
      2. _omega_risk_mult(score) — [U1 NOVO] proporcional ao edge real
      3. _global_risk_mult()     — alinhamento macro/direção
      4. VOL_RISK_SCALE          — regime de volatilidade
      5. RISK_SCALE_BY_REGIME    — regime macro
      6. dd_scale                — drawdown circuit breaker
      7. CHOP_SIZE_MULT          — [U3] trades de mean reversion = 40%
      8. Convex sizing           — (account/peak)^alpha: freia em DD, acelera em HWM
    """
    dist = abs(entry - stop)
    if not dist: return 0.0

    wr      = _wr(score)
    kelly   = max(0.0, (wr*TARGET_RR - (1-wr)) / TARGET_RR) * KELLY_FRAC
    t       = max(0.0, (score - SCORE_THRESHOLD) / (1.0 - SCORE_THRESHOLD))
    risk    = BASE_RISK + t * (min(kelly, MAX_RISK) - BASE_RISK)

    risk   *= _omega_risk_mult(score)
    risk   *= _global_risk_mult(macro_bias, direction)
    risk   *= VOL_RISK_SCALE.get(vol_regime, 1.0)
    risk   *= RISK_SCALE_BY_REGIME.get(macro_bias, 1.0)
    risk   *= dd_scale

    if is_chop_trade:
        risk *= CHOP_SIZE_MULT

    # 8. Convex sizing — quebra a proporcionalidade DD/ROI com leverage
    if CONVEX_ALPHA > 0.0 and peak_equity and peak_equity > 0:
        convex_mult = (account / peak_equity) ** CONVEX_ALPHA
        risk *= max(0.1, min(convex_mult, 1.5))   # clamp [10%, 150%]

    risk = max(BASE_RISK*0.25, min(MAX_RISK * 1.25, risk))
    return round(account * risk / dist, 4)

