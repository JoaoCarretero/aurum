import os, sys, time, math, json, random, requests, logging
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
from collections import defaultdict
from datetime import datetime
from pathlib import Path

RUN_DATE = datetime.now().strftime("%Y-%m-%d")
RUN_TIME = datetime.now().strftime("%H%M")
RUN_ID   = f"{RUN_DATE}_{RUN_TIME}"
RUN_DIR  = Path(f"data/{RUN_DATE}")
(RUN_DIR / "charts").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(RUN_DIR / "logs" / "run.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("AZOTH")

_tl = logging.getLogger("AZOTH.trades")
_th = logging.FileHandler(RUN_DIR / "logs" / "trades.log", encoding="utf-8")
_th.setFormatter(logging.Formatter("%(message)s"))
_tl.addHandler(_th); _tl.setLevel(logging.DEBUG); _tl.propagate = False

_vl = logging.getLogger("AZOTH.val")
_vh = logging.FileHandler(RUN_DIR / "logs" / "validation.log", encoding="utf-8")
_vh.setFormatter(logging.Formatter("%(message)s"))
_vl.addHandler(_vh); _vl.setLevel(logging.DEBUG); _vl.propagate = False

SYMBOLS = [
    "BNBUSDT", "INJUSDT", "LINKUSDT", "RENDERUSDT", "NEARUSDT",
    "SUIUSDT",  "ARBUSDT", "SANDUSDT", "XRPUSDT",   "FETUSDT", "OPUSDT",
]

ENTRY_TF   = "15m"
INTERVAL   = ENTRY_TF
SCAN_DAYS  = 90

N_CANDLES  = SCAN_DAYS * 24 * 4

HTF_STACK    = ["1h", "4h", "1d"]
MTF_ENABLED  = True

HTF_N_CANDLES_MAP = {
    "1h":  SCAN_DAYS * 24 + 300,
    "4h":  SCAN_DAYS *  6 + 200,
    "1d":  SCAN_DAYS      + 200,
}

ACCOUNT_SIZE = 10_000.0
BASE_RISK    = 0.005
MAX_RISK     = 0.015
LEVERAGE     = 1.0      # multiplicador de alavancagem (aplicado ao PnL)
CONVEX_ALPHA = 0.0      # convex sizing: 0=desligado  0.5=suave  1.0=linear  2.0=agressivo
KELLY_FRAC   = 0.5
SLIPPAGE     = 0.0002
SPREAD       = 0.0001
COMMISSION   = 0.0004
FUNDING_PER_8H = 0.0001
MAX_HOLD     = 48

EMA_SPANS    = [9, 21, 50, 100, 200]
RSI_PERIOD   = 14
ATR_PERIOD   = 14
W_NORM       = 120
PIVOT_N      = 5
MIN_SWINGS   = 3
TAKER_WINDOW = 20

RSI_BULL_MIN, RSI_BULL_MAX = 42, 68
RSI_BEAR_MIN, RSI_BEAR_MAX = 28, 60
PULLBACK_ATR_MAX            = 1.5
CASCADE_MIN                 = 1

REGIME_MIN_STRENGTH = 0.25
SCORE_THRESHOLD     = 0.53
OMEGA_MIN_COMPONENT = 0.15
OMEGA_WEIGHTS       = {"struct": 0.25, "flow": 0.25,
                        "cascade": 0.20, "momentum": 0.15, "pullback": 0.15}
STOP_ATR_M          = 1.8
TARGET_RR           = 2.0
RR_MIN              = 1.5

import math as _math

_TF_MINUTES: dict[str, int] = {
    "1m":1, "3m":3, "5m":5, "15m":15, "30m":30,
    "1h":60, "2h":120, "4h":240, "6h":360,
    "8h":480, "12h":720, "1d":1440,
}

def _tf_params(interval: str) -> dict:
    m   = _TF_MINUTES.get(interval, 240)
    r   = m / 240
    sr  = _math.sqrt(r)
    return {
        "min_stop_pct":  max(0.002, round(0.008 * sr, 4)),
        "slope_n":       max(3, min(80, round(1200 / m))),
        "chop_s21":      round(0.030 * sr, 5),
        "chop_s200":     round(0.010 * sr, 5),
        "pivot_n":       max(5, min(30, round(360 / m))),
        "max_hold":      max(24, min(200, round(11520 / m))),
    }

_TFP            = _tf_params("4h")
MIN_STOP_PCT    = _TFP["min_stop_pct"]
SLOPE_N         = _TFP["slope_n"]
CHOP_S21        = _TFP["chop_s21"]
CHOP_S200       = _TFP["chop_s200"]
PIVOT_N         = _TFP["pivot_n"]
MAX_HOLD        = _TFP["max_hold"]

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

MAX_OPEN_POSITIONS   = 3
CORR_THRESHOLD       = 0.80
CORR_SOFT_THRESHOLD  = 0.75
CORR_SOFT_MULT       = 0.40
CORR_LOOKBACK        = 120

MACRO_SYMBOL         = "BTCUSDT"
MACRO_SLOPE_BULL     =  0.05
MACRO_SLOPE_BEAR     = -0.05

MC_N, MC_BLOCK = 1000, 25   # block 25: melhor captura autocorrelação crypto
WF_TRAIN, WF_TEST = 20, 10

CHOP_BB_PERIOD    = 20
CHOP_BB_STD       = 2.0
CHOP_RSI_LONG     = 32
CHOP_RSI_SHORT    = 68
CHOP_RR           = 1.5
CHOP_SIZE_MULT    = 0.40
CHOP_MAX_SLOPE_ABS = 0.025

OMEGA_RISK_TABLE: list[tuple[float, float]] = [
    (0.65, 1.30),
    (0.59, 1.10),
    (0.55, 0.85),
    (0.53, 0.70),
    (0.00, 0.50),
]

def fetch(symbol: str, interval: str | None = None,
          n_candles: int | None = None,
          futures: bool = False) -> pd.DataFrame | None:
    _iv  = interval  or INTERVAL
    _nc  = n_candles or N_CANDLES
    # futures klines têm preço perp (mais próximo do que vai ser executado)
    base = "https://fapi.binance.com/fapi/v1" if futures else "https://api.binance.com/api/v3"
    url, frames, end_time = f"{base}/klines", [], None
    remaining = _nc
    while remaining > 0:
        limit  = min(1000, remaining)
        params = {"symbol": symbol, "interval": _iv, "limit": limit}
        if end_time:
            params["endTime"] = end_time
        try:
            r = requests.get(url, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(2.0); continue
            if r.status_code != 200: break
            data = r.json()
            if not data: break
            frames.insert(0, data)
            end_time   = data[0][0] - 1
            remaining -= len(data)
            time.sleep(0.08)
        except Exception as e:
            log.warning(f"[{symbol}] fetch error: {e}"); break
    if not frames: return None
    flat = [c for f in frames for c in f]
    df   = pd.DataFrame(flat, columns=[
        "time","open","high","low","close","vol",
        "ct","qvol","tr","tbb","tbq","ign"])
    df   = df[["time","open","high","low","close","vol","tbb"]].copy()
    for c in ["open","high","low","close","vol","tbb"]:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)

def fetch_all(symbols: list, interval: str | None = None,
              n_candles: int | None = None,
              label: str = "", workers: int = 6,
              futures: bool = False) -> dict:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _iv = interval or INTERVAL
    _nc = n_candles or N_CANDLES
    results: dict = {}
    futures_map: dict = {}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for sym in symbols:
            futures_map[ex.submit(fetch, sym, _iv, _nc, futures)] = sym
        done = 0
        for fut in as_completed(futures_map):
            sym = futures_map[fut]
            done += 1
            try:
                df = fut.result()
            except Exception as e:
                df = None
                log.warning(f"[{sym}] {e}")
            if df is not None and len(df) >= 300:
                results[sym] = df
                span = (f"{df['time'].iloc[0].strftime('%Y-%m-%d')} → "
                        f"{df['time'].iloc[-1].strftime('%Y-%m-%d')}")
                lbl = f"  [{sym:12s}]  ✓  {len(df)}c   {span}"
            else:
                lbl = f"  [{sym:12s}]  ✗ sem dados"
            print(lbl, flush=True)
    return results

def validate(df: pd.DataFrame, symbol: str) -> bool:
    issues = []
    if len(df) < 300: issues.append(f"SHORT_SERIES:{len(df)}")
    if df.duplicated("time").sum(): issues.append("DUPLICATES")
    tk = df["tbb"] / df["vol"].replace(0, np.nan)
    if ((tk > 1.01) | (tk < -0.01)).sum(): issues.append("TAKER_INVALID")
    m = tk.mean()
    if m > 0.70 or m < 0.30: issues.append(f"TAKER_BIASED:{m:.3f}")
    ok = not issues
    _vl.info(f"{symbol:12s}  {'OK' if ok else 'WARN'}  n={len(df)}"
             + (f"  {';'.join(issues)}" if issues else ""))
    return ok

def indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for s in EMA_SPANS:
        df[f"ema{s}"] = df["close"].ewm(span=s, adjust=False).mean()
    d  = df["close"].diff()
    ag = d.clip(lower=0).ewm(com=RSI_PERIOD-1, adjust=False).mean()
    al = (-d).clip(lower=0).ewm(com=RSI_PERIOD-1, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + ag / al.replace(0, np.nan))
    h, l, c   = df["high"], df["low"], df["close"]
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    df["atr"]       = tr.ewm(span=ATR_PERIOD, adjust=False).mean()
    df["vol_ma"]    = df["vol"].ewm(span=20, adjust=False).mean()
    tk              = (df["tbb"] / df["vol"].replace(0, np.nan)).clip(0, 1)
    df["taker_ratio"] = tk
    df["taker_ma"]    = tk.ewm(span=TAKER_WINDOW, adjust=False).mean()
    df["slope21"]     = df["ema21"].pct_change(SLOPE_N) * 100
    df["slope200"]    = df["ema200"].pct_change(SLOPE_N * 2) * 100

    atr_pct = df["atr"] / df["close"].replace(0, np.nan) * 100
    df["atr_pct"] = atr_pct
    pct_rank = atr_pct.rolling(VOL_WINDOW, min_periods=20).rank(pct=True)
    df["vol_pct_rank"] = pct_rank
    conditions = [
        pct_rank.isna(),
        pct_rank >= 0.95,
        pct_rank >= VOL_HIGH_PCT,
        pct_rank <= VOL_LOW_PCT,
    ]
    choices = ["NORMAL", "EXTREME", "HIGH", "LOW"]
    df["vol_regime"] = np.select(conditions, choices, default="NORMAL")

    bb_mid            = df["close"].rolling(CHOP_BB_PERIOD, min_periods=10).mean()
    bb_std            = df["close"].rolling(CHOP_BB_PERIOD, min_periods=10).std()
    df["bb_upper"]    = bb_mid + CHOP_BB_STD * bb_std
    df["bb_lower"]    = bb_mid - CHOP_BB_STD * bb_std
    df["bb_mid"]      = bb_mid
    df["bb_width"]    = (df["bb_upper"] - df["bb_lower"]) / bb_mid.replace(0, np.nan)

    s200      = df["slope200"]
    sign_now  = np.sign(s200)
    sign_past = np.sign(s200.shift(REGIME_TRANS_WINDOW))
    slope_flip = (sign_now != sign_past) & (sign_past != 0)

    calm           = df["vol_regime"].isin(["LOW", "NORMAL"])
    hot            = df["vol_regime"].isin(["HIGH", "EXTREME"])
    vol_escalation = hot & calm.shift(REGIME_TRANS_WINDOW).fillna(True)

    atr_ratio = (df["atr_pct"] /
                 df["atr_pct"].shift(REGIME_TRANS_WINDOW).replace(0, np.nan))
    atr_jump  = atr_ratio > REGIME_TRANS_ATR_JUMP

    df["regime_transition"] = (slope_flip | vol_escalation | atr_jump).fillna(False)

    return df

def swing_structure(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    n, h, l = len(df), df["high"].values, df["low"].values
    ph, pl  = np.zeros(n), np.zeros(n)
    for i in range(PIVOT_N, n):
        if h[i] == max(h[max(0,i-PIVOT_N):i+1]): ph[i] = h[i]
        if l[i] == min(l[max(0,i-PIVOT_N):i+1]): pl[i] = l[i]
    df["swing_high"], df["swing_low"] = ph, pl
    trend, strength = ["NEUTRAL"] * n, np.zeros(n)
    for i in range(PIVOT_N*3, n):
        rh = [(j,ph[j]) for j in range(max(0,i-120),i) if ph[j]>0][-MIN_SWINGS:]
        rl = [(j,pl[j]) for j in range(max(0,i-120),i) if pl[j]>0][-MIN_SWINGS:]
        if len(rh)<MIN_SWINGS or len(rl)<MIN_SWINGS: continue
        hh = sum(1 for k in range(1,len(rh)) if rh[k][1]>rh[k-1][1])
        hl = sum(1 for k in range(1,len(rl)) if rl[k][1]>rl[k-1][1])
        lh = sum(1 for k in range(1,len(rh)) if rh[k][1]<rh[k-1][1])
        ll = sum(1 for k in range(1,len(rl)) if rl[k][1]<rl[k-1][1])
        mx = MIN_SWINGS - 1
        if   hh+hl > lh+ll: trend[i]="UP";   strength[i]=(hh+hl)/(2*mx)
        elif lh+ll > hh+hl: trend[i]="DOWN";  strength[i]=(lh+ll)/(2*mx)
    df["trend_struct"]    = trend
    df["struct_strength"] = strength
    return df

def omega(df: pd.DataFrame) -> pd.DataFrame:
    df  = df.copy()
    e9,e21,e50,e100,e200 = (df[f"ema{s}"].values for s in EMA_SPANS)
    df["casc_up"]   = ((e9>e21)+(e21>e50)+(e50>e100)+(e100>e200)).astype(int)
    df["casc_down"] = ((e9<e21)+(e21<e50)+(e50<e100)+(e100<e200)).astype(int)
    df["omega_flow_bull"] = df["taker_ma"].rolling(W_NORM,min_periods=20).rank(pct=True)
    df["omega_flow_bear"] = 1 - df["omega_flow_bull"]
    rsi = df["rsi"].values
    def rsi_score(lo, hi):
        mid = (lo+hi)/2; half = (hi-lo)/2
        return np.clip(np.where((rsi>=lo)&(rsi<=hi), 1-abs(rsi-mid)/half, 0), 0, 1)
    df["omega_mom_bull"] = rsi_score(RSI_BULL_MIN, RSI_BULL_MAX)
    df["omega_mom_bear"] = rsi_score(RSI_BEAR_MIN, RSI_BEAR_MAX)
    d21 = (df["close"]-df["ema21"]).abs() / df["atr"].replace(0,np.nan)
    df["dist_ema21"]     = d21
    df["omega_pullback"] = np.where((d21>=0.05)&(d21<=PULLBACK_ATR_MAX),
                                    1-(d21/PULLBACK_ATR_MAX).clip(0,1), 0.0)
    df["omega_struct_up"]   = df["struct_strength"].where(df["trend_struct"]=="UP",   0)
    df["omega_struct_down"] = df["struct_strength"].where(df["trend_struct"]=="DOWN", 0)
    return df

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

_HTF_STACK_MAP: dict[str, list[str]] = {
    "1m":  ["5m",  "15m", "1h"],
    "3m":  ["15m", "1h",  "4h"],
    "5m":  ["15m", "1h",  "4h"],
    "15m": ["1h",  "4h",  "1d"],
    "30m": ["2h",  "4h",  "1d"],
    "1h":  ["4h",  "1d"],
    "2h":  ["4h",  "1d"],
    "4h":  [],
    "6h":  [],
    "8h":  [],
    "12h": [],
    "1d":  [],
}

HTF_INTERVAL = "4h"
HTF_STACK    = ["4h"]
MTF_ENABLED  = False

def prepare_htf(df_htf: pd.DataFrame, htf_interval: str = "4h") -> pd.DataFrame:
    global SLOPE_N, PIVOT_N, CHOP_S21, CHOP_S200, MIN_STOP_PCT, MAX_HOLD
    _saved = (SLOPE_N, PIVOT_N, CHOP_S21, CHOP_S200, MIN_STOP_PCT, MAX_HOLD)
    _p = _tf_params(htf_interval)
    SLOPE_N = _p["slope_n"]; PIVOT_N = _p["pivot_n"]
    CHOP_S21 = _p["chop_s21"]; CHOP_S200 = _p["chop_s200"]
    MIN_STOP_PCT = _p["min_stop_pct"]; MAX_HOLD = _p["max_hold"]
    try:
        df = indicators(df_htf)
        df = swing_structure(df)
        df = omega(df)
        scores = []
        for i in range(len(df)):
            row = df.iloc[i]; s = row["trend_struct"]
            if   s == "UP":   sc, _ = score_omega(row, "BULLISH")
            elif s == "DOWN": sc, _ = score_omega(row, "BEARISH")
            else:             sc    = 0.0
            scores.append(sc)
        df["htf_score"] = scores
        mb = pd.Series("CHOP", index=df.index)
        mb[df["slope200"] >  MACRO_SLOPE_BULL] = "BULL"
        mb[df["slope200"] <  MACRO_SLOPE_BEAR] = "BEAR"
        df["htf_macro"] = mb
    finally:
        SLOPE_N, PIVOT_N, CHOP_S21, CHOP_S200, MIN_STOP_PCT, MAX_HOLD = _saved
    return df

def merge_all_htf_to_ltf(df_ltf: pd.DataFrame,
                          htf_stack_dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    df_ltf["time"] = df_ltf["time"].astype("datetime64[ms]")
    for i, (tf, df_htf) in enumerate(htf_stack_dfs.items(), 1):
        mins = _TF_MINUTES.get(tf, 240)
        htf  = df_htf[["time","trend_struct","struct_strength",
                        "htf_score","htf_macro"]].copy()
        htf["time"] = (htf["time"] + pd.Timedelta(minutes=mins)).astype("datetime64[ms]")
        htf = htf.rename(columns={
            "trend_struct":    f"htf{i}_struct",
            "struct_strength": f"htf{i}_strength",
            "htf_score":       f"htf{i}_score",
            "htf_macro":       f"htf{i}_macro",
        })
        df_ltf = pd.merge_asof(
            df_ltf.sort_values("time").reset_index(drop=True),
            htf.sort_values("time").reset_index(drop=True),
            on="time", direction="backward")
        df_ltf[f"htf{i}_struct"]   = df_ltf[f"htf{i}_struct"].fillna("NEUTRAL")
        df_ltf[f"htf{i}_strength"] = df_ltf[f"htf{i}_strength"].fillna(0.0)
        df_ltf[f"htf{i}_score"]    = df_ltf[f"htf{i}_score"].fillna(0.0)
        df_ltf[f"htf{i}_macro"]    = df_ltf[f"htf{i}_macro"].fillna("CHOP")
    return df_ltf

def scan_symbol(df: pd.DataFrame, symbol: str,
                macro_bias_series, corr: dict,
                htf_stack_dfs: dict | None = None) -> tuple[list, dict]:
    df = indicators(df)
    df = swing_structure(df)
    df = omega(df)

    if MTF_ENABLED and htf_stack_dfs:
        df = merge_all_htf_to_ltf(df, htf_stack_dfs)

    trades  = []
    vetos   = defaultdict(int)
    account = ACCOUNT_SIZE
    min_idx = max(200, W_NORM, PIVOT_N*3) + 5

    open_pos: list[tuple[int, str]] = []

    # pre-extract numpy arrays — evita df.iloc[idx] no loop (3-5x mais rapido)
    _rsi   = df["rsi"].values;          _atr   = df["atr"].values
    _volr  = df["vol_regime"].values;   _tkma  = df["taker_ma"].values
    _sl21  = df["slope21"].values;      _sl200 = df["slope200"].values
    _dist  = df["dist_ema21"].values;   _str   = df["trend_struct"].values
    _stre  = df["struct_strength"].values
    _trans = df["regime_transition"].values
    _cup   = df["casc_up"].values;      _cdn   = df["casc_down"].values
    _ofb   = df["omega_flow_bull"].values; _ofbr = df["omega_flow_bear"].values
    _omb   = df["omega_mom_bull"].values;  _ombr = df["omega_mom_bear"].values
    _opu   = df["omega_pullback"].values
    _osu   = df["omega_struct_up"].values; _osd  = df["omega_struct_down"].values
    _bbu   = df["bb_upper"].values;     _bbl   = df["bb_lower"].values
    _bbm   = df["bb_mid"].values;       _bbw   = df["bb_width"].values
    _cls   = df["close"].values
    _htfm  = df[f"htf{len(HTF_STACK)}_macro"].values if MTF_ENABLED and f"htf{len(HTF_STACK)}_macro" in df.columns else None
    _htfs  = {i: {k: df[f"htf{i}_{k}"].values for k in ["struct","strength","score","macro"] if f"htf{i}_{k}" in df.columns}
              for i in range(1, len(HTF_STACK)+1)} if MTF_ENABLED else {}

    peak_equity        = ACCOUNT_SIZE
    prev_dd            = 0.0          # DD anterior para calcular velocidade
    consecutive_losses = 0
    cooldown_until     = -1
    sym_cooldown_until: dict[str, int] = {}

    _tl.info(f"\n{'═'*72}\n  {symbol}  [{df['time'].iloc[0].date()} → {df['time'].iloc[-1].date()}]\n{'═'*72}")

    for idx in range(min_idx, len(df)-MAX_HOLD-2):
        # build row from pre-extracted arrays (no Series overhead)
        row = {"trend_struct":_str[idx],"struct_strength":_stre[idx],
               "slope21":_sl21[idx],"slope200":_sl200[idx],
               "vol_regime":_volr[idx],"dist_ema21":_dist[idx],
               "rsi":_rsi[idx],"taker_ma":_tkma[idx],
               "casc_up":_cup[idx],"casc_down":_cdn[idx],
               "omega_flow_bull":_ofb[idx],"omega_flow_bear":_ofbr[idx],
               "omega_mom_bull":_omb[idx],"omega_mom_bear":_ombr[idx],
               "omega_pullback":_opu[idx],"omega_struct_up":_osu[idx],
               "omega_struct_down":_osd[idx],
               "close":_cls[idx],"bb_upper":_bbu[idx],"bb_lower":_bbl[idx],
               "bb_mid":_bbm[idx],"bb_width":_bbw[idx]}
        if MTF_ENABLED:
            for i,cols in _htfs.items():
                for k,arr in cols.items(): row[f"htf{i}_{k}"]=arr[idx]

        open_pos    = [(ei, s) for ei, s in open_pos if ei > idx]
        active_syms = [s for _, s in open_pos]

        macro_b = "CHOP"
        if MTF_ENABLED:
            macro_b = str(row.get("htf_macro", "CHOP"))
        elif macro_bias_series is not None:
            macro_b = macro_bias_series.iloc[min(idx, len(macro_bias_series)-1)]

        peak_equity = max(peak_equity, account)
        current_dd  = (peak_equity - account) / peak_equity if peak_equity > 0 else 0.0
        dd_scale    = 1.0
        for dd_thresh in sorted(DD_RISK_SCALE.keys(), reverse=True):
            if current_dd >= dd_thresh:
                dd_scale = DD_RISK_SCALE[dd_thresh]
                break
        if dd_scale == 0.0:
            vetos["dd_pause"] += 1; continue

        # DD velocity: se drawdown está a acelerar, reduz risco extra
        dd_velocity = current_dd - prev_dd
        if dd_velocity > 0.005 and current_dd > 0.03:   # DD a crescer >0.5pp e acima de 3%
            dd_scale *= max(0.5, 1.0 - dd_velocity * 10) # extra cut proporcional à velocidade
        prev_dd = current_dd

        in_transition = bool(_trans[idx])
        trans_mult    = REGIME_TRANS_SIZE_MULT if in_transition else 1.0

        if idx <= cooldown_until:
            vetos["streak_cooldown"] += 1; continue
        if idx <= sym_cooldown_until.get(symbol, -1):
            vetos["sym_cooldown"] += 1; continue

        ok, motivo_p, corr_size_mult = portfolio_allows(symbol, active_syms, corr)
        if not ok:
            vetos[motivo_p] += 1; continue

        direction, motivo, fractal_score = decide_direction(row, macro_b)

        is_chop_trade = False
        chop_bb_mid   = None
        chop_info     = {}

        if direction is None and motivo.startswith("chop"):
            chop_dir, chop_score, chop_info = score_chop(row)
            if chop_dir is not None and chop_score >= 0.30:
                direction     = chop_dir
                motivo        = "ok"
                fractal_score = 1.0
                is_chop_trade = True
                chop_bb_mid   = chop_info.get("bb_mid")
                vetos["chop_tentativa"] = vetos.get("chop_tentativa", 0)
            else:
                vetos[motivo] += 1; continue
        elif direction is None:
            vetos[motivo] += 1; continue

        if not is_chop_trade:
            score, comps = score_omega(row, direction)
            if score == 0.0:
                vetos["casc_zero"] += 1; continue

            weak = [k for k,v in comps.items() if v < OMEGA_MIN_COMPONENT]
            if len(weak) >= 3:
                vetos["comp_fraco"] += 1; continue

            vol_r_now   = str(_volr[idx])
            base_thresh = SCORE_BY_REGIME.get(macro_b, SCORE_THRESHOLD)
            threshold   = base_thresh + 0.05 if vol_r_now == "HIGH" else base_thresh
            if score < threshold:
                vetos["score_baixo"] += 1; continue
        else:
            _, score, _ = score_chop(row)
            comps = {"struct": 0.0, "flow": 0.0, "cascade": 0.0,
                     "momentum": chop_info.get("rsi_extreme", 0.0),
                     "pullback": chop_info.get("band_dist", 0.0)}

        if is_chop_trade:
            levels = calc_levels_chop(df, idx, direction, chop_bb_mid)
        else:
            levels = calc_levels(df, idx, direction)

        if levels is None:
            vetos["niveis"] += 1; continue

        entry, stop, target, rr = levels

        if is_chop_trade:
            result, duration, exit_p = label_trade_chop(
                df, idx+1, direction, entry, stop, target)
        else:
            result, duration, exit_p = label_trade(
                df, idx+1, direction, entry, stop, target)

        if result == "OPEN": continue

        vol_r = str(row.get("vol_regime", "NORMAL"))
        size  = position_size(account, entry, stop, score,
                              macro_b, direction, vol_r, dd_scale,
                              is_chop_trade=is_chop_trade,
                              peak_equity=peak_equity)
        size  = round(size * corr_size_mult * trans_mult, 4)
        if not is_chop_trade:
            size = round(size * fractal_score, 4)

        ep = float(exit_p)
        slip_exit = SLIPPAGE + SPREAD          # C2: slippage na saída (market order)
        if direction == "BULLISH":
            entry_cost = entry * (1 + COMMISSION)              # C1: comissão entrada
            ep_net     = ep * (1 - COMMISSION - slip_exit)     # C2: comissão + slip saída
            funding    = -(size * entry * FUNDING_PER_8H * duration / 32)
            pnl        = size * (ep_net - entry_cost) + funding
        else:
            entry_cost = entry * (1 - COMMISSION)              # C1: comissão entrada
            ep_net     = ep * (1 + COMMISSION + slip_exit)     # C2: comissão + slip saída
            funding    = +(size * entry * FUNDING_PER_8H * duration / 32)
            pnl        = size * (entry_cost - ep_net) + funding
        pnl     = round(pnl * LEVERAGE, 2)          # alavancagem escala PnL linearmente
        account = max(account + pnl, account * 0.5)

        if result == "LOSS":
            consecutive_losses += 1
            for n_losses in sorted(STREAK_COOLDOWN.keys(), reverse=True):
                if consecutive_losses >= n_losses:
                    cooldown_until = idx + STREAK_COOLDOWN[n_losses]
                    break
            sym_cooldown_until[symbol] = idx + SYM_LOSS_COOLDOWN
        else:
            consecutive_losses = 0

        open_pos.append((idx + 1 + duration, symbol))

        ts = df["time"].iloc[idx].strftime("%d/%m %Hh")
        trade_type = "CHOP-MR" if is_chop_trade else direction
        t = {
            "symbol":     symbol,
            "time":       ts,
            "timestamp":  df["time"].iloc[idx],
            "idx":        idx,
            "entry_idx":  idx+1,
            "direction":  direction,
            "trade_type": trade_type,
            "struct":     str(row["trend_struct"]),
            "struct_str": round(float(row["struct_strength"]),3),
            "cascade_n":  int(row["casc_up" if direction=="BULLISH" else "casc_down"]) if not is_chop_trade else 0,
            "taker_ma":   round(float(row["taker_ma"]),4) if not pd.isna(row["taker_ma"]) else 0,
            "rsi":        round(float(row["rsi"]),2)      if not pd.isna(row["rsi"])      else 0,
            "dist_ema21": round(float(row["dist_ema21"]),3),
            "macro_bias": macro_b,
            "vol_regime": vol_r,
            "dd_scale":   round(dd_scale, 2),
            "corr_mult":  round(corr_size_mult, 2),
            "in_transition": in_transition,
            "trans_mult":    round(trans_mult, 2),
            "entry":      entry, "stop": stop, "target": target,
            "exit_p":     round(float(exit_p),6),
            "rr":         rr, "duration": duration, "result": result, "pnl": pnl,
            "size":       round(size, 4),
            "score":      score, "fractal_align": fractal_score,
            "omega_struct":   comps["struct"],   "omega_flow":     comps["flow"],
            "omega_cascade":  comps["cascade"],  "omega_momentum": comps["momentum"],
            "omega_pullback": comps["pullback"],
            "chop_trade":     is_chop_trade,
            "bb_mid":         chop_info.get("bb_mid", 0.0) if is_chop_trade else 0.0,
        }
        trades.append(t)
        icon = "✓" if result=="WIN" else "✗"
        type_lbl = "[CHOP]" if is_chop_trade else ""
        _tl.info(f"  {ts}  {icon}  {direction:8s}{type_lbl}  Ω={score:.3f}  ${pnl:+.2f}  "
                 f"macro={macro_b}  vol={vol_r}  str={t['struct_str']:.2f}")

    closed = [t for t in trades if t["result"] in ("WIN","LOSS")]
    w = sum(1 for t in closed if t["result"]=="WIN")
    _tl.info(f"  TOTAL: {len(trades)}  W={w}  L={len(closed)-w}  "
             f"PnL=${sum(t['pnl'] for t in closed):+,.0f}\n")
    return trades, dict(vetos)

def equity_stats(pnl_list, start=ACCOUNT_SIZE):
    eq = [start]
    for p in pnl_list: eq.append(eq[-1]+p)
    peak, mdd, mdd_pct, streak, ms = start, 0.0, 0.0, 0, 0
    for e in eq:
        if e > peak: peak = e
        dd = peak-e; dp = dd/peak*100 if peak else 0
        if dd > mdd: mdd = dd; mdd_pct = dp
    for p in pnl_list:
        streak = streak+1 if p<0 else 0
        ms = max(ms, streak)
    return eq, round(mdd,2), round(mdd_pct,2), ms

def calc_ratios(pnl_list, start=ACCOUNT_SIZE, n_days=None):
    if len(pnl_list) < 2: return {"sharpe":None,"sortino":None,"calmar":None,"ret":0.0,"sharpe_daily":None}
    n      = len(pnl_list)
    mean   = sum(pnl_list)/n
    std    = (sum((p-mean)**2 for p in pnl_list)/(n-1))**0.5
    n_loss = sum(1 for p in pnl_list if p < 0)
    dd_std = (sum(p**2 for p in pnl_list if p<0)/max(n_loss,1))**0.5
    eq,_,mdd_pct,_ = equity_stats(pnl_list, start)
    ret = (eq[-1]-start)/start*100
    _days  = n_days if (n_days and n_days > 0) else 180
    tpy    = n * 365.0 / _days          # trades por ano
    ann    = tpy ** 0.5                 # anualizador per-trade
    dpd    = n / _days                  # trades por dia
    # Sharpe diário: agrega PnL em dias, calcula Sharpe sobre retornos diários
    daily: dict = {}
    for i, p in enumerate(pnl_list):
        day = int(i / max(dpd, 0.01))
        daily[day] = daily.get(day, 0.0) + p
    d_rets = list(daily.values())
    d_mean = sum(d_rets) / len(d_rets) if d_rets else 0
    d_std  = (sum((r-d_mean)**2 for r in d_rets)/max(len(d_rets)-1,1))**0.5
    sharpe_daily = round((d_mean/d_std)*(252**0.5), 3) if d_std else None
    return {
        "sharpe":       round((mean/std)*ann, 3)    if std    else None,
        "sharpe_daily": sharpe_daily,                           # R5: Sharpe diário (benchmark-comparable)
        "sortino":      round((mean/dd_std)*ann, 3) if dd_std else None,
        "calmar":       round(ret/mdd_pct, 3)       if mdd_pct else None,
        "ret":          round(ret, 2),
    }

def conditional_backtest(trades):
    buckets = {"0.53-0.59":[], "0.59-0.65":[], "0.65+":[]}
    for t in trades:
        s = t["score"]
        if   s < 0.59: buckets["0.53-0.59"].append(t)
        elif s < 0.65: buckets["0.59-0.65"].append(t)
        else:          buckets["0.65+"].append(t)
    out = {}
    for label, ts in buckets.items():
        c = [t for t in ts if t["result"] in ("WIN","LOSS")]
        if not c: out[label]=None; continue
        w   = [t for t in c if t["result"]=="WIN"]
        l   = [t for t in c if t["result"]=="LOSS"]
        wr  = len(w)/len(c)*100
        aw  = sum(t["pnl"] for t in w)/max(len(w),1)
        al  = sum(t["pnl"] for t in l)/max(len(l),1)
        exp = wr/100*aw + (1-wr/100)*al
        out[label] = {"n":len(c),"wr":round(wr,1),
                      "avg_rr":round(sum(t["rr"] for t in c)/len(c),2),
                      "exp":round(exp,2),"total":round(sum(t["pnl"] for t in c),2)}
    return out

def monte_carlo(pnl_list):
    if len(pnl_list) < MC_BLOCK*2: return None
    n, finals, dds, paths, pos = len(pnl_list), [], [], [], 0
    for sim in range(MC_N):
        sh = []
        while len(sh) < n:
            s = random.randint(0, n-MC_BLOCK); sh.extend(pnl_list[s:s+MC_BLOCK])
        sh  = sh[:n]; eq = [ACCOUNT_SIZE]
        for p in sh: eq.append(eq[-1]+p)
        finals.append(eq[-1])
        if eq[-1] > ACCOUNT_SIZE: pos += 1
        pk = ACCOUNT_SIZE; dd = 0.0
        for e in eq:
            if e > pk: pk = e
            if pk: dd = max(dd, (pk-e)/pk*100)
        dds.append(dd)
        if sim < 200: paths.append(eq)
    finals.sort()
    ror = sum(1 for f in finals if f < ACCOUNT_SIZE*0.80)/MC_N*100
    return {"pct_pos":round(pos/MC_N*100,1),
            "median":round(finals[MC_N//2],2),
            "p5":round(finals[int(MC_N*0.05)],2),
            "p95":round(finals[int(MC_N*0.95)],2),
            "avg_dd":round(sum(dds)/len(dds),2),
            "worst_dd":round(max(dds),2),
            "ror":round(ror,2),"finals":finals,"paths":paths,"dds":dds}

def walk_forward(trades):
    c = sorted([t for t in trades if t["result"] in ("WIN","LOSS")],
               key=lambda x: x["timestamp"])
    if len(c) < WF_TRAIN+WF_TEST: return []
    windows, i = [], 0
    while i+WF_TRAIN+WF_TEST <= len(c):
        tr = c[i:i+WF_TRAIN]; te = c[i+WF_TRAIN:i+WF_TRAIN+WF_TEST]
        def st(lst):
            w = sum(1 for t in lst if t["result"]=="WIN")
            return {"n":len(lst),"wr":round(w/len(lst)*100,1),"pnl":round(sum(t["pnl"] for t in lst),2)}
        windows.append({"w":i//WF_TEST+1,"train":st(tr),"test":st(te)}); i+=WF_TEST
    return windows

def walk_forward_by_regime(trades: list) -> dict:
    WF_TOL = 15
    results = {}
    for regime in ("BULL", "BEAR", "CHOP"):
        subset = sorted(
            [t for t in trades if t["result"] in ("WIN","LOSS")
             and t.get("macro_bias","CHOP") == regime],
            key=lambda x: x["timestamp"])
        if len(subset) < WF_TRAIN + WF_TEST:
            results[regime] = {"windows": [], "stable_pct": None, "n": len(subset)}
            continue
        windows = []
        i = 0
        while i + WF_TRAIN + WF_TEST <= len(subset):
            tr = subset[i:i+WF_TRAIN]
            te = subset[i+WF_TRAIN:i+WF_TRAIN+WF_TEST]
            wtr = sum(1 for t in tr if t["result"]=="WIN") / len(tr) * 100
            wte = sum(1 for t in te if t["result"]=="WIN") / len(te) * 100
            d   = wte - wtr
            windows.append({"train": round(wtr,1), "test": round(wte,1),
                             "delta": round(d,1), "ok": abs(d) <= WF_TOL})
            i += WF_TEST
        ok_n = sum(1 for w in windows if w["ok"])
        results[regime] = {
            "windows":    windows,
            "n":          len(subset),
            "stable_pct": round(ok_n / len(windows) * 100, 0) if windows else None,
        }
    return results

def print_wf_by_regime(wf_regime: dict):
    icons = {"BULL": "↑", "BEAR": "↓", "CHOP": "↔"}
    for regime, d in wf_regime.items():
        if d["stable_pct"] is None:
            print(f"  {icons.get(regime,'')} {regime:5s}  n={d['n']:>3d}  amostra insuficiente"); continue
        lbl = "✓ ESTÁVEL" if d["stable_pct"] >= 60 else "✗ INSTÁVEL"
        print(f"  {icons.get(regime,'')} {regime:5s}  n={d['n']:>3d}  "
              f"estáveis: {d['stable_pct']:.0f}%  {lbl}")
        for w in d["windows"][-6:]:
            st = "✓" if w["ok"] else "✗"
            print(f"         treino {w['train']:>5.1f}%  fora {w['test']:>5.1f}%  "
                  f"Δ {w['delta']:>+5.1f}%  {st}")

def symbol_robustness(all_trades):
    SYM_TRAIN, SYM_TEST = 8, 4
    by_sym = defaultdict(list)
    for t in all_trades: by_sym[t["symbol"]].append(t)
    results = {}
    for sym, trades in by_sym.items():
        closed = sorted([t for t in trades if t["result"] in ("WIN","LOSS")],
                        key=lambda x: x["timestamp"])
        pnl_s = [t["pnl"] for t in closed]
        r     = calc_ratios(pnl_s, n_days=SCAN_DAYS) if len(closed) >= 2 else {"sharpe":None,"calmar":None,"ret":0}
        _,_,mdd,_ = equity_stats(pnl_s) if pnl_s else ([0],0,0,0)
        wr = sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
        wf_ok = wf_tot = 0
        i = 0
        while i + SYM_TRAIN + SYM_TEST <= len(closed):
            tr  = closed[i:i+SYM_TRAIN]
            te  = closed[i+SYM_TRAIN:i+SYM_TRAIN+SYM_TEST]
            wtr = sum(1 for t in tr if t["result"]=="WIN")/len(tr)*100
            wte = sum(1 for t in te if t["result"]=="WIN")/len(te)*100
            if abs(wte-wtr) <= 35: wf_ok += 1
            wf_tot += 1; i += SYM_TEST
        results[sym] = {
            "n":      len(closed),
            "wr":     round(wr, 1),
            "sharpe": r["sharpe"],
            "max_dd": round(mdd, 1),
            "stable": round(wf_ok/wf_tot*100, 0) if wf_tot else None,
            "pnl":    round(sum(pnl_s), 2),
        }
    return results

BG,PANEL = "#0a0a12","#0f0f1a"
GOLD,GREEN,RED,BLUE,PURPLE,TEAL = "#e8b84b","#26d47c","#e85d5d","#4a9eff","#9b7fe8","#2dd4bf"
LGRAY,DGRAY,WHITE = "#6b7280","#1f2937","#f0f0f0"

def _ax(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor(PANEL)
    for sp in ax.spines.values(): sp.set_edgecolor(DGRAY); sp.set_linewidth(0.5)
    ax.tick_params(colors=LGRAY, labelsize=7, length=3)
    ax.xaxis.set_tick_params(labelcolor=LGRAY)
    ax.yaxis.set_tick_params(labelcolor=LGRAY)
    ax.grid(color=DGRAY, linewidth=0.4, linestyle="--", alpha=0.6)
    if title:   ax.set_title(title, color=LGRAY, fontsize=8, loc="left", pad=5)
    if xlabel:  ax.set_xlabel(xlabel, color=LGRAY, fontsize=7)
    if ylabel:  ax.set_ylabel(ylabel, color=LGRAY, fontsize=7)

def plot_dashboard(trades, eq, cond, wf, ratios, mdd_pct):
    closed  = [t for t in trades if t["result"] in ("WIN","LOSS")]
    wins    = [t for t in closed if t["result"]=="WIN"]
    losses  = [t for t in closed if t["result"]=="LOSS"]
    bull_t  = [t for t in closed if t["direction"]=="BULLISH"]
    bear_t  = [t for t in closed if t["direction"]=="BEARISH"]
    chop_t  = [t for t in closed if t.get("chop_trade")]
    wr      = len(wins)/len(closed)*100 if closed else 0
    bull_wr = sum(1 for t in bull_t if t["result"]=="WIN")/max(len(bull_t),1)*100
    bear_wr = sum(1 for t in bear_t if t["result"]=="WIN")/max(len(bear_t),1)*100
    roi     = (eq[-1]-ACCOUNT_SIZE)/ACCOUNT_SIZE*100

    fig = plt.figure(figsize=(26,14), facecolor=BG)
    fig.suptitle(
        f"☿  AZOTH v3.6   ·   {INTERVAL}   ·   {len(closed)} trades   ·   "
        f"[U1]Ω-risk  [U2]SoftCorr  [U3]CHOP-MR  ·   RR {TARGET_RR}×",
        color=GOLD, fontsize=11, y=0.98, fontweight="bold", fontfamily="monospace")
    gs = gridspec.GridSpec(3,4, figure=fig, hspace=0.50, wspace=0.35,
                           top=0.93, bottom=0.06, left=0.05, right=0.97)

    ax1 = fig.add_subplot(gs[0,:3])
    _ax(ax1, ylabel="Capital (USD)")
    x = list(range(len(eq)))
    ax1.fill_between(x, ACCOUNT_SIZE, eq, where=[v>=ACCOUNT_SIZE for v in eq], color=GREEN, alpha=0.06)
    ax1.fill_between(x, ACCOUNT_SIZE, eq, where=[v<ACCOUNT_SIZE  for v in eq], color=RED,   alpha=0.12)
    ax1.plot(x, eq, color=GOLD, linewidth=1.8, zorder=4)
    ax1.axhline(ACCOUNT_SIZE, color=DGRAY, linewidth=0.8, linestyle="--")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax1.set_title(
        f"${ACCOUNT_SIZE:,.0f} → ${eq[-1]:,.0f}   ROI {roi:+.1f}%   "
        f"Sharpe {ratios['sharpe']}   Sortino {ratios['sortino']}   "
        f"Calmar {ratios['calmar']}   MaxDD {mdd_pct:.1f}%   "
        f"L/S/MR {len(bull_t)}/{len(bear_t)}/{len(chop_t)}",
        color=LGRAY, fontsize=7, loc="left", pad=5)
    pk = [ACCOUNT_SIZE]
    for e in eq[1:]: pk.append(max(pk[-1],e))
    ddc = [(p-e)/p*100 if p else 0 for p,e in zip(pk,eq)]
    ax1b = ax1.twinx()
    ax1b.fill_between(x, 0, [-d for d in ddc], color=RED, alpha=0.18)
    ax1b.set_ylim(-50,5); ax1b.set_ylabel("DD%", color=RED, fontsize=6)
    ax1b.tick_params(colors=RED, labelsize=6); ax1b.set_facecolor(PANEL)

    ax2 = fig.add_subplot(gs[0,3])
    _ax(ax2, title=f"Score Ω   WR {wr:.1f}%  n={len(closed)}")
    bins = [i/50 for i in range(26,36)]
    ax2.hist([t["score"] for t in wins],   bins=bins, color=GREEN, alpha=0.7, label=f"WIN {len(wins)}",  density=True)
    ax2.hist([t["score"] for t in losses], bins=bins, color=RED,   alpha=0.7, label=f"LOSS {len(losses)}", density=True)
    ax2.axvline(SCORE_THRESHOLD, color=GOLD, linewidth=1.5, linestyle="--")
    ax2.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)

    ax3 = fig.add_subplot(gs[1,0])
    _ax(ax3, title="WR por Faixa Ω", ylabel="%")
    lc  = list(cond.keys())
    wrs = [cond[k]["wr"]  if cond[k] else 0 for k in lc]
    ns  = [cond[k]["n"]   if cond[k] else 0 for k in lc]
    exps= [cond[k]["exp"] if cond[k] else 0 for k in lc]
    bars = ax3.bar(lc, wrs, color=[GREEN if w>=55 else GOLD if w>=40 else RED for w in wrs], alpha=0.8, zorder=3)
    ax3.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
    for bar,n,exp in zip(bars,ns,exps):
        ax3.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
                 f"n={n}\nE${exp:+.0f}", ha="center", va="bottom", color=LGRAY, fontsize=6)
    ax3.set_ylim(0,100)

    ax4 = fig.add_subplot(gs[1,1])
    _ax(ax4, title="Vetor Ω  WIN vs LOSS")
    dims = ["omega_struct","omega_flow","omega_cascade","omega_momentum","omega_pullback"]
    dlb  = ["struct","flow","casc","mom","pull"]
    aw   = [sum(t[d] for t in wins)/max(len(wins),1)   for d in dims]
    al   = [sum(t[d] for t in losses)/max(len(losses),1) for d in dims]
    xd, bw = range(len(dims)), 0.35
    ax4.bar([i-bw/2 for i in xd], aw, bw, color=GREEN, alpha=0.75, label="WIN", zorder=3)
    ax4.bar([i+bw/2 for i in xd], al, bw, color=RED,   alpha=0.75, label="LOSS", zorder=3)
    ax4.axhline(OMEGA_MIN_COMPONENT, color=GOLD, linewidth=1.0, linestyle=":", alpha=0.7)
    ax4.set_xticks(list(xd)); ax4.set_xticklabels(dlb, fontsize=7, color=LGRAY)
    ax4.set_ylim(0,1.05); ax4.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=6)

    ax5 = fig.add_subplot(gs[1,2])
    _ax(ax5, title="Long / Short / CHOP-MR  WR%")
    chop_wr = sum(1 for t in chop_t if t["result"]=="WIN")/max(len(chop_t),1)*100
    sides    = ["LONG","SHORT","CHOP-MR"]
    wrs_ls   = [bull_wr, bear_wr, chop_wr]
    ns_ls    = [len(bull_t), len(bear_t), len(chop_t)]
    pnl_ls   = [sum(t["pnl"] for t in bull_t),
                sum(t["pnl"] for t in bear_t),
                sum(t["pnl"] for t in chop_t)]
    colors_ls = [GREEN if w>=50 else RED for w in wrs_ls]
    colors_ls[2] = TEAL
    bars2 = ax5.bar(sides, wrs_ls, color=colors_ls, alpha=0.8, width=0.4, zorder=3)
    ax5.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
    for bar,n,pnl in zip(bars2, ns_ls, pnl_ls):
        ax5.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
                 f"n={n}\n${pnl:+,.0f}", ha="center", va="bottom", color=LGRAY, fontsize=7)
    ax5.set_ylim(0,100)

    ax6 = fig.add_subplot(gs[1,3])
    _ax(ax6, title="PnL por Símbolo")
    by_sym  = defaultdict(list)
    for t in closed: by_sym[t["symbol"]].append(t)
    sp = dict(sorted({s:sum(t["pnl"] for t in ts) for s,ts in by_sym.items()}.items(), key=lambda x:x[1]))
    ax6.barh([s.replace("USDT","") for s in sp], list(sp.values()),
             color=[GREEN if v>=0 else RED for v in sp.values()], alpha=0.8, zorder=3)
    ax6.axvline(0, color=LGRAY, linewidth=0.8)
    ax6.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax6.tick_params(axis="y", labelsize=7)

    ax7 = fig.add_subplot(gs[2,:3])
    _ax(ax7, title="Walk-Forward  —  Treino vs Fora da Amostra", ylabel="WR%")
    if wf:
        wf_x  = [w["w"] for w in wf]; wf_tr = [w["train"]["wr"] for w in wf]; wf_te = [w["test"]["wr"] for w in wf]
        ok    = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15)
        ax7.plot(wf_x, wf_tr, color=BLUE,  linewidth=1.2, marker=".", markersize=3, label="Treino")
        ax7.plot(wf_x, wf_te, color=GREEN, linewidth=1.5, marker=".", markersize=3, label="Fora da amostra")
        ax7.fill_between(wf_x, [t-20 for t in wf_tr], [t+20 for t in wf_tr], alpha=0.06, color=BLUE)
        ax7.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
        ax7.set_title(f"Walk-Forward  {ok}/{len(wf)} estáveis ({ok/len(wf)*100:.0f}%)",
                      color=LGRAY, fontsize=8, loc="left", pad=5)
        ax7.set_ylim(0,105); ax7.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)

    ax8 = fig.add_subplot(gs[2,3])
    _ax(ax8, title="WR% por Regime Macro")
    bm_data = {}
    for t in closed:
        b = t.get("macro_bias","CHOP")
        bm_data.setdefault(b, []).append(t)
    regimes   = ["BULL","BEAR","CHOP"]
    bm_wrs, bm_ns, bm_pnls = [], [], []
    for regime in regimes:
        ts2 = bm_data.get(regime, [])
        if ts2:
            w2 = sum(1 for t in ts2 if t["result"]=="WIN")
            bm_wrs.append(round(w2/len(ts2)*100,1))
            bm_ns.append(len(ts2))
            bm_pnls.append(round(sum(t["pnl"] for t in ts2),0))
        else:
            bm_wrs.append(0); bm_ns.append(0); bm_pnls.append(0)
    bars_bm = ax8.bar(regimes, bm_wrs, color=[GREEN, RED, TEAL], alpha=0.8, zorder=3)
    ax8.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
    for bar, n, pnl in zip(bars_bm, bm_ns, bm_pnls):
        if n:
            ax8.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
                     f"n={n}\n${pnl:+,.0f}", ha="center", va="bottom",
                     color=LGRAY, fontsize=6)
    ax8.set_ylim(0, 100)

    fname = str(RUN_DIR / "charts" / f"dashboard_{INTERVAL}.png")
    plt.savefig(fname, dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(); print(f"  Dashboard → {fname}")

def plot_montecarlo(mc, real_eq):
    if not mc: return
    fig, axes = plt.subplots(1,3, figsize=(22,7), facecolor=BG)
    fig.suptitle(
        f"☿  AZOTH v3.6  ·  Monte Carlo  ({MC_N}×  bloco={MC_BLOCK})\n"
        f"Positivos: {mc['pct_pos']:.1f}%   Mediana: ${mc['median']:,.0f}   "
        f"p5: ${mc['p5']:,.0f}   p95: ${mc['p95']:,.0f}   RoR: {mc['ror']:.1f}%",
        color=GOLD, fontsize=11, y=0.98)
    ax1,ax2,ax3 = axes
    _ax(ax1,"Equity (200 simulações)","trades","Capital")
    for p in mc["paths"]:
        ax1.plot(range(len(p)), p, color=GREEN if p[-1]>ACCOUNT_SIZE else RED, alpha=0.05, linewidth=0.5)
    ax1.plot(range(len(real_eq)), real_eq, color=GOLD, linewidth=2.5, zorder=6, label="Real")
    for lv,c,lb in [(mc["p5"],RED,f"p5 ${mc['p5']:,.0f}"),
                    (mc["median"],GOLD,f"Med ${mc['median']:,.0f}"),
                    (mc["p95"],GREEN,f"p95 ${mc['p95']:,.0f}")]:
        ax1.axhline(lv, color=c, linewidth=1.2, linestyle=":", alpha=0.8, label=lb)
    ax1.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    _ax(ax2,"Distribuição Final","Capital Final","Freq")
    f=mc["finals"]; mn,mx=f[0],f[-1]; rng=mx-mn if mx!=mn else 1
    bw=rng/40; hist=[0]*40; bc=[mn+(i+.5)*bw for i in range(40)]
    for v in f: hist[min(int((v-mn)/rng*40),39)] += 1
    ax2.bar(bc,hist,width=bw*.9,color=[GREEN if c>=ACCOUNT_SIZE else RED for c in bc],alpha=0.8)
    for lv,c in [(ACCOUNT_SIZE,"#ffff88"),(mc["median"],GOLD),(mc["p5"],RED),(mc["p95"],GREEN)]:
        ax2.axvline(lv,color=c,linewidth=1.5)
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax2.tick_params(axis="x",rotation=30,labelsize=6)
    _ax(ax3,"Drawdown Máximo (%)","DD Max%","Freq")
    pdd=[]
    for p in mc["paths"]:
        pk=p[0]; dd=0.0
        for e in p:
            if e>pk: pk=e
            if pk: dd=max(dd,(pk-e)/pk*100)
        pdd.append(dd)
    ax3.hist(pdd,bins=30,color=PURPLE,alpha=0.8,edgecolor=BG)
    avg=sum(pdd)/len(pdd)
    ax3.axvline(avg, color=GOLD, linewidth=2.0, label=f"Média {avg:.1f}%")
    ax3.axvline(25,  color=RED,  linewidth=1.5, linestyle="--", alpha=0.8, label="Limite 25%")
    ax3.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)
    plt.tight_layout(rect=[0,0,1,0.93])
    fname = str(RUN_DIR / "charts" / f"montecarlo_{INTERVAL}.png")
    plt.savefig(fname, dpi=130, bbox_inches="tight", facecolor=BG)
    plt.close(); print(f"  Monte Carlo → {fname}")

def plot_trades(df, trades, symbol):
    closed = [t for t in trades if t["result"] in ("WIN","LOSS")]
    if not closed: return
    wins   = [t for t in closed if t["result"]=="WIN"]
    losses = [t for t in closed if t["result"]=="LOSS"]
    all_i  = []
    for t in closed: all_i.extend([t["idx"]-20, t["entry_idx"]+t["duration"]+8])
    i0  = max(0, min(all_i)-5); i1 = min(len(df), max(all_i)+5)
    sub = df.iloc[i0:i1].reset_index(drop=True); off = i0
    wr_str = f"{len(wins)/len(closed)*100:.0f}%WR" if closed else "—"
    pnl_total = sum(t["pnl"] for t in closed)

    fig = plt.figure(figsize=(26,16), facecolor=BG)
    fig.suptitle(
        f"☿ AZOTH v3.6  ·  {symbol}  ·  {INTERVAL}  ·  "
        f"{len(closed)} trades  ·  {len(wins)}W/{len(losses)}L  ·  {wr_str}  ·  "
        f"PnL ${pnl_total:+,.0f}",
        color=GOLD, fontsize=12, y=0.99, fontweight="bold", fontfamily="monospace")
    gs2 = gridspec.GridSpec(5,1, figure=fig, height_ratios=[4,.5,1,.8,.8],
                            hspace=0.06, top=0.95, bottom=0.04, left=0.06, right=0.97)
    ax1 = fig.add_subplot(gs2[0]); _ax(ax1, ylabel="Preço")

    if "vol_regime" in sub.columns:
        vol_c_map = {"LOW":"#1e3a5f","HIGH":"#3b1f1f","EXTREME":"#4c1010"}
        prev_r = None; si = 0
        for xi,vr in enumerate(sub["vol_regime"].values):
            if vr != prev_r:
                if prev_r and prev_r in vol_c_map:
                    ax1.axvspan(si-.5, xi-.5, color=vol_c_map[prev_r], alpha=0.25, zorder=0)
                si = xi; prev_r = vr
        if prev_r and prev_r in vol_c_map:
            ax1.axvspan(si-.5, len(sub)-.5, color=vol_c_map[prev_r], alpha=0.25, zorder=0)

    for xi in range(len(sub)):
        o=sub["open"].iloc[xi]; c=sub["close"].iloc[xi]
        h=sub["high"].iloc[xi]; l=sub["low"].iloc[xi]
        col = GREEN if c>=o else RED
        ax1.plot([xi,xi],[l,h],color=col,linewidth=0.5,alpha=0.5)
        ax1.bar(xi, max(abs(c-o),0.0001), bottom=min(o,c), width=0.7, color=col, alpha=0.75, zorder=2)

    for s,ec,lw,lb in [(9,TEAL,.9,"EMA9"),(21,BLUE,1.4,"EMA21"),(50,PURPLE,1.3,"EMA50"),(200,"#fb923c",2.1,"EMA200")]:
        cn = f"ema{s}"
        if cn in sub.columns:
            ev=sub[cn].values; vx=[xi for xi,v in enumerate(ev) if not(isinstance(v,float) and math.isnan(v))]
            if vx: ax1.plot(vx,[ev[xi] for xi in vx],color=ec,linewidth=lw,alpha=0.85,label=lb)

    if "bb_upper" in sub.columns:
        bbu = sub["bb_upper"].values; bbl = sub["bb_lower"].values; bbm = sub["bb_mid"].values
        vx  = [xi for xi in range(len(sub)) if not(isinstance(bbu[xi],float) and math.isnan(bbu[xi]))]
        if vx:
            ax1.plot(vx, [bbu[xi] for xi in vx], color=TEAL, linewidth=0.7, alpha=0.5, linestyle="--", label="BB")
            ax1.plot(vx, [bbl[xi] for xi in vx], color=TEAL, linewidth=0.7, alpha=0.5, linestyle="--")
            ax1.plot(vx, [bbm[xi] for xi in vx], color=TEAL, linewidth=0.5, alpha=0.3, linestyle=":")

    for xi,v in enumerate(sub["swing_high"].values):
        if v>0: ax1.scatter(xi,v,marker="^",color="#fb923c",s=20,zorder=7,alpha=0.5)
    for xi,v in enumerate(sub["swing_low"].values):
        if v>0: ax1.scatter(xi,v,marker="v",color=BLUE,s=20,zorder=7,alpha=0.5)

    price_range = sub["high"].max() - sub["low"].min()
    offset_step  = price_range * 0.025
    entry_positions = {}
    for t in closed:
        ei = t["entry_idx"] - off
        if ei < 0 or ei >= len(sub): continue
        entry_positions[ei] = entry_positions.get(ei, 0) + 1
    annotation_slots: dict = {}

    for t in closed:
        ei = t["entry_idx"] - off
        xi = t["entry_idx"] + t["duration"] - off
        if ei < 0 or ei >= len(sub): continue
        xi  = min(xi, len(sub)-1)
        if t.get("chop_trade"):
            col = TEAL if t["result"] == "WIN" else PURPLE
        else:
            col = GREEN if t["result"] == "WIN" else RED
        mk  = "^" if t["direction"] == "BULLISH" else "v"

        nearby = sum(1 for e in entry_positions if abs(e - ei) <= 3 and entry_positions[e] > 0)
        dense  = nearby > 2

        x0 = max(0, ei-1); x1 = min(len(sub), xi+2)
        if not dense:
            ax1.hlines(t["stop"],   x0, x1, colors=RED,   lw=1.0, linestyle=":", alpha=0.55, zorder=3)
            ax1.hlines(t["target"], x0, x1, colors=GREEN, lw=1.0, linestyle="--",alpha=0.55, zorder=3)
            ax1.fill_between([max(0,ei-1), min(len(sub)-1,xi+1)],
                             t["entry"], t["stop"], color=RED, alpha=0.05, zorder=1)
        else:
            ax1.hlines(t["stop"],   x0, x1, colors=RED,   lw=0.6, linestyle=":", alpha=0.30, zorder=2)
            ax1.hlines(t["target"], x0, x1, colors=GREEN, lw=0.6, linestyle="--",alpha=0.30, zorder=2)

        ax1.hlines(t["entry"], x0, x1, colors=WHITE, lw=0.5, linestyle="-", alpha=0.15, zorder=2)
        mk_size = 200 if not dense else 100
        ax1.scatter(ei, t["entry"], marker=mk, color=col, s=mk_size,
                    zorder=10, edgecolors=WHITE, linewidths=1.2 if not dense else 0.7)
        ax1.scatter(xi, t["exit_p"], marker="D", color=col, s=60 if not dense else 30,
                    zorder=10, edgecolors=WHITE, linewidths=0.7)
        ax1.plot([ei, xi], [t["entry"], t["exit_p"]],
                 color=col, lw=1.0 if not dense else 0.5, alpha=0.4, linestyle="--", zorder=4)

        slot_key = round(ei / 3)
        used_y   = annotation_slots.get(slot_key, [])
        base_y   = (t["entry"] + t["exit_p"]) / 2
        cand_y = base_y
        for used in sorted(used_y):
            if abs(cand_y - used) < offset_step * 1.5:
                cand_y = used + offset_step * 1.8
        annotation_slots.setdefault(slot_key, []).append(cand_y)

        ann_x  = ei + (xi - ei) * 0.3
        type_pfx = "MR" if t.get("chop_trade") else ("L" if t["direction"] == "BULLISH" else "S")
        lbl = f"{type_pfx} ${t['pnl']:+.0f}\nΩ{t['score']:.2f}"
        fs  = 6 if not dense else 5
        ax1.annotate(lbl, (ann_x, cand_y), color=col, fontsize=fs,
                     ha="center", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.15", facecolor=BG,
                               alpha=0.70, edgecolor="none"))

    from matplotlib.lines import Line2D
    handles,labels = ax1.get_legend_handles_labels()
    extra = [Line2D([0],[0],color=RED,lw=1.1,linestyle=":",label="Stop"),
             Line2D([0],[0],color=GREEN,lw=1.1,linestyle="--",label="Target"),
             Line2D([0],[0],color=LGRAY,lw=0,marker="^",markersize=8,label="Long"),
             Line2D([0],[0],color=LGRAY,lw=0,marker="v",markersize=8,label="Short"),
             Line2D([0],[0],color=TEAL,lw=1.0,linestyle="--",label="BB / CHOP-MR")]
    ax1.legend(handles=handles+extra, labels=labels+[e.get_label() for e in extra],
               facecolor=DGRAY,labelcolor=WHITE,fontsize=7,loc="upper left",ncol=9,framealpha=0.8)
    ax1.set_xlim(-1,len(sub)+1)

    ax_vs = fig.add_subplot(gs2[1],sharex=ax1)
    ax_vs.set_facecolor(PANEL); ax_vs.set_yticks([])
    ax_vs.set_ylabel("Vol",color=LGRAY,fontsize=6)
    for sp in ax_vs.spines.values(): sp.set_edgecolor(DGRAY)
    vol_cmap2 = {"LOW":BLUE,"NORMAL":LGRAY,"HIGH":"#fb923c","EXTREME":RED}
    if "vol_pct_rank" in sub.columns:
        vpr=sub["vol_pct_rank"].fillna(0.5).values
        vrc=[vol_cmap2.get(sub["vol_regime"].iloc[xi] if "vol_regime" in sub.columns else "NORMAL",LGRAY)
             for xi in range(len(sub))]
        ax_vs.bar(range(len(sub)),vpr,color=vrc,alpha=0.8,width=0.8)
        ax_vs.axhline(VOL_HIGH_PCT,color="#fb923c",lw=0.7,linestyle="--",alpha=0.6)
        ax_vs.axhline(VOL_LOW_PCT, color=BLUE,     lw=0.7,linestyle="--",alpha=0.6)
    ax_vs.set_ylim(0,1); ax_vs.tick_params(labelbottom=False,labelsize=5,colors=LGRAY)

    ax2=fig.add_subplot(gs2[2],sharex=ax1); _ax(ax2,ylabel="RSI")
    if "rsi" in sub.columns:
        rv=sub["rsi"].values
        vx=[xi for xi,v in enumerate(rv) if not(isinstance(v,float) and math.isnan(v))]
        vy=[rv[xi] for xi in vx]
        ax2.plot(vx,vy,color=GOLD,linewidth=1.2)
        ax2.fill_between(vx,50,vy,where=[v>50 for v in vy],color=GREEN,alpha=0.12)
        ax2.fill_between(vx,50,vy,where=[v<50 for v in vy],color=RED,alpha=0.12)
        for t in closed:
            ei2=t["entry_idx"]-off
            if 0<=ei2<len(sub):
                rv2=sub["rsi"].iloc[ei2]
                if not math.isnan(rv2):
                    c_dot = TEAL if t.get("chop_trade") else (GREEN if t["result"]=="WIN" else RED)
                    ax2.scatter(ei2,rv2,marker="o",color=c_dot,s=28,zorder=5,alpha=0.8)
    ax2.axhline(CHOP_RSI_SHORT, color=RED,   lw=0.8,linestyle="--",alpha=0.5)
    ax2.axhline(70, color=RED,  lw=0.5,linestyle=":",alpha=0.3)
    ax2.axhline(50,color=LGRAY,lw=0.5,linestyle="--",alpha=0.3)
    ax2.axhline(CHOP_RSI_LONG,  color=GREEN, lw=0.8,linestyle="--",alpha=0.5)
    ax2.axhline(30, color=GREEN,lw=0.5,linestyle=":",alpha=0.3)
    ax2.set_ylim(0,100)

    ax3=fig.add_subplot(gs2[3],sharex=ax1); _ax(ax3,ylabel="Flow")
    if "taker_ratio" in sub.columns:
        tr=sub["taker_ratio"].values
        vx=[xi for xi,v in enumerate(tr) if not(isinstance(v,float) and math.isnan(v))]
        vy=[tr[xi] for xi in vx]
        ax3.bar(vx,[(v-.5)*2 for v in vy],color=[GREEN if v>.5 else RED for v in vy],alpha=0.45,width=0.8)
        ax3.axhline(0,color=LGRAY,lw=0.8)
    if "taker_ma" in sub.columns:
        tm=sub["taker_ma"].values
        vx=[xi for xi,v in enumerate(tm) if not(isinstance(v,float) and math.isnan(v))]
        ax3.plot(vx,[(tm[xi]-.5)*2 for xi in vx],color=GOLD,lw=1.2)
    ax3.set_ylim(-1.1,1.1)

    ax4=fig.add_subplot(gs2[4],sharex=ax1); _ax(ax4,ylabel="Vol")
    vc=[GREEN if sub["close"].iloc[xi]>=sub["open"].iloc[xi] else RED for xi in range(len(sub))]
    ax4.bar(range(len(sub)),sub["vol"].values,color=vc,alpha=0.5,width=0.8)
    ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v/1e6:.1f}M"))
    step=max(1,len(sub)//14); tpos=list(range(0,len(sub),step))
    ax4.set_xticks(tpos)
    ax4.set_xticklabels([sub["time"].iloc[xi].strftime("%d/%m\n%Hh") for xi in tpos],
                        rotation=0,ha="center",fontsize=6,color=LGRAY)
    fname=str(RUN_DIR/"charts"/f"trades_{symbol}_{INTERVAL}.png")
    plt.savefig(fname,dpi=120,bbox_inches="tight",facecolor=BG); plt.close()
    print(f"  Chart → {fname}")

SEP = "=" * 80

def print_header():
    print(f"\n{SEP}")
    print(f"  ☿ AZOTH v3.6   AURUM Finance   {RUN_ID}")
    tf_label = f"{INTERVAL}+{HTF_INTERVAL}(MTF)" if MTF_ENABLED else INTERVAL
    print(f"  {len(SYMBOLS)} ativos   {tf_label}   {N_CANDLES} candles")
    print(f"  Regime≥{REGIME_MIN_STRENGTH}   "
          f"Ω: BEAR≥{SCORE_BY_REGIME['BEAR']} BULL≥{SCORE_BY_REGIME['BULL']} CHOP≥{SCORE_BY_REGIME['CHOP']}   "
          f"Corr<{CORR_THRESHOLD}(soft>{CORR_SOFT_THRESHOLD}×{CORR_SOFT_MULT})   MaxPos={MAX_OPEN_POSITIONS}")
    print(f"  Macro: {MACRO_SYMBOL} slope200 ({MACRO_SLOPE_BEAR:.2f}/{MACRO_SLOPE_BULL:.2f})   "
          f"Trailing: ON   GlobalRisk: ON")
    print(f"  [U1]Ω-risk  [U2]SoftCorr  [U3]CHOP-MR(BB{CHOP_BB_PERIOD}+RSI)  [U4]WF-regime  [U5]RegimeTrans(×{REGIME_TRANS_SIZE_MULT})")
    if MTF_ENABLED:
        stack_str = " → ".join([INTERVAL] + HTF_STACK)
        print(f"  Fractal Stack: {stack_str}   min_stop={MIN_STOP_PCT*100:.2f}%")
    print(f"  Risk {BASE_RISK*100:.1f}–{MAX_RISK*100:.1f}%   RR {TARGET_RR}× (CHOP:{CHOP_RR}×)   Capital ${ACCOUNT_SIZE:,.0f}")
    print(f"  Output → {RUN_DIR}/")
    print(SEP)

def bear_market_analysis(all_trades: list) -> dict:
    regimes = {"BULL": [], "BEAR": [], "CHOP": []}
    for t in all_trades:
        b = t.get("macro_bias", "CHOP")
        if b in regimes:
            regimes[b].append(t)
    result = {}
    for regime, ts in regimes.items():
        closed = [t for t in ts if t["result"] in ("WIN","LOSS")]
        if not closed:
            result[regime] = None; continue
        w   = sum(1 for t in closed if t["result"] == "WIN")
        wr  = w / len(closed) * 100
        pnl = sum(t["pnl"] for t in closed)
        eq, _, mdd, _ = equity_stats([t["pnl"] for t in closed])
        r   = calc_ratios([t["pnl"] for t in closed])
        result[regime] = {
            "n":      len(closed),
            "wr":     round(wr, 1),
            "pnl":    round(pnl, 2),
            "sharpe": r["sharpe"],
            "max_dd": round(mdd, 1),
            "bull_n": sum(1 for t in closed if t["direction"]=="BULLISH"),
            "bear_n": sum(1 for t in closed if t["direction"]=="BEARISH"),
        }
    return result

def year_by_year_analysis(all_trades: list, start_equity: float = ACCOUNT_SIZE) -> dict:
    from collections import defaultdict
    by_year: dict[int, list] = defaultdict(list)
    for t in all_trades:
        ts = t.get("timestamp")
        if ts is None: continue
        yr = ts.year if hasattr(ts, "year") else int(str(ts)[:4])
        by_year[yr].append(t)

    years = sorted(by_year.keys())
    result = {}
    running_eq = start_equity

    for yr in years:
        ts_ = by_year[yr]
        closed = [t for t in ts_ if t["result"] in ("WIN", "LOSS")]
        if not closed:
            result[yr] = None; continue

        wins   = sum(1 for t in closed if t["result"] == "WIN")
        wr     = wins / len(closed) * 100
        pnl    = sum(t["pnl"] for t in closed)
        longs  = [t for t in closed if t["direction"] == "BULLISH"]
        shorts = [t for t in closed if t["direction"] == "BEARISH"]

        eq, _, mdd_pct, streak = equity_stats([t["pnl"] for t in closed], running_eq)
        roi = (eq[-1] - running_eq) / running_eq * 100

        bear_ts = [t for t in closed if t.get("macro_bias") == "BEAR"]
        bull_ts = [t for t in closed if t.get("macro_bias") == "BULL"]

        r = calc_ratios([t["pnl"] for t in closed], running_eq)

        result[yr] = {
            "n":       len(closed),
            "wins":    wins,
            "wr":      round(wr, 1),
            "pnl":     round(pnl, 2),
            "roi":     round(roi, 2),
            "mdd":     round(mdd_pct, 2),
            "sharpe":  r["sharpe"],
            "streak":  streak,
            "longs":   len(longs),
            "shorts":  len(shorts),
            "bear_n":  len(bear_ts),
            "bull_n":  len(bull_ts),
            "eq_end":  round(eq[-1], 2),
        }
        running_eq = eq[-1]

    return result

def print_year_by_year(yy: dict, start_equity: float = ACCOUNT_SIZE):
    years = [yr for yr, d in yy.items() if d is not None]
    if len(years) < 2:
        return

    S_ = "─" * 82
    print(f"\n  {'ANO':4s}  {'N':>4s}  {'WR':>6s}  {'ROI':>7s}  {'PnL':>10s}  "
          f"{'MaxDD':>6s}  {'Sharpe':>7s}  {'L/S':>7s}  {'BEAR/BULL':>9s}  STATUS")
    print(f"  {S_}")

    for yr in sorted(years):
        d = yy[yr]
        if d is None:
            print(f"  {yr}  sem trades"); continue

        sh     = d["sharpe"] or 0.0
        roi_s  = f"{d['roi']:>+6.1f}%"

        if   d["roi"] > 15 and d["mdd"] < 15: status = "✓ BOM"
        elif d["roi"] > 0:                    status = "~ OK"
        elif d["roi"] == 0:                   status = "= NEUTRO"
        else:                                 status = "✗ PERDA"

        print(f"  {yr}  {d['n']:>4d}  {d['wr']:>5.1f}%  {roi_s}  "
              f"${d['pnl']:>+8,.0f}  {d['mdd']:>5.1f}%  {sh:>7.3f}  "
              f"L{d['longs']}/S{d['shorts']}  "
              f"B{d['bear_n']}/U{d['bull_n']}   {status}")

    print(f"  {S_}")
    print()
    max_abs = max(abs(yy[yr]["roi"]) for yr in years if yy[yr]) or 1
    bar_max = 30
    for yr in sorted(years):
        d = yy[yr]
        if not d: continue
        bar_len = int(abs(d["roi"]) / max_abs * bar_max)
        bar_c   = "█" if d["roi"] >= 0 else "░"
        bar     = bar_c * bar_len
        sign    = "+" if d["roi"] >= 0 else "-"
        print(f"  {yr}  {sign}{abs(d['roi']):>5.1f}%  {bar}")

    pos_years = sum(1 for yr in years if yy[yr] and yy[yr]["roi"] > 0)
    print(f"\n  ► {pos_years}/{len(years)} anos positivos  |  "
          f"Capital: ${start_equity:,.0f} → ${yy[sorted(years)[-1]]['eq_end']:,.0f}")

def print_bear_market_enhanced(bm: dict, yy: dict):
    print(f"\n  PERFORMANCE POR REGIME MACRO")
    print(f"  {'─'*72}")
    print(f"  {'REGIME':6s}  {'N':>4s}  {'WR':>6s}  {'Sharpe':>7s}  "
          f"{'MaxDD':>6s}  {'L/S':>7s}  {'PnL':>12s}  EDGE?")
    print(f"  {'─'*72}")

    icons = {"BULL": "↑", "BEAR": "↓", "CHOP": "↔"}
    totals = {}
    for regime in ("BULL", "BEAR", "CHOP"):
        d = bm.get(regime)
        if not d:
            print(f"  {icons.get(regime,'')} {regime:5s}   sem dados"); continue
        sh   = d["sharpe"] or 0.0
        edge = "✓" if d["wr"] >= 50 and d["pnl"] > 0 else "~" if d["pnl"] > 0 else "✗"
        bar_len = min(20, max(0, int(abs(d["pnl"]) / 300)))
        bar = ("█" * bar_len if d["pnl"] >= 0 else "░" * bar_len)
        print(f"  {icons.get(regime,'')} {regime:5s}  {d['n']:>4d}  {d['wr']:>5.1f}%  "
              f"{sh:>7.3f}  {d['max_dd']:>5.1f}%  "
              f"L{d['bull_n']}/S{d['bear_n']}  ${d['pnl']:>+10,.0f}  {edge}  {bar}")
        totals[regime] = d

    bear = totals.get("BEAR")
    bull = totals.get("BULL")
    chop = totals.get("CHOP")
    print()
    if bear and bear["pnl"] > 0:
        print(f"  ► BEAR: lucrativo em crash  (+${bear['pnl']:,.0f}, WR {bear['wr']:.1f}%) — edge anti-cíclico ✓")
    if bull and bull["pnl"] > 0:
        print(f"  ► BULL: lucrativo em alta   (+${bull['pnl']:,.0f}, WR {bull['wr']:.1f}%) — edge bidirecional ✓")
    elif bull and bull["pnl"] < 0:
        print(f"  ► BULL: perdendo em alta     (${bull['pnl']:,.0f}, WR {bull['wr']:.1f}%) — SHORT bias confirmado")
    if chop and chop["n"] > 0:
        chop_mr_n = chop["n"]
        print(f"  ► CHOP: {chop_mr_n} trades (inclui CHOP-MR [U3])  WR {chop['wr']:.1f}%  ${chop['pnl']:,.0f}")
    if bear and bull and bear["wr"] > bull["wr"]:
        delta = bear["wr"] - bull["wr"]
        print(f"  ► SHORT bias: WR BEAR {bear['wr']:.1f}% vs BULL {bull['wr']:.1f}% "
              f"(Δ+{delta:.1f}%) — sistema SHORT-dominant")

def print_symbol_robustness(r):
    print(f"  {'─'*74}")
    print(f"  {'ATIVO':12s}  {'N':>3s}  {'WR':>6s}  {'Sharpe':>7s}  {'MaxDD':>6s}  {'WF%':>5s}  {'PnL':>12s}  STATUS")
    print(f"  {'─'*74}")
    for sym, d in sorted(r.items(), key=lambda x: (x[1].get("sharpe") or -99), reverse=True):
        sh   = d["sharpe"] or 0.0
        stb  = d["stable"]
        stb_str = f"{stb:>4.0f}%" if stb is not None else "  N/A"
        status = ("✓ ROBUSTO" if sh>0.3 and (stb or 0)>=60
                  else "~ FRÁGIL" if (d["pnl"] or 0)>0
                  else "✗ DROPAR")
        print(f"  {sym:12s}  {d['n']:>3d}  {d['wr']:>5.1f}%  {sh:>7.3f}  "
              f"{d['max_dd']:>5.1f}%  {stb_str}  ${d['pnl']:>+10,.0f}  {status}")

    pos_pnls = {s: (v["pnl"] or 0) for s, v in r.items() if (v["pnl"] or 0) > 0}
    total_pos = sum(pos_pnls.values())
    if total_pos > 0:
        top_sym = max(pos_pnls, key=pos_pnls.get)
        top_pct = pos_pnls[top_sym] / total_pos * 100
        if top_pct > 50:
            print(f"\n  ⚠ CONCENTRAÇÃO: {top_sym} representa {top_pct:.0f}% do PnL positivo "
                  f"(${pos_pnls[top_sym]:,.0f}/{total_pos:,.0f})")
            print(f"    → sem esse símbolo o portfólio seria: "
                  f"${total_pos - pos_pnls[top_sym]:,.0f}")

def print_chop_analysis(all_trades: list):
    """[U3] Análise específica dos trades CHOP-MR."""
    chop_trades = [t for t in all_trades if t.get("chop_trade") and t["result"] in ("WIN","LOSS")]
    if not chop_trades:
        print(f"\n  CHOP-MR: sem trades gerados")
        return

    wins = sum(1 for t in chop_trades if t["result"] == "WIN")
    wr   = wins / len(chop_trades) * 100
    pnl  = sum(t["pnl"] for t in chop_trades)

    by_sym: dict = defaultdict(list)
    for t in chop_trades: by_sym[t["symbol"]].append(t)

    print(f"\n  CHOP-MR [U3]   n={len(chop_trades)}  WR={wr:.1f}%  PnL=${pnl:+,.0f}")
    print(f"  {'─'*60}")
    print(f"  {'ATIVO':12s}  {'N':>3s}  {'WR':>6s}  {'PnL':>10s}  {'RR_med':>6s}")
    for sym in sorted(by_sym):
        ts  = by_sym[sym]
        w2  = sum(1 for t in ts if t["result"]=="WIN")
        wr2 = w2/len(ts)*100
        p2  = sum(t["pnl"] for t in ts)
        rr2 = sum(t["rr"] for t in ts)/len(ts)
        ico = "✓" if wr2>=50 and p2>0 else "~" if p2>0 else "✗"
        print(f"  {ico} {sym:12s}  {len(ts):>3d}  {wr2:>5.1f}%  ${p2:>+8,.0f}  {rr2:>5.2f}×")

def print_veredito(all_trades, eq, mdd_pct, mc, wf, cond, ratios, wf_regime=None):
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr     = sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    exp    = sum(t["pnl"] for t in closed)/max(len(closed),1)
    top    = cond.get("0.65+") or cond.get("0.59-0.65") or cond.get("0.53-0.59")

    bear_stab = (wf_regime or {}).get("BEAR", {}).get("stable_pct")
    if bear_stab is not None:
        wf_ok = bear_stab >= 60
        wf_label = f"BEAR regime {bear_stab:.0f}%"
    elif wf:
        pct_g = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15)/len(wf)*100
        wf_ok = pct_g >= 60
        wf_label = f"global {pct_g:.0f}%"
    else:
        wf_ok = False; wf_label = "sem dados"

    checks = [
        ("Trades suficientes (≥30)",        len(closed)>=30),
        ("Win Rate ≥ 50%",                  wr>=50),
        ("Expectativa positiva",            exp>0),
        ("Edge faixa alta Ω",               top and top["wr"]>=55 and top["exp"]>0),
        ("MaxDD < 20%",                     mdd_pct<20),
        ("Sharpe ≥ 1.0 (annualizado)",      ratios["sharpe"] and ratios["sharpe"]>=1.0),
        ("Monte Carlo ≥ 70% positivo",      mc and mc["pct_pos"]>=70 and mc["p5"]>ACCOUNT_SIZE*0.75),
        (f"Walk-Forward estável ({wf_label})", wf_ok),
    ]
    passou = sum(1 for _,v in checks if v)
    print(f"\n{SEP}\n  ☿ VEREDITO — AZOTH v3.6\n{SEP}")
    for nome, ok in checks: print(f"  {'✓' if ok else '✗'}  {nome}")
    verdict = ("EDGE CONFIRMADO — pronto para live" if passou>=7
               else "PROMISSOR — ajuste fino" if passou>=5
               else "FRÁGIL — revisar filtros")
    print(f"\n  {passou}/8   ► {verdict}\n{SEP}\n")
    log.info(f"Veredito: {passou}/8  ROI={ratios['ret']:.2f}%  WR={wr:.1f}%  MaxDD={mdd_pct:.1f}%")
    try:
        print_benchmark(
            azoth_roi    = ratios["ret"],
            azoth_sharpe = ratios["sharpe"] or 0.0,
            azoth_mdd    = mdd_pct,
            n_days       = SCAN_DAYS
        )
    except Exception as e:
        log.warning(f"Benchmark falhou: {e}")

