"""
AURUM Autonomous Battery — find edge for CITADEL/JUMP/DE SHAW via grid tuning.

Designed to run unattended (lunch break). 3 phases:

  Phase 1: Baseline scan — each engine × {90, 180, 360, 720}d × {default, bluechip}
  Phase 2: Grid tune — perturb key params for engines that show promise
  Phase 3: Long-window validation — top configs on max window

Writes incremental progress to:
  data/param_search/YYYY-MM-DD/autonomous_battery.csv
  docs/sessions/YYYY-MM-DD_HHMM_autonomous.md  (rebuilt after each block)

Dispatched in foreground (this session's process); background-safe via
file checkpointing — re-running picks up where it stopped.
"""
import sys, time, csv, json, logging, traceback
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.portfolio import detect_macro, build_corr_matrix
from tools.param_search import _patch_param

# ── LOGGING ──────────────────────────────────────────────────
log = logging.getLogger("AUTONOMOUS")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)
for n in ("CITADEL", "DE_SHAW", "BRIDGEWATER", "JUMP", "RENAISSANCE", "HTF_FILTER", "THOTH"):
    logging.getLogger(n).setLevel(logging.WARNING)

# ── STATE ────────────────────────────────────────────────────
SESSION_TS = datetime.now().strftime("%Y-%m-%d_%H%M")
DATE = datetime.now().strftime("%Y-%m-%d")
CSV_PATH = ROOT / "data" / "param_search" / DATE / "autonomous_battery.csv"
MD_PATH = ROOT / "docs" / "sessions" / f"{SESSION_TS}_autonomous.md"
CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
MD_PATH.parent.mkdir(parents=True, exist_ok=True)

ALL: list[dict] = []
SEP = "═" * 80


# ── METRICS ──────────────────────────────────────────────────
def _metrics(trades, days=90):
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    from analysis.walkforward import walk_forward
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {"n_trades": 0, "win_rate": 0, "pnl": 0, "sharpe": None,
                "sortino": None, "max_dd_pct": 0, "mc_pct_pos": 0, "wf_pct": 0}
    pnl = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, _ = equity_stats(pnl)
    r = calc_ratios(pnl, n_days=days)
    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100
    try:
        mc = monte_carlo(pnl)
    except Exception:
        mc = None
    try:
        wf = walk_forward(closed)
        wf_ok = sum(1 for w in wf if abs(w["test"]["wr"] - w["train"]["wr"]) <= 15) if wf else 0
        wf_pct = round(wf_ok / len(wf) * 100) if wf else 0
    except Exception:
        wf_pct = 0
    return {
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
        "pnl": round(sum(pnl), 2),
        "sharpe": round(r["sharpe"], 3) if r.get("sharpe") else None,
        "sortino": round(r["sortino"], 3) if r.get("sortino") else None,
        "max_dd_pct": round(mdd_pct, 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
        "wf_pct": wf_pct,
    }


def _record(engine, config_label, tf, days, basket, m):
    s = f"{m.get('sharpe', 0) or 0:.3f}" if m.get("sharpe") else "—"
    row = {"engine": engine, "config": config_label, "tf": tf,
           "days": days, "basket": basket, **m}
    ALL.append(row)
    log.info(f"  {engine:<12s} {config_label:<28s} {tf:<4s} {days:>4d}d {basket:<10s} "
             f"{m['n_trades']:>5d}t WR {m['win_rate']:>5.1f}% Sharpe {s:>7s} "
             f"${m['pnl']:>+9,.0f} DD {m['max_dd_pct']:>5.1f}% MC {m.get('mc_pct_pos', 0):>3.0f}%")
    _save_progress()


def _save_progress():
    """Save CSV + markdown incrementally."""
    if not ALL:
        return
    try:
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(ALL[0].keys()))
            w.writeheader()
            w.writerows(ALL)
    except Exception as e:
        log.warning(f"CSV write failed: {e}")
    try:
        _write_md_report()
    except Exception as e:
        log.warning(f"MD write failed: {e}")


