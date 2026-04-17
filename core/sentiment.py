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
from pathlib import Path
import numpy as np
import pandas as pd

log = logging.getLogger("THOTH")

# rate limit helper
_last_req = 0.0
_REQ_GAP = 0.15  # 150ms between requests
_SENTIMENT_CACHE_DIR = Path("data/sentiment")
_PERIOD_MS = {
    "5m": 5 * 60 * 1000,
    "15m": 15 * 60 * 1000,
    "30m": 30 * 60 * 1000,
    "1h": 60 * 60 * 1000,
    "2h": 2 * 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "6h": 6 * 60 * 60 * 1000,
    "12h": 12 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}


def _cache_path(kind: str, symbol: str, period: str) -> Path:
    return _SENTIMENT_CACHE_DIR / kind / f"{symbol}_{period}.csv"


def _load_cached_frame(kind: str, symbol: str, period: str,
                       columns: list[str]) -> pd.DataFrame | None:
    path = _cache_path(kind, symbol, period)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if "time" not in df.columns:
            return None
        df["time"] = pd.to_datetime(df["time"])
        missing = [col for col in columns if col not in df.columns]
        if missing:
            return None
        return df[columns].sort_values("time").drop_duplicates("time").reset_index(drop=True)
    except Exception as e:
        log.warning(f"{kind} cache {symbol} load error: {e}")
        return None


def cached_coverage(kind: str, symbol: str, period: str) -> dict[str, object] | None:
    columns_by_kind = {
        "open_interest": ["time", "oi", "oi_value"],
        "long_short_ratio": ["time", "ls_ratio", "long_pct", "short_pct"],
    }
    cols = columns_by_kind.get(kind)
    if cols is None:
        return None
    df = _load_cached_frame(kind, symbol, period, cols)
    if df is None or df.empty:
        return None
    return {
        "rows": int(len(df)),
        "start": df["time"].min().isoformat(),
        "end": df["time"].max().isoformat(),
    }


def _persist_cached_frame(kind: str, symbol: str, period: str, df: pd.DataFrame) -> None:
    path = _cache_path(kind, symbol, period)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = df.copy()
        out["time"] = pd.to_datetime(out["time"])
        out = out.sort_values("time").drop_duplicates("time").reset_index(drop=True)
        out.to_csv(path, index=False)
    except Exception as e:
        log.warning(f"{kind} cache {symbol} write error: {e}")


def _merge_with_cache(kind: str, symbol: str, period: str,
                      fresh_df: pd.DataFrame | None,
                      columns: list[str]) -> pd.DataFrame | None:
    cached = _load_cached_frame(kind, symbol, period, columns)
    if fresh_df is None or fresh_df.empty:
        return cached
    merged = fresh_df[columns]
    if cached is not None and not cached.empty:
        merged = pd.concat([cached, fresh_df[columns]], ignore_index=True)
    merged["time"] = pd.to_datetime(merged["time"])
    merged = merged.sort_values("time").drop_duplicates("time").reset_index(drop=True)
    _persist_cached_frame(kind, symbol, period, merged)
    return merged


def _slice_cached_history(df: pd.DataFrame | None, period: str, limit: int,
                          end_time_ms: int) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    period_ms = _PERIOD_MS.get(period)
    if period_ms is None:
        return None
    end_ts = pd.to_datetime(end_time_ms, unit="ms")
    window_start_ms = end_time_ms - max(limit - 1, 0) * period_ms
    window_start_ts = pd.to_datetime(window_start_ms, unit="ms")
    subset = df[df["time"] <= end_ts].sort_values("time").tail(limit).reset_index(drop=True)
    if len(subset) < limit:
        return None
    first_ts = subset["time"].iloc[0]
    if first_ts > window_start_ts:
        return None
    return subset


def _fetch_binance_rows(url: str, params: dict, label: str) -> list[dict] | None:
    try:
        import requests
        _rate_limit()
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            log.warning(f"{label}: HTTP {resp.status_code}")
            return None
        data = resp.json()
        if not data:
            return None
        return data
    except Exception as e:
        log.warning(f"{label} error: {e}")
        return None


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
        url = "https://fapi.binance.com/fapi/v1/fundingRate"
        params: dict = {"symbol": symbol, "limit": limit}
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
        data = _fetch_binance_rows(url, params, f"funding rate {symbol}")
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
        cols = ["time", "oi", "oi_value"]
        if end_time_ms is not None:
            cached = _slice_cached_history(
                _load_cached_frame("open_interest", symbol, period, cols),
                period,
                limit,
                end_time_ms,
            )
            if cached is not None:
                return cached
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params: dict = {"symbol": symbol, "period": period, "limit": limit}
        data = _fetch_binance_rows(url, params, f"OI {symbol}")
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
        merged = _merge_with_cache(
            "open_interest",
            symbol,
            period,
            df[cols].sort_values("time").reset_index(drop=True),
            cols,
        )
        if end_time_ms is not None:
            return _slice_cached_history(merged, period, limit, end_time_ms)
        return merged.tail(limit).reset_index(drop=True) if merged is not None else None
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
        cols = ["time", "ls_ratio", "long_pct", "short_pct"]
        if end_time_ms is not None:
            cached = _slice_cached_history(
                _load_cached_frame("long_short_ratio", symbol, period, cols),
                period,
                limit,
                end_time_ms,
            )
            if cached is not None:
                return cached
        url = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
        params: dict = {"symbol": symbol, "period": period, "limit": limit}
        data = _fetch_binance_rows(url, params, f"LS ratio {symbol}")
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
        merged = _merge_with_cache(
            "long_short_ratio",
            symbol,
            period,
            df[cols].sort_values("time").reset_index(drop=True),
            cols,
        )
        if end_time_ms is not None:
            return _slice_cached_history(merged, period, limit, end_time_ms)
        return merged.tail(limit).reset_index(drop=True) if merged is not None else None
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
