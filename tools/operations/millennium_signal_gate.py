"""Shared signal-timestamp helpers for MILLENNIUM shadow/paper.

Both runners consume the same operational scan, so de-dup keys and
"is this a live bar?" checks must stay identical.
"""
from __future__ import annotations

from datetime import datetime, timezone


def trade_key(trade: dict) -> tuple:
    """Stable dedup key: engine + symbol + signal timestamp."""
    return (
        str(trade.get("strategy") or "").upper(),
        str(trade.get("symbol") or "").upper(),
        trade.get("open_ts") or trade.get("timestamp"),
    )


def signal_timestamp(trade: dict):
    """Return the raw signal timestamp field used by MILLENNIUM."""
    return trade.get("open_ts") or trade.get("timestamp")


def parse_utc_ts(raw) -> datetime | None:
    if raw is None:
        return None
    try:
        if hasattr(raw, "to_pydatetime"):
            ts = raw.to_pydatetime()
        elif isinstance(raw, datetime):
            ts = raw
        else:
            s = str(raw).strip()
            if "T" not in s and " " in s:
                s = s.replace(" ", "T", 1)
            s = s.replace("Z", "+00:00")
            ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def signal_age_seconds(trade: dict, reference_ts=None) -> float | None:
    """Age of trade signal in seconds relative to reference_ts."""
    ts = parse_utc_ts(signal_timestamp(trade))
    if ts is None:
        return None
    ref = parse_utc_ts(reference_ts)
    if ref is None:
        ref = datetime.now(timezone.utc)
    return (ref - ts).total_seconds()


def is_live_signal(
    trade: dict,
    tick_sec: int,
    tolerance_mult: float = 3.0,
    reference_ts=None,
) -> bool:
    """True if the signal belongs to the most recent bar(s).

    Default tolerance 3× tick_sec = 45min for tick_sec=900. The earlier
    default of 2× was tight enough that a shadow/paper runner landing on
    the wrong side of a 15min candle boundary (tick 5min after close
    returns empty, next tick 20min later observes the signal at age 35min)
    rejected the signal as stale. 2026-04-24 incident: paper caught the
    RENAISSANCE RENDERUSDT signal at age 23min, 3/3 shadow runners
    dropped it at age 35min. 3× gives a 15min margin on each side of the
    candle without admitting hour-old signals.
    """
    age = signal_age_seconds(trade, reference_ts=reference_ts)
    if age is None:
        return False
    if age < -tick_sec:
        return False
    return age <= tolerance_mult * tick_sec
