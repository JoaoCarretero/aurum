"""In-memory cache for GaussianHMMNp fit results.

Keyed by sha1(X-summary, sorted-params). Hit returns a dict with the
trained HMM state. Miss returns None.

Optional disk persistence: if env AURUM_HMM_CACHE_PERSIST=1, payloads are
pickled under data/_cache/hmm/<key>.pkl (gitignored). No eviction — the
cache is intended for within-session reuse during walk-forward batteries.

Clear manually with core.hmm_cache.cache_clear() or
tools/maintenance/clear_hmm_cache.py.
"""
from __future__ import annotations

import hashlib
import os
import pickle
from pathlib import Path
from typing import Any, Optional

import numpy as np

_CACHE: dict[str, dict[str, Any]] = {}
_STATS = {"hits": 0, "misses": 0}

_PERSIST_DIR = Path(__file__).resolve().parent.parent / "data" / "_cache" / "hmm"


def _persist_enabled() -> bool:
    return os.environ.get("AURUM_HMM_CACHE_PERSIST", "").strip() in ("1", "true", "yes")


def compute_cache_key(X: np.ndarray, params: dict[str, Any]) -> str:
    """sha1 over array shape/dtype/first+last rows + sorted params repr."""
    X = np.asarray(X)
    h = hashlib.sha1()
    h.update(str(X.shape).encode())
    h.update(str(X.dtype).encode())
    if X.size:
        # Include first & last rows + a few checksums — enough entropy
        # to detect any realistic re-fit scenario.
        h.update(X[0].tobytes())
        h.update(X[-1].tobytes())
        h.update(str(float(X.sum())).encode())
        h.update(str(float(np.var(X))).encode())
    # Sorted params for deterministic hashing
    for k in sorted(params.keys()):
        h.update(f"{k}={params[k]!r}".encode())
    return h.hexdigest()


def cache_get(key: str) -> Optional[dict[str, Any]]:
    val = _CACHE.get(key)
    if val is not None:
        _STATS["hits"] += 1
        return val
    if _persist_enabled():
        p = _PERSIST_DIR / f"{key}.pkl"
        if p.exists():
            try:
                val = pickle.loads(p.read_bytes())
                _CACHE[key] = val
                _STATS["hits"] += 1
                return val
            except Exception:
                pass
    _STATS["misses"] += 1
    return None


def cache_set(key: str, payload: dict[str, Any]) -> None:
    _CACHE[key] = payload
    if _persist_enabled():
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        (_PERSIST_DIR / f"{key}.pkl").write_bytes(pickle.dumps(payload))


def cache_clear() -> None:
    _CACHE.clear()
    _STATS["hits"] = 0
    _STATS["misses"] = 0


def cache_stats() -> dict[str, int]:
    return {"hits": _STATS["hits"], "misses": _STATS["misses"], "size": len(_CACHE)}
