"""AURUM Macro Brain — orchestrator.

Main loop do macro_brain. Agenda ingestion + regime + thesis + position
review em schedules configurados em config/macro_params.py.

Modos:
  python -m macro_brain.brain --once        # uma iteração completa
  python -m macro_brain.brain --daemon      # loop infinito (ctrl+c pra parar)
  python -m macro_brain.brain --ingest      # só data ingestion
  python -m macro_brain.brain --status      # snapshot do estado atual
"""
from __future__ import annotations

import argparse
import json
import logging
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from config.macro_params import (
    MACRO_DATA_DIR,
    MACRO_SCHED_BOTS_SEC,
    MACRO_SCHED_MACRO_SEC,
    MACRO_SCHED_NEWS_SEC,
    MACRO_SCHED_REGIME_SEC,
    MACRO_SCHED_REVIEW_SEC,
    MACRO_SCHED_THESIS_SEC,
)
from macro_brain.persistence.store import (
    active_theses, init_db, latest_regime, open_positions, pnl_summary,
)

log = logging.getLogger("macro_brain.brain")

HEALTH_FILE = MACRO_DATA_DIR / "health.json"


# ── HEALTH TRACKING ──────────────────────────────────────────

def _load_health() -> dict:
    if not HEALTH_FILE.exists():
        return {"last_runs": {}, "errors": {}, "uptime_start": datetime.utcnow().isoformat()}
    try:
        return json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"last_runs": {}, "errors": {}, "uptime_start": datetime.utcnow().isoformat()}


def _save_health(h: dict):
    HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_FILE.write_text(json.dumps(h, indent=2, default=str), encoding="utf-8")


def _record_run(job: str, result: dict | None = None, error: str | None = None):
    h = _load_health()
    h.setdefault("last_runs", {})[job] = {
        "ts": datetime.utcnow().isoformat(),
        "result": result,
        "error": error,
    }
    if error:
        h.setdefault("errors", {}).setdefault(job, []).append(
            {"ts": datetime.utcnow().isoformat(), "msg": error[:500]}
        )
        h["errors"][job] = h["errors"][job][-20:]  # keep last 20
    _save_health(h)


def _should_run(job: str, interval_sec: int) -> bool:
    h = _load_health()
    last = h.get("last_runs", {}).get(job, {}).get("ts")
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
    except ValueError:
        return True
    return (datetime.utcnow() - last_dt).total_seconds() >= interval_sec


# ── JOBS ─────────────────────────────────────────────────────

def job_ingest_news():
    from macro_brain.data_ingestion.news import GDELTCollector, NewsAPICollector
    from macro_brain.data_ingestion.rss import RSSCollector
    results = {}
    try:
        results["rss"] = RSSCollector().run()  # Primary — no key, institutional feeds
    except Exception as e:
        log.warning(f"rss job failed: {e}")
        results["rss"] = {"error": str(e)}
    try:
        results["newsapi"] = NewsAPICollector().run()
    except Exception as e:
        log.warning(f"newsapi job failed: {e}")
        results["newsapi"] = {"error": str(e)}
    try:
        results["gdelt"] = GDELTCollector().run()
    except Exception as e:
        log.warning(f"gdelt job failed: {e}")
        results["gdelt"] = {"error": str(e)}
    _record_run("news", result=results)
    return results


def job_ingest_cftc():
    """CFTC Commitments of Traders — weekly institutional positioning."""
    from macro_brain.data_ingestion.cftc import CFTCCollector
    try:
        result = CFTCCollector().run()
        _record_run("cftc", result=result)
        return result
    except Exception as e:
        log.warning(f"cftc failed: {e}")
        _record_run("cftc", error=str(e))
        return {"error": str(e)}


def job_ingest_onchain():
    """BTC on-chain metrics — hashrate, mempool, fees."""
    from macro_brain.data_ingestion.onchain import OnChainCollector
    try:
        result = OnChainCollector().run()
        _record_run("onchain", result=result)
        return result
    except Exception as e:
        log.warning(f"onchain failed: {e}")
        _record_run("onchain", error=str(e))
        return {"error": str(e)}


