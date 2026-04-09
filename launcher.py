#!/usr/bin/env python3
"""
AURUM Finance — Desktop Launcher v2
Complete control center. All engines run embedded.
CS 1.6 / Half-Life console aesthetic.
"""
import os, sys, subprocess, threading, queue, time, json, glob
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import messagebox

# ═══════════════════════════════════════════════════════════
# THEME — CS 1.6 / Half-Life
# ═══════════════════════════════════════════════════════════
BG       = "#0c0c0c"
BG2      = "#111111"
BG3      = "#1a1a1a"
PANEL    = "#0e0e0e"
BORDER   = "#2a2a2a"
AMBER    = "#ff9b00"
AMBER_D  = "#8a5500"
GREEN    = "#00ff41"
GREEN_D  = "#00802a"
RED      = "#ff3333"
CYAN     = "#00cccc"
PURPLE   = "#cc66ff"
ORANGE   = "#ff9933"
BLUE     = "#6699ff"
WHITE    = "#cccccc"
DIM      = "#555555"
DIM2     = "#333333"
SEL_BG   = "#1a1a00"
FONT     = "Consolas"

# ═══════════════════════════════════════════════════════════
# COMPLETE ENGINE + FEATURE REGISTRY
# ═══════════════════════════════════════════════════════════
MENU_TREE = {
    "main": [
        {"key": "backtest", "label": "BACKTEST",          "desc": "Run strategies on historical data",  "color": AMBER},
        {"key": "live",     "label": "LIVE TRADING",      "desc": "Paper / Demo / Testnet / Live",      "color": RED},
        {"key": "tools",    "label": "TOOLS",             "desc": "Darwin, API, Diagnostics",           "color": PURPLE},
        {"key": "data",     "label": "DATA & REPORTS",    "desc": "Browse backtest results and logs",   "color": CYAN},
        {"key": "procs",    "label": "PROCESSES",         "desc": "View and manage running engines",    "color": GREEN},
    ],
    "backtest": [
        {"key": "azoth",       "label": "AZOTH",           "desc": "Systematic Momentum (Graviton)",    "color": AMBER,  "script": "engines/backtest.py",      "inputs": ["days", "basket", "plots", "leverage", ""]},
        {"key": "mercurio",    "label": "MERCURIO",        "desc": "Order Flow / CVD Analysis",         "color": GREEN,  "script": "engines/mercurio.py",      "inputs": ["days", "basket", "leverage", ""]},
        {"key": "thoth",       "label": "THOTH",           "desc": "Sentiment Quantified",              "color": CYAN,   "script": "engines/thoth.py",         "inputs": ["days", "basket", "leverage", ""]},
        {"key": "newton",      "label": "NEWTON",          "desc": "Pairs Mean-Reversion",              "color": BLUE,   "script": "engines/newton.py",        "inputs": ["days", "basket", "leverage", ""]},
        {"key": "multistrat",  "label": "HADRON",          "desc": "Multi-Strategy Ensemble",           "color": PURPLE, "script": "engines/multistrategy.py", "inputs": ["1", "days", "", "", "", "", "", "n", ""]},
        {"key": "prometeu",    "label": "PROMETEU",        "desc": "ML Meta-Ensemble",                  "color": ORANGE, "script": "engines/prometeu.py",      "inputs": [""]},
    ],
    "live": [
        {"key": "paper",   "label": "PAPER TRADING",  "desc": "Simulated — no real orders",     "color": GREEN,  "script": "engines/live.py", "inputs": ["1"]},
        {"key": "demo",    "label": "DEMO",            "desc": "Binance Futures Demo API",       "color": AMBER,  "script": "engines/live.py", "inputs": ["2"]},
        {"key": "testnet", "label": "TESTNET",         "desc": "Binance Futures Testnet",        "color": CYAN,   "script": "engines/live.py", "inputs": ["3"]},
        {"key": "live",    "label": "LIVE TRADING",    "desc": "Real capital — use with caution", "color": RED,   "script": "engines/live.py", "inputs": ["4"]},
        {"key": "arb",     "label": "ARBITRAGE",       "desc": "Cross-exchange funding arb",     "color": PURPLE, "script": "engines/arbitrage.py", "inputs": [""]},
    ],
    "tools": [
        {"key": "darwin",  "label": "DARWIN",     "desc": "Adaptive Strategy Evolution",  "color": PURPLE, "script": "engines/darwin.py",  "inputs": []},
        {"key": "api",     "label": "NEXUS API",  "desc": "REST API server (port 8000)",  "color": ORANGE, "script": "run_api.py",         "inputs": []},
        {"key": "chronos", "label": "CHRONOS",    "desc": "ML Features Test (HMM/GARCH)", "color": CYAN,   "script": "core/chronos.py",    "inputs": []},
    ],
}

