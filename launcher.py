#!/usr/bin/env python3
"""
AURUM Finance — Terminal v3
Bloomberg Terminal meets Half-Life console.
"""
import os, sys, subprocess, threading, queue, time, json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import messagebox

# ═══════════════════════════════════════════════════════════
# BLOOMBERG x CS 1.6 THEME
# ═══════════════════════════════════════════════════════════
BG       = "#0a0a0a"
BG2      = "#0f0f0f"
BG3      = "#181818"
PANEL    = "#0c0c0c"
BORDER   = "#222222"
BORDER2  = "#333333"
AMBER    = "#ff8c00"       # bloomberg orange
AMBER_B  = "#ffaa33"       # bright amber
AMBER_D  = "#8a5500"
GREEN    = "#00c853"       # bloomberg green (positive)
GREEN_D  = "#007830"
RED      = "#ff1744"       # bloomberg red (negative)
RED_D    = "#991030"
CYAN     = "#00bcd4"
BLUE     = "#448aff"
PURPLE   = "#b388ff"
YELLOW   = "#ffd600"
WHITE    = "#d0d0d0"
DIM      = "#4a4a4a"
DIM2     = "#2a2a2a"
DIM3     = "#1a1a1a"
SEL_BG   = "#1a1400"

FONT     = "Consolas"

# ═══════════════════════════════════════════════════════════
# MARKET DATA (async fetch)
# ═══════════════════════════════════════════════════════════
_TICKER_DATA = {}
_TICKER_LOCK = threading.Lock()

def _fetch_tickers():
    """Background thread: fetch top crypto prices from Binance."""
    import requests
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    while True:
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=8)
            if r.status_code == 200:
                data = {t["symbol"]: t for t in r.json()}
                with _TICKER_LOCK:
                    for sym in symbols:
                        if sym in data:
                            _TICKER_DATA[sym] = {
                                "price": float(data[sym]["lastPrice"]),
                                "chg":   float(data[sym]["priceChangePercent"]),
                            }
        except Exception:
            pass
        time.sleep(10)


def _get_ticker_str():
    """Format ticker tape string."""
    with _TICKER_LOCK:
        if not _TICKER_DATA:
            return "  connecting..."
        parts = []
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]:
            d = _TICKER_DATA.get(sym)
            if d:
                name = sym.replace("USDT", "")
                chg = d["chg"]
                arrow = "+" if chg >= 0 else ""
                parts.append(f"{name} {d['price']:,.2f} {arrow}{chg:.1f}%")
        return "   ".join(parts)


# ═══════════════════════════════════════════════════════════
# ENGINE REGISTRY
# ═══════════════════════════════════════════════════════════
MENU_TREE = {
    "main": [
        {"key": "backtest", "label": "BACKTEST",       "desc": "Historical strategy simulation",  "color": AMBER,  "fkey": "F1"},
        {"key": "live",     "label": "LIVE",           "desc": "Paper / Demo / Testnet / Real",   "color": RED,    "fkey": "F2"},
        {"key": "tools",    "label": "TOOLS",          "desc": "Darwin / API / Chronos",          "color": PURPLE, "fkey": "F3"},
        {"key": "data",     "label": "DATA",           "desc": "Reports & logs browser",          "color": CYAN,   "fkey": "F4"},
        {"key": "procs",    "label": "PROCS",          "desc": "Running engine manager",          "color": GREEN,  "fkey": "F5"},
        {"key": "config",   "label": "CONFIG",         "desc": "Keys, VPS, VPN, Telegram",        "color": YELLOW, "fkey": "F6"},
    ],
    "backtest": [
        {"key": "azoth",      "label": "AZOTH",      "desc": "Systematic momentum / Graviton fractal",  "color": AMBER,  "script": "engines/backtest.py"},
        {"key": "mercurio",   "label": "MERCURIO",   "desc": "Order flow CVD + volume imbalance",       "color": GREEN,  "script": "engines/mercurio.py"},
        {"key": "thoth",      "label": "THOTH",      "desc": "Sentiment: funding + OI + LS ratio",      "color": CYAN,   "script": "engines/thoth.py"},
        {"key": "newton",     "label": "NEWTON",     "desc": "Pairs cointegration mean-reversion",      "color": BLUE,   "script": "engines/newton.py"},
        {"key": "hadron",     "label": "HADRON",     "desc": "Multi-strategy ensemble orchestrator",    "color": PURPLE, "script": "engines/multistrategy.py"},
        {"key": "prometeu",   "label": "PROMETEU",   "desc": "ML meta-ensemble learning",               "color": YELLOW, "script": "engines/prometeu.py"},
    ],
    "live": [
        {"key": "paper",    "label": "PAPER",      "desc": "Simulated execution — no real orders",   "color": GREEN,  "script": "engines/live.py"},
        {"key": "demo",     "label": "DEMO",       "desc": "Binance Futures Demo API",               "color": AMBER,  "script": "engines/live.py"},
        {"key": "testnet",  "label": "TESTNET",    "desc": "Binance Futures Testnet",                "color": CYAN,   "script": "engines/live.py"},
        {"key": "real",     "label": "LIVE",        "desc": "REAL CAPITAL — use with extreme care",  "color": RED,    "script": "engines/live.py"},
        {"key": "arb",      "label": "ARBITRAGE",  "desc": "Cross-exchange funding rate capture",    "color": PURPLE, "script": "engines/arbitrage.py"},
    ],
    "tools": [
        {"key": "darwin",   "label": "DARWIN",    "desc": "Adaptive strategy evolution engine",  "color": PURPLE, "script": "engines/darwin.py"},
        {"key": "api",      "label": "NEXUS",     "desc": "REST API + WebSocket (port 8000)",   "color": AMBER,  "script": "run_api.py"},
        {"key": "chronos",  "label": "CHRONOS",   "desc": "ML features: HMM regime + GARCH",    "color": CYAN,   "script": "core/chronos.py"},
    ],
}

