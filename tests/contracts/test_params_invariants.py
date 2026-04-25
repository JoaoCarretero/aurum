"""Pin invariants of config/params.py — the CORE-protected risk knob file.

Audit 2026-04-25 Lane 4 finding: `config/params.py` is one of the four
CLAUDE.md-protected CORE files (any change requires explicit Joao
approval). Despite that, no contract tests pinned the critical numeric
values — a silent edit of LEVERAGE, SLIPPAGE, COMMISSION, or
MAX_OPEN_POSITIONS would slip past CI.

These tests are characterization tests in the audit-trail sense: they
**fail loudly** when a value changes, forcing the editor to either
update the pin (with explicit intent + commit message) or revert.

When updating values in params.py legitimately:
  1. Edit params.py.
  2. Update the corresponding pin here.
  3. Both changes go in the same commit.
  4. Commit message must include the OOS / walk-forward justification.

These pins are NOT a substitute for backtest re-calibration. They just
make sure the calibration that ships is the one operator deploys.
"""
from __future__ import annotations

import pytest


# ────────────────────────────────────────────────────────────
# Cost model — C1+C2 (per MEMORY §7)
# ────────────────────────────────────────────────────────────
# Backtest sem esses 4 não conta. Ver
# docs/audits/backtest-physics-core-2026-04-10.md.

class TestCostModel:
    def test_slippage_is_two_bp(self):
        from config.params import SLIPPAGE
        assert SLIPPAGE == 0.0002, (
            f"SLIPPAGE drift: {SLIPPAGE} ≠ 0.0002. "
            "Cost model recalibration required."
        )

    def test_spread_is_one_bp(self):
        from config.params import SPREAD
        assert SPREAD == 0.0001, (
            f"SPREAD drift: {SPREAD} ≠ 0.0001."
        )

    def test_commission_is_four_bp(self):
        from config.params import COMMISSION
        assert COMMISSION == 0.0004, (
            f"COMMISSION drift: {COMMISSION} ≠ 0.0004 "
            "(Binance futures taker per side)."
        )

    def test_funding_per_8h_is_one_bp(self):
        from config.params import FUNDING_PER_8H
        assert FUNDING_PER_8H == 0.0001, (
            f"FUNDING_PER_8H drift: {FUNDING_PER_8H} ≠ 0.0001."
        )


# ────────────────────────────────────────────────────────────
# Sizing & leverage
# ────────────────────────────────────────────────────────────

class TestSizingAndLeverage:
    def test_account_size_is_10k(self):
        from config.params import ACCOUNT_SIZE
        assert ACCOUNT_SIZE == 10_000.0, (
            f"ACCOUNT_SIZE drift: {ACCOUNT_SIZE} ≠ 10000.0. "
            "Backtest baselines and position sizing depend on this."
        )

    def test_leverage_is_one(self):
        from config.params import LEVERAGE
        assert LEVERAGE == 1.0, (
            f"LEVERAGE drift: {LEVERAGE} ≠ 1.0. "
            "Cross-engine recalibration required if changed."
        )

    def test_max_open_positions_is_three(self):
        from config.params import MAX_OPEN_POSITIONS
        assert MAX_OPEN_POSITIONS == 3, (
            f"MAX_OPEN_POSITIONS drift: {MAX_OPEN_POSITIONS} ≠ 3."
        )


# ────────────────────────────────────────────────────────────
# Signal thresholds (Omega scoring)
# ────────────────────────────────────────────────────────────

class TestSignalThresholds:
    def test_score_threshold_is_calibrated(self):
        from config.params import SCORE_THRESHOLD
        # Calibrated on grid 2026-04-14: 0.53 fallback, regime-specific
        # in SCORE_BY_REGIME. Changing this resets every calibration.
        assert SCORE_THRESHOLD == 0.53, (
            f"SCORE_THRESHOLD drift: {SCORE_THRESHOLD} ≠ 0.53"
        )

    def test_stop_atr_multiplier_is_calibrated(self):
        from config.params import STOP_ATR_M
        # grid 2026-04-14: STOP_ATR_M=2.8 + SCORE 0.55 → Sharpe 4.49
        assert STOP_ATR_M == 2.8, (
            f"STOP_ATR_M drift: {STOP_ATR_M} ≠ 2.8"
        )

    def test_target_rr_is_three(self):
        from config.params import TARGET_RR
        assert TARGET_RR == 3.0, (
            f"TARGET_RR drift: {TARGET_RR} ≠ 3.0"
        )


# ────────────────────────────────────────────────────────────
# Backtest scope
# ────────────────────────────────────────────────────────────

class TestBacktestScope:
    def test_scan_days_is_90(self):
        from config.params import SCAN_DAYS
        assert SCAN_DAYS == 90, (
            f"SCAN_DAYS drift: {SCAN_DAYS} ≠ 90."
        )


# ────────────────────────────────────────────────────────────
# Anti-overfit anti-pattern detection
# ────────────────────────────────────────────────────────────
# MEMORY §5 anti-pattern: comments like `iter5 WINNER` indicate fishing
# expedition, not protocol-compliant tuning. Replace with
# `tuned_on=[...], oos_sharpe=X` style.

class TestAntiOverfitAntiPatterns:
    def test_no_iter_n_winner_comments(self):
        """Guards against the 'fishing iteration' anti-pattern.

        Per MEMORY §5: comments like 'iter_5 WINNER' on a calibrated
        constant signal a grid-search-until-it-fits process, not a
        principled OOS calibration. Use `tuned_on=[...], oos_sharpe=X`
        instead.
        """
        from pathlib import Path
        params_text = (Path(__file__).resolve().parent.parent.parent
                       / "config" / "params.py").read_text(encoding="utf-8")
        offending: list[str] = []
        for line_no, line in enumerate(params_text.splitlines(), 1):
            stripped = line.strip()
            if "WINNER" in stripped:
                offending.append(f"{line_no}: {stripped}")
        assert not offending, (
            "MEMORY §5 anti-pattern detected — replace `iter_N WINNER` "
            "with `tuned_on=[...], oos_sharpe=X`:\n"
            + "\n".join(offending)
        )


# ────────────────────────────────────────────────────────────
# Drift visibility
# ────────────────────────────────────────────────────────────
# A snapshot test that catches *any* change to the constants above as
# a single failure. Useful for code review: if this test fires, look
# at the individual pin tests to see what shifted.

class TestParamsSnapshot:
    SNAPSHOT = {
        "ACCOUNT_SIZE":       10_000.0,
        "LEVERAGE":           1.0,
        "SLIPPAGE":           0.0002,
        "SPREAD":             0.0001,
        "COMMISSION":         0.0004,
        "FUNDING_PER_8H":     0.0001,
        "MAX_OPEN_POSITIONS": 3,
        "SCORE_THRESHOLD":    0.53,
        "STOP_ATR_M":         2.8,
        "TARGET_RR":          3.0,
        "SCAN_DAYS":          90,
    }

    @pytest.mark.parametrize("name,expected", list(SNAPSHOT.items()))
    def test_constant_unchanged(self, name: str, expected):
        import config.params as params
        actual = getattr(params, name)
        assert actual == expected, (
            f"{name}: snapshot {expected} ≠ current {actual}. "
            "If this change is intentional: update SNAPSHOT here AND "
            "the individual pin test, in the same commit, with OOS "
            "justification in the message."
        )
