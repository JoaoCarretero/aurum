"""AURUM — Technical indicators, swing structure, omega scoring."""
import numpy as np
import pandas as pd
from config.params import *

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

    calm = df["vol_regime"].isin(["LOW", "NORMAL"])
    hot = df["vol_regime"].isin(["HIGH", "EXTREME"])
    calm_prev = calm.shift(REGIME_TRANS_WINDOW)
    # Keep the shifted regime mask explicitly boolean to avoid pandas
    # object downcasting warnings on fillna(True).
    calm_prev = calm_prev.where(calm_prev.notna(), True).astype(bool)
    vol_escalation = hot & calm_prev

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


# ── ORDER FLOW INDICATORS (MERCURIO) ────────────────────────

def cvd(df: pd.DataFrame) -> pd.DataFrame:
    """Cumulative Volume Delta: taker_buy - taker_sell accumulated."""
    df = df.copy()
    taker_buy = df["tbb"]
    taker_sell = df["vol"] - df["tbb"]
    df["vdelta"] = taker_buy - taker_sell
    df["cvd"] = df["vdelta"].cumsum()
    _cvd_mean = df["cvd"].rolling(200, min_periods=50).mean()
    _cvd_std  = df["cvd"].rolling(200, min_periods=50).std().replace(0, 1)
    df["cvd_z"] = (df["cvd"] - _cvd_mean) / _cvd_std
    return df


def cvd_divergence(df: pd.DataFrame, lookback: int = 10) -> pd.DataFrame:
    """
    Detect divergence between price and CVD.
    Bullish div: price makes new low but CVD doesn't.
    Bearish div: price makes new high but CVD doesn't.
    """
    df = df.copy()
    if "cvd_z" not in df.columns:
        df = cvd(df)

    price_high = df["high"].rolling(lookback, min_periods=3).max()
    price_low  = df["low"].rolling(lookback, min_periods=3).min()
    cvd_z_high = df["cvd_z"].rolling(lookback, min_periods=3).max()
    cvd_z_low  = df["cvd_z"].rolling(lookback, min_periods=3).min()

    # bearish: price at rolling high but CVD_z below its rolling high
    df["cvd_div_bear"] = (
        (df["high"] >= price_high * 0.999) &
        (df["cvd_z"] < cvd_z_high * 0.95)
    ).astype(float)

    # bullish: price at rolling low but CVD_z above its rolling low
    df["cvd_div_bull"] = (
        (df["low"] <= price_low * 1.001) &
        (df["cvd_z"] > cvd_z_low * 1.05)
    ).astype(float)

    return df


def volume_imbalance(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """Taker buy ratio over rolling window."""
    df = df.copy()
    buy_sum = df["tbb"].rolling(window, min_periods=3).sum()
    vol_sum = df["vol"].rolling(window, min_periods=3).sum()
    df["vimb"] = (buy_sum / vol_sum.replace(0, np.nan)).clip(0, 1).fillna(0.5)
    return df


def liquidation_proxy(df: pd.DataFrame, vol_mult: float = 3.0,
                      atr_mult: float = 2.0) -> pd.DataFrame:
    """Detect liquidation cascades via volume + ATR spikes."""
    df = df.copy()
    vol_mean = df["vol"].rolling(50, min_periods=10).mean()
    atr_mean = df["atr"].rolling(50, min_periods=10).mean() if "atr" in df.columns else None

    vol_spike = df["vol"] > vol_mean * vol_mult
    if atr_mean is not None:
        atr_spike = df["atr"] > atr_mean * atr_mult
        df["liq_proxy"] = (vol_spike & atr_spike).astype(float)
    else:
        df["liq_proxy"] = vol_spike.astype(float)

    return df


# ── TREND INDICATORS (SUPERTREND) ───────────────────────────

def supertrend(df: pd.DataFrame, multiplier: float, period: int) -> pd.DataFrame:
    """ATR-based trailing trend line + up/down state.

    Port do Supertrend freqtrade (FSupertrendStrategy), referência:
    https://github.com/freqtrade/freqtrade-strategies/issues/30

    Distinto do ``atr`` em :func:`indicators`: esse ATR usa SMA do True
    Range (SMA-``period``), mantendo a fórmula original da literatura de
    Supertrend. O ``atr`` do AURUM é EWM pra stops e sizing — não
    misturar, são usos diferentes.

    Params
    ------
    df         : OHLC com colunas 'high', 'low', 'close'. Não modifica df
                 in-place.
    multiplier : escala da banda (tipicamente 1–7).
    period     : janela do SMA do TR (tipicamente 7–21).

    Returns
    -------
    DataFrame aligned com df.index, colunas:
      - 'st'  : linha do Supertrend (float). Zero antes do warmup.
      - 'stx' : string {'up', 'down', ''} — direção da tendência. String
                vazia antes do warmup.
    """
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(df)

    # True Range (sem dependência do atr EWM do AURUM)
    prev_close = np.concatenate(([close[0]], close[:-1]))
    tr = np.maximum.reduce([
        high - low,
        np.abs(high - prev_close),
        np.abs(low - prev_close),
    ])
    # ATR = SMA(TR, period) — fórmula original do Supertrend
    atr_sma = pd.Series(tr).rolling(period, min_periods=period).mean().to_numpy()

    hl2 = (high + low) / 2.0
    basic_ub = hl2 + multiplier * atr_sma
    basic_lb = hl2 - multiplier * atr_sma

    final_ub = np.zeros(n, dtype=float)
    final_lb = np.zeros(n, dtype=float)
    st = np.zeros(n, dtype=float)

    # Loop sequencial — algoritmo tem dependência temporal (final_ub[i]
    # depende de final_ub[i-1]). Vetorização pura não captura isso.
    for i in range(period, n):
        if np.isnan(basic_ub[i]) or np.isnan(basic_lb[i]):
            continue
        final_ub[i] = (
            basic_ub[i]
            if (basic_ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1])
            else final_ub[i - 1]
        )
        final_lb[i] = (
            basic_lb[i]
            if (basic_lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1])
            else final_lb[i - 1]
        )

        prev_st = st[i - 1]
        prev_ub = final_ub[i - 1]
        prev_lb = final_lb[i - 1]
        if prev_st == prev_ub and close[i] <= final_ub[i]:
            st[i] = final_ub[i]
        elif prev_st == prev_ub and close[i] > final_ub[i]:
            st[i] = final_lb[i]
        elif prev_st == prev_lb and close[i] >= final_lb[i]:
            st[i] = final_lb[i]
        elif prev_st == prev_lb and close[i] < final_lb[i]:
            st[i] = final_ub[i]
        else:
            st[i] = 0.0

    stx = np.where(
        st > 0.0,
        np.where(close < st, "down", "up"),
        "",
    )
    return pd.DataFrame({"st": st, "stx": stx}, index=df.index)

