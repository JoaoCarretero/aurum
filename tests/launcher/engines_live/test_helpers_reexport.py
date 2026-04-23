"""Assert helpers.py re-exports the expected pure symbols from engines_live_helpers."""
from __future__ import annotations


def test_helpers_reexports_format_uptime():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.format_uptime is src.format_uptime


def test_helpers_reexports_assign_bucket():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.assign_bucket is src.assign_bucket


def test_helpers_reexports_cycle_mode():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.cycle_mode is src.cycle_mode


def test_helpers_reexports_load_save_mode():
    from launcher_support.engines_live import helpers as h
    from launcher_support import engines_live_helpers as src

    assert h.load_mode is src.load_mode
    assert h.save_mode is src.save_mode