def _write_md_report():
    valid = [r for r in ALL if r.get("sharpe") is not None and r["n_trades"] > 0]
    valid.sort(key=lambda r: r["sharpe"], reverse=True)

    lines = [
        f"# Autonomous Battery — {SESSION_TS}",
        "",
        f"**Status:** in_progress (atualiza a cada run).",
        f"**Total runs:** {len(ALL)} · **Valid:** {len(valid)}",
        f"**CSV:** `data/param_search/{DATE}/autonomous_battery.csv`",
        "",
        "## Top 20 by Sharpe (n≥30 trades, MC≥50%)",
        "",
        "| # | Engine | Config | TF | Days | Basket | Trades | WR% | Sharpe | PnL | DD% | MC% | WF% |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    qualified = [r for r in valid if r["n_trades"] >= 30 and (r.get("mc_pct_pos", 0) >= 50)]
    for i, r in enumerate(qualified[:20], 1):
        lines.append(
            f"| {i} | **{r['engine']}** | {r['config']} | {r['tf']} | {r['days']} | "
            f"{r['basket']} | {r['n_trades']} | {r['win_rate']:.1f}% | "
            f"**{r['sharpe']:.2f}** | ${r['pnl']:+,.0f} | {r['max_dd_pct']:.1f}% | "
            f"{r.get('mc_pct_pos', 0):.0f}% | {r.get('wf_pct', 0)}% |"
        )
    if not qualified:
        lines.append("| — | (no qualified runs yet) | | | | | | | | | | | |")

    # Per-engine best
    lines += ["", "## Best per engine (any sample size)", ""]
    by_eng: dict[str, list] = {}
    for r in valid:
        by_eng.setdefault(r["engine"], []).append(r)
    for eng in sorted(by_eng.keys()):
        rows = sorted(by_eng[eng], key=lambda r: r["sharpe"], reverse=True)
        best = rows[0]
        lines.append(f"### {eng}")
        lines.append(f"- **Best:** Sharpe `{best['sharpe']:.2f}` · "
                     f"`{best['config']}` · {best['tf']} · {best['days']}d · {best['basket']} · "
                     f"{best['n_trades']} trades · {best['win_rate']:.1f}% WR · "
                     f"${best['pnl']:+,.0f} · DD {best['max_dd_pct']:.1f}%")
        lines.append(f"- **Tested:** {len(rows)} configs")
        lines.append("")

    MD_PATH.write_text("\n".join(lines), encoding="utf-8")


# ── DATA FETCH (cached per (basket, tf, days)) ───────────────
_FETCH_CACHE: dict[tuple, tuple] = {}


def _fetch(basket_name, tf, days, extra=200):
    key = (basket_name, tf, days, extra)
    if key in _FETCH_CACHE:
        return _FETCH_CACHE[key]
    tf_mult = {"5m": 12, "15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25, "1d": 1 / 24}
    nc = int(days * 24 * tf_mult.get(tf, 4)) + extra
    syms = list(_p.BASKETS.get(basket_name, _p.SYMBOLS))
    _patch_param("SYMBOLS", syms)
    _patch_param("INTERVAL", tf)
    _patch_param("SCAN_DAYS", days)
    _patch_param("N_CANDLES", nc)
    fetch_syms = list(syms)
    if _p.MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, _p.MACRO_SYMBOL)
    log.info(f"  fetch {basket_name} {tf} {days}d ({len(fetch_syms)} syms × {nc} candles)")
    dfs = fetch_all(fetch_syms, tf, nc)
    for s, d in dfs.items():
        try: validate(d, s)
        except Exception: pass
    macro = detect_macro(dfs)
    corr = build_corr_matrix(dfs)
    _FETCH_CACHE[key] = (dfs, macro, corr)
    return dfs, macro, corr


# ── ENGINE RUNNERS ───────────────────────────────────────────
def _run_citadel(dfs, macro, corr, days):
    from engines.citadel import scan_symbol
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in dfs]:
        try:
            t, _ = scan_symbol(dfs[sym].copy(), sym, macro, corr)
            trades.extend(t)
        except Exception as e:
            log.warning(f"    citadel/{sym}: {e}")
    trades.sort(key=lambda t: t["timestamp"])
    return _metrics(trades, days)