def job_ingest_whales():
    """SEC insider (Form 4) + institutional (13F) filings."""
    from macro_brain.data_ingestion.whales import WhalesCollector
    try:
        result = WhalesCollector().run()
        _record_run("whales", result=result)
        return result
    except Exception as e:
        log.warning(f"whales failed: {e}")
        _record_run("whales", error=str(e))
        return {"error": str(e)}


def job_ingest_br():
    """Brazilian equities (IBOV + top B3 stocks + BRL)."""
    from macro_brain.data_ingestion.br_equities import BREquitiesCollector
    from datetime import timedelta
    try:
        result = BREquitiesCollector().run(
            since=datetime.utcnow() - timedelta(days=7),
        )
        _record_run("br", result=result)
        return result
    except Exception as e:
        log.warning(f"br failed: {e}")
        _record_run("br", error=str(e))
        return {"error": str(e)}


def job_ingest_defi():
    """DeFi TVL per chain + top protocols."""
    from macro_brain.data_ingestion.defi import DeFiLlamaCollector
    try:
        result = DeFiLlamaCollector().run()
        _record_run("defi", result=result)
        return result
    except Exception as e:
        log.warning(f"defi failed: {e}")
        _record_run("defi", error=str(e))
        return {"error": str(e)}


def job_ingest_hyperliquid():
    """Hyperliquid perps — funding, OI, mid prices."""
    from macro_brain.data_ingestion.hyperliquid import HyperliquidCollector
    try:
        result = HyperliquidCollector().run()
        _record_run("hyperliquid", result=result)
        return result
    except Exception as e:
        log.warning(f"hyperliquid failed: {e}")
        _record_run("hyperliquid", error=str(e))
        return {"error": str(e)}


def job_ingest_calendar():
    """Economic calendar — próximos releases (CPI, FOMC, NFP, etc)."""
    from macro_brain.data_ingestion.calendar import EconomicCalendarCollector
    try:
        result = EconomicCalendarCollector().run()
        _record_run("calendar", result=result)
        return result
    except Exception as e:
        log.warning(f"calendar job failed: {e}")
        _record_run("calendar", error=str(e))
        return {"error": str(e)}


def job_ingest_markets():
    """Yahoo Finance — commodities, forex, rates, equity indices."""
    from macro_brain.data_ingestion.markets import YahooMarketsCollector
    from datetime import timedelta
    try:
        result = YahooMarketsCollector().run(
            since=datetime.utcnow() - timedelta(days=7),
        )
        _record_run("markets", result=result)
        return result
    except Exception as e:
        log.warning(f"markets job failed: {e}")
        _record_run("markets", error=str(e))
        return {"error": str(e)}


def job_ingest_macro():
    from macro_brain.data_ingestion.monetary import FREDCollector
    results = {}
    try:
        results["fred"] = FREDCollector().run(
            since=datetime.utcnow() - timedelta(days=30),
        )
    except Exception as e:
        log.warning(f"fred job failed: {e}")
        results["fred"] = {"error": str(e)}
    _record_run("macro", result=results)
    return results


def job_ingest_sentiment():
    from macro_brain.data_ingestion.sentiment import FearGreedCollector
    results = {}
    try:
        results["fear_greed"] = FearGreedCollector().run(
            since=datetime.utcnow() - timedelta(days=30),
        )
    except Exception as e:
        log.warning(f"fear_greed job failed: {e}")
        results["fear_greed"] = {"error": str(e)}
    _record_run("sentiment", result=results)
    return results


def job_ingest_commodities():
    from macro_brain.data_ingestion.commodities import CoinGeckoCollector
    results = {}
    try:
        results["coingecko"] = CoinGeckoCollector().run()
    except Exception as e:
        log.warning(f"coingecko job failed: {e}")
        results["coingecko"] = {"error": str(e)}
    _record_run("commodities", result=results)
    return results


