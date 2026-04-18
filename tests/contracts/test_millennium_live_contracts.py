from engines.millennium import OPERATIONAL_ENGINES
from engines.millennium_live import build_bootstrap_plan, exit_code_for_mode


def test_bootstrap_plan_tracks_operational_core_and_blocked_modes():
    plan = build_bootstrap_plan("paper")
    assert plan.operational_core == list(OPERATIONAL_ENGINES)
    assert plan.live_ready is False
    assert plan.allowed_modes_now == ["diag"]
    assert "live" in plan.blocked_modes_now


def test_bootstrap_plan_marks_pending_adapters_honestly():
    plan = build_bootstrap_plan("diag")
    by_component = {row["component"]: row for row in plan.components}
    assert by_component["CITADEL"]["execution_ready"] is True
    assert by_component["RENAISSANCE"]["execution_ready"] is False
    assert by_component["JUMP"]["execution_ready"] is False


def test_bootstrap_modes_exit_cleanly_for_launcher_contract():
    assert exit_code_for_mode("diag") == 0
    assert exit_code_for_mode("paper") == 0
    assert exit_code_for_mode("demo") == 0
