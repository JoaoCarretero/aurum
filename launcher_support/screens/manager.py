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

import time
import tkinter as tk
from typing import Any, Callable

from launcher_support.screens.base import Screen
from launcher_support.screens.exceptions import ScreenBuildError
from launcher_support.screens._metrics import emit_switch_metric

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
        """Show the named screen, creating it on first access.

        On build/on_enter failure, keeps the previously-current screen
        logically current (caller must re-pack or show another screen to
        recover UX).
        """
        if name not in self._factories:
            raise ValueError(f"unknown screen: {name!r}")

        t0 = time.perf_counter()
        prev_name = self._current_name
        prev_screen = self._cache.get(prev_name) if prev_name else None
        if prev_screen is not None:
            try:
                prev_screen.on_exit()
            except Exception:
                pass
            prev_screen.pack_forget()

        screen = self._cache.get(name)
        is_first_visit = screen is None
        if is_first_visit:
            try:
                screen = self._factories[name](self._parent)
                screen.mount()
            except Exception as exc:
                self._restore_previous(prev_screen)
                self._current_name = prev_name
                raise ScreenBuildError(name, original=exc) from exc
            self._cache[name] = screen
        else:
            screen.mount()

        try:
            screen.on_enter(**kwargs)
        except Exception:
            self._restore_previous(prev_screen)
            self._current_name = prev_name
            raise
        screen.pack()
        self._current_name = name

        ms = (time.perf_counter() - t0) * 1000.0
        phase = "first_visit" if is_first_visit else "reentry"
        emit_switch_metric(name, phase, ms=ms)
        return screen

    def _restore_previous(self, prev_screen: Screen | None) -> None:
        if prev_screen is None:
            return
        try:
            prev_screen.pack()
        except Exception:
            pass
        try:
            prev_screen.on_enter()
        except Exception:
            pass
