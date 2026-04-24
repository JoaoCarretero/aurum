"""Unit tests for tick_schedule.seconds_until_next_tick_boundary.

Aligns shadow/paper tick loops to the candle grid so every runner is in
the same phase (just after candle close + small settle delay) regardless
of when its process started. Before this, processes restarted at wall
time X ran ticks at X, X+tick_sec, X+2*tick_sec — whichever phase of the
candle X happened to land in was baked in for the whole run. Shadow and
paper ended up in different phases after the 2026-04-24 06:50 apt-daily
restart and the shadow missed the RENAISSANCE RENDERUSDT signal paper
caught.
"""
from __future__ import annotations

from tools.operations.tick_schedule import seconds_until_next_tick_boundary


def test_exactly_on_boundary_sleeps_post_close_delay():
    # now = 10:00:00 UTC = 1000 * 900 == boundary aligned to tick_sec=900
    now = 900_000.0
    assert seconds_until_next_tick_boundary(
        now, tick_sec=900, post_close_delay=60
    ) == 60.0


def test_within_post_close_window_targets_remainder_of_window():
    # now = 30s past boundary, post_close_delay=60 — 30s to target
    now = 900_000.0 + 30.0
    assert seconds_until_next_tick_boundary(
        now, tick_sec=900, post_close_delay=60
    ) == 30.0


def test_just_past_post_close_window_goes_to_next_cycle():
    # now = 60s past boundary (exactly at target); next target is
    # next boundary (+ 900s) plus post_close_delay (+60s) = 900s away.
    now = 900_000.0 + 60.0
    assert seconds_until_next_tick_boundary(
        now, tick_sec=900, post_close_delay=60
    ) == 900.0


def test_mid_candle_waits_until_next_boundary_plus_delay():
    # now = 90s past boundary (30s past target); need to wait to next
    # boundary (+810s) + delay (+60s) = 870s.
    now = 900_000.0 + 90.0
    assert seconds_until_next_tick_boundary(
        now, tick_sec=900, post_close_delay=60
    ) == 870.0


def test_almost_at_next_boundary_waits_1s_plus_delay():
    # 899s past boundary — 1s to next boundary + 60s delay = 61s
    now = 900_000.0 + 899.0
    assert seconds_until_next_tick_boundary(
        now, tick_sec=900, post_close_delay=60
    ) == 61.0


def test_zero_post_close_delay_still_hits_boundary():
    # With post_close_delay=0, right at boundary we should sleep to next.
    now = 900_000.0
    assert seconds_until_next_tick_boundary(
        now, tick_sec=900, post_close_delay=0
    ) == 900.0


def test_works_for_different_tick_sec():
    # tick_sec=300 (5min), post_close_delay=30
    # now at boundary+10s: target is boundary+30s, sleep 20s
    now = 300_000.0 + 10.0
    assert seconds_until_next_tick_boundary(
        now, tick_sec=300, post_close_delay=30
    ) == 20.0


def test_returns_non_negative():
    # Edge: exactly 1 microsecond past target — must not return negative
    now = 900_000.0 + 60.0 + 1e-9
    result = seconds_until_next_tick_boundary(
        now, tick_sec=900, post_close_delay=60
    )
    assert result > 0
    # Should be ~900s (next cycle), not a tiny sliver
    assert result > 899.0


def test_rejects_non_positive_tick_sec():
    import pytest
    with pytest.raises(ValueError, match="tick_sec"):
        seconds_until_next_tick_boundary(1000.0, tick_sec=0)
    with pytest.raises(ValueError, match="tick_sec"):
        seconds_until_next_tick_boundary(1000.0, tick_sec=-60)


def test_rejects_negative_post_close_delay():
    import pytest
    with pytest.raises(ValueError, match="post_close_delay"):
        seconds_until_next_tick_boundary(
            1000.0, tick_sec=900, post_close_delay=-1
        )


def test_rejects_post_close_delay_gte_tick_sec():
    """Contract: sleep must be bounded by one tick_sec cycle. A
    post_close_delay >= tick_sec would put the tick past the next
    boundary, violating that contract.
    """
    import pytest
    with pytest.raises(ValueError, match="post_close_delay"):
        seconds_until_next_tick_boundary(
            1000.0, tick_sec=900, post_close_delay=900
        )
    with pytest.raises(ValueError, match="post_close_delay"):
        seconds_until_next_tick_boundary(
            1000.0, tick_sec=900, post_close_delay=901
        )
