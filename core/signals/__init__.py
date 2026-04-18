"""core.signals — signals subpackage skeleton (Phase 3A).

core/signals.py is a PROTECTED file (Phase 3B will migrate it to
core/signals/base.py). Until then this __init__ loads it via importlib
and replaces core.signals in sys.modules with the real module object,
so that monkeypatch, attribute writes (e.g. prepare_htf patching params),
and all imports resolve against the actual signals module.
"""
import importlib.util as _ilu
import pathlib as _pl
import sys as _sys

_here = _pl.Path(__file__).parent          # core/signals/
_src  = _here.parent / "signals.py"       # core/signals.py  (protected)

_spec = _ilu.spec_from_file_location("core.signals", _src)
_mod  = _ilu.module_from_spec(_spec)

# Register before exec so circular imports (if any) resolve correctly.
_sys.modules["core.signals"] = _mod
_spec.loader.exec_module(_mod)
