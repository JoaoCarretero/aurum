"""Screen registration helpers for launcher startup."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from launcher_support.screens.connections import ConnectionsScreen
from launcher_support.screens.data_center import DataCenterScreen
from launcher_support.screens.data_reports import DataReportsScreen
from launcher_support.screens.main_menu import MainMenuScreen
from launcher_support.screens.markets import MarketsScreen
from launcher_support.screens.processes import ProcessesScreen
from launcher_support.screens.risk import RiskScreen
from launcher_support.screens.settings import SettingsScreen
from launcher_support.screens.splash import SplashScreen
from launcher_support.screens.terminal import TerminalScreen


def register_default_screens(
    manager: Any,
    *,
    app: Any,
    conn: Any,
    root_path: Path,
    tagline: str,
) -> None:
    """Register the launcher screens that currently use ScreenManager."""
    manager.register(
        "splash",
        lambda parent: SplashScreen(parent=parent, app=app, conn=conn, tagline=tagline),
    )
    manager.register(
        "main_menu",
        lambda parent: MainMenuScreen(parent=parent, app=app, conn=conn),
    )
    manager.register(
        "markets",
        lambda parent: MarketsScreen(parent=parent, app=app, conn=conn),
    )
    manager.register(
        "connections",
        lambda parent: ConnectionsScreen(parent=parent, app=app, conn=conn),
    )
    manager.register(
        "terminal",
        lambda parent: TerminalScreen(parent=parent, app=app),
    )
    manager.register(
        "data_center",
        lambda parent: DataCenterScreen(parent=parent, app=app),
    )
    manager.register(
        "data_reports",
        lambda parent: DataReportsScreen(parent=parent, app=app, root_path=root_path),
    )
    manager.register(
        "settings",
        lambda parent: SettingsScreen(parent=parent, app=app),
    )
    manager.register(
        "processes",
        lambda parent: ProcessesScreen(parent=parent, app=app),
    )
    manager.register(
        "risk",
        lambda parent: RiskScreen(parent=parent, app=app),
    )
