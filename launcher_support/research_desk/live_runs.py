"""Live runs shape layer — converte dicts de /api/heartbeat-runs em
view-models tipados pro painel LIVE RUNS do detail modal.

Um run e uma execucao do agente sobre uma issue — tem tokens, custo,
duracao, status (running/success/error). Polling a cada 3s enquanto
o modal ta aberto; a UI so consome shapes canonicos.

Pure functions; testavel sem Tk.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_UNKNOWN = "unknown"

# Unicode dots com hue distinto; UI mapeia pra cor real
_STATUS_ICON: dict[str, str] = {
    STATUS_RUNNING: "◐",
    STATUS_SUCCESS: "●",
    STATUS_ERROR: "✕",
    STATUS_UNKNOWN: "○",
}


@dataclass(frozen=True)
class RunView:
    """View-model pra uma linha no painel LIVE RUNS."""
    id: str
    status: str              # running/success/error/unknown
    status_icon: str
    issue_title: str         # titulo da issue (truncado) ou "—"
    cost_text: str           # "$0.04" ou "—"
    tokens_text: str         # "1.2k in · 450 out" ou "—"
    duration_text: str       # "14s" / "2min" / "—"
    age_text: str            # "3min atras" ou "—"
    when_epoch: float        # pra ordenacao; 0 se invalido


def shape_runs(raw: list[dict], *, limit: int = 10) -> list[RunView]:
    """Normaliza + ordena DESC por timestamp + corta."""
    out = [shape_run(r) for r in raw]
    out.sort(key=lambda v: v.when_epoch, reverse=True)
    return out[:limit]


def shape_run(raw: dict) -> RunView:
    """Converte um dict cru em RunView tolerante."""
    rid = _str(raw, "id", "run_id", "uuid") or "?"
    status = _classify_status(raw)
    icon = _STATUS_ICON.get(status, _STATUS_ICON[STATUS_UNKNOWN])

    issue_title = _issue_title_from_run(raw)
    cost_text = _format_cost(raw)
    tokens_text = _format_tokens(raw)
    duration_text = _format_duration(raw)
    when_epoch = _parse_when(raw)
    age_text = _relative_age(when_epoch) if when_epoch > 0 else "—"

    return RunView(
        id=rid,
        status=status,
        status_icon=icon,
        issue_title=issue_title,
        cost_text=cost_text,
        tokens_text=tokens_text,
        duration_text=duration_text,
        age_text=age_text,
        when_epoch=when_epoch,
    )


# ── Classifiers ───────────────────────────────────────────────────


def _classify_status(raw: dict) -> str:
    """running se ended_at vazio + started; success se exit_code==0;
    error se exit_code!=0 ou status=='error'; senao unknown."""
    explicit = (_str(raw, "status", "state") or "").lower()
    if explicit in ("running", "in_progress"):
        return STATUS_RUNNING
    if explicit in ("error", "failed", "failure"):
        return STATUS_ERROR
    if explicit in ("success", "completed", "done", "ok"):
        return STATUS_SUCCESS

    ended = _str(raw, "ended_at", "finished_at", "completed_at")
    started = _str(raw, "started_at", "created_at")
    if started and not ended:
        return STATUS_RUNNING

    exit_code = raw.get("exit_code")
    if isinstance(exit_code, (int, float)):
        return STATUS_SUCCESS if int(exit_code) == 0 else STATUS_ERROR

    return STATUS_UNKNOWN


def _issue_title_from_run(raw: dict) -> str:
    # Varios shapes possiveis: {issue: {title}} ou {issue_title: ...}
    issue = raw.get("issue")
    if isinstance(issue, dict):
        t = issue.get("title") or issue.get("summary")
        if isinstance(t, str) and t.strip():
            return t.strip()[:60]
    t = _str(raw, "issue_title", "title", "goal")
    return t[:60] if t else "—"


# ── Formatters ────────────────────────────────────────────────────


def _format_cost(raw: dict) -> str:
    for key in ("cost_cents", "total_cost_cents"):
        v = raw.get(key)
        if isinstance(v, (int, float)):
            return f"${v / 100.0:.2f}"
    for key in ("cost_usd", "cost"):
        v = raw.get(key)
        if isinstance(v, (int, float)):
            return f"${float(v):.2f}"
    return "—"


def _format_tokens(raw: dict) -> str:
    tin = _coerce_int(raw, "tokens_in", "input_tokens", "prompt_tokens")
    tout = _coerce_int(raw, "tokens_out", "output_tokens", "completion_tokens")
    if tin == 0 and tout == 0:
        return "—"
    return f"{_compact_n(tin)} in · {_compact_n(tout)} out"


def _format_duration(raw: dict) -> str:
    # Tenta duration_ms direto; senao calcula ended - started
    ms = raw.get("duration_ms")
    if isinstance(ms, (int, float)) and ms > 0:
        return _ms_to_text(int(ms))
    started_iso = _str(raw, "started_at", "created_at")
    ended_iso = _str(raw, "ended_at", "finished_at", "completed_at")
    if started_iso and ended_iso:
        s_epoch = _parse_iso(started_iso)
        e_epoch = _parse_iso(ended_iso)
        if s_epoch and e_epoch and e_epoch > s_epoch:
            return _ms_to_text(int((e_epoch - s_epoch) * 1000))
    return "—"


def _ms_to_text(ms: int) -> str:
    if ms < 1000:
        return f"{ms}ms"
    sec = ms / 1000.0
    if sec < 60:
        return f"{sec:.1f}s"
    mins = sec / 60.0
    if mins < 60:
        return f"{mins:.1f}min"
    return f"{mins / 60.0:.1f}h"


def _compact_n(n: int) -> str:
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000.0:.1f}k"
    return f"{n / 1_000_000.0:.1f}M"


# ── Time helpers ──────────────────────────────────────────────────


def _parse_when(raw: dict) -> float:
    for key in ("started_at", "created_at", "updated_at"):
        iso = raw.get(key)
        if isinstance(iso, str) and iso:
            ts = _parse_iso(iso)
            if ts is not None:
                return ts
    return 0.0


def _parse_iso(iso: str) -> float | None:
    try:
        cleaned = iso.replace("Z", "+00:00")
        moment = dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.timestamp()


def _relative_age(epoch: float) -> str:
    import time
    delta = int(time.time() - epoch)
    if delta < 0:
        return "agora"
    if delta < 60:
        return f"{delta}s atras"
    if delta < 3600:
        return f"{delta // 60}min atras"
    if delta < 86400:
        return f"{delta // 3600}h atras"
    return f"{delta // 86400}d atras"


# ── Low-level helpers ─────────────────────────────────────────────


def _str(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _coerce_int(d: dict, *keys: str) -> int:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return int(v)
    return 0
