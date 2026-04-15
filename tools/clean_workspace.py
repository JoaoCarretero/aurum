from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.fs import robust_rmtree  # noqa: E402

DIR_PATTERNS = (
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    ".pytest_local_tmp",
    ".test_tmp",
)

GLOB_PATTERNS = (
    ".pytest_tmp_*",
    "pytest-cache-files-*",
    "pytest-run-*",
    "pytest_tmp_local*",
)


def iter_targets() -> list[Path]:
    targets: set[Path] = set()
    for pattern in DIR_PATTERNS:
        targets.update(path for path in ROOT.rglob(pattern) if path.is_dir())
    for pattern in GLOB_PATTERNS:
        targets.update(path for path in ROOT.glob(pattern) if path.is_dir())
        targets.update(path for path in ROOT.rglob(pattern) if path.is_dir())
    tmp_dir = ROOT / "tests" / "_tmp"
    if tmp_dir.is_dir():
        targets.add(tmp_dir)
    return sorted(targets)


def main() -> int:
    removed = 0
    skipped = 0
    for path in iter_targets():
        try:
            path.resolve().relative_to(ROOT.resolve())
        except ValueError:
            print(f"skip outside workspace: {path}")
            skipped += 1
            continue

        # robust_rmtree contorna locks/perms de OneDrive/Windows via
        # chmod + retry com pause — e nao levanta excecao.
        if robust_rmtree(path):
            print(f"removed {path.relative_to(ROOT)}")
            removed += 1
        else:
            print(f"skip {path.relative_to(ROOT)}: robust_rmtree failed")
            skipped += 1

    print(f"done removed={removed} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
