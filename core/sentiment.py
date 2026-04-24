"""
AURUM Finance — Sentiment Analysis Module (THOTH)

Fetches and scores on-chain/exchange sentiment data:
  - Funding Rate z-score (Binance Futures)
  - Open Interest delta
  - Long/Short Account Ratio

All data from Binance public API (no auth required).
"""
import logging
import threading
import time
from pathlib import Path
import numpy as np
import pandas as pd
import requests

log = logging.getLogger("THOTH")

# rate limit helper — lock makes the gap safe under ThreadPoolExecutor use
_last_req = 0.0
_REQ_GAP = 0.15  # 150ms between requests
_REQ_LOCK = threading.Lock()

# Shared session — reuses TCP/TLS connections across calls. requests.Session
# is thread-safe for basic GETs (urllib3 pool handles concurrency), which is
# what prewarm_sentiment_cache does under ThreadPoolExecutor.
_SESSION = requests.Session()
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
        df["time"] = pd.to_datetime(df["time"], errors="coerce")
        df = df.dropna(subset=["time"])
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


def _slice_partial_cached_history(
    df: pd.DataFrame | None,
    *,
    end_time_ms: int,
) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    end_ts = pd.to_datetime(end_time_ms, unit="ms")
    subset = df[df["time"] <= end_ts].sort_values("time").reset_index(drop=True)
    if subset.empty:
        return None
    return subset


def _fetch_binance_rows(url: str, params: dict, label: str) -> list[dict] | None:
    try:
        _rate_limit()
        resp = _SESSION.get(url, params=params, timeout=10)
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
    with _REQ_LOCK:
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
            funding_period_ms = 8 * 60 * 60 * 1000
            params["startTime"] = int(end_time_ms - max(limit - 1, 0) * funding_period_ms)
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
            cached_frame = _load_cached_frame("open_interest", symbol, period, cols)
            cached = _slice_cached_history(
                cached_frame,
                period,
                limit,
                end_time_ms,
            )
            if cached is not None:
                return cached
            if limit > 500:
                partial = _slice_partial_cached_history(cached_frame, end_time_ms=end_time_ms)
                if partial is not None:
                    return partial
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params: dict = {"symbol": symbol, "period": period, "limit": limit}
        # Bug 2 fix: when caller is running OOS/backtest with end_time_ms,
        # NEVER fetch without endTime. The Binance endpoint accepts endTime;
        # pass it so we get the historical window instead of the live tail
        # (which would be silent look-ahead).
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
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
        return merged.reset_index(drop=True) if merged is not None else None
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
            cached_frame = _load_cached_frame("long_short_ratio", symbol, period, cols)
            cached = _slice_cached_history(
                cached_frame,
                period,
                limit,
                end_time_ms,
            )
            if cached is not None:
                return cached
            if limit > 500:
                partial = _slice_partial_cached_history(cached_frame, end_time_ms=end_time_ms)
                if partial is not None:
                    return partial
        url = "https://fapi.binance.com/futures/data/globalLongShortAccountRatio"
        params: dict = {"symbol": symbol, "period": period, "limit": limit}
        # Bug 2 fix: propagate endTime to the live fetch so OOS/backtest
        # windows get the correct historical slice rather than the live tail.
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)
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
        return merged.reset_index(drop=True) if merged is not None else None
    except Exception as e:
        log.warning(f"LS ratio {symbol} error: {e}")
        return None


# ── SCORING ──────────────────────────────────────────────────

def funding_zscore(funding_df: pd.DataFrame, window: int = 30) -> pd.Series:
    """
    Z-score of funding rate over rolling window.
    Positive z = market overleveraged long.
    Negative z = market overleveraged short.

    Returns a Series indexed by the funding tick DatetimeIndex so that
    downstream temporal aligners (searchsorted on candle timestamps) work
    correctly. Returning a RangeIndex here collapses candles to positional
    alignment and fabricates signal across the backtest.
    """
    fr = funding_df["funding_rate"]
    roll_mean = fr.rolling(window, min_periods=5).mean()
    roll_std = fr.rolling(window, min_periods=5).std()
    z = (fr - roll_mean) / roll_std.replace(0, np.nan)
    z = z.fillna(0)
    if "time" in funding_df.columns:
        z.index = pd.to_datetime(funding_df["time"]).to_numpy()
    return z


