"""
CHRONOS — Time-Series Intelligence Layer
=========================================
ML-powered features that capture patterns traditional indicators miss.
Feeds all engines as an optional feature layer.

Features generated:
1. Regime Probability — P(bull), P(bear), P(chop) via Hidden Markov Model
2. Volatility Forecast — GARCH(1,1) prediction for next 4-8 candles
3. Momentum Decay — exponential decay rate of current momentum
4. Fractal Dimension — rolling Hurst exponent
5. Seasonality Score — hour/day edge from historical patterns

HMM backend order of preference:
1. hmmlearn.GaussianHMM  (if installed)
2. GaussianHMMNp         (numpy-pure fallback implemented below)
"""
import logging
import numpy as np
import pandas as pd
from scipy.special import logsumexp

log = logging.getLogger("chronos")

# ── Dependency checks ─────────────────────────────────────────
_HAS_HMM = False
_HAS_ARCH = False

try:
    from hmmlearn.hmm import GaussianHMM
    _HAS_HMM = True
except ImportError:
    pass

try:
    from arch import arch_model
    _HAS_ARCH = True
except ImportError:
    pass


# ══════════════════════════════════════════════════════════════
#  0. GaussianHMMNp — numpy-pure Gaussian HMM (diagonal cov)
# ══════════════════════════════════════════════════════════════
class GaussianHMMNp:
    """Minimal Gaussian-emission HMM with diagonal covariances.

    Implements Baum-Welch (EM) training, forward-backward posteriors,
    and Viterbi decoding in log-space for numerical stability.

    Purpose: disciplined fallback when ``hmmlearn`` cannot be installed
    (e.g. Python 3.14 on Windows without MSVC Build Tools). The API
    mirrors the subset of ``hmmlearn.hmm.GaussianHMM`` we actually use.

    Parameters
    ----------
    n_states : number of hidden states K
    n_iter   : max EM iterations
    tol      : relative log-likelihood convergence tolerance
    random_state : seed for deterministic initialisation
    min_covar : floor applied to variances for numerical safety
    """

    _LOG_ZERO_EPS = 1e-300

    def __init__(self, n_states=3, n_iter=100, tol=1e-4,
                 random_state=None, min_covar=1e-6):
        self.n_states = int(n_states)
        self.n_iter = int(n_iter)
        self.tol = float(tol)
        self.random_state = random_state
        self.min_covar = float(min_covar)

    # ── Initialisation ────────────────────────────────────────
    def _kmeans_init(self, X, rng, max_iter=25):
        """Lloyd's k-means to seed the HMM means robustly."""
        n_samples, n_features = X.shape
        K = self.n_states
        if n_samples < K:
            # Pad with random draws when the sequence is shorter than K.
            pick = rng.integers(0, max(n_samples, 1), size=K)
            return X[pick].copy() if n_samples else np.zeros((K, n_features))

        # Seed centers via k-means++ (deterministic under the given rng).
        first = int(rng.integers(0, n_samples))
        centers = [X[first]]
        for _ in range(1, K):
            d2 = np.min(
                np.sum((X[:, None, :] - np.array(centers)[None, :, :]) ** 2, axis=2),
                axis=1,
            )
            total = d2.sum()
            if total <= 0:
                centers.append(X[int(rng.integers(0, n_samples))])
                continue
            probs = d2 / total
            idx = int(rng.choice(n_samples, p=probs))
            centers.append(X[idx])
        centers = np.array(centers, dtype=float)

        for _ in range(max_iter):
            dists = np.sum(
                (X[:, None, :] - centers[None, :, :]) ** 2, axis=2
            )
            labels = dists.argmin(axis=1)
            new_centers = centers.copy()
            for k in range(K):
                mask = labels == k
                if mask.any():
                    new_centers[k] = X[mask].mean(axis=0)
            if np.allclose(new_centers, centers, atol=1e-8):
                centers = new_centers
                break
            centers = new_centers
        return centers

    def _init_params(self, X):
        n_samples, n_features = X.shape
        K = self.n_states
        rng = np.random.default_rng(self.random_state)

        self.means_ = self._kmeans_init(X, rng)

        global_var = X.var(axis=0) if n_samples > 1 else np.ones(n_features)
        global_var = np.maximum(global_var, self.min_covar)
        self.covars_ = np.tile(global_var, (K, 1))

        self.startprob_ = np.full(K, 1.0 / K)

        # Persistent transition (diagonal dominant) reflects our prior
        # that regimes don't flip every bar.
        self.transmat_ = np.full((K, K), 0.05 / max(K - 1, 1))
        np.fill_diagonal(self.transmat_, 0.95)
        if K == 1:
            self.transmat_ = np.ones((1, 1))

    # ── Emission log-probabilities ────────────────────────────
    def _log_gaussian(self, X):
        T, D = X.shape
        K = self.n_states
        log_B = np.empty((T, K))
        for k in range(K):
            var = np.maximum(self.covars_[k], self.min_covar)
            diff = X - self.means_[k]
            log_B[:, k] = -0.5 * np.sum(
                np.log(2.0 * np.pi * var) + (diff * diff) / var, axis=1
            )
        return log_B

    # ── Forward (log-space) ───────────────────────────────────
    def _forward(self, log_B):
        T, K = log_B.shape
        log_pi = np.log(self.startprob_ + self._LOG_ZERO_EPS)
        log_A = np.log(self.transmat_ + self._LOG_ZERO_EPS)
        log_alpha = np.empty((T, K))
        log_alpha[0] = log_pi + log_B[0]
        for t in range(1, T):
            log_alpha[t] = logsumexp(log_alpha[t - 1, :, None] + log_A, axis=0) + log_B[t]
        ll = logsumexp(log_alpha[-1])
        return log_alpha, ll

    # ── Backward (log-space) ──────────────────────────────────
    def _backward(self, log_B):
        T, K = log_B.shape
        log_A = np.log(self.transmat_ + self._LOG_ZERO_EPS)
        log_beta = np.zeros((T, K))
        for t in range(T - 2, -1, -1):
            log_beta[t] = logsumexp(
                log_A + (log_B[t + 1] + log_beta[t + 1])[None, :], axis=1
            )
        return log_beta

    # ── Fit via Baum-Welch ────────────────────────────────────
    def fit(self, X):
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if X.shape[0] == 1 and X.shape[1] != 1 and X.ndim == 2:
            # Treat 1-D input as column vector
            pass
        if X.ndim == 1:
            X = X.reshape(-1, 1)

        # Cache consult — avoid re-fitting across walk-forward folds.
        from core.hmm_cache import compute_cache_key, cache_get, cache_set
        _params = {
            "n_states": self.n_states,
            "n_iter": self.n_iter,
            "tol": self.tol,
            "random_state": self.random_state,
            "min_covar": self.min_covar,
        }
        _key = compute_cache_key(X, _params)
        _cached = cache_get(_key)
        if _cached is not None:
            self.means_ = _cached["means_"].copy()
            self.covars_ = _cached["covars_"].copy()
            self.transmat_ = _cached["transmat_"].copy()
            self.startprob_ = _cached["startprob_"].copy()
            return self

        self._init_params(X)
        n_samples = X.shape[0]
        K = self.n_states

        if n_samples < 2 or K == 1:
            # No .copy() here — cache_get copies on retrieval to protect
            # cached state from caller mutation, which is the stronger
            # guarantee. Skipping the copy on set saves 4 allocs per miss.
            cache_set(_key, {
                "means_": self.means_,
                "covars_": self.covars_,
                "transmat_": self.transmat_,
                "startprob_": self.startprob_,
            })
            return self

        prev_ll = -np.inf
        for _ in range(self.n_iter):
            log_B = self._log_gaussian(X)
            log_alpha, ll = self._forward(log_B)
            log_beta = self._backward(log_B)

            # Posteriors gamma_t(k)
            log_gamma = log_alpha + log_beta
            log_gamma -= logsumexp(log_gamma, axis=1, keepdims=True)
            gamma = np.exp(log_gamma)

            # Pairwise posteriors xi_t(i,j), t = 0..T-2
            log_A = np.log(self.transmat_ + self._LOG_ZERO_EPS)
            log_xi = (
                log_alpha[:-1, :, None]
                + log_A[None, :, :]
                + log_B[1:, None, :]
                + log_beta[1:, None, :]
                - ll
            )
            # Sum over time in log-space -> (K, K)
            xi_sum = np.exp(logsumexp(log_xi, axis=0))

            # M-step
            self.startprob_ = gamma[0] / max(gamma[0].sum(), self._LOG_ZERO_EPS)
            denom = xi_sum.sum(axis=1, keepdims=True)
            denom = np.where(denom > 0, denom, 1.0)
            self.transmat_ = xi_sum / denom

            gamma_sum = gamma.sum(axis=0)
            gamma_sum_safe = np.where(gamma_sum > 0, gamma_sum, 1.0)
            self.means_ = (gamma.T @ X) / gamma_sum_safe[:, None]
            for k in range(K):
                diff = X - self.means_[k]
                self.covars_[k] = (gamma[:, k, None] * diff * diff).sum(axis=0) / gamma_sum_safe[k]
                self.covars_[k] = np.maximum(self.covars_[k], self.min_covar)

            # Convergence: relative log-likelihood improvement
            if np.isfinite(prev_ll) and abs(ll - prev_ll) < self.tol * max(abs(ll), 1.0):
                break
            prev_ll = ll

        # No .copy() here — defensive copy happens on cache_get.
        cache_set(_key, {
            "means_": self.means_,
            "covars_": self.covars_,
            "transmat_": self.transmat_,
            "startprob_": self.startprob_,
        })
        return self

    # ── Inference ─────────────────────────────────────────────
    def predict_proba(self, X):
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        log_B = self._log_gaussian(X)
        log_alpha, _ = self._forward(log_B)
        log_beta = self._backward(log_B)
        log_gamma = log_alpha + log_beta
        log_gamma -= logsumexp(log_gamma, axis=1, keepdims=True)
        return np.exp(log_gamma)

    def predict(self, X):
        """Viterbi decoding: most likely state sequence."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        if X.ndim == 1:
            X = X.reshape(-1, 1)
        log_B = self._log_gaussian(X)
        T, K = log_B.shape
        log_pi = np.log(self.startprob_ + self._LOG_ZERO_EPS)
        log_A = np.log(self.transmat_ + self._LOG_ZERO_EPS)
        delta = np.full((T, K), -np.inf)
        psi = np.zeros((T, K), dtype=int)
        delta[0] = log_pi + log_B[0]
        for t in range(1, T):
            tmp = delta[t - 1, :, None] + log_A
            psi[t] = tmp.argmax(axis=0)
            delta[t] = tmp.max(axis=0) + log_B[t]
        states = np.zeros(T, dtype=int)
        states[-1] = int(delta[-1].argmax())
        for t in range(T - 2, -1, -1):
            states[t] = psi[t + 1, states[t + 1]]
        return states


# ══════════════════════════════════════════════════════════════
#  enrich_with_regime — engine-facing HMM wrapper
# ══════════════════════════════════════════════════════════════
HMM_COLS = [
    "hmm_regime", "hmm_regime_label",
    "hmm_prob_bull", "hmm_prob_bear", "hmm_prob_chop",
    "hmm_confidence",
]


def _build_hmm_backend(n_states: int, random_state: int = 42):
    """Prefer hmmlearn.GaussianHMM when available, else fall back to
    the numpy-pure GaussianHMMNp implemented above."""
    if _HAS_HMM:
        return GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=100,
            random_state=random_state,
            verbose=False,
        )
    return GaussianHMMNp(
        n_states=n_states,
        random_state=random_state,
        n_iter=100,
    )


def enrich_with_regime(df: pd.DataFrame,
                       n_states: int | None = None,
                       lookback: int | None = None) -> pd.DataFrame:
    """Attach HMM regime columns to ``df`` in place-safe fashion.

    Columns added (all float / object, NaN where unavailable):
        hmm_regime        : int state index under the internal permutation
        hmm_regime_label  : "BULL" / "BEAR" / "CHOP"
        hmm_prob_bull     : posterior P(bull | observations)
        hmm_prob_bear     : posterior P(bear | observations)
        hmm_prob_chop     : posterior P(chop | observations)
        hmm_confidence    : max of the three probabilities

    Behaviour:
        - Idempotent: if every column already exists, returns ``df`` untouched.
        - Graceful: missing ``close``, empty frame, or training failure
          leave the HMM columns as NaN instead of raising.
        - Trains the HMM ONCE per call using the last ``lookback`` bars
          and then predicts posteriors over the full frame — no per-bar
          retraining.

    This function is the single entry point every engine should call
    AFTER ``indicators(df)`` and BEFORE its trade loop.
    """
    # Params are loaded lazily so tests / standalone usage don't require
    # the full config import chain when they pass explicit values.
    if n_states is None or lookback is None:
        try:
            from config.params import CHRONOS_HMM_REGIMES, CHRONOS_HMM_LOOKBACK
            n_states = n_states or CHRONOS_HMM_REGIMES
            lookback = lookback or CHRONOS_HMM_LOOKBACK
        except Exception:
            n_states = n_states or 3
            lookback = lookback or 500

    if all(c in df.columns for c in HMM_COLS):
        return df

    df = df.copy()
    df["hmm_regime"] = np.nan
    df["hmm_regime_label"] = None
    df["hmm_prob_bull"] = np.nan
    df["hmm_prob_bear"] = np.nan
    df["hmm_prob_chop"] = np.nan
    df["hmm_confidence"] = np.nan

    if len(df) == 0 or "close" not in df.columns:
        return df

    min_warmup = max(n_states * 20, 80)
    if len(df) < min_warmup:
        log.warning(f"HMM skipped: {len(df)} bars < {min_warmup} min warmup")
        return df

    try:
        close = df["close"].astype(float).values
        returns = np.zeros_like(close)
        returns[1:] = np.log(close[1:] / np.maximum(close[:-1], 1e-12))
        returns = np.nan_to_num(returns, nan=0.0, posinf=0.0, neginf=0.0)

        vol = (
            pd.Series(returns).rolling(20, min_periods=5).std()
            .bfill().fillna(0.01).values
        )

        n = len(df)
        start = max(0, n - lookback)
        X_train = np.column_stack([returns[start:], vol[start:]])
        X_train = X_train[np.isfinite(X_train).all(axis=1)]

        if len(X_train) < min_warmup:
            return df

        model = _build_hmm_backend(n_states=n_states)
        model.fit(X_train)

        # [FIX] Predict ONLY on the training window (start..end) to
        # eliminate look-ahead bias.  Bars before `start` stay NaN —
        # they have no causal regime estimate.
        X_pred = np.column_stack([returns[start:], vol[start:]])
        X_pred = np.nan_to_num(X_pred, nan=0.0, posinf=0.0, neginf=0.0)
        proba = model.predict_proba(X_pred)

        # Map internal state indices to BEAR/CHOP/BULL by sorting on the
        # first feature (mean return): lowest = BEAR, highest = BULL.
        state_means = np.asarray(model.means_)[:, 0]
        order = np.argsort(state_means)

        # Build full-length probability arrays (NaN before start)
        prob_bear = np.full(n, np.nan)
        prob_bull = np.full(n, np.nan)
        prob_chop = np.full(n, np.nan)

        if n_states >= 3:
            bear_idx = int(order[0])
            bull_idx = int(order[-1])
            chop_idx_set = [int(i) for i in order[1:-1]]
            prob_bear[start:] = proba[:, bear_idx]
            prob_bull[start:] = proba[:, bull_idx]
            prob_chop[start:] = (
                proba[:, chop_idx_set].sum(axis=1) if chop_idx_set else 0.0
            )
        else:
            prob_bear[start:] = proba[:, int(order[0])]
            prob_bull[start:] = proba[:, int(order[-1])]
            prob_chop[start:] = 0.0

        df["hmm_prob_bear"] = prob_bear
        df["hmm_prob_bull"] = prob_bull
        df["hmm_prob_chop"] = prob_chop

        prob_mat = df[["hmm_prob_bear", "hmm_prob_chop", "hmm_prob_bull"]].values
        label_arr = np.array(["BEAR", "CHOP", "BULL"])
        nan_mask = np.isnan(prob_mat).all(axis=1)
        # Fill all-NaN rows with zeros so nanargmax doesn't raise ValueError;
        # the nan_mask overrides these rows to NaN/None afterwards.
        safe_mat = np.where(nan_mask[:, None], 0.0, prob_mat)
        winner = np.nanargmax(safe_mat, axis=1)
        df["hmm_confidence"] = np.where(nan_mask, np.nan, np.nanmax(safe_mat, axis=1))
        df["hmm_regime"] = np.where(nan_mask, np.nan, winner.astype(float))
        df["hmm_regime_label"] = np.where(nan_mask, None, label_arr[winner])

    except Exception as e:
        log.warning(f"enrich_with_regime failed: {e}")

    return df


# ══════════════════════════════════════════════════════════════
#  1. REGIME PROBABILITY — Hidden Markov Model
# ══════════════════════════════════════════════════════════════
def regime_probability(df: pd.DataFrame, n_regimes: int = 3,
                       lookback: int = 500) -> pd.DataFrame:
    """
    Compute continuous regime probabilities using a Gaussian HMM.
    Instead of hard BULL/BEAR/CHOP labels, returns P(bull), P(bear), P(chop).

    Uses returns + volatility as observed features.
    Assigns regime labels by sorting state means (highest return = bull).

    Falls back to NaN if hmmlearn not installed.
    """
    df = df.copy()
    df["regime_p_bull"] = np.nan
    df["regime_p_bear"] = np.nan
    df["regime_p_chop"] = np.nan

    if not _HAS_HMM:
        log.debug("hmmlearn not installed — regime_probability returns NaN")
        return df

    try:
        # Features: log returns + rolling volatility
        returns = np.log(df["close"] / df["close"].shift(1)).fillna(0).values
        vol = pd.Series(returns).rolling(20, min_periods=5).std().fillna(0.01).values

        # Use last `lookback` bars for fitting
        start = max(0, len(df) - lookback)
        X_fit = np.column_stack([returns[start:], vol[start:]])

        # Remove any inf/nan rows
        mask = np.isfinite(X_fit).all(axis=1)
        X_clean = X_fit[mask]

        if len(X_clean) < 50:
            return df

        # Fit HMM
        model = GaussianHMM(
            n_components=n_regimes,
            covariance_type="diag",
            n_iter=100,
            random_state=42,
            verbose=False,
        )
        model.fit(X_clean)

        # Predict probabilities for full series
        X_full = np.column_stack([returns, vol])
        X_full = np.nan_to_num(X_full, 0.0)
        proba = model.predict_proba(X_full)

        # Identify regimes by mean return (bull=highest, bear=lowest, chop=middle)
        state_means = model.means_[:, 0]  # return means
        sorted_idx = np.argsort(state_means)
        bear_idx, chop_idx, bull_idx = sorted_idx[0], sorted_idx[1], sorted_idx[2]

        df["regime_p_bull"] = proba[:, bull_idx]
        df["regime_p_bear"] = proba[:, bear_idx]
        df["regime_p_chop"] = proba[:, chop_idx]

    except Exception as e:
        log.warning(f"HMM regime estimation failed: {e}")

    return df


# ══════════════════════════════════════════════════════════════
#  2. VOLATILITY FORECAST — GARCH(1,1)
# ══════════════════════════════════════════════════════════════
def volatility_forecast(df: pd.DataFrame, horizon: int = 8,
                        lookback: int = 500) -> pd.DataFrame:
    """
    Forecast volatility for next `horizon` candles using GARCH(1,1).
    Allows proactive position sizing (reduce before vol spike, not after).

    Falls back to NaN if arch not installed.
    """
    df = df.copy()
    df["vol_forecast"] = np.nan

    if not _HAS_ARCH:
        log.debug("arch not installed — volatility_forecast returns NaN")
        return df

    try:
        returns = (np.log(df["close"] / df["close"].shift(1)) * 100).fillna(0)

        # Fit on recent data
        start = max(0, len(returns) - lookback)
        data = returns.iloc[start:].values

        if len(data) < 100:
            return df

        model = arch_model(data, vol="Garch", p=1, q=1, mean="Zero", rescale=False)
        res = model.fit(disp="off", show_warning=False)

        # Forecast
        forecasts = res.forecast(horizon=horizon)
        # Use the last fitted variance as the forecast for all rows
        # (in practice, you'd do a rolling forecast, but that's expensive)
        last_var = forecasts.variance.iloc[-1].mean()
        last_vol = np.sqrt(last_var) / 100  # back to decimal

        # Rolling conditional volatility from the fitted model
        cond_vol = res.conditional_volatility / 100

        # Map back to dataframe (only for fitted range)
        df.iloc[start:start+len(cond_vol), df.columns.get_loc("vol_forecast")] = cond_vol.values

        # Forward-fill the forecast for the last few bars
        df["vol_forecast"] = df["vol_forecast"].ffill()

    except Exception as e:
        log.warning(f"GARCH volatility forecast failed: {e}")

    return df


# ══════════════════════════════════════════════════════════════
#  3. MOMENTUM DECAY — Exponential decay rate
# ══════════════════════════════════════════════════════════════
def momentum_decay(df: pd.DataFrame, rsi_period: int = 14,
                   taker_window: int = 20, decay_window: int = 10) -> pd.DataFrame:
    """
    Measure the rate at which current momentum is fading.
    Detects when a trend is losing force BEFORE it reverses.

    Feeding rate = d(RSI)/dt + d(taker_ratio)/dt
    Positive = momentum building, Negative = momentum fading

    No external dependencies — pure numpy/pandas.
    """
    df = df.copy()

    # RSI rate of change (derivative)
    if "rsi" not in df.columns:
        # Simple RSI calculation if not present
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
    else:
        rsi = df["rsi"]

    rsi_slope = rsi.diff(decay_window) / decay_window  # d(RSI)/dt

    # Taker buy ratio rate of change
    if "tbb" in df.columns and "vol" in df.columns:
        taker_ratio = df["tbb"] / df["vol"].replace(0, np.nan)
        taker_slope = taker_ratio.rolling(taker_window).mean().diff(decay_window) / decay_window
    else:
        taker_slope = pd.Series(0.0, index=df.index)

    # Normalize both to similar scale
    rsi_z = (rsi_slope - rsi_slope.rolling(100, min_periods=20).mean()) / \
            rsi_slope.rolling(100, min_periods=20).std().replace(0, 1)
    taker_z = (taker_slope - taker_slope.rolling(100, min_periods=20).mean()) / \
              taker_slope.rolling(100, min_periods=20).std().replace(0, 1)

    # Composite momentum decay signal
    df["momentum_decay"] = (0.6 * rsi_z + 0.4 * taker_z).clip(-3, 3)
    df["momentum_decay"] = df["momentum_decay"].fillna(0)

    return df


# ══════════════════════════════════════════════════════════════
#  4. FRACTAL DIMENSION — Rolling Hurst Exponent
# ══════════════════════════════════════════════════════════════
def hurst_rolling(df: pd.DataFrame, window: int = 100,
                  min_periods: int = 50) -> pd.DataFrame:
    """
    Rolling Hurst exponent using R/S analysis.
    H > 0.5 = trending (good for AZOTH trend-following)
    H < 0.5 = mean-reverting (good for NEWTON pairs/MR)
    H ≈ 0.5 = random walk (don't trade)

    No external dependencies.
    """
    df = df.copy()
    prices = np.log(df["close"].values)
    n = len(prices)
    hurst_vals = np.full(n, np.nan)

    for i in range(min_periods, n):
        start = max(0, i - window)
        series = prices[start:i+1]

        if len(series) < min_periods:
            continue

        try:
            # R/S analysis
            mean_val = np.mean(series)
            deviate = np.cumsum(series - mean_val)
            r = np.max(deviate) - np.min(deviate)
            s = np.std(series, ddof=1)

            if s > 0 and r > 0:
                # Simple Hurst estimate: H = log(R/S) / log(n)
                rs = r / s
                hurst_vals[i] = np.log(rs) / np.log(len(series))
                hurst_vals[i] = np.clip(hurst_vals[i], 0.0, 1.0)
        except Exception:
            continue

    df["hurst_rolling"] = hurst_vals
    # Smooth with EMA to reduce noise
    df["hurst_rolling"] = df["hurst_rolling"].ewm(span=10, min_periods=5).mean()

    return df


# ══════════════════════════════════════════════════════════════
#  5. SEASONALITY — Hour/Day edge scoring
# ══════════════════════════════════════════════════════════════
def seasonality_score(df: pd.DataFrame, min_samples: int = 30) -> pd.DataFrame:
    """
    Score each bar's time slot based on historical edge.
    Crypto patterns: Asia open, US open, Sunday low vol.

    Computes average return per (hour, day_of_week) bucket.
    Score > 0 = historically positive edge in this time slot.

    No external dependencies.
    """
    df = df.copy()

    if "time" not in df.columns:
        df["seasonality_score"] = 0.0
        return df

    times = pd.to_datetime(df["time"])
    returns = df["close"].pct_change().fillna(0)

    # Build lookup: (hour, dow) -> mean return
    hours = times.dt.hour
    dows = times.dt.dayofweek  # 0=Monday

    edge_map = {}
    for h in range(24):
        for d in range(7):
            mask = (hours == h) & (dows == d)
            slot_returns = returns[mask]
            if len(slot_returns) >= min_samples:
                mean_ret = slot_returns.mean()
                std_ret = slot_returns.std()
                # Z-score of mean return (is this slot significantly positive/negative?)
                if std_ret > 0:
                    edge_map[(h, d)] = mean_ret / std_ret * np.sqrt(len(slot_returns))
                else:
                    edge_map[(h, d)] = 0.0
            else:
                edge_map[(h, d)] = 0.0

    # Map scores back to dataframe
    scores = np.array([edge_map.get((h, d), 0.0)
                       for h, d in zip(hours, dows)])

    # Normalize to [-1, 1]
    if np.std(scores) > 0:
        scores = scores / (np.abs(scores).max() + 0.001)

    df["seasonality_score"] = np.clip(scores, -1.0, 1.0)

    return df


# ══════════════════════════════════════════════════════════════
#  MAIN CLASS — Unified Feature Generator
# ══════════════════════════════════════════════════════════════
class ChronosFeatures:
    """
    Unified interface for all Chronos time-series features.
    Call enrich(df) to add all features to a DataFrame.
    Each feature degrades gracefully if dependencies are missing.
    """

    def __init__(self, enable_hmm: bool = True, enable_garch: bool = True,
                 enable_momentum: bool = True, enable_hurst: bool = True,
                 enable_seasonality: bool = True):
        self.enable_hmm = enable_hmm and _HAS_HMM
        self.enable_garch = enable_garch and _HAS_ARCH
        self.enable_momentum = enable_momentum
        self.enable_hurst = enable_hurst
        self.enable_seasonality = enable_seasonality

        features = []
        if self.enable_hmm: features.append("HMM-regime")
        if self.enable_garch: features.append("GARCH-vol")
        if self.enable_momentum: features.append("momentum-decay")
        if self.enable_hurst: features.append("hurst")
        if self.enable_seasonality: features.append("seasonality")

        log.info(f"  Chronos initialized: {', '.join(features) if features else 'no features'}")
        if not _HAS_HMM:
            log.info("    hmmlearn not installed — regime probability disabled (pip install hmmlearn)")
        if not _HAS_ARCH:
            log.info("    arch not installed — GARCH forecast disabled (pip install arch)")

    def enrich(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add all enabled Chronos features to the DataFrame.
        Call AFTER indicators() and BEFORE scan_symbol().

        Adds columns:
          - regime_p_bull, regime_p_bear, regime_p_chop
          - vol_forecast
          - momentum_decay
          - hurst_rolling
          - seasonality_score
        """
        if self.enable_hmm:
            df = regime_probability(df)

        if self.enable_garch:
            df = volatility_forecast(df)

        if self.enable_momentum:
            df = momentum_decay(df)

        if self.enable_hurst:
            df = hurst_rolling(df)

        if self.enable_seasonality:
            df = seasonality_score(df)

        return df

    @staticmethod
    def available_features() -> dict[str, bool]:
        """Report which features are available."""
        return {
            "regime_probability (HMM)": _HAS_HMM,
            "volatility_forecast (GARCH)": _HAS_ARCH,
            "momentum_decay": True,
            "hurst_rolling": True,
            "seasonality_score": True,
        }


# ══════════════════════════════════════════════════════════════
#  STANDALONE TEST
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from core.data import fetch
    from core.indicators import indicators

    print("\n  CHRONOS — Time-Series Intelligence Layer")
    print("  " + "=" * 45)

    # Show available features
    print("\n  Available features:")
    for feat, ok in ChronosFeatures.available_features().items():
        status = "OK" if ok else "MISSING (install dependency)"
        print(f"    {feat}: {status}")

    # Test with real data
    print("\n  Fetching BTCUSDT 15m (30 days) for testing...")
    df = fetch("BTCUSDT", n_candles=2880)

    if df is not None and len(df) > 100:
        print(f"  Got {len(df)} candles")

        # Apply standard indicators first
        df = indicators(df)

        # Apply Chronos features
        chronos = ChronosFeatures()
        df = chronos.enrich(df)

        # Show sample of added columns
        chronos_cols = ["regime_p_bull", "regime_p_bear", "regime_p_chop",
                       "vol_forecast", "momentum_decay", "hurst_rolling", "seasonality_score"]

        available_cols = [c for c in chronos_cols if c in df.columns and df[c].notna().any()]

        print(f"\n  Features added: {len(available_cols)}/{len(chronos_cols)}")
        for col in available_cols:
            vals = df[col].dropna()
            print(f"    {col:>20}: mean={vals.mean():.4f}  std={vals.std():.4f}  "
                  f"min={vals.min():.4f}  max={vals.max():.4f}")

        # Show last 5 rows
        if available_cols:
            print(f"\n  Last 5 bars:")
            print(df[available_cols].tail().to_string(index=False))
    else:
        print("  Could not fetch data. Check network connection.")

    print()
