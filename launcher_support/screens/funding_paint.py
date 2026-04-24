"""Funding-scanner table painter — score + filter + render opportunities.

Extracted from launcher.App._funding_paint. render(app, rows, arb, stats)
repaints the opportunities table inside the arb hub funding tab, applies
the active _arb_filters (APR / risk / grade / volume / OI), scores rows
via core.arb.arb_scoring, and refreshes the arb-pairs strip + meta line.
"""
from __future__ import annotations

from datetime import datetime
import tkinter as tk

from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG, BG2,
    DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)


def render(app, rows, arb, stats):
    """Repaint the funding-scanner opportunities table.

    Cached on app._funding_cached so a filter change can re-paint from
    the same data without triggering a network scan. Reads app._arb_filters
    (risk_max / grade_min / min_apr / min_volume / min_oi) and
    app._funding_cols for per-column widths + anchors. Targets
    app._funding_table_inner as parent; repaints app._funding_arb_frame
    and app._funding_meta in-place.
    """
    if not getattr(app, "_funding_alive", False):
        return
    inner = getattr(app, "_funding_table_inner", None)
    if inner is None:
        return

    # cache for filter repaint
    app._funding_cached = (rows, arb, stats)

    # -- Scoring & filtering ----------------------------------
    try:
        from core.arb.arb_scoring import score_opp, score_batch
        _scoring_ok = True
    except Exception:
        _scoring_ok = False

    filters = getattr(app, "_arb_filters", None)

    # Build score list for all rows (parallel)
    row_scores = None
    if _scoring_ok:
        try:
            opp_dicts = [o.to_dict() for o in rows]
            row_scores = score_batch(opp_dicts)
        except Exception:
            row_scores = None

    # Apply filters
    if filters and rows:
        _RISK_ORDER = {"LOW": 0, "MED": 1, "HIGH": 2}
        _GRADE_ORDER = {"GO": 0, "MAYBE": 1, "SKIP": 2}
        risk_max_ord = _RISK_ORDER.get(filters.get("risk_max", "HIGH"), 2)
        grade_min_ord = _GRADE_ORDER.get(filters.get("grade_min", "SKIP"), 2)
        min_apr = filters.get("min_apr", 0)
        min_volume = filters.get("min_volume", 0)
        min_oi = filters.get("min_oi", 0)

        filtered_rows = []
        filtered_scores = []
        for idx, o in enumerate(rows):
            if abs(o.apr) < min_apr:
                continue
            if min_volume and o.volume_24h < min_volume:
                continue
            if min_oi and o.open_interest < min_oi:
                continue
            if _RISK_ORDER.get(o.risk, 2) < risk_max_ord:
                # row risk is stricter than allowed max — include it
                pass
            elif _RISK_ORDER.get(o.risk, 2) > risk_max_ord:
                continue
            sr = row_scores[idx] if row_scores else None
            if sr is not None:
                if _GRADE_ORDER.get(sr.grade, 2) > grade_min_ord:
                    continue
            filtered_rows.append(o)
            filtered_scores.append(sr)
        rows = filtered_rows
        row_scores = filtered_scores

    # rebuild rows
    for w in inner.winfo_children():
        w.destroy()

    for i, o in enumerate(rows, 1):
        bg = BG if i % 2 == 1 else BG2
        rf = tk.Frame(inner, bg=bg)
        rf.pack(fill="x")

        # APR color classes
        apr_abs = abs(o.apr)
        if apr_abs >= 100:
            apr_fg = GREEN
        elif apr_abs >= 50:
            apr_fg = AMBER
        else:
            apr_fg = DIM
        risk_fg = RED if o.risk == "HIGH" else (AMBER_D if o.risk == "MED" else DIM)
        sym_fg = WHITE
        venue_fg = AMBER_D

        # SCORE cell
        sr = row_scores[i - 1] if row_scores else None
        if sr is not None:
            sc = int(sr.score)
            if sr.grade == "GO":
                score_txt = f"██ {sc:>2} GO"
                score_fg = GREEN
            elif sr.grade == "MAYBE":
                score_txt = f"█░ {sc:>2} MAYBE"
                score_fg = AMBER
            else:
                score_txt = f"░░ {sc:>2} SKIP"
                score_fg = DIM2
        else:
            score_txt = ""
            score_fg = DIM2

        cells = [
            (f"{i:>3}", DIM),
            (o.symbol, sym_fg),
            (o.venue, venue_fg),
            (o.venue_type, DIM2),
            (f"{o.rate*100:+.3f}%/{o.interval_h:.0f}h", DIM),
            (f"{o.apr:+.0f}%", apr_fg),
            (f"${o.volume_24h/1e6:.1f}M", DIM),
            (o.risk, risk_fg),
            (score_txt, score_fg),
        ]
        for (txt, fg), (_lbl, w, anchor) in zip(cells, app._funding_cols):
            tk.Label(rf, text=txt, font=(FONT, 8),
                     fg=fg, bg=bg, width=w, anchor=anchor).pack(side="left")

    if not rows:
        tk.Label(inner, text="  — no opportunities above threshold —  ",
                 font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)

    # arb pairs strip
    arb_frame = getattr(app, "_funding_arb_frame", None)
    if arb_frame:
        for w in arb_frame.winfo_children():
            w.destroy()
        if arb:
            for a in arb:
                # score arb pair
                arb_score_tag = ""
                if _scoring_ok:
                    try:
                        asr = score_opp(a)
                        if asr.grade == "GO":
                            arb_score_tag = f"  ██{int(asr.score):>2}GO"
                        elif asr.grade == "MAYBE":
                            arb_score_tag = f"  █░{int(asr.score):>2}MAYBE"
                        else:
                            arb_score_tag = f"  ░░{int(asr.score):>2}SKIP"
                    except Exception:
                        arb_score_tag = ""
                line = (
                    f"   {a['symbol']:8s}  "
                    f"SHORT {a['short_venue']:<11s} ({a['short_apr']:+6.1f}%)  "
                    f"→  "
                    f"LONG {a['long_venue']:<11s} ({a['long_apr']:+6.1f}%)  "
                    f"net {a['net_apr']:+6.0f}%"
                    f"{arb_score_tag}"
                )
                net_fg = GREEN if abs(a["net_apr"]) >= 50 else AMBER
                tk.Label(arb_frame, text=line, font=(FONT, 8),
                         fg=net_fg, bg=BG, anchor="w").pack(fill="x")
        else:
            tk.Label(arb_frame,
                     text="   — no cross-venue spreads above 5% APR —",
                     font=(FONT, 8), fg=DIM2, bg=BG, anchor="w").pack(fill="x")

    # meta strip
    try:
        now = datetime.now().strftime("%H:%M:%S")
        total = stats.get("total", 0)
        dex_on = stats.get("dex_online", 0)
        cex_on = stats.get("cex_online", 0)
        errs = stats.get("errors") or {}
        err_tag = f"  ·  {len(errs)} failed" if errs else ""
        app._funding_meta.configure(
            text=f"  last scan {now}  ·  "
                 f"{dex_on} dex  {cex_on} cex  "
                 f"·  {total} perps{err_tag}  ",
            fg=DIM,
        )
        app.h_stat.configure(text="LIVE", fg=GREEN)
    except Exception:
        pass
