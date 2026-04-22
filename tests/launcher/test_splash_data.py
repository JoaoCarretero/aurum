"""Unit tests for pure data readers used by SplashScreen."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from launcher_support.screens.splash_data import (
    ENGINE_ROSTER_LAYOUT,
    load_splash_cache,
    read_engine_roster,
    read_last_session,
    save_splash_cache,
)


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


def test_engine_roster_layout_has_11_engines():
    assert len(ENGINE_ROSTER_LAYOUT) == 11
    names = [row[0] for row in ENGINE_ROSTER_LAYOUT]
    assert "CITADEL" in names
    assert "PHI" in names
    assert "ORNSTEIN" in names
    # orchestrators & arquivados excluídos
    assert "MILLENNIUM" not in names
    assert "GRAHAM" not in names


def test_read_engine_roster_merges_sharpe_from_index(tmp_path):
    idx = _write_index(tmp_path, [
        {"engine": "citadel", "timestamp": "2026-04-20T10:00:00", "sharpe": 1.87},
        {"engine": "citadel", "timestamp": "2026-04-19T10:00:00", "sharpe": 1.50},
        {"engine": "jump",    "timestamp": "2026-04-20T10:00:00", "sharpe": 1.42},
    ])
    roster = read_engine_roster(idx)
    assert len(roster) == 11  # layout sempre completo mesmo quando só 2 engines tem runs
    citadel = next(r for r in roster if r["name"] == "CITADEL")
    jump    = next(r for r in roster if r["name"] == "JUMP")
    phi     = next(r for r in roster if r["name"] == "PHI")
    assert citadel["sharpe"] == 1.87  # mais recente vence
    assert jump["sharpe"] == 1.42
    assert phi["sharpe"] is None      # no run registrado


def test_read_engine_roster_no_index_returns_labels_only(tmp_path):
    missing = tmp_path / "absent.json"
    roster = read_engine_roster(missing)
    assert len(roster) == 11
    assert all(r["sharpe"] is None for r in roster)
    assert all(r["status"] in {"✅", "⚠️", "🆕", "🔧", "⚪", "🔴"} for r in roster)


def test_splash_cache_roundtrip(tmp_path):
    cache_path = tmp_path / "splash_cache.json"
    save_splash_cache(cache_path, {"btc": "67,240", "eth": "3,180"})
    assert load_splash_cache(cache_path) == {"btc": "67,240", "eth": "3,180"}


def test_splash_cache_load_missing_returns_empty_dict(tmp_path):
    assert load_splash_cache(tmp_path / "never.json") == {}


def test_splash_cache_load_corrupt_returns_empty_dict(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("not json {", encoding="utf-8")
    assert load_splash_cache(p) == {}


def test_splash_cache_save_creates_parent_dirs(tmp_path):
    cache_path = tmp_path / "nested" / "subdir" / "cache.json"
    assert not cache_path.parent.exists()  # precondicao: dir nao existe ainda
    save_splash_cache(cache_path, {"a": 1})
    assert cache_path.parent.is_dir()      # claim primario: mkdir aconteceu
    assert cache_path.exists()
    assert load_splash_cache(cache_path) == {"a": 1}


def test_splash_cache_load_null_json_returns_empty_dict(tmp_path):
    p = tmp_path / "null.json"
    p.write_text("null", encoding="utf-8")
    assert load_splash_cache(p) == {}


def test_splash_cache_save_swallows_non_serializable(tmp_path):
    from datetime import datetime
    cache_path = tmp_path / "cache.json"
    # O contrato e "nao raise". json.dump pode ter escrito parcial antes
    # do TypeError; o round-trip load recupera: load lida com corrupt → {}.
    save_splash_cache(cache_path, {"ts": datetime.now()})
    assert load_splash_cache(cache_path) == {}
