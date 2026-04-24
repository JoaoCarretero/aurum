"""Compatibility shim — redirects core.failure_policy to core.risk.failure_policy.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.risk import failure_policy as _impl
sys.modules[__name__] = _impl
