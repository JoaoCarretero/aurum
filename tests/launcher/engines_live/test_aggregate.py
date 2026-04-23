"""Unit tests for data/aggregate.py — pure transforms per-instance → per-engine card."""
from __future__ import annotations


def _make_proc(engine: str, mode: str, label: str, run_id: str,
               uptime_s: int = 900, equity: float | None = 10000.0,
               ticks_ok: int = 17, novel_total: int = 0,
               ticks_fail: int = 0):
    return {
        "run_id": run_id,
        "engine": engine, "mode": mode, "label": label,
        "uptime_s": uptime_s, "equity": equity,
        "ticks_ok": ticks_ok, "novel_total": novel_total,
        "ticks_fail": ticks_fail,
        "heartbeat_age_s": 30,  # fresh
    }


def test_empty_inputs_return_empty():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    assert build_engine_cards([]) == []


def test_single_instance_becomes_single_card():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [_make_proc("citadel", "paper", "desk-a", "rid-1")]
    cards = build_engine_cards(procs)

    assert len(cards) == 1
    card = cards[0]
    assert card.engine == "citadel"
    assert card.instance_count == 1
    assert card.live_count == 1
    assert card.error_count == 0
    assert card.stale_count == 0
    assert card.mode_summary == "p"  # paper only
    assert card.max_uptime_s == 900
    assert card.total_equity == 10000.0
    assert card.total_novel == 0
    assert card.total_ticks == 17


def test_two_instances_same_engine_aggregate_into_one_card():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [
        _make_proc("citadel", "paper", "desk-a", "rid-1"),
        _make_proc("citadel", "shadow", "desk-a", "rid-2", equity=None),
    ]
    cards = build_engine_cards(procs)

    assert len(cards) == 1
    card = cards[0]
    assert card.instance_count == 2
    assert card.live_count == 2
    assert card.mode_summary == "p+s"
    assert card.total_equity == 10000.0  # shadow equity None → excluded
    assert card.total_novel == 0
    assert card.total_ticks == 34


def test_stale_instance_increments_stale_count():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [
        _make_proc("citadel", "paper", "desk-a", "rid-1"),
    ]
    procs[0]["heartbeat_age_s"] = 1900  # > 2 * tick(900)
    cards = build_engine_cards(procs, tick_sec=900)

    assert len(cards) == 1
    assert cards[0].stale_count == 1
    assert cards[0].live_count == 0


def test_error_instance_increments_error_count():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [_make_proc("citadel", "paper", "desk-a", "rid-1", ticks_fail=3)]
    cards = build_engine_cards(procs)

    assert cards[0].error_count == 1
    assert cards[0].live_count == 0


def test_cards_sorted_by_sort_weight_ascending():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    # sort_weight: citadel=10, jump=40, millennium=60 (per config/engines.py)
    procs = [
        _make_proc("millennium", "paper", "desk-a", "rid-m"),
        _make_proc("citadel", "paper", "desk-a", "rid-c"),
        _make_proc("jump", "paper", "desk-a", "rid-j"),
    ]
    cards = build_engine_cards(procs)

    engines_ordered = [c.engine for c in cards]
    assert engines_ordered == ["citadel", "jump", "millennium"]


def test_error_cards_sorted_first():
    from launcher_support.engines_live.data.aggregate import build_engine_cards

    procs = [
        _make_proc("citadel", "paper", "desk-a", "rid-c"),  # healthy, sort_weight=10
        _make_proc("millennium", "paper", "desk-a", "rid-m", ticks_fail=5),  # error, sort_weight=60
    ]
    cards = build_engine_cards(procs)

    engines_ordered = [c.engine for c in cards]
    assert engines_ordered == ["millennium", "citadel"]  # error first despite higher sort_weight
