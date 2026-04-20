"""Screen ABC — base class for migrated launcher screens.

A Screen owns a tk.Frame (self.container). build() creates widgets once;
on_enter(**kwargs) refreshes data; on_exit() releases timers/bindings.
pack()/pack_forget() control visibility without destroying widgets.

Helpers _after/_bind register callbacks with automatic cleanup in on_exit.
"""
from __future__ import annotations

import tkinter as tk
from abc import ABC, abstractmethod
from typing import Any, Callable


class Screen(ABC):
    def __init__(self, parent: tk.Misc):
        self._parent = parent
        self.container: tk.Frame = tk.Frame(parent)
        self._built = False
        self._tracked_after_ids: list[str] = []
        self._tracked_bindings: list[tuple[tk.Misc, str, str]] = []

    @abstractmethod
    def build(self) -> None:
        """Create widgets once inside self.container."""
        raise NotImplementedError

    def on_enter(self, **kwargs: Any) -> None:
        """Refresh dynamic data / arm timers / register bindings."""

    def on_exit(self) -> None:
        """Cancel tracked timers and unbind tracked sequences."""
        for aid in list(self._tracked_after_ids):
            try:
                self.container.after_cancel(aid)
            except Exception:
                pass
        self._tracked_after_ids.clear()
        for widget, seq, funcid in list(self._tracked_bindings):
            try:
                widget.unbind(seq, funcid)
            except Exception:
                pass
        self._tracked_bindings.clear()

    def update_data(self, **kwargs: Any) -> None:
        """Configure() existing widgets without rebuilding."""

    def mount(self) -> None:
        if not self._built:
            self.build()
            self._built = True

    def pack(self, **opts: Any) -> None:
        opts.setdefault("fill", "both")
        opts.setdefault("expand", True)
        self.container.pack(**opts)

    def pack_forget(self) -> None:
        self.container.pack_forget()

    # ── lifecycle helpers ─────────────────────────────────────────

    def _after(self, ms: int, callback: Callable[[], Any]) -> str:
        """Schedule a callback and track the id for cleanup in on_exit."""
        aid = self.container.after(ms, callback)
        self._tracked_after_ids.append(aid)
        return aid

    def _bind(
        self,
        widget: tk.Misc,
        sequence: str,
        callback: Callable[[tk.Event], Any],
    ) -> str:
        """Bind a callback and track for cleanup in on_exit."""
        funcid = widget.bind(sequence, callback, add="+")
        self._tracked_bindings.append((widget, sequence, funcid))
        return funcid
