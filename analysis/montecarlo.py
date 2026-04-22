"""AURUM — Monte Carlo simulation (block bootstrap)."""
import random
import numpy as np
from config.params import ACCOUNT_SIZE, MC_N, MC_BLOCK


def monte_carlo(pnl_list, seed=None):
    """Block bootstrap MC. seed=None keeps legacy stochastic behaviour; pass
    an int to make walk-forward/robustness audits reproducible run-to-run.

    Vectorised: block draws stay in the Python RNG loop (so the consumption
    sequence is byte-identical to the prior implementation), but equity
    cumsum + drawdown + percentile aggregations use numpy. Empirically
    ~8-10x faster than the all-python loop; walk-forward batteries that
    call this per window see the bulk of the saving.
    """
    if len(pnl_list) < MC_BLOCK * 2:
        return None
    rng = random.Random(seed) if seed is not None else random
    n = len(pnl_list)
    pnls_arr = np.asarray(pnl_list, dtype=float)

    # Block bootstrap: draw MC_N × ceil(n/MC_BLOCK) starting indices.
    shuffled = np.empty((MC_N, n), dtype=float)
    for sim in range(MC_N):
        parts: list[np.ndarray] = []
        row_len = 0
        while row_len < n:
            s = rng.randint(0, n - MC_BLOCK)
            parts.append(pnls_arr[s:s + MC_BLOCK])
            row_len += MC_BLOCK
        shuffled[sim] = np.concatenate(parts)[:n]

    # Equity curves: ACCOUNT_SIZE prepended so drawdown considers the
    # initial balance as the first peak, matching the legacy loop exactly.
    cumsum = np.cumsum(shuffled, axis=1)
    equity = np.hstack([np.full((MC_N, 1), float(ACCOUNT_SIZE)), ACCOUNT_SIZE + cumsum])

    finals = equity[:, -1]
    running_peaks = np.maximum.accumulate(equity, axis=1)
    safe_peaks = np.where(running_peaks > 0, running_peaks, 1.0)
    dd_pct = np.where(running_peaks > 0, (running_peaks - equity) / safe_peaks * 100.0, 0.0)
    max_dds = dd_pct.max(axis=1)

    finals_sorted = np.sort(finals)
    pct_pos = float(np.sum(finals > ACCOUNT_SIZE)) / MC_N * 100.0
    ror = float(np.sum(finals < ACCOUNT_SIZE * 0.80)) / MC_N * 100.0

    # Paths capped at the first 200 sims to keep the payload size bounded,
    # matching the legacy behaviour of the `if sim < 200` guard.
    paths = equity[:200].tolist()

    return {
        "pct_pos": round(pct_pos, 1),
        "median": round(float(finals_sorted[MC_N // 2]), 2),
        "p5": round(float(finals_sorted[int(MC_N * 0.05)]), 2),
        "p95": round(float(finals_sorted[int(MC_N * 0.95)]), 2),
        "avg_dd": round(float(max_dds.mean()), 2),
        "worst_dd": round(float(max_dds.max()), 2),
        "ror": round(ror, 2),
        "finals": finals_sorted.tolist(),
        "paths": paths,
        "dds": max_dds.tolist(),
    }