def oi_delta_signal(oi_df: pd.DataFrame, price_df: pd.DataFrame,
                    window: int = 20, zscore_window: int = 200) -> pd.DataFrame:
    """
    OI change vs price change analysis — regime-adaptive z-score version.

    Bug 5 fix (2026-04-17): the previous absolute thresholds (OI ±5%, price
    ±1% over a 20-bar window) are regime-fragile. In the 2026 low-vol
    regime, only 1.8% of BTC observations clear |OI delta| > 5% — OI signal
    falls to 0 on 100% of trades, contributing nothing to the composite.

    Fix: score oi_delta and price_delta by their z-score over a longer
    rolling window (default 200 bars), with symmetric ±1σ/±2σ thresholds.
    Adapts to the prevailing regime so the signal fires when OI moves
    unusually relative to itself, not by a hardcoded percentage.

    Signal logic preserved (direction semantics):
      oi_up + px_dn : -1.0 (shorts accumulating — bearish continuation)
      oi_dn + px_up :  1.0 (short squeeze — bullish)
      oi_up + px_up :  0.3 (weak bullish — trend)
      oi_dn + px_dn : -0.3 (weak bearish — capitulation)

    Returns DataFrame with columns: oi_delta, price_delta, oi_signal.
    """
    price = price_df[["time", "close"]].copy()
    oi = oi_df[["time", "oi"]].copy()
    # Pandas 3.14 hardened merge_asof to reject datetime64 unit mismatches
    # (for example ns vs us). Normalize both sides explicitly so OI cannot
    # silently disappear in BRIDGEWATER due to a swallowed MergeError.
    price["time"] = pd.to_datetime(price["time"]).astype("datetime64[ns]")
    oi["time"] = pd.to_datetime(oi["time"]).astype("datetime64[ns]")
    merged = pd.merge_asof(
        price.sort_values("time"),
        oi.sort_values("time"),
        on="time",
    )

    merged["oi_delta"] = merged["oi"].pct_change(window).fillna(0)
    merged["price_delta"] = merged["close"].pct_change(window).fillna(0)

    min_periods = max(20, min(50, len(merged) // 4))
    oi_mean = merged["oi_delta"].rolling(zscore_window, min_periods=min_periods).mean()
    oi_std = merged["oi_delta"].rolling(zscore_window, min_periods=min_periods).std()
    px_mean = merged["price_delta"].rolling(zscore_window, min_periods=min_periods).mean()
    px_std = merged["price_delta"].rolling(zscore_window, min_periods=min_periods).std()

    oi_z = ((merged["oi_delta"] - oi_mean) / oi_std.replace(0, np.nan)).fillna(0).to_numpy()
    px_z = ((merged["price_delta"] - px_mean) / px_std.replace(0, np.nan)).fillna(0).to_numpy()

    # Symmetric ±1σ/±2σ thresholds on z-score; no asymmetry.
    oi_move_up = oi_z >= 1.0
    oi_move_dn = oi_z <= -1.0
    px_move_up = px_z >= 1.0
    px_move_dn = px_z <= -1.0

    signal = np.zeros(len(merged))
    signal = np.where(oi_move_up & px_move_dn, -1.0, signal)
    signal = np.where(oi_move_dn & px_move_up,  1.0, signal)
    signal = np.where(oi_move_up & px_move_up,  0.3, signal)
    signal = np.where(oi_move_dn & px_move_dn, -0.3, signal)

    merged["oi_signal"] = signal
    return merged


def ls_ratio_signal(ls_df: pd.DataFrame, window: int = 672) -> pd.Series:
    """
    Contrarian signal from Long/Short ratio (rolling z-score).

    Mechanism (Bug 3 fix — symmetric, regime-adaptive, non-overfit):
      - Compute z-score of the ratio over a rolling window (default 672 ticks
        = 1 week at 15m cadence). This adapts to the prevailing regime: a
        persistent bull market with LS > 1 is the new baseline, and the
        contrarian signal only fires on deviations from it.
      - Symmetric thresholds: ±2σ strong, ±1σ weak. No asymmetry toward one
        side (previous absolute thresholds 1.5/0.67 biased ~99% of signal
        bearish in crypto bull).

    Bug 1 fix: returns a Series indexed by the LS tick DatetimeIndex so
    that temporal aligners map candles to the correct historical value.

    Returns signal in [-1, +1]:
      positive = bullish (crowd is unusually short → contrarian long)
      negative = bearish (crowd is unusually long → contrarian short)
    """
    ratio = ls_df["ls_ratio"].astype(float)
    min_periods = max(10, min(50, len(ratio) // 4))
    roll_mean = ratio.rolling(window, min_periods=min_periods).mean()
    roll_std = ratio.rolling(window, min_periods=min_periods).std()
    z = (ratio - roll_mean) / roll_std.replace(0, np.nan)
    z = z.fillna(0).to_numpy(dtype=float)
    signal = np.where(z >  2.0, -1.0,
             np.where(z >  1.0, -0.5,
             np.where(z < -2.0,  1.0,
             np.where(z < -1.0,  0.5, 0.0))))
    if "time" in ls_df.columns:
        return pd.Series(signal, index=pd.to_datetime(ls_df["time"]).to_numpy())
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
