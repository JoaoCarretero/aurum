"""Pure transform: per-instance proc rows → per-engine EngineCard rows.

No tkinter, no I/O. Given a list of proc dicts (from data.procs enriched
with heartbeat + cockpit runs data), returns a list of EngineCard objects
suitable for rendering by panes/strip_grid.py and widgets/engine_card.py.

Sort order (per spec):
  1. Cards with any error instance first (top-left for attention).
  2. Healthy cards ordered by ENGINES[slug].sort_weight ascending.
  3. Tie-break alphabetical by engine slug.

Card state buckets:
  live   = heartbeat fresh AND ticks_fail == 0 AND process alive
  stale  = heartbeat age > 2 * tick_sec
  error  = ticks_fail > 0 OR process dead OR explicit error flag

Expected proc row schema (duck-typed; missing fields tolerated):
  engine:             str         (slug, required — skipped if missing)
  mode:               str         (paper/shadow/live/demo/testnet)
  uptime_s:           int
  equity:             float | None
  ticks_ok:           int
  novel_total:        int
  ticks_fail:         int
  heartbeat_age_s:    int | None  (None treated as fresh)
  process_dead:       bool        (optional; default False)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from config.engines import ENGINES


@dataclass(frozen=True)
class EngineCard:
    """Aggregated view of one engine's running instances."""
    engine: str                       # slug
    display: str                      # human name for header
    instance_count: int               # total live+stale+error
    live_count: int
    stale_count: int
    error_count: int
    mode_summary: str                 # e.g. "p+s" or "p+s+l"
    max_uptime_s: int
    total_equity: float               # 0.0 if no paper/live instance
    total_novel: int
    total_ticks: int
    sort_weight: int
    has_error: bool


_MODE_CHARS = {"paper": "p", "shadow": "s", "live": "l",
               "demo": "d", "testnet": "t"}


def _proc_state(proc: dict, tick_sec: int) -> str:
    """Classify a proc as 'live', 'stale', or 'error'."""
    if int(proc.get("ticks_fail") or 0) > 0:
        return "error"
    if bool(proc.get("process_dead")):
        return "error"
    age = proc.get("heartbeat_age_s")
    if age is not None and age > 2 * tick_sec:
        return "stale"
    return "live"


def _mode_char(mode: str) -> str:
    return _MODE_CHARS.get(mode, "?")


def build_engine_cards(procs: Iterable[dict], *,
                       tick_sec: int = 900) -> list[EngineCard]:
    """Collapse proc rows into per-engine cards, sorted per spec.

    Args:
      procs: iterable of proc dicts (see module docstring for schema).
      tick_sec: expected tick cadence; used to classify stale heartbeats.

    Returns:
      List of EngineCard, sorted: errors first, then by sort_weight asc,
      then alphabetical by engine slug.
    """
    by_engine: dict[str, list[dict]] = {}
    for p in procs:
        engine = p.get("engine")
        if not engine:
            continue
        by_engine.setdefault(engine, []).append(p)

    cards: list[EngineCard] = []
    for engine, rows in by_engine.items():
        live = stale = error = 0
        modes: set[str] = set()
        max_uptime = 0
        eq_sum = 0.0
        novel_sum = 0
        ticks_sum = 0
        for r in rows:
            state = _proc_state(r, tick_sec)
            if state == "live":
                live += 1
            elif state == "stale":
                stale += 1
            else:
                error += 1
            modes.add(_mode_char(r.get("mode", "")))
            max_uptime = max(max_uptime, int(r.get("uptime_s") or 0))
            eq = r.get("equity")
            if eq is not None:
                eq_sum += float(eq)
            novel_sum += int(r.get("novel_total") or 0)
            ticks_sum += int(r.get("ticks_ok") or 0)

        meta = ENGINES.get(engine, {})
        mode_order = ["p", "d", "t", "l", "s"]
        mode_summary = "+".join(m for m in mode_order if m in modes)

        cards.append(EngineCard(
            engine=engine,
            display=meta.get("display", engine.upper()),
            instance_count=live + stale + error,
            live_count=live,
            stale_count=stale,
            error_count=error,
            mode_summary=mode_summary,
            max_uptime_s=max_uptime,
            total_equity=eq_sum,
            total_novel=novel_sum,
            total_ticks=ticks_sum,
            sort_weight=int(meta.get("sort_weight", 9999)),
            has_error=error > 0,
        ))

    # Sort: errors first, then by sort_weight, then alphabetical
    cards.sort(key=lambda c: (not c.has_error, c.sort_weight, c.engine))
    return cards
