"""Pure key routing.

Given a StateSnapshot (source of truth) and a key name (Tk keysym string),
returns an Action dataclass describing what the orchestrator should do.
view.py receives the Action, may mutate state via reducers, and/or dispatch
side effects (SSH start, subprocess spawn, etc.).

Keysym conventions:
- Single letters: "s", "r", "a" (lowercase)
- Special: "Return" (Enter), "Escape", "Tab", "Up", "Down", "Left", "Right"
- "plus" for +, "slash" for /, "question" for ?

Unknown keys return None (no-op).
"""
from __future__ import annotations

from dataclasses import dataclass

from launcher_support.engines_live.state import StateSnapshot

# ---- Action types ----

@dataclass(frozen=True)
class ExitView: ...

@dataclass(frozen=True)
class BackToStrip: ...

@dataclass(frozen=True)
class CycleFocus: ...

@dataclass(frozen=True)
class CycleMode: ...

@dataclass(frozen=True)
class OpenDetail: ...

@dataclass(frozen=True)
class OpenNewInstanceDialog:
    engine: str

@dataclass(frozen=True)
class StopInstance:
    run_id: str

@dataclass(frozen=True)
class RestartInstance:
    run_id: str

@dataclass(frozen=True)
class StopAll:
    engine: str

@dataclass(frozen=True)
class OpenConfig:
    engine: str

@dataclass(frozen=True)
class OpenLogViewer:
    run_id: str

@dataclass(frozen=True)
class ToggleFollowTail: ...

@dataclass(frozen=True)
class TelegramTest:
    run_id: str

@dataclass(frozen=True)
class ToggleShelf: ...

@dataclass(frozen=True)
class SearchFilter: ...

@dataclass(frozen=True)
class ShowHelp: ...

@dataclass(frozen=True)
class NavigateUp: ...

@dataclass(frozen=True)
class NavigateDown: ...

@dataclass(frozen=True)
class NavigateLeft: ...

@dataclass(frozen=True)
class NavigateRight: ...


Action = (
    ExitView | BackToStrip | CycleFocus | CycleMode | OpenDetail
    | OpenNewInstanceDialog | StopInstance | RestartInstance | StopAll
    | OpenConfig | OpenLogViewer | ToggleFollowTail | TelegramTest
    | ToggleShelf | SearchFilter | ShowHelp
    | NavigateUp | NavigateDown | NavigateLeft | NavigateRight
)


def route(state: StateSnapshot, key: str) -> Action | None:
    """Map (state, key) -> action. None for unknown."""
    # --- Global keys (any focus) ---
    if key == "Escape":
        if state.selected_engine is None:
            return ExitView()
        return BackToStrip()
    if key == "Tab":
        return CycleFocus()
    if key == "m":
        return CycleMode()
    if key == "slash":
        return SearchFilter()
    if key == "question":
        return ShowHelp()
    if key == "Up":
        return NavigateUp()
    if key == "Down":
        return NavigateDown()
    if key == "Left":
        return NavigateLeft()
    if key == "Right":
        return NavigateRight()

    # --- Context-dependent keys ---
    if key == "Return":
        return OpenDetail()

    # Actions that require a selected engine
    engine = state.selected_engine
    if engine is None:
        return None

    if key == "plus":
        return OpenNewInstanceDialog(engine=engine)
    if key == "c":
        return OpenConfig(engine=engine)
    if key == "a":
        return StopAll(engine=engine)

    # Actions that require a selected instance
    run_id = state.selected_instance
    if run_id is None:
        return None

    if key == "s":
        return StopInstance(run_id=run_id)
    if key == "r":
        return RestartInstance(run_id=run_id)
    if key == "l":
        return OpenLogViewer(run_id=run_id)
    if key == "f":
        return ToggleFollowTail()
    if key == "t":
        return TelegramTest(run_id=run_id)

    return None
