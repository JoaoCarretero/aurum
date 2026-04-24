"""Compatibility shim — redirects core.key_store to core.risk.key_store.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.risk import key_store as _impl
sys.modules[__name__] = _impl
