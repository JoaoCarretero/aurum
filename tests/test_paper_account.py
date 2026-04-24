"""Unit tests for PaperAccount."""
import pytest
from tools.operations.paper_account import PaperAccount


def test_initial_state():
    a = PaperAccount(initial_balance=10_000.0)
    assert a.balance == 10_000.0
    assert a.realized_pnl == 0.0
    assert a.unrealized_pnl == 0.0
    assert a.equity == 10_000.0
    assert a.peak_equity == 10_000.0
    assert a.drawdown == 0.0


def test_apply_realized_updates_balance_and_peak():
    a = PaperAccount(initial_balance=10_000.0)
    a.apply_realized(+150.0)
    assert a.balance == 10_150.0
    assert a.realized_pnl == 150.0
    assert a.equity == 10_150.0
    assert a.peak_equity == 10_150.0
    a.apply_realized(-75.0)
    assert a.balance == 10_075.0
    assert a.peak_equity == 10_150.0  # peak unchanged
    assert a.drawdown == 75.0
    assert round(a.drawdown_pct, 4) == round(75.0 / 10_150.0 * 100, 4)


def test_set_unrealized_does_not_change_balance():
    a = PaperAccount(initial_balance=10_000.0)
    a.set_unrealized(42.5)
    assert a.balance == 10_000.0
    assert a.unrealized_pnl == 42.5
    assert a.equity == 10_042.5
    # Peak moves with equity (unrealized counts for KS)
    assert a.peak_equity == 10_042.5


def test_equity_drops_below_peak_creates_drawdown():
    a = PaperAccount(initial_balance=10_000.0)
    a.set_unrealized(+200.0)           # equity 10_200, peak 10_200
    a.set_unrealized(-150.0)           # equity 9_850, peak stays 10_200
    assert a.drawdown == pytest.approx(350.0)
    assert a.equity == 9_850.0


def test_snapshot_shape():
    a = PaperAccount(initial_balance=10_000.0)
    a.apply_realized(+100.0)
    a.set_unrealized(+50.0)
    snap = a.snapshot()
    assert snap["initial_balance"] == 10_000.0
    assert snap["current_balance"] == 10_100.0
    assert snap["realized_pnl"] == 100.0
    assert snap["unrealized_pnl"] == 50.0
    assert snap["equity"] == 10_150.0
    assert snap["peak_equity"] == 10_150.0
    assert snap["drawdown"] == 0.0