def job_regime():
    """Classify current regime via rule-based v1 and persist snapshot."""
    try:
        from macro_brain.ml_engine.regime import classify
        snap = classify(persist=True)
        result = {
            "regime": snap.regime,
            "confidence": snap.confidence,
            "reason": snap.reason[:200],
            "rules": len(snap.rules_matched),
            "features_count": len(snap.features),
        }
        log.info(f"[regime] {snap.regime}  conf {snap.confidence:.2%}  {snap.reason[:80]}")
        _record_run("regime", result=result)
        return result
    except Exception as e:
        log.error(f"regime classification failed: {e}")
        _record_run("regime", error=str(e))
        return {"error": str(e)}


def job_thesis():
    """Gera theses a partir do regime atual + scores."""
    try:
        from macro_brain.thesis.generator import generate
        approved = generate(persist=True)
        result = {
            "approved_count": len(approved),
            "theses": [{"asset": t.asset, "dir": t.direction,
                        "conf": t.confidence, "template": t.template_name}
                       for t in approved],
        }
        log.info(f"[thesis] {len(approved)} theses approved")
        for t in approved:
            log.info(f"   [{t.template_name}] {t.direction:<5} {t.asset} conf {t.confidence:.2%}")
        _record_run("thesis", result=result)
        return result
    except Exception as e:
        log.error(f"thesis generation failed: {e}")
        _record_run("thesis", error=str(e))
        return {"error": str(e)}


def job_run_bots():
    """Run registered bot watchers (HL whale, SOL sniper, ...).

    Each bot decides internally if it's ready to emit (watchlists/keys).
    Bots with status=planned yield nothing — zero network cost.
    """
    from macro_brain.bots import ALL_BOTS
    agg = {"inserted": 0, "errors": 0, "per_bot": {}}
    for cls in ALL_BOTS:
        try:
            bot = cls()
            # Skip bots still in 'planned' (no fetch() body yet)
            if bot.describe().status == "planned":
                continue
            r = bot.run()
            agg["inserted"] += r.get("inserted", 0)
            agg["errors"] += r.get("errors", 0)
            agg["per_bot"][bot.slug] = r
        except Exception as e:
            log.warning(f"bot {cls.__name__} failed: {e}")
            agg["errors"] += 1
    _record_run("bots", result=agg)
    return agg


def job_position_review():
    """Abre pending theses + review open positions (MTM + invalidation)."""
    try:
        from macro_brain.position.manager import (
            process_pending_theses, review_open_positions,
        )
        opened = process_pending_theses()
        reviewed = review_open_positions()
        result = {"opened": opened, "review": reviewed}
        log.info(f"[position] opened={opened.get('opened',0)}  "
                 f"closed={reviewed.get('closed',0)}  "
                 f"kept={reviewed.get('kept',0)}")
        _record_run("review", result=result)
        return result
    except Exception as e:
        log.error(f"position review failed: {e}")
        _record_run("review", error=str(e))
        return {"error": str(e)}


# ── ORCHESTRATION ────────────────────────────────────────────

def run_once(force: bool = False):
    """Run all due jobs once. `force=True` ignora throttle."""
    log.info("=" * 60)
    log.info("Macro Brain · run_once")
    log.info("=" * 60)

    init_db()

    schedule = [
        ("sentiment",   job_ingest_sentiment,   MACRO_SCHED_NEWS_SEC),   # 15min
        ("commodities", job_ingest_commodities, MACRO_SCHED_NEWS_SEC),   # 15min
        ("markets",     job_ingest_markets,     MACRO_SCHED_MACRO_SEC),  # daily (Yahoo)
        ("cftc",        job_ingest_cftc,        MACRO_SCHED_MACRO_SEC),  # daily (weekly data)
        ("onchain",     job_ingest_onchain,     MACRO_SCHED_NEWS_SEC),   # 15min
        ("whales",      job_ingest_whales,      MACRO_SCHED_NEWS_SEC),   # 15min
        ("br",          job_ingest_br,          MACRO_SCHED_MACRO_SEC),  # daily (Yahoo BR)
        ("defi",        job_ingest_defi,        MACRO_SCHED_NEWS_SEC),   # 15min (Llama)
        ("hyperliquid", job_ingest_hyperliquid, MACRO_SCHED_NEWS_SEC),   # 15min (HL perps)
        ("calendar",    job_ingest_calendar,    MACRO_SCHED_MACRO_SEC),  # daily
        ("news",        job_ingest_news,        MACRO_SCHED_NEWS_SEC),   # 15min
        ("macro",       job_ingest_macro,       MACRO_SCHED_MACRO_SEC),  # daily (FRED)
        ("bots",        job_run_bots,           MACRO_SCHED_BOTS_SEC),   # 5min
        ("regime",      job_regime,             MACRO_SCHED_REGIME_SEC), # 4h
        ("thesis",      job_thesis,             MACRO_SCHED_THESIS_SEC), # daily
        ("review",      job_position_review,    MACRO_SCHED_REVIEW_SEC), # hourly
    ]

    for name, fn, interval in schedule:
        if force or _should_run(name, interval):
            log.info(f"\n>> {name}")
            try:
                fn()
            except Exception as e:
                log.error(f"{name} failed: {e}\n{traceback.format_exc()}")
                _record_run(name, error=str(e))
        else:
            log.info(f"-- {name} (throttled)")


