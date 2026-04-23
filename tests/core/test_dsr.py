"""Unit tests for deflated Sharpe ratio (Bailey & López de Prado 2014).

Reference values computed from the formula:
  DSR = Phi(((Sharpe - E[max_Sharpe]) * sqrt(n-1)) / sqrt(1 - g3*Sharpe + g4/4 * Sharpe^2))
  E[max_Sharpe] ~ sqrt(2*log(n_trials)) for iid Gaussian (Euler-Mascheroni ignored in simple form)
"""
import pytest

from analysis.dsr import deflated_sharpe_ratio, expected_max_sharpe


def test_expected_max_sharpe_monotonic_in_n_trials():
    e1 = expected_max_sharpe(n_trials=1)
    e10 = expected_max_sharpe(n_trials=10)
    e100 = expected_max_sharpe(n_trials=100)
    assert e1 < e10 < e100
    assert abs(e1) < 0.1


def test_dsr_single_trial_is_high_for_good_sharpe():
    dsr = deflated_sharpe_ratio(
        sharpe=2.0, n_trials=1, skew=0.0, kurtosis=3.0, n_obs=252
    )
    assert dsr > 0.95


def test_dsr_many_trials_penalizes_moderate_sharpe():
    # Sharpe=1.5 após 100 trials: E[max]=~2.53, z=-11 → DSR colpasa pra ~0.
    # Assertion: DSR é drasticamente penalizado (muito abaixo de 0.8).
    # Usamos >= 0.0 porque float underflow é válido (não é erro de implementação).
    dsr = deflated_sharpe_ratio(
        sharpe=1.5, n_trials=100, skew=0.0, kurtosis=3.0, n_obs=252
    )
    assert dsr < 0.05  # z ≈ -11 underflows to 0.0 in float64 — DSR collapses


def test_dsr_negative_skew_penalizes():
    dsr_pos = deflated_sharpe_ratio(sharpe=2.0, n_trials=10, skew=0.5, kurtosis=3.0, n_obs=252)
    dsr_neg = deflated_sharpe_ratio(sharpe=2.0, n_trials=10, skew=-0.5, kurtosis=3.0, n_obs=252)
    assert dsr_neg < dsr_pos


def test_dsr_returns_in_unit_interval():
    dsr = deflated_sharpe_ratio(sharpe=3.0, n_trials=50, skew=0.2, kurtosis=4.0, n_obs=500)
    assert 0.0 <= dsr <= 1.0
    assert dsr > 0.90  # Sharpe=3 after 50 trials, E[max]~2.88: z > 0 → DSR high (actual ≈ 1.0)


def test_expected_max_sharpe_zero_trials_raises():
    with pytest.raises(ValueError):
        expected_max_sharpe(n_trials=0)


def test_dsr_invalid_n_obs_raises():
    with pytest.raises(ValueError):
        deflated_sharpe_ratio(sharpe=1.0, n_trials=10, skew=0.0, kurtosis=3.0, n_obs=1)
