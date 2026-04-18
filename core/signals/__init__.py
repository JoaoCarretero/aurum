"""core.signals — signals subpackage skeleton (Phase 3A).

core/signals.py is a PROTECTED file (Phase 3B will migrate it).
Until then this __init__ loads it via importlib so that both
``from core.signals import decide_direction`` and
``import core.signals`` continue to resolve correctly.
"""
import importlib.util as _ilu
import pathlib as _pl
import sys as _sys

_here = _pl.Path(__file__).parent          # core/signals/
_src  = _here.parent / "signals.py"       # core/signals.py

_spec = _ilu.spec_from_file_location("core._signals_impl", _src)
_mod  = _ilu.module_from_spec(_spec)
_sys.modules["core._signals_impl"] = _mod
_spec.loader.exec_module(_mod)

# Re-export public names into this package namespace.
decide_direction  = _mod.decide_direction    # noqa: F401
score_omega       = _mod.score_omega         # noqa: F401
score_chop        = _mod.score_chop          # noqa: F401
calc_levels       = _mod.calc_levels         # noqa: F401
calc_levels_chop  = _mod.calc_levels_chop    # noqa: F401
label_trade       = _mod.label_trade         # noqa: F401
label_trade_chop  = _mod.label_trade_chop    # noqa: F401

for _name in ("select_symbols", "safe_input", "_liq_prices"):
    if hasattr(_mod, _name):
        globals()[_name] = getattr(_mod, _name)
