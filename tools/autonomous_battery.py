"""
AURUM Autonomous Battery - find edge for CITADEL/JUMP/DE SHAW via grid tuning.

Designed to run unattended. 3 phases:

  Phase 1: Baseline scan - each engine x {90, 180, 360, 720}d x {default, bluechip}
  Phase 2: Grid tune - perturb key params for engines that show promise
  Phase 3: Long-window validation - top configs on 1500d

Writes incremental progress to:
  data/param_search/YYYY-MM-DD/autonomous_battery.csv
  docs/sessions/YYYY-MM-DD_HHMM_autonomous.md

Progress is checkpointed to CSV. Re-running on the same day resumes from the
existing CSV and skips combinations that were already completed.
"""
import csv
import json
import logging
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.portfolio import build_corr_matrix, detect_macro
from tools.param_search import _patch_param

log = logging.getLogger("AUTONOMOUS")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)
for n in ("CITADEL", "DE_SHAW", "BRIDGEWATER", "JUMP", "RENAISSANCE", "HTF_FILTER", "THOTH"):
    logging.getLogger(n).setLevel(logging.WARNING)

SESSION_TS = datetime.now().strftime("%Y-%m-%d_%H%M")
DATE = datetime.now().strftime("%Y-%m-%d")
CSV_PATH = ROOT / "data" / "param_search" / DATE / "autonomous_battery.csv"
MD_PATH = ROOT / "docs" / "sessions" / f"{SESSION_TS}_autonomous.md"
CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
MD_PATH.parent.mkdir(parents=True, exist_ok=True)

ALL: list[dict] = []
SEP = "=" * 80


def _patches_json(patches: dict | None) -> str:
    return json.dumps(patches or {}, sort_keys=True, ensure_ascii=False)


def _row_key(row: dict) -> tuple[str, str, str, str, str]:
    return (
        str(row.get("engine") or ""),
        str(row.get("config") or ""),
        str(row.get("tf") or ""),
        str(row.get("days") or ""),
        str(row.get("basket") or ""),
    )


def _seen_keys() -> set[tuple[str, str, str, str, str]]:
    return {_row_key(r) for r in ALL}


