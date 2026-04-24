"""Compatibility shim — redirects core.alchemy_state to core.arb.alchemy_state.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.arb import alchemy_state as _impl
sys.modules[__name__] = _impl
