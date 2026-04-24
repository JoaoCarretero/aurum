"""Entropy logging adherence: scan_hermes must emit `entropy_norm` (raw
normalized Shannon entropy, 0..1) on every trade record so future
divergences between live and backtest are diagnosable.

Why: 2026-04-24 RENAISSANCE live opened LONG RENDERUSDT; replaying the
scan the same day rejected it (entropy=RANDOM, norm=0.94). The live
path must have observed norm<=0.92 at scan time. Without persisting
the raw norm in the trade record we cannot reconstruct whether the
divergence was precision drift in the fetch or a real bug.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import core.harmonics as h


def test_h_entropy_norm_returns_float_in_unit_interval():
    rng = np.random.RandomState(42)
    prices = 100 * (1 + rng.randn(200) * 0.01).cumprod()
    df = pd.DataFrame({"close": prices})
    norm = h._h_entropy_norm(df, idx=150)
    assert isinstance(norm, float)
    assert 0.0 <= norm <= 1.0


def test_h_entropy_norm_returns_none_below_window():
    df = pd.DataFrame({"close": np.linspace(100, 110, 10)})
    assert h._h_entropy_norm(df, idx=5) is None


def test_h_entropy_norm_returns_none_on_flat_series():
    # zero variance → no meaningful bucketing → None
    df = pd.DataFrame({"close": [100.0] * 100})
    assert h._h_entropy_norm(df, idx=60) is None


def test_h_entropy_norm_consistent_with_label():
    """Label derived from norm must match _h_entropy string."""
    rng = np.random.RandomState(7)
    prices = 100 * (1 + rng.randn(200) * 0.02).cumprod()
    df = pd.DataFrame({"close": prices})
    idx = 150
    norm = h._h_entropy_norm(df, idx)
    label = h._h_entropy(df, idx)
    if norm is None:
        assert label == "STRUCTURED"
        return
    if norm > 0.92:
        assert label == "RANDOM"
    elif norm < 0.50:
        assert label == "STRUCTURED"
    else:
        assert label == "TRANSITION"
