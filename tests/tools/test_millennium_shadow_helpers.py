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
    """Future ts (from incomplete tail candle) must be clamped to now.

    live_mode scan can emit a signal whose timestamp = next candle's
    open_time, which is in the future relative to observation. Telegram
    used to render that literal, confusing the operator. Clamp is
    cosmetic — does not affect dedup or gating.
    """
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
    # Rendered ts should be <= now (rounded to minute; tolerate drift).
    now_minute = datetime.now(timezone.utc).isoformat().replace("T", " ")[:13]
    assert now_minute in msg, f"clamped ts not in message: {msg}"
    # And the raw future ts should NOT leak into the rendered line.
    future_minute = future_ts.replace("T", " ")[:16]
    assert future_minute not in msg


def test_tg_signal_preserves_past_ts(monkeypatch):
    """Past/present ts rendered as-is (only future ts is clamped)."""
    import tools.maintenance.millennium_shadow as shadow

    sent: list[str] = []
    monkeypatch.setattr(shadow, "_tg_send", lambda text: sent.append(text))

    past_ts = "2026-04-20T10:00:00Z"
    trade = {
        "strategy": "CITADEL", "symbol": "BTCUSDT", "direction": "LONG",
        "entry": 100.0, "stop": 98.0, "target": 103.0,
        "rr": 1.5, "size": 0.1,
        "timestamp": past_ts,
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
    # Shadow now calls _collect_live_signals (tail-only). Patch that.
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

    novel, scanned, engines_ok, last_novel = _run_tick(set(), tick_sec=900, notify=True)

    assert novel == 0
    assert scanned == 1
    assert engines_ok == 1
    assert last_novel is None
    assert appended == []
    assert notified == []


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
