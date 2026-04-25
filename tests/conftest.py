import os
import shutil
import sys
from pathlib import Path

import pytest
import _pytest.pathlib as pytest_pathlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _configure_windows_tk() -> None:
    """Set deterministic Tcl/Tk paths before any tkinter import on Windows."""
    if sys.platform != "win32":
        return
    py_root = Path(sys.executable).resolve().parent
    tcl_root = py_root / "tcl"
    tcl_lib = tcl_root / "tcl8.6"
    tk_lib = tcl_root / "tk8.6"
    if (tcl_lib / "init.tcl").exists():
        os.environ["TCL_LIBRARY"] = str(tcl_lib)
    if (tk_lib / "tk.tcl").exists():
        os.environ["TK_LIBRARY"] = str(tk_lib)


_configure_windows_tk()
os.environ.setdefault("AURUM_DISABLE_BOOT_WORKERS", "1")
os.environ.setdefault("AURUM_TEST_MODE", "1")


# Windows + synced/sandboxed filesystems can deny pytest's dead-symlink
# cleanup scan on basetemp. Disable that best-effort cleanup so the suite
# reports real test results instead of crashing in session teardown.
#
# Wrapped in pytest_sessionstart/finish so the monkey-patch is applied
# AND restored — mutating a private pytest internal at module-import
# time was leaking across pytest invocations in the same Python process
# (e.g., when a test runner reuses the interpreter for multiple
# `pytest.main()` calls, the second invocation found the original
# function gone). Audit 2026-04-25 Lane 4 finding.

_ORIGINAL_CLEANUP_DEAD_SYMLINKS = pytest_pathlib.cleanup_dead_symlinks


def pytest_sessionstart(session):
    pytest_pathlib.cleanup_dead_symlinks = lambda root: None


def pytest_sessionfinish(session, exitstatus):
    pytest_pathlib.cleanup_dead_symlinks = _ORIGINAL_CLEANUP_DEAD_SYMLINKS


TMP_ROOT = Path.home() / ".codex" / "memories" / "aurum.finance" / "pytest_tmp"


class _TmpPathFactory:
    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)
        self._counter = 0

    def mktemp(self, prefix: str) -> Path:
        while True:
            self._counter += 1
            path = self._root / f"{prefix}-{self._counter:04d}"
            try:
                path.mkdir(parents=True, exist_ok=False)
                return path
            except FileExistsError:
                continue


@pytest.fixture(scope="session")
def tmp_path_factory():
    return _TmpPathFactory(TMP_ROOT)


@pytest.fixture
def tmp_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("pytest")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)

@pytest.fixture
def tmp_run(tmp_path_factory):
    base = tmp_path_factory.mktemp("alchemy-run")
    run = base / "data" / "janestreet" / "2026-01-01_0000"
    (run / "state").mkdir(parents=True)
    (run / "logs").mkdir()
    (run / "reports").mkdir()
    yield run


# ═══ Session-scoped OHLCV fixtures ═══════════════════════════════
# Synthetic OHLCV data loaded once per session. Tests that need a
# mutable DataFrame should call .copy() inline to avoid polluting the
# shared instance.
#
# numpy/pandas imports are deferred inside _build_ohlcv so that tests
# not requesting these fixtures don't pay the import cost at conftest
# collection time — mirrors the B4 lazy-init philosophy.


def _build_ohlcv(n_bars: int, seed: int):
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n_bars))
    high = close + np.abs(rng.normal(0, 0.3, n_bars))
    low = close - np.abs(rng.normal(0, 0.3, n_bars))
    open_ = np.concatenate(([close[0]], close[:-1]))
    volume = rng.integers(1_000, 10_000, n_bars).astype(float)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="15min")
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )


@pytest.fixture(scope="session")
def ohlcv_500():
    """500-bar synthetic OHLCV DataFrame. Shared; caller must .copy() if mutating."""
    return _build_ohlcv(500, seed=42)


@pytest.fixture(scope="session")
def ohlcv_2000():
    """2000-bar synthetic OHLCV DataFrame. Shared; caller must .copy() if mutating."""
    return _build_ohlcv(2000, seed=42)
