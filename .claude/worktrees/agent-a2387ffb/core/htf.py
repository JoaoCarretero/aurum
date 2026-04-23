"""AURUM — Multi-timeframe: HTF preparation and merge."""
import logging
import pandas as pd
from config.params import *
from config.params import _tf_params, _TF_MINUTES
from core.indicators import indicators, swing_structure, omega
from core.signals import score_omega

log = logging.getLogger("CITADEL")

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

def prepare_htf(df_htf: pd.DataFrame, htf_interval: str = "4h") -> pd.DataFrame:
    # Indicators/signals use module-level copies from `from config.params import *`,
    # so we must patch the consumer modules directly for HTF-specific params.
    import core.indicators as _ind
    import core.signals as _sig
    _saved = (_ind.SLOPE_N, _ind.PIVOT_N, _sig.CHOP_S21, _sig.CHOP_S200, _sig.MIN_STOP_PCT)
    _p = _tf_params(htf_interval)
    _ind.SLOPE_N = _p["slope_n"]; _ind.PIVOT_N = _p["pivot_n"]
    _sig.CHOP_S21 = _p["chop_s21"]; _sig.CHOP_S200 = _p["chop_s200"]
    _sig.MIN_STOP_PCT = _p["min_stop_pct"]
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
        _ind.SLOPE_N, _ind.PIVOT_N, _sig.CHOP_S21, _sig.CHOP_S200, _sig.MIN_STOP_PCT = _saved
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

