"""Screen manager infrastructure for the launcher.

Keep package import lightweight: concrete screen classes stay in their own
modules and are imported lazily by the registry when first needed.
"""
from launcher_support.screens.base import Screen
from launcher_support.screens.exceptions import (
    ScreenBuildError,
    ScreenContextError,
    ScreenError,
)
from launcher_support.screens.manager import ScreenManager
from launcher_support.screens.registry import register_default_screens

__all__ = [
    "Screen",
    "ScreenManager",
    "register_default_screens",
    "ScreenError",
    "ScreenBuildError",
    "ScreenContextError",
]
