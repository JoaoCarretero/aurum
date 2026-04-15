from __future__ import annotations

from launcher_support.menu_data import (
    BLOCK_DESCRIPTIONS,
    COMMAND_ROADMAPS,
    MAIN_MENU,
    main_groups,
    markets_children,
)


def test_menu_data_main_menu_shape():
    assert len(MAIN_MENU) == 10
    assert MAIN_MENU[0][0] == "MARKETS"
    assert MAIN_MENU[-1][0] == "SETTINGS"


def test_menu_data_markets_children_follows_registry_order():
    markets = {
        "crypto_futures": {"label": "CRYPTO FUTURES"},
        "equities": {"label": "EQUITIES"},
    }
    assert markets_children(markets) == [
        ("CRYPTO FUTURES", "_market_crypto_futures"),
        ("EQUITIES", "_market_equities"),
    ]


def test_menu_data_main_groups_shape():
    groups = main_groups({"crypto_futures": {"label": "CRYPTO FUTURES"}}, "#1", "#2", "#3", "#4")
    assert [g[0] for g in groups] == ["MARKETS", "EXECUTE", "RESEARCH", "CONTROL"]
    assert groups[0][3] == [("CRYPTO FUTURES", "_market_crypto_futures")]


def test_menu_data_descriptions_and_roadmaps_exposed():
    assert "_strategies_live" in BLOCK_DESCRIPTIONS
    assert "DEPLOY" in COMMAND_ROADMAPS
