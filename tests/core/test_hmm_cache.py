"""Unit tests for the Gaussian HMM fit-result cache."""
from __future__ import annotations

import numpy as np
import pytest

from core.hmm_cache import (
    compute_cache_key,
    cache_get,
    cache_set,
    cache_clear,
    cache_stats,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    cache_clear()
    yield
    cache_clear()


def test_cache_key_is_deterministic():
    X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
    params = {"n_states": 3, "n_iter": 100, "tol": 1e-4, "random_state": 7, "min_covar": 1e-6}
    k1 = compute_cache_key(X, params)
    k2 = compute_cache_key(X, params)
    assert k1 == k2
    assert isinstance(k1, str)
    assert len(k1) == 40  # sha1 hex


def test_cache_key_differs_on_data_change():
    X1 = np.array([[1.0, 2.0], [3.0, 4.0]])
    X2 = np.array([[1.0, 2.0], [3.0, 5.0]])  # last value differs
    params = {"n_states": 3}
    assert compute_cache_key(X1, params) != compute_cache_key(X2, params)


def test_cache_key_differs_on_params_change():
    X = np.array([[1.0, 2.0], [3.0, 4.0]])
    assert compute_cache_key(X, {"n_states": 3}) != compute_cache_key(X, {"n_states": 4})


def test_get_missing_returns_none():
    assert cache_get("nonexistent") is None


def test_set_and_get_roundtrip():
    payload = {"means_": np.zeros((3, 2)), "covars_": np.ones((3, 2)), "transmat_": np.eye(3), "startprob_": np.ones(3) / 3}
    cache_set("abc123", payload)
    got = cache_get("abc123")
    assert got is not None
    np.testing.assert_array_equal(got["means_"], payload["means_"])
    np.testing.assert_array_equal(got["covars_"], payload["covars_"])


def test_stats_count_hits_and_misses():
    cache_clear()
    assert cache_stats() == {"hits": 0, "misses": 0, "size": 0}
    cache_get("nothing")
    assert cache_stats()["misses"] == 1
    cache_set("x", {"means_": np.zeros(1)})
    cache_get("x")
    assert cache_stats()["hits"] == 1
    assert cache_stats()["size"] == 1
