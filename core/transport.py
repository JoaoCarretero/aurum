"""Compatibility shim — redirects core.transport to core.data.transport."""
import sys as _sys
import importlib as _il

_real = _il.import_module("core.data.transport")
_sys.modules[__name__] = _real