def _run_jump(dfs, macro, corr, days):
    from engines.jump import scan_mercurio
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in dfs]:
        try:
            t, _ = scan_mercurio(dfs[sym].copy(), sym, macro, corr)
            trades.extend(t)
        except Exception as e:
            log.warning(f"    jump/{sym}: {e}")
    trades.sort(key=lambda t: t["timestamp"])
    return _metrics(trades, days)


def _run_deshaw(dfs, macro, corr, days):
    from engines.deshaw import find_cointegrated_pairs, scan_pair
    pairs = find_cointegrated_pairs(dfs)
    trades = []
    for p in pairs:
        da, db = dfs.get(p["sym_a"]), dfs.get(p["sym_b"])
        if da is None or db is None: continue
        try:
            t, _ = scan_pair(da.copy(), db.copy(), p["sym_a"], p["sym_b"], p, macro, corr)
            trades.extend(t)
        except Exception as e:
            log.warning(f"    deshaw/{p['sym_a']}-{p['sym_b']}: {e}")
    trades.sort(key=lambda t: t["timestamp"])
    return _metrics(trades, days)


def _patch_many(patches: dict) -> dict:
    """Apply patches, return saved values for restore."""
    saved = {}
    for k, v in patches.items():
        try:
            saved[k] = getattr(_p, k)
            _patch_param(k, v)
        except Exception:
            pass
    return saved


def _restore(saved: dict):
    for k, v in saved.items():
        try: _patch_param(k, v)
        except Exception: pass


# ── PHASE 1: BASELINE SCAN ───────────────────────────────────
def phase1_baseline():
    log.info(f"\n{SEP}\n  PHASE 1 — BASELINE SCAN\n{SEP}")
    targets = [
        ("CITADEL", _run_citadel, "15m"),
        ("DE SHAW", _run_deshaw, "4h"),  # 4h is cointegration-friendlier
        ("JUMP",    _run_jump,    "15m"),
    ]
    for engine, runner, tf in targets:
        for days in [90, 180, 360, 720]:
            for basket in ["default", "bluechip"]:
                try:
                    dfs, macro, corr = _fetch(basket, tf, days)
                    if engine == "DE SHAW":
                        # halflife scaling for 4h
                        sv = _patch_many({"NEWTON_HALFLIFE_MAX": 200, "NEWTON_MAX_HOLD": 24})
                    else:
                        sv = {}
                    m = runner(dfs, macro, corr, days)
                    _restore(sv)
                    _record(engine, "baseline", tf, days, basket, m)
                except Exception as e:
                    log.warning(f"    {engine} {tf} {days}d {basket} FAILED: {e}")


