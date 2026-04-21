from __future__ import annotations

from tools.maintenance.millennium_shadow import _fmt_num, _trade_key, _run_tick
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
