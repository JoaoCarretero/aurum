"""Exception hierarchy for launcher_support.screens."""
from __future__ import annotations


from launcher_support.screens.exceptions import (
    ScreenError,
    ScreenBuildError,
    ScreenContextError,
)


def test_screen_error_is_base():
    assert issubclass(ScreenBuildError, ScreenError)
    assert issubclass(ScreenContextError, ScreenError)


def test_screen_error_is_exception():
    assert issubclass(ScreenError, Exception)


def test_screen_build_error_carries_screen_name():
    err = ScreenBuildError("splash", original=ValueError("boom"))
    assert err.screen_name == "splash"
    assert isinstance(err.original, ValueError)
    assert "splash" in str(err)


def test_screen_context_error_carries_missing_keys():
    err = ScreenContextError("results", missing=["run_id", "mode"])
    assert err.screen_name == "results"
    assert err.missing == ["run_id", "mode"]
    assert "run_id" in str(err)
