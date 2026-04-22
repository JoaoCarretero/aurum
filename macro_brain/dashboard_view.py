"""Macro Brain cockpit — VGUI / Source Engine nostalgia.

Design principles (v7 — HL2 / CS 1.6 palette):
  - Warm cream text on charcoal gray (classic Source engine VGUI).
  - Primary accent: HL2 orange. Hover brightens, never shifts hue.
  - Sparklines removed — values + % change carry the signal.
  - Section headers as utilitarian brackets: [ TITLE ] ──────
  - Top bar reads "» MACRO BRAIN «" — MOTD / CS 1.6 scoreboard vibe.
  - Tabs numbered 1-8 with plain separator (no fantasy glyphs).
  - Signal colours (GREEN/RED) reserved for P&L / directional sentiment.
  - Uniform padding constants. Every interactive element hovers.

Tabs (agrupadas mkt / anl / ops no tab bar):
  [1] EUA       US desk completo: rates, equities, macro, COT, institutions, news
  [2] BRASIL    IBOV + top B3 stocks + ADRs + BRL forex
  [3] CRIPTO    by network — BTC, ETH, SOL, HYPE, DeFi cross-chain, bots
  [4] SINAIS    analytics cards derivados
  [5] MACRO     cross-market board: global indices, commodities, crypto macro
  [6] REDE      BTC on-chain + processes + VPS
  [7] LIVRO     macro P&L + theses + positions + regime
  [8] MOTORES   engine picker (shared with launcher)
"""
from __future__ import annotations

import json
import logging
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk

log = logging.getLogger("macro_brain.dashboard")

# ── PALETTE (HL2 / CS 1.6 VGUI) ──────────────────────────────
# Importado do SSOT core/ui_palette.py — muda lá, todo software
# adota. Nomes mantidos pra compat com call-sites locais.
from core.ui.ui_palette import (
    BG, BG2, BG3, PANEL,
    BORDER, BORDER_H,
    AMBER, AMBER_H,
    WHITE, DIM, DIM2,
    GREEN, RED, CYAN,
    FONT,
)

# ── SPACING (consistent across all tabs) ─────────────────────
PAD_OUT         = 8    # outer cockpit padding
PAD_SECTION_TOP = 10   # gap above each section header
PAD_SECTION_BAR = 3    # gap under the section separator
PAD_ROW         = 2    # vertical gap between tile rows
PAD_TILE_X      = 2    # horizontal gap between tiles in a row
PAD_TILE_INNER  = 4    # inner padding of a tile
PAD_COL_GAP     = 6    # gap between left/right columns

_STATE = {"tab": "EUA", "news_filter": "ALL"}
_VPS_STATUS_CACHE = {
    "expires_at": 0.0,
    "online": False,
    "detail": "checking...",
    "pending": False,
}
_VPS_STATUS_LOCK = threading.Lock()

# In-place tick registry — populated on render(), read on tick_update().
# Each key is a metric name (e.g. "BTC_SPOT"); value holds refs to the
# widgets that display its value/change/spark, plus the format string so
# we can re-format new values consistently. Cleared at the top of every
# full render() so stale refs from previous screens don't leak.
_TILE_REGISTRY: dict[str, dict] = {}


def _clear_tile_registry() -> None:
    _TILE_REGISTRY.clear()
    # _STATUSBAR refs apontam pra widgets que tb sao destruidos no
    # render() parent.destroy() loop. Limpar junto evita stale refs.
    try:
        _STATUSBAR.clear()
    except NameError:
        pass


def _read_vps_status() -> tuple[bool, str]:
    now = datetime.utcnow().timestamp()
    with _VPS_STATUS_LOCK:
        if now < float(_VPS_STATUS_CACHE["expires_at"]):
            return bool(_VPS_STATUS_CACHE["online"]), str(_VPS_STATUS_CACHE["detail"])
        if not bool(_VPS_STATUS_CACHE["pending"]):
            _VPS_STATUS_CACHE["pending"] = True
            _VPS_STATUS_CACHE["detail"] = "checking..."
            threading.Thread(target=_probe_vps_status, daemon=True).start()
        return bool(_VPS_STATUS_CACHE["online"]), str(_VPS_STATUS_CACHE["detail"])


def _probe_vps_status() -> None:
    online = False
    detail = "not configured"
    try:
        from config.paths import VPS_CONFIG_PATH

        vps_path = VPS_CONFIG_PATH
        if vps_path.exists():
            cfg = json.loads(vps_path.read_text(encoding="utf-8"))
            host = str(cfg.get("host") or "").strip()
            if host and host not in ("", "n/a"):
                import socket

                try:
                    port = int(cfg.get("port", 22))
                    with socket.create_connection((host, port), timeout=0.8):
                        online = True
                    detail = f"{host}:{port}"
                except (OSError, ValueError):
                    detail = f"{host}:{cfg.get('port', 22)}"
            else:
                detail = "host not set"
    except (OSError, json.JSONDecodeError):
        detail = "config error"
    finally:
        with _VPS_STATUS_LOCK:
            _VPS_STATUS_CACHE["online"] = online
            _VPS_STATUS_CACHE["detail"] = detail
            _VPS_STATUS_CACHE["expires_at"] = datetime.utcnow().timestamp() + 30.0
            _VPS_STATUS_CACHE["pending"] = False


def _cancel_chunk_jobs(parent: tk.Widget) -> None:
    jobs = getattr(parent, "_macro_chunk_jobs", None) or []
    for job in jobs:
        try:
            parent.after_cancel(job)
        except Exception:
            pass
    try:
        parent._macro_chunk_jobs = []
    except Exception:
        pass
    try:
        delattr(parent, "_macro_active_chunk_job")
    except Exception:
        pass


def _track_chunk_job(parent: tk.Widget, job) -> None:
    jobs = list(getattr(parent, "_macro_chunk_jobs", None) or [])
    jobs.append(job)
    parent._macro_chunk_jobs = jobs
    parent._macro_active_chunk_job = job


def _discard_chunk_job(parent: tk.Widget, job) -> None:
    jobs = list(getattr(parent, "_macro_chunk_jobs", None) or [])
    try:
        jobs.remove(job)
    except ValueError:
        pass
    parent._macro_chunk_jobs = jobs


def _run_chunked(parent: tk.Widget, steps: list, *, metric_name: str | None = None) -> None:
    started = time.perf_counter()

    def _run(index: int) -> None:
        active_job = getattr(parent, "_macro_active_chunk_job", None)
        if active_job is not None:
            _discard_chunk_job(parent, active_job)
            try:
                delattr(parent, "_macro_active_chunk_job")
            except Exception:
                pass
        if index >= len(steps):
            if metric_name:
                try:
                    from launcher_support.screens._metrics import emit_timing_metric

                    emit_timing_metric(metric_name, ms=(time.perf_counter() - started) * 1000.0)
                except Exception:
                    pass
            return
        steps[index]()
        job = parent.after_idle(lambda idx=index + 1: _run(idx))
        _track_chunk_job(parent, job)

    _run(0)


# ── DATA UTILS ───────────────────────────────────────────────

def _macro_map(metrics, n=30):
    from macro_brain.persistence.store import macro_series_many
    out = {}
    series_map = macro_series_many(metrics)
    for m in metrics:
        s = series_map.get(m) or []
        if not s: continue
        vals = [r["value"] for r in s[-n:]]
        last = s[-1]; prev = s[-2] if len(s) > 1 else None
        out[m] = {"value": last["value"], "ts": last["ts"],
                  "prev": prev["value"] if prev else None, "series": vals}
    return out


def _pct_change(a, b):
    if a is None or b is None or b == 0: return None
    return (a - b) / abs(b) * 100


def _fmt_age(ts):
    if not ts: return "—"
    try: dt = datetime.fromisoformat(str(ts).replace("Z", "")[:19])
    except ValueError: return str(ts)[:10]
    s = int((datetime.utcnow() - dt).total_seconds())
    if s < 0:
        s = -s
        if s < 3600:  return f"+{s // 60}m"
        if s < 86400: return f"+{s // 3600}h"
        return f"+{s // 86400}d"
    if s < 60:     return f"{s}s"
    if s < 3600:   return f"{s // 60}m"
    if s < 86400:  return f"{s // 3600}h"
    return f"{s // 86400}d"


# ── UI PRIMITIVES ────────────────────────────────────────────

def _draw_spark(canvas, values, color=AMBER, w=80, h=14,
                show_bounds: bool = True):
    """Sparkline line chart com bounds opcionais (teto/piso pontilhados).

    ``show_bounds``: se True, desenha linhas pontilhadas no min e max da
    serie (dash dim) pra dar range visual instantaneo tipo Bloomberg.
    """
    canvas.delete("all")
    if not values or len(values) < 2:
        return
    mn, mx = min(values), max(values)
    rng = mx - mn if mx > mn else 1.0

    # Bounds dotted — teto e piso cinza dim. Desenha ANTES da linha
    # principal pra linha ficar por cima.
    if show_bounds and h >= 12:
        canvas.create_line(2, 2, w - 2, 2, fill=DIM2, dash=(1, 2))
        canvas.create_line(2, h - 2, w - 2, h - 2, fill=DIM2, dash=(1, 2))

    pts = []
    for i, v in enumerate(values):
        x = 2 + (w - 4) * (i / (len(values) - 1))
        y = h - 2 - (h - 4) * ((v - mn) / rng)
        pts.append(x); pts.append(y)
    if len(pts) >= 4:
        canvas.create_line(*pts, fill=color, width=1)


def _draw_spark_candles(canvas, values, w=80, h=14, show_bounds: bool = True):
    """Mini-candle sparkline — cada ponto e uma barra vertical verde (close
    maior que anterior) ou vermelha (menor). Vibe Bloomberg OHLC density.

    Cada barra ocupa da linha do close anterior ate o atual — altura
    relativa no range total da serie.
    """
    canvas.delete("all")
    if not values or len(values) < 2:
        return
    mn, mx = min(values), max(values)
    rng = mx - mn if mx > mn else 1.0
    n = len(values)
    bw = max(1.0, (w - 4) / n - 0.5)

    if show_bounds and h >= 12:
        canvas.create_line(2, 2, w - 2, 2, fill=DIM2, dash=(1, 2))
        canvas.create_line(2, h - 2, w - 2, h - 2, fill=DIM2, dash=(1, 2))

    for i in range(1, n):
        v, p = values[i], values[i - 1]
        fill = GREEN if v >= p else RED
        x = 2 + (w - 4) * (i / (n - 1))
        y1 = h - 2 - (h - 4) * ((v - mn) / rng)
        y2 = h - 2 - (h - 4) * ((p - mn) / rng)
        canvas.create_rectangle(
            x - bw / 2, min(y1, y2), x + bw / 2, max(y1, y2) + 1,
            fill=fill, outline="",
        )


def _attach_hover(widget: tk.Widget, default_border: str = BORDER,
                  hover_border: str = BORDER_H) -> None:
    """Give a framed widget a subtle border change on mouse enter/leave."""
    def _on(_e): widget.config(highlightbackground=hover_border)
    def _off(_e): widget.config(highlightbackground=default_border)
    widget.bind("<Enter>", _on)
    widget.bind("<Leave>", _off)


def _event_link(event: dict) -> str:
    raw = event.get("raw_json")
    if not raw:
        return ""
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, json.JSONDecodeError):
        return ""
    return str((payload or {}).get("link") or "").strip()


def _open_event_link(event: dict) -> None:
    link = _event_link(event)
    if not link:
        return
    try:
        webbrowser.open(link)
    except Exception:
        pass


def _clickable_bg_row(parent, open_fn=None) -> tk.Frame:
    row = tk.Frame(parent, bg=BG, cursor="hand2" if open_fn else "arrow",
                   highlightbackground=BG, highlightthickness=1)
    if open_fn:
        def _on(_e=None):
            row.configure(bg=BG2, highlightbackground=BORDER_H)
        def _off(_e=None):
            row.configure(bg=BG, highlightbackground=BG)
        row.bind("<Enter>", _on)
        row.bind("<Leave>", _off)
        row.bind("<Button-1>", lambda _e: open_fn())
    return row


def _tile(parent, label, value, change="", change_color=WHITE,
          series=None, spark_color=AMBER, metric_key: str | None = None,
          fmt: str | None = None):
    """Render one metric tile — TradingView-vibe com sparkline viva.

    Pre 2026-04-22: v6 removeu sparklines ("visual pollution"). Joao
    pediu pra trazer de volta — mais alive, tipo TradingView. Agora:
    - label + valor + change% em cima
    - sparkline (30 pontos) embaixo, cor segue direcao do ultimo tick
    - flash verde/vermelho no valor quando muda (via tick_update)
    """
    f = tk.Frame(parent, bg=PANEL,
                 highlightbackground=BORDER, highlightthickness=1)
    tk.Label(f, text=label, font=(FONT, 6, "bold"), fg=DIM2, bg=PANEL,
             anchor="w").pack(fill="x",
                              padx=PAD_TILE_INNER, pady=(3, 0))
    body = tk.Frame(f, bg=PANEL); body.pack(fill="x",
                                             padx=PAD_TILE_INNER,
                                             pady=(0, 2))
    value_lbl = tk.Label(body, text=value, font=(FONT, 11, "bold"),
                          fg=WHITE, bg=PANEL, anchor="w")
    value_lbl.pack(side="left")
    change_lbl = None
    if change:
        change_lbl = tk.Label(body, text=change, font=(FONT, 7, "bold"),
                               fg=change_color, bg=PANEL, anchor="e")
        change_lbl.pack(side="right", padx=2)

    # Sparkline canvas — sempre presente, mesmo tiles sem data iniciam
    # vazios e recebem a 1a renderizacao no primeiro tick_update.
    spark_cv = tk.Canvas(f, bg=PANEL, height=14, highlightthickness=0,
                          borderwidth=0)
    spark_cv.pack(fill="x", padx=PAD_TILE_INNER, pady=(0, 3))
    # Desenho inicial se ja temos series (mini-candles por default)
    if series:
        try:
            vals = [
                (r.get("value") if isinstance(r, dict) else r)
                for r in series[-30:]
            ]
            vals = [v for v in vals if isinstance(v, (int, float))]
            if len(vals) >= 2:
                # Deferred render via after() — winfo_width so e valido pos-pack.
                spark_cv.after(
                    30,
                    lambda cv=spark_cv, vv=vals:
                        _draw_spark_candles(cv, vv,
                                            w=(cv.winfo_width() or 80),
                                            h=14),
                )
        except Exception:
            pass

    _attach_hover(f)

    if metric_key:
        _TILE_REGISTRY[metric_key] = {
            "value": value_lbl,
            "change": change_lbl,
            "spark": spark_cv,
            "fmt": fmt,
            "spark_color": spark_color,
            "last_val": None,  # flash detection
        }
        # Click-to-expand — tile inteiro (frame + todos os labels) abre
        # popup detalhado com chart de 100 barras + min/max/last.
        _mk = metric_key
        _lbl = label
        _fmt = fmt

        def _click(_e=None, m=_mk, l=_lbl, fm=_fmt):
            _open_tile_detail(m, l, fm)

        f.configure(cursor="hand2")
        f.bind("<Button-1>", _click)
        for child in (value_lbl, change_lbl, spark_cv):
            if child is None:
                continue
            try:
                child.configure(cursor="hand2")
                child.bind("<Button-1>", _click)
            except Exception:
                pass
    return f


# ── NORTH-STAR WATCHLIST + STATUS BAR state ──────────────────
# Refs globais pra tick_update refrescar o statusbar em place, sem
# rebuild. Populados em _render_northstar / _render_statusbar.
_STATUSBAR: dict = {}
_TICK_STATS = {"count": 0, "last_changed": 0, "last_tick_at": None}


