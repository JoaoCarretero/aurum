"""AURUM — Signal generation: direction, scoring, levels, trade labeling."""
import numpy as np
import pandas as pd
from config.params import *

def decide_direction(row, macro_bias: str) -> tuple[str | None, str, float]:
    struct, strength = row["trend_struct"], row["struct_strength"]

    if strength < REGIME_MIN_STRENGTH:
        return None, f"regime({strength:.2f})", 0.0

    s21  = row.get("slope21",  0.0) or 0.0
    s200 = row.get("slope200", 0.0) or 0.0
    if abs(s21) < CHOP_S21 and abs(s200) < CHOP_S200 and strength <= 0.70:
        return None, f"chop(s21={s21:.3f})", 0.0

    vol_r = row.get("vol_regime", "NORMAL")
    if VOL_RISK_SCALE.get(vol_r, 1.0) == 0.0:
        return None, "vol_extreme", 0.0

    fractal_score = 1.0
    if MTF_ENABLED and HTF_STACK:
        n_htf = len(HTF_STACK)
        aligned = 0
        macro_from_htf = "CHOP"
        for i in range(1, n_htf + 1):
            htf_s   = str(row.get(f"htf{i}_struct",    "NEUTRAL"))
            htf_str = float(row.get(f"htf{i}_strength", 0.0) or 0.0)
            htf_mac = str(row.get(f"htf{i}_macro",     "CHOP"))
            if htf_str >= 0.35 and htf_s == struct:
                aligned += 1
            if i == n_htf:
                macro_from_htf = htf_mac
        if aligned == 0:
            return None, "fractal_misalign", 0.0
        fractal_score = round(aligned / n_htf, 2)
        macro_bias    = macro_from_htf
        if macro_bias == "BEAR" and struct == "UP":
            if fractal_score < 1.0:
                return None, "macro_bear_veto_long", 0.0
        if macro_bias == "BULL" and struct == "DOWN":
            if fractal_score < 1.0:
                return None, "macro_bull_veto_short", 0.0
    else:
        if not MTF_ENABLED:
            if macro_bias == "BEAR" and struct == "UP":
                return None, "macro_bear_veto_long", 0.0
            if macro_bias == "BULL" and struct == "DOWN":
                return None, "macro_bull_veto_short", 0.0

    if macro_bias == "BULL" and struct == "UP":
        if MTF_ENABLED and fractal_score < 0.67:
            return None, "bull_fractal_fraco", 0.0
        dist = float(row.get("dist_ema21", 0.0) or 0.0)
        if dist < BULL_LONG_MIN_PULLBACK_ATR:
            return None, "bull_no_pullback", 0.0

    if struct == "UP":   return "BULLISH", "ok", fractal_score
    if struct == "DOWN": return "BEARISH", "ok", fractal_score
    return None, f"neutral({struct})", 0.0

def score_omega(row, direction: str) -> tuple[float, dict]:
    bull = direction == "BULLISH"
    cn   = int(row["casc_up"] if bull else row["casc_down"])
    c_s  = cn / 4.0 if cn >= CASCADE_MIN else 0.0
    fl   = float(row["omega_flow_bull" if bull else "omega_flow_bear"]) if not pd.isna(row["omega_flow_bull"]) else 0.0
    mo   = float(row["omega_mom_bull"  if bull else "omega_mom_bear"])
    pu   = float(row["omega_pullback"])
    st   = float(row["omega_struct_up" if bull else "omega_struct_down"])
    comps = {"struct": round(st,4), "flow": round(fl,4),
              "cascade": round(c_s,4), "momentum": round(mo,4), "pullback": round(pu,4)}
    if c_s == 0.0: return 0.0, comps
    ws  = (st*OMEGA_WEIGHTS["struct"] + fl*OMEGA_WEIGHTS["flow"]   +
           c_s*OMEGA_WEIGHTS["cascade"] + mo*OMEGA_WEIGHTS["momentum"] +
           pu*OMEGA_WEIGHTS["pullback"])
    penalty = 0.70 + 0.30 * min(comps.values())
    return round(ws * penalty, 4), comps

