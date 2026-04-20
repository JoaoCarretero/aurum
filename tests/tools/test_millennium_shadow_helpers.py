from __future__ import annotations

from tools.maintenance.millennium_shadow import _fmt_num, _trade_key


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