def _render_northstar(parent) -> None:
    """Strip fixo no topo com 5 tiles XL (BTC/ETH/SP500/DXY/BTC.D).

    Cada cell: label 7pt amber + value 20pt white + change 10pt + spark
    60px alto. Registra cada metric em _TILE_REGISTRY igual tiles normais
    — aproveita o tick_update existente pra refresh automatico (fade +
    candles + bounds).

    Vibe Bloomberg header: 5 "north stars" sempre visiveis, independente
    da tab ativa abaixo.
    """
    from macro_brain.persistence.store import macro_series_many

    bar = tk.Frame(parent, bg=BG,
                   highlightbackground=AMBER, highlightthickness=1)
    bar.pack(fill="x", pady=(4, 2))

    specs = [
        ("BTC_SPOT",       "BTC",    "${:,.0f}"),
        ("ETH_SPOT",       "ETH",    "${:,.2f}"),
        ("SP500",          "S&P",    "{:,.2f}"),
        ("DXY",            "DXY",    "{:.2f}"),
        ("BTC_DOMINANCE",  "BTC.D",  "{:.2f}%"),
    ]

    metrics_keys = [m for m, _, _ in specs]
    try:
        series_map = macro_series_many(metrics_keys)
    except Exception:
        series_map = {}

    for metric, lbl_text, fmt in specs:
        s = series_map.get(metric) or []
        val = s[-1].get("value") if s else None
        prev = s[-2].get("value") if len(s) > 1 else None

        cell = tk.Frame(bar, bg=BG2,
                        highlightbackground=BORDER, highlightthickness=1)
        cell.pack(side="left", fill="both", expand=True, padx=1, pady=1)

        tk.Label(cell, text=lbl_text, font=(FONT, 7, "bold"),
                 fg=AMBER, bg=BG2, anchor="w").pack(
            fill="x", padx=8, pady=(4, 0))

        vs = fmt.format(val) if val is not None else "—"
        vlbl = tk.Label(cell, text=vs, font=(FONT, 18, "bold"),
                        fg=WHITE, bg=BG2, anchor="w")
        vlbl.pack(fill="x", padx=8)

        pct = _pct_change(val, prev) if val is not None else None
        ch = f"{pct:+.2f}%" if pct is not None else ""
        cc = GREEN if (pct or 0) > 0 else (RED if (pct or 0) < 0 else DIM)
        chlbl = tk.Label(cell, text=ch, font=(FONT, 9, "bold"),
                         fg=cc, bg=BG2, anchor="w")
        chlbl.pack(fill="x", padx=8)

        cv = tk.Canvas(cell, bg=BG2, height=28,
                       highlightthickness=0, borderwidth=0)
        cv.pack(fill="x", padx=4, pady=(0, 4))
        # Draw initial candles (deferred — winfo_width so apos pack)
        if s and len(s) >= 2:
            vals = [r["value"] for r in s[-30:]
                    if isinstance(r.get("value"), (int, float))]
            if len(vals) >= 2:
                cv.after(30, lambda c=cv, v=vals:
                         _draw_spark_candles(c, v,
                                             w=(c.winfo_width() or 150),
                                             h=28))

        # Override bg=BG2 (nao PANEL) no registry — _flash_label precisa
        # saber pra onde voltar. Simples: tick_update usa PANEL default;
        # aqui o label usa BG2 como cor base, entao registramos com
        # spark_color/fmt normais mas marcamos "north_star": True pra
        # tratar no _flash_label (abaixo).
        _TILE_REGISTRY[metric] = {
            "value": vlbl,
            "change": chlbl,
            "spark": cv,
            "fmt": fmt,
            "spark_color": AMBER,
            "last_val": val if isinstance(val, (int, float)) else None,
            "north_star": True,
        }


def _render_statusbar(parent) -> None:
    """Barra fixa no bottom: ● LIVE · 47 tiles · last tick Xs ago · clock.

    Refs armazenadas em _STATUSBAR module-level pra tick_update refrescar.
    """
    bar = tk.Frame(parent, bg=BG2,
                   highlightbackground=BORDER, highlightthickness=1)
    bar.pack(fill="x", side="bottom", pady=(2, 0))

    dot = tk.Label(bar, text="●", font=(FONT, 9, "bold"),
                   fg=GREEN, bg=BG2)
    dot.pack(side="left", padx=(8, 4), pady=2)
    status = tk.Label(bar, text="LIVE", font=(FONT, 7, "bold"),
                      fg=WHITE, bg=BG2)
    status.pack(side="left", padx=2, pady=2)

    def _sep():
        return tk.Label(bar, text="│", font=(FONT, 7),
                        fg=DIM, bg=BG2)

    _sep().pack(side="left", padx=4)
    tiles_lbl = tk.Label(bar, text="0 tiles", font=(FONT, 7),
                         fg=DIM2, bg=BG2)
    tiles_lbl.pack(side="left", padx=2)

    _sep().pack(side="left", padx=4)
    tick_lbl = tk.Label(bar, text="no tick yet", font=(FONT, 7),
                        fg=DIM2, bg=BG2)
    tick_lbl.pack(side="left", padx=2)

    clock_lbl = tk.Label(bar, text="—", font=(FONT, 7, "bold"),
                         fg=AMBER, bg=BG2)
    clock_lbl.pack(side="right", padx=8)

    tk.Label(bar, text="aurum macro", font=(FONT, 6),
             fg=DIM, bg=BG2).pack(side="right", padx=(0, 4))

    _STATUSBAR.update({
        "dot": dot, "status": status, "tiles": tiles_lbl,
        "tick": tick_lbl, "clock": clock_lbl,
    })


def _statusbar_tick(changed: int) -> None:
    """Chamado por tick_update apos cada refresh. Atualiza counters +
    clock UTC in-place."""
    if not _STATUSBAR:
        return
    now = datetime.utcnow()
    try:
        clock = _STATUSBAR.get("clock")
        if clock and clock.winfo_exists():
            clock.configure(text=now.strftime("%H:%M:%S UTC"))
        tiles = _STATUSBAR.get("tiles")
        if tiles and tiles.winfo_exists():
            tiles.configure(text=f"{len(_TILE_REGISTRY)} tiles")
        tick = _STATUSBAR.get("tick")
        if tick and tick.winfo_exists():
            if changed > 0:
                tick.configure(
                    text=f"{changed} chg · just now", fg=GREEN,
                )
            else:
                tick.configure(
                    text=f"stable · {_TICK_STATS.get('count', 0)} ticks",
                    fg=DIM2,
                )
    except Exception:
        pass


def _open_tile_detail(metric_key: str, label: str,
                     fmt: str | None = None) -> None:
    """Click-to-expand popup (Toplevel 420x280) com chart detalhado de
    ate 100 barras (mini-candles grande) + min/max/last footer.

    Vibe drill-down TradingView: click tile = abre janela grande.
    """
    try:
        from macro_brain.persistence.store import macro_series_many
        s = (macro_series_many([metric_key]) or {}).get(metric_key) or []
        vals = [
            r["value"] for r in s[-100:]
            if isinstance(r.get("value"), (int, float))
        ]

        top = tk.Toplevel()
        top.title(f"{label} — {metric_key}")
        top.configure(bg=BG)
        top.geometry("440x300")

        tk.Label(top, text=f"  [ {label} · {metric_key} ]",
                 font=(FONT, 9, "bold"), fg=AMBER, bg=BG,
                 anchor="w").pack(fill="x", padx=8, pady=(8, 4))

        cv = tk.Canvas(top, bg=PANEL, width=420, height=220,
                       highlightthickness=1,
                       highlightbackground=BORDER)
        cv.pack(padx=10, pady=2)

        if len(vals) >= 2:
            cv.after(
                30,
                lambda: _draw_spark_candles(cv, vals, w=420, h=220),
            )
            foot_text = (
                f"  n={len(vals)}  "
                f"min {_fmt_val(min(vals), fmt)}  "
                f"max {_fmt_val(max(vals), fmt)}  "
                f"last {_fmt_val(vals[-1], fmt)}"
            )
        else:
            foot_text = f"  {label}: sem dados suficientes (n={len(vals)})"

        tk.Label(top, text=foot_text, font=(FONT, 8),
                 fg=DIM, bg=BG, anchor="w").pack(
            fill="x", padx=8, pady=(4, 4))

        tk.Label(top, text="  esc · close",
                 font=(FONT, 7), fg=DIM2, bg=BG,
                 anchor="w").pack(fill="x", padx=8)

        top.bind("<Escape>", lambda _e: top.destroy())
        top.focus_set()
    except Exception as exc:
        log.warning("open tile detail failed: %s", exc)


def _fmt_val(v, fmt: str | None) -> str:
    if fmt:
        try:
            return fmt.format(v)
        except (ValueError, TypeError):
            pass
    return f"{v:.4g}"


def _lerp_hex(c1: str, c2: str, t: float) -> str:
    """Linear-interpolate dois hex colors (#rrggbb). t em [0,1]."""
    try:
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return c2