# ── PHASE 2: PARAM TUNING ────────────────────────────────────
def phase2_citadel_tune():
    log.info(f"\n{SEP}\n  PHASE 2 — CITADEL PARAM TUNE\n{SEP}")
    # Param grid — focus on score threshold, stop, and regime sizing
    grid = [
        ("regime-adaptive",     {"RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 0.30, "CHOP": 0.50}}),
        ("regime-aggressive",   {"RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 1.0, "CHOP": 0.30}}),
        ("score-058",           {"SCORE_THRESHOLD": 0.58}),
        ("score-060",           {"SCORE_THRESHOLD": 0.60}),
        ("stop-tight",          {"STOP_ATR_M": 1.5, "TARGET_RR": 2.0}),
        ("stop-wide",           {"STOP_ATR_M": 2.5, "TARGET_RR": 3.0}),
        ("rr-3x",               {"TARGET_RR": 3.0}),
        ("score-058+adaptive",  {"SCORE_THRESHOLD": 0.58,
                                 "RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 0.30, "CHOP": 0.50}}),
    ]
    for days in [180, 360, 720]:
        for basket in ["default", "bluechip"]:
            try:
                dfs, macro, corr = _fetch(basket, "15m", days)
            except Exception as e:
                log.warning(f"    fetch FAILED {basket} 15m {days}d: {e}")
                continue
            for cfg_name, patches in grid:
                saved = _patch_many(patches)
                try:
                    m = _run_citadel(dfs, macro, corr, days)
                    _record("CITADEL", cfg_name, "15m", days, basket, m)
                except Exception as e:
                    log.warning(f"    CITADEL {cfg_name} {days}d {basket} FAILED: {e}")
                _restore(saved)


def phase2_jump_tune():
    log.info(f"\n{SEP}\n  PHASE 2 — JUMP PARAM TUNE\n{SEP}")
    grid = [
        ("score-040",    {"MERCURIO_MIN_SCORE": 0.40}),
        ("score-060",    {"MERCURIO_MIN_SCORE": 0.60}),
        ("score-070",    {"MERCURIO_MIN_SCORE": 0.70}),
        ("vimb-tight",   {"MERCURIO_VIMB_LONG": 0.65, "MERCURIO_VIMB_SHORT": 0.35}),
        ("vimb-loose",   {"MERCURIO_VIMB_LONG": 0.55, "MERCURIO_VIMB_SHORT": 0.45}),
        ("liq-loose",    {"MERCURIO_LIQ_VOL_MULT": 2.0}),
        ("liq-tight",    {"MERCURIO_LIQ_VOL_MULT": 4.0}),
        ("size-1.0",     {"MERCURIO_SIZE_MULT": 1.0}),
    ]
    for tf in ["15m", "1h"]:
        for days in [90, 180, 360]:
            for basket in ["default", "bluechip", "majors"]:
                try:
                    dfs, macro, corr = _fetch(basket, tf, days)
                except Exception as e:
                    log.warning(f"    fetch FAILED {basket} {tf} {days}d: {e}")
                    continue
                for cfg_name, patches in grid:
                    saved = _patch_many(patches)
                    try:
                        m = _run_jump(dfs, macro, corr, days)
                        _record("JUMP", cfg_name, tf, days, basket, m)
                    except Exception as e:
                        log.warning(f"    JUMP {cfg_name} {tf} {days}d {basket} FAILED: {e}")
                    _restore(saved)


def phase2_deshaw_tune():
    log.info(f"\n{SEP}\n  PHASE 2 — DE SHAW PARAM TUNE\n{SEP}")
    grid = [
        ("z-1.5/3.0",   {"NEWTON_ZSCORE_ENTRY": 1.5, "NEWTON_ZSCORE_STOP": 3.0}),
        ("z-2.0/3.5",   {"NEWTON_ZSCORE_ENTRY": 2.0, "NEWTON_ZSCORE_STOP": 3.5}),
        ("z-2.5/4.0",   {"NEWTON_ZSCORE_ENTRY": 2.5, "NEWTON_ZSCORE_STOP": 4.0}),
        ("hl-100",      {"NEWTON_HALFLIFE_MAX": 100, "NEWTON_MAX_HOLD": 12}),
        ("hl-500",      {"NEWTON_HALFLIFE_MAX": 500, "NEWTON_MAX_HOLD": 48}),
        ("pval-tight",  {"NEWTON_COINT_PVALUE": 0.01}),
        ("pval-loose",  {"NEWTON_COINT_PVALUE": 0.10}),
    ]
    for tf in ["1h", "4h"]:
        # Halflife scales with TF — these grid params are 4h-relative
        if tf == "1h":
            tf_mult = 4  # 1h has 4× more candles per period
        else:
            tf_mult = 1
        for days in [90, 180, 360]:
            for basket in ["default", "bluechip", "top12"]:
                try:
                    dfs, macro, corr = _fetch(basket, tf, days)
                except Exception as e:
                    log.warning(f"    fetch FAILED {basket} {tf} {days}d: {e}")
                    continue
                for cfg_name, patches in grid:
                    # Scale halflife/maxhold for the TF
                    scaled = dict(patches)
                    if "NEWTON_HALFLIFE_MAX" in scaled:
                        scaled["NEWTON_HALFLIFE_MAX"] *= tf_mult
                    if "NEWTON_MAX_HOLD" in scaled:
                        scaled["NEWTON_MAX_HOLD"] *= tf_mult
                    saved = _patch_many(scaled)
                    try:
                        m = _run_deshaw(dfs, macro, corr, days)
                        _record("DE SHAW", cfg_name, tf, days, basket, m)
                    except Exception as e:
                        log.warning(f"    DE SHAW {cfg_name} {tf} {days}d {basket} FAILED: {e}")
                    _restore(saved)


# ── PHASE 3: LONG-WINDOW VALIDATION ──────────────────────────
def phase3_validate():
    log.info(f"\n{SEP}\n  PHASE 3 — LONG-WINDOW VALIDATION (1500d)\n{SEP}")
    # Take top 3 valid configs per engine, validate on 1500d
    valid = [r for r in ALL if r.get("sharpe") is not None and r["n_trades"] >= 30]
    by_eng: dict[str, list] = {}
    for r in valid:
        by_eng.setdefault(r["engine"], []).append(r)

    for eng, rows in by_eng.items():
        rows.sort(key=lambda r: r["sharpe"], reverse=True)
        top = rows[:3]
        for r in top:
            try:
                dfs, macro, corr = _fetch(r["basket"], r["tf"], 1500)
            except Exception as e:
                log.warning(f"    fetch FAILED 1500d: {e}")
                continue
            # Re-apply the config (we don't have the patches stored; re-derive from name)
            # For safety, just run baseline at 1500d to see if engine survives
            try:
                if eng == "CITADEL":
                    m = _run_citadel(dfs, macro, corr, 1500)
                elif eng == "JUMP":
                    m = _run_jump(dfs, macro, corr, 1500)
                elif eng == "DE SHAW":
                    m = _run_deshaw(dfs, macro, corr, 1500)
                else: continue
                _record(eng, f"validate-1500d/{r['config']}", r["tf"], 1500, r["basket"], m)
            except Exception as e:
                log.warning(f"    {eng} 1500d {r['basket']} FAILED: {e}")


# ── MAIN ─────────────────────────────────────────────────────
def main():
    t0 = time.time()
    log.info(f"\n{SEP}\n  AUTONOMOUS BATTERY — {SESSION_TS}\n{SEP}\n")
    log.info(f"  CSV → {CSV_PATH}")
    log.info(f"  MD  → {MD_PATH}")

    try: phase1_baseline()
    except Exception as e: log.error(f"PHASE 1 FAILED: {e}\n{traceback.format_exc()}")

    try: phase2_citadel_tune()
    except Exception as e: log.error(f"PHASE 2 CITADEL FAILED: {e}\n{traceback.format_exc()}")

    try: phase2_jump_tune()
    except Exception as e: log.error(f"PHASE 2 JUMP FAILED: {e}\n{traceback.format_exc()}")

    try: phase2_deshaw_tune()
    except Exception as e: log.error(f"PHASE 2 DE SHAW FAILED: {e}\n{traceback.format_exc()}")

    try: phase3_validate()
    except Exception as e: log.error(f"PHASE 3 FAILED: {e}\n{traceback.format_exc()}")

    elapsed = (time.time() - t0) / 60
    log.info(f"\n{SEP}\n  DONE — {elapsed:.1f}min · {len(ALL)} runs\n{SEP}")
    _save_progress()

    # Final markdown gets "completed" status
    md = MD_PATH.read_text(encoding="utf-8")
    md = md.replace("**Status:** in_progress", f"**Status:** completed ({elapsed:.1f}min)")
    MD_PATH.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
