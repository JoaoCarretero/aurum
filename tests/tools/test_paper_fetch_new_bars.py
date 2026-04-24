"""Regression: `_fetch_new_bars` must filter out bars older than since_iso
regardless of tz-awareness of the inputs.

Bug 2026-04-24: standalone renaissance_paper wrote trades with
``exit_at < entry_at`` (e.g. entry 15:46, exit 10:45 UTC same day). Root
cause: `since_iso` from paper runner is tz-aware ISO (wall-clock entry),
`df["time"]` from Binance klines is tz-naive pandas Timestamp. The
comparison raised TypeError which the old `try/except: pass` swallowed
silently, disabling the filter and leaking all 20 historical bars into
`check_exits` — the first target-hit in history closed the position.

These tests pin the tz-normalisation so the filter never silently drops.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd


def _mk_df(times: list[datetime]) -> pd.DataFrame:
    """Build a minimal OHLCV df with the given times (tz-naive, matching
    core.data.fetch output shape)."""
    return pd.DataFrame({
        "time": pd.to_datetime(times),
        "open":  [1.0] * len(times),
        "high":  [2.0] * len(times),
        "low":   [0.5] * len(times),
        "close": [1.5] * len(times),
        "vol":   [100.0] * len(times),
        "tbb":   [50.0] * len(times),
    })


def test_fetch_new_bars_filters_tz_aware_since(monkeypatch):
    """Bug 2026-04-24 repro: tz-aware since_iso MUST filter historical bars
    instead of silently returning all 20.
    """
    from tools.operations import _paper_runner as pr

    # 20 candles of 15m, latest at 17:00 UTC, oldest at 12:15 UTC
    t_now = datetime(2026, 4, 24, 17, 0)
    times = [t_now - timedelta(minutes=15 * i) for i in range(19, -1, -1)]
    df = _mk_df(times)

    monkeypatch.setattr(pr, "core_fetch", lambda *a, **kw: df, raising=False)
    # Patch the nested import in _fetch_new_bars
    import core.data as core_data
    monkeypatch.setattr(core_data, "fetch", lambda *a, **kw: df)

    # Position opened at 15:46 UTC wall-clock (tz-aware)
    since_iso = "2026-04-24T15:46:00.114929+00:00"
    bars = pr._fetch_new_bars("OPUSDT", since_iso)

    # Should return ONLY bars strictly after 15:46 → 16:00, 16:15, 16:30, 16:45, 17:00 = 5
    assert len(bars) == 5, (
        f"expected 5 bars strictly after 15:46, got {len(bars)}. "
        f"Pre-fix this returned 20 because the tz-naive vs tz-aware "
        f"comparison raised TypeError and the old try/except: pass "
        f"silently disabled the filter."
    )
    for b in bars:
        assert b["time"] > "2026-04-24T15:46:00", (
            f"bar {b['time']} leaked through the since-filter"
        )


def test_fetch_new_bars_filters_tz_naive_since(monkeypatch):
    """After first successful fetch, since_iso is set to a bar's own
    tz-naive isoformat — the filter must still work."""
    from tools.operations import _paper_runner as pr
    import core.data as core_data

    t_now = datetime(2026, 4, 24, 17, 0)
    times = [t_now - timedelta(minutes=15 * i) for i in range(5, -1, -1)]
    df = _mk_df(times)
    monkeypatch.setattr(core_data, "fetch", lambda *a, **kw: df)

    # Simulate "last bar seen" as tz-naive ISO (as `.isoformat()` on
    # pandas.Timestamp produces).
    since_iso = "2026-04-24T16:30:00"  # bar times are 15:45..17:00
    bars = pr._fetch_new_bars("OPUSDT", since_iso)
    assert len(bars) == 2  # 16:45 and 17:00
    assert bars[0]["time"].startswith("2026-04-24T16:45")
    assert bars[1]["time"].startswith("2026-04-24T17:00")


def test_fetch_new_bars_returns_empty_on_parse_failure(monkeypatch, caplog):
    """Unparseable since_iso must return EMPTY (safe) rather than leak all
    20 bars (the pre-fix catastrophe)."""
    from tools.operations import _paper_runner as pr
    import core.data as core_data

    times = [datetime(2026, 4, 24, 16, 0) + timedelta(minutes=15 * i) for i in range(3)]
    monkeypatch.setattr(core_data, "fetch", lambda *a, **kw: _mk_df(times))

    bars = pr._fetch_new_bars("OPUSDT", since_iso="not-a-valid-timestamp")
    assert bars == []


def test_fetch_new_bars_millennium_shares_same_tz_fix(monkeypatch):
    """Millennium paper runner carries the same bug (same code) — fix must
    cover both paths."""
    from tools.operations import millennium_paper as mp
    import core.data as core_data

    t_now = datetime(2026, 4, 24, 17, 0)
    times = [t_now - timedelta(minutes=15 * i) for i in range(19, -1, -1)]
    monkeypatch.setattr(core_data, "fetch", lambda *a, **kw: _mk_df(times))

    since_iso = "2026-04-24T15:46:00.109616+00:00"
    bars = mp._fetch_new_bars("OPUSDT", since_iso)
    assert len(bars) == 5
