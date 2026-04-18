"""Contracts for CLI strategy registry coherence."""
from __future__ import annotations

import aurum_cli
from engines import millennium


def test_millennium_cli_components_match_operational_core():
    cli_components = aurum_cli.STRATEGIES["millennium"]["components"]
    expected = [name.lower() for name in millennium.OPERATIONAL_ENGINES]
    assert cli_components == expected


def test_millennium_cli_info_mentions_current_operational_core():
    info_lines = aurum_cli.STRATEGIES["millennium"]["info"]
    core_line = next(line for line in info_lines if line.startswith("Core"))
    assert "CITADEL + RENAISSANCE + JUMP" in core_line
    assert "BRIDGEWATER" not in core_line


def test_twosigma_cli_targets_meta_engine_universe_not_operational_core():
    info_lines = aurum_cli.STRATEGIES["twosigma"]["info"]
    req_line = next(line for line in info_lines if line.startswith("Requer"))
    assert "universo meta-engine" in req_line


def test_millennium_cli_live_routes_to_dedicated_bootstrap_runner():
    assert "simulator" in aurum_cli.STRATEGIES["millennium"]["methods"]
    assert "live" in aurum_cli.STRATEGIES["millennium"]["methods"]
    proc_key, script, stdin = aurum_cli._resolve("millennium", "live", {"mode": "3"})
    assert proc_key == "multi"
    assert script == "engines/millennium_live.py"
    assert stdin == ["3"]
