"""Position manager — lifecycle completo em paper mode.

Responsibilities:
  - open_from_thesis(thesis_id): abre posição pra tese aprovada
  - review_open_positions(): checa invalidation, time_stop, fecha se premise broke
  - mark_to_market(): atualiza pnl_unrealized usando preços atuais

Paper mode = simulação interna, nenhuma ordem real. Phase 2 adiciona
modo live usando core.exchange_api + core.audit_trail + core.risk_gates.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from config.macro_params import (
    MACRO_ACCOUNT_SIZE,
    MACRO_EXEC_MODE,
    MACRO_TIME_STOP_DAYS,
)
from macro_brain.persistence.store import (
    active_theses, close_position, insert_position, latest_macro, log_pnl,
    open_positions, pnl_summary, update_thesis_status,
)
from macro_brain.position.sizing import calc_size_usd

log = logging.getLogger("macro_brain.position")


# ── ENTRY ────────────────────────────────────────────────────

def _current_price(asset: str) -> float | None:
    """Get latest price from macro_data (CoinGecko snapshot)."""
    prefix_map = {
        "BTCUSDT": "BTC_SPOT", "ETHUSDT": "ETH_SPOT",
        "SOLUSDT": "SOL_SPOT", "BNBUSDT": "BNB_SPOT",
    }
    metric = prefix_map.get(asset)
    if not metric:
        return None
    latest = latest_macro(metric, n=1)
    if not latest:
        return None
    return latest[0]["value"]


def open_from_thesis(thesis: dict, regime_alignment: float = 1.0) -> dict | None:
    """Open a paper position from an approved thesis row.

    Returns position dict on success, None on failure.
    Idempotent: if thesis já tem posição aberta, retorna None.
    """
    # Already has position?
    existing = [p for p in open_positions() if p["thesis_id"] == thesis["id"]]
    if existing:
        log.info(f"  thesis {thesis['id'][:8]} já tem posição aberta — skip")
        return None

    price = _current_price(thesis["asset"])
    if price is None:
        log.warning(f"  no price for {thesis['asset']} — skip")
        return None

    # Current equity from pnl ledger
    summary = pnl_summary()
    equity = summary["equity"]

    # Sizing
    size_usd = calc_size_usd(
        confidence=thesis["confidence"],
        account_equity=equity,
        regime_alignment=regime_alignment,
    )

    if size_usd <= 10:  # absolute floor
        log.info(f"  size too small (${size_usd:.2f}) — skip")
        return None

    pid = insert_position(
        thesis_id=thesis["id"], asset=thesis["asset"],
        side=thesis["direction"], size_usd=size_usd,
        entry_price=price,
    )
    update_thesis_status(thesis["id"], "active")
    log_pnl("position_open", pnl_delta=0.0, account_equity=equity,
            position_id=pid, asset=thesis["asset"])

    log.info(f"  OPEN  {thesis['direction']:<5} {thesis['asset']:<10} "
             f"${size_usd:>8,.0f} @ {price}  (thesis {thesis['id'][:8]})")

    return {
        "id": pid, "asset": thesis["asset"], "side": thesis["direction"],
        "size_usd": size_usd, "entry_price": price,
    }


# ── INVALIDATION CHECKS ──────────────────────────────────────

def _evaluate_invalidation(
    invalidation: list[dict], thesis: dict, regime: dict | None,
    features_flat: dict,
) -> tuple[bool, str]:
    """Returns (should_close, reason)."""
    from datetime import datetime as _dt

    for cond in invalidation or []:
        ctype = cond.get("type")

        # Regime flip
        if ctype == "regime_flip" and regime:
            now_regime = regime.get("regime")
            frm = cond.get("from")
            frm_any = cond.get("from_any", [])
            to = cond.get("to")
            to_any = cond.get("to_any", [])
            # This condition triggers if regime NO LONGER matches the thesis's origin
            if (frm and now_regime != frm) or (frm_any and now_regime not in frm_any):
                if not to_any and not to:
                    return True, f"regime flipped away from {frm or frm_any}"
                if to and now_regime == to:
                    return True, f"regime flipped to {to}"
                if to_any and now_regime in to_any:
                    return True, f"regime flipped to {now_regime}"

        # Feature threshold
        elif ctype == "feature_threshold":
            feat = cond.get("feature", "")
            op = cond.get("op", ">=")
            val = cond.get("value")
            current = features_flat.get(feat)
            if current is None or val is None:
                continue
            triggered = (
                (op == ">=" and current >= val) or
                (op == "<=" and current <= val) or
                (op == ">" and current > val) or
                (op == "<" and current < val) or
                (op == "==" and current == val)
            )
            if triggered:
                return True, f"{feat}={current} {op} {val}"

        # Time stop
        elif ctype == "time_stop":
            days = cond.get("days", MACRO_TIME_STOP_DAYS)
            try:
                created = _dt.fromisoformat(thesis["created_ts"])
                if (datetime.utcnow() - created).days >= days:
                    return True, f"time_stop {days}d reached"
            except (ValueError, TypeError):
                pass

    # Absolute time stop fallback
    try:
        created = _dt.fromisoformat(thesis["created_ts"])
        horizon = thesis.get("target_horizon_days") or MACRO_TIME_STOP_DAYS
        if (datetime.utcnow() - created).days >= horizon + 30:
            return True, f"expired beyond horizon+30d"
    except (ValueError, TypeError):
        pass

    return False, ""


# ── MARK-TO-MARKET ───────────────────────────────────────────

def _mark_to_market(pos: dict, current_price: float) -> float:
    """Compute unrealized P&L for an open position."""
    size = pos["size_usd"]
    entry = pos["entry_price"]
    if entry == 0:
        return 0.0
    if pos["side"] == "long":
        pnl_pct = (current_price - entry) / entry
    else:  # short
        pnl_pct = (entry - current_price) / entry
    return round(size * pnl_pct, 2)


# ── REVIEW ───────────────────────────────────────────────────

def review_open_positions() -> dict:
    """Review all open positions: mark-to-market, check invalidation, close if needed."""
    import json as _json

    from macro_brain.ml_engine.features import build_features
    from macro_brain.ml_engine.regime import classify
    from macro_brain.persistence.store import latest_regime, _conn

    actions = {"closed": 0, "kept": 0, "errors": 0}

    # Get current state
    try:
        fv = build_features()
        regime = latest_regime() or {"regime": "uncertainty"}
        feats = fv.flat()
    except Exception as e:
        log.error(f"review: failed to build state: {e}")
        return {"error": str(e)}

    positions = open_positions()
    if not positions:
        log.info("  no open positions")
        return actions

    # Build thesis lookup
    thesis_lookup = {t["id"]: t for t in active_theses()}
    # Include closed theses too (maybe position reopened after tese closed)
    with _conn() as c:
        all_theses_rows = c.execute("SELECT * FROM theses").fetchall()
        all_theses = {r["id"]: dict(r) for r in all_theses_rows}

    for pos in positions:
        thesis = thesis_lookup.get(pos["thesis_id"]) or all_theses.get(pos["thesis_id"])
        if not thesis:
            log.warning(f"  position {pos['id'][:8]}: thesis {pos['thesis_id'][:8]} not found")
            actions["errors"] += 1
            continue

        price = _current_price(pos["asset"])
        if price is None:
            log.warning(f"  position {pos['id'][:8]}: no price")
            continue

        pnl_unrealized = _mark_to_market(pos, price)

        # Invalidation check
        try:
            invalidation = _json.loads(thesis.get("invalidation_json") or "[]")
        except _json.JSONDecodeError:
            invalidation = []

        should_close, reason = _evaluate_invalidation(
            invalidation, thesis, regime, feats
        )

        if should_close:
            # Close position
            close_position(pos["id"], exit_price=price, pnl=pnl_unrealized)
            summary = pnl_summary()
            new_equity = summary["equity"] + pnl_unrealized
            log_pnl("position_close", pnl_delta=pnl_unrealized,
                    account_equity=new_equity,
                    position_id=pos["id"], asset=pos["asset"])
            update_thesis_status(pos["thesis_id"], "closed", reason=reason)
            log.info(f"  CLOSE {pos['side']:<5} {pos['asset']:<10} "
                     f"pnl=${pnl_unrealized:>+7,.2f}  reason: {reason[:40]}")
            actions["closed"] += 1
        else:
            log.info(f"  KEEP  {pos['side']:<5} {pos['asset']:<10} "
                     f"unrealized=${pnl_unrealized:>+7,.2f}")
            actions["kept"] += 1

    # Snapshot mark-to-market into pnl_ledger
    if positions:
        try:
            total_unreal = sum(
                _mark_to_market(p, _current_price(p["asset"]) or p["entry_price"])
                for p in open_positions()
            )
            summary = pnl_summary()
            log_pnl("mark_to_market", pnl_delta=total_unreal,
                    account_equity=summary["equity"] + total_unreal)
        except Exception as e:
            log.warning(f"  MTM snapshot failed: {e}")

    return actions


# ── ORCHESTRATION ENTRY ──────────────────────────────────────

def process_pending_theses() -> dict:
    """Abre positions pra todas pending theses (status='pending')."""
    from macro_brain.persistence.store import _conn

    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM theses WHERE status = 'pending' ORDER BY created_ts ASC"
        ).fetchall()

    pending = [dict(r) for r in rows]
    opened = 0
    for t in pending:
        if open_from_thesis(t, regime_alignment=1.0):
            opened += 1
    return {"pending_count": len(pending), "opened": opened}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    print(f"MACRO_EXEC_MODE: {MACRO_EXEC_MODE}")

    # 1. Open any pending theses
    print("\n--- Processing pending theses ---")
    r1 = process_pending_theses()
    print(f"  {r1}")

    # 2. Review open positions
    print("\n--- Reviewing open positions ---")
    r2 = review_open_positions()
    print(f"  {r2}")

    # 3. Status
    from macro_brain.persistence.store import open_positions as _op
    print(f"\n--- Open positions: {len(_op())} ---")
    for p in _op():
        print(f"  {p['side']:<5} {p['asset']:<10} ${p['size_usd']:,.0f} @ {p['entry_price']}")