def score_chop(row) -> tuple[str | None, float, dict]:
    """
    Detecta oportunidades de mean reversion em regime CHOP.

    Condições de entrada:
      LONG:  close < bb_lower  E  RSI < CHOP_RSI_LONG
             (oversold em mercado lateral — espera retorno à média)
      SHORT: close > bb_upper  E  RSI > CHOP_RSI_SHORT
             (overbought em mercado lateral — espera retorno à média)

    Retorna (direction, score_qualidade, info_dict) ou (None, 0, {})
    """
    close    = float(row.get("close",    0) or 0)
    bb_upper = float(row.get("bb_upper", 0) or 0)
    bb_lower = float(row.get("bb_lower", 0) or 0)
    bb_mid   = float(row.get("bb_mid",   0) or 0)
    bb_width = float(row.get("bb_width", 0) or 0)
    rsi      = float(row.get("rsi",     50) or 50)
    s21      = float(row.get("slope21",  0) or 0)
    vol_r    = str(row.get("vol_regime", "NORMAL"))

    if bb_upper == 0 or bb_lower == 0 or bb_mid == 0:
        return None, 0.0, {}

    if vol_r == "EXTREME":
        return None, 0.0, {}

    if abs(s21) > CHOP_MAX_SLOPE_ABS:
        return None, 0.0, {}

    if bb_width < 0.005:
        return None, 0.0, {}

    direction = None
    rsi_extreme = 0.0

    if close < bb_lower and rsi < CHOP_RSI_LONG:
        direction   = "BULLISH"
        rsi_extreme = (CHOP_RSI_LONG - rsi) / CHOP_RSI_LONG

    elif close > bb_upper and rsi > CHOP_RSI_SHORT:
        direction   = "BEARISH"
        rsi_extreme = (rsi - CHOP_RSI_SHORT) / (100 - CHOP_RSI_SHORT)

    if direction is None:
        return None, 0.0, {}

    if direction == "BULLISH":
        band_dist = (bb_lower - close) / bb_lower if bb_lower > 0 else 0.0
    else:
        band_dist = (close - bb_upper) / bb_upper if bb_upper > 0 else 0.0

    band_dist = min(band_dist, 0.05) / 0.05

    score = round(0.60 * rsi_extreme + 0.40 * band_dist, 4)

    info = {
        "bb_upper":   round(bb_upper, 6),
        "bb_lower":   round(bb_lower, 6),
        "bb_mid":     round(bb_mid,   6),
        "bb_width":   round(bb_width, 4),
        "rsi":        round(rsi,      2),
        "rsi_extreme": round(rsi_extreme, 4),
        "band_dist":  round(band_dist, 4),
    }
    return direction, score, info

def calc_levels_chop(df, idx, direction, bb_mid):
    """
    Níveis para trade CHOP: alvo = BB mid (não extensão de tendência).
    Stop: ATR × 1.0 (mais apertado que trend porque é range bounded).
    """
    if idx >= len(df)-1: return None
    atr   = df["atr"].iloc[idx]
    if pd.isna(atr) or atr == 0: return None
    raw   = df["open"].iloc[idx+1]
    slip  = SLIPPAGE + SPREAD

    if direction == "BULLISH":
        entry  = raw * (1 + slip)
        stop   = entry - atr * 1.0
        stop   = min(stop, entry * (1 - MIN_STOP_PCT))
        target = bb_mid
    else:
        entry  = raw * (1 - slip)
        stop   = entry + atr * 1.0
        stop   = max(stop, entry * (1 + MIN_STOP_PCT))
        target = bb_mid

    if not entry: return None
    rr = abs(target-entry) / abs(entry-stop) if abs(entry-stop) > 0 else 0
    if rr < 1.0: return None
    if direction == "BULLISH" and (stop >= entry or target <= entry): return None
    if direction == "BEARISH" and (stop <= entry or target >= entry): return None
    return round(entry,8), round(stop,4), round(target,4), round(rr,3)

