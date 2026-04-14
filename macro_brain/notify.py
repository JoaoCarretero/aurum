"""Macro Brain — Telegram notification helper.

Sync sender (simples, sem asyncio) pra events importantes do macro brain:
  - regime_change
  - thesis_opened
  - position_opened
  - position_closed (com P&L)
  - invalidation_triggered
  - kill_switch (drawdown limit)

Reusa config/keys.json::telegram. No-op se não configurado.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

log = logging.getLogger("macro_brain.notify")

_API = "https://api.telegram.org/bot{token}/{method}"


def _load_config() -> tuple[str, str]:
    """Returns (bot_token, chat_id) from config/keys.json."""
    p = Path(__file__).resolve().parent.parent / "config" / "keys.json"
    if not p.exists():
        return "", ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        tg = data.get("telegram") or {}
        return (tg.get("bot_token") or "").strip(), str(tg.get("chat_id") or "").strip()
    except (OSError, json.JSONDecodeError):
        return "", ""


def send(text: str, parse_mode: str = "HTML") -> bool:
    """Send a text message. Returns True if delivered."""
    token, chat_id = _load_config()
    if not token or not chat_id:
        log.debug("telegram not configured — skipping notify")
        return False

    url = _API.format(token=token, method="sendMessage")
    payload = urlencode({
        "chat_id": chat_id,
        "text": text[:4096],
        "parse_mode": parse_mode,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    req = Request(url, data=payload, method="POST")

    try:
        with urlopen(req, timeout=10) as resp:
            resp.read()
        return True
    except Exception as e:
        log.warning(f"telegram send failed: {e}")
        return False


# ── PRE-BUILT ALERT TEMPLATES ────────────────────────────────

def notify_regime_change(prev: str | None, new: str, confidence: float, reason: str) -> bool:
    emoji = {
        "risk_off": "🔴", "risk_on": "🟢",
        "transition": "🟡", "uncertainty": "⚪",
    }.get(new, "⚪")
    text = (
        f"<b>MACRO BRAIN · REGIME CHANGE</b>\n"
        f"{emoji} <b>{new.upper()}</b>  (conf {confidence:.0%})\n"
        f"from: {prev or '—'}\n"
        f"reason: {reason[:200]}"
    )
    return send(text)


def notify_thesis_opened(thesis: dict) -> bool:
    direction = thesis.get("direction", "?").upper()
    asset = thesis.get("asset", "?")
    conf = thesis.get("confidence", 0.0) or 0.0
    horizon = thesis.get("target_horizon_days", "?")
    rationale = (thesis.get("rationale") or "")[:220]
    arrow = "📈" if direction == "LONG" else "📉"
    text = (
        f"<b>MACRO BRAIN · NEW THESIS</b>\n"
        f"{arrow} {direction} <b>{asset}</b>  (conf {conf:.0%}, {horizon}d)\n"
        f"{rationale}"
    )
    return send(text)


def notify_position_opened(pos: dict, thesis: dict | None = None) -> bool:
    direction = pos.get("side", "?").upper()
    asset = pos.get("asset", "?")
    size = pos.get("size_usd", 0.0) or 0.0
    entry = pos.get("entry_price", 0.0) or 0.0
    arrow = "📈" if direction == "LONG" else "📉"
    text = (
        f"<b>MACRO BRAIN · POSITION OPENED</b> (paper)\n"
        f"{arrow} {direction} <b>{asset}</b>\n"
        f"size: ${size:,.0f}   entry: {entry:,.2f}"
    )
    if thesis:
        text += f"\nthesis: {(thesis.get('rationale') or '')[:160]}"
    return send(text)


def notify_position_closed(pos: dict, pnl: float, reason: str) -> bool:
    direction = pos.get("side", "?").upper()
    asset = pos.get("asset", "?")
    emoji = "✅" if pnl >= 0 else "❌"
    text = (
        f"<b>MACRO BRAIN · POSITION CLOSED</b>\n"
        f"{emoji} {direction} <b>{asset}</b>\n"
        f"P&L: <b>${pnl:+,.2f}</b>\n"
        f"reason: {reason[:200]}"
    )
    return send(text)


def notify_killswitch(reason: str, drawdown_pct: float) -> bool:
    text = (
        f"<b>🛑 MACRO BRAIN · KILL SWITCH</b>\n"
        f"Macro book drawdown: <b>{drawdown_pct:.2f}%</b>\n"
        f"New theses paused.\n"
        f"reason: {reason[:200]}"
    )
    return send(text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ok = send("<b>MACRO BRAIN · TEST</b>\nTelegram notify path is wired.")
    print(f"send result: {ok}")