def _flash_label(lbl: tk.Label, up: bool, steps: int = 8,
                 dur_ms: int = 480) -> None:
    """Fade gradient no bg do value_lbl: verde/vermelho intenso → PANEL,
    em ``steps`` quadros distribuidos em ``dur_ms``. Sensacao analogica
    (fade out) em vez de cut abrupto.

    Antes (cut): bg=GREEN por 450ms, depois PANEL. Visualmente aspero.
    Agora (fade): bg e fg interpolam de (GREEN|RED, BG) -> (PANEL, WHITE)
    em 8 steps de ~60ms cada. Vibe TradingView/Bloomberg.
    """
    try:
        if not lbl.winfo_exists():
            return
        src_bg = GREEN if up else RED
        src_fg = BG

        def _step(i: int = 0):
            if not lbl.winfo_exists():
                return
            t = i / steps
            lbl.configure(
                bg=_lerp_hex(src_bg, PANEL, t),
                fg=_lerp_hex(src_fg, WHITE, t),
            )
            if i < steps:
                lbl.after(dur_ms // steps, lambda: _step(i + 1))

        _step()
    except Exception:
        pass


def _grid(parent, data, specs, spark_color=AMBER):
    row = tk.Frame(parent, bg=BG); row.pack(fill="x", pady=PAD_ROW // 2)
    for metric, label, fmt in specs:
        info = data.get(metric) or {}
        val = info.get("value")
        if val is None:
            t = _tile(row, label, "\u2014", "no data", DIM,
                      metric_key=metric, fmt=fmt)
        else:
            try: vs = fmt.format(val)
            except (ValueError, TypeError): vs = str(val)
            pct = _pct_change(val, info.get("prev"))
            if pct is not None:
                ch = f"{pct:+.2f}%"
                cc = GREEN if pct > 0 else (RED if pct < 0 else DIM)
                sc = GREEN if pct > 0 else (RED if pct < 0 else spark_color)
            else:
                ch = ""; cc = DIM; sc = spark_color
            t = _tile(row, label, vs, ch, cc, info.get("series", []), sc,
                      metric_key=metric, fmt=fmt)
        t.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)


def tick_update() -> int:
    """Refresh the value/change/spark of every registered tile in place.

    Reads the latest numbers from the macro store and pushes them to the
    existing Tk widgets via ``configure(text=…)``. No destroy/rebuild, so
    the screen updates like a terminal ticker instead of flashing every
    tick. Returns the number of tiles that actually changed value.
    """
    try:
        from macro_brain.persistence.store import macro_series_many
    except Exception:
        return 0

    changed = 0
    live_refs: dict[str, dict] = {}
    for metric, refs in list(_TILE_REGISTRY.items()):
        value_lbl = refs.get("value")
        # Prune registry entries whose widgets are gone (tab switched).
        try:
            if value_lbl is None or not value_lbl.winfo_exists():
                _TILE_REGISTRY.pop(metric, None)
                continue
        except Exception:
            _TILE_REGISTRY.pop(metric, None)
            continue
        live_refs[metric] = refs

    if not live_refs:
        return 0

    try:
        series_map = macro_series_many(list(live_refs))
    except Exception:
        return 0

    for metric, refs in live_refs.items():
        value_lbl = refs.get("value")
        s = series_map.get(metric) or []
        if not s:
            continue
        last = s[-1]
        prev = s[-2] if len(s) > 1 else None
        val = last.get("value")
        if val is None:
            continue

        fmt = refs.get("fmt") or "{}"
        try:
            vs = fmt.format(val)
        except (ValueError, TypeError):
            vs = str(val)

        try:
            if value_lbl.cget("text") != vs:
                # Flash verde/vermelho antes de atualizar, pra sinalizar
                # direcao do movimento (tipo TradingView tape).
                last_val = refs.get("last_val")
                if last_val is not None and isinstance(val, (int, float)):
                    try:
                        if val > last_val:
                            _flash_label(value_lbl, up=True)
                        elif val < last_val:
                            _flash_label(value_lbl, up=False)
                    except Exception:
                        pass
                refs["last_val"] = val if isinstance(val, (int, float)) else last_val
                value_lbl.configure(text=vs)
                changed += 1
        except Exception:
            continue

        # Change / direction chip
        change_lbl = refs.get("change")
        if change_lbl is not None:
            try:
                if change_lbl.winfo_exists():
                    pct = _pct_change(val, (prev or {}).get("value"))
                    if pct is not None:
                        ch_text = f"{pct:+.2f}%"
                        ch_color = (GREEN if pct > 0
                                    else (RED if pct < 0 else DIM))
                        if change_lbl.cget("text") != ch_text:
                            change_lbl.configure(text=ch_text, fg=ch_color)
            except Exception:
                pass

        # Spark series — usa mini-candles por default pra densidade visual
        # estilo Bloomberg. Se spark_style='line', desenha polyline simples.
        spark_cv = refs.get("spark")
        if spark_cv is not None:
            try:
                if spark_cv.winfo_exists():
                    vals = [r["value"] for r in s[-30:]]
                    w = spark_cv.winfo_width() or 80
                    h = spark_cv.winfo_height() or 14
                    style = refs.get("spark_style", "candles")
                    if style == "line":
                        _draw_spark(
                            spark_cv, vals,
                            color=refs.get("spark_color", AMBER),
                            w=w, h=h,
                        )
                    else:
                        _draw_spark_candles(spark_cv, vals, w=w, h=h)
            except Exception:
                pass

    _TICK_STATS["count"] = _TICK_STATS.get("count", 0) + 1
    _TICK_STATS["last_changed"] = changed
    _TICK_STATS["last_tick_at"] = datetime.utcnow()
    _statusbar_tick(changed)
    return changed


def _section(parent, title, color=None, pady_top=None):
    """Section header — VGUI bracket: ║ [ TITLE ] ─────────────.

    `color` kept for back-compat but ignored (palette is uniform
    HL2 orange from the SSOT).
    `pady_top=(0,0)` suppresses gap above the first section in a tab.
    """
    top = pady_top[0] if pady_top is not None else PAD_SECTION_TOP
    tk.Frame(parent, bg=BG, height=top).pack(fill="x")
    row = tk.Frame(parent, bg=BG); row.pack(fill="x")
    # Left orange notch — VGUI panel hint.
    tk.Frame(row, bg=AMBER, width=3).pack(side="left", fill="y")
    # [ TITLE ] — utilitarian bracket label, Source Engine VGUI style.
    tk.Label(row, text=f"  [ {title} ]",
             font=(FONT, 8, "bold"),
             fg=AMBER, bg=BG, anchor="w", padx=2).pack(side="left")
    # Rule fills to the right — separates section from body.
    rule = tk.Frame(row, bg=BORDER, height=1)
    rule.pack(side="left", fill="x", expand=True, padx=(10, 2),
              pady=(7, 0))
    tk.Frame(parent, bg=BG, height=PAD_SECTION_BAR).pack(fill="x")


def _two_col(parent) -> tuple[tk.Frame, tk.Frame]:
    row = tk.Frame(parent, bg=BG); row.pack(fill="x")
    left = tk.Frame(row, bg=BG)
    left.pack(side="left", fill="both", expand=True,
              padx=(0, PAD_COL_GAP // 2))
    right = tk.Frame(row, bg=BG)
    right.pack(side="left", fill="both", expand=True,
               padx=(PAD_COL_GAP // 2, 0))
    return left, right


def _panel_shell(parent, *, fill: str = "x", pady: tuple[int, int] = (0, 0)) -> tk.Frame:
    shell = tk.Frame(parent, bg=PANEL,
                     highlightbackground=BORDER, highlightthickness=1)
    shell.pack(fill=fill, expand=(fill == "both"), padx=2, pady=pady)
    inner = tk.Frame(shell, bg=PANEL)
    inner.pack(fill=fill, expand=(fill == "both"), padx=6, pady=6)
    return inner


def _desk_banner(parent, metrics: dict, specs: list[tuple[str, str, str]]) -> None:
    row = tk.Frame(parent, bg=PANEL)
    row.pack(fill="x", pady=(0, 4))
    for metric, label, fmt in specs:
        info = metrics.get(metric) or {}
        val = info.get("value")
        if val is None:
            value_txt = "\u2014"
            change_txt = "no data"
            change_color = DIM
        else:
            try:
                value_txt = fmt.format(val)
            except (ValueError, TypeError):
                value_txt = str(val)
            pct = _pct_change(val, info.get("prev"))
            if pct is None:
                change_txt = "flat"
                change_color = DIM
            else:
                change_txt = f"{pct:+.2f}%"
                change_color = GREEN if pct > 0 else (RED if pct < 0 else DIM)

        tile = tk.Frame(row, bg=BG2,
                        highlightbackground=BORDER, highlightthickness=1)
        tile.pack(side="left", fill="both", expand=True, padx=1)
        _attach_hover(tile)
        tk.Label(tile, text=label, font=(FONT, 6, "bold"), fg=DIM2, bg=BG2,
                 anchor="w").pack(fill="x", padx=6, pady=(4, 0))
        tk.Label(tile, text=value_txt, font=(FONT, 10, "bold"), fg=WHITE, bg=BG2,
                 anchor="w").pack(fill="x", padx=6)
        tk.Label(tile, text=change_txt, font=(FONT, 7, "bold"), fg=change_color, bg=BG2,
                 anchor="w").pack(fill="x", padx=6, pady=(0, 4))


def _bind_scroll_canvas(canvas: tk.Canvas, window_id: int, pad_x: int = 0) -> None:
    def _fit(_event=None):
        live_w = max(canvas.winfo_width(), 1)
        canvas.itemconfigure(window_id, width=max(live_w - pad_x, 1))
        canvas.configure(scrollregion=canvas.bbox("all"))
    canvas.bind("<Configure>", _fit)
    _fit()


def _wire_scroll_wheel(canvas: tk.Canvas, targets: list[tk.Widget] | None = None) -> None:
    def _on_wheel(event):
        try:
            canvas.yview_scroll(-1 * (event.delta // 120), "units")
        except Exception:
            pass

    def _enter(_event=None):
        canvas.bind_all("<MouseWheel>", _on_wheel)

    def _leave(_event=None):
        try:
            canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass

    canvas.bind("<Enter>", _enter)
    canvas.bind("<Leave>", _leave)
    for target in targets or []:
        target.bind("<Enter>", _enter)
        target.bind("<Leave>", _leave)


def _render_bot_slots(parent, network: str,
                      outline: str = BORDER, accent_bg: str = AMBER):
    """Render bot watcher slots — uniform amber chip styling.

    `outline` / `accent_bg` kept for back-compat but overridden to palette.
    """
    try:
        from macro_brain.bots import list_descriptors
        descs = [d for d in list_descriptors() if d.network == network]
    except Exception:
        descs = []
    if not descs:
        return

    status_tone = {
        "planned":    ("·", DIM),
        "scaffolded": ("◦", AMBER),
        "live":       ("●", GREEN),
        "degraded":   ("!", RED),
    }

    slot_row = tk.Frame(parent, bg=BG); slot_row.pack(fill="x",
                                                      pady=PAD_ROW // 2)
    for d in descs:
        slot = tk.Frame(slot_row, bg=PANEL,
                        highlightbackground=BORDER, highlightthickness=1,
                        padx=8, pady=4)
        slot.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
        _attach_hover(slot)
        head = tk.Frame(slot, bg=PANEL); head.pack(anchor="w", fill="x")
        tk.Label(head, text=d.label, font=(FONT, 7, "bold"),
                 fg=AMBER, bg=PANEL).pack(side="left")
        dot, dot_color = status_tone.get(d.status, ("·", DIM))
        tk.Label(head, text=f"  {dot} {d.status}",
                 font=(FONT, 6, "bold"), fg=dot_color,
                 bg=PANEL).pack(side="left")
        tk.Label(slot, text=d.tagline, font=(FONT, 7),
                 fg=DIM2, bg=PANEL, anchor="w").pack(anchor="w")


def _cot_matrix(parent, rows: list[tuple]):
    """Render a CFTC COT positioning matrix — markets × trader classes.

    rows: list of (label, nc_metric, swap_metric, mm_metric) tuples.
    Each metric may be None. Latest value is pulled from macro_data;
    green/red tint based on sign, dim when missing.
    """
    from macro_brain.persistence.store import latest_macro, latest_macro_many

    metrics = [m for _label, nc, sw, mm in rows for m in (nc, sw, mm) if m]
    latest_map = latest_macro_many(metrics, n=1)

    def _val(metric: str | None) -> tuple[str, str]:
        if not metric:
            return "—", DIM
        lat = latest_map.get(metric) or []
        if not lat:
            return "—", DIM
        v = lat[0]["value"]
        try: v = float(v)
        except (TypeError, ValueError):
            return "—", DIM
        s = f"{v:+,.0f}"
        c = GREEN if v > 0 else (RED if v < 0 else WHITE)
        return s, c

    shell = tk.Frame(parent, bg=PANEL,
                     highlightbackground=BORDER, highlightthickness=1)
    shell.pack(fill="x", padx=2, pady=2)
    hdr = tk.Frame(shell, bg=PANEL); hdr.pack(fill="x", pady=(3, 1), padx=2)
    for txt, w, align in [
        ("MARKET",        14, "w"),
        ("NC NET",        13, "e"),
        ("SWAP · BANKS",  14, "e"),
        ("MM · FUNDS",    14, "e"),
    ]:
        tk.Label(hdr, text=txt, font=(FONT, 6, "bold"), fg=DIM, bg=PANEL,
                 width=w, anchor=align, padx=4).pack(side="left")
    tk.Frame(shell, bg=BORDER, height=1).pack(fill="x", pady=(0, 1), padx=2)

    for label, nc, sw, mm in rows:
        metrics = [m for m in (nc, sw, mm) if m]
        def _open_cot_detail(row_label=label, metric_names=metrics):
            lines = [row_label]
            for metric_name in metric_names:
                lat = latest_macro(metric_name, n=5)
                if not lat:
                    lines.append(f"{metric_name}: no data")
                    continue
                values = ", ".join(f"{float(r['value']):+,.0f}" for r in lat[:3])
                lines.append(f"{metric_name}: {values}")
            try:
                from tkinter import messagebox
                messagebox.showinfo("COT detail", "\n".join(lines))
            except Exception:
                pass

        row = _clickable_bg_row(shell, open_fn=_open_cot_detail if metrics else None)
        row.pack(fill="x", padx=2, pady=1)

        tk.Label(row, text=label, font=(FONT, 8, "bold"),
                 fg=WHITE, bg=row.cget("bg"), width=14, anchor="w",
                 padx=4).pack(side="left")
        for metric, w in [(nc, 13), (sw, 14), (mm, 14)]:
            s, c = _val(metric)
            tk.Label(row, text=s, font=(FONT, 8),
                     fg=c, bg=row.cget("bg"), width=w, anchor="e",
                     padx=4).pack(side="left")
        if metrics:
            tk.Label(row, text="OPEN", font=(FONT, 6, "bold"),
                     fg=AMBER, bg=row.cget("bg"), width=8, anchor="e").pack(side="right", padx=4)


def _render_calendar_list(parent, title: str, only_us: bool = False):
    from macro_brain.persistence.store import recent_events

    _section(parent, title)
    cal_events = recent_events(category="calendar", limit=30)
    now_iso = datetime.utcnow().isoformat()
    future = sorted([e for e in cal_events if e.get("ts", "") >= now_iso],
                    key=lambda e: e.get("ts", ""))[:15]
    if only_us:
        future = [
            e for e in future
            if any(tok in ((e.get("entities") or [""])[0] or "").upper()
                   for tok in ("FOMC", "FED", "CPI", "PCE", "NFP", "PAYROLL",
                               "JOBLESS", "UNEMPLOYMENT", "GDP", "PMI",
                               "RETAIL", "PPI", "MICHIGAN", "HOUSING",
                               "INDUSTRIAL"))
        ]
    if future:
        for e in future[:12]:
            impact = e.get("impact", 0) or 0
            label = (e.get("entities") or ["?"])[0] if e.get("entities") else "?"
            date_s = e.get("ts", "")[:10]
            imp_c = RED if impact >= 0.9 else (AMBER if impact >= 0.7 else DIM)
            row = _clickable_bg_row(parent, open_fn=(lambda ev=e: _open_event_link(ev)) if _event_link(e) else None)
            row.pack(fill="x", padx=2)
            tk.Frame(row, bg=imp_c, width=3).pack(side="left", fill="y")
            tk.Label(row, text=f" {date_s} ", font=(FONT, 8), fg=WHITE, bg=row.cget("bg"),
                     width=12, anchor="w").pack(side="left")
            tk.Label(row, text=label[:32], font=(FONT, 8, "bold"), fg=WHITE, bg=row.cget("bg"),
                     width=30, anchor="w").pack(side="left")
            tk.Label(row, text=f"{impact:.0%}", font=(FONT, 7), fg=imp_c, bg=row.cget("bg")).pack(side="left")
            if _event_link(e):
                tk.Label(row, text="OPEN", font=(FONT, 6, "bold"), fg=AMBER,
                         bg=row.cget("bg")).pack(side="right", padx=4)
    else:
        tk.Label(parent, text="  (no upcoming releases)",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)


def _render_news_list(parent, title: str, allowed_categories: tuple[str, ...], us_only: bool = False):
    from macro_brain.persistence.store import recent_events

    _section(parent, title)
    events = recent_events(limit=120)
    filtered = [
        e for e in events
        if (
            e.get("source", "").startswith("rss:")
            or str(e.get("source", "")).startswith("newsapi:")
            or e.get("source") == "newsapi"
        )
        and str(e.get("category", "")).lower() in {c.lower() for c in allowed_categories}
    ]
    if us_only:
        us_tokens = ("fed", "treasury", "fomc", "us ", "u.s.", "america", "american",
                     "wall street", "nasdaq", "s&p", "sp500", "dow", "nyse",
                     "cpi", "pce", "nfp", "payroll", "jobless", "yield", "dollar")
        filtered = [
            e for e in filtered
            if any(tok in f"{e.get('headline', '')} {e.get('body', '')} {e.get('source', '')}".lower()
                   for tok in us_tokens)
            or str(e.get("category", "")).lower() in ("monetary", "institutional")
        ]
    for e in filtered[:15]:
        sent = e.get("sentiment") or 0.0
        impact = e.get("impact") or 0.0
        sc = GREEN if sent > 0.2 else (RED if sent < -0.2 else DIM2)
        src = str(e.get("source", "?")).replace("rss:", "").replace("newsapi:", "")[:14]
        ca = str(e.get("category") or "?")[:10].upper()
        hl = (e.get("headline") or "").strip()
        age = _fmt_age(e.get("ts", ""))
        row = _clickable_bg_row(parent, open_fn=(lambda ev=e: _open_event_link(ev)) if _event_link(e) else None)
        row.pack(fill="x")
        tk.Label(row, text=f"{age:<4}", font=(FONT, 7), fg=DIM, bg=row.cget("bg"),
                 width=5, anchor="w").pack(side="left")
        tk.Label(row, text=f"[{ca:<10}]", font=(FONT, 7, "bold"), fg=AMBER, bg=row.cget("bg"),
                 width=13, anchor="w").pack(side="left")
        tk.Label(row, text=src, font=(FONT, 7), fg=DIM2, bg=row.cget("bg"),
                 width=15, anchor="w").pack(side="left")
        tk.Label(row, text="█" * min(8, max(1, int(impact * 8))), font=(FONT, 6),
                 fg=AMBER, bg=row.cget("bg"), width=9, anchor="w").pack(side="left")
        tk.Label(row, text=f"{sent:+.2f}", font=(FONT, 7, "bold"), fg=sc, bg=row.cget("bg"),
                 width=7, anchor="w").pack(side="left")
        tk.Label(row, text=hl[:150], font=(FONT, 8), fg=WHITE, bg=row.cget("bg"),
                 anchor="w").pack(side="left", fill="x", expand=True)
        if _event_link(e):
            tk.Label(row, text="OPEN", font=(FONT, 6, "bold"), fg=AMBER,
                     bg=row.cget("bg")).pack(side="right", padx=4)
    if not filtered:
        tk.Label(parent, text="  (no news matching panel scope)",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)


def _render_institutional_flows(parent, title: str):
    from macro_brain.persistence.store import recent_events

    insider_events = recent_events(category="insider", limit=10)
    inst_events = recent_events(category="institutional", limit=10)
    left, right = _two_col(parent)

    _section(left, f"{title} · INSIDERS")
    if insider_events:
        shell = tk.Frame(left, bg=PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
        shell.pack(fill="x", padx=2, pady=2)
        for e in insider_events:
            age = _fmt_age(e.get("ts", ""))
            hl = (e.get("headline", "") or "").replace("INSIDER: ", "")
            row = _clickable_bg_row(shell, open_fn=(lambda ev=e: _open_event_link(ev)) if _event_link(e) else None)
            row.pack(fill="x", padx=2, pady=1)
            tk.Label(row, text=f" {age:<4}", font=(FONT, 7), fg=DIM, bg=row.cget("bg"),
                     width=6, anchor="w").pack(side="left")
            tk.Label(row, text=hl[:60], font=(FONT, 8), fg=WHITE, bg=row.cget("bg"),
                     anchor="w").pack(side="left", fill="x", expand=True)
            if _event_link(e):
                tk.Label(row, text="OPEN", font=(FONT, 6, "bold"), fg=AMBER,
                         bg=row.cget("bg")).pack(side="right", padx=4)
    else:
        tk.Label(left, text="  (no insider filings)",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)

    _section(right, f"{title} · 13F")
    if inst_events:
        shell = tk.Frame(right, bg=PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
        shell.pack(fill="x", padx=2, pady=2)
        for e in inst_events:
            age = _fmt_age(e.get("ts", ""))
            hl = (e.get("headline", "") or "").replace("13F FILING: ", "")
            row = _clickable_bg_row(shell, open_fn=(lambda ev=e: _open_event_link(ev)) if _event_link(e) else None)
            row.pack(fill="x", padx=2, pady=1)
            tk.Label(row, text=f" {age:<4}", font=(FONT, 7), fg=DIM, bg=row.cget("bg"),
                     width=6, anchor="w").pack(side="left")
            tk.Label(row, text=hl[:60], font=(FONT, 8), fg=WHITE, bg=row.cget("bg"),
                     anchor="w").pack(side="left", fill="x", expand=True)
            if _event_link(e):
                tk.Label(row, text="OPEN", font=(FONT, 6, "bold"), fg=AMBER,
                         bg=row.cget("bg")).pack(side="right", padx=4)
    else:
        tk.Label(right, text="  (no 13F filings)",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(pady=4)


# ── TAB RENDERERS ────────────────────────────────────────────

def _render_markets_tab(parent):
    """USA desk — rates, equities, macro, COT, institutions and US news."""
    _section(parent, "US DESK · MARKET NOW", pady_top=(0, 0))
    left, right = _two_col(parent)
    rates = _macro_map(["US13W", "US5Y", "US10Y", "US30Y",
                         "YIELD_SPREAD_10_2", "FED_RATE"])
    _section(left, "RATES · CURVE", pady_top=(0, 0))
    _grid(left, rates, [
        ("US13W",             "13W",     "{:.3f}%"),
        ("US5Y",              "5Y",      "{:.3f}%"),
        ("US10Y",             "10Y",     "{:.3f}%"),
        ("US30Y",             "30Y",     "{:.3f}%"),
        ("YIELD_SPREAD_10_2", "10Y-2Y",  "{:.3f}"),
        ("FED_RATE",          "FED",     "{:.2f}%"),
    ])

    fx = _macro_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY",
                      "DXY_BROAD"])
    _section(right, "DOLLAR · FX", pady_top=(0, 0))
    _grid(right, fx, [
        ("DXY",       "DXY",     "{:.2f}"),
        ("EUR_USD",   "EUR/USD", "{:.4f}"),
        ("USD_JPY",   "USD/JPY", "{:.2f}"),
        ("GBP_USD",   "GBP/USD", "{:.4f}"),
        ("USD_CNY",   "USD/CNY", "{:.4f}"),
        ("DXY_BROAD", "BROAD",   "{:.2f}"),
    ])

    left2, right2 = _two_col(parent)
    eq = _macro_map(["SP500", "NASDAQ", "VIX", "RUSSELL_RTY_NET_LONGS",
                     "GOLD", "WTI_OIL", "COPPER"])
    _section(left2, "EQUITIES · RISK", pady_top=(0, 0))
    _grid(left2, eq, [
        ("SP500",  "S&P 500", "{:,.0f}"),
        ("NASDAQ", "NASDAQ",  "{:,.0f}"),
        ("VIX",    "VIX",     "{:.2f}"),
        ("GOLD",   "GOLD",    "${:,.0f}"),
        ("WTI_OIL","WTI",     "${:.2f}"),
        ("COPPER", "COPPER",  "${:.3f}"),
    ])
    _grid(left2, eq, [
        ("RUSSELL_RTY_NET_LONGS", "RTY COT", "{:+,.0f}"),
    ])

    econ = _macro_map([
        "CPI_US", "CORE_CPI_US", "UNEMPLOYMENT_US", "NONFARM_PAYROLLS",
        "JOBLESS_CLAIMS", "MICHIGAN_SENTIMENT", "FED_BALANCE_SHEET",
        "HOUSING_STARTS", "INDUSTRIAL_PRODUCTION", "M2_MONEY_SUPPLY",
    ], n=30)
    _section(right2, "MACRO SNAPSHOT · FRED", pady_top=(0, 0))
    _grid(right2, econ, [
        ("CPI_US",             "CPI",          "{:.2f}"),
        ("CORE_CPI_US",        "CORE CPI",     "{:.2f}"),
        ("UNEMPLOYMENT_US",    "UNEMPLOY",     "{:.2f}%"),
        ("NONFARM_PAYROLLS",   "NFP",          "{:,.0f}"),
        ("JOBLESS_CLAIMS",     "JOBLESS",      "{:,.0f}"),
        ("MICHIGAN_SENTIMENT", "MICHIGAN",     "{:.1f}"),
        ("FED_BALANCE_SHEET",  "FED BAL",      "{:,.0f}"),
        ("M2_MONEY_SUPPLY",    "M2",           "{:,.0f}"),
    ])
    _grid(right2, econ, [
        ("HOUSING_STARTS",        "HOUSING",    "{:,.0f}"),
        ("INDUSTRIAL_PRODUCTION", "IND PROD",   "{:.2f}"),
    ])

    _section(parent, "US DESK · POSITIONING")
    _cot_matrix(parent, [
        ("DXY",       "DXY_NET_LONGS",       None,               None),
        ("UST 10Y",   "UST_10Y_NET_LONGS",   None,               None),
        ("UST 2Y",    "UST_2Y_NET_LONGS",    None,               None),
        ("SP500 ES",  "SP500_ES_NET_LONGS",  None,               None),
        ("NASDAQ NQ", "NASDAQ_NQ_NET_LONGS", None,               None),
        ("RTY",       "RUSSELL_RTY_NET_LONGS", None,             None),
        ("BTC CME",   "BTC_CME_NET_LONGS",   "BTC_CME_SWAP_NET", "BTC_CME_MM_NET"),
        ("GOLD",      "GOLD_NET_LONGS",      "GOLD_SWAP_NET",    "GOLD_MM_NET"),
        ("WTI",       "WTI_NET_LONGS",       "WTI_SWAP_NET",     "WTI_MM_NET"),
    ])

    _render_institutional_flows(parent, "INSTITUTIONAL FLOW")
    _render_calendar_list(parent, "CALENDAR · FED · LABOR · INFLATION", only_us=True)

    _render_news_list(parent, "US NEWSFLOW · FED · TREASURY · BANKS · STREET",
                      allowed_categories=("news", "monetary", "macro", "institutional", "geopolitics"),
                      us_only=True)
def _render_markets_tab_v2(parent):
    """USA desk reorganized into visual shells without changing data scope."""
    overview = _panel_shell(parent, pady=(0, 6))
    _section(overview, "US DESK · SNAPSHOT", pady_top=(0, 0))
    snapshot = _macro_map([
        "SP500", "US10Y", "DXY", "FED_RATE", "VIX", "CPI_US",
    ])
    _desk_banner(overview, snapshot, [
        ("SP500",    "S&P 500", "{:,.0f}"),
        ("US10Y",    "US10Y",   "{:.3f}%"),
        ("DXY",      "DXY",     "{:.2f}"),
        ("FED_RATE", "FED",     "{:.2f}%"),
        ("VIX",      "VIX",     "{:.2f}"),
        ("CPI_US",   "CPI",     "{:.2f}"),
    ])
    tk.Label(overview,
             text="  Price first, then curve and macro, then positioning, then institutional flow and news.",
             font=(FONT, 7), fg=DIM2, bg=PANEL, anchor="w").pack(fill="x", padx=2, pady=(0, 2))

    _section(parent, "US DESK · MARKET NOW", pady_top=(0, 0))
    market_shell = _panel_shell(parent, pady=(0, 6))
    left, right = _two_col(market_shell)
    rates = _macro_map(["US13W", "US5Y", "US10Y", "US30Y",
                        "YIELD_SPREAD_10_2", "FED_RATE"])
    _section(left, "RATES · CURVE", pady_top=(0, 0))
    _grid(left, rates, [
        ("US13W",             "13W",     "{:.3f}%"),
        ("US5Y",              "5Y",      "{:.3f}%"),
        ("US10Y",             "10Y",     "{:.3f}%"),
        ("US30Y",             "30Y",     "{:.3f}%"),
        ("YIELD_SPREAD_10_2", "10Y-2Y",  "{:.3f}"),
        ("FED_RATE",          "FED",     "{:.2f}%"),
    ])

    fx = _macro_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY",
                     "DXY_BROAD"])
    _section(right, "DOLLAR · FX", pady_top=(0, 0))
    _grid(right, fx, [
        ("DXY",       "DXY",     "{:.2f}"),
        ("EUR_USD",   "EUR/USD", "{:.4f}"),
        ("USD_JPY",   "USD/JPY", "{:.2f}"),
        ("GBP_USD",   "GBP/USD", "{:.4f}"),
        ("USD_CNY",   "USD/CNY", "{:.4f}"),
        ("DXY_BROAD", "BROAD",   "{:.2f}"),
    ])

    left2, right2 = _two_col(market_shell)
    eq = _macro_map(["SP500", "NASDAQ", "VIX", "RUSSELL_RTY_NET_LONGS",
                     "GOLD", "WTI_OIL", "COPPER"])
    _section(left2, "EQUITIES · RISK", pady_top=(0, 0))
    _grid(left2, eq, [
        ("SP500",  "S&P 500", "{:,.0f}"),
        ("NASDAQ", "NASDAQ",  "{:,.0f}"),
        ("VIX",    "VIX",     "{:.2f}"),
        ("GOLD",   "GOLD",    "${:,.0f}"),
        ("WTI_OIL","WTI",     "${:.2f}"),
        ("COPPER", "COPPER",  "${:.3f}"),
    ])
    _grid(left2, eq, [
        ("RUSSELL_RTY_NET_LONGS", "RTY COT", "{:+,.0f}"),
    ])

    econ = _macro_map([
        "CPI_US", "CORE_CPI_US", "UNEMPLOYMENT_US", "NONFARM_PAYROLLS",
        "JOBLESS_CLAIMS", "MICHIGAN_SENTIMENT", "FED_BALANCE_SHEET",
        "HOUSING_STARTS", "INDUSTRIAL_PRODUCTION", "M2_MONEY_SUPPLY",
    ], n=30)
    _section(right2, "MACRO SNAPSHOT · FRED", pady_top=(0, 0))
    _grid(right2, econ, [
        ("CPI_US",             "CPI",          "{:.2f}"),
        ("CORE_CPI_US",        "CORE CPI",     "{:.2f}"),
        ("UNEMPLOYMENT_US",    "UNEMPLOY",     "{:.2f}%"),
        ("NONFARM_PAYROLLS",   "NFP",          "{:,.0f}"),
        ("JOBLESS_CLAIMS",     "JOBLESS",      "{:,.0f}"),
        ("MICHIGAN_SENTIMENT", "MICHIGAN",     "{:.1f}"),
        ("FED_BALANCE_SHEET",  "FED BAL",      "{:,.0f}"),
        ("M2_MONEY_SUPPLY",    "M2",           "{:,.0f}"),
    ])
    _grid(right2, econ, [
        ("HOUSING_STARTS",        "HOUSING",    "{:,.0f}"),
        ("INDUSTRIAL_PRODUCTION", "IND PROD",   "{:.2f}"),
    ])

    _section(parent, "US DESK · POSITIONING")
    positioning_shell = _panel_shell(parent, pady=(0, 6))
    tk.Label(positioning_shell,
             text="  CFTC futures positioning for dollar, rates, index futures and key US-linked macro trades.",
             font=(FONT, 7), fg=DIM2, bg=PANEL, anchor="w").pack(fill="x", padx=2, pady=(0, 2))
    _cot_matrix(positioning_shell, [
        ("DXY",       "DXY_NET_LONGS",       None,               None),
        ("UST 10Y",   "UST_10Y_NET_LONGS",   None,               None),
        ("UST 2Y",    "UST_2Y_NET_LONGS",    None,               None),
        ("SP500 ES",  "SP500_ES_NET_LONGS",  None,               None),
        ("NASDAQ NQ", "NASDAQ_NQ_NET_LONGS", None,               None),
        ("RTY",       "RUSSELL_RTY_NET_LONGS", None,             None),
        ("BTC CME",   "BTC_CME_NET_LONGS",   "BTC_CME_SWAP_NET", "BTC_CME_MM_NET"),
        ("GOLD",      "GOLD_NET_LONGS",      "GOLD_SWAP_NET",    "GOLD_MM_NET"),
        ("WTI",       "WTI_NET_LONGS",       "WTI_SWAP_NET",     "WTI_MM_NET"),
    ])

    flow_shell = _panel_shell(parent, pady=(0, 6))
    _section(flow_shell, "US DESK · FLOW WATCH", pady_top=(0, 0))
    flow_left, flow_right = _two_col(flow_shell)
    _render_institutional_flows(flow_left, "INSTITUTIONAL FLOW")
    _render_calendar_list(flow_right, "CALENDAR · FED · LABOR · INFLATION", only_us=True)

    news_shell = _panel_shell(parent, pady=(0, 0))
    _render_news_list(news_shell, "US NEWSFLOW · FED · TREASURY · BANKS · STREET",
                      allowed_categories=("news", "monetary", "macro", "institutional", "geopolitics"),
                      us_only=True)


def _render_markets_tab_v3(parent):
    """USA desk rendered in batches to reduce time-to-content stalls."""
    _cancel_chunk_jobs(parent)

    def _render_overview() -> None:
        overview = _panel_shell(parent, pady=(0, 6))
        _section(overview, "US DESK Â· SNAPSHOT", pady_top=(0, 0))
        snapshot = _macro_map([
            "SP500", "US10Y", "DXY", "FED_RATE", "VIX", "CPI_US",
        ])
        _desk_banner(overview, snapshot, [
            ("SP500",    "S&P 500", "{:,.0f}"),
            ("US10Y",    "US10Y",   "{:.3f}%"),
            ("DXY",      "DXY",     "{:.2f}"),
            ("FED_RATE", "FED",     "{:.2f}%"),
            ("VIX",      "VIX",     "{:.2f}"),
            ("CPI_US",   "CPI",     "{:.2f}"),
        ])
        tk.Label(
            overview,
            text="  Price first, then curve and macro, then positioning, then institutional flow and news.",
            font=(FONT, 7), fg=DIM2, bg=PANEL, anchor="w",
        ).pack(fill="x", padx=2, pady=(0, 2))

    def _render_market_now() -> None:
        _section(parent, "US DESK Â· MARKET NOW", pady_top=(0, 0))
        market_shell = _panel_shell(parent, pady=(0, 6))
        left, right = _two_col(market_shell)
        rates = _macro_map(["US13W", "US5Y", "US10Y", "US30Y",
                            "YIELD_SPREAD_10_2", "FED_RATE"])
        _section(left, "RATES Â· CURVE", pady_top=(0, 0))
        _grid(left, rates, [
            ("US13W",             "13W",     "{:.3f}%"),
            ("US5Y",              "5Y",      "{:.3f}%"),
            ("US10Y",             "10Y",     "{:.3f}%"),
            ("US30Y",             "30Y",     "{:.3f}%"),
            ("YIELD_SPREAD_10_2", "10Y-2Y",  "{:.3f}"),
            ("FED_RATE",          "FED",     "{:.2f}%"),
        ])

        fx = _macro_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY",
                         "DXY_BROAD"])
        _section(right, "DOLLAR Â· FX", pady_top=(0, 0))
        _grid(right, fx, [
            ("DXY",       "DXY",     "{:.2f}"),
            ("EUR_USD",   "EUR/USD", "{:.4f}"),
            ("USD_JPY",   "USD/JPY", "{:.2f}"),
            ("GBP_USD",   "GBP/USD", "{:.4f}"),
            ("USD_CNY",   "USD/CNY", "{:.4f}"),
            ("DXY_BROAD", "BROAD",   "{:.2f}"),
        ])

        left2, right2 = _two_col(market_shell)
        eq = _macro_map(["SP500", "NASDAQ", "VIX", "RUSSELL_RTY_NET_LONGS",
                         "GOLD", "WTI_OIL", "COPPER"])
        _section(left2, "EQUITIES Â· RISK", pady_top=(0, 0))
        _grid(left2, eq, [
            ("SP500",  "S&P 500", "{:,.0f}"),
            ("NASDAQ", "NASDAQ",  "{:,.0f}"),
            ("VIX",    "VIX",     "{:.2f}"),
            ("GOLD",   "GOLD",    "${:,.0f}"),
            ("WTI_OIL","WTI",     "${:.2f}"),
            ("COPPER", "COPPER",  "${:.3f}"),
        ])
        _grid(left2, eq, [
            ("RUSSELL_RTY_NET_LONGS", "RTY COT", "{:+,.0f}"),
        ])

        econ = _macro_map([
            "CPI_US", "CORE_CPI_US", "UNEMPLOYMENT_US", "NONFARM_PAYROLLS",
            "JOBLESS_CLAIMS", "MICHIGAN_SENTIMENT", "FED_BALANCE_SHEET",
            "HOUSING_STARTS", "INDUSTRIAL_PRODUCTION", "M2_MONEY_SUPPLY",
        ], n=30)
        _section(right2, "MACRO SNAPSHOT Â· FRED", pady_top=(0, 0))
        _grid(right2, econ, [
            ("CPI_US",             "CPI",          "{:.2f}"),
            ("CORE_CPI_US",        "CORE CPI",     "{:.2f}"),
            ("UNEMPLOYMENT_US",    "UNEMPLOY",     "{:.2f}%"),
            ("NONFARM_PAYROLLS",   "NFP",          "{:,.0f}"),
            ("JOBLESS_CLAIMS",     "JOBLESS",      "{:,.0f}"),
            ("MICHIGAN_SENTIMENT", "MICHIGAN",     "{:.1f}"),
            ("FED_BALANCE_SHEET",  "FED BAL",      "{:,.0f}"),
            ("M2_MONEY_SUPPLY",    "M2",           "{:,.0f}"),
        ])
        _grid(right2, econ, [
            ("HOUSING_STARTS",        "HOUSING",    "{:,.0f}"),
            ("INDUSTRIAL_PRODUCTION", "IND PROD",   "{:.2f}"),
        ])

    def _render_positioning() -> None:
        _section(parent, "US DESK Â· POSITIONING")
        positioning_shell = _panel_shell(parent, pady=(0, 6))
        tk.Label(
            positioning_shell,
            text="  CFTC futures positioning for dollar, rates, index futures and key US-linked macro trades.",
            font=(FONT, 7), fg=DIM2, bg=PANEL, anchor="w",
        ).pack(fill="x", padx=2, pady=(0, 2))
        _cot_matrix(positioning_shell, [
            ("DXY",       "DXY_NET_LONGS",       None,               None),
            ("UST 10Y",   "UST_10Y_NET_LONGS",   None,               None),
            ("UST 2Y",    "UST_2Y_NET_LONGS",    None,               None),
            ("SP500 ES",  "SP500_ES_NET_LONGS",  None,               None),
            ("NASDAQ NQ", "NASDAQ_NQ_NET_LONGS", None,               None),
            ("RTY",       "RUSSELL_RTY_NET_LONGS", None,             None),
            ("BTC CME",   "BTC_CME_NET_LONGS",   "BTC_CME_SWAP_NET", "BTC_CME_MM_NET"),
            ("GOLD",      "GOLD_NET_LONGS",      "GOLD_SWAP_NET",    "GOLD_MM_NET"),
            ("WTI",       "WTI_NET_LONGS",       "WTI_SWAP_NET",     "WTI_MM_NET"),
        ])

    def _render_flow_watch() -> None:
        flow_shell = _panel_shell(parent, pady=(0, 6))
        _section(flow_shell, "US DESK Â· FLOW WATCH", pady_top=(0, 0))
        flow_left, flow_right = _two_col(flow_shell)
        _render_institutional_flows(flow_left, "INSTITUTIONAL FLOW")
        _render_calendar_list(flow_right, "CALENDAR Â· FED Â· LABOR Â· INFLATION", only_us=True)

    def _render_news() -> None:
        news_shell = _panel_shell(parent, pady=(0, 0))
        _render_news_list(
            news_shell,
            "US NEWSFLOW Â· FED Â· TREASURY Â· BANKS Â· STREET",
            allowed_categories=("news", "monetary", "macro", "institutional", "geopolitics"),
            us_only=True,
        )

    _run_chunked(
        parent,
        [
            _render_overview,
            _render_market_now,
            _render_positioning,
            _render_flow_watch,
            _render_news,
        ],
        metric_name="content.macro_brain.EUA.full",
    )


def _render_markets_tab_v4(parent):
    """USA desk rendered in finer batches to shorten time-to-content."""
    _cancel_chunk_jobs(parent)

    def _render_overview() -> None:
        overview = _panel_shell(parent, pady=(0, 6))
        _section(overview, "US DESK SNAPSHOT", pady_top=(0, 0))
        snapshot = _macro_map([
            "SP500", "US10Y", "DXY", "FED_RATE", "VIX", "CPI_US",
        ])
        _desk_banner(overview, snapshot, [
            ("SP500",    "S&P 500", "{:,.0f}"),
            ("US10Y",    "US10Y",   "{:.3f}%"),
            ("DXY",      "DXY",     "{:.2f}"),
            ("FED_RATE", "FED",     "{:.2f}%"),
            ("VIX",      "VIX",     "{:.2f}"),
            ("CPI_US",   "CPI",     "{:.2f}"),
        ])
        tk.Label(
            overview,
            text="  Price first, then curve and macro, then positioning, then flow, calendar and news.",
            font=(FONT, 7), fg=DIM2, bg=PANEL, anchor="w",
        ).pack(fill="x", padx=2, pady=(0, 2))

    def _render_market_now() -> None:
        _section(parent, "US DESK MARKET NOW", pady_top=(0, 0))
        market_shell = _panel_shell(parent, pady=(0, 6))
        left, right = _two_col(market_shell)
        rates = _macro_map(["US13W", "US5Y", "US10Y", "US30Y",
                            "YIELD_SPREAD_10_2", "FED_RATE"])
        _section(left, "RATES CURVE", pady_top=(0, 0))
        _grid(left, rates, [
            ("US13W",             "13W",     "{:.3f}%"),
            ("US5Y",              "5Y",      "{:.3f}%"),
            ("US10Y",             "10Y",     "{:.3f}%"),
            ("US30Y",             "30Y",     "{:.3f}%"),
            ("YIELD_SPREAD_10_2", "10Y-2Y",  "{:.3f}"),
            ("FED_RATE",          "FED",     "{:.2f}%"),
        ])

        fx = _macro_map(["DXY", "EUR_USD", "USD_JPY", "GBP_USD", "USD_CNY", "DXY_BROAD"])
        _section(right, "DOLLAR FX", pady_top=(0, 0))
        _grid(right, fx, [
            ("DXY",       "DXY",     "{:.2f}"),
            ("EUR_USD",   "EUR/USD", "{:.4f}"),
            ("USD_JPY",   "USD/JPY", "{:.2f}"),
            ("GBP_USD",   "GBP/USD", "{:.4f}"),
            ("USD_CNY",   "USD/CNY", "{:.4f}"),
            ("DXY_BROAD", "BROAD",   "{:.2f}"),
        ])

        left2, right2 = _two_col(market_shell)
        eq = _macro_map(["SP500", "NASDAQ", "VIX", "RUSSELL_RTY_NET_LONGS",
                         "GOLD", "WTI_OIL", "COPPER"])
        _section(left2, "EQUITIES RISK", pady_top=(0, 0))
        _grid(left2, eq, [
            ("SP500",  "S&P 500", "{:,.0f}"),
            ("NASDAQ", "NASDAQ",  "{:,.0f}"),
            ("VIX",    "VIX",     "{:.2f}"),
            ("GOLD",   "GOLD",    "${:,.0f}"),
            ("WTI_OIL","WTI",     "${:.2f}"),
            ("COPPER", "COPPER",  "${:.3f}"),
        ])
        _grid(left2, eq, [
            ("RUSSELL_RTY_NET_LONGS", "RTY COT", "{:+,.0f}"),
        ])

        econ = _macro_map([
            "CPI_US", "CORE_CPI_US", "UNEMPLOYMENT_US", "NONFARM_PAYROLLS",
            "JOBLESS_CLAIMS", "MICHIGAN_SENTIMENT", "FED_BALANCE_SHEET",
            "HOUSING_STARTS", "INDUSTRIAL_PRODUCTION", "M2_MONEY_SUPPLY",
        ], n=30)
        _section(right2, "MACRO SNAPSHOT FRED", pady_top=(0, 0))
        _grid(right2, econ, [
            ("CPI_US",             "CPI",          "{:.2f}"),
            ("CORE_CPI_US",        "CORE CPI",     "{:.2f}"),
            ("UNEMPLOYMENT_US",    "UNEMPLOY",     "{:.2f}%"),
            ("NONFARM_PAYROLLS",   "NFP",          "{:,.0f}"),
            ("JOBLESS_CLAIMS",     "JOBLESS",      "{:,.0f}"),
            ("MICHIGAN_SENTIMENT", "MICHIGAN",     "{:.1f}"),
            ("FED_BALANCE_SHEET",  "FED BAL",      "{:,.0f}"),
            ("M2_MONEY_SUPPLY",    "M2",           "{:,.0f}"),
        ])
        _grid(right2, econ, [
            ("HOUSING_STARTS",        "HOUSING",    "{:,.0f}"),
            ("INDUSTRIAL_PRODUCTION", "IND PROD",   "{:.2f}"),
        ])

    def _render_positioning() -> None:
        _section(parent, "US DESK POSITIONING")
        positioning_shell = _panel_shell(parent, pady=(0, 6))
        tk.Label(
            positioning_shell,
            text="  CFTC futures positioning for dollar, rates, index futures and key US-linked macro trades.",
            font=(FONT, 7), fg=DIM2, bg=PANEL, anchor="w",
        ).pack(fill="x", padx=2, pady=(0, 2))
        _cot_matrix(positioning_shell, [
            ("DXY",       "DXY_NET_LONGS",       None,               None),
            ("UST 10Y",   "UST_10Y_NET_LONGS",   None,               None),
            ("UST 2Y",    "UST_2Y_NET_LONGS",    None,               None),
            ("SP500 ES",  "SP500_ES_NET_LONGS",  None,               None),
            ("NASDAQ NQ", "NASDAQ_NQ_NET_LONGS", None,               None),
            ("RTY",       "RUSSELL_RTY_NET_LONGS", None,             None),
            ("BTC CME",   "BTC_CME_NET_LONGS",   "BTC_CME_SWAP_NET", "BTC_CME_MM_NET"),
            ("GOLD",      "GOLD_NET_LONGS",      "GOLD_SWAP_NET",    "GOLD_MM_NET"),
            ("WTI",       "WTI_NET_LONGS",       "WTI_SWAP_NET",     "WTI_MM_NET"),
        ])

    def _render_flow() -> None:
        flow_shell = _panel_shell(parent, pady=(0, 6))
        _section(flow_shell, "US DESK FLOW WATCH", pady_top=(0, 0))
        flow_left, flow_right = _two_col(flow_shell)
        parent._macro_eua_v4_flow_right = flow_right
        _render_institutional_flows(flow_left, "INSTITUTIONAL FLOW")

    def _render_calendar() -> None:
        flow_right = getattr(parent, "_macro_eua_v4_flow_right", None)
        if flow_right is None:
            return
        _render_calendar_list(flow_right, "CALENDAR FED LABOR INFLATION", only_us=True)

    def _render_news() -> None:
        news_shell = _panel_shell(parent, pady=(0, 0))
        _render_news_list(
            news_shell,
            "US NEWSFLOW FED TREASURY BANKS STREET",
            allowed_categories=("news", "monetary", "macro", "institutional", "geopolitics"),
            us_only=True,
        )

    _run_chunked(
        parent,
        [
            _render_overview,
            _render_market_now,
            _render_positioning,
            _render_flow,
            _render_calendar,
            _render_news,
        ],
        metric_name="content.macro_brain.EUA.full",
    )


def _render_br_tab(parent):
    """Brazilian equities + BRL forex."""
    br_indices = _macro_map([
        "IBOVESPA", "BR_SMALL_CAPS", "BR_REAL_ESTATE",
        "USD_BRL", "EUR_BRL",
    ], n=30)
    _section(parent, "BR INDICES · FOREX", pady_top=(0, 0))
    _grid(parent, br_indices, [
        ("IBOVESPA",       "IBOV",       "{:,.0f}"),
        ("BR_SMALL_CAPS",  "SMALL CAPS", "{:,.2f}"),
        ("BR_REAL_ESTATE", "IFIX",       "{:,.2f}"),
        ("USD_BRL",        "USD/BRL",    "{:.4f}"),
        ("EUR_BRL",        "EUR/BRL",    "{:.4f}"),
    ])

    stocks1 = _macro_map([
        "PETR4_PETROBRAS", "VALE3_VALE", "ITUB4_ITAU", "BBDC4_BRADESCO",
        "BBAS3_BB", "ABEV3_AMBEV", "B3SA3_B3", "WEGE3_WEG",
    ], n=30)
    _section(parent, "B3 TOP STOCKS · BANCOS · PETRO · MINERADORAS")
    _grid(parent, stocks1, [
        ("PETR4_PETROBRAS", "PETR4", "R${:.2f}"),
        ("VALE3_VALE",      "VALE3", "R${:.2f}"),
        ("ITUB4_ITAU",      "ITUB4", "R${:.2f}"),
        ("BBDC4_BRADESCO",  "BBDC4", "R${:.2f}"),
        ("BBAS3_BB",        "BBAS3", "R${:.2f}"),
        ("ABEV3_AMBEV",     "ABEV3", "R${:.2f}"),
        ("B3SA3_B3",        "B3SA3", "R${:.2f}"),
        ("WEGE3_WEG",       "WEGE3", "R${:.2f}"),
    ])

    stocks2 = _macro_map([
        "RENT3_LOCALIZA", "PRIO3_PRIO", "BRAP4_BRADESPAR",
        "SUZB3_SUZANO", "JBSS3_JBS", "KLBN11_KLABIN",
        "ELET3_ELETROBRAS", "MGLU3_MAGALU",
    ], n=30)
    _grid(parent, stocks2, [
        ("RENT3_LOCALIZA",   "RENT3",  "R${:.2f}"),
        ("PRIO3_PRIO",       "PRIO3",  "R${:.2f}"),
        ("BRAP4_BRADESPAR",  "BRAP4",  "R${:.2f}"),
        ("SUZB3_SUZANO",     "SUZB3",  "R${:.2f}"),
        ("JBSS3_JBS",        "JBSS3",  "R${:.2f}"),
        ("KLBN11_KLABIN",    "KLBN11", "R${:.2f}"),
        ("ELET3_ELETROBRAS", "ELET3",  "R${:.2f}"),
        ("MGLU3_MAGALU",     "MGLU3",  "R${:.2f}"),
    ])

    adrs = _macro_map(["VALE_ADR", "ITUB_ADR", "PBR_ADR", "BBD_ADR"], n=30)
    _section(parent, "BRAZILIAN ADRs · US-LISTED")
    _grid(parent, adrs, [
        ("VALE_ADR", "VALE NYSE", "${:.2f}"),
        ("ITUB_ADR", "ITUB NYSE", "${:.2f}"),
        ("PBR_ADR",  "PBR NYSE",  "${:.2f}"),
        ("BBD_ADR",  "BBD NYSE",  "${:.2f}"),
    ])


def _render_crypto_tab(parent):
    """Crypto deep — organizado por rede."""
    _section(parent, "BTC · NETWORK · ON-CHAIN · POSITIONING",
             pady_top=(0, 0))
    btc = _macro_map([
        "BTC_SPOT", "BTC_DOMINANCE", "BTC_HASH_RATE", "BTC_DIFFICULTY",
        "BTC_BLOCK_HEIGHT", "BTC_MEMPOOL_COUNT", "BTC_FEE_FASTEST_SATVB",
        "BTC_24H_TX_COUNT",
    ], n=30)
    _grid(parent, btc, [
        ("BTC_SPOT",              "PRICE",      "${:,.0f}"),
        ("BTC_DOMINANCE",         "DOMINANCE",  "{:.2f}%"),
        ("BTC_HASH_RATE",         "HASHRATE",   "{:,.0f}"),
        ("BTC_DIFFICULTY",        "DIFFICULTY", "{:,.0f}"),
        ("BTC_BLOCK_HEIGHT",      "BLOCK",      "{:,.0f}"),
        ("BTC_MEMPOOL_COUNT",     "MEMPOOL",    "{:,.0f}"),
        ("BTC_FEE_FASTEST_SATVB", "FEE sat/vB", "{:.0f}"),
        ("BTC_24H_TX_COUNT",      "24H TX",     "{:,.0f}"),
    ])
    btc_extra = _macro_map([
        "BTC_CME_NET_LONGS", "BTC_CME_SWAP_NET", "BTC_CME_MM_NET",
    ], n=12)
    _grid(parent, btc_extra, [
        ("BTC_CME_NET_LONGS", "BTC CME NC NET", "{:+,.0f}"),
        ("BTC_CME_SWAP_NET",  "BTC CME BANKS",  "{:+,.0f}"),
        ("BTC_CME_MM_NET",    "BTC CME FUNDS",  "{:+,.0f}"),
    ])

    _section(parent, "ETH · ETHEREUM · DEFI DOMINANT")
    eth = _macro_map(["ETH_SPOT", "DEFI_ETHEREUM_TVL"], n=30)
    _grid(parent, eth, [
        ("ETH_SPOT",          "ETH PRICE",    "${:,.1f}"),
        ("DEFI_ETHEREUM_TVL", "ETH DEFI TVL", "${:,.0f}"),
    ])

    _section(parent, "SOL · SOLANA · HIGH THROUGHPUT")
    sol = _macro_map(["SOL_SPOT", "DEFI_SOLANA_TVL"], n=30)
    _grid(parent, sol, [
        ("SOL_SPOT",        "SOL PRICE",    "${:.2f}"),
        ("DEFI_SOLANA_TVL", "SOL DEFI TVL", "${:,.0f}"),
    ])
    _render_bot_slots(parent, network="SOL")

    _section(parent, "HYPE · HYPERLIQUID · PERPS")
    hl = _macro_map([
        "HL_TOTAL_OI", "HL_BTC_PRICE", "HL_BTC_OI_USD", "HL_BTC_FUNDING",
        "HL_ETH_OI_USD", "HL_ETH_FUNDING", "HL_HYPE_PRICE",
        "HL_HYPE_OI_USD",
    ], n=12)
    _grid(parent, hl, [
        ("HL_TOTAL_OI",    "TOTAL OI",    "${:,.0f}"),
        ("HL_BTC_PRICE",   "BTC PERP",    "${:,.0f}"),
        ("HL_BTC_OI_USD",  "BTC OI",      "${:,.0f}"),
        ("HL_BTC_FUNDING", "BTC FUNDING", "{:+.4f}%"),
        ("HL_ETH_OI_USD",  "ETH OI",      "${:,.0f}"),
        ("HL_ETH_FUNDING", "ETH FUNDING", "{:+.4f}%"),
        ("HL_HYPE_PRICE",  "HYPE TOKEN",  "${:.2f}"),
        ("HL_HYPE_OI_USD", "HYPE OI",     "${:,.0f}"),
    ])
    _render_bot_slots(parent, network="HYPE")

    _section(parent, "CROSS-CHAIN DEFI · TVL PER NETWORK")
    defi = _macro_map([
        "DEFI_TOTAL_TVL", "DEFI_ETHEREUM_TVL", "DEFI_SOLANA_TVL",
        "DEFI_BSC_TVL", "DEFI_BASE_TVL", "DEFI_ARBITRUM_TVL",
        "DEFI_TRON_TVL", "DEFI_HYPERLIQUID_TVL",
    ], n=30)
    _grid(parent, defi, [
        ("DEFI_TOTAL_TVL",       "TOTAL",    "${:,.0f}"),
        ("DEFI_ETHEREUM_TVL",    "ETH",      "${:,.0f}"),
        ("DEFI_SOLANA_TVL",      "SOL",      "${:,.0f}"),
        ("DEFI_BSC_TVL",         "BSC",      "${:,.0f}"),
        ("DEFI_BASE_TVL",        "BASE",     "${:,.0f}"),
        ("DEFI_ARBITRUM_TVL",    "ARB",      "${:,.0f}"),
        ("DEFI_TRON_TVL",        "TRON",     "${:,.0f}"),
        ("DEFI_HYPERLIQUID_TVL", "HYPE L1",  "${:,.0f}"),
    ])


def _render_insights_tab(parent):
    """Derived cross-asset analytics only — no raw US desk feeds here."""

    try:
        from macro_brain.ml_engine.analytics import compute_all
        insights = compute_all()
    except Exception:
        insights = []
    if insights:
        _section(parent, "MACRO ANALYTICS · DERIVED INSIGHTS",
                 pady_top=(0, 0))
        sig_c = {"bullish": GREEN, "bearish": RED,
                 "warning": AMBER, "neutral": DIM2}
        row = tk.Frame(parent, bg=BG); row.pack(fill="x", pady=PAD_ROW // 2)
        for ins in insights:
            sc = sig_c.get(ins.signal, WHITE)
            card = tk.Frame(row, bg=PANEL,
                            highlightbackground=BORDER, highlightthickness=1)
            card.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
            _attach_hover(card)
            tk.Label(card, text=ins.name.upper(), font=(FONT, 6, "bold"),
                     fg=DIM, bg=PANEL, anchor="w").pack(
                         fill="x", padx=PAD_TILE_INNER, pady=(2, 0))
            tk.Label(card, text=str(ins.value), font=(FONT, 9, "bold"),
                     fg=WHITE, bg=PANEL, anchor="w").pack(
                         fill="x", padx=PAD_TILE_INNER)
            tk.Label(card, text=ins.signal.upper(), font=(FONT, 7, "bold"),
                     fg=sc, bg=PANEL, anchor="w").pack(
                         fill="x", padx=PAD_TILE_INNER)
            tk.Label(card, text=ins.detail[:60], font=(FONT, 7),
                     fg=DIM2, bg=PANEL, anchor="w", wraplength=180,
                     justify="left").pack(
                         fill="x", padx=PAD_TILE_INNER, pady=(0, 2))
    _section(parent, "ANALYTICS SCOPE")
    tk.Label(parent,
             text="  Raw US calendar, news, COT and institutional flow moved to [1] EUA.",
             font=(FONT, 8), fg=DIM2, bg=BG, anchor="w").pack(fill="x", padx=6)


def _render_analysis_tab(parent):
    """Cross-market macro board after US desk extraction to EUA."""
    left, right = _two_col(parent)

    global_mkts = _macro_map([
        "DAX", "FTSE", "NIKKEI", "HSI",
        "GOLD", "SILVER", "WTI_OIL", "BRENT_OIL",
        "COPPER", "NAT_GAS",
    ], n=30)
    _section(left, "GLOBAL EQUITIES · COMMODITIES", pady_top=(0, 0))
    _grid(left, global_mkts, [
        ("DAX",       "DAX",     "{:,.0f}"),
        ("FTSE",      "FTSE",    "{:,.0f}"),
        ("NIKKEI",    "NIKKEI",  "{:,.0f}"),
        ("HSI",       "HSI",     "{:,.0f}"),
        ("GOLD",      "GOLD",    "${:,.0f}"),
        ("WTI_OIL",   "WTI",     "${:.2f}"),
        ("BRENT_OIL", "BRENT",   "${:.2f}"),
    ])
    _grid(left, global_mkts, [
        ("SILVER",  "SILVER",  "${:.2f}"),
        ("COPPER",  "COPPER",  "${:.3f}"),
        ("NAT_GAS", "NAT GAS", "${:.3f}"),
    ])

    cross = _macro_map([
        "BTC_DOMINANCE", "TOTAL_CRYPTO_MCAP", "TOTAL_CRYPTO_VOL_24H",
        "CRYPTO_FEAR_GREED", "DEFI_TOTAL_TVL", "DEFI_ETHEREUM_TVL",
        "DEFI_SOLANA_TVL", "DEFI_BASE_TVL",
    ], n=30)
    _section(right, "CROSS-ASSET · CRYPTO MACRO", pady_top=(0, 0))
    _grid(right, cross, [
        ("BTC_DOMINANCE",     "BTC DOM",  "{:.2f}%"),
        ("TOTAL_CRYPTO_MCAP", "MKT CAP",  "${:,.0f}"),
        ("TOTAL_CRYPTO_VOL_24H", "VOL 24H", "${:,.0f}"),
        ("CRYPTO_FEAR_GREED", "F&G",      "{:.0f}/100"),
        ("DEFI_TOTAL_TVL",    "DEFI TVL", "${:,.0f}"),
        ("DEFI_ETHEREUM_TVL", "ETH TVL",  "${:,.0f}"),
        ("DEFI_SOLANA_TVL",   "SOL TVL",  "${:,.0f}"),
        ("DEFI_BASE_TVL",     "BASE TVL", "${:,.0f}"),
    ])

    _section(parent, "GLOBAL POSITIONING · CFTC")
    _cot_matrix(parent, [
        ("EUR FX",    "EUR_FX_NET_LONGS",   None,               None),
        ("JPY FX",    "JPY_FX_NET_LONGS",   None,               None),
        ("GBP FX",    "GBP_FX_NET_LONGS",   None,               None),
        ("GOLD",      "GOLD_NET_LONGS",     "GOLD_SWAP_NET",    "GOLD_MM_NET"),
        ("SILVER",    "SILVER_NET_LONGS",   "SILVER_SWAP_NET",  "SILVER_MM_NET"),
        ("WTI",       "WTI_NET_LONGS",      "WTI_SWAP_NET",     "WTI_MM_NET"),
        ("BRENT",     None,                 "BRENT_SWAP_NET",   "BRENT_MM_NET"),
        ("COPPER",    None,                 "COPPER_SWAP_NET",  "COPPER_MM_NET"),
        ("ETH CME",   None,                 "ETH_CME_SWAP_NET", "ETH_CME_MM_NET"),
    ])


def _render_network_tab(parent):
    """BTC on-chain — Portal | VPS — Processes."""
    onchain = _macro_map([
        "BTC_HASH_RATE", "BTC_DIFFICULTY", "BTC_BLOCK_HEIGHT",
        "BTC_MEMPOOL_COUNT", "BTC_FEE_FASTEST_SATVB",
        "BTC_24H_TX_COUNT", "BTC_24H_MINER_REVENUE_USD",
        "BTC_24H_TRADE_VOLUME_USD",
    ], n=30)
    _section(parent, "BTC ON-CHAIN · NETWORK STATE", pady_top=(0, 0))
    _grid(parent, onchain, [
        ("BTC_HASH_RATE",             "HASHRATE",   "{:,.0f}"),
        ("BTC_DIFFICULTY",            "DIFF",       "{:,.0f}"),
        ("BTC_BLOCK_HEIGHT",          "BLOCK",      "{:,.0f}"),
        ("BTC_MEMPOOL_COUNT",         "MEMPOOL",    "{:,.0f}"),
        ("BTC_FEE_FASTEST_SATVB",     "FEE sat/vB", "{:.0f}"),
        ("BTC_24H_TX_COUNT",          "24H TX",     "{:,.0f}"),
        ("BTC_24H_MINER_REVENUE_USD", "MINER REV",  "${:,.0f}"),
        ("BTC_24H_TRADE_VOLUME_USD",  "VOL USD",    "${:,.0f}"),
    ])

    adv = _macro_map([
        "BTC_FEE_30MIN_SATVB", "BTC_FEE_1H_SATVB", "BTC_FEE_ECONOMY_SATVB",
        "BTC_MEMPOOL_VSIZE", "BTC_AVG_BLOCK_TIME_MIN",
        "BTC_24H_FEES_BTC", "BTC_24H_MINED",
    ], n=30)
    _section(parent, "BTC ADVANCED · FEES · BLOCK TIME")
    _grid(parent, adv, [
        ("BTC_FEE_30MIN_SATVB",    "30MIN FEE",  "{:.0f}"),
        ("BTC_FEE_1H_SATVB",       "1H FEE",     "{:.0f}"),
        ("BTC_FEE_ECONOMY_SATVB",  "ECON FEE",   "{:.0f}"),
        ("BTC_MEMPOOL_VSIZE",      "MP VSIZE",   "{:,.0f}"),
        ("BTC_AVG_BLOCK_TIME_MIN", "BLOCK TIME", "{:.1f}"),
        ("BTC_24H_FEES_BTC",       "24H FEES",   "{:.2f}"),
        ("BTC_24H_MINED",          "24H MINED",  "{:.0f}"),
    ])

    left, right = _two_col(parent)

    _section(left, "ENGINES PORTAL · PROCESS MONITOR")
    try:
        from core.ops.proc import list_procs
        procs = list_procs()
    except Exception:
        procs = []
    running = [p for p in procs if p.get("alive") or
               p.get("status") == "running"]
    finished = [p for p in procs if not p.get("alive") and
                p.get("status") == "finished"]

    stat_row = tk.Frame(left, bg=BG); stat_row.pack(fill="x",
                                                    pady=PAD_ROW // 2)
    for label, val in [
        ("ACTIVE",   f"{len(running)}"),
        ("FINISHED", f"{len(finished)}"),
        ("TOTAL",    f"{len(procs)}"),
    ]:
        box = tk.Frame(stat_row, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1,
                       padx=10, pady=4)
        box.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
        _attach_hover(box)
        tk.Label(box, text=label, font=(FONT, 6, "bold"),
                 fg=DIM, bg=PANEL).pack()
        tk.Label(box, text=val, font=(FONT, 14, "bold"),
                 fg=WHITE, bg=PANEL).pack()

    vps_online, vps_detail = _read_vps_status()

    _section(right, "VPS STATUS")
    vps_c = GREEN if vps_online else RED
    vps_box = tk.Frame(right, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1,
                       padx=12, pady=10)
    vps_box.pack(fill="x", padx=2, pady=2)
    _attach_hover(vps_box)
    vps_status_lbl = tk.Label(vps_box, text="● ONLINE" if vps_online else "○ OFFLINE",
                              font=(FONT, 14, "bold"), fg=vps_c, bg=PANEL)
    vps_status_lbl.pack(anchor="w")
    vps_detail_lbl = tk.Label(vps_box, text=vps_detail, font=(FONT, 8),
                              fg=WHITE, bg=PANEL)
    vps_detail_lbl.pack(anchor="w")
    tk.Label(vps_box, text="SSH connect test · port 22",
             font=(FONT, 6), fg=DIM, bg=PANEL).pack(anchor="w",
                                                     pady=(2, 0))
    if vps_detail == "checking...":
        def _refresh_vps_box() -> None:
            try:
                if not vps_box.winfo_exists():
                    return
            except Exception:
                return
            latest_online, latest_detail = _read_vps_status()
            if latest_detail == "checking...":
                vps_box.after(250, _refresh_vps_box)
                return
            latest_color = GREEN if latest_online else RED
            vps_status_lbl.configure(
                text="● ONLINE" if latest_online else "○ OFFLINE",
                fg=latest_color,
            )
            vps_detail_lbl.configure(text=latest_detail)

        vps_box.after(250, _refresh_vps_box)

    if procs:
        _section(parent, "PROCESSES · ACTIVE + RECENT")
        hdr = tk.Frame(parent, bg=BG); hdr.pack(fill="x", pady=(0, 1))
        for txt, w in [("", 3), ("ENGINE", 16), ("PID", 12),
                       ("STATUS", 10), ("STARTED", 15)]:
            tk.Label(hdr, text=txt, font=(FONT, 6, "bold"), fg=DIM,
                     bg=BG, width=w, anchor="w").pack(side="left")

        for p in procs[:15]:
            engine = (p.get("engine") or "?").upper()
            pid = p.get("pid") or "?"
            status = p.get("status", "?")
            alive = p.get("alive", False)
            sc = GREEN if alive else DIM
            row = tk.Frame(parent, bg=BG); row.pack(fill="x")
            tk.Label(row, text=f" {'●' if alive else '○'}",
                     font=(FONT, 8, "bold"), fg=sc, bg=BG,
                     width=3).pack(side="left")
            tk.Label(row, text=f"{engine:<14}", font=(FONT, 8, "bold"),
                     fg=WHITE, bg=BG, width=16,
                     anchor="w").pack(side="left")
            tk.Label(row, text=f"{pid}", font=(FONT, 7),
                     fg=DIM, bg=BG, width=12,
                     anchor="w").pack(side="left")
            tk.Label(row, text=status.upper(), font=(FONT, 7, "bold"),
                     fg=sc, bg=BG, width=10,
                     anchor="w").pack(side="left")
            started = p.get("started", "")
            tk.Label(row,
                     text=f"{_fmt_age(started)} ago" if started else "",
                     font=(FONT, 7), fg=DIM, bg=BG, anchor="w").pack(
                         side="left", fill="x", expand=True)



def _render_network_tab_v2(parent):
    """BTC on-chain and ops tab rendered in batches."""
    _cancel_chunk_jobs(parent)

    def _render_onchain() -> None:
        onchain = _macro_map([
            "BTC_HASH_RATE", "BTC_DIFFICULTY", "BTC_BLOCK_HEIGHT",
            "BTC_MEMPOOL_COUNT", "BTC_FEE_FASTEST_SATVB",
            "BTC_24H_TX_COUNT", "BTC_24H_MINER_REVENUE_USD",
            "BTC_24H_TRADE_VOLUME_USD",
        ], n=30)
        _section(parent, "BTC ON-CHAIN Â· NETWORK STATE", pady_top=(0, 0))
        _grid(parent, onchain, [
            ("BTC_HASH_RATE",             "HASHRATE",   "{:,.0f}"),
            ("BTC_DIFFICULTY",            "DIFF",       "{:,.0f}"),
            ("BTC_BLOCK_HEIGHT",          "BLOCK",      "{:,.0f}"),
            ("BTC_MEMPOOL_COUNT",         "MEMPOOL",    "{:,.0f}"),
            ("BTC_FEE_FASTEST_SATVB",     "FEE sat/vB", "{:.0f}"),
            ("BTC_24H_TX_COUNT",          "24H TX",     "{:,.0f}"),
            ("BTC_24H_MINER_REVENUE_USD", "MINER REV",  "${:,.0f}"),
            ("BTC_24H_TRADE_VOLUME_USD",  "VOL USD",    "${:,.0f}"),
        ])

    def _render_advanced() -> None:
        adv = _macro_map([
            "BTC_FEE_30MIN_SATVB", "BTC_FEE_1H_SATVB", "BTC_FEE_ECONOMY_SATVB",
            "BTC_MEMPOOL_VSIZE", "BTC_AVG_BLOCK_TIME_MIN",
            "BTC_24H_FEES_BTC", "BTC_24H_MINED",
        ], n=30)
        _section(parent, "BTC ADVANCED Â· FEES Â· BLOCK TIME")
        _grid(parent, adv, [
            ("BTC_FEE_30MIN_SATVB",    "30MIN FEE",  "{:.0f}"),
            ("BTC_FEE_1H_SATVB",       "1H FEE",     "{:.0f}"),
            ("BTC_FEE_ECONOMY_SATVB",  "ECON FEE",   "{:.0f}"),
            ("BTC_MEMPOOL_VSIZE",      "MP VSIZE",   "{:,.0f}"),
            ("BTC_AVG_BLOCK_TIME_MIN", "BLOCK TIME", "{:.1f}"),
            ("BTC_24H_FEES_BTC",       "24H FEES",   "{:.2f}"),
            ("BTC_24H_MINED",          "24H MINED",  "{:.0f}"),
        ])

    def _render_ops_summary() -> None:
        left, right = _two_col(parent)

        _section(left, "ENGINES PORTAL Â· PROCESS MONITOR")
        try:
            from core.ops.proc import list_procs
            procs = list_procs()
        except Exception:
            procs = []
        parent._macro_network_procs = procs
        running = [p for p in procs if p.get("alive") or p.get("status") == "running"]
        finished = [p for p in procs if not p.get("alive") and p.get("status") == "finished"]

        stat_row = tk.Frame(left, bg=BG)
        stat_row.pack(fill="x", pady=PAD_ROW // 2)
        for label, val in [
            ("ACTIVE",   f"{len(running)}"),
            ("FINISHED", f"{len(finished)}"),
            ("TOTAL",    f"{len(procs)}"),
        ]:
            box = tk.Frame(stat_row, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1,
                           padx=10, pady=4)
            box.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
            _attach_hover(box)
            tk.Label(box, text=label, font=(FONT, 6, "bold"),
                     fg=DIM, bg=PANEL).pack()
            tk.Label(box, text=val, font=(FONT, 14, "bold"),
                     fg=WHITE, bg=PANEL).pack()

        vps_online, vps_detail = _read_vps_status()
        _section(right, "VPS STATUS")
        vps_c = GREEN if vps_online else RED
        vps_box = tk.Frame(right, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1,
                           padx=12, pady=10)
        vps_box.pack(fill="x", padx=2, pady=2)
        _attach_hover(vps_box)
        vps_status_lbl = tk.Label(vps_box, text="â— ONLINE" if vps_online else "â—‹ OFFLINE",
                                  font=(FONT, 14, "bold"), fg=vps_c, bg=PANEL)
        vps_status_lbl.pack(anchor="w")
        vps_detail_lbl = tk.Label(vps_box, text=vps_detail, font=(FONT, 8),
                                  fg=WHITE, bg=PANEL)
        vps_detail_lbl.pack(anchor="w")
        tk.Label(vps_box, text="SSH connect test Â· port 22",
                 font=(FONT, 6), fg=DIM, bg=PANEL).pack(anchor="w", pady=(2, 0))
        if vps_detail == "checking...":
            def _refresh_vps_box() -> None:
                try:
                    if not vps_box.winfo_exists():
                        return
                except Exception:
                    return
                latest_online, latest_detail = _read_vps_status()
                if latest_detail == "checking...":
                    vps_box.after(250, _refresh_vps_box)
                    return
                latest_color = GREEN if latest_online else RED
                vps_status_lbl.configure(
                    text="â— ONLINE" if latest_online else "â—‹ OFFLINE",
                    fg=latest_color,
                )
                vps_detail_lbl.configure(text=latest_detail)

            vps_box.after(250, _refresh_vps_box)

    def _render_processes() -> None:
        procs = list(getattr(parent, "_macro_network_procs", []) or [])
        if not procs:
            return
        _section(parent, "PROCESSES Â· ACTIVE + RECENT")
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", pady=(0, 1))
        for txt, w in [("", 3), ("ENGINE", 16), ("PID", 12), ("STATUS", 10), ("STARTED", 15)]:
            tk.Label(hdr, text=txt, font=(FONT, 6, "bold"), fg=DIM,
                     bg=BG, width=w, anchor="w").pack(side="left")

        for p in procs[:15]:
            engine = (p.get("engine") or "?").upper()
            pid = p.get("pid") or "?"
            status = p.get("status", "?")
            alive = p.get("alive", False)
            sc = GREEN if alive else DIM
            row = tk.Frame(parent, bg=BG)
            row.pack(fill="x")
            tk.Label(row, text=f" {'â—' if alive else 'â—‹'}",
                     font=(FONT, 8, "bold"), fg=sc, bg=BG, width=3).pack(side="left")
            tk.Label(row, text=f"{engine:<14}", font=(FONT, 8, "bold"),
                     fg=WHITE, bg=BG, width=16, anchor="w").pack(side="left")
            tk.Label(row, text=f"{pid}", font=(FONT, 7),
                     fg=DIM, bg=BG, width=12, anchor="w").pack(side="left")
            tk.Label(row, text=status.upper(), font=(FONT, 7, "bold"),
                     fg=sc, bg=BG, width=10, anchor="w").pack(side="left")
            started = p.get("started", "")
            tk.Label(row,
                     text=f"{_fmt_age(started)} ago" if started else "",
                     font=(FONT, 7), fg=DIM, bg=BG, anchor="w").pack(
                         side="left", fill="x", expand=True)

    _run_chunked(
        parent,
        [
            _render_onchain,
            _render_advanced,
            _render_ops_summary,
            _render_processes,
        ],
        metric_name="content.macro_brain.REDE.full",
    )


def _render_book_tab(parent):
    """Macro paper P&L header · Theses | Positions · Regime details."""
    from macro_brain.persistence.store import (
        active_theses, latest_regime, open_positions, pnl_summary,
    )

    pnl = pnl_summary()
    total = pnl.get("total_pnl", 0) or 0
    equity = pnl.get("equity", 0) or 0
    initial = pnl.get("initial", 0) or 0
    dd_pct = ((initial - equity) / initial * 100) if initial else 0
    theses = active_theses()
    positions = open_positions()

    _section(parent, "MACRO BOOK · PAPER", pady_top=(0, 0))
    pnl_row = tk.Frame(parent, bg=BG); pnl_row.pack(fill="x",
                                                    pady=PAD_ROW // 2)
    for label, val, color in [
        ("EQUITY",    f"${equity:,.0f}",                       WHITE),
        ("TOTAL P&L", f"${total:+,.0f}",
                      GREEN if total >= 0 else RED),
        ("INITIAL",   f"${initial:,.0f}",                      DIM2),
        ("DRAWDOWN",
         f"{-dd_pct:+.2f}%" if dd_pct > 0 else "0.00%",
         RED if dd_pct > 0 else GREEN),
        ("THESES",    f"{len(theses)}",                        AMBER),
        ("POSITIONS", f"{len(positions)}",                     AMBER),
    ]:
        box = tk.Frame(pnl_row, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1,
                       padx=12, pady=6)
        box.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
        _attach_hover(box)
        tk.Label(box, text=val, font=(FONT, 13, "bold"),
                 fg=color, bg=PANEL).pack()
        tk.Label(box, text=label, font=(FONT, 7, "bold"),
                 fg=DIM, bg=PANEL).pack()

    left, right = _two_col(parent)

    _section(left, "ACTIVE THESES")
    if theses:
        for t in theses:
            card = tk.Frame(left, bg=PANEL,
                            highlightbackground=BORDER,
                            highlightthickness=1)
            card.pack(fill="x", pady=2, padx=2)
            _attach_hover(card)
            hdr_c = tk.Frame(card, bg=PANEL)
            hdr_c.pack(fill="x", padx=6, pady=(4, 2))
            sc = GREEN if t["direction"] == "long" else RED
            tk.Label(hdr_c, text=t["direction"].upper(),
                     font=(FONT, 8, "bold"), fg=sc, bg=PANEL).pack(side="left")
            tk.Label(hdr_c, text=f"  {t['asset']}",
                     font=(FONT, 10, "bold"),
                     fg=WHITE, bg=PANEL).pack(side="left")
            tk.Label(hdr_c, text=f"conf {t['confidence']:.0%}",
                     font=(FONT, 8), fg=AMBER,
                     bg=PANEL).pack(side="right", padx=4)
            tk.Label(hdr_c, text=f"{t.get('target_horizon_days', '?')}d",
                     font=(FONT, 8), fg=DIM,
                     bg=PANEL).pack(side="right", padx=4)
            rationale = t.get("rationale", "") or ""
            tk.Label(card, text=rationale[:250], font=(FONT, 8), fg=DIM2,
                     bg=PANEL, wraplength=500, justify="left",
                     anchor="w").pack(fill="x", padx=6, pady=(0, 4))
    else:
        tk.Label(left, text="  (no active theses)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=6)

    _section(right, "OPEN POSITIONS")
    if positions:
        for p in positions:
            sc = GREEN if p["side"] == "long" else RED
            card = tk.Frame(right, bg=PANEL,
                            highlightbackground=BORDER,
                            highlightthickness=1)
            card.pack(fill="x", pady=2, padx=2)
            _attach_hover(card)
            tk.Label(card,
                     text=f"  {p['side'].upper()}  {p['asset']}",
                     font=(FONT, 10, "bold"),
                     fg=sc, bg=PANEL).pack(anchor="w", padx=6,
                                           pady=(4, 0))
            detail = (
                f"  size ${p['size_usd']:,.0f}  @  "
                f"{p['entry_price']:,.2f}"
            )
            tk.Label(card, text=detail, font=(FONT, 8),
                     fg=WHITE, bg=PANEL).pack(anchor="w", padx=6,
                                               pady=(0, 4))
    else:
        tk.Label(right, text="  (no open positions)", font=(FONT, 9),
                 fg=DIM, bg=BG).pack(pady=6)

    _section(parent, "CURRENT REGIME · DETAILS")
    regime = latest_regime()
    if regime:
        reg_name = (regime.get("regime") or "?").upper()
        conf = regime.get("confidence") or 0.0
        reg_color = {"RISK_ON": GREEN, "RISK_OFF": RED,
                     "TRANSITION": AMBER, "UNCERTAINTY": DIM2}.get(
                         reg_name, WHITE)
        reg_row = tk.Frame(parent, bg=BG); reg_row.pack(fill="x",
                                                        pady=PAD_ROW // 2)
        tk.Label(reg_row, text=reg_name, font=(FONT, 20, "bold"),
                 fg=reg_color, bg=BG).pack(side="left", padx=(8, 20))
        col = tk.Frame(reg_row, bg=BG); col.pack(side="left")
        tk.Label(col, text=f"confidence {conf:.0%}",
                 font=(FONT, 10), fg=WHITE, bg=BG).pack(anchor="w")
        tk.Label(col,
                 text=f"snapshot age {_fmt_age(regime.get('ts', ''))}",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w")
        reason = regime.get("reason") or ""
        if reason:
            tk.Label(parent, text=f"  {reason}", font=(FONT, 8),
                     fg=DIM2, bg=BG, anchor="w",
                     wraplength=1000, justify="left").pack(
                         fill="x", padx=6, pady=(2, 0))
    else:
        tk.Label(parent, text="  (no regime snapshot yet)",
                 font=(FONT, 9), fg=DIM, bg=BG).pack(pady=6)


# ── TAB BAR / MAIN RENDER ────────────────────────────────────

def _render_book_tab_v2(parent):
    """Macro book rendered in batches."""
    _cancel_chunk_jobs(parent)
    from macro_brain.persistence.store import (
        active_theses, latest_regime, open_positions, pnl_summary,
    )

    pnl = pnl_summary()
    total = pnl.get("total_pnl", 0) or 0
    equity = pnl.get("equity", 0) or 0
    initial = pnl.get("initial", 0) or 0
    dd_pct = ((initial - equity) / initial * 100) if initial else 0
    theses = active_theses()
    positions = open_positions()
    regime = latest_regime()

    def _render_pnl() -> None:
        _section(parent, "MACRO BOOK Â· PAPER", pady_top=(0, 0))
        pnl_row = tk.Frame(parent, bg=BG)
        pnl_row.pack(fill="x", pady=PAD_ROW // 2)
        for label, val, color in [
            ("EQUITY",    f"${equity:,.0f}", WHITE),
            ("TOTAL P&L", f"${total:+,.0f}", GREEN if total >= 0 else RED),
            ("INITIAL",   f"${initial:,.0f}", DIM2),
            ("DRAWDOWN",  f"{-dd_pct:+.2f}%" if dd_pct > 0 else "0.00%", RED if dd_pct > 0 else GREEN),
            ("THESES",    f"{len(theses)}", AMBER),
            ("POSITIONS", f"{len(positions)}", AMBER),
        ]:
            box = tk.Frame(pnl_row, bg=PANEL,
                           highlightbackground=BORDER, highlightthickness=1,
                           padx=12, pady=6)
            box.pack(side="left", padx=PAD_TILE_X, fill="both", expand=True)
            _attach_hover(box)
            tk.Label(box, text=val, font=(FONT, 13, "bold"),
                     fg=color, bg=PANEL).pack()
            tk.Label(box, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL).pack()

    def _render_sides() -> None:
        left, right = _two_col(parent)
        _section(left, "ACTIVE THESES")
        if theses:
            for t in theses:
                card = tk.Frame(left, bg=PANEL,
                                highlightbackground=BORDER,
                                highlightthickness=1)
                card.pack(fill="x", pady=2, padx=2)
                _attach_hover(card)
                hdr_c = tk.Frame(card, bg=PANEL)
                hdr_c.pack(fill="x", padx=6, pady=(4, 2))
                sc = GREEN if t["direction"] == "long" else RED
                tk.Label(hdr_c, text=t["direction"].upper(),
                         font=(FONT, 8, "bold"), fg=sc, bg=PANEL).pack(side="left")
                tk.Label(hdr_c, text=f"  {t['asset']}",
                         font=(FONT, 10, "bold"),
                         fg=WHITE, bg=PANEL).pack(side="left")
                tk.Label(hdr_c, text=f"conf {t['confidence']:.0%}",
                         font=(FONT, 8), fg=AMBER,
                         bg=PANEL).pack(side="right", padx=4)
                tk.Label(hdr_c, text=f"{t.get('target_horizon_days', '?')}d",
                         font=(FONT, 8), fg=DIM,
                         bg=PANEL).pack(side="right", padx=4)
                rationale = t.get("rationale", "") or ""
                tk.Label(card, text=rationale[:250], font=(FONT, 8), fg=DIM2,
                         bg=PANEL, wraplength=500, justify="left",
                         anchor="w").pack(fill="x", padx=6, pady=(0, 4))
        else:
            tk.Label(left, text="  (no active theses)", font=(FONT, 9),
                     fg=DIM, bg=BG).pack(pady=6)

        _section(right, "OPEN POSITIONS")
        if positions:
            for p in positions:
                sc = GREEN if p["side"] == "long" else RED
                card = tk.Frame(right, bg=PANEL,
                                highlightbackground=BORDER,
                                highlightthickness=1)
                card.pack(fill="x", pady=2, padx=2)
                _attach_hover(card)
                tk.Label(card,
                         text=f"  {p['side'].upper()}  {p['asset']}",
                         font=(FONT, 10, "bold"),
                         fg=sc, bg=PANEL).pack(anchor="w", padx=6, pady=(4, 0))
                detail = f"  size ${p['size_usd']:,.0f}  @  {p['entry_price']:,.2f}"
                tk.Label(card, text=detail, font=(FONT, 8),
                         fg=WHITE, bg=PANEL).pack(anchor="w", padx=6, pady=(0, 4))
        else:
            tk.Label(right, text="  (no open positions)", font=(FONT, 9),
                     fg=DIM, bg=BG).pack(pady=6)

    def _render_regime() -> None:
        _section(parent, "CURRENT REGIME Â· DETAILS")
        if regime:
            reg_name = (regime.get("regime") or "?").upper()
            conf = regime.get("confidence") or 0.0
            reg_color = {"RISK_ON": GREEN, "RISK_OFF": RED,
                         "TRANSITION": AMBER, "UNCERTAINTY": DIM2}.get(reg_name, WHITE)
            reg_row = tk.Frame(parent, bg=BG)
            reg_row.pack(fill="x", pady=PAD_ROW // 2)
            tk.Label(reg_row, text=reg_name, font=(FONT, 20, "bold"),
                     fg=reg_color, bg=BG).pack(side="left", padx=(8, 20))
            col = tk.Frame(reg_row, bg=BG)
            col.pack(side="left")
            tk.Label(col, text=f"confidence {conf:.0%}",
                     font=(FONT, 10), fg=WHITE, bg=BG).pack(anchor="w")
            tk.Label(col,
                     text=f"snapshot age {_fmt_age(regime.get('ts', ''))}",
                     font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w")
            reason = regime.get("reason") or ""
            if reason:
                tk.Label(parent, text=f"  {reason}", font=(FONT, 8),
                         fg=DIM2, bg=BG, anchor="w",
                         wraplength=1000, justify="left").pack(
                             fill="x", padx=6, pady=(2, 0))
        else:
            tk.Label(parent, text="  (no regime snapshot yet)",
                     font=(FONT, 9), fg=DIM, bg=BG).pack(pady=6)

    _run_chunked(
        parent,
        [
            _render_pnl,
            _render_sides,
            _render_regime,
        ],
        metric_name="content.macro_brain.LIVRO.full",
    )


def _render_engines_tab_impl(parent):
    """iPod-classic engine picker — shared component."""
    try:
        from config.engines import ENGINES
        from core import engine_picker as ep
    except Exception as e:
        tk.Label(parent, text=f"picker unavailable: {e}",
                 font=(FONT, 9), fg=RED, bg=BG).pack(pady=20)
        return
    tracks = ep.build_tracks_from_registry(ENGINES)
    ep.render(parent, tracks)


def _render_engines_tab(parent):
    """Stage the engine picker so the tab responds before full mount."""
    _cancel_chunk_jobs(parent)
    shell = _panel_shell(parent, pady=(0, 0))
    _section(shell, "ENGINES DESK", pady_top=(0, 0))
    tk.Label(
        shell,
        text="  Loading engine picker, tracks and detail panel...",
        font=(FONT, 8),
        fg=DIM,
        bg=PANEL,
        anchor="w",
    ).pack(fill="x", padx=4, pady=(2, 6))
    started = time.perf_counter()

    def _mount_picker() -> None:
        try:
            for child in shell.winfo_children():
                try:
                    child.destroy()
                except Exception:
                    pass
            _render_engines_tab_impl(shell)
        finally:
            try:
                from launcher_support.screens._metrics import emit_timing_metric

                emit_timing_metric(
                    "content.macro_brain.MOTORES.full",
                    ms=(time.perf_counter() - started) * 1000.0,
                )
            except Exception:
                pass

    job = parent.after_idle(_mount_picker)
    _track_chunk_job(parent, job)


# Tabs in three functional groups — a thin divider is drawn between
# groups in the tab bar so EUA / BRASIL / CRIPTO (mercados) is visually
# separate from SINAIS / MACRO (análise), and from REDE / LIVRO /
# MOTORES (operação). Labels are PT-BR / Valve-ish short.
_TABS = [
    ("EUA",      "1", _render_markets_tab_v4,  "mkt"),
    ("BRASIL",   "2", _render_br_tab,       "mkt"),
    ("CRIPTO",   "3", _render_crypto_tab,   "mkt"),
    ("SINAIS",   "4", _render_insights_tab, "anl"),
    ("MACRO",    "5", _render_analysis_tab, "anl"),
    ("REDE",     "6", _render_network_tab_v2,  "ops"),
    ("LIVRO",    "7", _render_book_tab_v2,  "ops"),
    ("MOTORES",  "8", _render_engines_tab,  "ops"),
]


def render(parent: tk.Widget, app=None) -> None:
    from macro_brain.persistence.store import init_db, latest_regime
    init_db()
    pending_job = getattr(parent, "_macro_render_idle_job", None)
    if pending_job is not None:
        try:
            parent.after_cancel(pending_job)
        except Exception:
            pass
        try:
            delattr(parent, "_macro_render_idle_job")
        except Exception:
            pass
    _cancel_chunk_jobs(parent)

    # Full render rebuilds every tile, so any previously-registered refs
    # are about to become stale. Drop them now so tick_update() doesn't
    # try to configure dead widgets.
    _clear_tile_registry()

    for w in parent.winfo_children():
        try: w.destroy()
        except Exception: pass

    outer = tk.Frame(parent, bg=BG)
    outer.pack(fill="both", expand=True, padx=PAD_OUT, pady=PAD_OUT // 2)

    if app is not None:
        for k in ("<Escape>", "<Key-0>", "<BackSpace>"):
            try: app._kb(k, lambda: app._menu("main"))
            except Exception: pass
        try: app._kb("<Key-r>", lambda: render(parent, app))
        except Exception: pass

    # ── TOP BAR ────────────────────────────────────────
    top = tk.Frame(outer, bg=BG); top.pack(fill="x")
    # VGUI-style title — orange HL2 text on charcoal, guillemets as
    # the Source Engine MOTD / scoreboard flair.
    tk.Label(top, text="»  MACRO BRAIN  «",
             font=(FONT, 11, "bold"),
             fg=AMBER, bg=BG, padx=4, pady=1).pack(side="left")
    tk.Label(top, text="  //  aurum cio · live cockpit",
             font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left", padx=3)

    right = tk.Frame(top, bg=BG); right.pack(side="right")

    def _enter_main():
        if app is not None: app._menu("main")

    enter_btn = tk.Label(
        right, text="  [ ENTER TERMINAL · ESC ]  ",
        font=(FONT, 8, "bold"), fg=BG, bg=AMBER,
        cursor="hand2", padx=8, pady=2,
    )
    enter_btn.pack(side="right", padx=4)
    enter_btn.bind("<Button-1>", lambda e: _enter_main())
    enter_btn.bind("<Enter>", lambda e: enter_btn.config(bg=AMBER_H))
    enter_btn.bind("<Leave>", lambda e: enter_btn.config(bg=AMBER))

    regime = latest_regime()
    if regime:
        rn = (regime.get("regime") or "?").upper()
        c = regime.get("confidence") or 0.0
        rc = {"RISK_ON": GREEN, "RISK_OFF": RED,
              "TRANSITION": AMBER, "UNCERTAINTY": DIM2}.get(rn, WHITE)
        tk.Label(right, text=f" {rn} ", font=(FONT, 8, "bold"),
                 fg=BG, bg=rc, padx=4).pack(side="right", padx=(4, 0))
        tk.Label(right, text=f"{c:.0%}", font=(FONT, 7),
                 fg=AMBER, bg=BG).pack(side="right", padx=(0, 3))
        tk.Label(right, text="REGIME", font=(FONT, 6, "bold"),
                 fg=DIM, bg=BG).pack(side="right")

    tk.Label(right, text=datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="right", padx=8)

    tk.Frame(outer, bg=AMBER, height=1).pack(fill="x", pady=(2, 0))

    # ── NORTH-STAR WATCHLIST (fixed header) ────────────
    # 5 tiles XL (BTC · ETH · S&P · DXY · BTC.D) sempre visiveis, tick
    # update via _TILE_REGISTRY como qualquer outro tile.
    try:
        _render_northstar(outer)
    except Exception as exc:
        log.warning("render northstar failed: %s", exc)

    # ── STATUS BAR (fixed bottom — packed BEFORE content expands) ──
    # Pack side=bottom agora pra reservar espaco antes de content_wrap
    # tomar o resto com expand=True.
    try:
        _render_statusbar(outer)
    except Exception as exc:
        log.warning("render statusbar failed: %s", exc)

    # ── TAB BAR ────────────────────────────────────────
    tab_bar = tk.Frame(outer, bg=BG)
    tab_bar.pack(fill="x", pady=(6, 0))

    content_wrap = tk.Frame(outer, bg=BG)
    content_wrap.pack(fill="both", expand=True, pady=(6, 0))
    content_canvas = tk.Canvas(content_wrap, bg=BG, highlightthickness=0)
    content_scroll = tk.Scrollbar(content_wrap, orient="vertical", command=content_canvas.yview)
    content = tk.Frame(content_canvas, bg=BG)
    content_window = content_canvas.create_window((0, 0), window=content, anchor="nw")
    content.bind("<Configure>", lambda _e: content_canvas.configure(scrollregion=content_canvas.bbox("all")))
    _bind_scroll_canvas(content_canvas, content_window, pad_x=4)
    _wire_scroll_wheel(content_canvas, [content])
    content_canvas.configure(yscrollcommand=content_scroll.set)
    content_canvas.pack(side="left", fill="both", expand=True)
    content_scroll.pack(side="right", fill="y")
    content_loading = tk.Label(
        content,
        text="loading active desk...",
        font=(FONT, 9),
        fg=DIM,
        bg=BG,
        anchor="w",
    )
    content_loading.pack(fill="x", padx=6, pady=12)

    # Tab widget refs, keyed by tab_name — populated by _build_tabs
    # so _switch_tab can repaint styling without rebuilding the bar.
    _tab_refs: dict[str, tk.Label] = {}
    render_state = {"job": None, "generation": 0}

    def _repaint_tabs() -> None:
        """Update active/inactive styling on existing tab widgets —
        avoids the destroy+rebuild cycle of the whole tab bar every
        time the user presses 1-8."""
        for tn, w in _tab_refs.items():
            try:
                if not w.winfo_exists():
                    continue
            except Exception:
                continue
            active = (_STATE["tab"] == tn)
            if active:
                w.config(fg=BG, bg=AMBER)
            else:
                w.config(fg=DIM, bg=BG)

    def _cancel_pending_render() -> None:
        job = render_state.get("job")
        if job is None:
            return
        try:
            parent.after_cancel(job)
        except Exception:
            pass
        render_state["job"] = None
        try:
            delattr(parent, "_macro_render_idle_job")
        except Exception:
            pass

    def _render_active_tab(name: str, generation: int) -> None:
        render_state["job"] = None
        try:
            delattr(parent, "_macro_render_idle_job")
        except Exception:
            pass
        if generation != render_state["generation"]:
            return
        for w in content.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        _clear_tile_registry()
        for tab_name, _k, renderer, _g in _TABS:
            if tab_name == name:
                try:
                    renderer(content)
                except Exception as e:
                    log.warning(f"tab render {name} failed: {e}")
                    tk.Label(
                        content,
                        text=f"Error: {e}",
                        font=(FONT, 9),
                        fg=RED,
                        bg=BG,
                    ).pack(pady=20)
                break

    def _switch_tab(name):
        _STATE["tab"] = name
        _repaint_tabs()
        render_state["generation"] += 1
        _cancel_pending_render()
        for w in content.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass
        _clear_tile_registry()
        tk.Label(
            content,
            text=f"loading {name.lower()}...",
            font=(FONT, 9),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(fill="x", padx=6, pady=12)
        generation = render_state["generation"]
        render_state["job"] = parent.after_idle(
            lambda n=name, g=generation: _render_active_tab(n, g)
        )
        parent._macro_render_idle_job = render_state["job"]

    def _build_tabs():
        # Group tabs by their functional bucket so we can render a
        # heading above each group (MERCADOS / ANÁLISE / OPERAÇÃO)
        # — classic VGUI menu grouping, scannable at a glance.
        group_labels = {
            "mkt": "MERCADOS",
            "anl": "ANÁLISE",
            "ops": "OPERAÇÃO",
        }
        grouped: dict[str, list[tuple[str, str]]] = {}
        order: list[str] = []
        for tab_name, key_num, _r, group in _TABS:
            if group not in grouped:
                grouped[group] = []
                order.append(group)
            grouped[group].append((tab_name, key_num))

        first_group = True
        for group in order:
            if not first_group:
                # Thin rule between groups — aligned with the tab row
                # (ignores the height of the group heading above).
                tk.Frame(tab_bar, bg=BORDER, width=1).pack(
                    side="left", fill="y", padx=8, pady=(16, 4))
            first_group = False

            g_box = tk.Frame(tab_bar, bg=BG)
            g_box.pack(side="left", padx=(0, 2))

            # Group heading — orange dim small-caps, ties to the
            # accent colour so the eye reads the grouping as part
            # of the same chrome, not a floating label.
            tk.Label(
                g_box, text=group_labels.get(group, group.upper()),
                font=(FONT, 6, "bold"), fg=AMBER, bg=BG,
                anchor="w", padx=4,
            ).pack(fill="x", pady=(0, 2))

            g_row = tk.Frame(g_box, bg=BG); g_row.pack(fill="x")

            # VGUI tab styling:
            #   inactive → flat, merges with the header bg, dim gray
            #   active   → solid HL2 orange chip, dark text
            #   hover    → lift to BG3, brighten text to WHITE
            # No highlightthickness (kept Tk happier on resize and
            # reads cleaner — the HL2 menu isn't about box outlines).
            for tab_name, key_num in grouped[group]:
                active = (_STATE["tab"] == tab_name)
                if active:
                    fg, bg = BG, AMBER
                else:
                    fg, bg = DIM, BG
                tab = tk.Label(
                    g_row,
                    text=f"  [{key_num}]  {tab_name}  ",
                    font=(FONT, 10, "bold"),
                    fg=fg, bg=bg, cursor="hand2", padx=12, pady=5,
                    bd=0, highlightthickness=0,
                )
                tab.pack(side="left", padx=(0, 1))
                _tab_refs[tab_name] = tab
                tab.bind("<Button-1>",
                         lambda e, n=tab_name: _switch_tab(n))
                # Hover handlers always read the current active state
                # from _STATE so the effect is safe after _switch_tab
                # has repainted this widget's bg/fg in place.
                tab.bind(
                    "<Enter>",
                    lambda e, t=tab, n=tab_name: (
                        None if _STATE["tab"] == n
                        else t.config(bg=BG3, fg=WHITE)
                    ),
                )
                tab.bind(
                    "<Leave>",
                    lambda e, t=tab, n=tab_name: (
                        None if _STATE["tab"] == n
                        else t.config(bg=BG, fg=DIM)
                    ),
                )
                if app is not None:
                    try: app._kb(f"<Key-{key_num}>",
                                 lambda n=tab_name: _switch_tab(n))
                    except Exception: pass

    # Build tab bar once — _switch_tab now repaints existing widgets
    # instead of rebuilding the bar, so the initial render no longer
    # pays the double-build cost.
    _build_tabs()
    _switch_tab(_STATE["tab"])

    # ── FOOTER ─────────────────────────────────────────
    foot = tk.Frame(outer, bg=BG)
    foot.pack(fill="x", pady=(6, 0), side="bottom")

    def _run_cycle():
        import threading
        def _work():
            try:
                from macro_brain.brain import run_once
                run_once(force=True)
                if app is not None:
                    app.after(0, lambda: render(parent, app))
            except Exception as e:
                log.error(f"run_cycle failed: {e}")
        threading.Thread(target=_work, daemon=True).start()

    def _refresh(): render(parent, app)

    for label, cmd in [
        ("[ RUN CYCLE · C ]", _run_cycle),
        ("[ REFRESH · R ]",   _refresh),
    ]:
        b = tk.Label(
            foot, text=f"  {label}  ", font=(FONT, 8, "bold"),
            fg=WHITE, bg=BG3, cursor="hand2", padx=8, pady=3,
        )
        b.pack(side="left", padx=2)
        b.bind("<Button-1>", lambda e, c=cmd: c())
        b.bind("<Enter>",
               lambda e, w=b: w.config(bg=BORDER_H, fg=AMBER))
        b.bind("<Leave>",
               lambda e, w=b: w.config(bg=BG3, fg=WHITE))
    if app is not None:
        try: app._kb("<Key-c>", lambda: _run_cycle())
        except Exception: pass

    tk.Label(
        foot,
        text="  //  ESC main menu  ·  1-8 switch tab  ·  R refresh  ·  C cycle",
        font=(FONT, 7), fg=DIM2, bg=BG,
    ).pack(side="right", padx=4)
