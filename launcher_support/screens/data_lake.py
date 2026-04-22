"""OHLCV cache browser — split-pane screen extracted from launcher.App._data_lake.

The ``render(app)`` entry point is a faithful extraction of the original
method: same behaviour, same widget tree, same state dict. It consumes the
launcher App instance via the ``app`` parameter and calls back into
``app._*`` helpers for page scaffolding / keybindings / navigation. No new
public API — ``launcher.App._data_lake`` stays as a thin delegate so
existing menu-dispatch sites (``launcher_support.screens.data_center``
strings ``"app._data_lake"``) keep working unchanged.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox

from config.params import BASKETS
from core import cache as cache_mod
from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D,
    BG, BG2, BG3, BORDER,
    DIM, DIM2, FONT,
    GREEN, WHITE,
)


def render(app) -> None:
    """Build and mount the OHLCV cache browser into the App's content area.

    Split-pane layout:
      Left  (60%): table of every cached file. Click pre-fills the
                   right-hand form in SYMBOL mode; DEL removes the file.
      Right (40%): download form — BASKET or SYMBOL mode, interval, days,
                   market. DOWNLOAD button spawns tools/capture/prefetch.py.
    While a prefetch is alive the status line polls every 3s and the
    table refreshes so new rows appear as they land.
    """
    app._clr()
    app._clear_kb()
    app.h_path.configure(text="> DATA > LAKE")
    app.h_stat.configure(text="OHLCV", fg=AMBER_D)
    app.f_lbl.configure(text="ESC voltar  |  DEL apagar  |  enter baixar")
    app._kb("<Escape>", lambda: app._data_center())
    app._kb("<Key-0>", lambda: app._data_center())
    app._bind_global_nav()

    _outer, body = app._ui_page_shell(
        "OHLCV CACHE",
        "Dados históricos locais · data/.cache/ · alimenta backtests e pesquisa",
    )

    # Split-pane: left list (expands), right form (fixed width)
    split = tk.Frame(body, bg=BG)
    split.pack(fill="both", expand=True)
    left_wrap = tk.Frame(split, bg=BG)
    left_wrap.pack(side="left", fill="both", expand=True, padx=(0, 10))
    right_wrap = tk.Frame(split, bg=BG, width=340)
    right_wrap.pack(side="right", fill="y")
    right_wrap.pack_propagate(False)

    # -- LEFT: cache list --
    left_panel = app._ui_panel_frame(
        left_wrap, "LOCAL CACHE",
        "baskets e arquivos · click → pre-popula form · DEL apaga",
    )

    # -- BASKETS COVERAGE (section 1) --
    bk_title_row = tk.Frame(left_panel, bg=BG)
    bk_title_row.pack(fill="x", padx=10, pady=(0, 2))
    tk.Label(bk_title_row, text="BASKETS", font=(FONT, 7, "bold"),
             fg=AMBER_D, bg=BG).pack(side="left")
    tk.Label(bk_title_row, text="  · coverage por (tf, mkt) · click = BASKET mode",
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="left")

    bk_header = tk.Frame(left_panel, bg=BG2)
    bk_header.pack(fill="x", padx=10, pady=(0, 2))
    _bcols = [("BASKET", 16), ("TF", 6), ("MKT", 6),
              ("COVERAGE", 10), ("SIZE", 8)]
    for name, w in _bcols:
        tk.Label(bk_header, text=name, font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=BG2, width=w, anchor="w").pack(side="left")
    tk.Frame(left_panel, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 2))

    bk_list_wrap = tk.Frame(left_panel, bg=BG)
    bk_list_wrap.pack(fill="x", padx=10, pady=(0, 8))
    bk_canvas = tk.Canvas(bk_list_wrap, bg=BG, highlightthickness=0, height=140)
    bk_sb = tk.Scrollbar(bk_list_wrap, orient="vertical",
                         command=bk_canvas.yview)
    bk_rows_frame = tk.Frame(bk_canvas, bg=BG)
    window_id = bk_canvas.create_window((0, 0), window=bk_rows_frame, anchor="nw")
    app._bind_canvas_window_width(bk_canvas, window_id, pad_x=4)
    bk_canvas.configure(yscrollcommand=bk_sb.set)
    bk_canvas.pack(side="left", fill="x", expand=True)
    bk_sb.pack(side="right", fill="y")
    bk_rows_frame.bind("<Configure>",
                       lambda e: bk_canvas.configure(scrollregion=bk_canvas.bbox("all")))

    # -- FILES (section 2) --
    fl_title_row = tk.Frame(left_panel, bg=BG)
    fl_title_row.pack(fill="x", padx=10, pady=(2, 2))
    tk.Label(fl_title_row, text="FILES", font=(FONT, 7, "bold"),
             fg=AMBER_D, bg=BG).pack(side="left")
    tk.Label(fl_title_row, text="  · um arquivo por (sym, tf, mkt) · click = SYMBOL mode",
             font=(FONT, 7), fg=DIM, bg=BG).pack(side="left")

    header = tk.Frame(left_panel, bg=BG2)
    header.pack(fill="x", padx=10, pady=(0, 2))
    _cols = [("SYMBOL", 12), ("TF", 6), ("MKT", 6),
             ("SPAN", 22), ("BARS", 10), ("SIZE", 8)]
    for name, w in _cols:
        tk.Label(header, text=name, font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=BG2, width=w, anchor="w").pack(side="left")
    tk.Frame(left_panel, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 2))

    list_wrap = tk.Frame(left_panel, bg=BG)
    list_wrap.pack(fill="both", expand=True, padx=10, pady=(0, 4))
    canvas = tk.Canvas(list_wrap, bg=BG, highlightthickness=0, height=420)
    sb = tk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview)
    rows_frame = tk.Frame(canvas, bg=BG)
    window_id = canvas.create_window((0, 0), window=rows_frame, anchor="nw")
    app._bind_canvas_window_width(canvas, window_id, pad_x=4)
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    rows_frame.bind("<Configure>",
                    lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

    def _on_wheel(event):
        canvas.yview_scroll(-1 * (event.delta // 120), "units")
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

    total_lbl = tk.Label(left_panel, text="", font=(FONT, 8),
                         fg=DIM, bg=BG, anchor="w")
    total_lbl.pack(fill="x", padx=10, pady=(2, 6))

    # -- RIGHT: download form --
    right_panel = app._ui_panel_frame(
        right_wrap, "DOWNLOAD", "binance · prefetch → cache local",
    )
    form = tk.Frame(right_panel, bg=BG)
    form.pack(fill="x", padx=10, pady=(0, 8))

    def _lbl(txt):
        tk.Label(form, text=txt, font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=BG, anchor="w").pack(fill="x", pady=(4, 2))

    mode_var = tk.StringVar(value="BASKET")
    basket_var = tk.StringVar(value="bluechip")
    symbol_var = tk.StringVar(value="BTCUSDT")
    interval_var = tk.StringVar(value="15m")
    days_var = tk.StringVar(value="3000")
    market_var = tk.StringVar(value="FUTURES")
    btn_var = tk.StringVar(value="DOWNLOAD")

    _lbl("MODE")
    mode_row = tk.Frame(form, bg=BG)
    mode_row.pack(fill="x")
    for val in ("BASKET", "SYMBOL"):
        tk.Radiobutton(mode_row, text=val, variable=mode_var, value=val,
                       font=(FONT, 8, "bold"), fg=WHITE, bg=BG,
                       selectcolor=BG2, activebackground=BG,
                       activeforeground=AMBER, bd=0).pack(side="left", padx=(0, 10))

    _lbl("BASKET")
    bk_keys = list(BASKETS.keys())
    bk_om = tk.OptionMenu(form, basket_var, *bk_keys)
    bk_om.configure(font=(FONT, 8), bg=BG2, fg=WHITE, bd=0,
                    highlightthickness=0, activebackground=AMBER_D,
                    activeforeground=BG, anchor="w")
    bk_om.pack(fill="x")

    _lbl("SYMBOL")
    tk.Entry(form, textvariable=symbol_var, font=(FONT, 9, "bold"),
             bg=BG2, fg=WHITE, insertbackground=AMBER, bd=0,
             highlightthickness=1, highlightbackground=BORDER
             ).pack(fill="x", ipady=3)

    _lbl("INTERVAL")
    iv_om = tk.OptionMenu(form, interval_var,
                          "1m", "5m", "15m", "1h", "4h", "1d")
    iv_om.configure(font=(FONT, 8), bg=BG2, fg=WHITE, bd=0,
                    highlightthickness=0, activebackground=AMBER_D,
                    activeforeground=BG, anchor="w")
    iv_om.pack(fill="x")

    _lbl("DAYS")
    tk.Entry(form, textvariable=days_var, font=(FONT, 9, "bold"),
             bg=BG2, fg=WHITE, insertbackground=AMBER, bd=0,
             highlightthickness=1, highlightbackground=BORDER
             ).pack(fill="x", ipady=3)

    _lbl("MARKET")
    mk_row = tk.Frame(form, bg=BG)
    mk_row.pack(fill="x", pady=(0, 8))
    for val in ("FUTURES", "SPOT"):
        tk.Radiobutton(mk_row, text=val, variable=market_var, value=val,
                       font=(FONT, 8, "bold"), fg=WHITE, bg=BG,
                       selectcolor=BG2, activebackground=BG,
                       activeforeground=AMBER, bd=0).pack(side="left", padx=(0, 10))

    dl_btn = tk.Button(form, textvariable=btn_var, font=(FONT, 10, "bold"),
                       bg=AMBER, fg=BG, bd=0, padx=10, pady=8,
                       activebackground=AMBER_B, activeforeground=BG,
                       cursor="hand2")
    dl_btn.pack(fill="x", pady=(4, 4))

    status_lbl = tk.Label(form, text="idle", font=(FONT, 7),
                          fg=DIM, bg=BG, anchor="w")
    status_lbl.pack(fill="x")

    # -- state + renderers --
    state = {"selected": None, "rows": [], "files": [], "meta_seq": 0}

    def _fmt_size(b):
        if b < 1024:
            return f"{b}B"
        if b < 1024 * 1024:
            return f"{b/1024:.1f}K"
        return f"{b/1024/1024:.1f}M"

    def _load_files():
        info = cache_mod.info()
        files = []
        for sym, entries in info["by_symbol"].items():
            for e in entries:
                files.append({
                    "symbol": sym,
                    "interval": e["interval"],
                    "market": e["market"],
                    "bytes": e["bytes"],
                })
        files.sort(key=lambda f: (f["symbol"], f["interval"], f["market"]))
        return files, info

    def _row_paint(idx, selected: bool):
        if idx is None or idx >= len(state["rows"]):
            return
        row, cells = state["rows"][idx]
        bg = BG2 if selected else BG
        fg = AMBER if selected else WHITE
        row.configure(bg=bg)
        for c in cells:
            c.configure(bg=bg, fg=fg)

    def _select(idx):
        prev = state["selected"]
        if prev is not None:
            _row_paint(prev, False)
        state["selected"] = idx
        _row_paint(idx, True)
        f = state["files"][idx]
        mode_var.set("SYMBOL")
        symbol_var.set(f["symbol"])
        interval_var.set(f["interval"])
        market_var.set(f["market"].upper())
        btn_var.set("RE-DOWNLOAD")

    def _clear_selection():
        state["selected"] = None
        btn_var.set("DOWNLOAD")

    def _compute_basket_coverage(files):
        """For each basket × (tf, market) combo present in the cache,
        return how many of the basket's symbols are covered + total bytes.
        """
        by_key = {}  # (sym, tf, market) -> bytes
        combos = set()
        for f in files:
            k = (f["symbol"], f["interval"], f["market"])
            by_key[k] = f["bytes"]
            combos.add((f["interval"], f["market"]))
        out = []
        for bk_name, bk_syms in BASKETS.items():
            if not bk_syms:
                continue
            for (iv, mk) in combos:
                present = [s for s in bk_syms if (s, iv, mk) in by_key]
                if not present:
                    continue
                total_bytes = sum(by_key[(s, iv, mk)] for s in present)
                out.append({
                    "basket": bk_name,
                    "interval": iv,
                    "market": mk,
                    "present": len(present),
                    "total": len(bk_syms),
                    "bytes": total_bytes,
                })
        out.sort(key=lambda x: (
            -x["present"] / max(1, x["total"]),  # higher coverage first
            x["basket"], x["interval"],
        ))
        return out

    def _render_baskets():
        for w in bk_rows_frame.winfo_children():
            w.destroy()
        coverage = _compute_basket_coverage(state["files"])
        if not coverage:
            tk.Label(bk_rows_frame,
                     text="nenhum basket coberto — baixe algo primeiro",
                     font=(FONT, 8), fg=DIM, bg=BG,
                     anchor="w", padx=6, pady=8).pack(fill="x")
            return
        for e in coverage:
            pct = e["present"] / max(1, e["total"])
            cov_fg = GREEN if pct >= 1.0 else (AMBER if pct >= 0.5 else DIM)
            row = tk.Frame(bk_rows_frame, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=0)
            cells_data = [
                (e["basket"], 16, WHITE),
                (e["interval"], 6, WHITE),
                (e["market"].upper()[:3], 6, WHITE),
                (f"{e['present']}/{e['total']}", 10, cov_fg),
                (_fmt_size(e["bytes"]), 8, WHITE),
            ]
            lbls = []
            for txt, w_, fg in cells_data:
                c = tk.Label(row, text=txt, font=(FONT, 8),
                             fg=fg, bg=BG, width=w_,
                             anchor="w", padx=2, pady=1)
                c.pack(side="left")
                lbls.append(c)

            def _bind_bk(entry=e, r=row, ls=lbls):
                def _on_click(_e=None):
                    prev = state["selected"]
                    if prev is not None:
                        _row_paint(prev, False)
                    state["selected"] = None
                    mode_var.set("BASKET")
                    basket_var.set(entry["basket"])
                    interval_var.set(entry["interval"])
                    market_var.set(entry["market"].upper())
                    btn_var.set("RE-DOWNLOAD")

                def _on_enter(_e=None):
                    r.configure(bg=BG3)
                    for lb in ls:
                        lb.configure(bg=BG3)

                def _on_leave(_e=None):
                    r.configure(bg=BG)
                    for lb in ls:
                        lb.configure(bg=BG)

                for w in (r, *ls):
                    w.bind("<Button-1>", _on_click)
                    w.bind("<Enter>", _on_enter)
                    w.bind("<Leave>", _on_leave)
            _bind_bk()

    def _render_rows():
        for w in rows_frame.winfo_children():
            w.destroy()
        files, info = _load_files()
        state["files"] = files
        state["rows"] = []
        state["meta_seq"] += 1  # invalidates in-flight meta worker

        if not files:
            tk.Label(rows_frame,
                     text="cache vazio — use o form à direita pra baixar",
                     font=(FONT, 8), fg=DIM, bg=BG,
                     anchor="w", padx=6, pady=20).pack(fill="x")
        else:
            for i, f in enumerate(files):
                row = tk.Frame(rows_frame, bg=BG, cursor="hand2")
                row.pack(fill="x", pady=0)
                cells = []
                values = [
                    (f["symbol"], 12), (f["interval"], 6),
                    (f["market"].upper()[:3], 6),
                    ("...", 22), ("...", 10), (_fmt_size(f["bytes"]), 8),
                ]
                for txt, w_ in values:
                    c = tk.Label(row, text=txt, font=(FONT, 8),
                                 fg=WHITE, bg=BG, width=w_,
                                 anchor="w", padx=2, pady=2)
                    c.pack(side="left")
                    cells.append(c)
                state["rows"].append((row, cells))

                def _bind(idx=i, r=row, cs=cells):
                    def _on_click(_e=None):
                        _select(idx)

                    def _on_enter(_e=None):
                        if state["selected"] != idx:
                            r.configure(bg=BG3)
                            for c in cs:
                                c.configure(bg=BG3)

                    def _on_leave(_e=None):
                        if state["selected"] != idx:
                            r.configure(bg=BG)
                            for c in cs:
                                c.configure(bg=BG)

                    for w in (r, *cs):
                        w.bind("<Button-1>", _on_click)
                        w.bind("<Enter>", _on_enter)
                        w.bind("<Leave>", _on_leave)
                _bind()

        total_mb = info["total_bytes"] / 1024 / 1024
        total_lbl.configure(
            text=f"total: {info['n_files']} files · {total_mb:.1f} MB")
        _render_baskets()
        _load_meta_async()

    def _load_meta_async():
        """Read first/last timestamp + bar count per file in a worker.

        Tagged with meta_seq so a later re-render (download finished,
        delete, manual refresh) invalidates older workers still mid-read.
        """
        seq = state["meta_seq"]
        files = list(state["files"])

        def worker():
            for i, f in enumerate(files):
                if state["meta_seq"] != seq:
                    return
                p = (cache_mod.CACHE_DIR /
                     f"{f['symbol']}_{f['interval']}_{f['market']}.pkl.gz")
                try:
                    df = cache_mod.load_frame(p)
                    if df is not None and not df.empty:
                        span = (f"{df['time'].iloc[0].strftime('%y-%m-%d')}"
                                f" -> "
                                f"{df['time'].iloc[-1].strftime('%y-%m-%d')}")
                        bars = f"{len(df):,}"
                    else:
                        span, bars = "empty", "0"
                except Exception:
                    span, bars = "error", "-"

                def update(ii=i, s=span, b=bars, sq=seq):
                    if state["meta_seq"] != sq:
                        return
                    if ii < len(state["rows"]):
                        _, cs = state["rows"][ii]
                        if len(cs) >= 5:
                            cs[3].configure(text=s)
                            cs[4].configure(text=b)

                try:
                    app.after(0, update)
                except Exception:
                    return

        threading.Thread(target=worker, daemon=True).start()

    def _on_del(_e=None):
        idx = state["selected"]
        if idx is None or idx >= len(state["files"]):
            return
        f = state["files"][idx]
        tag = f"{f['symbol']}_{f['interval']}_{f['market']}.pkl.gz"
        if not messagebox.askyesno(
                "Apagar cache",
                f"Remover {tag}?\n\nO arquivo é recriável via DOWNLOAD."):
            return
        try:
            (cache_mod.CACHE_DIR / tag).unlink(missing_ok=True)
        except OSError as ex:
            messagebox.showerror("Erro", str(ex))
            return
        _clear_selection()
        _render_rows()

    app._kb("<Delete>", _on_del)

    def _do_download(_e=None):
        try:
            from core.ops.proc import spawn
        except Exception as e:
            messagebox.showerror("Download", f"proc indisponivel: {e}")
            return
        try:
            days = int(days_var.get().strip())
            assert days > 0
        except Exception:
            messagebox.showwarning("Download", "DAYS inválido.")
            return
        cli = ["--days", str(days),
               "--interval", interval_var.get().strip() or "15m"]
        if mode_var.get() == "SYMBOL":
            sym = symbol_var.get().strip().upper()
            if not sym:
                messagebox.showwarning("Download", "SYMBOL vazio.")
                return
            cli += ["--symbol", sym]
        else:
            cli += ["--basket", basket_var.get()]
        if market_var.get() == "SPOT":
            cli.append("--spot")
        info = spawn("prefetch", cli_args=cli)
        if not info:
            messagebox.showwarning(
                "Download", "ja esta em execucao (ou falhou ao iniciar).")
            return
        status_lbl.configure(
            text=f"running · PID {info.get('pid', '?')}", fg=AMBER)
        _poll_status()

    dl_btn.configure(command=_do_download)
    app._kb("<Return>", _do_download)

    def _poll_status():
        try:
            from core.ops.proc import list_procs
            running = any(
                p.get("alive") and p.get("engine") == "prefetch"
                for p in list_procs(max_age=0))
        except Exception:
            running = False
        if running:
            status_lbl.configure(text="running · baixando...", fg=AMBER)
            _render_rows()
            try:
                app.after(3000, _poll_status)
            except Exception:
                pass
        else:
            status_lbl.configure(text="idle", fg=DIM)
            _render_rows()

    _render_rows()

    # Bottom: return row
    app._ui_back_row(body, lambda: app._data_center())
