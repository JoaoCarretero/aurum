"""Pure data readers for SplashScreen. No Tkinter, no threading — testable headless.

Responsibilities:
  Implemented:
    - read last session entry from data/index.json
    - read engine roster (OOS status + latest Sharpe per engine)
    - read macro_brain snapshot (regime + active thesis) for the MACRO BRAIN tile
    - load/save splash cache (market pulse between openings; legado, ainda disponivel)
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _safe_float(value) -> Optional[float]:
    """Cast pra float, retorna None em NaN/inf/erro. Evita 'nan%' no splash."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


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
    ("CITADEL",     "citadel",     "OK"),
    ("JUMP",        "jump",        "OK"),
    ("RENAISS",     "renaissance", "BUG"),
    ("BRIDGEW",     "bridgewater", "BUG"),
    ("PHI",         "phi",         "NEW"),
    ("ORNSTEIN",    "ornstein",    "TUN"),
    ("TWOSIGMA",    "twosigma",    "OFF"),
    ("AQR",         "aqr",         "OFF"),
    ("DE_SHAW",     "deshaw",      "NO"),
    ("KEPOS",       "kepos",       "NO"),
    ("MEDALLION",   "medallion",   "NO"),
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


# Regimes conhecidos do macro_brain — literal match pra evitar typos downstream.
_MACRO_REGIME_CODES = {
    "risk_on":     "RISK ON",
    "risk_off":    "RISK OFF",
    "transition":  "TRANSITION",
    "uncertainty": "UNCERTAINTY",
}


def read_macro_brain() -> Optional[dict]:
    """Le snapshot do macro_brain (regime atual + primeira thesis ativa).

    Retorna dict: {
        "regime":     "RISK ON" | "RISK OFF" | "TRANSITION" | "UNCERTAINTY" | "---",
        "regime_raw": codigo interno (risk_on etc) pra mapeamento de cor,
        "confidence": float em [0, 1] ou None,
        "why":        primeira rule do reason do regime (ate 18 chars) ou "---",
        "thesis":     "LONG BTC" (direction + asset) ou "FLAT",
        "thesis_conf": float em [0, 1] ou None,
        "idea":       primeiros chars da rationale ou "awaiting signal",
    }

    Retorna None se macro_brain nao importa, DB inexistente, ou schema quebrado.
    Todo erro vira None — splash nunca crasha por conta do cerebro.
    """
    try:
        # import tardio: macro_brain pode ter seus proprios side-effects na
        # importacao (config path, logging); melhor isolar dentro do try.
        from macro_brain.persistence.store import (
            active_theses,
            latest_regime,
        )
    except Exception:
        return None

    try:
        regime_row = latest_regime()
    except Exception:
        regime_row = None
    try:
        theses = active_theses()
    except Exception:
        theses = []

    if regime_row is None and not theses:
        return None

    regime_raw = (regime_row or {}).get("regime") or ""
    regime_txt = _MACRO_REGIME_CODES.get(regime_raw, "---")
    confidence = _safe_float((regime_row or {}).get("confidence"))

    reason = ((regime_row or {}).get("reason") or "").strip()
    # reason tipo: "DXY_z30d=-1.73 ≤ -0.5; VIX_z30d=-1.00 ≤ 0.0"
    # pega so a primeira rule, trunca em 18 chars.
    first_rule = reason.split(";")[0].strip() if reason else ""
    why = first_rule[:18] if first_rule else "---"

    thesis_txt = "FLAT"
    thesis_conf: Optional[float] = None
    idea_txt = "awaiting signal"
    if theses:
        t = theses[0]
        direction = (t.get("direction") or "").upper()
        asset = (t.get("asset") or "").replace("USDT", "")[:5]
        if direction and asset:
            thesis_txt = f"{direction} {asset}"
        thesis_conf = _safe_float(t.get("confidence"))
        rationale = (t.get("rationale") or "").strip()
        if rationale:
            idea_txt = rationale[:18]

    return {
        "regime":      regime_txt,
        "regime_raw":  regime_raw,
        "confidence":  confidence,
        "why":         why,
        "thesis":      thesis_txt,
        "thesis_conf": thesis_conf,
        "idea":        idea_txt,
    }
