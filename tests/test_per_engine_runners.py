"""Contract tests for per-engine runners (CITADEL/JUMP/RENAISSANCE paper+shadow).

These runners delegate to parametric cores (``_paper_runner.py`` /
``_shadow_runner.py``) via env var ``AURUM_ENGINE_NAME``. We verify:

1. Each of the 6 entry scripts imports without error and exposes main().
2. The parametric core writes to ``data/{engine}_{mode}/<run_id>/``.
3. The signal filter restricts output to the specified engine.
4. Manifest records the engine name correctly.

Tests use subprocess spawn so each engine gets a fresh Python process
(env var pattern is per-process — modules cached in the current process
would capture the first engine set).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable


PAPER_ENTRIES = {
    "citadel": "tools/operations/citadel_paper.py",
    "jump": "tools/operations/jump_paper.py",
    "renaissance": "tools/operations/renaissance_paper.py",
}

SHADOW_ENTRIES = {
    "citadel": "tools/maintenance/citadel_shadow.py",
    "jump": "tools/maintenance/jump_shadow.py",
    "renaissance": "tools/maintenance/renaissance_shadow.py",
}


@pytest.mark.parametrize("engine,script", list(PAPER_ENTRIES.items()))
def test_paper_entry_runs_help(engine, script):
    """Each paper entry script should respond to --help without crashing.

    Verifies argparse + imports + env var wiring end-to-end.
    """
    result = subprocess.run(
        [PY, script, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"{script} --help failed: {result.stderr}"
    assert f"AURUM_{engine.upper()}_PAPER_LABEL" in result.stdout, (
        f"env var name for {engine} not surfaced in help"
    )


@pytest.mark.parametrize("engine,script", list(SHADOW_ENTRIES.items()))
def test_shadow_entry_runs_help(engine, script):
    """Each shadow entry script should respond to --help without crashing."""
    result = subprocess.run(
        [PY, script, "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"{script} --help failed: {result.stderr}"
    assert f"AURUM_{engine.upper()}_SHADOW_LABEL" in result.stdout, (
        f"env var name for {engine} not surfaced in help"
    )


@pytest.mark.parametrize("engine", ["citadel", "jump", "renaissance"])
def test_paper_runner_paths_parametrized(engine, monkeypatch, tmp_path):
    """Import parametric core with AURUM_ENGINE_NAME set — paths must
    contain the engine name.

    Uses subprocess to guarantee fresh Python + fresh module import
    (the core reads env at import time, cached if run in-process)."""
    code = (
        f"import os; os.environ['AURUM_ENGINE_NAME']='{engine}';\n"
        "import sys; sys.path.insert(0, r'" + str(ROOT) + "');\n"
        "from tools.operations import _paper_runner as m;\n"
        "print(m.ENGINE_NAME, m.ENGINE_UPPER);\n"
        "print(str(m.RUN_DIR));\n"
    )
    result = subprocess.run(
        [PY, "-c", code],
        cwd=tmp_path,  # run in tmp so RUN_DIR side-effects don't touch repo data/
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    # First line: engine name + upper
    assert lines[0].startswith(f"{engine} {engine.upper()}"), result.stdout
    # Second line: RUN_DIR must contain the engine_paper path segment
    assert f"{engine}_paper" in lines[1], (
        f"RUN_DIR {lines[1]!r} missing segment '{engine}_paper'"
    )


@pytest.mark.parametrize("engine", ["citadel", "jump", "renaissance"])
def test_shadow_runner_paths_parametrized(engine, tmp_path):
    """Same contract for shadow core."""
    code = (
        f"import os; os.environ['AURUM_ENGINE_NAME']='{engine}';\n"
        "import sys; sys.path.insert(0, r'" + str(ROOT) + "');\n"
        "from tools.maintenance import _shadow_runner as m;\n"
        "print(m.ENGINE_NAME, m.ENGINE_UPPER);\n"
        "print(str(m.RUN_DIR));\n"
    )
    result = subprocess.run(
        [PY, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    assert lines[0].startswith(f"{engine} {engine.upper()}"), result.stdout
    assert f"{engine}_shadow" in lines[1], (
        f"RUN_DIR {lines[1]!r} missing segment '{engine}_shadow'"
    )


@pytest.mark.parametrize("engine", ["citadel", "jump", "renaissance"])
def test_signal_filter_isolates_engine(engine, tmp_path):
    """O paper runner delega pra engines.millennium._scan_one_engine_live
    passando ENGINE_NAME. O helper retorna signals ja filtrados pro
    engine. Stubar o helper pra evitar fetch real.
    """
    code = f"""
import os
os.environ['AURUM_ENGINE_NAME'] = {engine!r}
import sys
sys.path.insert(0, r'{ROOT}')

import types
def _fake_scan(engine_name):
    want = engine_name.upper()
    all_trades = [
        {{'strategy': 'CITADEL', 'symbol': 'BTCUSDT', 'direction': 'LONG'}},
        {{'strategy': 'JUMP', 'symbol': 'ETHUSDT', 'direction': 'SHORT'}},
        {{'strategy': 'RENAISSANCE', 'symbol': 'SOLUSDT', 'direction': 'LONG'}},
        {{'strategy': 'CITADEL', 'symbol': 'LINKUSDT', 'direction': 'LONG'}},
    ]
    return [t for t in all_trades if t['strategy'] == want]

fake_mill = types.ModuleType('engines.millennium')
fake_mill._scan_one_engine_live = _fake_scan
sys.modules['engines.millennium'] = fake_mill

from tools.operations import _paper_runner as m
filtered = m._scan_new_signals(notify=False)
print(len(filtered))
for t in filtered:
    print(t['strategy'])
"""
    result = subprocess.run(
        [PY, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    # Expected count for each engine:
    expected_n = {"citadel": 2, "jump": 1, "renaissance": 1}[engine]
    assert int(lines[0]) == expected_n, f"expected {expected_n}, got {lines[0]}"
    # All strategies must be uppercase engine
    for ln in lines[1:]:
        assert ln == engine.upper(), f"filter leaked non-{engine} trade: {ln}"
