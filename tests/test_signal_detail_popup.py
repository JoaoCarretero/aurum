"""Tests pros formatters puros do signal detail popup."""
from __future__ import annotations


def test_format_omega_bar_full():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(1.0) == "██████████"
    assert format_omega_bar(0.99) == "██████████"


def test_format_omega_bar_empty():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(0.0) == "░░░░░░░░░░"


def test_format_omega_bar_half():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(0.5) == "█████░░░░░"


def test_format_omega_bar_none():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(None) == "          "


def test_format_omega_bar_clamps_out_of_range():
    from launcher_support.signal_detail_popup import format_omega_bar
    assert format_omega_bar(1.5) == "██████████"
    assert format_omega_bar(-0.2) == "░░░░░░░░░░"


def test_section_outcome_all_fields():
    """Outcome section gera linhas com (label, value, color_name)."""
    from launcher_support.signal_detail_popup import section_outcome
    trade = {
        "result": "WIN", "exit_reason": "trailing",
        "pnl": 285.4, "exit_p": 66210.0,
        "r_multiple": 1.44, "duration": 5,
    }
    rows = section_outcome(trade)
    label_set = {r[0] for r in rows}
    assert "result" in label_set
    assert "pnl" in label_set
    assert "r_multiple" in label_set
    r_row = next(r for r in rows if r[0] == "result")
    assert r_row[1] == "WIN"
    assert r_row[2] == "GREEN"


def test_section_outcome_loss_renders_red():
    from launcher_support.signal_detail_popup import section_outcome
    rows = section_outcome({"result": "LOSS"})
    r_row = next(r for r in rows if r[0] == "result")
    assert r_row[2] == "RED"


def test_section_outcome_none_fields_render_dash():
    from launcher_support.signal_detail_popup import section_outcome
    rows = section_outcome({})
    for label, value, _color in rows:
        if label == "pnl":
            assert value == "—"
        if label == "result":
            assert value == "—"


def test_section_entry_all_fields():
    from launcher_support.signal_detail_popup import section_entry
    trade = {"entry": 65432.0, "stop": 65120.0, "target": 66950.0,
             "rr": 3.0, "size": 285.4, "score": 0.5363}
    rows = section_entry(trade)
    labels = {r[0] for r in rows}
    assert {"entry", "stop", "target", "rr", "size", "score"} <= labels


def test_section_regime():
    from launcher_support.signal_detail_popup import section_regime
    trade = {"macro_bias": "BULL", "vol_regime": "NORMAL",
             "hmm_regime": None, "chop_trade": False,
             "dd_scale": 1.0, "corr_mult": 1.0}
    rows = section_regime(trade)
    labels = {r[0] for r in rows}
    assert "macro_bias" in labels
    assert "vol_regime" in labels
    assert "hmm_regime" in labels


def test_section_omega_returns_bars():
    """Omega section returns (dim_name, value, bar_str) tuples for the 5 axes."""
    from launcher_support.signal_detail_popup import section_omega
    trade = {"omega_struct": 0.75, "omega_flow": 0.858,
             "omega_cascade": 0.25, "omega_momentum": 0.667,
             "omega_pullback": 0.933}
    rows = section_omega(trade)
    dims = {r[0] for r in rows}
    assert dims == {"struct", "flow", "cascade", "momentum", "pullback"}
    for _, _, bar in rows:
        assert len(bar) == 10
