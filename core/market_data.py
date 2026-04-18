"""Compatibility shim — redirects core.market_data to core.data.market_data."""
import sys as _sys
import importlib as _il

_real = _il.import_module("core.data.market_data")
_sys.modules[__name__] = _real
