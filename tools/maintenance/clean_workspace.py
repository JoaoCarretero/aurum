from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.ops.fs import robust_rmtree  # noqa: E402

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


def iter_targets(*, root: Path = ROOT) -> list[Path]:
    targets: set[Path] = set()
    for pattern in DIR_PATTERNS:
        targets.update(path for path in root.rglob(pattern) if path.is_dir())
    for pattern in GLOB_PATTERNS:
        targets.update(path for path in root.glob(pattern) if path.is_dir())
        targets.update(path for path in root.rglob(pattern) if path.is_dir())
    tmp_dir = root / "tests" / "_tmp"
    if tmp_dir.is_dir():
        targets.add(tmp_dir)
    return sorted(targets)


def clean(*, root: Path = ROOT, apply: bool = True) -> tuple[int, int]:
    removed = 0
    skipped = 0
    root_resolved = root.resolve()
    for path in iter_targets(root=root):
        try:
            rel = path.resolve().relative_to(root_resolved)
        except ValueError:
            print(f"skip outside workspace: {path}")
            skipped += 1
            continue

        if not apply:
            print(f"would remove {rel}")
            skipped += 1
            continue

        # robust_rmtree handles Windows/OneDrive file locks with retry logic.
        if robust_rmtree(path):
            print(f"removed {rel}")
            removed += 1
        else:
            print(f"skip {rel}: robust_rmtree failed")
            skipped += 1
    return removed, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Clean local pytest/cache workspace trash safely.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually remove matched directories. Default is dry-run.",
    )
    args = parser.parse_args(argv)

    removed, skipped = clean(apply=args.apply)
    print(f"done removed={removed} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
