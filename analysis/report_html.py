"""
AURUM Finance -- HTML Report Generator
=======================================
Self-contained Bloomberg-terminal-style HTML report for backtest results.
Generates inline SVG charts, no external dependencies.
"""
from __future__ import annotations
import math, os
from datetime import datetime
from pathlib import Path
from config.params import ACCOUNT_SIZE, INTERVAL, MC_N, MC_BLOCK


# ── Colour palette (Bloomberg dark) ─────────────────────────────
# Shared chart palette — see analysis/_chart_palette.py for canonical hex.
from analysis._chart_palette import (
    BG as _BG, PANEL as _PANEL, GOLD as _GOLD, GREEN as _GREEN, RED as _RED,
    BLUE as _BLUE, PURPLE as _PURPLE, TEAL as _TEAL, GRAY as _GRAY,
    WHITE as _WHITE, BORDER as _BORDER,
)


# ── SVG helpers ──────────────────────────────────────────────────

def _scale(values: list[float], w: float, h: float,
           pad_x: float = 60, pad_y: float = 30,
           y_min: float | None = None, y_max: float | None = None):
    """Return list of (cx, cy) pixel coords for *values*."""
    n = len(values)
    if n < 2:
        return [(pad_x, h - pad_y)]
    vmin = y_min if y_min is not None else min(values)
    vmax = y_max if y_max is not None else max(values)
    span = vmax - vmin or 1.0
    usable_w = w - 2 * pad_x
    usable_h = h - 2 * pad_y
    pts = []
    for i, v in enumerate(values):
        cx = pad_x + (i / (n - 1)) * usable_w
        cy = pad_y + (1 - (v - vmin) / span) * usable_h
        pts.append((cx, cy))
    return pts