def calc_levels(df, idx, direction):
    if idx >= len(df)-1: return None
    atr = df["atr"].iloc[idx]
    if pd.isna(atr) or atr == 0: return None
    raw  = df["open"].iloc[idx+1]
    slip = SLIPPAGE + SPREAD
    if direction == "BULLISH":
        entry  = raw * (1 + slip)
        rl     = df["swing_low"].iloc[max(0,idx-30):idx]; rl = rl[rl>0]
        stop   = max(rl.iloc[-1]-atr*0.3, entry-STOP_ATR_M*atr) if len(rl) else entry-STOP_ATR_M*atr
        stop   = min(stop, entry * (1 - MIN_STOP_PCT))
        target = entry + abs(entry-stop) * TARGET_RR
    else:
        entry  = raw * (1 - slip)
        rh     = df["swing_high"].iloc[max(0,idx-30):idx]; rh = rh[rh>0]
        stop   = min(rh.iloc[-1]+atr*0.3, entry+STOP_ATR_M*atr) if len(rh) else entry+STOP_ATR_M*atr
        stop   = max(stop, entry * (1 + MIN_STOP_PCT))
        target = entry - abs(stop-entry) * TARGET_RR
    if not entry: return None
    rr = abs(target-entry) / abs(entry-stop)
    if rr < RR_MIN: return None
    if direction == "BULLISH" and (stop >= entry or target <= entry): return None
    if direction == "BEARISH" and (stop <= entry or target >= entry): return None
    return round(entry,8), round(stop,4), round(target,4), round(rr,3)

def label_trade(df, entry_idx, direction, entry, stop, target):
    """
    Trailing stop inteligente:
      Fase 1: preço move 1.0× risco → stop para breakeven
      Fase 2: preço move 1.5× risco → trailing a 0.5× risco
    """
    end       = min(entry_idx + MAX_HOLD, len(df))
    cur_stop  = stop
    risk      = abs(entry - stop)
    be_done   = False
    trail_done = False

    for j in range(entry_idx, end):
        h, l = df["high"].iloc[j], df["low"].iloc[j]
        if direction == "BULLISH":
            if not be_done and h >= entry + risk:
                cur_stop = entry; be_done = True
            if be_done and not trail_done and h >= entry + 1.5*risk:
                cur_stop = max(cur_stop, h - 0.5*risk); trail_done = True
            elif trail_done:
                cur_stop = max(cur_stop, h - 0.5*risk)
            if l <= cur_stop:
                result = "WIN" if cur_stop >= entry else "LOSS"
                return result, j-entry_idx, cur_stop
            if h >= target:
                return "WIN", j-entry_idx, target
        else:
            if not be_done and l <= entry - risk:
                cur_stop = entry; be_done = True
            if be_done and not trail_done and l <= entry - 1.5*risk:
                cur_stop = min(cur_stop, l + 0.5*risk); trail_done = True
            elif trail_done:
                cur_stop = min(cur_stop, l + 0.5*risk)
            if h >= cur_stop:
                result = "WIN" if cur_stop <= entry else "LOSS"
                return result, j-entry_idx, cur_stop
            if l <= target:
                return "WIN", j-entry_idx, target
    return "OPEN", MAX_HOLD, df["close"].iloc[min(end-1,len(df)-1)]

def label_trade_chop(df, entry_idx, direction, entry, stop, target):
    """
    Label para CHOP trades: sem trailing stop (mercado lateral não tende).
    Saída simples: stop fixo ou target fixo (BB mid).
    Max hold mais curto: CHOP trades devem resolver rápido.
    """
    chop_max_hold = min(MAX_HOLD // 2, 24)
    end = min(entry_idx + chop_max_hold, len(df))

    for j in range(entry_idx, end):
        h, l = df["high"].iloc[j], df["low"].iloc[j]
        if direction == "BULLISH":
            if l <= stop:   return "LOSS", j-entry_idx, stop
            if h >= target: return "WIN",  j-entry_idx, target
        else:
            if h >= stop:   return "LOSS", j-entry_idx, stop
            if l <= target: return "WIN",  j-entry_idx, target
    return "OPEN", chop_max_hold, df["close"].iloc[min(end-1,len(df)-1)]

