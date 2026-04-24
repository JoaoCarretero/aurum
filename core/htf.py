"""Compatibility shim — redirects core.htf to core.data.htf."""
import sys as _sys
import importlib as _il

_real = _il.import_module("core.data.htf")
_sys.modules[__name__] = _real
