from __future__ import annotations

import gzip
import json
import os
import time

import pandas as pd

from core import cache


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "time": pd.date_range("2026-01-01", periods=3, freq="1h"),
            "open": [1.0, 2.0, 3.0],
            "high": [1.1, 2.1, 3.1],
            "low": [0.9, 1.9, 2.9],
            "close": [1.0, 2.0, 3.0],
            "vol": [10.0, 20.0, 30.0],
            "tbb": [5.0, 10.0, 15.0],
        }
    )


def test_read_ignores_stale_live_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    p = cache._path("BTCUSDT", "1h", True)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"frame": json.loads(_frame().to_json(orient="table", date_format="iso"))}))
    stale = time.time() - 600
    os.utime(p, (stale, stale))

    assert cache.read("BTCUSDT", "1h", 3, True, max_age_seconds=60) is None


def test_read_allows_historical_slice_even_if_cache_file_is_old(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    p = cache._path("BTCUSDT", "1h", True)
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"frame": json.loads(_frame().to_json(orient="table", date_format="iso"))}))
    stale = time.time() - 600
    os.utime(p, (stale, stale))

    df = cache.read(
        "BTCUSDT",
        "1h",
        2,
        True,
        end_time_ms=int(pd.Timestamp("2026-01-01 02:00:00").timestamp() * 1000),
        max_age_seconds=60,
    )

    assert df is not None
    assert len(df) == 2
