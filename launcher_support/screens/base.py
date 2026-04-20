"""Screen ABC — base class for migrated launcher screens.

A Screen owns a tk.Frame (self.container). build() creates widgets once;
on_enter(**kwargs) refreshes data; on_exit() releases timers/bindings.
pack()/pack_forget() control visibility without destroying widgets.

Lifecycle helpers (_after, _bind) are added in Task 4.
"""
from __future__ import annotations

import tkinter as tk
from abc import ABC, abstractmethod
from typing import Any


class Screen(ABC):
    def __init__(self, parent: tk.Misc):
        self._parent = parent
        self.container: tk.Frame = tk.Frame(parent)
        self._built = False

    @abstractmethod
    def build(self) -> None:
        """Create widgets once inside self.container. No data fetch here."""
        raise NotImplementedError

    def on_enter(self, **kwargs: Any) -> None:
        """Called each time the screen is shown. Refresh dynamic data here."""

    def on_exit(self) -> None:
        """Called each time the screen is hidden. Cancel timers/bindings here."""

    def update_data(self, **kwargs: Any) -> None:
        """Helper for refreshing widget .configure() without rebuilding."""

    def mount(self) -> None:
        """Ensure build() has been called exactly once."""
        if not self._built:
            self.build()
            self._built = True

    def pack(self, **opts: Any) -> None:
        opts.setdefault("fill", "both")
        opts.setdefault("expand", True)
        self.container.pack(**opts)

    def pack_forget(self) -> None:
        self.container.pack_forget()
