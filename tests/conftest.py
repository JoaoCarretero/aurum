import shutil
import sys
from pathlib import Path

import pytest
import _pytest.pathlib as pytest_pathlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Windows + synced/sandboxed filesystems can deny pytest's dead-symlink
# cleanup scan on basetemp. Disable that best-effort cleanup so the suite
# reports real test results instead of crashing in session teardown.
pytest_pathlib.cleanup_dead_symlinks = lambda root: None

TMP_ROOT = ROOT / "tests" / "_tmp"


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
