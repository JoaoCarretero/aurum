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
"""
import logging
import numpy as np
import pandas as pd

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
