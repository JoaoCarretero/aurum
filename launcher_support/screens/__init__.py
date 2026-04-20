"""Screen manager infrastructure for the launcher.

See docs/architecture/screen_manager.md for the migration pattern.
Specs: docs/superpowers/specs/2026-04-20-launcher-screen-manager-design.md
"""
from launcher_support.screens.exceptions import (
    ScreenError,
    ScreenBuildError,
    ScreenContextError,
)
from launcher_support.screens.base import Screen
from launcher_support.screens.registry import register_default_screens
from launcher_support.screens.connections import ConnectionsScreen
from launcher_support.screens.data_center import DataCenterScreen
from launcher_support.screens.data_reports import DataReportsScreen
from launcher_support.screens.engines_live import EnginesLiveScreen
from launcher_support.screens.manager import ScreenManager
from launcher_support.screens.main_menu import MainMenuScreen
from launcher_support.screens.macro_brain import MacroBrainScreen
from launcher_support.screens.markets import MarketsScreen
from launcher_support.screens.processes import ProcessesScreen
from launcher_support.screens.risk import RiskScreen
from launcher_support.screens.runs_history import RunsHistoryScreen
from launcher_support.screens.settings import SettingsScreen
from launcher_support.screens.terminal import TerminalScreen

__all__ = [
    "ConnectionsScreen",
    "DataCenterScreen",
    "DataReportsScreen",
    "EnginesLiveScreen",
    "MacroBrainScreen",
    "register_default_screens",
    "SettingsScreen",
    "ProcessesScreen",
    "RiskScreen",
    "RunsHistoryScreen",
    "TerminalScreen",
    "MarketsScreen",
    "Screen",
    "ScreenManager",
    "MainMenuScreen",
    "ScreenError",
    "ScreenBuildError",
    "ScreenContextError",
]
