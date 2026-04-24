"""Candle-aligned tick scheduling for shadow/paper runners.

Before this module, tick loops slept ``tick_sec`` between iterations, so
a process that booted in the wrong phase of the candle grid stayed in
that phase forever. Shadow and paper ended up out of sync after the
2026-04-24 06:50 unattended-upgrades restart and shadow missed the
RENAISSANCE RENDERUSDT signal paper caught — shadow ran its tick 5min
past candle close (scan empty), then 20min later observed the signal at
age 35min and filtered it as STALE.

Aligning every tick to the UTC candle grid plus a small settle delay
collapses all runners into the same phase within one cycle.
"""
from __future__ import annotations

import math


def seconds_until_next_tick_boundary(
    now_ts: float,
    tick_sec: int,
    post_close_delay: float = 60.0,
) -> float:
    """Seconds to sleep until the next candle-aligned tick.

    The candle grid is UTC-aligned at multiples of ``tick_sec`` relative
    to the epoch. The target tick time is ``boundary + post_close_delay``
    for the nearest boundary that hasn't yet been reached. Runs that
    already passed the current boundary's target roll to the next
    boundary — this keeps the sleep bounded by one ``tick_sec`` cycle.

    Returns a strictly positive float.
    """
    if tick_sec <= 0:
        raise ValueError(f"tick_sec must be > 0, got {tick_sec!r}")
    if post_close_delay < 0:
        raise ValueError(
            f"post_close_delay must be >= 0, got {post_close_delay!r}"
        )
    if post_close_delay >= tick_sec:
        raise ValueError(
            f"post_close_delay ({post_close_delay}) must be < tick_sec "
            f"({tick_sec}) so sleep stays bounded by one cycle"
        )
    boundary = math.floor(now_ts / tick_sec) * tick_sec
    target = boundary + post_close_delay
    if target <= now_ts:
        target = boundary + tick_sec + post_close_delay
    return target - now_ts
