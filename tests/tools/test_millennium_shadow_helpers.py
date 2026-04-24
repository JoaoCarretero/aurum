from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from tools.maintenance.millennium_shadow import (
    _fmt_num,
    _run_tick,
    _tg_signal,
    _trade_key,
)
from tools.operations.millennium_signal_gate import is_live_signal


def test_trade_key_normalizes_strategy_and_symbol_case():
    trade = {
        "strategy": "citadel",
        "symbol": "btcusdt",
        "timestamp": "2026-04-20T10:00:00Z",
    }

    assert _trade_key(trade) == ("CITADEL", "BTCUSDT", "2026-04-20T10:00:00Z")


def test_trade_key_tolerates_missing_fields():
    assert _trade_key({}) == ("", "", None)


def test_fmt_num_formats_large_small_and_invalid_values():
    assert _fmt_num(1234.567) == "1,234.57"
    assert _fmt_num(12.34567) == "12.35"
    assert _fmt_num("abc") == "—"


def test_is_live_signal_uses_reference_timestamp():
    trade = {"timestamp": "2026-04-20T10:00:00+00:00"}

    assert is_live_signal(
        trade,
        tick_sec=900,
        reference_ts="2026-04-20T10:20:00+00:00",
    ) is True
    assert is_live_signal(
        trade,
        tick_sec=900,
        reference_ts="2026-04-20T11:00:01+00:00",
    ) is False


def test_tg_signal_clamps_future_ts_to_now(monkeypatch):
    """Future ts must be clamped to now in Telegram rendering."""
    import tools.maintenance.millennium_shadow as shadow

    sent: list[str] = []
    monkeypatch.setattr(shadow, "_tg_send", lambda text: sent.append(text))

    future_ts = (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()
    trade = {
        "strategy": "JUMP", "symbol": "ARBUSDT", "direction": "BEARISH",
        "entry": 0.126, "stop": 0.1274, "target": 0.1217,
        "rr": 3, "size": 27645,
        "timestamp": future_ts,
    }

    _tg_signal(trade)

    assert len(sent) == 1
    msg = sent[0]
    now_minute = datetime.now(timezone.utc).isoformat().replace("T", " ")[:13]
    assert now_minute in msg, f"clamped ts not in message: {msg}"
    future_minute = future_ts.replace("T", " ")[:16]
    assert future_minute not in msg


def test_tg_signal_preserves_past_ts(monkeypatch):
    import tools.maintenance.millennium_shadow as shadow

    sent: list[str] = []
    monkeypatch.setattr(shadow, "_tg_send", lambda text: sent.append(text))

    trade = {
        "strategy": "CITADEL", "symbol": "BTCUSDT", "direction": "LONG",
        "entry": 100.0, "stop": 98.0, "target": 103.0,
        "rr": 1.5, "size": 0.1,
        "timestamp": "2026-04-20T10:00:00Z",
    }

    _tg_signal(trade)

    assert len(sent) == 1
    assert "2026-04-20 10:00" in sent[0]


def test_run_tick_skips_stale_signals_after_prime(monkeypatch):
    import engines.millennium as mm
    import tools.maintenance.millennium_shadow as shadow

    appended: list[dict] = []
    notified: list[dict] = []

    monkeypatch.setattr(mm, "_load_dados", lambda _: (None, None, None, None))
    monkeypatch.setattr(
        mm,
        "_collect_live_signals",
        lambda *_args, **_kwargs: (
            {"CITADEL": [{"symbol": "BTCUSDT"}]},
            [{
                "strategy": "CITADEL",
                "symbol": "BTCUSDT",
                "direction": "LONG",
                "entry": 100.0,
                "stop": 98.0,
                "target": 103.0,
                "timestamp": "2026-01-22T14:00:00Z",
            }],
        ),
    )
    monkeypatch.setattr(shadow, "_append_trade", lambda trade: appended.append(trade))
    monkeypatch.setattr(shadow, "_append_per_engine", lambda trade: None)
    monkeypatch.setattr(shadow, "_tg_signal", lambda trade: notified.append(trade))

    novel, scanned, engines_ok, last_novel, stats = _run_tick(set(), tick_sec=900, notify=True)

    assert novel == 0
    assert scanned == 1
    assert engines_ok == 1
    assert last_novel is None
    assert stats == {"scanned": 1, "dedup": 0, "stale": 1, "live": 0}
    assert appended == []
    assert notified == []


def test_run_tick_does_not_materialize_stale_priming_signal(monkeypatch):
    import engines.millennium as mm
    import tools.maintenance.millennium_shadow as shadow

    appended: list[dict] = []
    seen_keys: set[tuple] = set()

    monkeypatch.setattr(mm, "_load_dados", lambda _: (None, None, None, None))
    monkeypatch.setattr(
        mm,
        "_collect_live_signals",
        lambda *_args, **_kwargs: (
            {"JUMP": [{"symbol": "SANDUSDT"}]},
            [{
                "strategy": "JUMP",
                "symbol": "SANDUSDT",
                "direction": "BEARISH",
                "entry": 0.10,
                "stop": 0.11,
                "target": 0.07,
                "timestamp": "2026-01-22T14:00:00Z",
            }],
        ),
    )
    monkeypatch.setattr(shadow, "_append_trade", lambda trade: appended.append(trade))
    monkeypatch.setattr(shadow, "_append_per_engine", lambda trade: None)
    monkeypatch.setattr(shadow, "_tg_signal", lambda trade: None)

    novel, scanned, engines_ok, last_novel, stats = _run_tick(seen_keys, tick_sec=900, notify=False)

    assert novel == 0
    assert scanned == 1
    assert engines_ok == 1
    assert last_novel is None
    assert stats == {"scanned": 1, "dedup": 0, "stale": 1, "live": 0}
    assert appended == []
    assert len(seen_keys) == 1


def test_run_tick_logs_prime_scan_summary_for_stale_bootstrap(monkeypatch, caplog):
    import engines.millennium as mm

    monkeypatch.setattr(mm, "_load_dados", lambda _: (None, None, None, None))
    monkeypatch.setattr(
        mm,
        "_collect_live_signals",
        lambda *_args, **_kwargs: (
            {"JUMP": [{"symbol": "SANDUSDT"}]},
            [{
                "strategy": "JUMP",
                "symbol": "SANDUSDT",
                "direction": "BEARISH",
                "entry": 0.10,
                "stop": 0.11,
                "target": 0.07,
                "timestamp": "2026-01-22T14:00:00Z",
            }],
        ),
    )

    with caplog.at_level(logging.INFO, logger="millennium_shadow"):
        _run_tick(set(), tick_sec=900, notify=False)

    assert "PRIME scan scanned=1 dedup=0 stale=1 live=0" in caplog.text


def test_ensure_log_handlers_rebinds_shadow_log_after_label_change(monkeypatch):
    import tools.maintenance.millennium_shadow as shadow

    shadow._configure_run("desk-shadow-test")
    shadow._ensure_log_handlers()

    file_handlers = [
        handler for handler in shadow.log.handlers
        if isinstance(handler, logging.FileHandler)
    ]
    assert file_handlers
    assert file_handlers[-1].baseFilename == str(shadow.SHADOW_LOG.resolve())
