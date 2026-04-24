"""Compatibility shim — redirects core.db to core.ops.db.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ops import db as _impl
sys.modules[__name__] = _impl