def _fetch_yahoo(ticker: str, n_days: int) -> dict | None:
    import time as _t
    end_ts   = int(_t.time())
    start_ts = end_ts - n_days * 86400 - 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&period1={start_ts}&period2={end_ts}")
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code != 200: return None
        result = r.json()["chart"]["result"]
        if not result: return None
        closes = result[0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 5: return None
        return {"first": closes[0], "last": closes[-1], "closes": closes}
    except Exception:
        return None

def _bm_maxdd(closes: list) -> float:
    peak = closes[0]; mdd = 0.0
    for c in closes:
        if c > peak: peak = c
        dd = (peak-c)/peak*100
        if dd > mdd: mdd = dd
    return round(mdd, 2)

def _bm_sharpe(closes: list) -> float | None:
    if len(closes) < 10: return None
    rets = [(closes[i]-closes[i-1])/closes[i-1] for i in range(1, len(closes))]
    n = len(rets); mean = sum(rets)/n
    std = (sum((r-mean)**2 for r in rets)/(n-1))**0.5 if n>1 else 0
    return round((mean/std)*(252**0.5), 3) if std else None

def print_benchmark(azoth_roi: float, azoth_sharpe: float,
                    azoth_mdd: float, n_days: int):
    S = "─" * 80
    print(f"\n{S}")
    print(f"  BENCHMARK   AZOTH v3.6  vs  Buy-and-Hold  ({n_days} dias)")
    print(S)

    specs = [
        ("BTC-USD",  "Bitcoin (BTC)"),
        ("SPY",      "S&P 500 (SPY) "),
        ("GC=F",     "Ouro (XAU)    "),
        ("^DXY",     "Dólar (DXY)   "),
    ]

    rows = []
    for ticker, label in specs:
        d = _fetch_yahoo(ticker, n_days)
        if d:
            roi    = round((d["last"]-d["first"])/d["first"]*100, 2)
            mdd    = _bm_maxdd(d["closes"])
            sharpe = _bm_sharpe(d["closes"])
            rows.append((label, roi, mdd, sharpe))
        else:
            rows.append((label, None, None, None))

    print(f"  {'Ativo':20s}  {'ROI':>8s}  {'MaxDD':>7s}  {'Sharpe':>8s}  {'AZOTH alpha':>12s}")
    print(f"  {'─'*20}  {'─'*8}  {'─'*7}  {'─'*8}  {'─'*12}")

    valid_rois = []
    for label, roi, mdd, sharpe in rows:
        if roi is None:
            print(f"  {label:20s}  {'—':>8s}  {'—':>7s}  {'—':>8s}  {'N/A':>12s}")
            continue
        roi_s = f"{roi:+.1f}%"
        mdd_s = f"{mdd:.1f}%"
        sh_s  = f"{sharpe:.3f}" if sharpe else "—"
        alpha = azoth_roi - roi
        alp_s = f"{alpha:+.1f}pp"
        marker = " ◄ AZOTH lidera" if alpha > 0 else " ✗ AZOTH atrás "
        print(f"  {label:20s}  {roi_s:>8s}  {mdd_s:>7s}  {sh_s:>8s}  {alp_s:>6s}{marker}")
        valid_rois.append(roi)

    print(f"  {'─'*20}  {'─'*8}  {'─'*7}  {'─'*8}  {'─'*12}")
    az_roi = f"{azoth_roi:+.1f}%"
    az_mdd = f"{azoth_mdd:.1f}%"
    az_sh  = f"{azoth_sharpe:.3f}"
    print(f"  {'☿ AZOTH v3.6':20s}  {az_roi:>8s}  {az_mdd:>7s}  {az_sh:>8s}  {'◄ REFERÊNCIA':>12s}")

    if valid_rois:
        beat = sum(1 for r in valid_rois if azoth_roi > r)
        best = max(valid_rois)
        print(f"\n  ► AZOTH supera {beat}/{len(valid_rois)} benchmarks   "
              f"Melhor bench: {best:+.1f}%   "
              f"Alpha s/ melhor: {azoth_roi-best:+.1f}pp   "
              f"MaxDD AZOTH {azoth_mdd:.1f}% vs BTC {rows[0][2] or 0:.1f}%")
    print(S)

def export_json(all_trades, eq, mc, cond, ratios):
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    wr     = sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
    chop_n = sum(1 for t in closed if t.get("chop_trade"))
    payload = {
        "version": "azoth-3.6", "run_id": RUN_ID,
        "timestamp": datetime.now().isoformat(),
        "config": {
            "interval": INTERVAL, "n_candles": N_CANDLES, "symbols": SYMBOLS,
            "score_threshold": SCORE_THRESHOLD, "regime_min": REGIME_MIN_STRENGTH,
            "cascade_min": CASCADE_MIN, "omega_min": OMEGA_MIN_COMPONENT,
            "stop_atr_m": STOP_ATR_M, "target_rr": TARGET_RR,
            "base_risk": BASE_RISK, "max_risk": MAX_RISK,
            "max_open_positions": MAX_OPEN_POSITIONS, "corr_threshold": CORR_THRESHOLD,
            "corr_soft_threshold": CORR_SOFT_THRESHOLD, "corr_soft_mult": CORR_SOFT_MULT,
            "macro_symbol": MACRO_SYMBOL,
            "omega_risk_table": OMEGA_RISK_TABLE,
            "chop_bb_period": CHOP_BB_PERIOD, "chop_bb_std": CHOP_BB_STD,
            "chop_rsi_long": CHOP_RSI_LONG, "chop_rsi_short": CHOP_RSI_SHORT,
            "chop_rr": CHOP_RR, "chop_size_mult": CHOP_SIZE_MULT,
            "regime_trans_window":    REGIME_TRANS_WINDOW,
            "regime_trans_atr_jump":  REGIME_TRANS_ATR_JUMP,
            "regime_trans_size_mult": REGIME_TRANS_SIZE_MULT,
        },
        "summary": {
            "total_trades": len(all_trades), "closed": len(closed),
            "win_rate": round(wr,2), "total_pnl": round(sum(t["pnl"] for t in closed),2),
            "final_equity": round(eq[-1],2),
            "chop_mr_trades": chop_n,
            **{k: ratios.get(k) for k in ("sharpe","sortino","calmar","ret")},
        },
        "conditional": cond,
        "bear_market": {r: d for r, d in bear_market_analysis(all_trades).items() if d},
        "monte_carlo": {k:v for k,v in (mc or {}).items() if k not in ("paths","finals","dds")},
        "trades": [{k:(str(v) if k=="timestamp" else v) for k,v in t.items() if k!="timestamp"}
                   for t in all_trades],
        "equity": eq,
    }
    fname = str(RUN_DIR / "reports" / f"azoth_{INTERVAL}_v36.json")
    with open(fname,"w",encoding="utf-8") as f:
        json.dump(payload,f,ensure_ascii=False,indent=2,default=str)
    print(f"  JSON → {fname}")

if __name__ == "__main__":

    print("\n" + "═"*52)
    print("  ☿  AZOTH v3.6   AURUM Finance")
    print("  ── ALL-SCALE FRACTAL ENGINE ──────────────")
    print("  15m entrada × 1h × 4h × 1d  estrutura")
    print("  [U1]Ω-risk [U2]SoftCorr [U3]CHOP-MR")
    print("═"*52)

    print(f"\n  Exemplos: 30=1m  90=3m  180=6m  365=1ano  730=2anos")
    print(f"  (365 dias = ~35k candles 15m + 8.5k 1h + 2.4k 4h + 465 1d × 28 símbolos)")
    _days_in = input(f"  Período em dias [{SCAN_DAYS}] > ").strip()
    if _days_in.isdigit() and 7 <= int(_days_in) <= 1500:
        SCAN_DAYS = int(_days_in)

    N_CANDLES = SCAN_DAYS * 24 * 4
    HTF_N_CANDLES_MAP = {
        "1h": SCAN_DAYS * 24       + 200,
        "4h": SCAN_DAYS *  6       + 100,
        "1d": SCAN_DAYS            + 100,
    }

    _TFP         = _tf_params(ENTRY_TF)
    MIN_STOP_PCT = _TFP["min_stop_pct"]
    SLOPE_N      = _TFP["slope_n"]
    CHOP_S21     = _TFP["chop_s21"]
    CHOP_S200    = _TFP["chop_s200"]
    PIVOT_N      = _TFP["pivot_n"]
    MAX_HOLD     = _TFP["max_hold"]

    _plot_ans = input("  Gerar gráficos? [s/N] > ").strip().lower()
    GENERATE_PLOTS = _plot_ans in ("s", "sim", "y", "yes", "1")

    _total_req = (
        len(SYMBOLS) * (
            _math.ceil(N_CANDLES / 1000) +
            _math.ceil(HTF_N_CANDLES_MAP["1h"] / 1000) +
            _math.ceil(HTF_N_CANDLES_MAP["4h"] / 1000) +
            _math.ceil(HTF_N_CANDLES_MAP["1d"] / 1000)
        )
    )
    _est_mins = round(_total_req * 0.08 / 60, 1)

    print(f"\n  Período   : {SCAN_DAYS} dias")
    print(f"  15m       : {N_CANDLES:,} candles  ({_math.ceil(N_CANDLES/1000)} requests/símbolo)")
    print(f"  1h        : {HTF_N_CANDLES_MAP['1h']:,}c    4h: {HTF_N_CANDLES_MAP['4h']:,}c    1d: {HTF_N_CANDLES_MAP['1d']:,}c")
    print(f"  Download  : ~{_total_req} requests  (~{_est_mins} min)")
    print(f"  Fractal   : score 0.33→1.00 × position size")
    print(f"  Ω-Risk    : 0.53→×0.70  0.59→×1.10  0.65→×1.30  [U1]")
    print(f"  SoftCorr  : corr {CORR_SOFT_THRESHOLD}–{CORR_THRESHOLD} → size×{CORR_SOFT_MULT}  [U2]")
    print(f"  CHOP-MR   : BB{CHOP_BB_PERIOD}+RSI<{CHOP_RSI_LONG}/>RSI>{CHOP_RSI_SHORT}  RR={CHOP_RR}  [U3]")
    print(f"  Plots     : {'✓ ON' if GENERATE_PLOTS else '✗ OFF'}")
    print("  " + "─"*48)
    input("  Enter para iniciar... ")

    print_header()
    log.info(f"AZOTH v3.6 iniciado — {RUN_ID}  tf={INTERVAL}  nc={N_CANDLES}  plots={'on' if GENERATE_PLOTS else 'off'}")

    S = "─" * 80

    print(f"\n{S}\n  DADOS   {ENTRY_TF}   {N_CANDLES:,} candles   ({SCAN_DAYS} dias)\n{S}")
    _fetch_syms = list(SYMBOLS)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)
    all_dfs = fetch_all(_fetch_syms)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs: print("Sem dados."); sys.exit(1)

    htf_stack_by_sym: dict[str, dict] = {}
    if MTF_ENABLED:
        for tf in HTF_STACK:
            nc = HTF_N_CANDLES_MAP.get(tf, 300)
            print(f"\n{S}\n  HTF   {tf}   {nc:,} candles\n{S}")
            tf_dfs = fetch_all(list(all_dfs.keys()), interval=tf, n_candles=nc)
            for sym, df_h in tf_dfs.items():
                df_h = prepare_htf(df_h, htf_interval=tf)
                htf_stack_by_sym.setdefault(sym, {})[tf] = df_h

    print(f"\n{S}\n  PRÉ-PROCESSAMENTO\n{S}")
    macro_series = detect_macro(all_dfs)
    if macro_series is not None:
        bull_n = (macro_series=="BULL").sum()
        bear_n = (macro_series=="BEAR").sum()
        chop_n = (macro_series=="CHOP").sum()
        total  = bull_n + bear_n + chop_n
        print(f"  Macro ({MACRO_SYMBOL})    "
              f"↑ BULL {bull_n}c ({bull_n/total*100:.0f}%)   "
              f"↓ BEAR {bear_n}c ({bear_n/total*100:.0f}%)   "
              f"↔ CHOP {chop_n}c ({chop_n/total*100:.0f}%)")
    else:
        print("  Macro: N/A — usando CHOP")

    corr = build_corr_matrix(all_dfs)
    top_pairs = sorted([(k,v) for k,v in corr.items() if k[0]<k[1]], key=lambda x:-x[1])[:5]
    corr_str  = "   ".join(
        f"{a[0].replace('USDT','')}/{a[1].replace('USDT','')}: {v:.2f}"
        for a, v in top_pairs)
    print(f"  Correlação      {corr_str}")

    vol_summary = {}
    for sym, df in all_dfs.items():
        df_i = indicators(df)
        vc   = df_i["vol_regime"].value_counts().to_dict()
        vol_summary[sym.replace("USDT","")] = vc
    total_vc: dict = {}
    for vc in vol_summary.values():
        for k, v in vc.items(): total_vc[k] = total_vc.get(k,0) + v
    tot = sum(total_vc.values())
    vol_dist = "   ".join(f"{k} {v/tot*100:.0f}%" for k, v in
                          sorted(total_vc.items(), key=lambda x: ["LOW","NORMAL","HIGH","EXTREME"].index(x[0]) if x[0] in ["LOW","NORMAL","HIGH","EXTREME"] else 99))
    print(f"  Vol Regime      {vol_dist}")

    print(f"\n{S}")
    print(f"  SCAN   {'ATIVO':12s}  {'N':>5s}  {'W/L':>7s}  {'WR':>6s}  {'L/S':>6s}  {'Ω̄':>5s}  {'PnL':>10s}")
    print(S)
    all_trades: list = []
    all_vetos = defaultdict(int)
    for sym, df in all_dfs.items():
        if sym not in SYMBOLS:
            continue
        trades, vetos = scan_symbol(df, sym, macro_series, corr,
                                    htf_stack_by_sym.get(sym) if MTF_ENABLED else None)
        all_trades.extend(trades)
        for k, v in vetos.items(): all_vetos[k] += v
        closed = [t for t in trades if t["result"] in ("WIN","LOSS")]
        w    = sum(1 for t in closed if t["result"]=="WIN")
        l2   = len(closed) - w
        pnl  = sum(t["pnl"] for t in closed)
        bull = sum(1 for t in trades if t["direction"]=="BULLISH")
        bear = sum(1 for t in trades if t["direction"]=="BEARISH")
        avg  = sum(t["score"] for t in trades)/max(len(trades),1) if trades else 0.0
        wr2  = w/len(closed)*100 if closed else 0.0
        chop_mr = sum(1 for t in trades if t.get("chop_trade"))
        flag = "  ⚠ WR<25%" if wr2<25 and closed else ""
        chop_flag = f"  [MR:{chop_mr}]" if chop_mr > 0 else ""
        print(f"  ✓  {sym:12s}  {len(trades):>5d}  {w:>3d}/{l2:<3d}  {wr2:>5.1f}%  "
              f"L{bull}/S{bear}  {avg:.3f}  ${pnl:>+9,.0f}{flag}{chop_flag}")

    print(f"\n{S}\n  FILTROS DE VETO\n{S}")
    total_v = sum(all_vetos.values())
    for k, n in sorted(all_vetos.items(), key=lambda x: -x[1]):
        bar = "▓" * min(int(n/total_v*35), 35) if total_v else ""
        print(f"  {k:42s}  {n:>6d}  {n/total_v*100:>4.1f}%  {bar}")

    if not all_trades: print("\n  Sem trades."); sys.exit(1)
    all_trades.sort(key=lambda x: x["timestamp"])
    closed = [t for t in all_trades if t["result"] in ("WIN","LOSS")]
    if not closed: print("\n  Sem trades fechados."); sys.exit(1)

    pnl_s = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, ms = equity_stats(pnl_s)
    ratios = calc_ratios(pnl_s)

    print(f"\n{S}")
    print(f"  RESULTADOS   {'ATIVO':12s}  {'N':>3s}  {'W/L':>7s}  {'WR':>6s}  {'L/S':>6s}  {'Ω̄':>5s}  {'PnL':>12s}  OK")
    print(S)
    by_sym = defaultdict(list)
    for t in all_trades: by_sym[t["symbol"]].append(t)
    for sym in sorted(by_sym):
        ts  = by_sym[sym]
        c   = [t for t in ts if t["result"] in ("WIN","LOSS")]
        if not c: continue
        w2  = sum(1 for t in c if t["result"]=="WIN")
        wr2 = w2/len(c)*100
        ag  = sum(t["score"] for t in ts)/len(ts)
        p2  = sum(t["pnl"] for t in c)
        b2  = sum(1 for t in ts if t["direction"]=="BULLISH")
        s2  = sum(1 for t in ts if t["direction"]=="BEARISH")
        ico = "✓" if wr2>=50 and p2>0 else "~" if p2>0 else "✗"
        print(f"  {sym:12s}  {len(ts):>3d}  {w2:>3d}/{len(c)-w2:<3d}  {wr2:>5.1f}%  "
              f"L{b2}/S{s2}  {ag:.3f}  ${p2:>+10,.0f}  {ico}")

    print(f"\n{S}\n  MÉTRICAS DE PORTFÓLIO\n{S}")
    print(f"  Sharpe   {str(ratios['sharpe'] or '—'):>7s}     "
          f"Sortino  {str(ratios['sortino'] or '—'):>7s}     "
          f"Calmar  {str(ratios['calmar'] or '—'):>7s}")
    print(f"  Sharpe diário {str(ratios.get('sharpe_daily') or '—'):>5s}  "
          f"(benchmark-comparable, ann. 252d)")
    print(f"  ROI      {ratios['ret']:>6.2f}%     "
          f"MaxDD    {mdd_pct:>6.2f}%     "
          f"Streak  {ms:>5d} perdas")
    print(f"  Capital  ${ACCOUNT_SIZE:>8,.0f}  →  ${eq[-1]:>10,.0f}   (+${eq[-1]-ACCOUNT_SIZE:,.0f})")
    for lado, ts2 in [("LONG ", [t for t in closed if t["direction"]=="BULLISH"]),
                      ("SHORT", [t for t in closed if t["direction"]=="BEARISH"]),
                      ("MR   ", [t for t in closed if t.get("chop_trade")])]:
        if not ts2: continue
        w3  = sum(1 for t in ts2 if t["result"]=="WIN")
        wr3 = w3/len(ts2)*100
        p3  = sum(t["pnl"] for t in ts2)
        ico = "✓" if wr3>=50 and p3>0 else "~" if p3>0 else "✗"
        print(f"  {ico} {lado}   {w3:>3d}W / {len(ts2)-w3:<3d}L   "
              f"WR {wr3:>5.1f}%   PnL ${p3:>+10,.0f}   n={len(ts2)}")

    print(f"\n{S}\n  EDGE POR FAIXA Ω\n{S}")
    print(f"  {'Faixa':>10s}  {'N':>4s}  {'WR':>6s}  {'RR':>5s}  {'E/trade':>9s}  {'Total':>12s}  STATUS")
    cond = conditional_backtest(all_trades)
    for label, d in cond.items():
        if not d: print(f"  {label:>10s}  —  sem dados"); continue
        st = ("✓ EDGE" if d["wr"]>=55 and d["exp"]>0
              else "~ NEUTRO" if d["exp"]>0 else "✗ SEM EDGE")
        print(f"  {label:>10s}  {d['n']:>4d}  {d['wr']:>5.1f}%  {d['avg_rr']:>4.2f}×  "
              f"${d['exp']:>+8.2f}  ${d['total']:>+10,.0f}  {st}")

    mc = monte_carlo(pnl_s)
    print(f"\n{S}\n  MONTE CARLO   {MC_N}× simulações   bloco={MC_BLOCK}\n{S}")
    if mc:
        rlb = "✓ SEGURO" if mc["ror"]<1 else "⚠ ATENÇÃO" if mc["ror"]<5 else "✗ ALTO RISCO"
        print(f"  Positivos  {mc['pct_pos']:>5.1f}%   "
              f"p5 ${mc['p5']:>9,.0f}   Mediana ${mc['median']:>9,.0f}   p95 ${mc['p95']:>9,.0f}")
        print(f"  RoR        {mc['ror']:>5.1f}%   [{rlb}]   "
              f"DD médio {mc['avg_dd']:.1f}%   pior {mc['worst_dd']:.1f}%")
    else:
        print("  Amostra insuficiente")

    wf = walk_forward(all_trades)
    print(f"\n{S}\n  WALK-FORWARD GLOBAL   {len(wf)} janelas   treino={WF_TRAIN}  teste={WF_TEST}\n{S}")
    if wf:
        ok  = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15)
        pct = ok/len(wf)*100
        lbl = "✓ ESTÁVEL" if pct>=60 else "✗ INSTÁVEL"
        print(f"  {ok}/{len(wf)} estáveis ({pct:.0f}%)   {lbl}")
        print(f"\n  {'W':>3s}  {'TREINO':>6s}  {'FORA':>6s}  {'Δ':>6s}  OK?")
        for w in wf[-12:]:
            d  = w["test"]["wr"] - w["train"]["wr"]
            st = "✓" if abs(d)<=15 else "✗"
            print(f"  {w['w']:>3d}  {w['train']['wr']:>5.1f}%  "
                  f"{w['test']['wr']:>5.1f}%  {d:>+5.1f}%  {st}")
        if len(wf) > 12:
            print(f"  ... (+{len(wf)-12} janelas anteriores)")
    else:
        print("  Amostra insuficiente")

    wf_regime = walk_forward_by_regime(all_trades)
    print(f"\n{S}\n  WALK-FORWARD POR REGIME   (tolerância ±25%)\n{S}")
    print(f"  Isola o efeito de troca de regime — cada período avaliado no próprio contexto")
    print()
    print_wf_by_regime(wf_regime)
    regime_stabs = [d["stable_pct"] for d in wf_regime.values() if d["stable_pct"] is not None]
    if regime_stabs:
        bear_stab = wf_regime.get("BEAR", {}).get("stable_pct")
        if bear_stab is not None:
            print(f"\n  BEAR regime (principal): {bear_stab:.0f}% estável  "
                  f"{'✓' if bear_stab >= 60 else '~' if bear_stab >= 40 else '✗'}")

    print(f"\n{S}\n  RELATÓRIOS\n{S}")
    if GENERATE_PLOTS:
        plot_dashboard(all_trades, eq, cond, wf, ratios, mdd_pct)
        plot_montecarlo(mc, eq)
        top_syms = sorted(by_sym,
                          key=lambda s: len([t for t in by_sym[s]
                                             if t["result"] in ("WIN","LOSS")]),
                          reverse=True)[:6]
        for sym in top_syms:
            df = all_dfs.get(sym)
            if df is not None:
                plot_trades(omega(swing_structure(indicators(df))), by_sym[sym], sym)
    else:
        print("  Plots desativados — exportando só JSON e métricas")
    export_json(all_trades, eq, mc, cond, ratios)

    print(f"\n{S}\n  ROBUSTEZ POR SÍMBOLO\n{S}")
    print_symbol_robustness(symbol_robustness(all_trades))

    print_chop_analysis(all_trades)

    yy = year_by_year_analysis(all_trades)
    if len([yr for yr, d in yy.items() if d]) >= 2:
        print(f"\n{S}\n  PERFORMANCE ANO A ANO\n{S}")
        print_year_by_year(yy)

    print(f"\n{S}\n  ANÁLISE DE REGIME   (Pitch Institucional)\n{S}")
    print_bear_market_enhanced(bear_market_analysis(all_trades), yy)

    print_veredito(all_trades, eq, mdd_pct, mc, wf, cond, ratios, wf_regime)

    print(f"{S}")
    print(f"  OUTPUT: {RUN_DIR}/")
    print(f"  ├── charts/    dashboard_{INTERVAL}.png   montecarlo_{INTERVAL}.png   trades_*")
    print(f"  ├── reports/   azoth_{INTERVAL}_v36.json")
    print(f"  └── logs/      run.log   trades.log   validation.log")
    print(f"{S}\n")