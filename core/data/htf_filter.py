"""
AURUM — Generic HTF alignment filter for all engines.

Provides a simple function that checks if the higher timeframe
agrees with a proposed trade direction. Used as a veto layer.

Usage in any engine's scan loop:
    from core.htf_filter import htf_agrees, prepare_htf_context

    # Once before scanning:
    htf_ctx = prepare_htf_context(all_dfs, htf_interval="4h")

    # Per trade:
    if not htf_agrees(htf_ctx, symbol, idx, direction, df):
        vetos["htf_veto"] += 1
        continue
"""
import logging
import pandas as pd
from config.params import _TF_MINUTES

log = logging.getLogger("HTF_FILTER")


def prepare_htf_context(all_dfs_ltf: dict[str, pd.DataFrame],
                        htf_dfs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Merge HTF struct/macro into each LTF dataframe.

    Returns dict[symbol] = LTF dataframe with htf_struct, htf_macro columns.
    """
    from core.htf import prepare_htf

    ctx: dict[str, pd.DataFrame] = {}
    for sym, df_ltf in all_dfs_ltf.items():
        df_htf = htf_dfs.get(sym)
        if df_htf is None or len(df_htf) < 50:
            ctx[sym] = None
            continue

        # Prepare HTF indicators
        try:
            htf_prepared = prepare_htf(df_htf.copy(), htf_interval="4h")
        except Exception as e:
            log.debug(f"HTF prepare failed for {sym}: {e}")
            ctx[sym] = None
            continue

        # Merge HTF struct/macro into LTF via merge_asof
        htf_cols = htf_prepared[["time", "trend_struct", "htf_macro", "slope200"]].copy()
        htf_cols = htf_cols.rename(columns={
            "trend_struct": "htf_struct",
            "htf_macro": "htf_macro",
            "slope200": "htf_slope200",
        })
        # Shift HTF time forward by one bar to prevent look-ahead
        mins = _TF_MINUTES.get("4h", 240)
        htf_cols["time"] = (htf_cols["time"] + pd.Timedelta(minutes=mins)).astype("datetime64[ms]")

        df_merged = df_ltf.copy()
        df_merged["time"] = df_merged["time"].astype("datetime64[ms]")
        df_merged = pd.merge_asof(
            df_merged.sort_values("time").reset_index(drop=True),
            htf_cols.sort_values("time").reset_index(drop=True),
            on="time", direction="backward",
        )
        df_merged["htf_struct"] = df_merged["htf_struct"].fillna("NEUTRAL")
        df_merged["htf_macro"] = df_merged["htf_macro"].fillna("CHOP")
        df_merged["htf_slope200"] = df_merged["htf_slope200"].fillna(0.0)

        ctx[sym] = df_merged

    return ctx


def htf_agrees(htf_ctx: dict, symbol: str, idx: int,
               direction: str) -> bool:
    """Check if HTF trend agrees with proposed trade direction.

    Rules:
    - BULLISH trade: HTF struct must be UP or NEUTRAL (not DOWN)
    - BEARISH trade: HTF struct must be DOWN or NEUTRAL (not UP)
    - If no HTF data: pass (don't veto)

    This is a soft filter — NEUTRAL passes both ways.
    """
    df = htf_ctx.get(symbol)
    if df is None:
        return True  # no HTF data = no veto

    if idx >= len(df):
        return True

    htf_struct = str(df["htf_struct"].iloc[idx])

    if direction == "BULLISH" and htf_struct == "DOWN":
        return False
    if direction == "BEARISH" and htf_struct == "UP":
        return False
    return True


def htf_contrarian(htf_ctx: dict, symbol: str, idx: int,
                   direction: str) -> bool:
    """Contrarian HTF filter: ALLOW trades that go AGAINST the HTF trend.

    Logic: if HTF is stretched in one direction, a contrarian reversal
    trade in the opposite direction is MORE likely to succeed.

    Rules:
    - BULLISH trade: HTF must be DOWN or NEUTRAL (buying into weakness)
    - BEARISH trade: HTF must be UP or NEUTRAL (selling into strength)
    - If no HTF data: pass
    """
    df = htf_ctx.get(symbol)
    if df is None or idx >= len(df):
        return True

    htf_struct = str(df["htf_struct"].iloc[idx])

    # Contrarian: allow trades AGAINST the HTF trend
    if direction == "BULLISH" and htf_struct == "UP":
        return False  # don't buy into strength — that's trend-following
    if direction == "BEARISH" and htf_struct == "DOWN":
        return False  # don't sell into weakness — that's trend-following
    return True


def htf_macro(htf_ctx: dict, symbol: str, idx: int) -> str:
    """Get the HTF macro regime for a symbol at a given index."""
    df = htf_ctx.get(symbol)
    if df is None or idx >= len(df):
        return "CHOP"
    return str(df["htf_macro"].iloc[idx])
