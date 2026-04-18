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

VERSION = "1.0.0"
STARTED_AT = datetime.now(timezone.utc)


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


def _summarize_run(run_dir: Path) -> RunSummary:
    hb = load_heartbeat(run_dir)
    manifest = load_manifest(run_dir)
    if manifest:
        engine = manifest.engine
        mode = manifest.mode
        started_at = manifest.started_at
    else:
        engine, mode = _engine_from_dir(run_dir)
        started_at = hb.last_tick_at or datetime.now(timezone.utc)
    return RunSummary(
        run_id=hb.run_id,
        engine=engine,
        mode=mode,
        status=hb.status,
        started_at=started_at,
        last_tick_at=hb.last_tick_at,
        novel_total=hb.novel_total,
    )


def _find_run_by_id(data_root: Path, run_id: str) -> Path | None:
    for run_dir in find_runs(data_root):
        if run_dir.name == run_id:
            return run_dir
    return None


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
            if token != admin_token:
                raise HTTPException(status_code=403, detail="admin scope required")
        else:
            if token not in (read_token, admin_token):
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
    def run_trades(run_id: str, request: Request, limit: int = 50, since: str | None = None):
        _check_auth(request)
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be 1..500")
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        since_dt = None
        if since:
            try:
                # fromisoformat accepts 'Z' suffix in Python 3.11+
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=400, detail="since must be ISO8601")
        jsonl = run_dir / "reports" / "shadow_trades.jsonl"
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
