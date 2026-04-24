"""Sanity tests do scaffold do Research Desk.

Nao exerce Tk widgets — so valida constantes, imports e wiring no
registry. Tests de UI (gui marker) virao em fases posteriores.
"""
from __future__ import annotations

import pytest


def test_agents_package_loads() -> None:
    """Os 5 agentes canonicos existem e tem UUIDs distintos."""
    from launcher_support.research_desk import agents

    assert len(agents.AGENTS) == 5
    keys = [a.key for a in agents.AGENTS]
    assert keys == ["RESEARCH", "REVIEW", "BUILD", "CURATE", "AUDIT"]

    uuids = {a.uuid for a in agents.AGENTS}
    assert len(uuids) == 5, "UUIDs devem ser unicos"

    # Cross-reference resolve por uuid retorna o mesmo objeto
    for agent in agents.AGENTS:
        assert agents.BY_UUID[agent.uuid] is agent
        assert agents.BY_KEY[agent.key] is agent


def test_audit_registered() -> None:
    """AUDIT eh o 5to operativo com UUID e role corretos (antes era ORACLE)."""
    from launcher_support.research_desk.agents import AGENTS, BY_KEY, AUDIT

    assert AUDIT.key == "AUDIT"
    assert AUDIT.uuid == "2f790a10-55d1-4b4c-9a48-30db1e4cb73b"
    assert AUDIT.role == "Integrity Auditor"
    assert AUDIT.archetype == "The Oracle"  # archetype flavor preservado
    assert AUDIT.stone == "Gold"
    assert AUDIT in AGENTS
    assert BY_KEY["AUDIT"] is AUDIT


def test_palette_covers_every_agent() -> None:
    """Cada key de agente tem entrada na paleta com as 3 cores."""
    from launcher_support.research_desk import agents
    from launcher_support.research_desk.palette import AGENT_COLORS

    for agent in agents.AGENTS:
        assert agent.key in AGENT_COLORS, f"palette missing: {agent.key}"
        palette = AGENT_COLORS[agent.key]
        for field in ("primary", "dark", "dim"):
            value = getattr(palette, field)
            assert value.startswith("#") and len(value) == 7, (
                f"{agent.key}.{field}={value!r} nao eh hex #RRGGBB"
            )


def test_strings_module_has_essentials() -> None:
    """Strings PT-BR obrigatorias pro header/footer existem."""
    from launcher_support.research_desk import strings as s

    for attr in (
        "TITLE",
        "SUBTITLE_FMT",
        "PATH_LABEL",
        "STATUS_LABEL",
        "FOOTER_KEYS",
        "STATE_ONLINE",
        "STATE_OFFLINE",
        "PANEL_AGENTS",
        "PANEL_PIPELINE",
        "PANEL_ARTIFACTS",
    ):
        assert hasattr(s, attr), f"strings.{attr} faltando"


def test_screen_class_importable() -> None:
    """ResearchDeskScreen importa sem side-effects (nao instancia Tk)."""
    from launcher_support.screens.base import Screen
    from launcher_support.screens.research_desk import ResearchDeskScreen

    assert issubclass(ResearchDeskScreen, Screen)


def test_menu_data_wires_research_desk() -> None:
    """O tile RESEARCH inclui 'RESEARCH DESK' apontando pro shim certo."""
    from launcher_support.menu_data import BLOCK_DESCRIPTIONS, main_groups

    groups = main_groups({}, "x", "y", "z", "w")
    research = next(g for g in groups if g[0] == "RESEARCH")
    children = dict(research[3])
    assert "RESEARCH DESK" in children
    assert children["RESEARCH DESK"] == "_research_desk"
    assert "_research_desk" in BLOCK_DESCRIPTIONS


def test_registry_registers_research_desk() -> None:
    """register_default_screens registra 'research_desk' no ScreenManager.

    Usa fake manager que so captura os nomes registrados — sem Tk.
    """
    from pathlib import Path

    from launcher_support.screens.registry import register_default_screens

    captured: list[str] = []

    class _FakeManager:
        def register(self, name: str, _factory) -> None:  # noqa: ANN001
            captured.append(name)

    register_default_screens(
        _FakeManager(),
        app=object(),
        conn=object(),
        root_path=Path("."),
        tagline="x",
    )
    assert "research_desk" in captured


def test_launcher_has_research_desk_shim() -> None:
    """launcher.App ganhou o metodo _research_desk que vai pro screen.

    Nao instancia App (precisa Tk). Checa via AST que o shim existe.
    """
    import ast
    from pathlib import Path

    src = Path("launcher.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    app_cls = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and node.name == "App"
        ),
        None,
    )
    assert app_cls is not None, "classe App nao encontrada em launcher.py"
    method_names = {
        node.name
        for node in app_cls.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_research_desk" in method_names, (
        "launcher.App._research_desk shim nao foi adicionado"
    )


@pytest.mark.parametrize("key", ["RESEARCH", "REVIEW", "BUILD", "CURATE", "AUDIT"])
def test_agent_tagline_and_role_populated(key: str) -> None:
    """Cada identidade tem role + tagline + archetype nao vazios."""
    from launcher_support.research_desk.agents import BY_KEY

    a = BY_KEY[key]
    assert a.role and a.archetype and a.stone and a.tagline
