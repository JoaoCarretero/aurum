"""Compatibility shim — redirects core.connections to core.data.connections.

This shim ensures that ``import core.connections as cxn`` and
``monkeypatch.setattr(cxn, "STATE_FILE", ...)`` continue to work by
replacing this module with the actual core.data.connections module in
sys.modules at import time.
"""
import sys as _sys
import importlib as _il

_real = _il.import_module("core.data.connections")
_sys.modules[__name__] = _real
