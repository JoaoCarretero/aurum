"""ScreenManager — central orchestrator for migrated launcher screens.

Usage:
    mgr = ScreenManager(parent=root_frame)
    mgr.register("splash", SplashScreen)
    mgr.show("splash")            # first visit: instantiate + build + enter
    mgr.show("cockpit")           # hide splash, show cockpit
    mgr.show("splash")            # cache hit: just on_enter + pack

Screens live in a single shared parent (usually `root.screens_container`).
Only one screen is visible at a time; others are pack_forget-ed but kept
in memory for instant re-entry.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from launcher_support.screens.base import Screen

ScreenFactory = Callable[[tk.Misc], Screen]


class ScreenManager:
    def __init__(self, parent: tk.Misc):
        self._parent = parent
        self._factories: dict[str, ScreenFactory] = {}
        self._cache: dict[str, Screen] = {}
        self._current_name: str | None = None

    def register(self, name: str, factory: ScreenFactory) -> None:
        """Register a Screen class or factory callable."""
        self._factories[name] = factory

    def registered_names(self) -> list[str]:
        return list(self._factories.keys())

    def current_name(self) -> str | None:
        return self._current_name

    def show(self, name: str, **kwargs: Any) -> Screen:
        """Show the named screen, creating it on first access."""
        if name not in self._factories:
            raise ValueError(f"unknown screen: {name!r}")
        screen = self._cache.get(name)
        if screen is None:
            screen = self._factories[name](self._parent)
            self._cache[name] = screen
        screen.mount()
        screen.on_enter(**kwargs)
        screen.pack()
        self._current_name = name
        return screen
