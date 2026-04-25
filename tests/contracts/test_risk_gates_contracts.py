"""Contract tests for core.risk_gates — kill-switch circuit breakers.

Cobrem 8 gates individuais + check_gates composite:
- daily_dd / daily_loss (hard_block)
- consecutive_losses (soft ≥ threshold, hard ≥ max)
- gross_notional / net_exposure / concurrent_positions / freeze_window (soft)
- single_position (soft, per-trade cap)
- Composite: hard sempre vence soft, primeiro soft retorna quando não há hard,
  defaults permissive = sempre allow
"""
from __future__ import annotations


import pytest

from core.risk_gates import (
    RiskGateConfig,
    RiskState,
    check_gates,
    gate_anomaly,
    gate_concurrent_positions,
    gate_consecutive_losses,
    gate_daily_dd,
    gate_daily_loss,
    gate_dd_velocity,
    gate_freeze_window,
    gate_gross_notional,
    gate_net_exposure,
    gate_single_position,
)


# ────────────────────────────────────────────────────────────
# gate_daily_dd
# ────────────────────────────────────────────────────────────

class TestGateDailyDd:
    def test_allow_when_peak_zero(self):
        cfg = RiskGateConfig(max_daily_dd_pct=5.0)
        state = RiskState(account_equity=10_000, peak_equity=0.0)
        assert gate_daily_dd(state, cfg).severity == "allow"

    def test_allow_when_below_threshold(self):
        cfg = RiskGateConfig(max_daily_dd_pct=10.0)
        # peak 10000 → equity 9500 → dd 5% < 10%
        state = RiskState(account_equity=9_500, peak_equity=10_000)
        assert gate_daily_dd(state, cfg).severity == "allow"

    def test_hard_block_at_threshold(self):
        cfg = RiskGateConfig(max_daily_dd_pct=5.0)
        # peak 10000 → equity 9500 → dd 5% = 5% threshold
        state = RiskState(account_equity=9_500, peak_equity=10_000)
        d = gate_daily_dd(state, cfg)
        assert d.severity == "hard_block"
        assert d.gate == "daily_dd"

    def test_default_config_permissive_for_normal_dd(self):
        # max_daily_dd_pct default = 100.0 = effectively off for any realistic DD
        cfg = RiskGateConfig()
        # 50% DD ainda passa no default (threshold = 100%)
        state = RiskState(account_equity=5_000, peak_equity=10_000)
        assert gate_daily_dd(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_daily_loss
# ────────────────────────────────────────────────────────────

class TestGateDailyLoss:
    def test_allow_when_start_of_day_zero(self):
        cfg = RiskGateConfig(max_daily_loss_pct=5.0)
        state = RiskState(account_equity=10_000, start_of_day_equity=0.0, daily_pnl=-500)
        assert gate_daily_loss(state, cfg).severity == "allow"

    def test_hard_block_when_loss_exceeds(self):
        cfg = RiskGateConfig(max_daily_loss_pct=5.0)
        state = RiskState(account_equity=10_000, start_of_day_equity=10_000, daily_pnl=-600)
        d = gate_daily_loss(state, cfg)
        assert d.severity == "hard_block"
        assert d.gate == "daily_loss"

    def test_profit_never_blocks(self):
        cfg = RiskGateConfig(max_daily_loss_pct=5.0)
        state = RiskState(account_equity=11_000, start_of_day_equity=10_000, daily_pnl=+1_000)
        assert gate_daily_loss(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_consecutive_losses
# ────────────────────────────────────────────────────────────

class TestGateConsecutiveLosses:
    def test_soft_block_at_soft_threshold(self):
        cfg = RiskGateConfig(soft_block_losses=3, max_consecutive_losses=10)
        state = RiskState(account_equity=10_000, consecutive_losses=3)
        d = gate_consecutive_losses(state, cfg)
        assert d.severity == "soft_block"

    def test_hard_block_at_max(self):
        cfg = RiskGateConfig(soft_block_losses=3, max_consecutive_losses=6)
        state = RiskState(account_equity=10_000, consecutive_losses=6)
        d = gate_consecutive_losses(state, cfg)
        assert d.severity == "hard_block"

    def test_allow_below_soft_threshold(self):
        cfg = RiskGateConfig(soft_block_losses=3, max_consecutive_losses=10)
        state = RiskState(account_equity=10_000, consecutive_losses=2)
        assert gate_consecutive_losses(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_gross_notional
# ────────────────────────────────────────────────────────────

class TestGateGrossNotional:
    def test_sums_abs_notional(self):
        cfg = RiskGateConfig(max_gross_notional_pct=100.0)
        state = RiskState(
            account_equity=10_000,
            open_positions=[
                {"notional": 6_000.0},
                {"notional": 4_000.0},
            ],
        )
        # Soma 10000 / equity 10000 = 100% = threshold → soft_block
        d = gate_gross_notional(state, cfg)
        assert d.severity == "soft_block"

    def test_below_threshold_allows(self):
        cfg = RiskGateConfig(max_gross_notional_pct=200.0)
        state = RiskState(
            account_equity=10_000,
            open_positions=[{"notional": 5_000}],
        )
        assert gate_gross_notional(state, cfg).severity == "allow"

    def test_zero_equity_allows(self):
        cfg = RiskGateConfig(max_gross_notional_pct=100.0)
        state = RiskState(account_equity=0.0, open_positions=[{"notional": 1000}])
        assert gate_gross_notional(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_net_exposure
# ────────────────────────────────────────────────────────────

class TestGateNetExposure:
    def test_net_computes_long_minus_short(self):
        cfg = RiskGateConfig(max_net_exposure_pct=50.0)
        state = RiskState(
            account_equity=10_000,
            open_positions=[
                {"side": "LONG",  "notional": 8_000},
                {"side": "SHORT", "notional": 2_000},
            ],
        )
        # net = 8000 - 2000 = 6000 → 60% > 50% → soft_block
        d = gate_net_exposure(state, cfg)
        assert d.severity == "soft_block"

    def test_balanced_book_allows(self):
        cfg = RiskGateConfig(max_net_exposure_pct=50.0)
        state = RiskState(
            account_equity=10_000,
            open_positions=[
                {"side": "LONG",  "notional": 5_000},
                {"side": "SHORT", "notional": 5_000},
            ],
        )
        assert gate_net_exposure(state, cfg).severity == "allow"

    def test_absolute_value_used(self):
        # Net negativo também dispara (shorts dominam)
        cfg = RiskGateConfig(max_net_exposure_pct=50.0)
        state = RiskState(
            account_equity=10_000,
            open_positions=[
                {"side": "LONG",  "notional": 2_000},
                {"side": "SHORT", "notional": 8_000},
            ],
        )
        # net = 2000 - 8000 = -6000; abs = 6000 → 60% > 50%
        d = gate_net_exposure(state, cfg)
        assert d.severity == "soft_block"


# ────────────────────────────────────────────────────────────
# gate_concurrent_positions
# ────────────────────────────────────────────────────────────

class TestGateConcurrentPositions:
    def test_at_limit_soft_blocks(self):
        cfg = RiskGateConfig(max_concurrent_positions=3)
        state = RiskState(account_equity=10_000,
                           open_positions=[{}, {}, {}])
        assert gate_concurrent_positions(state, cfg).severity == "soft_block"

    def test_below_limit_allows(self):
        cfg = RiskGateConfig(max_concurrent_positions=3)
        state = RiskState(account_equity=10_000, open_positions=[{}])
        assert gate_concurrent_positions(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_freeze_window
# ────────────────────────────────────────────────────────────

class TestGateFreezeWindow:
    def test_no_freeze_hours_allows(self):
        cfg = RiskGateConfig(freeze_hours_utc=())
        state = RiskState(account_equity=10_000, current_hour_utc=3)
        assert gate_freeze_window(state, cfg).severity == "allow"

    def test_hour_in_freeze_list_soft_blocks(self):
        cfg = RiskGateConfig(freeze_hours_utc=(3, 4, 5))
        state = RiskState(account_equity=10_000, current_hour_utc=4)
        assert gate_freeze_window(state, cfg).severity == "soft_block"

    def test_hour_outside_list_allows(self):
        cfg = RiskGateConfig(freeze_hours_utc=(3, 4, 5))
        state = RiskState(account_equity=10_000, current_hour_utc=12)
        assert gate_freeze_window(state, cfg).severity == "allow"

    def test_negative_hour_allows(self):
        # current_hour_utc=-1 (unknown) → não bloqueia
        cfg = RiskGateConfig(freeze_hours_utc=(3,))
        state = RiskState(account_equity=10_000, current_hour_utc=-1)
        assert gate_freeze_window(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_single_position
# ────────────────────────────────────────────────────────────

class TestGateSinglePosition:
    def test_allows_when_no_proposal(self):
        cfg = RiskGateConfig(max_single_position_pct=10.0)
        state = RiskState(account_equity=10_000, proposed_notional=0.0)
        assert gate_single_position(state, cfg).severity == "allow"

    def test_soft_block_above_cap(self):
        cfg = RiskGateConfig(max_single_position_pct=10.0)
        # cap = 1000; proposed 1500 > 1000 → soft
        state = RiskState(account_equity=10_000, proposed_notional=1_500)
        assert gate_single_position(state, cfg).severity == "soft_block"

    def test_below_cap_allows(self):
        cfg = RiskGateConfig(max_single_position_pct=10.0)
        state = RiskState(account_equity=10_000, proposed_notional=900)
        assert gate_single_position(state, cfg).severity == "allow"

    def test_zero_equity_allows(self):
        cfg = RiskGateConfig(max_single_position_pct=10.0)
        state = RiskState(account_equity=0.0, proposed_notional=5_000)
        assert gate_single_position(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_dd_velocity
#
# CLAUDE.md mandates 3 layers of kill-switch protection:
# "Drawdown velocity, exposure limits, anomaly". Until 2026-04-25 only
# static DD (peak-to-current) was implemented. A 3% cliff in 10 minutes
# would pass every gate until the static threshold tripped — by which
# point the velocity already showed catastrophic structural failure.
# This gate is the leading indicator: soft_block on velocity ≥ threshold,
# pausing new entries before static DD fires hard_block.
#
# Caller is responsible for computing dd_velocity_pct_per_hour from a
# rolling window of equity readings. risk_gates.py stays stateless.
# ────────────────────────────────────────────────────────────

class TestGateDdVelocity:
    def test_below_threshold_allows(self):
        cfg = RiskGateConfig(max_dd_velocity_pct_per_hour=2.5)
        state = RiskState(account_equity=10_000, dd_velocity_pct_per_hour=1.0)
        assert gate_dd_velocity(state, cfg).severity == "allow"

    def test_at_threshold_soft_blocks(self):
        # Exact-equal trips. Pre-empt the cliff before it confirms.
        cfg = RiskGateConfig(max_dd_velocity_pct_per_hour=2.5)
        state = RiskState(account_equity=10_000, dd_velocity_pct_per_hour=2.5)
        d = gate_dd_velocity(state, cfg)
        assert d.severity == "soft_block"
        assert d.gate == "dd_velocity"

    def test_above_threshold_soft_blocks_with_metric(self):
        cfg = RiskGateConfig(max_dd_velocity_pct_per_hour=2.5)
        state = RiskState(account_equity=10_000, dd_velocity_pct_per_hour=4.5)
        d = gate_dd_velocity(state, cfg)
        assert d.severity == "soft_block"
        assert d.metric == 4.5
        assert d.threshold == 2.5
        assert "4.5" in d.reason or "4.50" in d.reason

    def test_zero_velocity_allows(self):
        # Default state — caller hasn't provided velocity yet, no reason to block.
        cfg = RiskGateConfig(max_dd_velocity_pct_per_hour=2.5)
        state = RiskState(account_equity=10_000)
        assert gate_dd_velocity(state, cfg).severity == "allow"

    def test_negative_velocity_always_allows(self):
        # Equity recovering (peak-relative); no cliff.
        cfg = RiskGateConfig(max_dd_velocity_pct_per_hour=2.5)
        state = RiskState(account_equity=10_000, dd_velocity_pct_per_hour=-1.5)
        assert gate_dd_velocity(state, cfg).severity == "allow"

    def test_default_threshold_is_permissive(self):
        # Factory default = 100.0 %/hr; insanely high velocity still allows.
        cfg = RiskGateConfig()
        state = RiskState(account_equity=10_000, dd_velocity_pct_per_hour=99.0)
        assert gate_dd_velocity(state, cfg).severity == "allow"
        # is_default() must still hold after the new field is added.
        assert cfg.is_default() is True

    def test_zero_equity_allows(self):
        # Bootstrap state — no equity, no meaningful velocity. Don't block.
        cfg = RiskGateConfig(max_dd_velocity_pct_per_hour=2.5)
        state = RiskState(account_equity=0.0, dd_velocity_pct_per_hour=10.0)
        assert gate_dd_velocity(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# gate_anomaly
#
# CLAUDE.md mandates 3 layers of kill-switch protection:
# "Drawdown velocity, exposure limits, anomaly". Layer 3 (anomaly) is
# implemented as API latency p99 — the simplest universal signal that
# catches "exchange is sick / network blip / rate limited" before bad
# fills happen. Soft_block tier (same as dd_velocity): leading indicator,
# not a flatten trigger. Caller computes p99 over a rolling 5-min window
# of REST call latencies and populates RiskState.api_latency_ms_p99.
# ────────────────────────────────────────────────────────────

class TestGateAnomaly:
    def test_below_threshold_allows(self):
        cfg = RiskGateConfig(max_api_latency_ms=2000.0)
        state = RiskState(account_equity=10_000, api_latency_ms_p99=400.0)
        assert gate_anomaly(state, cfg).severity == "allow"

    def test_at_threshold_soft_blocks(self):
        # Exact-equal trips. Pre-empt the spike before it confirms.
        cfg = RiskGateConfig(max_api_latency_ms=2000.0)
        state = RiskState(account_equity=10_000, api_latency_ms_p99=2000.0)
        d = gate_anomaly(state, cfg)
        assert d.severity == "soft_block"
        assert d.gate == "anomaly"

    def test_above_threshold_soft_blocks_with_metric(self):
        cfg = RiskGateConfig(max_api_latency_ms=2000.0)
        state = RiskState(account_equity=10_000, api_latency_ms_p99=3500.0)
        d = gate_anomaly(state, cfg)
        assert d.severity == "soft_block"
        assert d.metric == 3500.0
        assert d.threshold == 2000.0
        assert "3500" in d.reason
        assert "2000" in d.reason

    def test_zero_latency_allows(self):
        # Default state — caller hasn't accumulated enough samples yet.
        cfg = RiskGateConfig(max_api_latency_ms=2000.0)
        state = RiskState(account_equity=10_000)
        assert gate_anomaly(state, cfg).severity == "allow"

    def test_negative_latency_allows(self):
        # Defensive: negative is non-physical, treat as no-data.
        cfg = RiskGateConfig(max_api_latency_ms=2000.0)
        state = RiskState(account_equity=10_000, api_latency_ms_p99=-5.0)
        assert gate_anomaly(state, cfg).severity == "allow"

    def test_default_threshold_is_permissive(self):
        # Factory default = 1e9 ms; even an absurd 60s p99 still allows.
        cfg = RiskGateConfig()
        state = RiskState(account_equity=10_000, api_latency_ms_p99=60_000.0)
        assert gate_anomaly(state, cfg).severity == "allow"
        # is_default() must still hold after the new field is added.
        assert cfg.is_default() is True


# ────────────────────────────────────────────────────────────
# check_gates (composite)
# ────────────────────────────────────────────────────────────

class TestCheckGates:
    def test_default_config_allows(self):
        state = RiskState(account_equity=10_000)
        d = check_gates(state)
        assert d.severity == "allow"

    def test_none_config_uses_defaults(self):
        state = RiskState(account_equity=10_000)
        assert check_gates(state, None).severity == "allow"

    def test_hard_wins_over_soft(self):
        # Dois gates disparam: consecutive_losses soft + daily_dd hard → hard wins
        cfg = RiskGateConfig(
            max_daily_dd_pct=5.0,
            max_consecutive_losses=10,
            soft_block_losses=3,
        )
        state = RiskState(
            account_equity=9_400,
            peak_equity=10_000,        # 6% DD → hard_block
            consecutive_losses=3,      # soft_block
        )
        d = check_gates(state, cfg)
        assert d.severity == "hard_block"
        assert d.gate == "daily_dd"

    def test_first_soft_returned_when_no_hard(self):
        # gross_notional soft + single_position soft → qual vem primeiro em _ALL_GATES?
        # Ordem: gross_notional vem ANTES de single_position
        cfg = RiskGateConfig(
            max_gross_notional_pct=10.0,
            max_single_position_pct=1.0,
        )
        state = RiskState(
            account_equity=10_000,
            open_positions=[{"notional": 5_000}],  # 50% gross → soft
            proposed_notional=5_000,  # 50% single → soft
        )
        d = check_gates(state, cfg)
        assert d.severity == "soft_block"
        assert d.gate == "gross_notional"  # gross vem primeiro na ordem

    def test_allow_when_all_gates_pass(self):
        cfg = RiskGateConfig(
            max_daily_dd_pct=10.0, max_daily_loss_pct=10.0,
            max_consecutive_losses=10, soft_block_losses=5,
            max_gross_notional_pct=500.0, max_net_exposure_pct=200.0,
            max_concurrent_positions=10,
        )
        state = RiskState(
            account_equity=10_000, peak_equity=10_000,
            start_of_day_equity=10_000, daily_pnl=0,
            consecutive_losses=0,
            open_positions=[{"side": "LONG", "notional": 5_000}],
            proposed_notional=500,
        )
        assert check_gates(state, cfg).severity == "allow"


# ────────────────────────────────────────────────────────────
# RiskGateConfig utility
# ────────────────────────────────────────────────────────────

class TestIsDefault:
    def test_fresh_config_is_default(self):
        assert RiskGateConfig().is_default() is True

    def test_modified_config_not_default(self):
        assert RiskGateConfig(max_daily_dd_pct=5.0).is_default() is False


# ────────────────────────────────────────────────────────────
# GateDecision shape
# ────────────────────────────────────────────────────────────

class TestGateDecisionShape:
    def test_allow_decision_has_ok_reason(self):
        d = check_gates(RiskState(account_equity=10_000))
        assert d.severity == "allow"
        assert d.reason == "ok"

    def test_blocked_decision_has_metric_and_threshold(self):
        cfg = RiskGateConfig(max_daily_dd_pct=5.0)
        state = RiskState(account_equity=9_000, peak_equity=10_000)  # 10% dd
        d = check_gates(state, cfg)
        assert d.severity == "hard_block"
        assert d.metric > 0
        assert d.threshold == 5.0
        assert d.gate == "daily_dd"


# ────────────────────────────────────────────────────────────
# LiveEngine plumbing — _check_single_position_gate
# ────────────────────────────────────────────────────────────
# Bug histórico: gate_single_position existia mas nunca recebia
# proposed_notional vindo de engines/live.py. Estes testes travam
# o contrato do helper: account + risk_cfg in → GateDecision out,
# com soft_block quando notional > cap, allow caso contrário.

class TestLiveEnginePlumbing:
    def _bind(self, account: float, cfg: RiskGateConfig):
        from types import SimpleNamespace
        from engines.live import LiveEngine
        fake_self = SimpleNamespace(account=account, risk_cfg=cfg)
        return lambda notional: LiveEngine._check_single_position_gate(fake_self, notional)

    def test_allows_small_order(self):
        check = self._bind(10_000, RiskGateConfig(max_single_position_pct=25.0))
        # cap = 2500; 500 notional is well below
        assert check(500).severity == "allow"

    def test_soft_blocks_order_above_cap(self):
        check = self._bind(10_000, RiskGateConfig(max_single_position_pct=25.0))
        # cap = 2500; 3000 notional > cap
        d = check(3_000)
        assert d.severity == "soft_block"
        assert d.gate == "single_position"
        assert d.metric == 3_000.0
        assert d.threshold == 2_500.0

    def test_permissive_config_allows_any_size(self):
        # paper/demo/testnet modes set max_single_position_pct=100,
        # effectively disabling the cap until full equity is used.
        check = self._bind(10_000, RiskGateConfig(max_single_position_pct=100.0))
        assert check(9_999).severity == "allow"

    def test_live_config_caps_at_25pct(self):
        # Regression test for the config defaults shipped with live mode.
        from core.risk_gates import load_gate_config
        cfg = load_gate_config("live")
        check = self._bind(10_000, cfg)
        # 30% of 10k = 3000 > 25% cap = 2500 → soft_block
        assert check(3_000).severity == "soft_block"
        # 20% = 2000 < cap → allow
        assert check(2_000).severity == "allow"


# ────────────────────────────────────────────────────────────
# _guard_real_money_gates — fail-safe for missing/malformed config
# ────────────────────────────────────────────────────────────
# Regra: se risk_gates.json sumiu ou não tem seção pro modo, load_gate_config
# silenciosamente devolve RiskGateConfig() com defaults permissivos (todos
# os gates efetivamente off). Pra paper/demo/testnet é ok. Pra live/arb_live
# precisa abortar — operar com circuit breakers off pode queimar a banca.

class TestRealMoneyGuard:
    def _guard(self):
        from engines.live import _guard_real_money_gates
        return _guard_real_money_gates

    def test_paper_with_defaults_is_ok(self):
        # Paper/demo/testnet NÃO dispara guard mesmo com defaults permissivos.
        self._guard()("paper", RiskGateConfig())  # no raise
        self._guard()("demo", RiskGateConfig())
        self._guard()("testnet", RiskGateConfig())
        self._guard()("arbitrage_paper", RiskGateConfig())

    def test_live_with_defaults_raises(self):
        with pytest.raises(RuntimeError, match="REFUSING"):
            self._guard()("live", RiskGateConfig())

    def test_arbitrage_live_with_defaults_raises(self):
        with pytest.raises(RuntimeError, match="arbitrage_live"):
            self._guard()("arbitrage_live", RiskGateConfig())

    def test_live_with_configured_cfg_is_ok(self):
        # Config com pelo menos um valor não-default = passa.
        cfg = RiskGateConfig(max_daily_dd_pct=5.0)  # diverge do 100% default
        self._guard()("live", cfg)  # no raise

    def test_live_loads_real_config_from_disk(self):
        # Integration-ish: load_gate_config("live") deve retornar config
        # não-default a partir do risk_gates.json shipped.
        from core.risk_gates import load_gate_config
        cfg = load_gate_config("live")
        assert not cfg.is_default(), "live mode needs non-default risk gates"
        self._guard()("live", cfg)  # no raise


# ────────────────────────────────────────────────────────────
# LiveEngine dd_velocity caller-side wiring
# ────────────────────────────────────────────────────────────
# gate_dd_velocity é stateless — depende do caller computar
# dd_velocity_pct_per_hour de uma janela rolante de equity readings e
# popular o RiskState. Estes testes pinam os helpers em LiveEngine que
# fazem essa computação: _record_equity_sample (subsampleia 1/min) e
# _compute_dd_velocity_pct_per_hour (lookup por anchor + per-hour rate).
#
# Sem esses helpers populando RiskState.dd_velocity_pct_per_hour, o gate
# (que existe em risk_gates.py desde 624a57d) ficaria dormente em prod.

class TestDdVelocityCallerSide:
    def _engine(self):
        """Minimal engine stub for helper testing — same pattern as
        TestLiveEnginePlumbing._bind. Avoids spinning a full LiveEngine
        which needs exchange config + WS tasks."""
        from collections import deque
        from types import SimpleNamespace
        from engines.live import LiveEngine

        eng = SimpleNamespace()
        eng._equity_history = deque(maxlen=120)
        eng.account = 10_000.0
        # Bind unbound methods.
        eng._record_equity_sample = (
            LiveEngine._record_equity_sample.__get__(eng)
        )
        eng._compute_dd_velocity_pct_per_hour = (
            LiveEngine._compute_dd_velocity_pct_per_hour.__get__(eng)
        )
        return eng

    def test_empty_history_returns_zero(self):
        from datetime import datetime, timezone
        eng = self._engine()
        v = eng._compute_dd_velocity_pct_per_hour(
            datetime.now(timezone.utc), window_min=60
        )
        assert v == 0.0

    def test_single_sample_returns_zero(self):
        # Only one reading → no time delta → velocity not meaningful.
        from datetime import datetime, timezone
        eng = self._engine()
        now = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        eng._record_equity_sample(now, 10_000.0)
        v = eng._compute_dd_velocity_pct_per_hour(now, window_min=60)
        assert v == 0.0

    def test_decline_over_60min_yields_positive_velocity(self):
        # equity 10000 at t-60min → 9700 at t → 3% drop / 1.0 hr = 3.0 %/hr
        from datetime import datetime, timedelta, timezone
        eng = self._engine()
        t0 = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        eng._record_equity_sample(t0, 10_000.0)
        now = t0 + timedelta(minutes=60)
        eng.account = 9_700.0
        eng._record_equity_sample(now, 9_700.0)
        v = eng._compute_dd_velocity_pct_per_hour(now, window_min=60)
        assert 2.95 <= v <= 3.05, f"expected ~3.0 %/hr, got {v}"

    def test_recovery_yields_negative_velocity(self):
        # equity climbing → velocity < 0 → gate_dd_velocity returns allow.
        from datetime import datetime, timedelta, timezone
        eng = self._engine()
        t0 = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        eng._record_equity_sample(t0, 10_000.0)
        now = t0 + timedelta(minutes=30)
        eng.account = 10_300.0
        eng._record_equity_sample(now, 10_300.0)
        v = eng._compute_dd_velocity_pct_per_hour(now, window_min=60)
        assert v < 0, f"recovery should yield negative velocity, got {v}"

    def test_subsamples_to_one_per_minute(self):
        # 100 calls in same minute → only 1 entry in history.
        from datetime import datetime, timezone
        eng = self._engine()
        t0 = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        for sec in range(0, 60, 1):
            ts = t0.replace(second=sec)
            eng._record_equity_sample(ts, 10_000.0 - sec)
        # Same minute, should only retain ONE sample (the first).
        assert len(eng._equity_history) == 1

    def test_subsample_advances_on_minute_boundary(self):
        from datetime import datetime, timedelta, timezone
        eng = self._engine()
        t0 = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        eng._record_equity_sample(t0, 10_000.0)
        eng._record_equity_sample(t0 + timedelta(minutes=1), 9_990.0)
        eng._record_equity_sample(t0 + timedelta(minutes=2), 9_980.0)
        assert len(eng._equity_history) == 3

    def test_window_min_excludes_older_samples(self):
        # Anchor must be within window_min minutes of `now`.
        from datetime import datetime, timedelta, timezone
        eng = self._engine()
        t0 = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        # Ancient: 90 min before now. Should NOT anchor with window_min=60.
        eng._record_equity_sample(t0, 10_000.0)
        # Within window: 30 min before now.
        eng._record_equity_sample(t0 + timedelta(minutes=60), 9_950.0)
        now = t0 + timedelta(minutes=90)
        eng.account = 9_950.0
        # Anchor should be the 60-min mark, not the 0-min mark.
        # Drop from 9950 → 9950 over 30 min = 0%/hr (no decline in window).
        v = eng._compute_dd_velocity_pct_per_hour(now, window_min=60)
        assert abs(v) < 0.01, f"expected ~0.0 with no in-window decline, got {v}"

    def test_zero_anchor_equity_returns_zero(self):
        # Defensive: if history has equity=0 entry, don't divide by zero.
        from datetime import datetime, timedelta, timezone
        eng = self._engine()
        t0 = datetime(2026, 4, 25, 10, 0, 0, tzinfo=timezone.utc)
        eng._record_equity_sample(t0, 0.0)
        now = t0 + timedelta(minutes=30)
        eng.account = 1_000.0
        v = eng._compute_dd_velocity_pct_per_hour(now, window_min=60)
        assert v == 0.0
