"""Kill-switch live gate — fast halt on drawdown breach.

V1 implements FAST_HALT only (mirrors engines/live.py KS_FAST_DD_MULT).
SLOW_HALT would require a new constant KS_SLOW_DD_MULT in config/params.py
which is CORE PROTECTED — deferred to V2 with explicit approval.

State machine: NORMAL -> FAST_HALT (latched, no auto-recovery).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class KSState(str, Enum):
    NORMAL = "NORMAL"
    SLOW_HALT = "SLOW_HALT"   # reserved for V2
    FAST_HALT = "FAST_HALT"
    LOCKED = "LOCKED"         # reserved (after flatten + persistent lock)


@dataclass
class KSLiveGate:
    account_size: float
    base_risk: float = 0.005
    fast_mult: float = 2.0
    state: KSState = KSState.NORMAL
    last_trigger: str | None = None   # ISO8601
    last_reason: str | None = None

    @property
    def fast_threshold(self) -> float:
        """Negative number: equity - peak <= threshold triggers FAST_HALT."""
        return -self.fast_mult * self.account_size * self.base_risk

    def check(self, peak_equity: float, equity: float) -> bool:
        """Returns True iff this call TRANSITIONED to a halt state."""
        if self.state == KSState.FAST_HALT:
            return False
        dd = equity - peak_equity  # negative or zero
        if dd < self.fast_threshold:
            self.state = KSState.FAST_HALT
            self.last_trigger = datetime.now(timezone.utc).isoformat()
            self.last_reason = (
                f"fast_halt: dd {dd:.2f} < {self.fast_threshold:.2f} "
                f"(peak {peak_equity:.2f}, equity {equity:.2f})"
            )
            return True
        return False

    def snapshot(self) -> dict:
        return {
            "ks_state": self.state.value,
            "ks_last_trigger": self.last_trigger,
            "ks_last_reason": self.last_reason,
            "ks_fast_threshold": round(self.fast_threshold, 2),
        }
