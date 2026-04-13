"""Summarize Phase C capture coverage from fixture files.

Support-only utility. Reads the Phase C manifest plus any captured fixture
payloads already written under tests/fixtures/phase_c/captures and prints a
compact JSON report to stdout.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PHASE_C_ROOT = ROOT / "tests" / "fixtures" / "phase_c"
MANIFEST_PATH = PHASE_C_ROOT / "capture_manifest.json"
CAPTURES_ROOT = PHASE_C_ROOT / "captures"


def _safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_report() -> dict:
    manifest = _safe_read_json(MANIFEST_PATH) or {}
    capture_counts: dict[str, int] = {}
    latest_files: dict[str, str] = {}

    if CAPTURES_ROOT.exists():
        for surface_dir in sorted(p for p in CAPTURES_ROOT.iterdir() if p.is_dir()):
            files = sorted(surface_dir.glob("*.json"))
            capture_counts[surface_dir.name] = len(files)
            if files:
                latest_files[surface_dir.name] = str(files[-1].relative_to(ROOT))

    entries = []
    for entry in manifest.get("entries", []):
        if not isinstance(entry, dict):
            continue
        surface = str(entry.get("surface", ""))
        merged = dict(entry)
        merged["capture_count"] = capture_counts.get(surface, 0)
        merged["latest_capture"] = latest_files.get(surface)
        entries.append(merged)

    return {
        "manifest_path": str(MANIFEST_PATH.relative_to(ROOT)),
        "captures_root": str(CAPTURES_ROOT.relative_to(ROOT)),
        "entries": entries,
    }


def main() -> int:
    print(json.dumps(build_report(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
