"""Ensures core package does not eagerly import pandas or heavy submodules.

The goal: `from core.ui.ui_palette import BG` should not load core.data or
pandas just to get a color constant. PEP 562 __getattr__ makes core's
top-level re-exports on-demand.
"""
from __future__ import annotations

import subprocess
import sys


def _import_and_probe(probe_expr: str, target_modules: list[str]) -> dict[str, bool]:
    """Run probe in a clean subprocess; return which target modules got loaded."""
    targets = ",".join(f"'{m}'" for m in target_modules)
    code = f"""
import sys
{probe_expr}
result = {{m: (m in sys.modules) for m in [{targets}]}}
import json
print(json.dumps(result))
"""
    out = subprocess.check_output([sys.executable, "-c", code], text=True)
    import json
    return json.loads(out.strip().splitlines()[-1])


def test_ui_palette_does_not_load_pandas():
    loaded = _import_and_probe(
        "from core.ui.ui_palette import BG",
        ["pandas", "core.data", "core.indicators", "core.signals"],
    )
    # Post-fix: none of these should be loaded just to get a color.
    assert not loaded["pandas"], "pandas eagerly loaded by core.ui.ui_palette"
    assert not loaded["core.data"], "core.data eagerly loaded"
    assert not loaded["core.indicators"], "core.indicators eagerly loaded"
    assert not loaded["core.signals"], "core.signals eagerly loaded"


def test_core_still_exposes_top_level_names_on_access():
    loaded = _import_and_probe(
        "import core; _ = core.fetch; _ = core.indicators",
        ["pandas", "core.data", "core.indicators"],
    )
    # After accessing core.fetch and core.indicators, those modules ARE loaded.
    assert loaded["core.indicators"]
    assert loaded["core.data"]
