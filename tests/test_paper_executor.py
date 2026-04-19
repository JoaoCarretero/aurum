"""Unit tests for PaperExecutor."""
import math
import pytest
from tools.operations.paper_executor import PaperExecutor


def _signal(direction="LONG", entry=100.0, stop=98.0, target=104.0,
            symbol="BTCUSDT", engine="CITADEL"):
    return {
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "symbol": symbol,
        "strategy": engine,
        "size": 1.0,  # base qty the scan produced for 10k account
    }


def test_long_fill_applies_slippage_and_spread():
    ex = PaperExecutor(slippage=0.0002, spread=0.0001, commission=0.0004,
                       account_size=10_000.0, base_account_size=10_000.0)
    pos = ex.open(_signal(direction="LONG", entry=100.0), opened_at_idx=42,
                  opened_at_iso="2026-04-19T14:05:00Z")
    # LONG: fill = entry * (1 + slip) + spread = 100 * 1.0002 + 0.0001 = 100.0201
    assert pos.direction == "LONG"
    assert math.isclose(pos.entry_price, 100.0201, abs_tol=1e-6)
    # commission = fill * size * commission
    assert math.isclose(pos.commission_paid, 100.0201 * 1.0 * 0.0004, abs_tol=1e-6)


def test_short_fill_applies_negative_slippage_minus_spread():
    ex = PaperExecutor(slippage=0.0002, spread=0.0001, commission=0.0004,
                       account_size=10_000.0, base_account_size=10_000.0)
    pos = ex.open(_signal(direction="SHORT", entry=100.0), opened_at_idx=0,
                  opened_at_iso="2026-04-19T14:05:00Z")
    # SHORT: fill = entry * (1 - slip) - spread = 100 * 0.9998 - 0.0001 = 99.9799
    assert math.isclose(pos.entry_price, 99.9799, abs_tol=1e-6)


def test_size_scales_linearly_with_account_size():
    ex_10k = PaperExecutor(account_size=10_000.0, base_account_size=10_000.0)
    ex_25k = PaperExecutor(account_size=25_000.0, base_account_size=10_000.0)
    pos_10k = ex_10k.open(_signal(), 0, "2026-04-19T14:05:00Z")
    pos_25k = ex_25k.open(_signal(), 0, "2026-04-19T14:05:00Z")
    assert pos_25k.size == pytest.approx(pos_10k.size * 2.5)
    assert pos_25k.notional == pytest.approx(pos_10k.notional * 2.5)


def test_position_id_is_unique():
    ex = PaperExecutor(account_size=10_000.0, base_account_size=10_000.0)
    p1 = ex.open(_signal(), 0, "2026-04-19T14:05:00Z")
    p2 = ex.open(_signal(), 1, "2026-04-19T14:06:00Z")
    assert p1.id != p2.id


def test_notional_equals_entry_times_size():
    ex = PaperExecutor(account_size=10_000.0, base_account_size=10_000.0)
    sig = _signal(entry=100.0)
    sig["size"] = 0.5
    pos = ex.open(sig, 0, "2026-04-19T14:05:00Z")
    assert math.isclose(pos.notional, pos.entry_price * pos.size, abs_tol=1e-6)
