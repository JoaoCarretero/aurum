"""Exception hierarchy for screen lifecycle errors."""
from __future__ import annotations


class ScreenError(Exception):
    """Base exception for screen-related failures."""


class ScreenBuildError(ScreenError):
    """Raised when Screen.build() fails during first mount."""

    def __init__(self, screen_name: str, *, original: BaseException | None = None):
        super().__init__(f"screen {screen_name!r} failed to build: {original!r}")
        self.screen_name = screen_name
        self.original = original


class ScreenContextError(ScreenError):
    """Raised when on_enter() is missing required kwargs."""

    def __init__(self, screen_name: str, *, missing: list[str]):
        super().__init__(
            f"screen {screen_name!r} missing required kwargs: {missing}"
        )
        self.screen_name = screen_name
        self.missing = missing