BANNER = [
    "    ╔═╗ ╦ ╦ ╦═╗ ╦ ╦ ╔╦╗",
    "    ╠═╣ ║ ║ ╠╦╝ ║ ║ ║║║",
    "    ╩ ╩ ╚═╝ ╩╚═ ╚═╝ ╩ ╩",
]
BANNER_COLORS = ["#ffa000", "#ff8c00", "#cc7000"]


class AurumTerminal(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AURUM Terminal")
        self.configure(bg=BG)
        self.geometry("1020x700")
        self.minsize(900, 600)

        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists():
                self.iconbitmap(str(ico))
        except Exception:
            pass

        self.process = None
        self.output_queue = queue.Queue()
        self._blink_on = True

        # Start market data feed
        threading.Thread(target=_fetch_tickers, daemon=True).start()

        self._build()
        self._show_splash()
        self._tick_clock()
        self._tick_ticker()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ─── BUILD CHROME ────────────────────────────────────
    def _build(self):
        # ── TICKER BAR (bloomberg style) ──
        self.ticker_bar = tk.Frame(self, bg=BG2, height=20)
        self.ticker_bar.pack(fill="x")
        self.ticker_bar.pack_propagate(False)

        tc = tk.Frame(self.ticker_bar, bg=BG2)
        tc.pack(fill="both", expand=True, padx=8)

        self.ticker_lbl = tk.Label(tc, text="  connecting...", font=(FONT, 7),
                                    fg=DIM, bg=BG2, anchor="w")
        self.ticker_lbl.pack(side="left")

        self.clock_lbl = tk.Label(tc, text="", font=(FONT, 7, "bold"),
                                   fg=AMBER_D, bg=BG2)
        self.clock_lbl.pack(side="right")

        # ── AMBER LINE ──
        tk.Frame(self, bg=AMBER, height=1).pack(fill="x")

        # ── HEADER ──
        hdr = tk.Frame(self, bg=BG, height=28)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        hc = tk.Frame(hdr, bg=BG)
        hc.pack(fill="both", expand=True, padx=12)

        tk.Label(hc, text="AURUM", font=(FONT, 9, "bold"), fg=AMBER, bg=BG).pack(side="left")
        tk.Label(hc, text="FINANCE", font=(FONT, 9), fg=AMBER_D, bg=BG).pack(side="left", padx=(2, 0))
        self.hdr_path = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG)
        self.hdr_path.pack(side="left", padx=(12, 0))
        self.hdr_status = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG)
        self.hdr_status.pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── MAIN ──
        self.main = tk.Frame(self, bg=BG)
        self.main.pack(fill="both", expand=True)

        # ── FOOTER / F-KEYS BAR ──
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        self.fbar = tk.Frame(self, bg=BG2, height=22)
        self.fbar.pack(fill="x")
        self.fbar.pack_propagate(False)

    def _set_fkeys(self, items):
        """Set F-key bar items. items = [(label, color), ...]"""
        for w in self.fbar.winfo_children():
            w.destroy()
        fc = tk.Frame(self.fbar, bg=BG2)
        fc.pack(fill="both", expand=True, padx=6)
        for label, color in items:
            tk.Label(fc, text=label, font=(FONT, 7, "bold"), fg=color, bg=BG2).pack(side="left", padx=6, pady=3)

    def _clear(self):
        for w in self.main.winfo_children():
            w.destroy()

    def _unbind(self):
        for k in ("<Return>", "<space>", "<Escape>", "<BackSpace>",
                   *[f"<Key-{i}>" for i in range(10)],
                   *[f"<F{i}>" for i in range(1, 13)]):
            try: self.unbind(k)
            except: pass
        try: self.main.unbind("<Button-1>")
        except: pass

    # ─── TICKERS ─────────────────────────────────────────
    def _tick_clock(self):
        now = datetime.now().strftime("%H:%M:%S")
        self.clock_lbl.configure(text=now)
        self.after(1000, self._tick_clock)

    def _tick_ticker(self):
        raw = _get_ticker_str()
        # Color the ticker
        self.ticker_lbl.configure(text=raw)
        # Alternate dim/bright for activity feel
        with _TICKER_LOCK:
            if _TICKER_DATA:
                self.ticker_lbl.configure(fg=DIM if not self._blink_on else AMBER_D)
                self._blink_on = not self._blink_on
        self.after(5000, self._tick_ticker)

    # ─── SPLASH ──────────────────────────────────────────
    def _show_splash(self):
        self._clear(); self._unbind()
        self.hdr_path.configure(text="")
        self.hdr_status.configure(text="READY", fg=GREEN_D)
        self._set_fkeys([
            ("F1 BACKTEST", AMBER_D), ("F2 LIVE", RED_D), ("F3 TOOLS", DIM),
            ("F4 DATA", DIM), ("F5 PROCS", DIM), ("ENTER CONTINUE", AMBER_D),
        ])

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        # Banner
        for i, line in enumerate(BANNER):
            tk.Label(f, text=line, font=(FONT, 14, "bold"), fg=BANNER_COLORS[i], bg=BG).pack()

        tk.Label(f, text="QUANTITATIVE TRADING TERMINAL", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=BG).pack(pady=(2, 0))

        # Separator
        sep_f = tk.Frame(f, bg=BG)
        sep_f.pack(pady=10)
        tk.Frame(sep_f, bg=AMBER_D, height=1, width=420).pack()

        # System info panel (bloomberg style)
        info_f = tk.Frame(f, bg=BG)
        info_f.pack()

        def _irow(parent, label, value, color=DIM):
            r = tk.Frame(parent, bg=BG)
            r.pack(fill="x", padx=40)
            tk.Label(r, text=f"  {label}", font=(FONT, 8), fg=DIM, bg=BG, width=18, anchor="w").pack(side="left")
            tk.Label(r, text=value, font=(FONT, 8, "bold"), fg=color, bg=BG, anchor="w").pack(side="left")

        _irow(info_f, "BUILD", datetime.now().strftime("%Y.%m.%d"), AMBER_D)
        _irow(info_f, "PYTHON", sys.version.split()[0], DIM)
        _irow(info_f, "PLATFORM", f"win32 x64" if sys.platform == "win32" else sys.platform, DIM)
        _irow(info_f, "ENGINES", "10 registered", GREEN_D)
        _irow(info_f, "STATUS", "ALL SYSTEMS NOMINAL", GREEN)

        tk.Frame(f, bg=BG, height=12).pack()

        # Engine table
        tbl_f = tk.Frame(f, bg=BG)
        tbl_f.pack()

        hdr_text = f"  {'ENGINE':<12} {'TYPE':<12} {'DESCRIPTION':<40}"
        tk.Label(tbl_f, text=hdr_text, font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(fill="x", padx=30)
        tk.Frame(tbl_f, bg=DIM2, height=1).pack(fill="x", padx=30, pady=1)

        engines = [
            ("AZOTH",     "BACKTEST", "Systematic momentum fractal", AMBER),
            ("MERCURIO",  "BACKTEST", "Order flow CVD analysis", GREEN),
            ("THOTH",     "BACKTEST", "Sentiment quantified", CYAN),
            ("NEWTON",    "BACKTEST", "Pairs mean-reversion", BLUE),
            ("HADRON",    "BACKTEST", "Multi-strategy ensemble", PURPLE),
            ("PROMETEU",  "BACKTEST", "ML meta-ensemble", YELLOW),
            ("GRAVITON",  "LIVE",     "Live trading engine", RED),
            ("NEUTRINO",  "LIVE",     "Cross-exchange arbitrage", PURPLE),
            ("DARWIN",    "TOOL",     "Strategy evolution", PURPLE),
            ("NEXUS",     "TOOL",     "REST API server", AMBER),
        ]
        for name, typ, desc, color in engines:
            text = f"  {name:<12} {typ:<12} {desc:<40}"
            tk.Label(tbl_f, text=text, font=(FONT, 7), fg=DIM, bg=BG, anchor="w").pack(fill="x", padx=30)

        tk.Frame(f, bg=BG, height=16).pack()
        tk.Label(f, text="(c) 2026 AURUM Finance Ltd. All rights reserved.",
                 font=(FONT, 7), fg=DIM2, bg=BG).pack()

        # Bindings
        for ev in ("<Button-1>", "<Return>", "<space>"):
            if ev == "<Button-1>":
                self.main.bind(ev, lambda e: self._show_menu("main"))
            else:
                self.bind(ev, lambda e: self._show_menu("main"))

        # F-key shortcuts from splash
        self.bind("<F1>", lambda e: self._show_menu("backtest"))
        self.bind("<F2>", lambda e: self._show_menu("live"))
        self.bind("<F3>", lambda e: self._show_menu("tools"))
        self.bind("<F4>", lambda e: self._show_data())
        self.bind("<F5>", lambda e: self._show_procs())

    # ─── GENERIC MENU ────────────────────────────────────
    def _show_menu(self, menu_key):
        if menu_key == "data":   self._show_data(); return
        if menu_key == "procs":  self._show_procs(); return
        if menu_key == "config": self._show_config(); return

        self._clear(); self._unbind()
        items = MENU_TREE.get(menu_key, [])
        titles = {"main": "MAIN", "backtest": "BACKTEST", "live": "LIVE", "tools": "TOOLS"}
        title = titles.get(menu_key, menu_key.upper())

        self.hdr_path.configure(text=f"> {title}")
        self.hdr_status.configure(text="SELECT", fg=AMBER_D)

        is_sub = menu_key != "main"

        # F-keys
        if menu_key == "main":
            fkeys = [(f"F{i+1} {it['label']}", it.get("color", DIM)) for i, it in enumerate(items)]
            fkeys.append(("ESC QUIT", DIM))
        else:
            fkeys = [("ESC BACK", AMBER_D), ("0 BACK", DIM)]
        self._set_fkeys(fkeys)

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        # Title with bloomberg bracket style
        tk.Label(f, text=f"< {title} >", font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG).pack(pady=(0, 6))

        # Subtitle
        subs = {"main": "Select operation mode", "backtest": "Select engine to backtest",
                "live": "Select trading mode", "tools": "Select tool to run"}
        tk.Label(f, text=subs.get(menu_key, ""), font=(FONT, 8), fg=DIM, bg=BG).pack(pady=(0, 16))

        for i, item in enumerate(items):
            num = i + 1
            color = item.get("color", AMBER)
            desc = item.get("desc", "")
            fkey = item.get("fkey", "")

            # Bloomberg style: number + label + description on right
            btn_f = tk.Frame(f, bg=BG, cursor="hand2")
            btn_f.pack(fill="x", padx=50, pady=1)

            num_lbl = tk.Label(btn_f, text=f" {num} ", font=(FONT, 9, "bold"),
                               fg=BG, bg=color, width=3)
            num_lbl.pack(side="left")

            name_lbl = tk.Label(btn_f, text=f"  {item['label']}", font=(FONT, 10, "bold"),
                                fg=WHITE, bg=BG3, anchor="w", padx=8, pady=5)
            name_lbl.pack(side="left")

            desc_lbl = tk.Label(btn_f, text=desc, font=(FONT, 8),
                                fg=DIM, bg=BG3, anchor="w", padx=8, pady=5)
            desc_lbl.pack(side="left", fill="x", expand=True)

            if fkey:
                tk.Label(btn_f, text=fkey, font=(FONT, 7, "bold"), fg=DIM2, bg=BG3,
                         padx=6, pady=5).pack(side="right")

            # Determine action
            has_script = "script" in item
            if has_script:
                cmd = lambda it=item: self._run_engine(it)
            else:
                cmd = lambda k=item["key"]: self._show_menu(k)

            # Hover
            widgets = [btn_f, num_lbl, name_lbl, desc_lbl]
            for w in widgets:
                w.bind("<Enter>", lambda e, ws=widgets, c=color: [
                    ws[0].configure(bg=BG3),
                    ws[2].configure(fg=c, bg=BG3),
                ])
                w.bind("<Leave>", lambda e, ws=widgets: [
                    ws[0].configure(bg=BG),
                    ws[2].configure(fg=WHITE, bg=BG3),
                ])
                w.bind("<Button-1>", lambda e, c=cmd: c())

            # Key binding
            if has_script:
                self.bind(f"<Key-{num}>", lambda e, it=item: self._run_engine(it))
            else:
                self.bind(f"<Key-{num}>", lambda e, k=item["key"]: self._show_menu(k))

            # F-key binding for main menu
            if fkey and menu_key == "main":
                fn = int(fkey.replace("F", ""))
                if has_script:
                    self.bind(f"<F{fn}>", lambda e, it=item: self._run_engine(it))
                else:
                    self.bind(f"<F{fn}>", lambda e, k=item["key"]: self._show_menu(k))

        # Back / Quit
        tk.Frame(f, bg="transparent", height=12).pack()
        if is_sub:
            self.bind("<Escape>", lambda e: self._show_menu("main"))
            self.bind("<BackSpace>", lambda e: self._show_menu("main"))
            self.bind("<Key-0>", lambda e: self._show_menu("main"))
            back_f = tk.Frame(f, bg=BG, cursor="hand2")
            back_f.pack(fill="x", padx=50, pady=1)
            tk.Label(back_f, text=" 0 ", font=(FONT, 9, "bold"), fg=WHITE, bg=DIM2, width=3).pack(side="left")
            bl = tk.Label(back_f, text="  BACK", font=(FONT, 10), fg=DIM, bg=BG3, anchor="w", padx=8, pady=5)
            bl.pack(side="left", fill="x", expand=True)
            for w in [back_f, bl]:
                w.bind("<Button-1>", lambda e: self._show_menu("main"))
        else:
            self.bind("<Escape>", lambda e: self._on_close())
            self.bind("<Key-0>", lambda e: self._on_close())

    # ─── RUN ENGINE ──────────────────────────────────────
    def _run_engine(self, eng):
        self._clear(); self._unbind()
        color = eng.get("color", GREEN)
        label = eng["label"]
        self.hdr_path.configure(text=f"> {label}")
        self.hdr_status.configure(text="RUNNING", fg=GREEN)
        self._set_fkeys([("STOP", RED), ("BACK", DIM), ("TYPE INPUT BELOW + ENTER", AMBER_D)])

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True)

        # Top status bar (bloomberg style)
        top = tk.Frame(f, bg=BG2)
        top.pack(fill="x")

        # Left: engine info
        tk.Label(top, text=f" {label} ", font=(FONT, 8, "bold"), fg=BG, bg=color).pack(side="left", padx=(6, 4), pady=4)
        tk.Label(top, text=eng.get("desc", ""), font=(FONT, 8), fg=DIM, bg=BG2).pack(side="left", pady=4)

        # Right: controls
        tk.Button(top, text=" STOP ", font=(FONT, 7, "bold"), fg=RED, bg=BG2,
                  activeforeground=WHITE, activebackground=RED_D, border=0, cursor="hand2",
                  command=self._stop_engine).pack(side="right", padx=4, pady=4)

        def go_back():
            self._stop_engine()
            parent = None
            for mkey, items in MENU_TREE.items():
                for it in items:
                    if it.get("key") == eng["key"]:
                        parent = mkey; break
            self._show_menu(parent or "main")

        tk.Button(top, text=" BACK ", font=(FONT, 7, "bold"), fg=DIM, bg=BG2,
                  activeforeground=WHITE, activebackground=BG3, border=0, cursor="hand2",
                  command=go_back).pack(side="right", pady=4)

        tk.Frame(f, bg=color, height=1).pack(fill="x")

        # Console
        con_f = tk.Frame(f, bg=PANEL)
        con_f.pack(fill="both", expand=True)
        sb = tk.Scrollbar(con_f, bg=BG, troughcolor=BG, activebackground=DIM2,
                           highlightthickness=0, bd=0)
        sb.pack(side="right", fill="y")
        self.console = tk.Text(con_f, bg=PANEL, fg=GREEN, font=(FONT, 9), wrap="word",
                                borderwidth=0, highlightthickness=0, insertbackground=GREEN,
                                padx=10, pady=6, state="disabled", cursor="arrow",
                                yscrollcommand=sb.set, selectbackground=SEL_BG, selectforeground=GREEN)
        self.console.pack(fill="both", expand=True)
        sb.config(command=self.console.yview)
        for tag, col in [("amber", AMBER), ("green", GREEN), ("red", RED), ("cyan", CYAN),
                         ("dim", DIM), ("white", WHITE), ("yellow", YELLOW)]:
            self.console.tag_configure(tag, foreground=col)

        # Input bar
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x")
        inp_bar = tk.Frame(f, bg=BG2)
        inp_bar.pack(fill="x")
        tk.Label(inp_bar, text=" >", font=(FONT, 10, "bold"), fg=AMBER, bg=BG2).pack(side="left", padx=(6, 0), pady=4)
        self.inp = tk.Entry(inp_bar, bg=BG2, fg=GREEN, font=(FONT, 10), insertbackground=AMBER,
                             border=0, highlightthickness=0)
        self.inp.pack(side="left", fill="x", expand=True, padx=6, pady=4)
        self.inp.focus_set()
        self.inp.bind("<Return>", self._send_input)

        # Header in console
        ts = datetime.now().strftime("%H:%M:%S")
        self._cprint(f" {label} ", "amber")
        self._cprint(f"  {eng.get('desc', '')}  //  {ts}\n", "dim")
        self._cprint(f"{'─'*60}\n", "dim")

        # Launch
        script = ROOT / eng["script"]
        if not script.exists():
            self._cprint(f"ERROR: {script} not found\n", "red"); return

        try:
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0
            self.process = subprocess.Popen(
                [sys.executable, "-u", str(script)], cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, env=env,
            )
            threading.Thread(target=self._read_output, daemon=True).start()
            self._poll_output()
        except Exception as e:
            self._cprint(f"FAILED: {e}\n", "red")

    def _send_input(self, event=None):
        text = self.inp.get(); self.inp.delete(0, "end")
        if self.process and self.process.poll() is None and self.process.stdin:
            try:
                self.process.stdin.write(text + "\n"); self.process.stdin.flush()
                self._cprint(f"> {text}\n", "amber")
            except: pass

    def _read_output(self):
        try:
            for line in iter(self.process.stdout.readline, ""):
                if line: self.output_queue.put(line)
            self.process.stdout.close()
        except: pass
        self.output_queue.put(None)

    def _poll_output(self):
        try:
            for _ in range(80):
                line = self.output_queue.get_nowait()
                if line is None:
                    rc = self.process.poll() if self.process else -1
                    self._cprint(f"\n{'─'*60}\n", "dim")
                    self._cprint(f"  EXIT CODE {rc}\n", "green" if rc == 0 else "red")
                    self._cprint(f"{'─'*60}\n", "dim")
                    self.hdr_status.configure(text="DONE" if rc == 0 else f"EXIT {rc}", fg=GREEN if rc == 0 else RED)
                    self.process = None; return
                else:
                    self._cprint(line)
        except queue.Empty: pass
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
            self._cprint("\n  >> SIGTERM\n", "red")
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except: self.process.kill()
            self._cprint("  >> STOPPED\n", "red")
            self.hdr_status.configure(text="STOPPED", fg=RED)
            self.process = None

    # ─── DATA BROWSER ────────────────────────────────────
    def _show_data(self):
        self._clear(); self._unbind()
        self.hdr_path.configure(text="> DATA")
        self.hdr_status.configure(text="BROWSE", fg=CYAN)
        self._set_fkeys([("ESC BACK", AMBER_D), ("CLICK TO OPEN", DIM)])
        self.bind("<Escape>", lambda e: self._show_menu("main"))
        self.bind("<BackSpace>", lambda e: self._show_menu("main"))

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True, padx=16, pady=12)

        tk.Label(f, text="< DATA & REPORTS >", font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(anchor="w", pady=(0, 8))

        data_dir = ROOT / "data"
        reports = []
        if data_dir.exists():
            for rpt in sorted(data_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if "reports" in str(rpt) or "darwin" in str(rpt):
                    reports.append(rpt)

        # Scrollable
        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(f, orient="vertical", command=canvas.yview)
        scroll_f = tk.Frame(canvas, bg=BG)
        scroll_f.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_f, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        # Table header
        hdr = f"  {'FILE':<60} {'MODIFIED':<18} {'SIZE':>8}"
        tk.Label(scroll_f, text=hdr, font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(fill="x")
        tk.Frame(scroll_f, bg=DIM2, height=1).pack(fill="x", pady=1)

        if not reports:
            tk.Label(scroll_f, text="  No reports. Run a backtest first.", font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=8)
        else:
            for rpt in reports[:60]:
                rel = str(rpt.relative_to(ROOT))
                mt = datetime.fromtimestamp(rpt.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                sz = rpt.stat().st_size
                szs = f"{sz/1024:.0f}K" if sz > 1024 else f"{sz}B"
                text = f"  {rel:<60} {mt:<18} {szs:>8}"
                lbl = tk.Label(scroll_f, text=text, font=(FONT, 7), fg=GREEN_D, bg=BG, anchor="w", cursor="hand2")
                lbl.pack(fill="x")
                lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=BG3, fg=GREEN))
                lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=BG, fg=GREEN_D))
                lbl.bind("<Button-1>", lambda e, p=rpt: self._open_file(p))

    def _open_file(self, path):
        if sys.platform == "win32": os.startfile(str(path))
        elif sys.platform == "darwin": subprocess.run(["open", str(path)])
        else: subprocess.run(["xdg-open", str(path)])

    # ─── PROCESSES ───────────────────────────────────────
    def _show_procs(self):
        self._clear(); self._unbind()
        self.hdr_path.configure(text="> PROCS")
        self.hdr_status.configure(text="MANAGE", fg=GREEN)
        self._set_fkeys([("ESC BACK", AMBER_D), ("R REFRESH", DIM)])
        self.bind("<Escape>", lambda e: self._show_menu("main"))
        self.bind("<BackSpace>", lambda e: self._show_menu("main"))
        self.bind("<Key-r>", lambda e: self._show_procs())

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        tk.Label(f, text="< RUNNING PROCESSES >", font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 12))

        try:
            from core.proc import list_procs, stop_proc
            procs = [p for p in list_procs() if p.get("alive")]
        except: procs = []

        if not procs:
            tk.Label(f, text="  No engines running.", font=(FONT, 10), fg=DIM, bg=BG).pack(pady=8)
        else:
            for i, p in enumerate(procs):
                eng = p.get("engine", "?").upper()
                pid = p.get("pid", "?")
                row = tk.Frame(f, bg=BG3)
                row.pack(fill="x", padx=50, pady=2)
                tk.Label(row, text=f" {eng} ", font=(FONT, 8, "bold"), fg=BG, bg=GREEN).pack(side="left")
                tk.Label(row, text=f"  PID {pid}", font=(FONT, 9), fg=WHITE, bg=BG3, padx=8, pady=4).pack(side="left")
                tk.Button(row, text=" STOP ", font=(FONT, 7, "bold"), fg=RED, bg=BG3,
                          activeforeground=WHITE, activebackground=RED_D, border=0, cursor="hand2",
                          command=lambda pid=pid: (stop_proc(pid), self._show_procs())).pack(side="right", padx=4, pady=2)

    # ─── CONFIG ──────────────────────────────────────────
    def _show_config(self):
        self._clear(); self._unbind()
        self.hdr_path.configure(text="> CONFIG")
        self.hdr_status.configure(text="SETTINGS", fg=YELLOW)
        self._set_fkeys([("ESC BACK", AMBER_D)])
        self.bind("<Escape>", lambda e: self._show_menu("main"))
        self.bind("<BackSpace>", lambda e: self._show_menu("main"))

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        tk.Label(f, text="< CONFIG >", font=(FONT, 14, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 6))
        tk.Label(f, text="Manage API keys, VPS, VPN, Telegram", font=(FONT, 8), fg=DIM, bg=BG).pack(pady=(0, 16))

        config_items = [
            {"num": 1, "label": "API KEYS",     "desc": "Binance Demo / Testnet / Live keys",    "color": AMBER,  "cmd": self._cfg_keys},
            {"num": 2, "label": "TELEGRAM",      "desc": "Bot token & chat ID",                   "color": CYAN,   "cmd": self._cfg_telegram},
            {"num": 3, "label": "VPS",           "desc": "Remote server SSH connection",           "color": GREEN,  "cmd": self._cfg_vps},
            {"num": 4, "label": "VPN",           "desc": "WireGuard / OpenVPN tunnel",             "color": PURPLE, "cmd": self._cfg_vpn},
            {"num": 5, "label": "DEPLOY",        "desc": "Deploy AURUM to VPS via SSH",            "color": RED,    "cmd": self._cfg_deploy},
        ]

        for item in config_items:
            btn_f = tk.Frame(f, bg=BG, cursor="hand2")
            btn_f.pack(fill="x", padx=50, pady=1)
            tk.Label(btn_f, text=f" {item['num']} ", font=(FONT, 9, "bold"), fg=BG, bg=item["color"], width=3).pack(side="left")
            nl = tk.Label(btn_f, text=f"  {item['label']}", font=(FONT, 10, "bold"), fg=WHITE, bg=BG3, anchor="w", padx=8, pady=5)
            nl.pack(side="left")
            dl = tk.Label(btn_f, text=item["desc"], font=(FONT, 8), fg=DIM, bg=BG3, anchor="w", padx=8, pady=5)
            dl.pack(side="left", fill="x", expand=True)
            for w in [btn_f, nl, dl]:
                w.bind("<Enter>", lambda e, ws=[btn_f, nl, dl], c=item["color"]: ws[1].configure(fg=c))
                w.bind("<Leave>", lambda e, ws=[btn_f, nl, dl]: ws[1].configure(fg=WHITE))
                w.bind("<Button-1>", lambda e, c=item["cmd"]: c())
            self.bind(f"<Key-{item['num']}>", lambda e, c=item["cmd"]: c())

        tk.Frame(f, bg="transparent", height=12).pack()
        back_f = tk.Frame(f, bg=BG, cursor="hand2")
        back_f.pack(fill="x", padx=50, pady=1)
        tk.Label(back_f, text=" 0 ", font=(FONT, 9, "bold"), fg=WHITE, bg=DIM2, width=3).pack(side="left")
        bl = tk.Label(back_f, text="  BACK", font=(FONT, 10), fg=DIM, bg=BG3, anchor="w", padx=8, pady=5)
        bl.pack(side="left", fill="x", expand=True)
        for w in [back_f, bl]:
            w.bind("<Button-1>", lambda e: self._show_menu("main"))
        self.bind("<Key-0>", lambda e: self._show_menu("main"))

    def _cfg_editor(self, title, fields, save_callback):
        """Generic config editor with labeled input fields."""
        self._clear(); self._unbind()
        self.hdr_path.configure(text=f"> CONFIG > {title}")
        self._set_fkeys([("ESC BACK", AMBER_D), ("CTRL+S SAVE", GREEN)])
        self.bind("<Escape>", lambda e: self._show_config())
        self.bind("<BackSpace>", lambda e: self._show_config())

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        tk.Label(f, text=f"< {title} >", font=(FONT, 13, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 16))

        entries = {}
        for field in fields:
            row = tk.Frame(f, bg=BG)
            row.pack(fill="x", padx=60, pady=3)
            tk.Label(row, text=f"  {field['label']}", font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, width=18, anchor="w").pack(side="left")
            e = tk.Entry(row, bg=BG3, fg=GREEN, font=(FONT, 9), insertbackground=AMBER,
                         border=0, highlightthickness=1, highlightcolor=AMBER_D, highlightbackground=BORDER,
                         width=50)
            e.pack(side="left", fill="x", expand=True, padx=(4, 0), ipady=4)
            if field.get("value"):
                e.insert(0, field["value"])
            if field.get("show") == "*":
                e.configure(show="*")
            entries[field["key"]] = e
            if field.get("hint"):
                tk.Label(row, text=field["hint"], font=(FONT, 7), fg=DIM2, bg=BG).pack(side="right", padx=4)

        tk.Frame(f, bg="transparent", height=16).pack()

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack()

        def save():
            values = {k: e.get().strip() for k, e in entries.items()}
            save_callback(values)
            self.hdr_status.configure(text="SAVED", fg=GREEN)
            self.after(1500, lambda: self.hdr_status.configure(text="", fg=DIM))

        save_btn = tk.Label(btn_row, text="  SAVE  ", font=(FONT, 10, "bold"), fg=BG, bg=GREEN,
                            cursor="hand2", padx=16, pady=4)
        save_btn.pack(side="left", padx=4)
        save_btn.bind("<Button-1>", lambda e: save())

        cancel_btn = tk.Label(btn_row, text="  CANCEL  ", font=(FONT, 10), fg=DIM, bg=BG3,
                              cursor="hand2", padx=16, pady=4)
        cancel_btn.pack(side="left", padx=4)
        cancel_btn.bind("<Button-1>", lambda e: self._show_config())

        self.bind("<Control-s>", lambda e: save())

    def _load_keys(self):
        """Load keys.json."""
        kp = ROOT / "config" / "keys.json"
        if kp.exists():
            try:
                with open(kp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except: pass
        return {"demo": {"api_key": "", "api_secret": ""}, "testnet": {"api_key": "", "api_secret": ""},
                "live": {"api_key": "", "api_secret": ""}, "telegram": {"bot_token": "", "chat_id": ""}}

    def _save_keys(self, data):
        """Save keys.json."""
        kp = ROOT / "config" / "keys.json"
        kp.parent.mkdir(parents=True, exist_ok=True)
        with open(kp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    def _cfg_keys(self):
        keys = self._load_keys()
        fields = [
            {"key": "demo_key",     "label": "DEMO API KEY",     "value": keys.get("demo", {}).get("api_key", ""),     "show": "*"},
            {"key": "demo_secret",  "label": "DEMO SECRET",      "value": keys.get("demo", {}).get("api_secret", ""),  "show": "*"},
            {"key": "test_key",     "label": "TESTNET KEY",      "value": keys.get("testnet", {}).get("api_key", ""),  "show": "*"},
            {"key": "test_secret",  "label": "TESTNET SECRET",   "value": keys.get("testnet", {}).get("api_secret", ""), "show": "*"},
            {"key": "live_key",     "label": "LIVE KEY",         "value": keys.get("live", {}).get("api_key", ""),     "show": "*", "hint": "REAL CAPITAL"},
            {"key": "live_secret",  "label": "LIVE SECRET",      "value": keys.get("live", {}).get("api_secret", ""),  "show": "*", "hint": "REAL CAPITAL"},
        ]
        def save(vals):
            keys["demo"]["api_key"] = vals["demo_key"]
            keys["demo"]["api_secret"] = vals["demo_secret"]
            keys["testnet"]["api_key"] = vals["test_key"]
            keys["testnet"]["api_secret"] = vals["test_secret"]
            keys["live"]["api_key"] = vals["live_key"]
            keys["live"]["api_secret"] = vals["live_secret"]
            self._save_keys(keys)
        self._cfg_editor("API KEYS — BINANCE", fields, save)

    def _cfg_telegram(self):
        keys = self._load_keys()
        tg = keys.get("telegram", {})
        fields = [
            {"key": "bot_token", "label": "BOT TOKEN",   "value": tg.get("bot_token", ""), "show": "*", "hint": "@BotFather"},
            {"key": "chat_id",   "label": "CHAT ID",     "value": tg.get("chat_id", ""),   "hint": "@userinfobot"},
        ]
        def save(vals):
            keys.setdefault("telegram", {})
            keys["telegram"]["bot_token"] = vals["bot_token"]
            keys["telegram"]["chat_id"] = vals["chat_id"]
            self._save_keys(keys)
        self._cfg_editor("TELEGRAM", fields, save)

    def _cfg_vps(self):
        # Load VPS config from a separate file
        vps_path = ROOT / "config" / "vps.json"
        vps = {}
        if vps_path.exists():
            try:
                with open(vps_path, "r", encoding="utf-8") as f:
                    vps = json.load(f)
            except: pass
        fields = [
            {"key": "host",     "label": "HOST / IP",      "value": vps.get("host", ""),     "hint": "ex: 185.199.10.1"},
            {"key": "port",     "label": "SSH PORT",        "value": vps.get("port", "22"),   "hint": "default 22"},
            {"key": "user",     "label": "USERNAME",        "value": vps.get("user", "root")},
            {"key": "key_path", "label": "SSH KEY PATH",    "value": vps.get("key_path", ""), "hint": "C:\\Users\\...\\id_rsa"},
            {"key": "password", "label": "PASSWORD",        "value": "",                       "show": "*", "hint": "or use SSH key"},
            {"key": "remote_dir", "label": "REMOTE DIR",    "value": vps.get("remote_dir", "/opt/aurum")},
        ]
        def save(vals):
            vps_data = {k: v for k, v in vals.items() if k != "password"}
            # Don't save password to disk — it's for one-time use
            vps_path.parent.mkdir(parents=True, exist_ok=True)
            with open(vps_path, "w", encoding="utf-8") as f:
                json.dump(vps_data, f, indent=4)
        self._cfg_editor("VPS — SSH CONNECTION", fields, save)

    def _cfg_vpn(self):
        vpn_path = ROOT / "config" / "vpn.json"
        vpn = {}
        if vpn_path.exists():
            try:
                with open(vpn_path, "r", encoding="utf-8") as f:
                    vpn = json.load(f)
            except: pass
        fields = [
            {"key": "type",        "label": "VPN TYPE",       "value": vpn.get("type", "wireguard"), "hint": "wireguard / openvpn"},
            {"key": "config_path", "label": "CONFIG FILE",    "value": vpn.get("config_path", ""),   "hint": "path to .conf or .ovpn"},
            {"key": "server",      "label": "SERVER IP",      "value": vpn.get("server", ""),        "hint": "VPN endpoint"},
            {"key": "private_key", "label": "PRIVATE KEY",    "value": vpn.get("private_key", ""),   "show": "*"},
            {"key": "dns",         "label": "DNS",            "value": vpn.get("dns", "1.1.1.1"),    "hint": "Cloudflare default"},
        ]
        def save(vals):
            vpn_path.parent.mkdir(parents=True, exist_ok=True)
            with open(vpn_path, "w", encoding="utf-8") as f:
                json.dump(vals, f, indent=4)
        self._cfg_editor("VPN — TUNNEL CONFIG", fields, save)

    def _cfg_deploy(self):
        """Deploy to VPS — runs rsync/scp over SSH."""
        self._clear(); self._unbind()
        self.hdr_path.configure(text="> CONFIG > DEPLOY")
        self._set_fkeys([("ESC BACK", AMBER_D)])
        self.bind("<Escape>", lambda e: self._show_config())

        f = tk.Frame(self.main, bg=BG)
        f.pack(expand=True)

        tk.Label(f, text="< DEPLOY TO VPS >", font=(FONT, 13, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 12))

        # Load VPS config
        vps_path = ROOT / "config" / "vps.json"
        if not vps_path.exists():
            tk.Label(f, text="  VPS not configured. Go to CONFIG > VPS first.", font=(FONT, 10), fg=RED, bg=BG).pack(pady=8)
            self._make_btn(f, "  [0]  BACK", DIM, self._show_config).pack(fill="x", padx=60)
            return

        with open(vps_path, "r") as fv:
            vps = json.load(fv)

        host = vps.get("host", "?")
        user = vps.get("user", "root")
        remote = vps.get("remote_dir", "/opt/aurum")
        port = vps.get("port", "22")
        key_path = vps.get("key_path", "")

        tk.Label(f, text=f"  Target: {user}@{host}:{remote}", font=(FONT, 9), fg=GREEN, bg=BG).pack(anchor="w", padx=60, pady=2)
        tk.Label(f, text=f"  Port: {port}  Key: {key_path or 'password'}", font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", padx=60, pady=2)

        tk.Frame(f, bg="transparent", height=16).pack()

        info_lines = [
            "This will sync the project to your VPS via SSH.",
            "Files excluded: data/, node_modules/, .git/, config/keys.json",
            "",
            "On the VPS, run:  python launcher.py  or  python -m aurum_finance",
        ]
        for line in info_lines:
            tk.Label(f, text=f"  {line}", font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(anchor="w", padx=60)

        tk.Frame(f, bg="transparent", height=16).pack()

        def do_deploy():
            # Build rsync/scp command
            key_arg = f'-i "{key_path}"' if key_path else ""
            ssh_opts = f'-e "ssh -p {port} {key_arg}"' if key_arg else f'-e "ssh -p {port}"'
            excludes = '--exclude=data --exclude=node_modules --exclude=.git --exclude=config/keys.json --exclude=__pycache__ --exclude=*.pyc --exclude=dist --exclude=build'
            cmd = f'rsync -avz {excludes} {ssh_opts} "{ROOT}/" {user}@{host}:{remote}/'

            # Run as engine
            self._run_engine({
                "key": "deploy", "label": "DEPLOY", "desc": f"Syncing to {host}",
                "color": RED, "script": "__deploy__",
            })
            # Override — run the command directly
            # Actually, let's show the command and let user confirm
            self._clear()
            self._show_config()
            messagebox.showinfo("Deploy Command",
                f"Run this in your terminal:\n\n{cmd}\n\nOr install rsync via: winget install rsync")

        deploy_btn = tk.Label(f, text="  DEPLOY NOW  ", font=(FONT, 10, "bold"), fg=BG, bg=RED,
                              cursor="hand2", padx=16, pady=6)
        deploy_btn.pack(pady=4)
        deploy_btn.bind("<Button-1>", lambda e: do_deploy())

        self._make_btn(f, "  [0]  BACK", DIM, self._show_config).pack(fill="x", padx=60, pady=(12, 0))

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
    app = AurumTerminal()
    app.mainloop()
