from __future__ import annotations

import pandas as pd

from tools.maintenance.bridgewater_cache_backfill import backfill_one, earliest_contiguous_ts


def test_earliest_contiguous_ts_ignores_older_isolated_block():
    df = pd.DataFrame(
        {
            "time": pd.to_datetime(
                [
                    "2026-04-01 00:00:00",
                    "2026-04-10 00:00:00",
                    "2026-04-10 00:15:00",
                    "2026-04-10 00:30:00",
                ]
            ),
            "oi": [1, 2, 3, 4],
            "oi_value": [1, 2, 3, 4],
        }
    )

    ts = earliest_contiguous_ts(
        "open_interest",
        "BTCUSDT",
        "15m",
        load_cached_frame=lambda *_args, **_kwargs: df,
    )

    assert ts == pd.Timestamp("2026-04-10 00:00:00")


def test_backfill_one_steps_until_no_new_rows():
    calls = []
    coverages = [
        {"rows": 10, "start": "2026-04-10"},
        {"rows": 20, "start": "2026-04-09"},
        {"rows": 25, "start": "2026-04-08"},
        {"rows": 25, "start": "2026-04-08"},
    ]

    def fake_fetch(symbol, *, period, limit, end_time_ms):
        calls.append((symbol, period, limit, end_time_ms))
        return pd.DataFrame()

    def fake_cached_coverage(*_args, **_kwargs):
        return coverages.pop(0)

    sleeps = []
    successes = backfill_one(
        "open_interest",
        "BTCUSDT",
        "15m",
        limit=5,
        max_iterations=5,
        fetch_open_interest_fn=fake_fetch,
        cached_coverage_fn=fake_cached_coverage,
        earliest_contiguous_ts_fn=lambda *_args, **_kwargs: pd.Timestamp("2026-04-10 00:00:00"),
        sleep_fn=lambda seconds: sleeps.append(seconds),
    )

    assert successes == 2
    assert len(calls) == 3
    assert sleeps == [0.3, 0.3]