def _polyline_str(pts: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def _fmt_money(v: float) -> str:
    if abs(v) >= 1e6:
        return f"${v/1e6:,.2f}M"
    return f"${v:,.2f}"


def _fmt_pct(v: float) -> str:
    return f"{v:+.2f}%" if v else "0.00%"


def _fmt_price(v: float) -> str:
    """Format price with decimals appropriate to magnitude (BTC vs SHIB)."""
    v = float(v)
    if v == 0:    return "0"
    a = abs(v)
    if a >= 1000: return f"{v:,.2f}"
    if a >= 100:  return f"{v:.2f}"
    if a >= 10:   return f"{v:.3f}"
    if a >= 1:    return f"{v:.4f}"
    if a >= 0.01: return f"{v:.5f}"
    return f"{v:.6f}"


def _extract_close(prices) -> list:
    """Accept either OHLC dict or close-only list, return close array."""
    if isinstance(prices, dict) and "close" in prices:
        return list(prices["close"])
    return list(prices) if prices else []


def _y_for_value(val: float, values: list[float], h: float,
                 pad_y: float = 30, y_min: float | None = None,
                 y_max: float | None = None) -> float:
    vmin = y_min if y_min is not None else min(values)
    vmax = y_max if y_max is not None else max(values)
    span = vmax - vmin or 1.0
    return pad_y + (1 - (val - vmin) / span) * (h - 2 * pad_y)


def _svg_axis_labels(values: list[float], w: float, h: float,
                     pad_x: float = 60, pad_y: float = 30,
                     n_ticks: int = 5, y_min: float | None = None,
                     y_max: float | None = None) -> str:
    """Y-axis tick labels + faint grid lines."""
    vmin = y_min if y_min is not None else min(values)
    vmax = y_max if y_max is not None else max(values)
    span = vmax - vmin or 1.0
    lines = []
    for i in range(n_ticks + 1):
        frac = i / n_ticks
        val = vmax - frac * span
        cy = pad_y + frac * (h - 2 * pad_y)
        lines.append(
            f'<line x1="{pad_x}" y1="{cy:.1f}" x2="{w - pad_x}" y2="{cy:.1f}" '
            f'stroke="rgba(255,255,255,0.04)" stroke-width="0.5"/>'
        )
        lines.append(
            f'<text x="{pad_x - 8}" y="{cy + 4:.1f}" text-anchor="end" '
            f'font-size="9" fill="{_GRAY}" opacity="0.7" '
            f'font-variant-numeric="tabular-nums">{val:,.0f}</text>'
        )
    return "\n".join(lines)


# ── SVG equity curve ─────────────────────────────────────────────

def _svg_equity(eq: list[float], w: int = 900, h: int = 300) -> str:
    if not eq or len(eq) < 2:
        return '<svg width="900" height="100"><text x="20" y="50" fill="#9ca3af">No equity data</text></svg>'

    pad_x, pad_y = 60, 30
    y_min_val = min(eq) * 0.995
    y_max_val = max(eq) * 1.005
    pts = _scale(eq, w, h, pad_x, pad_y, y_min_val, y_max_val)
    pts_str = _polyline_str(pts)

    # Breakeven line
    be_y = _y_for_value(ACCOUNT_SIZE, eq, h, pad_y, y_min_val, y_max_val)

    # Peak & trough
    peak_val = max(eq)
    trough_val = min(eq)
    peak_idx = eq.index(peak_val)
    trough_idx = eq.index(trough_val)
    peak_pt = pts[peak_idx]
    trough_pt = pts[trough_idx]

    # Drawdown shading: area between equity and running peak
    running_peak = []
    p = eq[0]
    for v in eq:
        p = max(p, v)
        running_peak.append(p)
    # Build a polygon: eq line forward, then peak line backward
    dd_poly_pts = []
    for i in range(len(eq)):
        dd_poly_pts.append(pts[i])
    # Walk backward along running peak
    peak_pts_scaled = _scale(running_peak, w, h, pad_x, pad_y, y_min_val, y_max_val)
    for i in range(len(running_peak) - 1, -1, -1):
        dd_poly_pts.append(peak_pts_scaled[i])
    dd_poly_str = _polyline_str(dd_poly_pts)

    axis = _svg_axis_labels(eq, w, h, pad_x, pad_y, 5, y_min_val, y_max_val)

    # X-axis labels (trade numbers)
    n = len(eq)
    x_labels = []
    step = max(1, n // 6)
    for i in range(0, n, step):
        cx = pad_x + (i / max(n - 1, 1)) * (w - 2 * pad_x)
        x_labels.append(
            f'<text x="{cx:.1f}" y="{h - 5}" text-anchor="middle" '
            f'font-size="10" fill="{_GRAY}">{i}</text>'
        )

    # Area-fill polygon: equity line down to break-even baseline
    area_pts = list(pts) + [(pts[-1][0], be_y), (pts[0][0], be_y)]
    area_str = _polyline_str(area_pts)

    return f'''<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;max-width:{w}px;height:auto;background:transparent;border-radius:12px;">
  <defs>
    <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="{_GOLD}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{_GOLD}" stop-opacity="0.0"/>
    </linearGradient>
    <linearGradient id="eq-line" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="{_GOLD}" stop-opacity="0.6"/>
      <stop offset="100%" stop-color="{_GOLD}" stop-opacity="1.0"/>
    </linearGradient>
  </defs>
  {axis}
  {"".join(x_labels)}
  <polygon points="{dd_poly_str}" fill="{_RED}" opacity="0.08"/>
  <polygon points="{area_str}" fill="url(#eq-fill)"/>
  <line x1="{pad_x}" y1="{be_y:.1f}" x2="{w - pad_x}" y2="{be_y:.1f}"
        stroke="{_GRAY}" stroke-width="1" stroke-dasharray="4,4" opacity="0.35"/>
  <text x="{w - pad_x + 4}" y="{be_y + 4:.1f}" font-size="9" fill="{_GRAY}"
        letter-spacing="0.1em">break-even</text>
  <polyline points="{pts_str}" stroke="url(#eq-line)" fill="none"
            stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{peak_pt[0]:.1f}" cy="{peak_pt[1]:.1f}" r="5" fill="{_GREEN}" opacity="0.35"/>
  <circle cx="{peak_pt[0]:.1f}" cy="{peak_pt[1]:.1f}" r="3" fill="{_GREEN}"/>
  <text x="{peak_pt[0]:.1f}" y="{peak_pt[1] - 10:.1f}" text-anchor="middle"
        font-size="10" font-weight="700" fill="{_GREEN}">{_fmt_money(peak_val)}</text>
  <circle cx="{trough_pt[0]:.1f}" cy="{trough_pt[1]:.1f}" r="5" fill="{_RED}" opacity="0.35"/>
  <circle cx="{trough_pt[0]:.1f}" cy="{trough_pt[1]:.1f}" r="3" fill="{_RED}"/>
  <text x="{trough_pt[0]:.1f}" y="{trough_pt[1] + 18:.1f}" text-anchor="middle"
        font-size="10" font-weight="700" fill="{_RED}">{_fmt_money(trough_val)}</text>
</svg>'''


# ── SVG Monte Carlo paths ────────────────────────────────────────

def _svg_mc_paths(mc: dict, eq: list[float], w: int = 900, h: int = 300) -> str:
    paths = mc.get("paths", [])
    if not paths:
        return ""

    pad_x, pad_y = 60, 30
    # Compute global y range across all paths + real eq
    all_vals = [v for p in paths for v in p] + list(eq)
    y_min_val = min(all_vals) * 0.99
    y_max_val = max(all_vals) * 1.01

    lines = []
    # Simulated paths (low opacity)
    for path in paths:
        pts = _scale(path, w, h, pad_x, pad_y, y_min_val, y_max_val)
        lines.append(
            f'<polyline points="{_polyline_str(pts)}" stroke="{_GOLD}" '
            f'fill="none" stroke-width="0.5" opacity="0.05"/>'
        )

    # Real equity on top
    real_pts = _scale(eq, w, h, pad_x, pad_y, y_min_val, y_max_val)
    lines.append(
        f'<polyline points="{_polyline_str(real_pts)}" stroke="{_WHITE}" '
        f'fill="none" stroke-width="2" opacity="0.9"/>'
    )

    axis = _svg_axis_labels(eq, w, h, pad_x, pad_y, 5, y_min_val, y_max_val)

    # Reference lines: p5, median, p95
    ref_lines = []
    for key, label, color in [("p5", "P5", _RED), ("median", "MED", _TEAL), ("p95", "P95", _GREEN)]:
        val = mc.get(key)
        if val is not None:
            ry = _y_for_value(val, eq, h, pad_y, y_min_val, y_max_val)
            ry = max(pad_y, min(h - pad_y, ry))
            ref_lines.append(
                f'<line x1="{pad_x}" y1="{ry:.1f}" x2="{w - pad_x}" y2="{ry:.1f}" '
                f'stroke="{color}" stroke-width="1" stroke-dasharray="5,5" opacity="0.6"/>'
            )
            ref_lines.append(
                f'<text x="{w - pad_x + 4}" y="{ry + 4:.1f}" font-size="9" '
                f'fill="{color}">{label} {_fmt_money(val)}</text>'
            )

    return f'''<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;max-width:{w}px;height:auto;background:transparent;border-radius:12px;">
  {axis}
  {"".join(lines)}
  {"".join(ref_lines)}
</svg>'''


# ── SVG Monte Carlo histogram ────────────────────────────────────

def _svg_mc_histogram(mc: dict, w: int = 900, h: int = 250, n_bins: int = 40) -> str:
    finals = mc.get("finals", [])
    if not finals:
        return ""

    pad_x, pad_y = 60, 30
    fmin, fmax = min(finals), max(finals)
    span = fmax - fmin or 1.0
    bin_w = span / n_bins

    # Build bins
    bins = [0] * n_bins
    for v in finals:
        idx = min(int((v - fmin) / bin_w), n_bins - 1)
        bins[idx] += 1
    max_count = max(bins) or 1

    usable_w = w - 2 * pad_x
    usable_h = h - 2 * pad_y
    bar_w = usable_w / n_bins

    bars = []
    for i, count in enumerate(bins):
        bx = pad_x + i * bar_w
        bar_h = (count / max_count) * usable_h
        by = pad_y + usable_h - bar_h
        bin_mid = fmin + (i + 0.5) * bin_w
        color = _GREEN if bin_mid >= ACCOUNT_SIZE else _RED
        bars.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w - 1:.1f}" '
            f'height="{bar_h:.1f}" fill="{color}" opacity="0.7"/>'
        )

    # Reference lines
    ref_lines = []
    for key, label, color, dash in [
        ("p5", "P5", _RED, "5,5"),
        ("median", "MED", _TEAL, "5,5"),
        ("p95", "P95", _GREEN, "5,5"),
    ]:
        val = mc.get(key)
        if val is not None and fmin <= val <= fmax:
            lx = pad_x + ((val - fmin) / span) * usable_w
            ref_lines.append(
                f'<line x1="{lx:.1f}" y1="{pad_y}" x2="{lx:.1f}" y2="{h - pad_y}" '
                f'stroke="{color}" stroke-width="1" stroke-dasharray="{dash}" opacity="0.8"/>'
            )
            ref_lines.append(
                f'<text x="{lx:.1f}" y="{pad_y - 4}" text-anchor="middle" '
                f'font-size="9" fill="{color}">{label} {_fmt_money(val)}</text>'
            )

    # Breakeven line
    if fmin <= ACCOUNT_SIZE <= fmax:
        be_x = pad_x + ((ACCOUNT_SIZE - fmin) / span) * usable_w
        ref_lines.append(
            f'<line x1="{be_x:.1f}" y1="{pad_y}" x2="{be_x:.1f}" y2="{h - pad_y}" '
            f'stroke="{_RED}" stroke-width="2" opacity="0.9"/>'
        )
        ref_lines.append(
            f'<text x="{be_x:.1f}" y="{h - pad_y + 14}" text-anchor="middle" '
            f'font-size="9" fill="{_RED}">BE {_fmt_money(ACCOUNT_SIZE)}</text>'
        )

    # X-axis labels
    x_labels = []
    for i in range(0, n_bins + 1, max(1, n_bins // 6)):
        val = fmin + i * bin_w
        lx = pad_x + (i / n_bins) * usable_w
        x_labels.append(
            f'<text x="{lx:.1f}" y="{h - 5}" text-anchor="middle" '
            f'font-size="9" fill="{_GRAY}">{val:,.0f}</text>'
        )

    return f'''<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;max-width:{w}px;height:auto;background:transparent;border-radius:12px;">
  {"".join(bars)}
  {"".join(ref_lines)}
  {"".join(x_labels)}
</svg>'''


# ── HTML section builders ────────────────────────────────────────

def _metric_card(label: str, value: str, color: str = _WHITE) -> str:
    return f'''<div class="metric-card">
      <div class="metric-label">{label}</div>
      <div class="metric-value" style="color:{color};">{value}</div>
    </div>'''


def _section(title: str, content: str, id_: str = "", kicker: str = "AURUM") -> str:
    id_attr = f' id="{id_}"' if id_ else ""
    return f'''<section{id_attr} class="report-section">
  <div class="section-head">
    <div class="section-kicker">{kicker}</div>
    <h2>{title}</h2>
  </div>
  <div class="section-body">{content}</div>
</section>'''


def _details_block(title: str, content: str, subtitle: str = "",
                   open_: bool = False, tone: str = "neutral",
                   kicker: str = "AURUM") -> str:
    open_attr = " open" if open_ else ""
    subtitle_html = f'<span class="details-subtitle">{subtitle}</span>' if subtitle else ""
    return f'''<details class="details-block tone-{tone}"{open_attr}>
  <summary>
    <div class="details-head">
      <span class="details-kicker">{kicker}</span>
      <span class="details-title">{title}</span>
      {subtitle_html}
    </div>
    <span class="details-toggle">expand</span>
  </summary>
  <div class="details-body">{content}</div>
</details>'''


def _build_executive_strip(all_trades: list[dict], by_sym: dict,
                           audit_results: dict | None,
                           wf_regime: dict | None,
                           all_vetos: dict | None) -> str:
    import re as _re

    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    top_symbol = "N/A"
    top_symbol_pnl = 0.0
    if by_sym:
        ranked = []
        for sym, trades in by_sym.items():
            pnl = sum(t.get("pnl", 0) for t in trades if t.get("result") in ("WIN", "LOSS"))
            ranked.append((sym, pnl))
        if ranked:
            top_symbol, top_symbol_pnl = max(ranked, key=lambda item: item[1])

    audit_card = ("Audit", "Not available", _GRAY)
    if audit_results and isinstance(audit_results, dict):
        tests = audit_results.get("tests", {})
        statuses = [str((v or {}).get("status", "")).upper() for v in tests.values()]
        n_fail = sum(1 for s in statuses if s == "FAIL")
        n_warn = sum(1 for s in statuses if s == "WARN")
        n_pass = sum(1 for s in statuses if s == "PASS")
        audit_color = _GREEN if n_fail == 0 else (_GOLD if n_fail == 1 else _RED)
        audit_card = ("Audit", f"{n_pass} pass  {n_warn} warn  {n_fail} fail", audit_color)

    stability_card = ("Regime", "No stability data", _GRAY)
    if wf_regime:
        stable_values = []
        for data in wf_regime.values():
            stable = data.get("stable_pct")
            if stable is not None:
                stable_values.append(float(stable))
        if stable_values:
            avg_stable = sum(stable_values) / len(stable_values)
            stability_color = _GREEN if avg_stable >= 60 else (_GOLD if avg_stable >= 40 else _RED)
            stability_card = ("Regime", f"{avg_stable:.0f}% stable avg", stability_color)

    friction_card = ("Main friction", "No veto pressure", _GREEN)
    if all_vetos:
        main_reason, main_count = max(all_vetos.items(), key=lambda item: item[1])
        main_reason = _re.sub(r"\([^)]*\)", "", str(main_reason)).strip() or str(main_reason)
        friction_card = ("Main friction", f"{main_reason} ({main_count})", _GOLD)

    cards = [
        _metric_card("Best Symbol", f'{top_symbol.replace("USDT", "")}  {_fmt_money(top_symbol_pnl)}',
                     _GREEN if top_symbol_pnl >= 0 else _RED),
        _metric_card(*audit_card),
        _metric_card(*stability_card),
        _metric_card(*friction_card),
    ]
    return f'''<section class="executive-strip">
  <div class="strip-header">
    <span class="section-kicker">Executive Summary</span>
    <h2>Research Snapshot</h2>
  </div>
  <div class="strip-grid">{"".join(cards)}</div>
</section>'''


def _build_header(run_dir: Path, config_dict: dict | None,
                  engine_name: str = "AURUM") -> str:
    """Header inteligente: usa engine institucional + timestamp explícito do run.

    engine_name vem do summary["engine"] (BRIDGEWATER, CITADEL, JUMP, etc).
    run_dir.name dá o RUN_ID (ex: 2026-04-14_1018 ou citadel_2026-04-14_1018).
    Timestamp do run é parseado do RUN_ID quando possível, com fallback pra
    file mtime; "Generated" footer mostra hora atual.
    """
    import re as _re
    run_id = run_dir.name if run_dir else "unknown"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Parse timestamp do RUN_ID (formato YYYY-MM-DD_HHMM ou _HHMMSS)
    m = _re.search(r"(\d{4}-\d{2}-\d{2})[_T](\d{2})(\d{2})(\d{2})?", run_id)
    if m:
        date_part, h, mn, s = m.group(1), m.group(2), m.group(3), m.group(4) or "00"
        run_ts = f"{date_part} {h}:{mn}:{s}"
    elif run_dir and run_dir.exists():
        # Fallback: file modification time
        ts = datetime.fromtimestamp(run_dir.stat().st_mtime)
        run_ts = ts.strftime("%Y-%m-%d %H:%M:%S")
    else:
        run_ts = now

    # Filtro: só mostrar params relevantes (skip noise like ARB_*, ABLATION)
    cfg_summary = ""
    if config_dict:
        priority_keys = [
            "ENGINE", "RUN_ID", "INTERVAL", "ENTRY_TF", "SCAN_DAYS",
            "BASKET_EFFECTIVE", "SCAN_DAYS_EFFECTIVE", "N_CANDLES",
            "ACCOUNT_SIZE", "LEVERAGE", "BASE_RISK", "MAX_RISK",
            "STOP_ATR_M", "TARGET_RR", "MAX_HOLD",
        ]
        items = []
        for k in priority_keys:
            if k in config_dict:
                v = config_dict[k]
                # Format numeric values nicely
                if isinstance(v, float):
                    v_str = f"{v:.4g}"
                elif isinstance(v, (int, str)):
                    v_str = str(v)[:30]
                else:
                    continue
                items.append(f'<span style="color:{_GRAY};">{k}:</span> '
                             f'<span style="color:{_WHITE};">{v_str}</span>')
                if len(items) >= 6:
                    break
        cfg_summary = " &nbsp;&middot;&nbsp; ".join(items)
    if not cfg_summary:
        cfg_summary = (f'<span style="color:{_GRAY};">interval:</span> '
                       f'<span style="color:{_WHITE};">{INTERVAL}</span> &nbsp;&middot;&nbsp; '
                       f'<span style="color:{_GRAY};">account:</span> '
                       f'<span style="color:{_WHITE};">{_fmt_money(ACCOUNT_SIZE)}</span>')

    return f'''<header class="hero">
  <div class="hero-top">
    <div>
      <div class="eyebrow">AURUM FINANCE</div>
      <h1>{engine_name}</h1>
      <div class="hero-subtitle">Institutional Backtest Report</div>
    </div>
    <div class="hero-badge">Institutional Research</div>
  </div>
  <div class="hero-meta">
    <div class="hero-meta-item">
      <span>Run</span>
      <strong>{run_id}</strong>
    </div>
    <div class="hero-meta-item">
      <span>Executed</span>
      <strong>{run_ts}</strong>
    </div>
  </div>
  <div class="hero-config">{cfg_summary}</div>
</header>'''


def _build_result_box(all_trades: list[dict], eq: list[float],
                      ratios: dict, mdd_pct: float) -> str:
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    n_trades = len(closed)
    wins = sum(1 for t in closed if t["result"] == "WIN")
    wr = (wins / n_trades * 100) if n_trades else 0.0
    final = eq[-1] if eq else ACCOUNT_SIZE
    pnl = final - ACCOUNT_SIZE
    roi = ratios.get("ret", 0.0) or 0.0
    sharpe = ratios.get("sharpe")
    sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
    sortino = ratios.get("sortino")
    sortino_str = f"{sortino:.2f}" if sortino is not None else "N/A"
    calmar = ratios.get("calmar")
    calmar_str = f"{calmar:.2f}" if calmar is not None else "N/A"

    # Avg R-multiple (portfolio-level) computed from closed trades when available
    rms = [t.get("r_multiple") for t in closed if t.get("r_multiple") is not None]
    avg_r = (sum(rms) / len(rms)) if rms else None
    avg_r_str = f"{avg_r:.2f}" if avg_r is not None else "N/A"

    max_streak = ratios.get("max_consec_losses")
    streak_str = str(max_streak) if max_streak is not None else "N/A"

    # Edge verdict
    has_edge = wr > 50 and roi > 0 and (sharpe or 0) > 0.5
    verdict = "EDGE CONFIRMED" if has_edge else "SEM EDGE"
    v_color = _GREEN if has_edge else _RED

    pnl_color = _GREEN if pnl >= 0 else _RED
    sortino_color = _GREEN if (sortino or 0) > 1 else _WHITE
    calmar_color = _GREEN if (calmar or 0) > 3 else _WHITE
    avg_r_color = _GREEN if (avg_r or 0) > 0 else _RED
    streak_color = _RED if (max_streak or 0) >= 6 else _WHITE

    return f'''<section class="summary-shell">
  <div class="summary-card">
    <div class="summary-balance">
      <div class="summary-balance-label">Net Result</div>
      <div class="summary-balance-main">
        <span class="muted">{_fmt_money(ACCOUNT_SIZE)}</span>
        <span class="arrow">&rarr;</span>
        <span style="color:{pnl_color};">{_fmt_money(final)}</span>
      </div>
      <div class="summary-balance-roi" style="color:{pnl_color};">{_fmt_pct(roi)}</div>
    </div>
    <div class="summary-grid">
      {_metric_card("Trades", str(n_trades), _WHITE)}
      {_metric_card("Win Rate", f"{wr:.1f}%", _GREEN if wr > 50 else _RED)}
      {_metric_card("Sharpe", sharpe_str, _WHITE)}
      {_metric_card("Sortino", sortino_str, sortino_color)}
      {_metric_card("Calmar", calmar_str, calmar_color)}
      {_metric_card("Max DD", f"-{mdd_pct:.1f}%", _RED)}
      {_metric_card("Avg R", avg_r_str, avg_r_color)}
      {_metric_card("Max Streak", streak_str, streak_color)}
      {_metric_card("PnL", _fmt_money(pnl), pnl_color)}
    </div>
    <div class="verdict-row">
      <div class="summary-verdict" style="color:{v_color};">{verdict}</div>
    </div>
  </div>
</section>'''


def _build_mc_stats(mc: dict) -> str:
    cards = []
    specs = [
        ("Positive %", f'{mc.get("pct_pos", 0):.1f}%',
         _GREEN if mc.get("pct_pos", 0) > 50 else _RED),
        ("Median", _fmt_money(mc.get("median", 0)), _WHITE),
        ("P5", _fmt_money(mc.get("p5", 0)), _RED),
        ("P95", _fmt_money(mc.get("p95", 0)), _GREEN),
        ("Avg DD", f'{mc.get("avg_dd", 0):.1f}%', _GOLD),
        ("Worst DD", f'{mc.get("worst_dd", 0):.1f}%', _RED),
        ("Ruin %", f'{mc.get("ror", 0):.1f}%',
         _GREEN if mc.get("ror", 0) < 5 else _RED),
    ]
    for label, val, col in specs:
        cards.append(_metric_card(label, val, col))
    return f'''<div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center;
                margin-top:16px;">{"".join(cards)}</div>'''


def _build_symbol_table(by_sym: dict, all_trades: list[dict]) -> str:
    rows = []
    sym_data = []
    for sym, trades in by_sym.items():
        closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
        if not closed:
            continue
        n = len(closed)
        wins = sum(1 for t in closed if t["result"] == "WIN")
        losses = n - wins
        wr = wins / n * 100 if n else 0
        longs = sum(1 for t in closed if t.get("direction") == "BULLISH")
        shorts = n - longs
        avg_score = sum(t.get("score", 0) for t in closed) / n if n else 0
        pnl = sum(t.get("pnl", 0) for t in closed)
        sym_data.append((sym, n, wins, losses, wr, longs, shorts, avg_score, pnl))

    sym_data.sort(key=lambda x: x[8], reverse=True)

    for sym, n, wins, losses, wr, longs, shorts, avg_score, pnl in sym_data:
        pnl_color = _GREEN if pnl >= 0 else _RED
        bg_tint = "rgba(38,212,124,0.05)" if pnl >= 0 else "rgba(232,93,93,0.05)"
        status = "OK" if pnl > 0 and wr > 45 else "WEAK"
        status_color = _GREEN if status == "OK" else _RED
        rows.append(f'''<tr style="background:{bg_tint};">
          <td style="padding:6px 12px;color:{_WHITE};font-weight:600;">{sym.replace("USDT","")}</td>
          <td style="padding:6px 8px;text-align:center;">{n}</td>
          <td style="padding:6px 8px;text-align:center;color:{_GREEN};">{wins}<span style="color:{_GRAY};">/</span><span style="color:{_RED};">{losses}</span></td>
          <td style="padding:6px 8px;text-align:center;color:{_GREEN if wr > 50 else _RED};">{wr:.1f}%</td>
          <td style="padding:6px 8px;text-align:center;">{longs}L / {shorts}S</td>
          <td style="padding:6px 8px;text-align:center;">{avg_score:.2f}</td>
          <td style="padding:6px 8px;text-align:right;color:{pnl_color};font-weight:600;">{_fmt_money(pnl)}</td>
          <td style="padding:6px 8px;text-align:center;color:{status_color};">{status}</td>
        </tr>''')

    header = '''<tr style="border-bottom:2px solid #1e1e2e;">
      <th style="padding:8px 12px;text-align:left;">Symbol</th>
      <th style="padding:8px;text-align:center;">N</th>
      <th style="padding:8px;text-align:center;">W/L</th>
      <th style="padding:8px;text-align:center;">WR%</th>
      <th style="padding:8px;text-align:center;">L/S</th>
      <th style="padding:8px;text-align:center;">Avg Score</th>
      <th style="padding:8px;text-align:right;">PnL</th>
      <th style="padding:8px;text-align:center;">Status</th>
    </tr>'''

    return f'''<table style="width:100%;border-collapse:collapse;font-size:13px;color:{_GRAY};">
    <thead>{header}</thead>
    <tbody>{"".join(rows)}</tbody>
    </table>'''


def _build_omega_table(cond: dict) -> str:
    if not cond:
        return '<p style="color:#9ca3af;">No conditional data available.</p>'
    rows = []
    for rng, data in sorted(cond.items()):
        if data is None:
            continue
        n = data.get("n", 0)
        wr = data.get("wr", 0)
        rr = data.get("avg_rr", 0)
        exp = data.get("exp", 0)
        total = data.get("total", 0)
        status = "EDGE" if exp > 0 and wr > 48 else "FLAT" if abs(exp) < 0.02 else "NEG"
        s_color = _GREEN if status == "EDGE" else (_GOLD if status == "FLAT" else _RED)
        pnl_color = _GREEN if total >= 0 else _RED
        rows.append(f'''<tr>
          <td style="padding:5px 10px;color:{_GOLD};">{rng}</td>
          <td style="padding:5px 8px;text-align:center;">{n}</td>
          <td style="padding:5px 8px;text-align:center;color:{_GREEN if wr > 50 else _RED};">{wr:.1f}%</td>
          <td style="padding:5px 8px;text-align:center;">{rr:.2f}</td>
          <td style="padding:5px 8px;text-align:center;color:{_GREEN if exp > 0 else _RED};">{exp:.3f}</td>
          <td style="padding:5px 8px;text-align:right;color:{pnl_color};">{_fmt_money(total)}</td>
          <td style="padding:5px 8px;text-align:center;color:{s_color};font-weight:600;">{status}</td>
        </tr>''')

    return f'''<table style="width:100%;border-collapse:collapse;font-size:13px;color:{_GRAY};">
    <thead><tr style="border-bottom:2px solid {_BORDER};">
      <th style="padding:6px 10px;text-align:left;">Score Range</th>
      <th style="padding:6px 8px;text-align:center;">N</th>
      <th style="padding:6px 8px;text-align:center;">WR%</th>
      <th style="padding:6px 8px;text-align:center;">Avg RR</th>
      <th style="padding:6px 8px;text-align:center;">Expectancy</th>
      <th style="padding:6px 8px;text-align:right;">Total PnL</th>
      <th style="padding:6px 8px;text-align:center;">Status</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
    </table>'''


def _build_wf_table(wf: list) -> str:
    if not wf:
        return '<p style="color:#9ca3af;">No walk-forward data.</p>'
    rows = []
    for i, window in enumerate(wf):
        train = window.get("train", {})
        test = window.get("test", {})
        train_wr = train.get("wr", 0)
        test_wr = test.get("wr", 0)
        delta = test_wr - train_wr
        stable = abs(delta) < 10
        s_color = _GREEN if stable else _RED
        status = "STABLE" if stable else "UNSTABLE"
        rows.append(f'''<tr>
          <td style="padding:5px 10px;color:{_WHITE};">W{i + 1}</td>
          <td style="padding:5px 8px;text-align:center;">{train_wr:.1f}%</td>
          <td style="padding:5px 8px;text-align:center;">{test_wr:.1f}%</td>
          <td style="padding:5px 8px;text-align:center;color:{_GREEN if delta >= 0 else _RED};">{delta:+.1f}%</td>
          <td style="padding:5px 8px;text-align:center;color:{s_color};font-weight:600;">{status}</td>
        </tr>''')

    return f'''<table style="width:100%;border-collapse:collapse;font-size:13px;color:{_GRAY};">
    <thead><tr style="border-bottom:2px solid {_BORDER};">
      <th style="padding:6px 10px;text-align:left;">Window</th>
      <th style="padding:6px 8px;text-align:center;">Train WR</th>
      <th style="padding:6px 8px;text-align:center;">Test WR</th>
      <th style="padding:6px 8px;text-align:center;">Delta</th>
      <th style="padding:6px 8px;text-align:center;">Status</th>
    </tr></thead>
    <tbody>{"".join(rows)}</tbody>
    </table>'''


def _build_veto_section(all_vetos: dict) -> str:
    if not all_vetos:
        return '<p style="color:#9ca3af;">No veto filters triggered.</p>'
    # Coalesce parametric vetos like "agg_cap(15344>9940)" into a single bucket
    import re as _re_v
    _coalesced: dict[str, int] = {}
    for k, v in all_vetos.items():
        base = _re_v.sub(r"\([^)]*\)", "", str(k)).strip() or str(k)
        _coalesced[base] = _coalesced.get(base, 0) + v
    total = sum(_coalesced.values()) or 1
    sorted_vetos = sorted(_coalesced.items(), key=lambda x: x[1], reverse=True)
    rows = []
    for reason, count in sorted_vetos:
        pct = count / total * 100
        # Gradient color: gold for dominant, fading to muted purple for rare
        intensity = min(1.0, count / (sorted_vetos[0][1] or 1))
        if intensity > 0.66:
            bar_grad = f"linear-gradient(90deg, {_GOLD}, {_GOLD} 85%, rgba(232,184,75,0.5))"
        elif intensity > 0.33:
            bar_grad = f"linear-gradient(90deg, {_PURPLE}, {_GOLD})"
        else:
            bar_grad = f"linear-gradient(90deg, {_PURPLE}, {_PURPLE})"
        rows.append(f'''<div class="veto-row">
      <div class="veto-label">{reason}</div>
      <div class="veto-track">
        <div class="veto-bar" style="width:{pct:.1f}%;background:{bar_grad};"></div>
      </div>
      <div class="veto-count"><span class="veto-n">{count:,}</span><span class="veto-pct">{pct:.1f}%</span></div>
    </div>''')

    return f'<div class="veto-grid">{"".join(rows)}</div>'


# ── SVG trade charts per symbol ──────────────────────────────────

def _svg_trade_chart(prices, trades: list[dict], symbol: str,
                     w: int = 900, h: int = 250) -> str:
    """Inline SVG price chart with trade entry/exit markers.
    Accepts OHLC dict (uses close) or close-only list — line chart only."""
    prices = _extract_close(prices)
    if not prices or len(prices) < 10:
        return ""

    # Downsample prices to max ~1000 points for SVG performance
    max_pts = 1000
    if len(prices) > max_pts:
        step = len(prices) / max_pts
        sampled = [prices[int(i * step)] for i in range(max_pts)]
        idx_scale = len(prices) / max_pts  # to remap trade indices
    else:
        sampled = prices
        idx_scale = 1.0

    pad_x, pad_y = 50, 25
    y_min_val = min(sampled) * 0.998
    y_max_val = max(sampled) * 1.002
    pts = _scale(sampled, w, h, pad_x, pad_y, y_min_val, y_max_val)
    pts_str = _polyline_str(pts)

    axis = _svg_axis_labels(prices, w, h, pad_x, pad_y, 4, y_min_val, y_max_val)

    # Trade markers
    markers = []
    n_orig = len(prices)
    n_sampled = len(sampled)
    usable_w = w - 2 * pad_x

    for t in trades:
        if t.get("result") not in ("WIN", "LOSS"):
            continue
        idx = t.get("entry_idx", 0)
        dur = t.get("duration", 1)
        if idx >= n_orig or idx < 0:
            continue

        # X positions (mapped to sampled space)
        x_entry = pad_x + (idx / max(n_orig - 1, 1)) * usable_w
        x_exit = pad_x + (min(idx + dur, n_orig - 1) / max(n_orig - 1, 1)) * usable_w

        entry_p = t.get("entry", 0)
        stop_p = t.get("stop", 0)
        target_p = t.get("target", 0)
        exit_p_val = t.get("exit_p", entry_p)

        y_entry = _y_for_value(entry_p, prices, h, pad_y, y_min_val, y_max_val)
        y_stop = _y_for_value(stop_p, prices, h, pad_y, y_min_val, y_max_val)
        y_target = _y_for_value(target_p, prices, h, pad_y, y_min_val, y_max_val)
        y_exit = _y_for_value(exit_p_val, prices, h, pad_y, y_min_val, y_max_val)

        is_win = t["result"] == "WIN"
        is_bull = t.get("direction") == "BULLISH"
        fill_color = "rgba(38,212,124,0.10)" if is_win else "rgba(232,93,93,0.10)"
        border_color = _GREEN if is_win else _RED

        # Shaded area between entry and exit
        rect_y = min(y_entry, y_exit)
        rect_h = abs(y_exit - y_entry)
        if rect_h > 1:
            markers.append(
                f'<rect x="{x_entry:.1f}" y="{rect_y:.1f}" '
                f'width="{max(x_exit - x_entry, 2):.1f}" height="{rect_h:.1f}" '
                f'fill="{fill_color}" stroke="{border_color}" stroke-width="0.5"/>'
            )

        # Stop line (red dashed)
        markers.append(
            f'<line x1="{x_entry:.1f}" y1="{y_stop:.1f}" x2="{x_exit:.1f}" y2="{y_stop:.1f}" '
            f'stroke="{_RED}" stroke-width="0.7" stroke-dasharray="3,3" opacity="0.6"/>'
        )
        # Target line (green dashed)
        markers.append(
            f'<line x1="{x_entry:.1f}" y1="{y_target:.1f}" x2="{x_exit:.1f}" y2="{y_target:.1f}" '
            f'stroke="{_GREEN}" stroke-width="0.7" stroke-dasharray="3,3" opacity="0.6"/>'
        )

        # Entry marker: triangle
        sz = 5
        if is_bull:
            tri = f"{x_entry:.1f},{y_entry + sz:.1f} {x_entry - sz:.1f},{y_entry + sz * 2:.1f} {x_entry + sz:.1f},{y_entry + sz * 2:.1f}"
            markers.append(f'<polygon points="{tri}" fill="{_GREEN}" opacity="0.9"/>')
        else:
            tri = f"{x_entry:.1f},{y_entry - sz:.1f} {x_entry - sz:.1f},{y_entry - sz * 2:.1f} {x_entry + sz:.1f},{y_entry - sz * 2:.1f}"
            markers.append(f'<polygon points="{tri}" fill="{_RED}" opacity="0.9"/>')

    return f'''<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg"
     style="width:100%;max-width:{w}px;height:auto;background:{_PANEL};border-radius:8px;margin-bottom:8px;">
  {axis}
  <polyline points="{pts_str}" stroke="{_GOLD}" fill="none" stroke-width="1.2" stroke-linejoin="round"/>
  {"".join(markers)}
  <text x="{w / 2}" y="16" text-anchor="middle" font-size="11" fill="{_GRAY}">{symbol}</text>
</svg>'''


def _build_trade_charts(by_sym: dict, price_data: dict) -> str:
    """Build all per-symbol trade chart SVGs."""
    if not price_data:
        return ""

    charts = []
    # Sort by number of trades descending
    sorted_syms = sorted(
        by_sym.keys(),
        key=lambda s: len([t for t in by_sym[s] if t.get("result") in ("WIN", "LOSS")]),
        reverse=True
    )

    for sym in sorted_syms[:8]:  # top 8 symbols
        prices = price_data.get(sym)
        trades = by_sym.get(sym, [])
        if not prices or not trades:
            continue
        svg = _svg_trade_chart(prices, trades, sym)
        if svg:
            charts.append(svg)

    if not charts:
        return '<p style="color:#9ca3af;">No price data available for trade charts.</p>'
    return "\n".join(charts)


# ── Trade Inspector — Bloomberg-style interactive ───────────────

# Bloomberg dark palette for the Trade Inspector
_TI_BG    = "#0d1117"
_TI_GRID  = "#1b2028"
_TI_PRICE = "#58a6ff"
_TI_AMBER = "#ff8c00"
_TI_GREEN = "#26d47c"
_TI_RED   = "#e85d5d"
_TI_WHITE = "#ffffff"
_TI_DIM   = "#8b949e"
_TI_TEXT  = "#e5e7eb"


def _render_single_trade_svg(window, trade: dict,
                             local_entry_idx: int, local_exit_idx: int,
                             w: int = 800, h: int = 300) -> str:
    """Focused per-trade SVG. Accepts OHLC dict (candlesticks if window <= 80
    bars) or a close-only list (always line chart). Renders entry/stop/target/
    exit horizontals, entry triangle, exit dot, shaded fill."""
    is_ohlc = isinstance(window, dict) and "close" in window
    if is_ohlc:
        opens, highs, lows, closes = (window["open"], window["high"],
                                       window["low"], window["close"])
    else:
        closes = list(window)
        opens = highs = lows = closes  # degenerate; line-chart path only

    n = len(closes)
    if n < 2:
        return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg">'
                f'<rect width="{w}" height="{h}" fill="{_TI_BG}"/>'
                f'<text x="20" y="50" fill="{_TI_DIM}" font-size="11">no data</text></svg>')

    pad_l, pad_r, pad_t, pad_b = 60, 70, 24, 28
    inner_w = w - pad_l - pad_r
    inner_h = h - pad_t - pad_b

    entry_p  = float(trade.get("entry", 0))
    stop_p   = float(trade.get("stop", entry_p))
    target_p = float(trade.get("target", entry_p))
    exit_p   = float(trade.get("exit_p", entry_p))

    y_lo = min(min(lows),  stop_p, target_p, exit_p, entry_p)
    y_hi = max(max(highs), stop_p, target_p, exit_p, entry_p)
    pad_v = (y_hi - y_lo) * 0.04 or max(abs(entry_p) * 0.005, 1e-6)
    y_lo -= pad_v; y_hi += pad_v
    y_span = (y_hi - y_lo) or 1.0

    def y_of(v: float) -> float:
        return pad_t + (1 - (v - y_lo) / y_span) * inner_h

    def x_of(i: float) -> float:
        return pad_l + (i / max(n - 1, 1)) * inner_w

    parts: list[str] = []
    parts.append(f'<rect x="0" y="0" width="{w}" height="{h}" fill="{_TI_BG}"/>')

    # Grid + Y axis labels
    for i in range(5):
        frac = i / 4
        gy = pad_t + frac * inner_h
        v  = y_hi - frac * y_span
        parts.append(
            f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{w - pad_r}" y2="{gy:.1f}" '
            f'stroke="{_TI_GRID}" stroke-width="0.5" stroke-dasharray="2,3"/>')
        parts.append(
            f'<text x="{pad_l - 6}" y="{gy + 3:.1f}" text-anchor="end" '
            f'font-size="9" fill="{_TI_DIM}">{_fmt_price(v)}</text>')

    # Candlesticks for small windows, line chart otherwise
    use_candles = is_ohlc and n <= 80
    if use_candles:
        bw = max(2.0, min(11.0, inner_w / max(n, 1) - 1.5))
        for i in range(n):
            o, hi, lo, c = opens[i], highs[i], lows[i], closes[i]
            cx = x_of(i)
            yo, yc = y_of(o), y_of(c)
            yh, yl = y_of(hi), y_of(lo)
            up = c >= o
            color = _TI_GREEN if up else _TI_RED
            parts.append(
                f'<line x1="{cx:.1f}" y1="{yh:.1f}" x2="{cx:.1f}" y2="{yl:.1f}" '
                f'stroke="{color}" stroke-width="1"/>')
            body_top = min(yo, yc); body_h = max(abs(yc - yo), 1)
            parts.append(
                f'<rect x="{cx - bw / 2:.1f}" y="{body_top:.1f}" '
                f'width="{bw:.1f}" height="{body_h:.1f}" '
                f'fill="{color}" opacity="0.85"/>')
    else:
        pts = " ".join(f"{x_of(i):.1f},{y_of(closes[i]):.1f}" for i in range(n))
        parts.append(
            f'<polyline points="{pts}" stroke="{_TI_PRICE}" fill="none" '
            f'stroke-width="1.6" stroke-linejoin="round"/>')

    # Trade window shading
    le = max(0, min(n - 1, local_entry_idx))
    lx = max(le, min(n - 1, local_exit_idx))
    x_entry = x_of(le)
    x_exit  = x_of(lx)
    is_win = trade.get("result") == "WIN"
    fill = "rgba(38,212,124,0.10)" if is_win else "rgba(232,93,93,0.10)"
    parts.append(
        f'<rect x="{x_entry:.1f}" y="{pad_t}" '
        f'width="{max(x_exit - x_entry, 2):.1f}" height="{inner_h}" fill="{fill}"/>')

    # Horizontal levels
    def hline(yv: float, color: str, dash: str | None = None, width: str = "1") -> None:
        d = f' stroke-dasharray="{dash}"' if dash else ""
        parts.append(
            f'<line x1="{pad_l}" y1="{yv:.1f}" x2="{w - pad_r}" y2="{yv:.1f}" '
            f'stroke="{color}" stroke-width="{width}"{d} opacity="0.95"/>')

    y_e = y_of(entry_p);  hline(y_e, _TI_AMBER, width="1.3")
    y_s = y_of(stop_p);   hline(y_s, _TI_RED,   dash="4,3")
    y_t = y_of(target_p); hline(y_t, _TI_GREEN, dash="4,3")
    y_x = y_of(exit_p);   hline(y_x, _TI_WHITE, dash="2,2", width="0.9")

    def rlabel(yv: float, text: str, color: str) -> None:
        parts.append(
            f'<text x="{w - pad_r + 4}" y="{yv + 3:.1f}" font-size="9" '
            f'fill="{color}">{text}</text>')

    rlabel(y_e, f"E {_fmt_price(entry_p)}",  _TI_AMBER)
    rlabel(y_s, f"S {_fmt_price(stop_p)}",   _TI_RED)
    rlabel(y_t, f"T {_fmt_price(target_p)}", _TI_GREEN)
    rlabel(y_x, f"X {_fmt_price(exit_p)}",   _TI_WHITE)

    # Entry triangle
    is_long = trade.get("direction") == "BULLISH"
    sz = 6
    if is_long:
        tri = (f"{x_entry:.1f},{y_e + sz + 2:.1f} "
               f"{x_entry - sz:.1f},{y_e + sz * 2 + 5:.1f} "
               f"{x_entry + sz:.1f},{y_e + sz * 2 + 5:.1f}")
        tri_color = _TI_GREEN
    else:
        tri = (f"{x_entry:.1f},{y_e - sz - 2:.1f} "
               f"{x_entry - sz:.1f},{y_e - sz * 2 - 5:.1f} "
               f"{x_entry + sz:.1f},{y_e - sz * 2 - 5:.1f}")
        tri_color = _TI_RED
    parts.append(f'<polygon points="{tri}" fill="{tri_color}"/>')

    # Exit dot
    exit_color = _TI_GREEN if is_win else _TI_RED
    parts.append(
        f'<circle cx="{x_exit:.1f}" cy="{y_x:.1f}" r="4.5" '
        f'fill="{exit_color}" stroke="{_TI_BG}" stroke-width="1.4"/>')

    # X-axis ticks
    def xtick(xv: float, label: str, color: str = _TI_DIM) -> None:
        parts.append(
            f'<text x="{xv:.1f}" y="{h - 8}" text-anchor="middle" '
            f'font-size="9" fill="{color}">{label}</text>')

    xtick(pad_l,        f"-{le}c")
    xtick(x_entry,      "entry", _TI_AMBER)
    xtick(x_exit,       "exit",  exit_color)
    xtick(w - pad_r,    f"+{n - 1 - lx}c")

    # Header strip
    sym  = trade.get("symbol", "?")
    side = "LONG" if is_long else "SHORT"
    result = trade.get("result", "?")
    pnl = float(trade.get("pnl", 0))
    pnl_color = _TI_GREEN if pnl >= 0 else _TI_RED
    parts.append(
        f'<text x="{pad_l}" y="16" font-size="11" fill="{_TI_AMBER}" '
        f'font-weight="bold">{sym}</text>')
    parts.append(
        f'<text x="{pad_l + 88}" y="16" font-size="10" fill="{_TI_DIM}">'
        f'{side} · {result}</text>')
    parts.append(
        f'<text x="{w - pad_r}" y="16" text-anchor="end" font-size="11" '
        f'fill="{pnl_color}" font-weight="bold">'
        f'{"+" if pnl >= 0 else ""}${pnl:,.2f}</text>')

    # Watermark
    parts.append(
        f'<text x="{w - pad_r - 4}" y="{h - 8}" text-anchor="end" '
        f'font-size="8" fill="{_TI_GRID}">AURUM</text>')

    return (f'<svg viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" '
            f'style="width:100%;display:block;">' + "".join(parts) + '</svg>')


def _prerender_trade_charts(all_trades: list[dict], price_data: dict) -> list[dict]:
    """Pre-render every closed trade's per-trade SVG. Each entry: {idx, trade, svg}.
    Window: 30 candles before entry → trade duration → 15 candles after exit."""
    out: list[dict] = []
    if not price_data:
        return out

    for i, t in enumerate(all_trades):
        if t.get("result") not in ("WIN", "LOSS"):
            continue
        sym = t.get("symbol")
        if not sym or sym not in price_data:
            continue

        prices = price_data[sym]
        is_ohlc = isinstance(prices, dict) and "close" in prices
        n_total = len(prices["close"]) if is_ohlc else len(prices)
        if n_total < 5:
            continue

        idx = int(t.get("entry_idx", 0))
        dur = max(1, int(t.get("duration", 1)))
        start = max(0, idx - 30)
        end   = min(n_total, idx + dur + 15)
        if end - start < 5:
            continue

        if is_ohlc:
            window = {k: prices[k][start:end] for k in ("open", "high", "low", "close")}
        else:
            window = list(prices[start:end])

        svg = _render_single_trade_svg(
            window, t,
            local_entry_idx=idx - start,
            local_exit_idx=(idx + dur) - start,
            w=800, h=300,
        )
        out.append({"idx": i, "trade": t, "svg": svg})

    return out


def _build_trade_inspector(prerendered: list[dict]) -> str:
    """Bloomberg-style interactive trade inspector with sidebar list, chart,
    data panel, omega bars, filters, footer nav, keyboard arrows."""
    if not prerendered:
        return '<p style="color:#9ca3af;">No trades to inspect.</p>'

    import json as _json
    n_total = len(prerendered)

    items_html: list[str] = []
    svg_html:   list[str] = []
    js_data:    list[dict] = []

    for slot, p in enumerate(prerendered):
        t = p["trade"]
        sym       = str(t.get("symbol", "?"))
        is_long   = t.get("direction") == "BULLISH"
        is_win    = t.get("result") == "WIN"
        side      = "LONG" if is_long else "SHORT"
        result    = "WIN" if is_win else "LOSS"
        pnl       = float(t.get("pnl", 0))
        pnl_str   = f"{'+' if pnl >= 0 else ''}${pnl:,.2f}"
        pnl_color = _GREEN if pnl >= 0 else _RED
        result_cls = "result-win" if is_win else "result-loss"
        active = " active" if slot == 0 else ""
        display = "block" if slot == 0 else "none"
        short_sym = sym.replace("USDT", "")

        items_html.append(
            f'<div class="trade-item{active}" id="item-{slot}" data-slot="{slot}" '
            f'data-result="{result}" data-symbol="{sym}">'
            f'<div class="ti-head">#{slot + 1} <span class="sym">{short_sym}</span></div>'
            f'<div class="ti-meta"><span class="{result_cls}">{side} {result}</span></div>'
            f'<div class="pnl" style="color:{pnl_color}">{pnl_str}</div>'
            f'</div>'
        )
        svg_html.append(
            f'<div class="trade-svg" id="svg-{slot}" style="display:{display}">'
            f'{p["svg"]}</div>'
        )

        # Compute R-multiple from price-only inputs
        entry_v = float(t.get("entry", 0))
        stop_v  = float(t.get("stop", 0))
        exit_v  = float(t.get("exit_p", 0))
        risk    = abs(entry_v - stop_v)
        if risk > 0:
            move = (exit_v - entry_v) if is_long else (entry_v - exit_v)
            rmult = round(move / risk, 2)
        else:
            rmult = 0.0

        js_data.append({
            "slot":     slot,
            "symbol":   sym,
            "side":     side,
            "result":   result,
            "entry":    entry_v,
            "stop":     stop_v,
            "target":   float(t.get("target", 0)),
            "exit":     exit_v,
            "pnl":      pnl,
            "score":    float(t.get("score", 0)),
            "rr":       float(t.get("rr", 0)),
            "rmult":    rmult,
            "duration": int(t.get("duration", 0)),
            "macro":    str(t.get("macro_bias", "?")),
            "vol":      str(t.get("vol_regime", "?")),
            "dd_scale": float(t.get("dd_scale", 1.0)),
            "os":       float(t.get("omega_struct", 0)),
            "of":       float(t.get("omega_flow", 0)),
            "oc":       float(t.get("omega_cascade", 0)),
            "om":       float(t.get("omega_momentum", 0)),
            "op":       float(t.get("omega_pullback", 0)),
        })

    # Symbol dropdown
    syms = sorted({d["symbol"] for d in js_data})
    sym_opts = '<option value="all">All Symbols</option>' + "".join(
        f'<option value="{s}">{s.replace("USDT","")}</option>' for s in syms
    )

    # Aggregate stats
    wins = sum(1 for d in js_data if d["result"] == "WIN")
    wr_total  = (wins / n_total * 100) if n_total else 0.0
    pnl_total = sum(d["pnl"] for d in js_data)

    json_blob = _json.dumps(js_data, ensure_ascii=False)

    css = '''<style>
.trade-inspector { background:#0a0a0a; border:1px solid #1b2028; border-radius:8px;
  display:flex; font-family:'Consolas','Monaco',monospace; color:#e5e7eb;
  font-size:12px; overflow:hidden; }
.trade-list { width:200px; border-right:1px solid #1b2028; display:flex;
  flex-direction:column; min-height:0; background:#0a0a0a; }
.filter-row { padding:8px; border-bottom:1px solid #1b2028; display:flex;
  flex-wrap:wrap; gap:4px; background:#0d0d0d; }
.filter-btn { padding:3px 9px; background:#1a1a1a; border:1px solid #2a2a2a;
  color:#8b949e; cursor:pointer; border-radius:3px; font-size:10px;
  font-family:inherit; }
.filter-btn.active { background:#ff8c00; color:#0a0a0a; border-color:#ff8c00;
  font-weight:bold; }
.symbol-filter { width:100%; margin-top:4px; padding:3px; background:#1a1a1a;
  color:#e5e7eb; border:1px solid #2a2a2a; border-radius:3px; font-size:10px;
  font-family:inherit; }
.trade-items { overflow-y:auto; max-height:580px; flex:1; }
.trade-item { padding:7px 10px; cursor:pointer; border-left:3px solid transparent;
  border-bottom:1px solid #0d0d0d; transition:background 0.12s; }
.trade-item:hover { background:#111; }
.trade-item.active { background:#1a1a2e; border-left-color:#ff8c00; }
.trade-item.hidden { display:none; }
.trade-item .ti-head { font-size:10px; color:#8b949e; }
.trade-item .sym { color:#ff8c00; font-weight:bold; font-size:11px;
  margin-left:4px; }
.trade-item .ti-meta { font-size:9px; margin:2px 0; }
.trade-item .result-win  { color:#26d47c; }
.trade-item .result-loss { color:#e85d5d; }
.trade-item .pnl { font-size:11px; font-weight:bold; }
.chart-area { flex:1; padding:12px; min-width:0; }
.chart-container { background:#0d1117; border:1px solid #1b2028; border-radius:6px; }
.data-panel { display:grid; grid-template-columns:repeat(4,1fr); gap:8px 14px;
  padding:12px 14px; background:#0d0d0d; border:1px solid #1b2028;
  border-radius:6px; margin-top:10px; }
.data-pair { display:flex; flex-direction:column; }
.data-label { color:#8b949e; font-size:9px; text-transform:uppercase;
  letter-spacing:0.5px; }
.data-value { color:#e5e7eb; font-size:11px; font-weight:bold; }
.omega-panel { padding:12px 14px; background:#0d0d0d; border:1px solid #1b2028;
  border-radius:6px; margin-top:8px; display:grid;
  grid-template-columns:repeat(5,1fr); gap:8px 14px; }
.omega-item { font-size:9px; color:#8b949e; }
.omega-item .omega-label { display:flex; justify-content:space-between;
  text-transform:uppercase; letter-spacing:0.5px; }
.omega-bar { height:6px; background:#1b2028; border-radius:2px;
  overflow:hidden; margin-top:3px; }
.omega-fill { height:100%; background:#ff8c00; }
.nav-bar { display:flex; align-items:center; justify-content:space-between;
  padding:8px 12px; background:#0d0d0d; border:1px solid #1b2028;
  border-radius:0 0 8px 8px; font-size:10px; color:#8b949e; gap:12px;
  flex-wrap:wrap; margin-top:-1px; }
.nav-btn { cursor:pointer; color:#ff8c00; user-select:none; padding:2px 8px;
  border-radius:3px; }
.nav-btn:hover { color:#ffaa44; background:#1a1a1a; }
</style>'''

    js = ('<script>\n(function() {\n'
          '  const TRADES = ' + json_blob + ';\n'
          '  const ALL = TRADES.map(t => t.slot);\n'
          '  let filtered = ALL.slice();\n'
          '  let curIdx = 0;\n'
          '  let resultFilter = "all";\n'
          '  let symbolFilter = "all";\n'
          '\n'
          '  function fmtP(v) {\n'
          '    if (v === 0 || v == null) return "0";\n'
          '    const a = Math.abs(v);\n'
          '    const d = a >= 1000 ? 2 : a >= 100 ? 2 : a >= 10 ? 3 : a >= 1 ? 4 : 5;\n'
          '    return v.toLocaleString("en-US", {minimumFractionDigits:d, maximumFractionDigits:d});\n'
          '  }\n'
          '  function fmtMoney(v) {\n'
          '    return (v >= 0 ? "+$" : "-$") + Math.abs(v).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2});\n'
          '  }\n'
          '  function omegaBar(label, val) {\n'
          '    const w = Math.max(0, Math.min(1, val)) * 100;\n'
          '    return \'<div class="omega-item"><div class="omega-label"><span>\' + label + \'</span><span>\' + val.toFixed(2) + \'</span></div><div class="omega-bar"><div class="omega-fill" style="width:\' + w.toFixed(0) + \'%"></div></div></div>\';\n'
          '  }\n'
          '\n'
          '  function showSlot(slot) {\n'
          '    document.querySelectorAll(".trade-svg").forEach(el => el.style.display = "none");\n'
          '    const svg = document.getElementById("svg-" + slot);\n'
          '    if (svg) svg.style.display = "block";\n'
          '    document.querySelectorAll(".trade-item").forEach(el => el.classList.remove("active"));\n'
          '    const item = document.getElementById("item-" + slot);\n'
          '    if (item) {\n'
          '      item.classList.add("active");\n'
          '      try { item.scrollIntoView({block:"nearest"}); } catch(e) {}\n'
          '    }\n'
          '    updateData(TRADES[slot]);\n'
          '    curIdx = filtered.indexOf(slot);\n'
          '    if (curIdx < 0) curIdx = 0;\n'
          '    updateNav();\n'
          '  }\n'
          '\n'
          '  function updateData(t) {\n'
          '    const grid = document.getElementById("data-panel");\n'
          '    const pnlColor = t.pnl >= 0 ? "#26d47c" : "#e85d5d";\n'
          '    const rColor   = t.rmult >= 0 ? "#26d47c" : "#e85d5d";\n'
          '    grid.innerHTML =\n'
          '      pair("Symbol", t.symbol) +\n'
          '      pair("Side", t.side) +\n'
          '      pair("Result", t.result, pnlColor) +\n'
          '      pair("PnL", fmtMoney(t.pnl), pnlColor) +\n'
          '      pair("Entry", fmtP(t.entry)) +\n'
          '      pair("Stop", fmtP(t.stop), "#e85d5d") +\n'
          '      pair("Target", fmtP(t.target), "#26d47c") +\n'
          '      pair("Exit", fmtP(t.exit)) +\n'
          '      pair("Score Ω", t.score.toFixed(3)) +\n'
          '      pair("Regime", t.macro) +\n'
          '      pair("Vol", t.vol) +\n'
          '      pair("DD Scale", t.dd_scale.toFixed(2)) +\n'
          '      pair("Duration", t.duration + "c") +\n'
          '      pair("RR Plan", t.rr.toFixed(2) + "x") +\n'
          '      pair("R-Mult", t.rmult.toFixed(2) + "R", rColor) +\n'
          '      pair("Slot", "#" + (t.slot + 1));\n'
          '    document.getElementById("omega-grid").innerHTML =\n'
          '      omegaBar("struct",   t.os) +\n'
          '      omegaBar("flow",     t.of) +\n'
          '      omegaBar("cascade",  t.oc) +\n'
          '      omegaBar("momentum", t.om) +\n'
          '      omegaBar("pullback", t.op);\n'
          '  }\n'
          '  function pair(label, value, color) {\n'
          '    const c = color ? \' style="color:\' + color + \'"\' : "";\n'
          '    return \'<div class="data-pair"><div class="data-label">\' + label + \'</div><div class="data-value"\' + c + \'>\' + value + \'</div></div>\';\n'
          '  }\n'
          '\n'
          '  function applyFilter() {\n'
          '    filtered = ALL.filter(s => {\n'
          '      const t = TRADES[s];\n'
          '      if (resultFilter === "win"  && t.result !== "WIN")  return false;\n'
          '      if (resultFilter === "loss" && t.result !== "LOSS") return false;\n'
          '      if (symbolFilter !== "all"  && t.symbol !== symbolFilter) return false;\n'
          '      return true;\n'
          '    });\n'
          '    document.querySelectorAll(".trade-item").forEach(el => {\n'
          '      const slot = parseInt(el.dataset.slot);\n'
          '      el.classList.toggle("hidden", filtered.indexOf(slot) === -1);\n'
          '    });\n'
          '    if (filtered.length > 0) showSlot(filtered[0]);\n'
          '    updateStats();\n'
          '  }\n'
          '\n'
          '  function updateStats() {\n'
          '    const subset = filtered.map(s => TRADES[s]);\n'
          '    const wins = subset.filter(t => t.result === "WIN").length;\n'
          '    const wr = subset.length ? (wins / subset.length * 100) : 0;\n'
          '    const pnl = subset.reduce((a, t) => a + t.pnl, 0);\n'
          '    document.getElementById("nav-stats").textContent =\n'
          '      "WR " + wr.toFixed(1) + "%  |  PnL $" + pnl.toFixed(0) + "  |  " + filtered.length + " trades";\n'
          '  }\n'
          '\n'
          '  function updateNav() {\n'
          '    document.getElementById("nav-counter").textContent =\n'
          '      (curIdx + 1) + " / " + filtered.length;\n'
          '  }\n'
          '\n'
          '  function next() { if (filtered.length === 0) return;\n'
          '    curIdx = (curIdx + 1) % filtered.length; showSlot(filtered[curIdx]); }\n'
          '  function prev() { if (filtered.length === 0) return;\n'
          '    curIdx = (curIdx - 1 + filtered.length) % filtered.length; showSlot(filtered[curIdx]); }\n'
          '\n'
          '  document.querySelectorAll(".trade-item").forEach(el => {\n'
          '    el.addEventListener("click", () => showSlot(parseInt(el.dataset.slot)));\n'
          '  });\n'
          '  document.querySelectorAll(".filter-btn").forEach(btn => {\n'
          '    btn.addEventListener("click", () => {\n'
          '      resultFilter = btn.dataset.filter;\n'
          '      document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));\n'
          '      btn.classList.add("active");\n'
          '      applyFilter();\n'
          '    });\n'
          '  });\n'
          '  const symSel = document.getElementById("symbol-filter");\n'
          '  if (symSel) symSel.addEventListener("change", () => {\n'
          '    symbolFilter = symSel.value; applyFilter();\n'
          '  });\n'
          '  document.getElementById("prev-btn").addEventListener("click", prev);\n'
          '  document.getElementById("next-btn").addEventListener("click", next);\n'
          '\n'
          '  document.addEventListener("keydown", (e) => {\n'
          '    if (e.target && (e.target.tagName === "SELECT" || e.target.tagName === "INPUT")) return;\n'
          '    if (e.key === "ArrowLeft" || e.key === "ArrowUp")   { prev(); e.preventDefault(); }\n'
          '    if (e.key === "ArrowRight"|| e.key === "ArrowDown") { next(); e.preventDefault(); }\n'
          '  });\n'
          '\n'
          '  if (TRADES.length > 0) showSlot(TRADES[0].slot);\n'
          '  updateStats();\n'
          '})();\n'
          '</script>')

    return f'''{css}
<div class="trade-inspector">
  <div class="trade-list">
    <div class="filter-row">
      <button class="filter-btn active" data-filter="all">ALL</button>
      <button class="filter-btn" data-filter="win">WIN</button>
      <button class="filter-btn" data-filter="loss">LOSS</button>
      <select class="symbol-filter" id="symbol-filter">{sym_opts}</select>
    </div>
    <div class="trade-items">
      {"".join(items_html)}
    </div>
  </div>
  <div class="chart-area">
    <div class="chart-container">{"".join(svg_html)}</div>
    <div class="data-panel" id="data-panel"></div>
    <div class="omega-panel" id="omega-grid"></div>
  </div>
</div>
<div class="nav-bar">
  <div><span class="nav-btn" id="prev-btn">◄ prev</span></div>
  <div id="nav-counter">1 / {n_total}</div>
  <div><span class="nav-btn" id="next-btn">next ►</span></div>
  <div id="nav-stats">WR {wr_total:.1f}%  |  PnL ${pnl_total:.0f}  |  {n_total} trades</div>
</div>
{js}'''


# ── Main generator ───────────────────────────────────────────────

def generate_report(all_trades, eq, mc, cond, ratios, mdd_pct, wf, wf_regime,
                    by_sym, all_vetos, run_dir, config_dict=None,
                    price_data=None, audit_results=None,
                    engine_name: str | None = None) -> str:
    """Self-contained HTML at run_dir/report.html.

    engine_name overrides config_dict.get("ENGINE") for header. If neither
    is set, falls back to inferring from run_dir name (e.g. "citadel_..."
    → "CITADEL", or last folder segment uppercased).
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / "report.html"

    # Resolve engine name with precedence: explicit kwarg > config["ENGINE"] > path inference
    if not engine_name:
        engine_name = (config_dict or {}).get("ENGINE")
    if not engine_name:
        # Try to infer from run_dir parent name (data/<engine>/<run_id>)
        parent_name = run_dir.parent.name.lower()
        _ENGINE_FROM_DIR = {
            "bridgewater": "BRIDGEWATER", "jump": "JUMP", "deshaw": "DE SHAW",
            "renaissance": "RENAISSANCE", "millennium": "MILLENNIUM",
            "twosigma": "TWO SIGMA", "aqr": "AQR", "janestreet": "JANE STREET",
            "runs": "CITADEL",  # citadel writes to data/runs/
        }
        engine_name = _ENGINE_FROM_DIR.get(parent_name, parent_name.upper() or "AURUM")

    # ── Build all sections ──
    header = _build_header(run_dir, config_dict, engine_name=engine_name)
    result_box = _build_result_box(all_trades, eq, ratios, mdd_pct)
    executive_strip = _build_executive_strip(
        all_trades, by_sym, audit_results, wf_regime, all_vetos
    )
    equity_svg = _svg_equity(eq)
    symbol_table = _build_symbol_table(by_sym, all_trades)
    omega_table = _build_omega_table(cond)
    wf_table = _build_wf_table(wf)
    veto_html = _build_veto_section(all_vetos)
    # Pre-render every per-trade SVG once and embed inside the Trade Inspector.
    # Falls back to an empty list when price_data is missing.
    _prerendered = _prerender_trade_charts(all_trades, price_data or {})
    trade_inspector_html = _build_trade_inspector(_prerendered) if _prerendered else ""

    # Audit section
    audit_html = ""
    if audit_results:
        try:
            from analysis.overfit_audit import build_audit_html
            audit_html = _details_block(
                "Overfit Audit",
                build_audit_html(audit_results),
                subtitle="reality checks and concentration diagnostics",
                open_=False,
                tone="risk",
                kicker="Reality Check",
            )
        except Exception:
            pass

    # Monte Carlo (optional)
    mc_html = ""
    if mc:
        mc_paths_svg = _svg_mc_paths(mc, eq)
        mc_hist_svg = _svg_mc_histogram(mc)
        mc_stats = _build_mc_stats(mc)
        mc_html = _details_block("Monte Carlo Simulation", f"""
            {mc_paths_svg}
            <div style="height:16px;"></div>
            {mc_hist_svg}
            {mc_stats}
        """, subtitle="distribution and drawdown stress", open_=False, kicker="Risk")

    # Walk-forward regime summary
    wf_regime_html = ""
    if wf_regime:
        regime_cards = []
        for regime, data in wf_regime.items():
            windows = data.get("windows", 0)
            stable = data.get("stable_pct")
            if stable is None:
                stable = 0
            r_color = _GREEN if stable >= 60 else (_GOLD if stable >= 40 else _RED)
            regime_cards.append(_metric_card(
                f"{regime} ({windows}w)",
                f"{stable:.0f}% stable",
                r_color
            ))
        wf_regime_html = f'''<div style="display:flex;gap:12px;flex-wrap:wrap;
                              margin-top:12px;">{"".join(regime_cards)}</div>'''

    # NOTE: PNG charts removed — metrics are now rendered inside the launcher
    # terminal (equity curve, MC paths, distribution as native tk.Canvas).
    # The HTML report keeps SVG-based equity_svg/mc_paths_svg/mc_hist_svg
    # which are inline and self-contained.
    institutional_html = executive_strip

    # ── Assemble full HTML ──
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{engine_name} - AURUM Backtest Report</title>
<style>
  :root {{
    --bg: {_BG};
    --panel: rgba(15, 18, 28, 0.86);
    --panel-strong: rgba(15, 18, 28, 0.94);
    --panel-soft: rgba(255,255,255,0.03);
    --border: rgba(255,255,255,0.06);
    --border-strong: {_BORDER};
    --text: {_WHITE};
    --muted: {_GRAY};
    --accent: {_GOLD};
    --positive: {_GREEN};
    --negative: {_RED};
    --info: {_BLUE};
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    background:
      radial-gradient(circle at top left, rgba(74,158,255,0.10), transparent 28%),
      radial-gradient(circle at top right, rgba(232,184,75,0.08), transparent 24%),
      linear-gradient(180deg, #0a0c12 0%, #0d1017 100%);
    color: var(--text);
    font-family: 'Inter', 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
    line-height: 1.6;
    padding: 0;
  }}
  .container {{
    max-width: 1120px;
    margin: 0 auto;
    padding: 28px 32px 56px 32px;
  }}
  table {{ border-spacing: 0; }}
  th {{
    color: {_GOLD};
    font-weight: 700;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }}
  tr {{ border-bottom: 1px solid {_BORDER}; }}
  td {{ border-bottom: 1px solid {_BORDER}; }}
  a {{ color: {_BLUE}; text-decoration: none; }}
  section {{ background: transparent; }}
  .hero {{
    background: rgba(15, 18, 28, 0.92);
    border: 1px solid var(--border);
    border-radius: 24px;
    padding: 32px 34px 28px 34px;
    margin-bottom: 28px;
    box-shadow: 0 24px 80px rgba(0,0,0,0.35);
    backdrop-filter: blur(10px);
  }}
  .hero-top {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 18px;
  }}
  .eyebrow {{
    color: {_GOLD};
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 10px;
  }}
  .hero h1 {{
    font-size: 44px;
    line-height: 1.0;
    letter-spacing: -0.04em;
    margin-bottom: 10px;
    font-weight: 800;
    background: linear-gradient(90deg, {_WHITE} 0%, {_GOLD} 100%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    display: inline-block;
  }}
  .hero-subtitle {{
    color: {_GRAY};
    font-size: 13px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .hero-badge {{
    color: {_GOLD};
    background: rgba(232,184,75,0.08);
    border: 1px solid rgba(232,184,75,0.25);
    border-radius: 999px;
    padding: 10px 16px;
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    font-weight: 700;
    white-space: nowrap;
  }}
  .hero-meta {{
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
    margin-bottom: 18px;
  }}
  .hero-meta-item {{
    flex: 1;
    min-width: 220px;
    background: linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.012) 100%);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 14px;
    padding: 14px 18px;
  }}
  .hero-meta-item span {{
    display: block;
    color: {_GRAY};
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    margin-bottom: 8px;
  }}
  .hero-meta-item strong {{
    color: {_WHITE};
    font-size: 14px;
    font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.02em;
  }}
  .hero-config {{
    color: var(--muted);
    font-size: 11px;
    line-height: 2.0;
    letter-spacing: 0.04em;
    padding-top: 14px;
    border-top: 1px solid rgba(255,255,255,0.04);
  }}
  .executive-strip {{
    margin-bottom: 22px;
  }}
  .strip-header {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
    padding: 0 2px;
  }}
  .strip-header .section-kicker {{
    color: var(--accent);
  }}
  .strip-header h2 {{
    font-size: 18px;
    letter-spacing: -0.02em;
  }}
  .strip-grid {{
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 16px;
  }}
  .summary-shell {{
    margin-bottom: 32px;
  }}
  .summary-card {{
    position: relative;
    background: linear-gradient(180deg, rgba(15,18,28,0.94) 0%, rgba(13,15,22,0.94) 100%);
    border: 1px solid var(--border);
    border-radius: 24px;
    padding: 38px 32px 32px 32px;
    box-shadow: 0 24px 80px rgba(0,0,0,0.28);
    overflow: hidden;
  }}
  .summary-card::before {{
    content: "";
    position: absolute;
    top: 0; left: 30%; right: 30%;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    opacity: 0.5;
  }}
  .summary-balance {{
    margin-bottom: 26px;
    text-align: center;
  }}
  .summary-balance-label {{
    color: {_GRAY};
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    margin-bottom: 12px;
  }}
  .summary-balance-main {{
    display: flex;
    gap: 14px;
    align-items: baseline;
    justify-content: center;
    flex-wrap: wrap;
    font-size: 48px;
    font-weight: 700;
    letter-spacing: -0.03em;
    line-height: 1.05;
  }}
  .summary-balance-main .muted {{
    color: {_WHITE};
    opacity: 0.45;
    font-size: 26px;
    font-weight: 600;
  }}
  .summary-balance-main .arrow {{
    color: {_GRAY};
    font-size: 22px;
    opacity: 0.6;
  }}
  .summary-balance-roi {{
    margin-top: 10px;
    font-size: 17px;
    font-weight: 700;
    letter-spacing: 0.04em;
  }}
  .summary-grid {{
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 16px;
  }}
  .metric-card {{
    position: relative;
    background: linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0.012) 100%);
    border: 1px solid rgba(255,255,255,0.05);
    border-radius: 16px;
    padding: 18px 16px;
    min-width: 0;
    min-height: 82px;
    text-align: center;
    display: flex;
    flex-direction: column;
    justify-content: center;
    overflow: hidden;
  }}
  .metric-card::before {{
    content: "";
    position: absolute;
    top: 0; left: 20%; right: 20%;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    opacity: 0.35;
  }}
  .metric-label {{
    color: {_GRAY};
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    margin-bottom: 10px;
  }}
  .metric-value {{
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.02em;
    font-variant-numeric: tabular-nums;
  }}
  .verdict-row {{
    margin-top: 22px;
    text-align: center;
  }}
  .summary-verdict {{
    display: inline-flex;
    align-items: center;
    gap: 10px;
    padding: 10px 22px;
    border-radius: 999px;
    border: 1px solid currentColor;
    background: rgba(255,255,255,0.03);
    font-size: 11px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    font-weight: 700;
  }}
  .summary-verdict::before {{
    content: "";
    display: inline-block;
    width: 7px; height: 7px; border-radius: 50%;
    background: currentColor;
    box-shadow: 0 0 10px currentColor;
  }}
  .report-section {{
    background: rgba(15, 18, 28, 0.55);
    border: 1px solid rgba(255,255,255,0.035);
    border-radius: 20px;
    padding: 28px 30px;
    margin-bottom: 26px;
    box-shadow: 0 12px 40px rgba(0,0,0,0.18);
  }}
  .section-head {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 16px;
    padding-bottom: 10px;
    border-bottom: 1px solid rgba(255,255,255,0.06);
  }}
  .section-kicker {{
    color: {_GOLD};
    font-size: 10px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
  }}
  .section-head h2 {{
    color: {_WHITE};
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }}
  .section-body {{
    overflow-x: auto;
  }}
  .report-section table,
  .details-body table {{
    font-variant-numeric: tabular-nums;
  }}
  .report-section th,
  .details-body th {{
    padding-top: 10px;
    padding-bottom: 12px;
  }}
  .report-section thead tr,
  .details-body thead tr {{
    border-bottom: 1px solid rgba(232,184,75,0.28) !important;
  }}
  .report-section tbody tr,
  .details-body tbody tr {{
    border-bottom: 1px solid rgba(255,255,255,0.035) !important;
    transition: background 0.15s;
  }}
  .report-section tbody tr:hover,
  .details-body tbody tr:hover {{
    background: rgba(232,184,75,0.04) !important;
  }}
  .report-section tbody tr:last-child,
  .details-body tbody tr:last-child {{
    border-bottom: none !important;
  }}
  .report-section tbody td,
  .details-body tbody td {{
    border-bottom: none !important;
    padding-top: 8px !important;
    padding-bottom: 8px !important;
  }}
  .details-block {{
    background: rgba(15, 18, 28, 0.55);
    border: 1px solid rgba(255,255,255,0.035);
    border-radius: 20px;
    margin-bottom: 20px;
    overflow: hidden;
    box-shadow: 0 12px 40px rgba(0,0,0,0.16);
    transition: border-color 0.2s;
  }}
  .details-block:hover {{
    border-color: rgba(232,184,75,0.18);
  }}
  .details-block[open] {{
    border-color: rgba(232,184,75,0.14);
  }}
  .details-block summary {{
    list-style: none;
    cursor: pointer;
    padding: 20px 26px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }}
  .details-block summary::-webkit-details-marker {{
    display: none;
  }}
  .details-head {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    flex-wrap: wrap;
  }}
  .details-kicker {{
    color: var(--accent);
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.18em;
  }}
  .details-title {{
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }}
  .details-subtitle {{
    color: var(--muted);
    font-size: 12px;
  }}
  .details-toggle {{
    color: var(--muted);
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.14em;
  }}
  .details-block[open] .details-toggle {{
    color: var(--text);
  }}
  .details-body {{
    padding: 4px 26px 24px 26px;
    border-top: 1px solid rgba(255,255,255,0.04);
  }}
  .tone-risk {{
    border-color: rgba(232,93,93,0.24);
  }}
  .veto-grid {{
    display: flex;
    flex-direction: column;
    gap: 10px;
  }}
  .veto-row {{
    display: grid;
    grid-template-columns: 220px 1fr 130px;
    align-items: center;
    gap: 16px;
  }}
  .veto-label {{
    font-size: 12px;
    color: {_WHITE};
    text-align: right;
    font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
    letter-spacing: 0.02em;
  }}
  .veto-track {{
    background: rgba(255,255,255,0.035);
    border-radius: 999px;
    height: 10px;
    overflow: hidden;
    position: relative;
  }}
  .veto-bar {{
    height: 100%;
    border-radius: 999px;
    box-shadow: 0 0 12px rgba(232,184,75,0.25);
    transition: width 0.3s;
  }}
  .veto-count {{
    display: flex;
    gap: 10px;
    align-items: baseline;
    justify-content: flex-start;
    font-variant-numeric: tabular-nums;
  }}
  .veto-n {{
    color: {_WHITE};
    font-size: 13px;
    font-weight: 700;
  }}
  .veto-pct {{
    color: {_GRAY};
    font-size: 11px;
  }}
  @media (max-width: 720px) {{
    .veto-row {{ grid-template-columns: 1fr; gap: 4px; }}
    .veto-label {{ text-align: left; }}
  }}
  footer {{
    opacity: 0.9;
  }}
  .report-footer {{
    position: relative;
    text-align: center;
    padding: 32px 0 16px 0;
    margin-top: 40px;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 10px;
  }}
  .report-footer::before {{
    content: "";
    position: absolute;
    top: 0; left: 35%; right: 35%;
    height: 1px;
    background: linear-gradient(90deg, transparent, {_GOLD}, transparent);
    opacity: 0.4;
  }}
  .footer-mark {{
    color: {_GOLD};
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.4em;
  }}
  .footer-meta {{
    color: {_GRAY};
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    display: flex;
    gap: 10px;
    align-items: center;
    font-variant-numeric: tabular-nums;
  }}
  .footer-dot {{
    opacity: 0.4;
  }}
  @media (max-width: 960px) {{
    .container {{ padding: 20px 18px 40px 18px; }}
    .strip-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .summary-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .hero-top {{ flex-direction: column; }}
  }}
  @media (max-width: 640px) {{
    .hero h1 {{ font-size: 28px; }}
    .summary-balance-main {{ font-size: 28px; }}
    .strip-grid {{ grid-template-columns: 1fr; }}
    .summary-grid {{ grid-template-columns: 1fr; }}
    .report-section {{ padding: 18px 16px; }}
    .details-block summary {{ padding: 16px; }}
    .details-body {{ padding: 0 16px 16px 16px; }}
  }}
  ::selection {{ background: {_GOLD}; color: {_BG}; }}
</style>
</head>
<body>
<div class="container">

{header}

{result_box}

{institutional_html}

{_section("Equity Curve", equity_svg, "equity", kicker="Capital Trajectory")}

{_section("Performance by Symbol", symbol_table, "symbols", kicker="Performance")}

{audit_html}

{mc_html}

{_details_block("Trade Inspector", trade_inspector_html, subtitle="per-trade replay and execution context", open_=False, kicker="Forensics") if trade_inspector_html else ""}

{_details_block("Edge by Omega Score Range", omega_table, subtitle="score stratification and expectancy", open_=False, kicker="Edge Attribution")}

{_details_block("Walk-Forward Analysis", wf_table + wf_regime_html, subtitle="stability outside the in-sample slice", open_=False, kicker="Stability")}

{_details_block("Veto Filters", veto_html, subtitle="dominant rejection reasons during scan", open_=False, kicker="Diagnostics")}

<footer class="report-footer">
  <div class="footer-mark">AURUM</div>
  <div class="footer-meta">
    <span>{engine_name}</span>
    <span class="footer-dot">&middot;</span>
    <span>Generated {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</span>
  </div>
</footer>

</div>
</body>
</html>'''

    out_path.write_text(html, encoding="utf-8")
    return str(out_path)
