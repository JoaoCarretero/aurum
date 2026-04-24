"""MILLENNIUM live bootstrap runner.

Entrypoint for preparing the live path of the MILLENNIUM pod, used by
``tools/maintenance/millennium_shadow.py`` and the shadow VPS service.
Kept distinct from ``engines/millennium.py`` (the backtest orchestrator)
so the live path can advance through paper -> demo -> testnet -> live
without destabilizing backtest behavior.

Consumers:
  - tools/maintenance/millennium_shadow.py  (shadow runner, VPS service)
  - tests/engines/test_millennium_live_*    (smoke + contract tests)

When the full multi-engine live execution loop is validated end-to-end,
this module either absorbs into engines/millennium.py or gets a clear
deprecation path. Until then, it stays as the deliberate bootstrap shim.

NOT on the CORE PROTEGIDO list — changes here are allowed with the
normal review bar.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ops.fs import atomic_write
from engines.millennium import OPERATIONAL_ENGINES


BOOTSTRAP_VERSION = "millennium-live-bootstrap-v0"


def _bootstrap_run_stamp() -> tuple[datetime, str]:
    ts = datetime.now(timezone.utc)
    return ts, ts.strftime("%Y-%m-%d_%H%M%S_%f")


RUN_TS, RUN_ID = _bootstrap_run_stamp()
RUN_DIR = Path("data") / "millennium_live" / RUN_ID
REPORTS_DIR = RUN_DIR / "reports"
STATE_DIR = RUN_DIR / "state"
LOGS_DIR = RUN_DIR / "logs"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

_MODE_LABELS = {
    "paper": "PAPER",
    "demo": "DEMO",
    "testnet": "TESTNET",
    "live": "LIVE",
    "diag": "DIAG",
}


@dataclass(frozen=True)
class ComponentStatus:
    component: str
    status: str
    execution_ready: bool
    notes: str


@dataclass(frozen=True)
class BootstrapPlan:
    version: str
    run_id: str
    generated_at: str
    mode: str
    mode_label: str
    live_ready: bool
    allowed_modes_now: list[str]
    blocked_modes_now: list[str]
    operational_core: list[str]
    components: list[dict]
    blockers: list[str]
    next_steps: list[str]


def build_bootstrap_plan(mode: str) -> BootstrapPlan:
    component_rows = [
        ComponentStatus(
            component="CITADEL",
            status="runner_available",
            execution_ready=True,
            notes="Base live runtime already exists in engines/live.py; pod adapter handoff still pending.",
        ),
        ComponentStatus(
            component="RENAISSANCE",
            status="adapter_pending",
            execution_ready=False,
            notes="Needs streaming harmonic candidate builder before order routing can be trusted.",
        ),
        ComponentStatus(
            component="JUMP",
            status="adapter_pending",
            execution_ready=False,
            notes="Needs streaming order-flow signal adapter before order routing can be trusted.",
        ),
    ]
    return BootstrapPlan(
        version=BOOTSTRAP_VERSION,
        run_id=RUN_ID,
        generated_at=RUN_TS.isoformat(),
        mode=mode,
        mode_label=_MODE_LABELS.get(mode, mode.upper()),
        live_ready=False,
        allowed_modes_now=["diag"],
        blocked_modes_now=["paper", "demo", "testnet", "live"],
        operational_core=list(OPERATIONAL_ENGINES),
        components=[asdict(row) for row in component_rows],
        blockers=[
            "Dedicated streaming adapters for RENAISSANCE and JUMP are not implemented.",
            "Portfolio allocator is not yet wired to live candidate arbitration and shared risk budgets.",
            "Real-money execution stays blocked until the full pod can produce honest signal provenance per component.",
        ],
        next_steps=[
            "Port JUMP signal generation into a stateless live adapter with fixture coverage.",
            "Port RENAISSANCE harmonic candidate generation into a live adapter with fixture coverage.",
            "Wire allocator + shared position limits + audit snapshots, then smoke-test in paper before testnet/live.",
        ],
    )


def write_bootstrap_plan(plan: BootstrapPlan) -> Path:
    payload = json.dumps(asdict(plan), indent=2, ensure_ascii=True)
    out = REPORTS_DIR / "bootstrap_plan.json"
    atomic_write(out, payload)
    atomic_write(STATE_DIR / "bootstrap_plan.json", payload)
    return out


def plan_summary_lines(plan: BootstrapPlan) -> list[str]:
    lines = [
        "",
        "  " + ("=" * 66),
        f"  MILLENNIUM LIVE BOOTSTRAP  |  mode={plan.mode_label}  |  run={plan.run_id}",
        f"  Core: {' + '.join(plan.operational_core)}",
        f"  Bootstrap: {plan.version}",
        f"  Allowed now: {', '.join(plan.allowed_modes_now)}",
        f"  Blocked now: {', '.join(plan.blocked_modes_now)}",
        "  " + ("-" * 66),
    ]
    for row in plan.components:
        ready = "ready" if row["execution_ready"] else "pending"
        lines.append(f"  {row['component']:12s}  {row['status']:18s}  {ready:7s}  {row['notes']}")
    lines.append("  " + ("-" * 66))
    for idx, blocker in enumerate(plan.blockers, start=1):
        lines.append(f"  Blocker {idx}: {blocker}")
    lines.append(f"  Artifact: {REPORTS_DIR / 'bootstrap_plan.json'}")
    lines.append("  " + ("=" * 66))
    return lines


def exit_code_for_mode(mode: str) -> int:
    # Bootstrap modes are intentionally non-executing, but they should still
    # resolve as a successful preflight from the launcher's point of view.
    return 0


def _run_mode(mode: str) -> int:
    plan = build_bootstrap_plan(mode)
    artifact = write_bootstrap_plan(plan)
    summary_lines = plan_summary_lines(plan)
    atomic_write(LOGS_DIR / "bootstrap.log", "\n".join(summary_lines) + "\n")
    atomic_write(REPORTS_DIR / "bootstrap_summary.txt", "\n".join(summary_lines) + "\n")
    for line in summary_lines:
        print(line)
    if mode != "diag":
        print("")
        print("  Execution loop intentionally blocked.")
        print("  This runner is only registering the live bootstrap structure for now.")
        print(f"  Review: {artifact}")
    return exit_code_for_mode(mode)


def _menu() -> str:
    print("\n  " + ("-" * 40))
    print("  MILLENNIUM  ·  Live Bootstrap")
    print("  " + ("-" * 40))
    print("")
    print("  [1]  Diagnostico / preflight")
    print("  [2]  Paper bootstrap")
    print("  [3]  Demo bootstrap")
    print("  [4]  Testnet bootstrap")
    print("  [5]  Live bootstrap")
    print("  [0]  Sair")
    print("")
    op = input("  > ").strip()
    return {
        "1": "diag",
        "2": "paper",
        "3": "demo",
        "4": "testnet",
        "5": "live",
        "0": "exit",
    }.get(op, "exit")


def main() -> int:
    ap = argparse.ArgumentParser(description="MILLENNIUM live bootstrap runner")
    ap.add_argument(
        "mode",
        nargs="?",
        choices=["paper", "demo", "testnet", "live", "diag"],
        help="Bootstrap mode (omit for menu)",
    )
    args = ap.parse_args()
    mode = args.mode or _menu()
    if mode == "exit":
        print("\n  Ate logo.\n")
        return 0
    return _run_mode(mode)


if __name__ == "__main__":
    raise SystemExit(main())
