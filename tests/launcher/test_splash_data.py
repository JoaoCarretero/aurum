"""Unit tests for pure data readers used by SplashScreen."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from launcher_support.screens.splash_data import read_last_session


def _write_index(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "index.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def test_read_last_session_returns_most_recent(tmp_path):
    idx = _write_index(tmp_path, [
        {"engine": "citadel", "timestamp": "2026-04-20T10:00:00",
         "n_trades": 3, "pnl": 120.0, "sharpe": 1.4},
        {"engine": "jump", "timestamp": "2026-04-21T15:30:00",
         "n_trades": 7, "pnl": 420.0, "sharpe": 2.1},
        {"engine": "citadel", "timestamp": "2026-04-19T09:00:00",
         "n_trades": 2, "pnl": -30.0, "sharpe": 0.5},
    ])
    result = read_last_session(idx)
    assert result is not None
    assert result["engine"] == "jump"
    assert result["timestamp"] == "2026-04-21T15:30:00"
    assert result["n_trades"] == 7
    assert result["pnl"] == 420.0


def test_read_last_session_missing_file_returns_none(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert read_last_session(missing) is None


def test_read_last_session_malformed_json_returns_none(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert read_last_session(p) is None


def test_read_last_session_empty_list_returns_none(tmp_path):
    idx = _write_index(tmp_path, [])
    assert read_last_session(idx) is None


def test_read_last_session_skips_rows_without_timestamp(tmp_path):
    idx = _write_index(tmp_path, [
        {"engine": "citadel", "n_trades": 1, "pnl": 50.0},
        {"engine": "jump", "timestamp": "2026-04-21T15:30:00",
         "n_trades": 7, "pnl": 420.0},
    ])
    result = read_last_session(idx)
    assert result is not None
    assert result["engine"] == "jump"


def test_read_last_session_skips_rows_with_unparseable_timestamp(tmp_path):
    idx = _write_index(tmp_path, [
        {"engine": "bad", "timestamp": "not-a-date", "n_trades": 1},
        {"engine": "jump", "timestamp": "2026-04-21T15:30:00", "n_trades": 7, "pnl": 420.0},
    ])
    result = read_last_session(idx)
    assert result is not None
    assert result["engine"] == "jump"
