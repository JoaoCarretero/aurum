"""Compatibility shim — redirects core.htf_filter to core.data.htf_filter."""
import sys as _sys
import importlib as _il

_real = _il.import_module("core.data.htf_filter")
_sys.modules[__name__] = _real
