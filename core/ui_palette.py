"""Compatibility shim — redirects core.ui_palette to core.ui.ui_palette.
Preserves monkey-patch semantics for tests and runtime via sys.modules.
"""
import sys
from core.ui import ui_palette as _impl
sys.modules[__name__] = _impl
