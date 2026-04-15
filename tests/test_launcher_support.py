from __future__ import annotations

from launcher_support.bootstrap import canonical_engine_key, engine_display_name
from launcher_support.execution import live_launch_plan, script_to_proc_key, strategies_progress_target


def test_bootstrap_engine_aliases_normalize_legacy_names():
    assert canonical_engine_key("backtest") == "citadel"
    assert canonical_engine_key("jane_street") == "janestreet"
    assert canonical_engine_key("Two Sigma") == "twosigma"


def test_bootstrap_engine_display_name_uses_canonical_registry():
    assert engine_display_name("backtest") == "CITADEL"
    assert engine_display_name("janestreet") == "JANE STREET"


def test_execution_script_to_proc_key_matches_expected_legacy_proc_keys():
    assert script_to_proc_key("engines/citadel.py") == "backtest"
    assert script_to_proc_key("engines/janestreet.py") is None
    assert script_to_proc_key("engines/bridgewater.py") == "thoth"


def test_execution_live_launch_plan_routes_janestreet_to_dedicated_runner():
    plan = live_launch_plan("engines/janestreet.py", "demo", {"leverage": "10x"})
    assert plan["uses_dedicated_runner"] is True
    assert plan["script"] == "engines/janestreet.py"
    assert plan["stdin_inputs"] == ["3"]


def test_execution_live_launch_plan_routes_generic_live_with_cli_args():
    plan = live_launch_plan("engines/citadel.py", "paper", {"leverage": "5x"})
    assert plan["uses_dedicated_runner"] is False
    assert plan["script"] == "engines/live.py"
    assert plan["cli_args"] == ["paper", "--leverage", "5.0"]


def test_execution_progress_target_keeps_existing_stage_contract():
    assert strategies_progress_target("loading candles")[0] == 24.0
    assert strategies_progress_target("wr=0.54 pnl=123")[0] == 74.0
