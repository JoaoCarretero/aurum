"""
AURUM Finance — Sentiment Analysis Module (THOTH)

Fetches and scores on-chain/exchange sentiment data:
  - Funding Rate z-score (Binance Futures)
  - Open Interest delta
  - Long/Short Account Ratio

All data from Binance public API (no auth required).
"""
import logging
import time
import numpy as np
import pandas as pd

log = logging.getLogger("THOTH")

# rate limit helper
_last_req = 0.0
_REQ_GAP = 0.15  # 150ms between requests


def _rate_limit():
    global _last_req
    elapsed = time.time() - _last_req
    if elapsed < _REQ_GAP:
        time.sleep(_REQ_GAP - elapsed)
    _last_req = time.time()


def fetch_funding_rate(symbol: str, limit: int = 100,
                       end_time_ms: int | None = None) -> pd.DataFrame | None:
    """Fetch historical funding rate from Binance Futures.

    If end_time_ms is provided, the API returns funding rates ending at that
    instant — required for OOS/backtest reproducibility. Without it, the API
    returns the most recent `limit` rates ending NOW, introducing look-ahead.
    """
    try:
        import requests
        _rate_limit()
        url = "https://fapi.binance.com/fapi/v1/fundingRate"
        params: dict = {"symbol": symbol, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            log.warning(f"funding rate {symbol}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        if not data:
            return None
        df = pd.DataFrame(data)
        df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms")
        df["fundingRate"] = df["fundingRate"].astype(float)
        df = df.rename(columns={"fundingTime": "time", "fundingRate": "funding_rate"})
        return df[["time", "funding_rate"]].sort_values("time").reset_index(drop=True)
    except Exception as e:
        log.warning(f"funding rate {symbol} error: {e}")
        return None


def fetch_open_interest(symbol: str, period: str = "15m", limit: int = 200,
                        end_time_ms: int | None = None) -> pd.DataFrame | None:
    """Fetch Open Interest history from Binance Futures.

    If end_time_ms is provided, returns the `limit` observations ending at
    that instant — required for OOS/backtest. Without it, returns most
    recent observations ending NOW (look-ahead in backtest).
    """
    try:
        import requests
        _rate_limit()
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params: dict = {"symbol": symbol, "period": period, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            log.warning(f"OI {symbol}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        if not data:
            return None
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["sumOpenInterest"] = df["sumOpenInterest"].astype(float)
        df["sumOpenInterestValue"] = df["sumOpenInterestValue"].astype(float)
        df = df.rename(columns={
            "timestamp": "time",
            "sumOpenInterest": "oi",
            "sumOpenInterestValue": "oi_value",
        })
        return df[["time", "oi", "oi_value"]].sort_values("time").reset_index(drop=True)
    except Exception as e:
        log.warning(f"OI {symbol} error: {e}")
        return None


def fetch_long_short_ratio(symbol: str, period: str = "15m",
                           limit: int = 200,
                           end_time_ms: int | None = None) -> pd.DataFrame | None:
    """Fetch global Long/Short Account Ratio from Binance Futures.

    If end_time_ms is provided, returns the `limit` observations ending at
    that instant — required for OOS/backtest. Without it, returns live data
    (look-ahead in backtest).
    """
    try:
        import requests
        _rate_limit()
        url = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
        params: dict = {"symbol": symbol, "period": period, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            log.warning(f"LS ratio {symbol}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        if not data:
            return None
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["longShortRatio"] = df["longShortRatio"].astype(float)
        df["longAccount"] = df["longAccount"].astype(float)
        df["shortAccount"] = df["shortAccount"].astype(float)
        df = df.rename(columns={
            "timestamp": "time",
            "longShortRatio": "ls_ratio",
            "longAccount": "long_pct",
            "shortAccount": "short_pct",
        })
        return df[["time", "ls_ratio", "long_pct", "short_pct"]].sort_values("time").reset_index(drop=True)
    except Exception as e:
        log.warning(f"LS ratio {symbol} error: {e}")
        return None


# ── SCORING ──────────────────────────────────────────────────

def funding_zscore(funding_df: pd.DataFrame, window: int = 30) -> pd.Series:
    """
    Z-score of funding rate over rolling window.
    Positive z = market overleveraged long.
    Negative z = market overleveraged short.
    """
    fr = funding_df["funding_rate"]
    roll_mean = fr.rolling(window, min_periods=5).mean()
    roll_std = fr.rolling(window, min_periods=5).std()
    z = (fr - roll_mean) / roll_std.replace(0, np.nan)
    return z.fillna(0)


def oi_delta_signal(oi_df: pd.DataFrame, price_df: pd.DataFrame,
                    window: int = 20) -> pd.DataFrame:
    """
    OI change vs price change analysis.
    Returns DataFrame with columns: oi_delta, price_delta, oi_signal
    """
    merged = pd.merge_asof(
        price_df[["time", "close"]].sort_values("time"),
        oi_df[["time", "oi"]].sort_values("time"),
        on="time",
    )

    merged["oi_delta"] = merged["oi"].pct_change(window).fillna(0)
    merged["price_delta"] = merged["close"].pct_change(window).fillna(0)

    # OI up + price down = shorts accumulating (bearish continuation)
    # OI down + price up = short squeeze (bullish)
    signal = np.zeros(len(merged))
    oi_up = merged["oi_delta"] > 0.05
    oi_dn = merged["oi_delta"] < -0.05
    px_up = merged["price_delta"] > 0.01
    px_dn = merged["price_delta"] < -0.01

    signal = np.where(oi_up & px_dn, -1.0, signal)   # bearish
    signal = np.where(oi_dn & px_up,  1.0, signal)    # bullish (squeeze)
    signal = np.where(oi_up & px_up,  0.3, signal)    # weak bullish (trend)
    signal = np.where(oi_dn & px_dn, -0.3, signal)    # weak bearish (capitulation)

    merged["oi_signal"] = signal
    return merged


def ls_ratio_signal(ls_df: pd.DataFrame) -> pd.Series:
    """
    Contrarian signal from Long/Short ratio.
    Returns signal: positive = bullish (crowd is short), negative = bearish (crowd is long).
    """
    ratio = ls_df["ls_ratio"]
    # crowd too long → bearish
    # crowd too short → bullish
    signal = np.where(ratio > 2.0, -1.0,
             np.where(ratio > 1.5, -0.5,
             np.where(ratio < 0.5,  1.0,
             np.where(ratio < 0.67, 0.5, 0.0))))
    return pd.Series(signal, index=ls_df.index)


def composite_sentiment(funding_z: float, oi_sig: float, ls_sig: float,
                        w_funding: float = 0.4,
                        w_oi: float = 0.3,
                        w_ls: float = 0.3) -> float:
    """
    Weighted composite sentiment score.
    Returns: float in [-1, 1]
      > 0 = bullish sentiment signal
      < 0 = bearish sentiment signal
    """
    # funding z-score → contrarian: positive z = overleveraged long = bearish
    funding_sig = np.clip(-funding_z / 2.0, -1.0, 1.0)

    score = w_funding * funding_sig + w_oi * oi_sig + w_ls * ls_sig
    return float(np.clip(score, -1.0, 1.0))
