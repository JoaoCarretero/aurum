"""Screen registration helpers for launcher startup."""
from __future__ import annotations

from pathlib import Path
from typing import Any


def register_default_screens(
    manager: Any,
    *,
    app: Any,
    conn: Any,
    root_path: Path,
    tagline: str,
) -> None:
    """Register the launcher screens that currently use ScreenManager."""
    from launcher_support.screens.connections import ConnectionsScreen
    from launcher_support.screens.data_center import DataCenterScreen
    from launcher_support.screens.data_reports import DataReportsScreen
    from launcher_support.screens.deploy_pipeline import DeployPipelineScreen
    from launcher_support.screens.engine_logs import EngineLogsScreen
    from launcher_support.screens.engines_live import EnginesLiveScreen
    from launcher_support.screens.live_runs import LiveRunsScreen
    from launcher_support.screens.macro_brain import MacroBrainScreen
    from launcher_support.screens.main_menu import MainMenuScreen
    from launcher_support.screens.markets import MarketsScreen
    from launcher_support.screens.processes import ProcessesScreen
    from launcher_support.screens.risk import RiskScreen
    from launcher_support.screens.runs_history import RunsHistoryScreen
    from launcher_support.screens.settings import SettingsScreen
    from launcher_support.screens.splash import SplashScreen
    from launcher_support.screens.terminal import TerminalScreen

    manager.register(
        "splash",
        lambda parent: SplashScreen(parent=parent, app=app, conn=conn, tagline=tagline),
    )
    manager.register(
        "main_menu",
        lambda parent: MainMenuScreen(parent=parent, app=app, conn=conn),
    )
    manager.register(
        "macro_brain",
        lambda parent: MacroBrainScreen(parent=parent, app=app),
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
        "deploy_pipeline",
        lambda parent: DeployPipelineScreen(parent=parent, app=app),
    )
    manager.register(
        "engines_live",
        lambda parent: EnginesLiveScreen(parent=parent, app=app, conn=conn),
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
        "engine_logs",
        lambda parent: EngineLogsScreen(parent=parent, app=app),
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
    manager.register(
        "live_runs",
        lambda parent: LiveRunsScreen(parent=parent, app=app),
    )
    manager.register(
        "runs_history",
        lambda parent: RunsHistoryScreen(
            parent=parent,
            app=app,
            client_factory=__import__(
                "launcher_support.engines_live_view",
                fromlist=["_get_cockpit_client"],
            )._get_cockpit_client,
        ),
    )
