"""Trade chart popup — matplotlib candlestick for PAPER/SHADOW trades.

Pure helpers (resolve_tf, tf_to_seconds, derive_candle_window,
build_marker_specs, fetch_binance_candles, parse_klines_to_df) are
unit-tested. Toplevel TradeChartPopup is smoke-only.

Design spec: docs/superpowers/specs/2026-04-24-cockpit-trade-history-chart-design.md
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from config.params import ENGINE_INTERVALS, INTERVAL


_ENGINE_ALIASES: dict[str, str] = {
    # Launcher/logger name → params.ENGINE_INTERVALS key
    "DE_SHAW": "DESHAW",
}


def resolve_tf(engine: str | None) -> str:
    """Resolve native TF for an engine, reading params.ENGINE_INTERVALS.

    Case-insensitive. Returns params.INTERVAL as fallback for None/empty
    or engines absent from ENGINE_INTERVALS (meta/arb/allocator engines).
    """
    if not engine:
        return INTERVAL
    upper = str(engine).upper()
    key = _ENGINE_ALIASES.get(upper, upper)
    return ENGINE_INTERVALS.get(key, INTERVAL)


_TF_SECONDS: dict[str, int] = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600,
    "8h": 28800, "12h": 43200, "1d": 86400,
}


def tf_to_seconds(tf: str) -> int:
    """Convert Binance interval string to seconds. Raises on unknown."""
    if tf not in _TF_SECONDS:
        raise ValueError(f"unknown TF: {tf}")
    return _TF_SECONDS[tf]


_MAX_WINDOW_CANDLES = 500
_MIN_WINDOW_CANDLES = 20
_WINDOW_PADDING_FACTOR = 1.6  # total window = duration × 1.6 → ~30% pad each side


def derive_candle_window(
    entry_ts: int,
    exit_ts: int | None,
    *,
    tf_sec: int,
    now_ts: int | None = None,
) -> tuple[int, int]:
    """Compute (start_ts, end_ts) for candle fetch.

    Trade duration drives window size; floors at 20 candles, caps at 500.
    Centers the trade in the window. Unix seconds.
    """
    if exit_ts is None:
        if now_ts is None:
            now_ts = int(time.time())
        end_anchor = now_ts
        duration_sec = max(tf_sec, now_ts - entry_ts)
    else:
        end_anchor = exit_ts
        duration_sec = max(tf_sec, exit_ts - entry_ts)

    duration_candles = max(1, duration_sec // tf_sec)
    # Window target: duration × 1.6, floored at MIN, capped at MAX.
    window_candles = max(_MIN_WINDOW_CANDLES,
                         int(duration_candles * _WINDOW_PADDING_FACTOR))
    window_candles = min(_MAX_WINDOW_CANDLES, window_candles)

    pad_candles = (window_candles - duration_candles) // 2
    if pad_candles >= 0:
        pad_sec = pad_candles * tf_sec
        start = entry_ts - pad_sec
        end = end_anchor + pad_sec
    else:
        # Trade exceeds cap (>500 candles): center the cap around the trade mid.
        mid = (entry_ts + end_anchor) // 2
        half = (window_candles * tf_sec) // 2
        start = mid - half
        end = mid + half
    return int(start), int(end)


def _ts_to_unix(ts: Any) -> int | None:
    """Best-effort ISO8601 → unix seconds."""
    if ts is None:
        return None
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


def build_marker_specs(trade: dict, *, tf_sec: int) -> list[dict[str, Any]]:
    """Build a list of marker specs for matplotlib overlay.

    Kinds: "entry" (yellow line), "stop" (red dashed), "target" (green
    dashed), "exit" (amber ▼ if closed), "current" (green ● if LIVE).
    Missing levels (zero/None) are omitted.
    """
    specs: list[dict] = []

    entry = trade.get("entry")
    stop = trade.get("stop")
    target = trade.get("target")

    if entry:
        specs.append({"kind": "entry", "price": float(entry),
                      "style": "line", "color": "#FFB000", "linewidth": 1.2})
    if stop:
        specs.append({"kind": "stop", "price": float(stop),
                      "style": "dashed", "color": "#FF4444", "linewidth": 1.0})
    if target:
        specs.append({"kind": "target", "price": float(target),
                      "style": "dashed", "color": "#44FF88", "linewidth": 1.0})

    if trade.get("result") == "LIVE":
        cur_px = trade.get("exit_p") or trade.get("entry")
        if cur_px:
            specs.append({"kind": "current", "price": float(cur_px),
                          "style": "scatter", "marker": "o",
                          "color": "#44FF88", "size": 100})
    else:
        exit_p = trade.get("exit_p")
        if exit_p:
            entry_ts = _ts_to_unix(trade.get("timestamp"))
            duration = int(trade.get("duration", 0) or 0)
            exit_ts = (entry_ts + duration * tf_sec) if entry_ts else None
            specs.append({"kind": "exit", "price": float(exit_p),
                          "timestamp": exit_ts,
                          "style": "scatter", "marker": "v",
                          "color": "#FFB000", "size": 120})
    return specs


def parse_klines_to_df(klines: list[list]) -> pd.DataFrame:
    """Parse Binance fapi/v1/klines response into mplfinance-ready DF."""
    if not klines:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    rows = []
    index = []
    for k in klines:
        # [open_ts_ms, O, H, L, C, V, close_ts, ...]
        index.append(pd.to_datetime(int(k[0]), unit="ms", utc=True))
        rows.append({
            "Open": float(k[1]),
            "High": float(k[2]),
            "Low": float(k[3]),
            "Close": float(k[4]),
            "Volume": float(k[5]),
        })
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(index, name="Date"))
    return df


_BINANCE_FAPI = "https://fapi.binance.com/fapi/v1/klines"
_FETCH_TIMEOUT_SEC = 6.0


def fetch_binance_candles(
    symbol: str,
    tf: str,
    *,
    start_ts: int,
    end_ts: int,
    limit: int = 500,
) -> pd.DataFrame:
    """Fetch candles from Binance USDT-M public klines. Returns empty
    DataFrame on any error (timeout/HTTP/parse)."""
    params = urllib.parse.urlencode({
        "symbol": symbol.upper(),
        "interval": tf,
        "startTime": start_ts * 1000,
        "endTime": end_ts * 1000,
        "limit": min(limit, 1500),
    })
    url = f"{_BINANCE_FAPI}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=_FETCH_TIMEOUT_SEC) as resp:
            body = resp.read()
        data = json.loads(body)
        if not isinstance(data, list):
            return parse_klines_to_df([])
        return parse_klines_to_df(data)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError,
            OSError, ValueError, json.JSONDecodeError):
        return parse_klines_to_df([])


# TradeChartPopup class added in Task 5 below.
