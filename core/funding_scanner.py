"""Compatibility shim — redirects core.funding_scanner to core.ui.funding_scanner.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ui import funding_scanner as _impl
sys.modules[__name__] = _impl
