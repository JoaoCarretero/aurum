"""Data fetch helpers para EngineDetailScreen — sem render.

Cada helper aceita `RunSummary` e devolve dados puros (list[dict],
list[str], dict | None). Local source lê arquivos do `run_dir`; VPS
source delega ao CockpitClient. Skipa silencioso em qualquer erro
(retorna estrutura vazia) — quem renderiza decide a UX do "vazio".

Separar fetch de render facilita teste, evita Tk acoplamento em I/O,
e mantém `engine_detail_view.py` enxuto.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from launcher_support.runs_history import RunSummary


def _fetch_signals(run: RunSummary, limit: int) -> list[dict]:
    """Tail de signals.jsonl. Local: read file; VPS: cockpit endpoint.

    Layouts suportados (local):
      - run_dir/signals.jsonl                 (legacy, raiz)
      - run_dir/reports/signals.jsonl         (canônico, sub-reports)
    """
    rows: list[dict] = []
    if run.source == "local" and run.run_dir:
        candidates = [
            Path(run.run_dir) / "reports" / "signals.jsonl",
            Path(run.run_dir) / "signals.jsonl",
        ]
        sig_path = next((p for p in candidates if p.exists()), None)
        if sig_path is not None:
            try:
                lines = sig_path.read_text(
                    encoding="utf-8").splitlines()[-limit:]
                for ln in lines:
                    if ln.strip():
                        rows.append(json.loads(ln))
            except (OSError, ValueError):
                pass
    elif run.source == "vps":
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
            if client is not None:
                resp = client.get_run_signals(run.run_id, limit=limit)
                if isinstance(resp, dict):
                    rows = resp.get("signals", []) or []
        except Exception:
            pass
    return rows


def _fetch_trades(run: RunSummary) -> list[dict]:
    """Local trades OR cockpit /v1/runs/{id}/trades.

    Layouts suportados (local — em ordem de preferencia):
      - run_dir/reports/trades.jsonl          (paper canonical)
      - run_dir/reports/shadow_trades.jsonl   (shadow runner usa shadow_trades)
      - run_dir/trades.jsonl                  (legacy raiz)
    """
    rows: list[dict] = []
    if run.source == "local" and run.run_dir:
        candidates = [
            Path(run.run_dir) / "reports" / "trades.jsonl",
            Path(run.run_dir) / "reports" / "shadow_trades.jsonl",
            Path(run.run_dir) / "trades.jsonl",
        ]
        tp = next((p for p in candidates if p.exists()), None)
        if tp is not None:
            try:
                for ln in tp.read_text(encoding="utf-8").splitlines():
                    if ln.strip():
                        rows.append(json.loads(ln))
            except Exception:
                pass
    elif run.source == "vps":
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
            if client is not None:
                resp = client.get_run_trades(run.run_id)
                if resp and isinstance(resp, dict):
                    rows = resp.get("trades", []) or []
        except Exception:
            pass
    return rows


def _fetch_log_tail(run: RunSummary, limit: int) -> list[str]:
    """Local log.txt tail OR cockpit /v1/runs/{id}/log."""
    rows: list[str] = []
    if run.source == "local" and run.run_dir:
        lp = Path(run.run_dir) / "log.txt"
        if not lp.exists():
            lp = Path(run.run_dir) / "logs" / "live.log"
        if lp.exists():
            try:
                rows = lp.read_text(encoding="utf-8",
                                    errors="replace").splitlines()[-limit:]
            except Exception:
                pass
    elif run.source == "vps":
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
            if client is not None:
                resp = client.get_run_log_tail(run.run_id, limit=limit)
                if resp and isinstance(resp, dict):
                    rows = resp.get("lines", []) or []
        except Exception:
            pass
    return rows


def _load_latest_audit(audit_dir: Path) -> tuple[dict | None, str | None]:
    """Latest YYYY-*.json dentro de audit_dir, parsed.

    Retorna (payload, error_filename):
      - (None, None)        — dir ausente ou sem candidatos JSON
      - (None, "<filename>") — parse error num arquivo específico
      - (payload, None)     — sucesso; payload anexado com
        ``_audit_filename`` (nome completo) e ``_audit_stem`` (sem ext).

    Caller (render_aderencia_block) decide a UX: dim "(no audit data)"
    quando ambos None, banner RED quando ``parse_err`` setado.
    """
    if not audit_dir.exists():
        return None, None
    candidates = sorted(audit_dir.glob("*.json"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    candidates = [p for p in candidates if p.name[0].isdigit()]
    if not candidates:
        return None, None
    latest = candidates[0]
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return None, latest.name
    # Anexa o stem do arquivo pra o caller mostrar a data sem refazer glob.
    if isinstance(payload, dict):
        payload.setdefault("_audit_filename", latest.name)
        payload.setdefault("_audit_stem", latest.stem)
    return payload, None


__all__ = [
    "_fetch_signals",
    "_fetch_trades",
    "_fetch_log_tail",
    "_load_latest_audit",
]
