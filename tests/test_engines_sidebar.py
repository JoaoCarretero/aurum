"""Tests pros helpers puros do sidebar. Render Tk eh smoke-only."""
from __future__ import annotations
import pytest


def test_engine_row_dataclass():
    from launcher_support.engines_sidebar import EngineRow
    row = EngineRow(slug="millennium", display="MILLENNIUM",
                    active=True, ticks=41, signals=625)
    assert row.slug == "millennium"
    assert row.active is True
    assert row.ticks == 41


def test_build_engine_rows_active_engine():
    """Engine com heartbeat em cache aparece como active com ticks/signals."""
    from launcher_support.engines_sidebar import build_engine_rows
    registry = [
        {"slug": "millennium", "display": "MILLENNIUM"},
        {"slug": "citadel",    "display": "CITADEL"},
    ]
    heartbeats = {
        "millennium": {"ticks_ok": 41, "novel_total": 625, "status": "running"},
    }
    rows = build_engine_rows(registry, heartbeats)
    assert len(rows) == 2
    mill = next(r for r in rows if r.slug == "millennium")
    cit = next(r for r in rows if r.slug == "citadel")
    assert mill.active is True
    assert mill.ticks == 41
    assert mill.signals == 625
    assert cit.active is False
    assert cit.ticks is None
    assert cit.signals is None


def test_build_engine_rows_preserves_registry_order():
    from launcher_support.engines_sidebar import build_engine_rows
    registry = [
        {"slug": "a", "display": "A"},
        {"slug": "b", "display": "B"},
        {"slug": "c", "display": "C"},
    ]
    rows = build_engine_rows(registry, {})
    assert [r.slug for r in rows] == ["a", "b", "c"]


def test_format_signal_row_complete():
    """Trade com todos os campos → dict de strings formatados."""
    from launcher_support.engines_sidebar import format_signal_row
    trade = {
        "timestamp": "2026-04-18T19:02:15",
        "symbol": "BTCUSDT",
        "direction": "BULLISH",
        "entry": 65432.5,
        "stop": 65120.0,
        "rr": 3.0,
        "size": 285.4,
        "result": "WIN",
    }
    cells = format_signal_row(trade)
    assert cells["time"] == "19:02"
    assert cells["sym"] == "BTC"
    assert cells["dir"] == "L"
    assert cells["entry"] == "65432"
    assert cells["stop"] == "65120"
    assert cells["rr"] == "3.0"
    assert cells["size"] == "$285"
    assert cells["res"] == "WIN"


def test_format_signal_row_none_fields_render_dash():
    from launcher_support.engines_sidebar import format_signal_row
    trade = {"timestamp": "2026-04-18T12:00", "symbol": "ETH",
             "direction": "SHORT"}
    cells = format_signal_row(trade)
    assert cells["time"] == "12:00"
    assert cells["dir"] == "S"
    assert cells["entry"] == "—"
    assert cells["stop"] == "—"
    assert cells["rr"] == "—"
    assert cells["size"] == "—"
    assert cells["res"] == "—"


def test_format_signal_row_short_symbol_not_truncated():
    from launcher_support.engines_sidebar import format_signal_row
    cells = format_signal_row({"timestamp": "2026-04-18T12:00",
                                "symbol": "OP", "direction": "LONG"})
    assert cells["sym"] == "OP"


def test_format_signal_row_direction_variants():
    from launcher_support.engines_sidebar import format_signal_row
    ts = "2026-04-18T12:00"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "LONG"})["dir"] == "L"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "BULL"})["dir"] == "L"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "BULLISH"})["dir"] == "L"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "SHORT"})["dir"] == "S"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "BEAR"})["dir"] == "S"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "BEARISH"})["dir"] == "S"
    assert format_signal_row({"timestamp": ts, "symbol": "X", "direction": "???"})["dir"] == "?"


def test_format_signal_row_date_only_timestamp_returns_dash():
    """Reviewer findings: date-only timestamp (sem hora) retornava '2026-' bizarro.
    Agora retorna '—' pra evitar output enganoso."""
    from launcher_support.engines_sidebar import format_signal_row
    cells = format_signal_row({
        "timestamp": "2026-04-18",
        "symbol": "BTC",
        "direction": "LONG",
    })
    assert cells["time"] == "—"


def test_format_signal_row_short_hh_mm_timestamp():
    """String curta '12:00' já formatada deve ser preservada."""
    from launcher_support.engines_sidebar import format_signal_row
    cells = format_signal_row({
        "timestamp": "12:00",
        "symbol": "BTC",
        "direction": "LONG",
    })
    assert cells["time"] == "12:00"


def test_result_color_mapping():
    """Pure function mapeia result → color name (string pro renderer usar)."""
    from launcher_support.engines_sidebar import result_color_name
    assert result_color_name("WIN") == "GREEN"
    assert result_color_name("LOSS") == "RED"
    assert result_color_name(None) == "DIM"
    assert result_color_name("") == "DIM"


def test_build_engine_rows_active_engine_without_counts():
    """Non-shadow heartbeat sem ticks_ok/novel_total → active=True mas ticks/signals=None."""
    from launcher_support.engines_sidebar import build_engine_rows
    registry = [{"slug": "citadel", "display": "CITADEL"}]
    heartbeats = {"citadel": {"status": "running"}}
    rows = build_engine_rows(registry, heartbeats)
    assert len(rows) == 1
    assert rows[0].active is True
    assert rows[0].ticks is None
    assert rows[0].signals is None
