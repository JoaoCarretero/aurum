"""Compatibility shim — redirects core.risk_gates to core.risk.risk_gates.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.risk import risk_gates as _impl
sys.modules[__name__] = _impl
