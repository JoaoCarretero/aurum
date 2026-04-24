"""Unit tests for KSLiveGate."""
from tools.operations.paper_ks_gate import KSLiveGate, KSState


def test_initial_state_normal():
    g = KSLiveGate(account_size=10_000.0, base_risk=0.005, fast_mult=2.0)
    assert g.state == KSState.NORMAL


def test_threshold_scales_with_account_size():
    g_10k = KSLiveGate(account_size=10_000.0, base_risk=0.005, fast_mult=2.0)
    g_100k = KSLiveGate(account_size=100_000.0, base_risk=0.005, fast_mult=2.0)
    # 10k: 2 * 10000 * 0.005 = 100 -> threshold -100
    # 100k: 2 * 100000 * 0.005 = 1000 -> threshold -1000
    assert g_10k.fast_threshold == -100.0
    assert g_100k.fast_threshold == -1000.0


def test_drawdown_below_threshold_triggers_fast_halt():
    g = KSLiveGate(account_size=10_000.0, base_risk=0.005, fast_mult=2.0)
    # dd = -99 -> still NORMAL
    triggered = g.check(peak_equity=10_100.0, equity=10_001.0)
    assert not triggered
    assert g.state == KSState.NORMAL
    # dd = -101 -> FAST_HALT
    triggered = g.check(peak_equity=10_100.0, equity=9_999.0)
    assert triggered
    assert g.state == KSState.FAST_HALT
    assert g.last_trigger is not None


def test_after_fast_halt_stays_latched():
    g = KSLiveGate(account_size=10_000.0, base_risk=0.005, fast_mult=2.0)
    g.check(peak_equity=10_000.0, equity=9_800.0)  # triggers
    assert g.state == KSState.FAST_HALT
    # Recovery does not un-latch
    g.check(peak_equity=10_000.0, equity=10_050.0)
    assert g.state == KSState.FAST_HALT
