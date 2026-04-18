"""Compatibility shim — redirects core.exchange_api to core.data.exchange_api."""
import sys as _sys
import importlib as _il

_real = _il.import_module("core.data.exchange_api")
_sys.modules[__name__] = _real
