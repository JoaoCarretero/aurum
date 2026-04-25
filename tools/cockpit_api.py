"""Aurum Cockpit API — read-only HTTP surface pra runners shadow/paper/live.

Descobre runs via core.shadow_contract.find_runs sobre um data_root
configurável (default: ROOT/data). Expõe GET endpoints read-only e um
POST /kill admin-scoped. Bind default 127.0.0.1 — acesso externo via
SSH tunnel.

Uso standalone:
    AURUM_COCKPIT_READ_TOKEN=... AURUM_COCKPIT_ADMIN_TOKEN=... \\
        python tools/cockpit_api.py --port 8787

Config via env vars (systemd unit preenche):
    AURUM_COCKPIT_DATA_ROOT   default: <repo>/data
    AURUM_COCKPIT_READ_TOKEN  obrigatório
    AURUM_COCKPIT_ADMIN_TOKEN obrigatório
    AURUM_COCKPIT_BIND_HOST   default: 127.0.0.1
    AURUM_COCKPIT_BIND_PORT   default: 8787
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.shadow_contract import (  # noqa: E402
    Heartbeat, Manifest, RunSummary, RunDetail,
    find_runs, load_heartbeat, load_manifest,
)
from tools.operations.millennium_signal_gate import is_live_signal  # noqa: E402

VERSION = "1.0.0"
STARTED_AT = datetime.now(timezone.utc)
# Match {engine}_{mode}(@{instance})? — all engines with live runners.
# Kept strict on engine prefix + mode to prevent shell injection via arbitrary
# unit names. Instance suffix (desk-a, desk-paper-a, etc.) is templated via
# systemd @-instance syntax — alphanumeric + hyphen only.
_SERVICE_RE = re.compile(
    r"^(?:citadel|jump|renaissance|millennium)_(paper|shadow)"
    r"(?:@[a-z0-9][a-z0-9-]{0,39})?$"
)


def _engine_from_dir(run_dir: Path) -> tuple[str, str]:
    """Derive (engine, mode) do path quando manifest ausente.

    Layout A: data/{engine}_shadow/{run_id}/ → (engine, "shadow")
    Layout B: data/shadow/{engine}/{run_id}/ → (engine, "shadow")
    """
    parent = run_dir.parent
    if parent.name.endswith("_shadow"):
        return parent.name.removesuffix("_shadow"), "shadow"
    if parent.parent.name == "shadow":
        return parent.name, "shadow"
    return "unknown", "unknown"


def _effective_status(hb: Heartbeat, now: datetime | None = None):
    """Derive a status that accounts for zombie runs.

    A runner killed by SIGKILL or stopped via systemctl never writes
    status=stopped to its own heartbeat file; the file stays frozen at
    'running' until an operator hand-edits it. We have two signals to
    defeat the zombie:

    1. DB row with ``ended_at != NULL`` — authoritative: the runner's
       shutdown hook (or ``aurum_cleanup_stale_runs``) marked the row
       ended. Trust this even when the heartbeat is "fresh".
    2. Staleness of ``last_tick_at`` — fallback when DB is unreachable:
       a heartbeat claiming 'running' whose tick is older than
       ``max(tick_sec * 3, 600s)`` is effectively stopped.

    The underlying heartbeat file is never mutated here — this is purely
    the API-level view.
    """
    if hb.status != "running":
        return hb.status

    # DB cross-check — authoritative when available.
    try:
        from core.ops import db_live_runs
        db_row = db_live_runs.get_live_run(str(hb.run_id or ""))
    except Exception:  # noqa: BLE001
        db_row = None
    if db_row is not None:
        db_status = str(db_row.get("status") or "").lower()
        db_ended = db_row.get("ended_at")
        if db_status == "stopped" or db_ended:
            return "stopped"

    if hb.last_tick_at is None:
        return hb.status
    now = now or datetime.now(timezone.utc)
    staleness_threshold = max((hb.tick_sec or 900) * 3, 600)
    age = (now - hb.last_tick_at).total_seconds()
    if age > staleness_threshold:
        return "stopped"
    return hb.status


def _summarize_run(run_dir: Path) -> RunSummary:
    hb = load_heartbeat(run_dir)
    manifest = load_manifest(run_dir)
    if manifest:
        engine = manifest.engine
        mode = manifest.mode
        started_at = manifest.started_at
        label = manifest.label
    else:
        engine, mode = _engine_from_dir(run_dir)
        started_at = hb.last_tick_at or datetime.now(timezone.utc)
        # Heartbeat allows extras — label may be there as fallback
        extras = hb.model_extra or {}
        label = extras.get("label")
    extras = hb.model_extra or {}
    equity = extras.get("equity")
    drawdown_pct = extras.get("drawdown_pct")
    ks_state = extras.get("ks_state")
    primed = extras.get("primed")
    return RunSummary(
        run_id=hb.run_id,
        engine=engine,
        mode=mode,
        status=_effective_status(hb),
        started_at=started_at,
        last_tick_at=hb.last_tick_at,
        novel_total=hb.novel_total,
        label=label,
        ticks_ok=hb.ticks_ok,
        ticks_fail=hb.ticks_fail,
        equity=float(equity) if isinstance(equity, (int, float)) else None,
        drawdown_pct=float(drawdown_pct) if isinstance(drawdown_pct, (int, float)) else None,
        ks_state=str(ks_state) if ks_state else None,
        primed=bool(primed) if primed is not None else None,
    )


def _find_run_by_id(data_root: Path, run_id: str) -> Path | None:
    for run_dir in find_runs(data_root):
        if run_dir.name == run_id:
            return run_dir
    return None


def _is_allowed_service_name(service: str) -> bool:
    return bool(_SERVICE_RE.fullmatch(str(service or "").strip()))


def build_app() -> FastAPI:
    data_root = Path(os.environ.get("AURUM_COCKPIT_DATA_ROOT", str(ROOT / "data")))
    read_token = os.environ.get("AURUM_COCKPIT_READ_TOKEN", "")
    admin_token = os.environ.get("AURUM_COCKPIT_ADMIN_TOKEN", "")

    if not read_token or not admin_token:
        raise RuntimeError(
            "AURUM_COCKPIT_READ_TOKEN e AURUM_COCKPIT_ADMIN_TOKEN devem estar setadas"
        )

    app = FastAPI(title="Aurum Cockpit API", version=VERSION)

    def _check_auth(request: Request, admin: bool = False) -> None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="unauthorized")
        token = header.removeprefix("Bearer ").strip()
        if admin:
            if not secrets.compare_digest(token, admin_token):
                raise HTTPException(status_code=403, detail="admin scope required")
        else:
            # Compute BOTH compare_digest calls always (constant-time);
            # don't short-circuit before the `or` to avoid timing leaks.
            ok_read = secrets.compare_digest(token, read_token)
            ok_admin = secrets.compare_digest(token, admin_token)
            if not (ok_read or ok_admin):
                raise HTTPException(status_code=401, detail="unauthorized")

    @app.exception_handler(HTTPException)
    async def _exc(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.get("/v1/healthz")
    def healthz():
        return {
            "status": "ok",
            "version": VERSION,
            "started_at": STARTED_AT.isoformat(),
        }

    @app.get("/v1/runs", response_model=list[RunSummary])
    def list_runs(request: Request):
        _check_auth(request)
        return [_summarize_run(p) for p in find_runs(data_root)]

    @app.get("/v1/live-runs")
    def list_live_runs_endpoint(
        request: Request,
        mode: str | None = None,
        engine: str | None = None,
        since: str | None = None,
        limit: int = 200,
    ):
        """DB-backed run state (live_runs table). Faster than filesystem
        scan for >100 accumulated run_dirs; returns aggregate metrics
        (tick_count, novel_count, equity) from per-tick upserts. Use
        /v1/runs for filesystem-discovered runs with full heartbeat."""
        _check_auth(request)
        if limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit must be 1..1000")
        from core.ops import db_live_runs
        try:
            rows = db_live_runs.list_live_runs(
                mode=mode, engine=engine, since=since, limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            # Fresh DB without schema is now auto-migrated, but guard any
            # other sqlite error so the cockpit stays up.
            raise HTTPException(status_code=500, detail=f"db query failed: {exc}")
        return {"count": len(rows), "runs": rows}

    @app.get("/v1/runs/{run_id}")
    def run_detail(run_id: str, request: Request):
        _check_auth(request)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        hb = load_heartbeat(run_dir)
        manifest = load_manifest(run_dir)
        if manifest is None:
            engine, mode = _engine_from_dir(run_dir)
            manifest = Manifest(
                run_id=hb.run_id, engine=engine, mode=mode,
                started_at=hb.last_tick_at or datetime.now(timezone.utc),
                commit="unknown", branch="unknown",
                config_hash="unknown", host="unknown",
            )
        return RunDetail(manifest=manifest, heartbeat=hb)

    @app.get("/v1/runs/{run_id}/heartbeat", response_model=Heartbeat)
    def run_heartbeat(run_id: str, request: Request):
        _check_auth(request)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        return load_heartbeat(run_dir)

    @app.get("/v1/runs/{run_id}/trades")
    def run_trades(
        run_id: str,
        request: Request,
        limit: int = 50,
        since: str | None = None,
        include_primed: bool = False,
    ):
        _check_auth(request)
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be 1..500")
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        hb = load_heartbeat(run_dir)
        tick_sec = int(hb.tick_sec or 900)
        since_dt = None
        if since:
            try:
                # fromisoformat accepts 'Z' suffix in Python 3.11+
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=400, detail="since must be ISO8601")
        # Paper runner writes reports/trades.jsonl; shadow writes
        # reports/shadow_trades.jsonl. A given run_dir only has one of the
        # two (paper and shadow live in separate data/ subdirs), so try
        # shadow first (back-compat) and fall back to the paper filename.
        jsonl_shadow = run_dir / "reports" / "shadow_trades.jsonl"
        jsonl_paper = run_dir / "reports" / "trades.jsonl"
        jsonl = jsonl_shadow if jsonl_shadow.exists() else jsonl_paper
        if not jsonl.exists():
            return {"run_id": run_id, "count": 0, "trades": []}
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        records = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                import json as _json
                records.append(_json.loads(ln))
            except ValueError:
                continue
        if not include_primed:
            records = [r for r in records if not r.get("primed", False)]
        if run_dir.parent.name.endswith("_shadow"):
            records = [
                r for r in records
                if (
                    not r.get("shadow_observed_at")
                    or is_live_signal(
                        r,
                        tick_sec=tick_sec,
                        reference_ts=r.get("shadow_observed_at"),
                    )
                )
            ]
        if since_dt is not None:
            def _ts_after(rec: dict) -> bool:
                raw = rec.get("timestamp")
                if not raw:
                    return False
                try:
                    rec_dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                except ValueError:
                    return False
                return rec_dt > since_dt

            records = [r for r in records if _ts_after(r)]
        tail = records[-limit:]
        return {"run_id": run_id, "count": len(tail), "trades": tail}

    @app.get("/v1/runs/{run_id}/log")
    def run_log(run_id: str, request: Request,
                tail: int = 100, grep: str | None = None):
        """Read-only tail de logs/shadow.log. `tail`=1..1000 linhas,
        `grep`=substring case-insensitive opcional pra filtrar (ex:
        'telegram', 'error', 'novel'). Retorna {"lines": [...]}."""
        _check_auth(request)
        if tail < 1 or tail > 1000:
            raise HTTPException(status_code=400, detail="tail must be 1..1000")
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        # Cockpit serves shadow + paper + live runs — try each canonical
        # name plus any *.log fallback so paper runs don't hand back empty.
        logs_dir = run_dir / "logs"
        candidates = [
            logs_dir / "shadow.log",
            logs_dir / "paper.log",
            logs_dir / "live.log",
            logs_dir / "engine.log",
        ]
        log_path = next((p for p in candidates if p.exists()), None)
        if log_path is None and logs_dir.exists():
            fallback = sorted(logs_dir.glob("*.log"))
            if fallback:
                log_path = fallback[0]
        if log_path is None or not log_path.exists():
            return {"run_id": run_id, "lines": [], "grep": grep,
                    "path": str(logs_dir / "shadow.log")}
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"read failed: {exc}")
        all_lines = text.splitlines()
        if grep:
            needle = grep.lower()
            filtered = [ln for ln in all_lines if needle in ln.lower()]
        else:
            filtered = all_lines
        sliced = filtered[-tail:]
        return {
            "run_id": run_id,
            "lines": sliced,
            "grep": grep,
            "total_matching": len(filtered),
            "total_lines": len(all_lines),
        }

    @app.get("/v1/runs/{run_id}/signals")
    def run_signals(run_id: str, request: Request, limit: int = 30):
        """Tail de reports/signals.jsonl do run_dir.

        Cada linha do JSONL é um decision record:
          {ts, symbol, decision, score, reason, ...features}
        decision ∈ {opened, stale, max_open, dir_conflict, corr_block, ...}.

        Vazio com source='missing' se signals.jsonl não existe ainda
        (runner novo, sem ticks). 404 só se o run_id não for descoberto.
        """
        _check_auth(request)
        if limit < 1 or limit > 1000:
            raise HTTPException(status_code=400, detail="limit must be 1..1000")
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        sig_path = run_dir / "reports" / "signals.jsonl"
        if not sig_path.exists():
            return {"run_id": run_id, "signals": [], "source": "missing"}
        try:
            text = sig_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500,
                                detail=f"read failed: {exc}") from exc
        import json as _json
        lines = [ln for ln in text.splitlines() if ln.strip()]
        tail = lines[-limit:]
        out: list[dict] = []
        for ln in tail:
            try:
                out.append(_json.loads(ln))
            except ValueError:
                continue
        return {"run_id": run_id, "signals": out, "source": "jsonl"}

    @app.get("/v1/runs/{run_id}/telegram-diag")
    def telegram_diag(run_id: str, request: Request):
        """Extrai contadores e timestamps de atividade Telegram no
        shadow.log. Retorna sends/failures/last_send/last_failure_reason
        — fecha a pergunta "Telegram funcionou?" sem precisar parsear
        log cru."""
        _check_auth(request)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        log_path = run_dir / "logs" / "shadow.log"
        if not log_path.exists():
            return {"run_id": run_id, "log_missing": True}
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"read failed: {exc}")
        sends = 0
        failures = 0
        last_send_ts: str | None = None
        last_fail_ts: str | None = None
        last_fail_reason: str | None = None
        for ln in text.splitlines():
            low = ln.lower()
            if "telegram" not in low:
                continue
            # Timestamp do formatter é o inicio da linha ("YYYY-MM-DD HH:MM:SS").
            ts = ln[:19] if len(ln) >= 19 and ln[4] == "-" and ln[13] == ":" else None
            if "telegram send failed" in low or "telegram send error" in low:
                failures += 1
                last_fail_ts = ts or last_fail_ts
                # Keep reason post "failed: "
                idx = low.find("failed:")
                if idx >= 0:
                    last_fail_reason = ln[idx+7:].strip()[:200]
            elif "shadow · " in low or "telegram" in low and "sent" in low:
                # Heurística fraca — _tg_signal nao loga "sent" hoje, so
                # conta se introduzirmos. Por ora mantem contador zero
                # pra sends mas detalhamos se o texto vier.
                sends += 1
                last_send_ts = ts or last_send_ts
        return {
            "run_id": run_id,
            "telegram_sends_logged": sends,
            "telegram_failures_logged": failures,
            "last_send_ts": last_send_ts,
            "last_failure_ts": last_fail_ts,
            "last_failure_reason": last_fail_reason,
            "hint": (
                "telegram_sends_logged=0 + zero failures = runner nao estava "
                "logando cada send. Ative o log com um emit info em _tg_signal "
                "pra rastrear histórico, OU use /log?grep=telegram pra ver o "
                "cru. Se failures>0, last_failure_reason tem a causa."
            ),
        }

    @app.get("/v1/runs/{run_id}/positions")
    def run_positions(run_id: str, request: Request):
        """Paper runner: retorna state/positions.json (snapshot atomic).
        Shadow runs nao tem positions — retorna vazio se arquivo ausente."""
        _check_auth(request)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        path = run_dir / "state" / "positions.json"
        if not path.exists():
            return {"as_of": None, "count": 0, "positions": []}
        import json as _json
        try:
            return _json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise HTTPException(status_code=500,
                                detail=f"positions.json malformed: {exc}")

    @app.get("/v1/runs/{run_id}/account")
    def run_account(run_id: str, request: Request):
        """Paper runner: retorna state/account.json (snapshot atomic com
        metrics aninhado — Sharpe/PF/WR/MaxDD/ROI, ks_state, peak_equity).
        Shadow runs nao tem account.json — retorna vazio."""
        _check_auth(request)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        path = run_dir / "state" / "account.json"
        if not path.exists():
            return {"available": False}
        import json as _json
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            data["available"] = True
            return data
        except ValueError as exc:
            raise HTTPException(status_code=500,
                                detail=f"account.json malformed: {exc}")

    @app.get("/v1/runs/{run_id}/equity")
    def run_equity(run_id: str, request: Request, tail: int = 200):
        """Paper runner: tail dos ultimos N pontos de equity.jsonl.
        `tail` 1..10000. Vazio se arquivo ausente (shadow ou paper fresh)."""
        _check_auth(request)
        if tail < 1 or tail > 10_000:
            raise HTTPException(status_code=400, detail="tail must be 1..10000")
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        path = run_dir / "reports" / "equity.jsonl"
        if not path.exists():
            return {"run_id": run_id, "count": 0, "points": []}
        import json as _json
        lines = path.read_text(encoding="utf-8").splitlines()
        tail_lines = lines[-tail:]
        points = []
        for ln in tail_lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                points.append(_json.loads(ln))
            except ValueError:
                continue
        return {"run_id": run_id, "count": len(points), "points": points}

    @app.post("/v1/runs/{run_id}/kill")
    def run_kill(run_id: str, request: Request):
        _check_auth(request, admin=True)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        (run_dir / ".kill").touch()
        return {"status": "kill_flag_dropped", "run_id": run_id}

    @app.post("/v1/shadow/start")
    def shadow_start(request: Request, service: str = "millennium_shadow"):
        """Admin-scoped: dispara `systemctl start <service>.service`.
        Permite o operador relancar o shadow runner pelo cockpit sem
        SSH. `service` default millennium_shadow; whitelist abaixo
        previne chamada arbitraria."""
        _check_auth(request, admin=True)
        if not _is_allowed_service_name(service):
            raise HTTPException(status_code=400,
                                detail="service must be {citadel|jump|renaissance|millennium}_{paper|shadow} or template instance")
        import subprocess
        try:
            proc = subprocess.run(
                ["systemctl", "start", f"{service}.service"],
                capture_output=True, text=True, timeout=20,
            )
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="systemctl not available")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="systemctl start timed out")
        if proc.returncode != 0:
            raise HTTPException(status_code=500,
                                detail=f"systemctl exit {proc.returncode}: {proc.stderr.strip()[:300]}")
        return {"status": "started", "service": f"{service}.service",
                "stdout": proc.stdout.strip()[:400]}

    @app.post("/v1/systemctl/{action}")
    def systemctl_action(action: str, request: Request,
                         service: str = "millennium_shadow"):
        """Admin-scoped: dispara systemctl <action> <service>.service.
        Whitelist rígida pra action e service — sem shell injection. Permite
        ao operador parar/restartar/ver status de services VPS pelo cockpit
        sem SSH. Complementa /v1/shadow/start (que só startava)."""
        _check_auth(request, admin=True)
        ALLOWED_ACTIONS = {"start", "stop", "restart", "status", "is-active"}
        if action not in ALLOWED_ACTIONS:
            raise HTTPException(status_code=400,
                                detail=f"action must be one of {sorted(ALLOWED_ACTIONS)}")
        if not _is_allowed_service_name(service):
            raise HTTPException(status_code=400,
                                detail="service must be {citadel|jump|renaissance|millennium}_{paper|shadow} or template instance")
        import subprocess
        try:
            proc = subprocess.run(
                ["systemctl", action, f"{service}.service"],
                capture_output=True, text=True, timeout=20,
            )
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="systemctl not available")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504,
                                detail=f"systemctl {action} timed out")
        # status/is-active retornam codigos non-zero em estados "inactive" —
        # nao sao erros, apenas reportam o estado. Passar stdout tal qual.
        is_query = action in ("status", "is-active")
        if proc.returncode != 0 and not is_query:
            raise HTTPException(
                status_code=500,
                detail=f"systemctl {action} exit {proc.returncode}: {proc.stderr.strip()[:300]}")
        return {
            "action": action,
            "service": f"{service}.service",
            "returncode": proc.returncode,
            "stdout": proc.stdout.strip()[:800],
            "stderr": proc.stderr.strip()[:400] if proc.returncode != 0 else "",
        }

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("AURUM_COCKPIT_BIND_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AURUM_COCKPIT_BIND_PORT", "8787")))
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
