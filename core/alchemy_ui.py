"""Compatibility shim — redirects core.alchemy_ui to core.ui.alchemy_ui.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ui import alchemy_ui as _impl
sys.modules[__name__] = _impl