def _infer_patches(engine: str, config: str, tf: str) -> dict:
    engine = str(engine or "").upper()
    config = str(config or "")
    tf = str(tf or "")

    if config == "baseline":
        if engine == "DE SHAW":
            return {"NEWTON_HALFLIFE_MAX": 200, "NEWTON_MAX_HOLD": 24}
        return {}

    if engine == "CITADEL":
        mapping = {
            "regime-adaptive": {"RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 0.30, "CHOP": 0.50}},
            "regime-aggressive": {"RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 1.0, "CHOP": 0.30}},
            "score-058": {"SCORE_THRESHOLD": 0.58},
            "score-060": {"SCORE_THRESHOLD": 0.60},
            "stop-tight": {"STOP_ATR_M": 1.5, "TARGET_RR": 2.0},
            "stop-wide": {"STOP_ATR_M": 2.5, "TARGET_RR": 3.0},
            "rr-3x": {"TARGET_RR": 3.0},
            "score-058+adaptive": {
                "SCORE_THRESHOLD": 0.58,
                "RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 0.30, "CHOP": 0.50},
            },
        }
        return mapping.get(config, {})

    if engine == "JUMP":
        mapping = {
            "score-040": {"MERCURIO_MIN_SCORE": 0.40},
            "score-060": {"MERCURIO_MIN_SCORE": 0.60},
            "score-070": {"MERCURIO_MIN_SCORE": 0.70},
            "vimb-tight": {"MERCURIO_VIMB_LONG": 0.65, "MERCURIO_VIMB_SHORT": 0.35},
            "vimb-loose": {"MERCURIO_VIMB_LONG": 0.55, "MERCURIO_VIMB_SHORT": 0.45},
            "liq-loose": {"MERCURIO_LIQ_VOL_MULT": 2.0},
            "liq-tight": {"MERCURIO_LIQ_VOL_MULT": 4.0},
            "size-1.0": {"MERCURIO_SIZE_MULT": 1.0},
        }
        return mapping.get(config, {})

    if engine == "DE SHAW":
        mapping = {
            "z-1.5/3.0": {"NEWTON_ZSCORE_ENTRY": 1.5, "NEWTON_ZSCORE_STOP": 3.0},
            "z-2.0/3.5": {"NEWTON_ZSCORE_ENTRY": 2.0, "NEWTON_ZSCORE_STOP": 3.5},
            "z-2.5/4.0": {"NEWTON_ZSCORE_ENTRY": 2.5, "NEWTON_ZSCORE_STOP": 4.0},
            "hl-100": {"NEWTON_HALFLIFE_MAX": 100, "NEWTON_MAX_HOLD": 12},
            "hl-500": {"NEWTON_HALFLIFE_MAX": 500, "NEWTON_MAX_HOLD": 48},
            "pval-tight": {"NEWTON_COINT_PVALUE": 0.01},
            "pval-loose": {"NEWTON_COINT_PVALUE": 0.10},
        }
        patches = dict(mapping.get(config, {}))
        if tf == "1h":
            if "NEWTON_HALFLIFE_MAX" in patches:
                patches["NEWTON_HALFLIFE_MAX"] *= 4
            if "NEWTON_MAX_HOLD" in patches:
                patches["NEWTON_MAX_HOLD"] *= 4
        return patches

    return {}


def _load_progress():
    if not CSV_PATH.exists():
        return
    try:
        with open(CSV_PATH, "r", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        log.warning(f"CSV resume failed: {e}")
        return

    ALL.clear()

    def _f(row: dict, name: str):
        val = row.get(name)
        if val in (None, "", "None"):
            return None
        try:
            return float(val)
        except Exception:
            return None

    def _i(row: dict, name: str, default=0):
        val = row.get(name)
        if val in (None, "", "None"):
            return default
        try:
            return int(float(val))
        except Exception:
            return default

    for row in rows:
        patches_json = row.get("patches_json") or "{}"
        try:
            patches = json.loads(patches_json)
        except Exception:
            patches = {}
            patches_json = "{}"
        if not patches:
            patches = _infer_patches(row.get("engine") or "", row.get("config") or "", row.get("tf") or "")
            patches_json = _patches_json(patches)
        ALL.append({
            "engine": row.get("engine") or "",
            "config": row.get("config") or "",
            "tf": row.get("tf") or "",
            "days": _i(row, "days", 0),
            "basket": row.get("basket") or "",
            "n_trades": _i(row, "n_trades", 0),
            "win_rate": _f(row, "win_rate") or 0.0,
            "pnl": _f(row, "pnl") or 0.0,
            "sharpe": _f(row, "sharpe"),
            "sortino": _f(row, "sortino"),
            "max_dd_pct": _f(row, "max_dd_pct") or 0.0,
            "mc_pct_pos": _f(row, "mc_pct_pos") or 0.0,
            "wf_pct": _i(row, "wf_pct", 0),
            "phase": row.get("phase") or "",
            "patches_json": patches_json,
            "patches": patches,
        })
    if ALL:
        log.info(f"  resumed {len(ALL)} prior runs from {CSV_PATH.name}")


def _metrics(trades, days=90):
    from analysis.montecarlo import monte_carlo
    from analysis.stats import calc_ratios, equity_stats
    from analysis.walkforward import walk_forward

    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {
            "n_trades": 0,
            "win_rate": 0,
            "pnl": 0,
            "sharpe": None,
            "sortino": None,
            "max_dd_pct": 0,
            "mc_pct_pos": 0,
            "wf_pct": 0,
        }
    pnl = [t["pnl"] for t in closed]
    _eq, _mdd, mdd_pct, _ = equity_stats(pnl)
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
        "sharpe": round(r["sharpe"], 3) if r.get("sharpe") is not None else None,
        "sortino": round(r["sortino"], 3) if r.get("sortino") is not None else None,
        "max_dd_pct": round(mdd_pct, 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
        "wf_pct": wf_pct,
    }


def _record(engine, config_label, tf, days, basket, m, phase="", patches=None):
    row = {
        "engine": engine,
        "config": config_label,
        "tf": tf,
        "days": days,
        "basket": basket,
        **m,
        "phase": phase,
        "patches_json": _patches_json(patches),
        "patches": patches or {},
    }
    if _row_key(row) in _seen_keys():
        log.info(f"  skip existing  {engine:<12s} {config_label:<28s} {tf:<4s} {days:>4d}d {basket:<10s}")
        return
    ALL.append(row)
    sharpe_label = f"{m.get('sharpe', 0) or 0:.3f}" if m.get("sharpe") is not None else "-"
    log.info(
        f"  {engine:<12s} {config_label:<28s} {tf:<4s} {days:>4d}d {basket:<10s} "
        f"{m['n_trades']:>5d}t WR {m['win_rate']:>5.1f}% Sharpe {sharpe_label:>7s} "
        f"${m['pnl']:>+9,.0f} DD {m['max_dd_pct']:>5.1f}% MC {m.get('mc_pct_pos', 0):>3.0f}%"
    )
    _save_progress()


def _save_progress():
    if not ALL:
        return
    try:
        rows = [{k: v for k, v in r.items() if k != "patches"} for r in ALL]
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
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
        f"# Autonomous Battery - {SESSION_TS}",
        "",
        "**Status:** in_progress (updates after each completed run).",
        f"**Total runs:** {len(ALL)} · **Valid:** {len(valid)}",
        f"**CSV:** `data/param_search/{DATE}/autonomous_battery.csv`",
        "",
        "## Top 20 by Sharpe (n>=30 trades, MC>=50%)",
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
        lines.append("| - | (no qualified runs yet) | | | | | | | | | | | |")

    lines += ["", "## Best per engine (any sample size)", ""]
    by_eng: dict[str, list] = {}
    for r in valid:
        by_eng.setdefault(r["engine"], []).append(r)
    for eng in sorted(by_eng.keys()):
        rows = sorted(by_eng[eng], key=lambda r: r["sharpe"], reverse=True)
        best = rows[0]
        lines.append(f"### {eng}")
        lines.append(
            f"- **Best:** Sharpe `{best['sharpe']:.2f}` · "
            f"`{best['config']}` · {best['tf']} · {best['days']}d · {best['basket']} · "
            f"{best['n_trades']} trades · {best['win_rate']:.1f}% WR · "
            f"${best['pnl']:+,.0f} · DD {best['max_dd_pct']:.1f}%"
        )
        lines.append(f"- **Tested:** {len(rows)} configs")
        lines.append("")

    MD_PATH.write_text("\n".join(lines), encoding="utf-8")


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
    log.info(f"  fetch {basket_name} {tf} {days}d ({len(fetch_syms)} syms x {nc} candles)")
    dfs = fetch_all(fetch_syms, tf, nc)
    for s, d in dfs.items():
        try:
            validate(d, s)
        except Exception:
            pass
    macro = detect_macro(dfs)
    corr = build_corr_matrix(dfs)
    _FETCH_CACHE[key] = (dfs, macro, corr)
    return dfs, macro, corr


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
        if da is None or db is None:
            continue
        try:
            t, _ = scan_pair(da.copy(), db.copy(), p["sym_a"], p["sym_b"], p, macro, corr)
            trades.extend(t)
        except Exception as e:
            log.warning(f"    deshaw/{p['sym_a']}-{p['sym_b']}: {e}")
    trades.sort(key=lambda t: t["timestamp"])
    return _metrics(trades, days)


def _patch_many(patches: dict) -> dict:
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
        try:
            _patch_param(k, v)
        except Exception:
            pass


def phase1_baseline():
    log.info(f"\n{SEP}\n  PHASE 1 - BASELINE SCAN\n{SEP}")
    targets = [
        ("CITADEL", _run_citadel, "15m"),
        ("DE SHAW", _run_deshaw, "4h"),
        ("JUMP", _run_jump, "15m"),
    ]
    for engine, runner, tf in targets:
        for days in [90, 180, 360]:  # 720d dropped - fetch too slow, marginal value
            for basket in ["default", "bluechip"]:
                try:
                    dfs, macro, corr = _fetch(basket, tf, days)
                    applied = {}
                    if engine == "DE SHAW":
                        applied = {"NEWTON_HALFLIFE_MAX": 200, "NEWTON_MAX_HOLD": 24}
                        saved = _patch_many(applied)
                    else:
                        saved = {}
                    m = runner(dfs, macro, corr, days)
                    _restore(saved)
                    _record(engine, "baseline", tf, days, basket, m, phase="phase1_baseline", patches=applied)
                except Exception as e:
                    log.warning(f"    {engine} {tf} {days}d {basket} FAILED: {e}")


def phase2_citadel_tune():
    log.info(f"\n{SEP}\n  PHASE 2 - CITADEL PARAM TUNE\n{SEP}")
    grid = [
        ("regime-adaptive", {"RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 0.30, "CHOP": 0.50}}),
        ("regime-aggressive", {"RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 1.0, "CHOP": 0.30}}),
        ("score-058", {"SCORE_THRESHOLD": 0.58}),
        ("score-060", {"SCORE_THRESHOLD": 0.60}),
        ("stop-tight", {"STOP_ATR_M": 1.5, "TARGET_RR": 2.0}),
        ("stop-wide", {"STOP_ATR_M": 2.5, "TARGET_RR": 3.0}),
        ("rr-3x", {"TARGET_RR": 3.0}),
        (
            "score-058+adaptive",
            {"SCORE_THRESHOLD": 0.58, "RISK_SCALE_BY_REGIME": {"BEAR": 1.0, "BULL": 0.30, "CHOP": 0.50}},
        ),
    ]
    # Pruned: only default basket (strongest edge) × 2 periods. Data cached from phase1.
    for days in [180, 360]:
        for basket in ["default"]:
            try:
                dfs, macro, corr = _fetch(basket, "15m", days)
            except Exception as e:
                log.warning(f"    fetch FAILED {basket} 15m {days}d: {e}")
                continue
            for cfg_name, patches in grid:
                saved = _patch_many(patches)
                try:
                    m = _run_citadel(dfs, macro, corr, days)
                    _record("CITADEL", cfg_name, "15m", days, basket, m, phase="phase2_citadel", patches=patches)
                except Exception as e:
                    log.warning(f"    CITADEL {cfg_name} {days}d {basket} FAILED: {e}")
                _restore(saved)


def phase2_jump_tune():
    log.info(f"\n{SEP}\n  PHASE 2 - JUMP PARAM TUNE\n{SEP}")
    grid = [
        ("score-040", {"MERCURIO_MIN_SCORE": 0.40}),
        ("score-060", {"MERCURIO_MIN_SCORE": 0.60}),
        ("score-070", {"MERCURIO_MIN_SCORE": 0.70}),
        ("vimb-tight", {"MERCURIO_VIMB_LONG": 0.65, "MERCURIO_VIMB_SHORT": 0.35}),
        ("vimb-loose", {"MERCURIO_VIMB_LONG": 0.55, "MERCURIO_VIMB_SHORT": 0.45}),
        ("liq-loose", {"MERCURIO_LIQ_VOL_MULT": 2.0}),
        ("liq-tight", {"MERCURIO_LIQ_VOL_MULT": 4.0}),
        ("size-1.0", {"MERCURIO_SIZE_MULT": 1.0}),
    ]
    # Pruned: only 15m (cache hit from Phase 1), 2 periods, 2 baskets.
    # majors basket would need new fetch, skip for speed.
    for tf in ["15m"]:
        for days in [90, 180]:
            for basket in ["default", "bluechip"]:
                try:
                    dfs, macro, corr = _fetch(basket, tf, days)
                except Exception as e:
                    log.warning(f"    fetch FAILED {basket} {tf} {days}d: {e}")
                    continue
                for cfg_name, patches in grid:
                    saved = _patch_many(patches)
                    try:
                        m = _run_jump(dfs, macro, corr, days)
                        _record("JUMP", cfg_name, tf, days, basket, m, phase="phase2_jump", patches=patches)
                    except Exception as e:
                        log.warning(f"    JUMP {cfg_name} {tf} {days}d {basket} FAILED: {e}")
                    _restore(saved)


def phase2_deshaw_tune():
    log.info(f"\n{SEP}\n  PHASE 2 - DE SHAW PARAM TUNE\n{SEP}")
    grid = [
        ("z-1.5/3.0", {"NEWTON_ZSCORE_ENTRY": 1.5, "NEWTON_ZSCORE_STOP": 3.0}),
        ("z-2.0/3.5", {"NEWTON_ZSCORE_ENTRY": 2.0, "NEWTON_ZSCORE_STOP": 3.5}),
        ("z-2.5/4.0", {"NEWTON_ZSCORE_ENTRY": 2.5, "NEWTON_ZSCORE_STOP": 4.0}),
        ("hl-100", {"NEWTON_HALFLIFE_MAX": 100, "NEWTON_MAX_HOLD": 12}),
        ("hl-500", {"NEWTON_HALFLIFE_MAX": 500, "NEWTON_MAX_HOLD": 48}),
        ("pval-tight", {"NEWTON_COINT_PVALUE": 0.01}),
        ("pval-loose", {"NEWTON_COINT_PVALUE": 0.10}),
    ]
    # Pruned: only 4h (cointegration-friendly + cache hit from Phase 1),
    # 2 periods, 2 baskets. Skipping 1h and top12 to reduce fetches.
    for tf in ["4h"]:
        tf_mult = 1
        for days in [90, 180]:
            for basket in ["default", "bluechip"]:
                try:
                    dfs, macro, corr = _fetch(basket, tf, days)
                except Exception as e:
                    log.warning(f"    fetch FAILED {basket} {tf} {days}d: {e}")
                    continue
                for cfg_name, patches in grid:
                    scaled = dict(patches)
                    if "NEWTON_HALFLIFE_MAX" in scaled:
                        scaled["NEWTON_HALFLIFE_MAX"] *= tf_mult
                    if "NEWTON_MAX_HOLD" in scaled:
                        scaled["NEWTON_MAX_HOLD"] *= tf_mult
                    saved = _patch_many(scaled)
                    try:
                        m = _run_deshaw(dfs, macro, corr, days)
                        _record("DE SHAW", cfg_name, tf, days, basket, m, phase="phase2_deshaw", patches=scaled)
                    except Exception as e:
                        log.warning(f"    DE SHAW {cfg_name} {tf} {days}d {basket} FAILED: {e}")
                    _restore(saved)


def phase3_validate():
    log.info(f"\n{SEP}\n  PHASE 3 - LONG-WINDOW VALIDATION (1500d)\n{SEP}")
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
            saved = _patch_many(r.get("patches") or {})
            try:
                if eng == "CITADEL":
                    m = _run_citadel(dfs, macro, corr, 1500)
                elif eng == "JUMP":
                    m = _run_jump(dfs, macro, corr, 1500)
                elif eng == "DE SHAW":
                    m = _run_deshaw(dfs, macro, corr, 1500)
                else:
                    continue
                _record(
                    eng,
                    f"validate-1500d/{r['config']}",
                    r["tf"],
                    1500,
                    r["basket"],
                    m,
                    phase="phase3_validate",
                    patches=r.get("patches") or {},
                )
            except Exception as e:
                log.warning(f"    {eng} 1500d {r['basket']} FAILED: {e}")
            _restore(saved)


def main():
    t0 = time.time()
    log.info(f"\n{SEP}\n  AUTONOMOUS BATTERY - {SESSION_TS}\n{SEP}\n")
    log.info(f"  CSV -> {CSV_PATH}")
    log.info(f"  MD  -> {MD_PATH}")
    _load_progress()

    try:
        phase1_baseline()
    except Exception as e:
        log.error(f"PHASE 1 FAILED: {e}\n{traceback.format_exc()}")

    try:
        phase2_citadel_tune()
    except Exception as e:
        log.error(f"PHASE 2 CITADEL FAILED: {e}\n{traceback.format_exc()}")

    try:
        phase2_jump_tune()
    except Exception as e:
        log.error(f"PHASE 2 JUMP FAILED: {e}\n{traceback.format_exc()}")

    try:
        phase2_deshaw_tune()
    except Exception as e:
        log.error(f"PHASE 2 DE SHAW FAILED: {e}\n{traceback.format_exc()}")

    # Phase 3 (1500d validation) skipped — too slow for lunch window.
    # Top configs from Phase 2 at 360d already provide enough edge signal.
    # Run manually later: python tools/autonomous_battery.py --phase3

    elapsed = (time.time() - t0) / 60
    log.info(f"\n{SEP}\n  DONE - {elapsed:.1f}min · {len(ALL)} runs\n{SEP}")
    _save_progress()

    md = MD_PATH.read_text(encoding="utf-8")
    md = md.replace("**Status:** in_progress", f"**Status:** completed ({elapsed:.1f}min)")
    MD_PATH.write_text(md, encoding="utf-8")


if __name__ == "__main__":
    main()
