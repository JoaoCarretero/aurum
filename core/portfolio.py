"""Compatibility shim — redirects core.portfolio to core.risk.portfolio.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.risk import portfolio as _impl
sys.modules[__name__] = _impl
