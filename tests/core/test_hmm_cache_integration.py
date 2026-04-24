"""End-to-end: GaussianHMMNp.fit hits the cache on repeated calls with same input."""
from __future__ import annotations

import numpy as np
import pytest

from core.chronos import GaussianHMMNp
from core.hmm_cache import cache_clear, cache_stats


@pytest.fixture(autouse=True)
def _reset():
    cache_clear()
    yield
    cache_clear()


def _synth(n: int = 200, d: int = 2, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(size=(n, d))


def test_second_fit_is_cache_hit_and_matches():
    X = _synth()
    m1 = GaussianHMMNp(n_states=3, n_iter=50, random_state=7).fit(X)
    stats1 = cache_stats()
    assert stats1["misses"] == 1
    assert stats1["hits"] == 0

    m2 = GaussianHMMNp(n_states=3, n_iter=50, random_state=7).fit(X)
    stats2 = cache_stats()
    assert stats2["hits"] == 1, stats2
    assert stats2["size"] == 1

    # Outputs are numerically identical on cache hit
    np.testing.assert_array_equal(m1.means_, m2.means_)
    np.testing.assert_array_equal(m1.covars_, m2.covars_)
    np.testing.assert_array_equal(m1.transmat_, m2.transmat_)
    np.testing.assert_array_equal(m1.startprob_, m2.startprob_)


def test_different_params_do_not_collide():
    X = _synth()
    GaussianHMMNp(n_states=3, random_state=1).fit(X)
    GaussianHMMNp(n_states=3, random_state=2).fit(X)
    GaussianHMMNp(n_states=4, random_state=1).fit(X)
    s = cache_stats()
    assert s["misses"] == 3
    assert s["size"] == 3


def test_predict_after_cached_fit_works():
    X = _synth()
    GaussianHMMNp(n_states=3, random_state=7).fit(X)
    m2 = GaussianHMMNp(n_states=3, random_state=7).fit(X)
    y = m2.predict(X)
    assert y.shape == (X.shape[0],)
    assert y.min() >= 0 and y.max() <= 2
