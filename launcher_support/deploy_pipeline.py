from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config.engines import ENGINES, LIVE_BOOTSTRAP_SLUGS, LIVE_READY_SLUGS


@dataclass(frozen=True)
class DeployCandidate:
    slug: str
    display: str
    stage: str
    run_id: str
    timestamp: str
    interval: str
    scan_days: int | None
    basket: str
    leverage: float | None
    roi: float | None
    sharpe: float | None
    sortino: float | None
    max_dd: float | None
    n_symbols: int | None
    live_ready: bool
    live_bootstrap: bool
    source_row: dict[str, Any]

    @property
    def can_paper(self) -> bool:
        return self.live_ready

    @property
    def needs_cockpit(self) -> bool:
        return self.live_bootstrap and not self.live_ready


def pipeline_snapshot(limit: int = 80) -> dict[str, Any]:
    try:
        from core.ops import db as runs_db

        rows = runs_db.list_runs(limit=limit)
    except Exception:
        rows = []
    candidates = list_deploy_candidates(rows)
    paper_candidate = next((c for c in candidates if c.can_paper), None)
    bootstrap_candidate = next((c for c in candidates if c.needs_cockpit), None)
    return {
        "rows": rows,
        "total_runs": len(rows),
        "candidates": candidates,
        "paper_candidate": paper_candidate,
        "bootstrap_candidate": bootstrap_candidate,
    }


def list_deploy_candidates(rows: list[dict[str, Any]]) -> list[DeployCandidate]:
    by_engine: dict[str, DeployCandidate] = {}
    for row in rows:
        candidate = _candidate_from_row(row)
        if candidate is None:
            continue
        current = by_engine.get(candidate.slug)
        if current is None or _candidate_order_key(candidate) > _candidate_order_key(current):
            by_engine[candidate.slug] = candidate
    return sorted(by_engine.values(), key=_candidate_order_key, reverse=True)


def pick_paper_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate = next((c for c in list_deploy_candidates(rows) if c.can_paper), None)
    return candidate.source_row if candidate else None


def pick_bootstrap_candidate(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate = next((c for c in list_deploy_candidates(rows) if c.needs_cockpit), None)
    return candidate.source_row if candidate else None


def candidate_label(row: DeployCandidate | dict[str, Any] | None) -> str:
    candidate = row if isinstance(row, DeployCandidate) else _candidate_from_row(row) if row else None
    if not candidate:
        return "none"
    roi_text = f"roi {_num(candidate.roi):+.2f}%" if candidate.roi is not None else "roi --"
    sharpe_text = f"sh {_num(candidate.sharpe):+.2f}" if candidate.sharpe is not None else "sh --"
    return f"{candidate.display} | {roi_text} | {sharpe_text}"


def start_best_paper_candidate(app, snap: dict[str, Any] | None = None) -> None:
    snap = snap or pipeline_snapshot()
    candidate = snap.get("paper_candidate")
    if isinstance(candidate, dict):
        candidate = _candidate_from_row(candidate)
    start_candidate(app, candidate)


def start_candidate(app, candidate: DeployCandidate | None) -> None:
    if not candidate:
        app.h_stat.configure(text="NO PAPER CANDIDATE", fg="#8F7A45")
        return
    if not candidate.can_paper:
        app.h_stat.configure(text=f"{candidate.display} USE COCKPIT", fg="#8F7A45")
        return
    meta = ENGINES.get(candidate.slug)
    if not meta:
        app.h_stat.configure(text=f"UNKNOWN ENGINE {candidate.slug}", fg="#8F7A45")
        return
    app.h_stat.configure(text=f"PAPER {meta['display']}", fg="#8F7A45")
    app._exec_live_inline(
        meta["display"],
        meta["script"],
        meta["desc"],
        "paper",
        {},
    )


def open_live_cockpit(app, candidate: DeployCandidate | None = None) -> None:
    if candidate is not None:
        app.h_stat.configure(text=f"COCKPIT {candidate.display}", fg="#8F7A45")
    else:
        app.h_stat.configure(text="LIVE COCKPIT", fg="#8F7A45")
    app._strategies_live()


def stage_badge(candidate: DeployCandidate) -> str:
    if candidate.can_paper:
        return "PAPER READY"
    if candidate.needs_cockpit:
        return "BOOTSTRAP"
    return candidate.stage.upper().replace("_", " ")


def launch_hint(candidate: DeployCandidate) -> str:
    if candidate.can_paper:
        return "paper via unified live runner"
    if candidate.needs_cockpit:
        return "bootstrap via live cockpit"
    return "not deployable yet"


def _candidate_from_row(row: dict[str, Any] | None) -> DeployCandidate | None:
    if not row:
        return None
    slug = str(row.get("engine") or "").strip().lower()
    meta = ENGINES.get(slug)
    if not meta:
        return None
    live_ready = slug in LIVE_READY_SLUGS
    live_bootstrap = slug in LIVE_BOOTSTRAP_SLUGS
    if not (live_ready or live_bootstrap):
        return None
    return DeployCandidate(
        slug=slug,
        display=str(meta.get("display") or slug.upper()),
        stage=str(meta.get("stage") or "unknown"),
        run_id=str(row.get("run_id") or ""),
        timestamp=str(row.get("timestamp") or ""),
        interval=str(row.get("interval") or "-"),
        scan_days=_int_or_none(row.get("scan_days")),
        basket=str(row.get("basket") or row.get("universe") or "-"),
        leverage=_float_or_none(row.get("leverage")),
        roi=_float_or_none(row.get("roi")),
        sharpe=_float_or_none(row.get("sharpe")),
        sortino=_float_or_none(row.get("sortino")),
        max_dd=_float_or_none(row.get("max_dd")),
        n_symbols=_int_or_none(row.get("n_symbols")),
        live_ready=live_ready,
        live_bootstrap=live_bootstrap,
        source_row=row,
    )


def _candidate_order_key(candidate: DeployCandidate) -> tuple:
    roi = _num(candidate.roi)
    sharpe = _num(candidate.sharpe)
    return (
        1 if candidate.can_paper else 0,
        1 if candidate.needs_cockpit else 0,
        1 if roi > 0 and sharpe > 0 else 0,
        1 if sharpe > 0 else 0,
        1 if roi > 0 else 0,
        sharpe,
        roi,
        candidate.timestamp,
        candidate.run_id,
    )


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
