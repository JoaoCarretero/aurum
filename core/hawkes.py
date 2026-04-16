"""
AURUM — core/hawkes.py
======================
Minimal univariate Hawkes process (exponential kernel) for regime sensing.

Branching ratio η = α/β measures endogeneity: the fraction of events caused by
self-excitation vs exogenous Poisson flow. η → 1 characterizes a nearly-unstable
regime, empirically associated with precursors to crashes / liquidation cascades.

References
----------
- Hawkes (1971) — self-exciting point process
- Ogata (1981) — O(N) recursion for exponential-kernel log-likelihood
- Filimonov & Sornette (2012) — η as reflexivity proxy in S&P500
- Hardiman & Bouchaud (2014) — η estimation in crypto / BTC

Additive library. No coupling to engines or config/params. Intended to be
consumed by engines/kepos.py and engines/graham.py as a regime feature source.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy.optimize import minimize

logger = logging.getLogger("core.hawkes")


# ── thresholds for qualitative labels ───────────────────────────────
_ETA_EXO_MAX   = 0.50
_ETA_MIXED_MAX = 0.80
_ETA_ENDO_MAX  = 0.95

# ── numerical guards ────────────────────────────────────────────────
_EPS = 1e-12
_EXP_CLIP = 50.0   # clip β·Δt to avoid overflow in exp(-·)


# ════════════════════════════════════════════════════════════════════
# Result container
# ════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class HawkesFit:
    """Single Hawkes MLE fit result.

    Attributes
    ----------
    mu : float
        Baseline intensity (events per unit time; here, per bar).
    alpha : float
        Excitation magnitude.
    beta : float
        Excitation decay rate.
    branching_ratio : float
        η = α/β, in [0, max_eta].
    loglik : float
        Final log-likelihood value.
    n_events : int
        Number of events used in the fit.
    T : float
        Observation window duration.
    converged : bool
        Whether the optimizer reported success AND η < 1.
    message : str
        Optimizer message (or reason for failure).
    """
    mu: float
    alpha: float
    beta: float
    branching_ratio: float
    loglik: float
    n_events: int
    T: float
    converged: bool
    message: str


# ════════════════════════════════════════════════════════════════════
# Jump detection
# ════════════════════════════════════════════════════════════════════

def detect_jumps(
    returns: np.ndarray,
    k_sigma: float = 2.0,
    vol_lookback: int = 100,
) -> np.ndarray:
    """Detect jump events in a returns series.

    A jump is a bar t where |r_t| > k_sigma × σ_rolling_t, with σ_rolling_t
    estimated from the previous `vol_lookback` bars (shift(1) — no lookahead).

    The "time" unit of subsequent Hawkes fitting is the BAR INDEX (not
    seconds): μ is in events/bar, β in 1/bar, η is dimensionless.

    Parameters
    ----------
    returns : np.ndarray of shape (N,)
        Simple or log returns. Order is preserved.
    k_sigma : float
        Threshold multiplier on rolling σ. Default 2.0.
    vol_lookback : int
        Window for rolling σ. Default 100.

    Returns
    -------
    np.ndarray[int64]
        Sorted indices of bars where a jump was detected. Bars before
        `vol_lookback` valid returns are excluded (insufficient σ history).
    """
    r = np.asarray(returns, dtype=float)
    if r.ndim != 1:
        raise ValueError("returns must be 1-D")
    if vol_lookback < 2:
        raise ValueError("vol_lookback must be >= 2")

    s = pd.Series(r)
    # shift(1) prevents bar t from entering its own σ — no lookahead
    sigma = s.rolling(vol_lookback, min_periods=vol_lookback).std().shift(1).values

    with np.errstate(invalid="ignore"):
        threshold = k_sigma * sigma
        mask = np.abs(r) > threshold
    mask = np.where(np.isnan(threshold), False, mask)
    return np.asarray(np.where(mask)[0], dtype=np.int64)


# ════════════════════════════════════════════════════════════════════
# Log-likelihood (Ogata 1981 recursion, O(N))
# ════════════════════════════════════════════════════════════════════

def _neg_loglik_exp(
    params: np.ndarray,
    event_times: np.ndarray,
    T: float,
    max_eta: float,
) -> float:
    """Negative log-likelihood for exponential-kernel Hawkes.

    LL = Σ log(μ + α·A_i) - μ·T - (α/β)·Σ (1 - exp(-β·(T - t_i)))

    with the recursion

        A_0 = 0
        A_i = exp(-β·(t_i - t_{i-1})) · (1 + A_{i-1})   for i ≥ 1

    computed inline in O(N). Soft penalty 1e6·max(0, α/β − max_eta)² is
    added to enforce η < max_eta during optimization (avoids divergence in
    the nearly-unstable regime without needing constrained optimization).
    """
    mu, alpha, beta = params
    if mu <= 0 or alpha <= 0 or beta <= 0:
        return 1e18

    n = len(event_times)
    if n == 0:
        return mu * T

    # Recursion for log-intensity sum
    log_sum = np.log(mu + _EPS)  # λ(t_0) = μ (A_0 = 0)
    A = 0.0
    prev_t = event_times[0]
    for i in range(1, n):
        dt = event_times[i] - prev_t
        if dt < 0:
            return 1e18  # unsorted; caller should have validated
        decay = np.exp(-min(beta * dt, _EXP_CLIP))
        A = decay * (1.0 + A)
        lam = mu + alpha * A
        if lam <= 0:
            return 1e18
        log_sum += np.log(lam + _EPS)
        prev_t = event_times[i]

    # Integral term: ∫₀^T λ(s)ds = μ·T + (α/β)·Σ(1 - exp(-β(T-t_i)))
    tail_exp = np.exp(np.clip(-beta * (T - event_times), -_EXP_CLIP, 0.0))
    integral = mu * T + (alpha / beta) * np.sum(1.0 - tail_exp)

    ll = log_sum - integral
    neg_ll = -ll

    eta = alpha / beta
    if eta > max_eta:
        neg_ll += 1e6 * (eta - max_eta) ** 2

    if not np.isfinite(neg_ll):
        return 1e18
    return float(neg_ll)


# ════════════════════════════════════════════════════════════════════
# MLE fit
# ════════════════════════════════════════════════════════════════════

def fit_hawkes_exp(
    event_times: np.ndarray,
    T: float,
    *,
    mu0: Optional[float] = None,
    alpha0: float = 0.3,
    beta0: float = 1.0,
    max_eta: float = 0.999,
) -> HawkesFit:
    """MLE of univariate exponential-kernel Hawkes process via L-BFGS-B.

    Parameters
    ----------
    event_times : np.ndarray
        Sorted event timestamps (floats) in [0, T]. In our convention these
        are bar indices.
    T : float
        End of observation window (duration).
    mu0, alpha0, beta0 : float
        Initial guesses. `mu0=None` uses empirical rate N/T.
    max_eta : float
        Cap on η = α/β. Enforced via soft penalty in the objective.

    Returns
    -------
    HawkesFit
        If the optimizer fails or returns non-finite likelihood,
        ``converged=False`` and the caller decides how to handle it.

    Raises
    ------
    ValueError
        If len(event_times) < 10, T <= 0, or event_times not sorted.
    """
    et = np.asarray(event_times, dtype=float)
    if et.ndim != 1:
        raise ValueError("event_times must be 1-D")
    if len(et) < 10:
        raise ValueError(f"need >= 10 events, got {len(et)}")
    if T <= 0:
        raise ValueError(f"T must be > 0, got {T}")
    if np.any(np.diff(et) < 0):
        raise ValueError("event_times must be sorted ascending")
    if et[-1] > T:
        raise ValueError(f"last event {et[-1]} > T={T}")

    n = len(et)
    if mu0 is None:
        mu0 = max(n / T, 1e-6)

    x0 = np.array([mu0, alpha0, beta0], dtype=float)
    bounds = [
        (1e-8, max(10.0 * n / T, 10.0)),  # mu
        (1e-8, 50.0),                      # alpha
        (1e-4, 100.0),                     # beta
    ]

    try:
        res = minimize(
            _neg_loglik_exp,
            x0,
            args=(et, T, max_eta),
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": 200, "ftol": 1e-8},
        )
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("Hawkes MLE raised %s", e)
        return HawkesFit(
            mu=float(mu0), alpha=float(alpha0), beta=float(beta0),
            branching_ratio=float(alpha0 / beta0),
            loglik=float("nan"), n_events=n, T=float(T),
            converged=False, message=f"exception: {e}",
        )

    mu, alpha, beta = res.x
    eta = alpha / beta if beta > 0 else float("nan")
    ll = -res.fun
    converged = bool(res.success) and np.isfinite(ll) and eta < 1.0

    msg = res.message
    if isinstance(msg, bytes):
        msg = msg.decode("utf-8", errors="replace")

    return HawkesFit(
        mu=float(mu),
        alpha=float(alpha),
        beta=float(beta),
        branching_ratio=float(eta),
        loglik=float(ll),
        n_events=n,
        T=float(T),
        converged=converged,
        message=str(msg),
    )


# ════════════════════════════════════════════════════════════════════
# Rolling estimator
# ════════════════════════════════════════════════════════════════════

def rolling_branching_ratio(
    df: pd.DataFrame,
    *,
    window_bars: int = 2000,
    refit_every: int = 100,
    k_sigma: float = 2.0,
    vol_lookback: int = 100,
    smoothing_span: int = 5,
    min_events: int = 30,
    close_col: str = "close",
) -> pd.DataFrame:
    """Rolling Hawkes fit on an OHLCV close series.

    Every `refit_every` bars, fits an exponential Hawkes on the last
    `window_bars` bars' detected jumps. Between fits, eta_raw is carried
    forward from the most recent successful fit. `eta_smooth` is EWM of
    eta_raw with span `smoothing_span`.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV with at least column `close_col`. Index is preserved.
    window_bars : int
        Lookback for each fit. Default 2000. Must be ≥ 100.
    refit_every : int
        Periodicity (in bars) of refits. Default 100.
    k_sigma, vol_lookback : passed to `detect_jumps`.
    smoothing_span : int
        Span of EWM over eta_raw. Default 5.
    min_events : int
        Minimum jumps in window to accept a fit. Default 30.
    close_col : str
        Price column. Default "close".

    Returns
    -------
    pd.DataFrame
        Index equal to df.index, columns:
          - eta_raw : η from most recent successful fit (carried forward)
          - eta_smooth : EWM of eta_raw
          - n_events : events used in most recent fit
          - fit_bar : bar index of most recent fit
        Bars before the first successful fit are NaN.
    """
    if close_col not in df.columns:
        raise ValueError(f"df missing column {close_col!r}")
    if window_bars < 100:
        raise ValueError("window_bars must be >= 100")
    if refit_every < 1:
        raise ValueError("refit_every must be >= 1")

    n_bars = len(df)
    close = df[close_col].values.astype(float)
    log_ret = np.zeros(n_bars)
    log_ret[1:] = np.log(np.clip(close[1:], _EPS, None) /
                         np.clip(close[:-1], _EPS, None))

    out_eta_raw = np.full(n_bars, np.nan)
    out_n_events = np.full(n_bars, np.nan)
    out_fit_bar = np.full(n_bars, np.nan)

    last_eta = np.nan
    last_n = np.nan
    last_fit_bar = np.nan
    _warned_insufficient = False

    for bar_idx in range(window_bars, n_bars, refit_every):
        sub = log_ret[bar_idx - window_bars : bar_idx]
        jumps = detect_jumps(sub, k_sigma=k_sigma, vol_lookback=vol_lookback)

        if len(jumps) < min_events:
            if not _warned_insufficient:
                logger.warning(
                    "Hawkes window @bar=%d has %d events (< min_events=%d); "
                    "carrying forward previous η (further warnings suppressed).",
                    bar_idx, len(jumps), min_events,
                )
                _warned_insufficient = True
        else:
            fit = fit_hawkes_exp(jumps.astype(float), T=float(window_bars))
            if fit.converged and np.isfinite(fit.branching_ratio):
                last_eta = fit.branching_ratio
                last_n = fit.n_events
                last_fit_bar = bar_idx
            else:
                logger.warning(
                    "Hawkes fit @bar=%d did not converge (%s); carrying forward",
                    bar_idx, fit.message,
                )

        end = min(bar_idx + refit_every, n_bars)
        out_eta_raw[bar_idx:end] = last_eta
        out_n_events[bar_idx:end] = last_n
        out_fit_bar[bar_idx:end] = last_fit_bar

    raw_series = pd.Series(out_eta_raw)
    smooth = (
        raw_series
        .ewm(span=smoothing_span, adjust=False, ignore_na=True)
        .mean()
    )
    # Keep smooth NaN wherever raw is NaN (no interpolation across gaps)
    smooth = smooth.where(~raw_series.isna(), np.nan)

    return pd.DataFrame(
        {
            "eta_raw": out_eta_raw,
            "eta_smooth": smooth.values,
            "n_events": out_n_events,
            "fit_bar": out_fit_bar,
        },
        index=df.index,
    )


# ════════════════════════════════════════════════════════════════════
# Label helper
# ════════════════════════════════════════════════════════════════════

def label_eta(eta: Optional[float]) -> str:
    """Map branching ratio to qualitative regime label.

    - "EXO"      : η < 0.50   — market driven by exogenous flow
    - "MIXED"    : 0.50 ≤ η < 0.80
    - "ENDO"     : 0.80 ≤ η < 0.95 — high self-reinforcement
    - "CRITICAL" : η ≥ 0.95   — nearly-unstable regime
    - "NAN"      : input is None / NaN / non-numeric
    """
    if eta is None:
        return "NAN"
    try:
        e = float(eta)
    except (TypeError, ValueError):
        return "NAN"
    if not np.isfinite(e):
        return "NAN"
    if e < _ETA_EXO_MAX:
        return "EXO"
    if e < _ETA_MIXED_MAX:
        return "MIXED"
    if e < _ETA_ENDO_MAX:
        return "ENDO"
    return "CRITICAL"