def run_daemon(interval_sec: int = 300):
    """Loop infinito, checa jobs a cada `interval_sec` segundos (default 5min)."""
    log.info(f"Macro Brain daemon · interval={interval_sec}s · ctrl+c para parar")
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("daemon stopped")
            break
        except Exception as e:
            log.error(f"iteration failed: {e}")
        time.sleep(interval_sec)


def print_status():
    """Snapshot do estado atual pra debug / dashboard feed."""
    init_db()
    h = _load_health()
    regime = latest_regime()
    theses = active_theses()
    positions = open_positions()
    pnl = pnl_summary()

    print("=" * 60)
    print("MACRO BRAIN · STATUS")
    print("=" * 60)
    print(f"Uptime since:  {h.get('uptime_start', 'unknown')}")

    print("\nLast runs:")
    for job, info in sorted(h.get("last_runs", {}).items()):
        ts = info.get("ts", "never")
        err = info.get("error")
        flag = "[FAIL]" if err else "[OK]  "
        print(f"  {flag} {job:<14} {ts}")

    print("\nRegime:")
    if regime:
        print(f"  {regime['regime']} (conf {regime['confidence']:.2%})")
        print(f"  reason: {regime.get('reason', '-')}")
    else:
        print("  (no regime snapshot yet)")

    print(f"\nActive theses: {len(theses)}")
    for t in theses[:5]:
        print(f"  {t['direction']:<5} {t['asset']:<10} conf {t['confidence']:.2%}  {t['rationale'][:40]}")

    print(f"\nOpen positions: {len(positions)}")
    for p in positions[:5]:
        print(f"  {p['side']:<5} {p['asset']:<10} ${p['size_usd']:>9,.0f}  @ {p['entry_price']}")

    print(f"\nP&L (macro book):")
    print(f"  Total: ${pnl['total_pnl']:>+10,.2f}")
    print(f"  Equity: ${pnl['equity']:>10,.2f}  (initial ${pnl['initial']:>10,.2f})")

    print("=" * 60)


# ── CLI ──────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="AURUM Macro Brain orchestrator")
    ap.add_argument("--once", action="store_true", help="Run all due jobs once")
    ap.add_argument("--force", action="store_true", help="Ignore throttle (with --once)")
    ap.add_argument("--daemon", action="store_true", help="Run continuously")
    ap.add_argument("--interval", type=int, default=300, help="Daemon loop interval (s)")
    ap.add_argument("--ingest", action="store_true", help="Only run ingestion jobs")
    ap.add_argument("--status", action="store_true", help="Print current status")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-5s  %(message)s",
    )

    if args.status:
        print_status()
    elif args.ingest:
        init_db()
        job_ingest_sentiment()
        job_ingest_commodities()
        job_ingest_news()
        job_ingest_macro()
    elif args.daemon:
        run_daemon(args.interval)
    elif args.once or not any([args.status, args.ingest, args.daemon]):
        run_once(force=args.force)


if __name__ == "__main__":
    main()
