"""Verify that the shadow runner writes manifest.json on start."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_shadow_writes_manifest_on_help_smoke(tmp_path, monkeypatch):
    """Importing the module + calling the writer yields a valid manifest."""
    monkeypatch.chdir(tmp_path)
    # Simulate being inside ROOT so relative paths work
    # but capture writes to a temp RUN_DIR
    sys.path.insert(0, str(ROOT))
    from core.shadow_contract import Manifest
    from tools.millennium_shadow import _write_manifest  # NEW symbol

    run_dir = tmp_path / "data" / "millennium_shadow" / "2026-04-18_0000"
    (run_dir / "state").mkdir(parents=True)

    _write_manifest(run_dir, run_id="2026-04-18_0000", engine="millennium", mode="shadow")

    payload = json.loads((run_dir / "state" / "manifest.json").read_text())
    m = Manifest(**payload)  # validates shape
    assert m.engine == "millennium"
    assert m.mode == "shadow"
    assert m.commit  # non-empty
    assert m.config_hash.startswith("sha256:")
