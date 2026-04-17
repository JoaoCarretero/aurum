"""AURUM — OHLCV local cache.

Transparent slice-from-disk layer that sits in front of core.data.fetch().
Keeps Binance klines prefetched by tools/prefetch.py in a per-symbol
pickle+gzip file under data/.cache/.

Design notes:
  - Cache format: pickle-gzip of a pandas DataFrame with the exact columns
    produced by fetch() (time, open, high, low, close, vol, tbb).
  - Reads return the LAST n_candles rows so backtests always look at the
    freshest window in the cache.
  - Writes merge the incoming frame with whatever is on disk, dedup by
    time, then write atomically (tmp + os.replace) — OneDrive-safe.
  - AURUM_NO_CACHE=1 bypasses reads only; writes always persist so an
    integrity run still updates the store.
"""
from __future__ import annotations

import gzip
import io
import json
import os
import time
from pathlib import Path
from typing import Optional

import pandas as pd

CACHE_DIR = Path("data") / ".cache"


def _path(symbol: str, interval: str, futures: bool) -> Path:
    market = "futures" if futures else "spot"
    return CACHE_DIR / f"{symbol}_{interval}_{market}.pkl.gz"


def reads_disabled() -> bool:
    """True when AURUM_NO_CACHE forces the fetcher to hit the live API."""
    return os.environ.get("AURUM_NO_CACHE", "").strip() not in ("", "0", "false", "False")


def _serialize_frame(df: pd.DataFrame) -> str:
    payload = {"frame": json.loads(df.to_json(orient="table", date_format="iso"))}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def load_frame(path: Path) -> Optional[pd.DataFrame]:
    """Load a cache dataframe from disk, returning None on corruption."""
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            payload = json.load(fh)
        frame = payload.get("frame")
        if frame is None:
            return None
        df = pd.read_json(io.StringIO(json.dumps(frame)), orient="table")
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=False)
        return df
    except Exception:
        return None


def read(symbol: str, interval: str, n_candles: int,
         futures: bool, end_time_ms: Optional[int] = None,
         max_age_seconds: Optional[float] = None) -> Optional[pd.DataFrame]:
    """Return the last n_candles from cache, or None if insufficient.

    If end_time_ms is provided, slice the cached frame to rows whose
    bar time is <= end_time_ms BEFORE taking the tail — enables retro
    OOS/holdout backtests without refetching.
    """
    if reads_disabled():
        return None
    p = _path(symbol, interval, futures)
    if not p.exists():
        return None
    if end_time_ms is None and max_age_seconds is not None:
        try:
            age_s = max(0.0, time.time() - os.path.getmtime(p))
        except OSError:
            return None
        if age_s > max_age_seconds:
            return None
    df = load_frame(p)
    if df is None:
        return None
    if end_time_ms is not None:
        cutoff = pd.Timestamp(end_time_ms, unit="ms")
        df = df[df["time"] <= cutoff]
    if len(df) < n_candles:
        return None
    return df.tail(n_candles).reset_index(drop=True)


def write(symbol: str, interval: str, df: pd.DataFrame,
          futures: bool) -> bool:
    """Merge df into the cached frame and persist atomically."""
    if df is None or df.empty:
        return False
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(symbol, interval, futures)
    existing = None
    if p.exists():
        existing = load_frame(p)
    if existing is not None and not existing.empty:
        merged = pd.concat([existing, df], ignore_index=True)
        merged = (merged.drop_duplicates("time")
                        .sort_values("time")
                        .reset_index(drop=True))
    else:
        merged = df.copy()
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            f.write(_serialize_frame(merged))
        os.replace(tmp, p)
        return True
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def info() -> dict:
    """Summary of cache contents (for status pills in the launcher)."""
    out = {"n_files": 0, "total_bytes": 0, "by_symbol": {}}
    if not CACHE_DIR.exists():
        return out
    for p in CACHE_DIR.glob("*_*_*.pkl.gz"):
        out["n_files"] += 1
        out["total_bytes"] += p.stat().st_size
        stem = p.name[:-len(".pkl.gz")]
        # Stem looks like BTCUSDT_15m_futures — split from the right so symbols
        # with underscores stay intact.
        rest, _, market = stem.rpartition("_")
        sym, _, interval = rest.rpartition("_")
        if sym:
            out["by_symbol"].setdefault(sym, []).append({
                "interval": interval,
                "market": market,
                "bytes": p.stat().st_size,
            })
    return out
