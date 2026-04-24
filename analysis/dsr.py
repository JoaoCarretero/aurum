"""Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

DSR corrige o Sharpe pela inflação causada por multiple testing
(n_trials de param-sweep) e por não-normalidade dos retornos (skew,
kurtosis). Output: probabilidade de que o Sharpe observado reflita edge
real em vez de acaso dentre N tentativas.

Referência: Bailey, David H., and Marcos López de Prado. "The deflated
Sharpe ratio: correcting for selection bias, backtest overfitting, and
non-normality." The Journal of Portfolio Management 40.5 (2014): 94-107.
"""
from __future__ import annotations
import math


_EULER_MASCHERONI = 0.5772156649015329


def expected_max_sharpe(n_trials: int) -> float:
    """E[max Sharpe] entre n_trials amostras iid Gaussianas N(0,1).

    Forma fechada (López de Prado):
      E[max] = (1 - gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N*e))
    onde gamma = Euler-Mascheroni. Pra N=1, retorna ~0.
    """
    if n_trials <= 0:
        raise ValueError(f"n_trials must be positive, got {n_trials}")
    if n_trials == 1:
        return 0.0
    n = float(n_trials)
    z1 = _inv_norm_cdf(1.0 - 1.0 / n)
    z2 = _inv_norm_cdf(1.0 - 1.0 / (n * math.e))
    return (1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2


def deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    skew: float,
    kurtosis: float,
    n_obs: int,
) -> float:
    """DSR = Prob(true Sharpe > 0 | observed Sharpe, n_trials, moments, n_obs).

    Args:
        sharpe: Sharpe ratio observado (non-annualized; mesma escala que n_obs).
        n_trials: quantas configurações distintas de params foram testadas.
        skew: skewness dos retornos.
        kurtosis: kurtosis dos retornos (Gaussiano=3.0).
        n_obs: número de observações (trades ou períodos) usado pra estimar Sharpe.

    Returns:
        DSR em [0, 1]. > 0.95 = evidência forte de edge real. < 0.5 = suspeito.
    """
    if n_obs < 2:
        raise ValueError(f"n_obs must be >= 2, got {n_obs}")
    exp_max = expected_max_sharpe(n_trials)
    var_sharpe = (1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe * sharpe) / (n_obs - 1)
    if var_sharpe <= 0:
        return 1.0 if sharpe > exp_max else 0.0
    z = (sharpe - exp_max) / math.sqrt(var_sharpe)
    return _norm_cdf(z)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _inv_norm_cdf(p: float) -> float:
    """Inverse standard normal CDF via Beasley-Springer-Moro / Acklam approximation."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.3577518672690, -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416]
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
             ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
