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
    # notional = size (285.4 tokens) * entry (65432.5) = ~$18.67M → "$18672.3k"
    assert cells["notional"].startswith("$")
    assert "k" in cells["notional"]
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
    assert cells["notional"] == "—"
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


def test_last_sig_age_prefers_heartbeat_last_novel():
    """LAST SIG deve usar heartbeat.last_novel_at (detectado AO VIVO)
    em vez do ultimo trade (que pode ser primed do universo)."""
    from datetime import datetime, timezone, timedelta
    from launcher_support.engines_sidebar import _last_sig_age
    # heartbeat diz: 2 min atras
    novel_at = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    hb = {"last_novel_at": novel_at}
    trades = [{
        "primed": True,
        "shadow_observed_at": "2020-01-01T00:00:00+00:00",  # velho
    }]
    text, color = _last_sig_age(trades, hb)
    assert text.endswith("m"), f"expected ending 'm', got {text}"
    assert color  # nao vazio


def test_last_sig_age_filters_primed_when_hb_missing():
    """Se heartbeat nao tem last_novel_at (runner antigo), filtra
    primed records e usa ultimo nao-primed."""
    from datetime import datetime, timezone, timedelta
    from launcher_support.engines_sidebar import _last_sig_age
    non_primed_ts = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    trades = [
        {"primed": True, "shadow_observed_at": "2020-01-01T00:00:00+00:00"},
        {"primed": False, "shadow_observed_at": non_primed_ts},
    ]
    text, color = _last_sig_age(trades, heartbeat=None)
    # 30min deve aparecer como "30m" e cor GREEN (<1h)
    assert "30m" in text or "29m" in text


def test_last_sig_age_empty_returns_dash():
    from launcher_support.engines_sidebar import _last_sig_age
    text, color = _last_sig_age([], None)
    assert text == "—"


def test_render_detail_paper_smoke_no_exception():
    """Paper mode renders EQUITY/DD/NET + OPEN POSITIONS + EQUITY CURVE +
    METRICS sections without crashing when all paper params are passed."""
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("tkinter not available")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    try:
        from launcher_support.engines_sidebar import render_detail
        parent = tk.Frame(root)
        heartbeat = {
            "run_id": "R", "status": "running", "ticks_ok": 3,
            "ticks_fail": 0, "novel_total": 1, "last_tick_at": None,
            "mode": "paper", "account_size": 10_000.0,
            "equity": 10_120.0, "drawdown_pct": 0.12, "ks_state": "NORMAL",
        }
        frame = render_detail(
            parent=parent, engine_display="MILLENNIUM",
            mode="paper", heartbeat=heartbeat,
            manifest={"commit": "c", "branch": "b"},
            trades=[], on_row_click=lambda _t: None,
            account_snapshot={
                "equity": 10_120.0, "drawdown": 12.0, "drawdown_pct": 0.12,
                "realized_pnl": 80.0, "unrealized_pnl": 40.0,
                "initial_balance": 10_000.0,
                "metrics": {"sharpe": 1.5, "win_rate": 0.6,
                            "profit_factor": 2.0, "net_pnl": 120.0,
                            "maxdd": 30.0, "roi_pct": 1.2},
            },
            open_positions=[{
                "id": "pos_1", "symbol": "BTCUSDT", "engine": "CITADEL",
                "direction": "LONG", "entry_price": 100.0,
                "notional": 1000.0, "unrealized_pnl": 25.0,
                "stop": 98.0, "target": 104.0,
                "opened_at": "2026-04-19T14:00:00Z", "bars_held": 3,
            }],
            equity_series=[10_000.0, 10_020.0, 10_080.0, 10_120.0],
            on_stop_paper=lambda: None,
        )
        assert frame is not None
    finally:
        root.destroy()


def test_render_detail_paper_with_no_positions_renders_empty_state():
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("tkinter not available")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    try:
        from launcher_support.engines_sidebar import render_detail
        parent = tk.Frame(root)
        heartbeat = {
            "run_id": "R", "status": "running", "ticks_ok": 1,
            "ticks_fail": 0, "novel_total": 0,
        }
        frame = render_detail(
            parent=parent, engine_display="MILLENNIUM",
            mode="paper", heartbeat=heartbeat, manifest=None,
            trades=[], on_row_click=lambda _t: None,
            account_snapshot={"equity": 10_000.0, "drawdown_pct": 0.0,
                              "realized_pnl": 0.0, "unrealized_pnl": 0.0,
                              "initial_balance": 10_000.0, "metrics": {}},
            open_positions=[],
            equity_series=[],
        )
        assert frame is not None
    finally:
        root.destroy()


def test_render_detail_shadow_still_works_without_paper_params():
    """Backward compat: shadow mode renders without any paper kwargs."""
    try:
        import tkinter as tk
    except ImportError:
        pytest.skip("tkinter not available")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    root.withdraw()
    try:
        from launcher_support.engines_sidebar import render_detail
        parent = tk.Frame(root)
        heartbeat = {"run_id": "R", "status": "running", "ticks_ok": 5,
                     "ticks_fail": 0, "novel_total": 2}
        frame = render_detail(
            parent=parent, engine_display="MILLENNIUM",
            mode="shadow", heartbeat=heartbeat, manifest=None,
            trades=[], on_row_click=lambda _t: None,
        )
        assert frame is not None
    finally:
        root.destroy()