BANNER = r"""
    ___   __  __ ____  __  __ __  __
   /   | / / / // __ \/ / / //  |/  /
  / /| |/ / / // /_/ / / / // /|_/ /
 / ___ / /_/ // _, _/ /_/ // /  / /
/_/  |_\____//_/ |_|\____//_/  /_/
"""


class AurumApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AURUM Finance")
        self.configure(bg=BG)
        self.geometry("960x660")
        self.minsize(860, 580)

        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass

        self.process = None
        self.output_queue = queue.Queue()
        self.nav_stack = []  # for back navigation

        self._build_chrome()
        self._show_splash()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── CHROME (header/footer) ──────────────────────────
    def _build_chrome(self):
        tk.Frame(self, bg=AMBER, height=2).pack(fill="x")

        hdr = tk.Frame(self, bg=BG, height=34)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        hc = tk.Frame(hdr, bg=BG)
        hc.pack(fill="both", expand=True, padx=14)
        tk.Label(hc, text="AURUM FINANCE", font=(FONT, 8, "bold"), fg=AMBER, bg=BG).pack(side="left", pady=7)
        self.hdr_right = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG)
        self.hdr_right.pack(side="right", pady=7)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        self.main = tk.Frame(self, bg=BG)
        self.main.pack(fill="both", expand=True)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        foot = tk.Frame(self, bg=BG2, height=22)
        foot.pack(fill="x")
        foot.pack_propagate(False)
        fc = tk.Frame(foot, bg=BG2)
        fc.pack(fill="both", expand=True, padx=14)
        tk.Label(fc, text="v2.0.0", font=(FONT, 7), fg=DIM2, bg=BG2).pack(side="left")
        self.foot_hint = tk.Label(fc, text="", font=(FONT, 7), fg=DIM, bg=BG2)
        self.foot_hint.pack(side="right")

    def _clear(self):
        for w in self.main.winfo_children():
            w.destroy()

    def _unbind(self):
        for k in ("<Return>", "<space>", "<Escape>", "<BackSpace>",
                   *[f"<Key-{i}>" for i in range(10)]):
            try: self.unbind(k)
            except: pass
        try: self.main.unbind("<Button-1>")
        except: pass

    # ─── SPLASH ──────────────────────────────────────────
    def _show_splash(self):
        self._clear(); self._unbind()
        self.hdr_right.configure(text="")
        self.foot_hint.configure(text="press any key")

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        tk.Label(f, text=BANNER, font=(FONT, 11), fg=AMBER, bg=BG, justify="left").pack()
        tk.Label(f, text="QUANTITATIVE TRADING PLATFORM", font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG).pack()
        tk.Frame(f, bg=BORDER, height=1, width=400).pack(pady=14)

        info = [
            (f"build {datetime.now().strftime('%Y.%m.%d')}  //  python {sys.version.split()[0]}", DIM),
            ("", DIM),
            ("ENGINES", AMBER_D),
            ("  AZOTH        systematic momentum           backtest", GREEN_D),
            ("  MERCURIO     order flow analysis            backtest", GREEN_D),
            ("  THOTH        sentiment quantified           backtest", GREEN_D),
            ("  NEWTON       pairs mean-reversion           backtest", GREEN_D),
            ("  HADRON       multi-strategy ensemble        backtest", GREEN_D),
            ("  PROMETEU     ML meta-ensemble               backtest", GREEN_D),
            ("  GRAVITON     live trading engine             live", GREEN_D),
            ("  NEUTRINO     cross-exchange arbitrage        live", GREEN_D),
            ("", DIM),
            ("TOOLS", AMBER_D),
            ("  DARWIN       adaptive strategy evolution", GREEN_D),
            ("  NEXUS        REST API server", GREEN_D),
            ("  CHRONOS      ML features (HMM/GARCH)", GREEN_D),
            ("", DIM),
            ("(c) 2026 AURUM Finance", DIM2),
        ]
        for txt, col in info:
            tk.Label(f, text=txt, font=(FONT, 8), fg=col, bg=BG, anchor="w").pack(anchor="w", padx=80)

        for ev in ("<Button-1>", "<Return>", "<space>"):
            cb = lambda e: self._show_menu("main")
            if ev == "<Button-1>":
                self.main.bind(ev, cb)
            else:
                self.bind(ev, cb)

    # ─── GENERIC MENU ────────────────────────────────────
    def _show_menu(self, menu_key, from_key=None):
        self._clear(); self._unbind()
        self.nav_stack.append(menu_key)
        items = MENU_TREE.get(menu_key, [])

        titles = {"main": "MAIN MENU", "backtest": "BACKTEST — SELECT ENGINE",
                  "live": "LIVE — SELECT MODE", "tools": "TOOLS"}
        self.hdr_right.configure(text=titles.get(menu_key, menu_key.upper()))

        back_target = {"backtest": "main", "live": "main", "tools": "main"}.get(menu_key)
        if back_target:
            self.foot_hint.configure(text="click or number to select  //  ESC back")
            self.bind("<Escape>", lambda e: self._show_menu("main"))
            self.bind("<BackSpace>", lambda e: self._show_menu("main"))
        else:
            self.foot_hint.configure(text="click or number to select  //  ESC quit")
            self.bind("<Escape>", lambda e: self._on_close())

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        title_text = titles.get(menu_key, menu_key.upper())
        tk.Label(f, text=f"] {title_text} [", font=(FONT, 13, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 20))

        for i, item in enumerate(items):
            num = i + 1
            color = item.get("color", AMBER)
            desc = item.get("desc", "")
            text = f"  [{num}]  {item['label']:<18} {desc}"

            if "script" in item:
                cmd = lambda it=item: self._run_engine(it)
            else:
                cmd = lambda k=item["key"]: self._show_menu(k)

            btn = self._make_btn(f, text, color, cmd)
            btn.pack(fill="x", padx=60, pady=2)
            self.bind(f"<Key-{num}>",
                      (lambda it=item: lambda e: self._run_engine(it))(item)
                      if "script" in item else
                      (lambda k=item["key"]: lambda e: self._show_menu(k))(item["key"]))

        # Back / Quit
        tk.Frame(f, bg="transparent", height=16).pack()
        if back_target:
            self._make_btn(f, "  [0]  BACK", DIM,
                           lambda: self._show_menu("main")).pack(fill="x", padx=60, pady=2)
            self.bind("<Key-0>", lambda e: self._show_menu("main"))
        else:
            self._make_btn(f, "  [0]  QUIT", DIM,
                           lambda: self._on_close()).pack(fill="x", padx=60, pady=2)
            self.bind("<Key-0>", lambda e: self._on_close())

    # ─── RUN ENGINE ──────────────────────────────────────
    def _run_engine(self, eng):
        self._clear(); self._unbind()
        color = eng.get("color", GREEN)
        label = eng["label"]
        self.hdr_right.configure(text=f"RUNNING: {label}", fg=color)
        self.foot_hint.configure(text="type input below and press ENTER  //  STOP to terminate  //  BACK to return")

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True)

        # Top bar
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x")
        tk.Label(top, text=f"  > {label}", font=(FONT, 10, "bold"), fg=color, bg=BG2).pack(side="left", pady=5, padx=4)

        def go_back():
            self._stop_engine()
            parent = None
            for mkey, items in MENU_TREE.items():
                for it in items:
                    if it.get("key") == eng["key"]:
                        parent = mkey
                        break
            self._show_menu(parent or "main")

        tk.Button(top, text="[ STOP ]", font=(FONT, 8, "bold"), fg=RED, bg=BG2,
                  activeforeground=RED, activebackground=BG3, border=0, cursor="hand2",
                  command=self._stop_engine).pack(side="right", padx=8, pady=5)
        tk.Button(top, text="[ BACK ]", font=(FONT, 8, "bold"), fg=DIM, bg=BG2,
                  activeforeground=WHITE, activebackground=BG3, border=0, cursor="hand2",
                  command=go_back).pack(side="right", pady=5)

        tk.Frame(f, bg=BORDER, height=1).pack(fill="x")

        # Console
        console_f = tk.Frame(f, bg=PANEL)
        console_f.pack(fill="both", expand=True)
        sb = tk.Scrollbar(console_f, bg=BG, troughcolor=BG, activebackground=DIM2, highlightthickness=0, bd=0)
        sb.pack(side="right", fill="y")
        self.console = tk.Text(console_f, bg=PANEL, fg=GREEN, font=(FONT, 9), wrap="word",
                                borderwidth=0, highlightthickness=0, insertbackground=GREEN,
                                padx=10, pady=8, state="disabled", cursor="arrow",
                                yscrollcommand=sb.set, selectbackground=SEL_BG, selectforeground=GREEN)
        self.console.pack(fill="both", expand=True)
        sb.config(command=self.console.yview)
        for tag, col in [("amber", AMBER), ("green", GREEN), ("red", RED), ("cyan", CYAN), ("dim", DIM), ("white", WHITE)]:
            self.console.tag_configure(tag, foreground=col)

        # Input bar
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x")
        inp_bar = tk.Frame(f, bg=BG2)
        inp_bar.pack(fill="x")
        tk.Label(inp_bar, text=" >", font=(FONT, 10, "bold"), fg=AMBER, bg=BG2).pack(side="left", padx=(8, 0), pady=5)
        self.inp = tk.Entry(inp_bar, bg=BG2, fg=GREEN, font=(FONT, 10), insertbackground=GREEN,
                             border=0, highlightthickness=0)
        self.inp.pack(side="left", fill="x", expand=True, padx=6, pady=5)
        self.inp.focus_set()
        self.inp.bind("<Return>", self._send_input)
        tk.Button(inp_bar, text="SEND", font=(FONT, 8, "bold"), fg=AMBER, bg=BG2,
                  activeforeground=WHITE, activebackground=BG3, border=0, cursor="hand2",
                  command=self._send_input).pack(side="right", padx=8, pady=5)

        # Header
        self._cprint(f"{'='*55}\n", "amber")
        self._cprint(f"  {label}  —  {eng.get('desc', '')}\n", "amber")
        self._cprint(f"  {datetime.now().strftime('%H:%M:%S')}  //  {ROOT}\n", "dim")
        self._cprint(f"{'='*55}\n\n", "amber")

        # Launch
        script = ROOT / eng["script"]
        if not script.exists():
            self._cprint(f"ERROR: {script} not found\n", "red")
            return

        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0

            self.process = subprocess.Popen(
                [sys.executable, "-u", str(script)],
                cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE, text=True, bufsize=1,
                encoding="utf-8", errors="replace",
                startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, env=env,
            )

            threading.Thread(target=self._read_output, daemon=True).start()
            self._poll_output()

        except Exception as e:
            self._cprint(f"FAILED: {e}\n", "red")

    def _send_input(self, event=None):
        text = self.inp.get()
        self.inp.delete(0, "end")
        if self.process and self.process.poll() is None and self.process.stdin:
            try:
                self.process.stdin.write(text + "\n")
                self.process.stdin.flush()
                self._cprint(f"> {text}\n", "amber")
            except Exception:
                pass

    def _read_output(self):
        try:
            for line in iter(self.process.stdout.readline, ""):
                if line:
                    self.output_queue.put(line)
            self.process.stdout.close()
        except Exception:
            pass
        self.output_queue.put(None)

    def _poll_output(self):
        try:
            for _ in range(50):  # drain up to 50 lines per tick
                line = self.output_queue.get_nowait()
                if line is None:
                    rc = self.process.poll() if self.process else -1
                    self._cprint(f"\n{'='*55}\n", "dim")
                    if rc == 0:
                        self._cprint(f"  Process exited OK\n", "green")
                    else:
                        self._cprint(f"  Process exited (code {rc})\n", "red")
                    self._cprint(f"{'='*55}\n", "dim")
                    self.hdr_right.configure(text="FINISHED", fg=DIM)
                    self.process = None
                    return
                else:
                    self._cprint(line)
        except queue.Empty:
            pass
        if self.process and self.process.poll() is None:
            self.after(30, self._poll_output)
        else:
            self.after(100, self._poll_output)

    def _cprint(self, text, tag="green"):
        self.console.configure(state="normal")
        self.console.insert("end", text, tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _stop_engine(self):
        if self.process and self.process.poll() is None:
            self._cprint("\n  >> TERMINATING...\n", "red")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self._cprint("  >> STOPPED\n", "red")
            self.hdr_right.configure(text="STOPPED", fg=RED)
            self.process = None

    # ─── DATA BROWSER ────────────────────────────────────
    def _show_data(self):
        self._clear(); self._unbind()
        self.hdr_right.configure(text="DATA & REPORTS")
        self.foot_hint.configure(text="ESC back")
        self.bind("<Escape>", lambda e: self._show_menu("main"))
        self.bind("<BackSpace>", lambda e: self._show_menu("main"))

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True, padx=20, pady=16)

        tk.Label(f, text="] DATA & REPORTS [", font=(FONT, 13, "bold"), fg=AMBER, bg=BG).pack(anchor="w", pady=(0, 12))

        # Scan data directory for reports
        data_dir = ROOT / "data"
        reports = []
        if data_dir.exists():
            for rpt in sorted(data_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if "reports" in str(rpt) or "darwin" in str(rpt):
                    rel = rpt.relative_to(ROOT)
                    size = rpt.stat().st_size
                    mtime = datetime.fromtimestamp(rpt.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    reports.append((str(rel), mtime, size))

        if not reports:
            tk.Label(f, text="  No reports found. Run a backtest first.", font=(FONT, 9), fg=DIM, bg=BG).pack(anchor="w")
        else:
            # Scrollable list
            canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
            sb = tk.Scrollbar(f, orient="vertical", command=canvas.yview, bg=BG, troughcolor=BG)
            scroll_f = tk.Frame(canvas, bg=BG)
            scroll_f.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=scroll_f, anchor="nw")
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")

            # Header
            hdr_text = f"  {'FILE':<55} {'DATE':<18} {'SIZE':>8}"
            tk.Label(scroll_f, text=hdr_text, font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(fill="x")
            tk.Frame(scroll_f, bg=BORDER, height=1).pack(fill="x", pady=2)

            for path, mtime, size in reports[:50]:
                sz = f"{size/1024:.0f}KB" if size > 1024 else f"{size}B"
                text = f"  {path:<55} {mtime:<18} {sz:>8}"
                lbl = tk.Label(scroll_f, text=text, font=(FONT, 8), fg=GREEN_D, bg=BG, anchor="w", cursor="hand2")
                lbl.pack(fill="x")
                lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=BG3, fg=GREEN))
                lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=BG, fg=GREEN_D))
                lbl.bind("<Button-1>", lambda e, p=path: self._open_file(p))

        tk.Frame(f, bg="transparent", height=16).pack()
        self._make_btn(f, "  [0]  BACK", DIM, lambda: self._show_menu("main")).pack(anchor="w")

    def _open_file(self, path):
        full = ROOT / path
        if sys.platform == "win32":
            os.startfile(str(full))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(full)])
        else:
            subprocess.run(["xdg-open", str(full)])

    # ─── PROCESSES ───────────────────────────────────────
    def _show_procs(self):
        self._clear(); self._unbind()
        self.hdr_right.configure(text="PROCESSES")
        self.foot_hint.configure(text="ESC back")
        self.bind("<Escape>", lambda e: self._show_menu("main"))
        self.bind("<BackSpace>", lambda e: self._show_menu("main"))

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        tk.Label(f, text="] RUNNING PROCESSES [", font=(FONT, 13, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 16))

        try:
            from core.proc import list_procs, stop_proc
            procs = [p for p in list_procs() if p.get("alive")]
        except Exception:
            procs = []

        if not procs:
            tk.Label(f, text="  No engines running.", font=(FONT, 10), fg=DIM, bg=BG).pack(pady=8)
        else:
            for i, p in enumerate(procs):
                eng_name = p.get("engine", "?").upper()
                pid = p.get("pid", "?")
                text = f"  [{i+1}]  {eng_name:<14} PID {pid}"
                row = tk.Frame(f, bg=BG)
                row.pack(fill="x", padx=60, pady=2)
                tk.Label(row, text=text, font=(FONT, 10), fg=GREEN, bg=BG, anchor="w").pack(side="left")
                tk.Button(row, text="STOP", font=(FONT, 8, "bold"), fg=RED, bg=BG,
                          activeforeground=WHITE, activebackground=BG3, border=0, cursor="hand2",
                          command=lambda pid=pid: (stop_proc(pid), self._show_procs())).pack(side="right")

        tk.Frame(f, bg="transparent", height=16).pack()
        self._make_btn(f, "  [0]  BACK", DIM, lambda: self._show_menu("main")).pack(fill="x", padx=60)

    # ─── MENU DISPATCH (override for data/procs) ────────
    def _show_menu(self, menu_key):
        if menu_key == "data":
            self._show_data(); return
        if menu_key == "procs":
            self._show_procs(); return
        self._show_menu_generic(menu_key)

    def _show_menu_generic(self, menu_key):
        self._clear(); self._unbind()
        items = MENU_TREE.get(menu_key, [])
        titles = {"main": "MAIN MENU", "backtest": "BACKTEST — SELECT ENGINE",
                  "live": "LIVE — SELECT MODE", "tools": "TOOLS"}
        self.hdr_right.configure(text=titles.get(menu_key, menu_key.upper()), fg=DIM)

        is_sub = menu_key != "main"
        if is_sub:
            self.foot_hint.configure(text="click or number to select  //  ESC back")
            self.bind("<Escape>", lambda e: self._show_menu("main"))
            self.bind("<BackSpace>", lambda e: self._show_menu("main"))
        else:
            self.foot_hint.configure(text="click or number to select  //  ESC quit")
            self.bind("<Escape>", lambda e: self._on_close())

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        tk.Label(f, text=f"] {titles.get(menu_key, menu_key.upper())} [",
                 font=(FONT, 13, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 20))

        for i, item in enumerate(items):
            num = i + 1
            color = item.get("color", AMBER)
            desc = item.get("desc", "")
            text = f"  [{num}]  {item['label']:<18} {desc}"

            has_script = "script" in item
            if has_script:
                cmd = lambda it=item: self._run_engine(it)
            else:
                cmd = lambda k=item["key"]: self._show_menu(k)

            self._make_btn(f, text, color, cmd).pack(fill="x", padx=60, pady=2)

            if has_script:
                self.bind(f"<Key-{num}>", lambda e, it=item: self._run_engine(it))
            else:
                self.bind(f"<Key-{num}>", lambda e, k=item["key"]: self._show_menu(k))

        tk.Frame(f, bg="transparent", height=16).pack()
        if is_sub:
            self._make_btn(f, "  [0]  BACK", DIM, lambda: self._show_menu("main")).pack(fill="x", padx=60, pady=2)
            self.bind("<Key-0>", lambda e: self._show_menu("main"))
        else:
            self._make_btn(f, "  [0]  QUIT", DIM, lambda: self._on_close()).pack(fill="x", padx=60, pady=2)
            self.bind("<Key-0>", lambda e: self._on_close())

    # ─── UI HELPERS ──────────────────────────────────────
    def _make_btn(self, parent, text, color, command):
        btn = tk.Label(parent, text=text, font=(FONT, 10), fg=color, bg=BG,
                       anchor="w", cursor="hand2", padx=8, pady=5)
        btn.bind("<Enter>", lambda e: btn.configure(bg=BG3, fg=WHITE if color == DIM else color))
        btn.bind("<Leave>", lambda e: btn.configure(bg=BG, fg=color))
        btn.bind("<Button-1>", lambda e: command())
        return btn

    # ─── CLOSE ───────────────────────────────────────────
    def _on_close(self):
        if self.process and self.process.poll() is None:
            r = messagebox.askyesnocancel("AURUM", "Engine running. Stop before closing?")
            if r is None: return
            if r:
                self.process.terminate()
                try: self.process.wait(timeout=3)
                except: self.process.kill()
        self.destroy()


if __name__ == "__main__":
    app = AurumApp()
    app.mainloop()
