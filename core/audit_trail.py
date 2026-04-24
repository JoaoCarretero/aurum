"""Compatibility shim — redirects core.audit_trail to core.risk.audit_trail.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.risk import audit_trail as _impl
sys.modules[__name__] = _impl
