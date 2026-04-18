"""Compatibility shim — redirects core.cache to core.data.cache.

This shim ensures that ``from core import cache`` and
``monkeypatch.setattr(cache, "CACHE_DIR", ...)`` continue to work by
replacing this module with the actual core.data.cache module in
sys.modules at import time.
"""
import sys as _sys
import importlib as _il

# Import the real module.
_real = _il.import_module("core.data.cache")

# Replace this shim in sys.modules so consumers get the real module object.
_sys.modules[__name__] = _real
