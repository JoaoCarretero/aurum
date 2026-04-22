"""Pure data readers for SplashScreen. No Tkinter, no threading — testable headless.

Responsibilities:
  Implemented:
    - read last session entry from data/index.json
    - read engine roster (OOS status + latest Sharpe per engine)
    - load/save splash cache (market pulse between openings)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _parse_timestamp(value) -> Optional[datetime]:
    """Parse ISO timestamp to a comparable UTC-naive datetime, or None."""
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    # Normalize to naive UTC so aware and naive rows sort together without errors.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def read_last_session(index_path: Path) -> Optional[dict]:
    """Retorna o run mais recente do index.json, ou None se ausente/malformado."""
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(rows, list) or not rows:
        return None
    dated = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        parsed = _parse_timestamp(r.get("timestamp"))
        if parsed is None:
            continue
        dated.append((parsed, r))
    if not dated:
        return None
    dated.sort(key=lambda pair: pair[0], reverse=True)
    return dated[0][1]


# OOS audit 2026-04-17 — (DISPLAY_NAME, engine_key_in_index, status_icon)
# ordenado: edges primeiro, mixed, novos, em tuning, fora-da-bateria, falhados.
# Exclui JANE_STREET (arb, não direcional), MILLENNIUM/WINTON (orchestrators)
# e GRAHAM (arquivado).
ENGINE_ROSTER_LAYOUT: list[tuple[str, str, str]] = [
    ("CITADEL",     "citadel",     "✅"),
    ("JUMP",        "jump",        "✅"),
    ("RENAISS",     "renaissance", "⚠️"),
    ("BRIDGEW",     "bridgewater", "⚠️"),
    ("PHI",         "phi",         "🆕"),
    ("ORNSTEIN",    "ornstein",    "🔧"),
    ("TWOSIGMA",    "twosigma",    "⚪"),
    ("AQR",         "aqr",         "⚪"),
    ("DE_SHAW",     "deshaw",      "🔴"),
    ("KEPOS",       "kepos",       "🔴"),
    ("MEDALLION",   "medallion",   "🔴"),
]


def read_engine_roster(index_path: Path) -> list[dict]:
    """Cruza status hardcoded (OOS audit) com Sharpe mais recente do index.json.

    Retorna lista de dicts [{name, status, sharpe}]. sharpe é None se não há
    run registrado para o engine. Usa `_parse_timestamp` defensivo pra tolerar
    formatos ISO variados (naive vs aware) sem quebrar.
    """
    try:
        with open(index_path, "r", encoding="utf-8") as fh:
            rows = json.load(fh)
        if not isinstance(rows, list):
            rows = []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        rows = []

    latest_by_engine: dict[str, tuple[datetime, float]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        key = r.get("engine")
        sh = r.get("sharpe")
        if not key or sh is None:
            continue
        parsed = _parse_timestamp(r.get("timestamp"))
        if parsed is None:
            continue
        # parsed: datetime (Optional narrowed pelo continue acima)
        try:
            sh_f = float(sh)
        except (TypeError, ValueError):
            continue
        cur = latest_by_engine.get(key)
        if cur is None or parsed > cur[0]:
            latest_by_engine[key] = (parsed, sh_f)

    out: list[dict] = []
    for display, key, status in ENGINE_ROSTER_LAYOUT:
        entry = latest_by_engine.get(key)
        out.append({
            "name": display,
            "status": status,
            "sharpe": entry[1] if entry else None,
        })
    return out


def load_splash_cache(cache_path: Path) -> dict:
    """Le cache do mercado salvo na sessao anterior. Falha silenciosa → {}."""
    try:
        with open(cache_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_splash_cache(cache_path: Path, data: dict) -> None:
    """Escreve cache. Cria pasta pai se necessario. Falha silenciosa.

    TypeError tambem e engolido — se o caller passa um objeto nao-serializavel
    (datetime, numpy types etc), o write vira no-op em vez de crashar a UI.
    """
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except (OSError, TypeError):
        pass
