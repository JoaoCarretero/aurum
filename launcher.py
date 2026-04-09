#!/usr/bin/env python3
"""
AURUM Finance — Terminal v4
Bloomberg Terminal aesthetic. Clean, functional, no bugs.
"""
import os, sys, subprocess, threading, queue, json, time
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tkinter as tk
from tkinter import messagebox

# ═══════════════════════════════════════════════════════════
# BLOOMBERG PALETTE — amber on black, minimal color
# ═══════════════════════════════════════════════════════════
BG      = "#0a0a0a"
BG2     = "#101010"
BG3     = "#181818"
PANEL   = "#0c0c0c"
BORDER  = "#1e1e1e"
AMBER   = "#ff8c00"
AMBER_D = "#7a4400"
AMBER_B = "#ffaa33"
WHITE   = "#c8c8c8"
DIM     = "#4a4a4a"
DIM2    = "#2a2a2a"
GREEN   = "#00c040"
RED     = "#e03030"

FONT    = "Consolas"

# ═══════════════════════════════════════════════════════════
# TICKER (live prices)
# ═══════════════════════════════════════════════════════════
_TD = {}
_TL = threading.Lock()
def _fetch():
    import requests
    while True:
        try:
            r = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr", timeout=8)
            if r.status_code == 200:
                d = {t["symbol"]: t for t in r.json()}
                with _TL:
                    for s in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]:
                        if s in d: _TD[s] = {"p": float(d[s]["lastPrice"]), "c": float(d[s]["priceChangePercent"])}
        except: pass
        time.sleep(12)

def _ticker_str():
    with _TL:
        if not _TD: return "connecting..."
        return "   ".join(f"{s.replace('USDT','')} {_TD[s]['p']:,.2f} {'+'if _TD[s]['c']>=0 else ''}{_TD[s]['c']:.1f}%" for s in ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"] if s in _TD)

# ═══════════════════════════════════════════════════════════
# MENUS
# ═══════════════════════════════════════════════════════════
MAIN_MENU = [
    ("BACKTEST",     "backtest",  "Historical strategy simulation"),
    ("LIVE",         "live",      "Paper / Demo / Testnet / Real"),
    ("TOOLS",        "tools",     "Darwin / API / Chronos"),
    ("DATA",         "data",      "Reports & logs browser"),
    ("PROCESSES",    "procs",     "Running engine manager"),
    ("CONFIG",       "config",    "Keys, VPS, VPN, Telegram"),
]

SUB_MENUS = {
    "backtest": [
        ("AZOTH",      "engines/backtest.py",      "Systematic momentum — Graviton fractal engine"),
        ("MERCURIO",   "engines/mercurio.py",       "Order flow — CVD divergence + volume imbalance"),
        ("THOTH",      "engines/thoth.py",          "Sentiment — funding rate + OI + LS ratio"),
        ("NEWTON",     "engines/newton.py",         "Pairs — cointegration mean-reversion"),
        ("HADRON",     "engines/multistrategy.py",  "Ensemble — multi-strategy orchestrator"),
        ("PROMETEU",   "engines/prometeu.py",       "ML — meta-ensemble learning"),
    ],
    "live": [
        ("PAPER",      "engines/live.py",           "Simulated execution — no real orders"),
        ("DEMO",       "engines/live.py",           "Binance Futures Demo API"),
        ("TESTNET",    "engines/live.py",           "Binance Futures Testnet"),
        ("LIVE",       "engines/live.py",           "REAL CAPITAL — extreme care"),
        ("ARBITRAGE",  "engines/arbitrage.py",      "Cross-exchange funding rate capture"),
    ],
    "tools": [
        ("DARWIN",     "engines/darwin.py",         "Adaptive strategy evolution"),
        ("NEXUS API",  "run_api.py",               "REST API + WebSocket (port 8000)"),
        ("CHRONOS",    "core/chronos.py",           "ML features test — HMM + GARCH"),
    ],
}

BANNER = """
    ╔═╗ ╦ ╦ ╦═╗ ╦ ╦ ╔╦╗
    ╠═╣ ║ ║ ╠╦╝ ║ ║ ║║║
    ╩ ╩ ╚═╝ ╩╚═ ╚═╝ ╩ ╩
"""

# ═══════════════════════════════════════════════════════════
# STRATEGY BRIEFINGS — philosophy + logic before execution
# ═══════════════════════════════════════════════════════════
BRIEFINGS = {
    "AZOTH": {
        "philosophy": "Markets are fractal. The same patterns that form on a 15m chart echo on the 4h and daily. AZOTH reads this self-similarity — detecting trend structure across scales, scoring confluence, and entering only when the math converges.",
        "logic": [
            "Detect macro regime via BTC slope200 (BULL / BEAR / CHOP)",
            "Identify swing structure fractals on multiple timeframes",
            "Score signals with Omega 5D: struct + flow + cascade + momentum + pullback",
            "Size positions with Kelly fractional + drawdown scaling",
            "CHOP mode: mean-reversion via Bollinger + RSI when market is lateral",
        ],
        "edge": "Trend-following with fractal confirmation. Profitable in directional markets.",
        "risk": "Underperforms in extended chop. Max drawdown historically ~5%.",
    },
    "MERCURIO": {
        "philosophy": "Price is the last thing to move. Before price breaks, volume shifts. Taker buy/sell pressure, cumulative delta, and order flow imbalances reveal intent before the candle closes. MERCURIO listens to what the market whispers.",
        "logic": [
            "Compute Cumulative Volume Delta (CVD) — taker buy minus taker sell",
            "Detect CVD divergence: price makes new high but CVD doesn't (distribution)",
            "Measure volume imbalance: taker buy ratio over rolling window",
            "Identify liquidation cascades via volume + ATR spikes",
            "Composite score: 30% CVD div + 25% imbalance + 30% structure + 15% trend",
        ],
        "edge": "Sees institutional flow before retail. Works in all regimes.",
        "risk": "False signals in low-volume markets. Requires liquid pairs.",
    },
    "THOTH": {
        "philosophy": "When everyone is greedy, be fearful. When everyone is fearful, be greedy. THOTH quantifies crowd sentiment — funding rates, open interest shifts, and long/short ratios — to find contrarian extremes where the crowd is wrong.",
        "logic": [
            "Z-score of funding rate over 30 periods of 8h — extreme funding = reversal",
            "Delta Open Interest vs price — rising OI + falling price = forced selling",
            "Long/Short ratio contrarian — ratio > 2.0 = too many longs, fade them",
            "Composite: 40% funding + 30% OI + 30% LS ratio",
            "Direction from sentiment extremes, confirmed by price structure",
        ],
        "edge": "Catches reversals at sentiment extremes. High win rate.",
        "risk": "Sentiment can stay extreme longer than expected. Timing risk.",
    },
    "NEWTON": {
        "philosophy": "Two connected assets that diverge must converge. Cointegration is not correlation — it's a mathematical bond. When the spread between two cointegrated pairs stretches beyond normal, gravity pulls it back. NEWTON trades this gravity.",
        "logic": [
            "Engle-Granger cointegration test across all symbol pairs",
            "Calculate spread z-score with rolling OLS half-life estimation",
            "Entry when |z-score| > 2.0 — spread is 2 standard deviations from mean",
            "Exit when z-score crosses 0 — mean reversion complete",
            "Stop when |z-score| > 3.5 — cointegration may have broken",
        ],
        "edge": "Market-neutral. Profits regardless of market direction.",
        "risk": "Cointegration can break permanently. Requires careful pair selection.",
    },
    "HADRON": {
        "philosophy": "No single strategy survives all market conditions. But a portfolio of uncorrelated strategies, each strong in different regimes, creates an edge that persists. HADRON orchestrates — combining signals, managing correlation, allocating capital where the math says to.",
        "logic": [
            "Runs all engines simultaneously on the same data",
            "Aggregates signals at the trade level — not prediction level",
            "Weights by rolling Sortino ratio per engine per regime",
            "Kill-switch: pauses any engine with Sortino(20) < -0.5",
            "Portfolio-level drawdown management across all positions",
        ],
        "edge": "Smoothest equity curve. Diversified across strategies.",
        "risk": "If all strategies correlate in a crash, diversification fails.",
    },
    "PROMETEU": {
        "philosophy": "Can a machine learn which strategy will dominate the next market phase? PROMETEU uses the trades of all engines as training data, learning patterns of when each strategy performs best — and allocating before the regime changes.",
        "logic": [
            "Collect trade history from all engines as features",
            "Build target: which engine has best R-multiple in next N trades",
            "Train gradient-boosted model on market regime + performance features",
            "Predict optimal allocation per engine for current conditions",
            "Rebalance portfolio weights based on ML predictions",
        ],
        "edge": "Adapts allocation proactively, not reactively.",
        "risk": "ML overfitting. Requires diverse training data to generalize.",
    },
}

BRIEFINGS["PAPER"] = BRIEFINGS["DEMO"] = BRIEFINGS["TESTNET"] = BRIEFINGS["LIVE"] = {
    "philosophy": "The market is a living system. Live trading is the final test — where your algorithms meet reality. Every tick is a vote, every trade a thesis. Paper mode lets you observe without risk. Demo validates execution. Live is where conviction meets capital.",
    "logic": [
        "Connect to Binance Futures API (paper/demo/testnet/live)",
        "Seed historical data for all symbols — build indicator state",
        "Run scan cycle every 15m candle — same logic as backtest",
        "Execute orders via REST API with HMAC-signed requests",
        "Monitor positions: trailing stops, funding, kill-switch",
    ],
    "edge": "Same edge as backtest, validated on live market microstructure.",
    "risk": "Slippage, API latency, exchange downtime. Start with paper/demo.",
}

BRIEFINGS["ARBITRAGE"] = {
    "philosophy": "In an efficient market, the same asset should cost the same everywhere. But markets aren't efficient — funding rates diverge, prices lag between exchanges, and liquidity fragments. NEUTRINO captures these inefficiencies: delta-neutral, mathematical, pure arbitrage.",
    "logic": [
        "Scan 10 venues simultaneously: Binance, Bybit, OKX, Gate, Bitget + 5 more",
        "Detect 4 types: funding rate arb, spot-perp basis, cross-venue spread, internal",
        "Score with Omega v2: edge × fill probability × adversarial discount",
        "Execute split orders (5 parts) with latency profiling per venue",
        "Hedge monitor ensures delta-neutral at all times",
    ],
    "edge": "Market-neutral. Profits from exchange inefficiency, not direction.",
    "risk": "Execution risk, withdrawal delays between venues, funding rate changes.",
}

BRIEFINGS["DARWIN"] = {
    "philosophy": "Natural selection applied to trading strategies. Each engine is an organism competing for capital. The fittest survive, the weak are pruned. Over time, the portfolio evolves — adapting to the market as it changes.",
    "logic": [
        "Evaluate fitness per engine: Sortino (40%) + Profit Factor (20%) + Win Rate (20%) + Stability (20%)",
        "Rank engines and allocate capital: top performer 35%, above median 25%, below 10%",
        "Kill zone: 3 consecutive negative windows → engine paused at 5% minimum",
        "Mutation: every 100 trades, perturb parameters ±10% and test improvement",
        "Crossover: combine DNA of two high-performing engines in same regime",
    ],
    "edge": "Adapts portfolio allocation automatically based on real performance.",
    "risk": "Requires sufficient trade history. May over-allocate to lucky streaks.",
}

BRIEFINGS["NEXUS API"] = {
    "philosophy": "Control is freedom. NEXUS opens the AURUM platform to the world — REST API, WebSocket streaming, JWT authentication. Your phone, your dashboard, your integrations. The terminal expands beyond the terminal.",
    "logic": [
        "FastAPI server on port 8000 with Swagger docs at /docs",
        "JWT authentication with bcrypt password hashing",
        "Endpoints: auth, account, trading, analytics, live WebSocket",
        "SQLite database for users, trades, deposits, engine state",
        "Real-time streaming of engine status and trade events",
    ],
    "edge": "Remote control. Mobile access. Third-party integrations.",
    "risk": "Expose only on localhost or behind VPN. Never on public internet without auth.",
}

BRIEFINGS["CHRONOS"] = {
    "philosophy": "Traditional indicators look at what happened. CHRONOS looks at the invisible structure of time — hidden regimes, volatility clusters, momentum decay, fractal dimensions. The patterns that exist beneath the candles.",
    "logic": [
        "Hidden Markov Model: P(bull), P(bear), P(chop) as continuous probabilities",
        "GARCH(1,1): forecast volatility for next 4-8 candles proactively",
        "Momentum decay: exponential decay rate — detect fading trends before reversal",
        "Hurst exponent: H>0.5 trending, H<0.5 mean-reverting, H≈0.5 random walk",
        "Seasonality: hour × day-of-week edge scoring from historical patterns",
    ],
    "edge": "Sees regime transitions before they complete. Proactive sizing.",
    "risk": "ML dependencies (hmmlearn, arch). Falls back gracefully if not installed.",
}

BASKETS_UI = [
    ("DEFAULT",  "", ["BNB","INJ","LINK","RENDER","NEAR","SUI","ARB","SAND","XRP","FET","OP"]),
    ("TOP 12",   "2", ["BTC","ETH","BNB","SOL","XRP","DOGE","ADA","AVAX","LINK","DOT","MATIC","SUI"]),
    ("DEFI",     "3", ["LINK","AAVE","UNI","MKR","SNX","COMP","CRV","SUSHI","INJ","JUP"]),
    ("LAYER 1",  "4", ["BTC","ETH","SOL","AVAX","NEAR","SUI","APT","ATOM","DOT","ALGO"]),
    ("LAYER 2",  "5", ["ARB","OP","MATIC","STRK","MANTA","IMX"]),
    ("AI",       "6", ["FET","RENDER","TAO","NEAR","WLD","ARKM"]),
    ("MEME",     "7", ["DOGE","SHIB","PEPE","BONK","FLOKI","WIF"]),
    ("MAJORS",   "8", ["BTC","ETH","BNB","SOL","XRP"]),
    ("BLUECHIP", "9", ["BTC","ETH","BNB","SOL","XRP","ADA","AVAX","LINK","DOT","MATIC",
                        "ATOM","NEAR","INJ","ARB","OP","SUI","RENDER","FET","SAND","AAVE"]),
]

PERIODS_UI = [
    ("30 DAYS",   "~1 month — quick validation",     "30"),
    ("90 DAYS",   "~3 months — standard backtest",    "90"),
    ("180 DAYS",  "~6 months — medium-term",          "180"),
    ("365 DAYS",  "~1 year — full cycle test",        "365"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AURUM Terminal")
        self.configure(bg=BG)
        self.geometry("960x660")
        self.minsize(860, 560)

        # Taskbar icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("aurum.finance.terminal")
        except: pass
        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists(): self.iconbitmap(str(ico))
        except: pass

        self.proc = None
        self.oq = queue.Queue()
        self.history = []  # nav history for back

        threading.Thread(target=_fetch, daemon=True).start()
        self._chrome()
        self._splash()
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._quit)

    # ─── CHROME ──────────────────────────────────────────
    def _chrome(self):
        # Ticker
        tb = tk.Frame(self, bg=BG2, height=18); tb.pack(fill="x"); tb.pack_propagate(False)
        tbc = tk.Frame(tb, bg=BG2); tbc.pack(fill="both", expand=True, padx=10)
        self.t_lbl = tk.Label(tbc, text="", font=(FONT, 7), fg=DIM, bg=BG2); self.t_lbl.pack(side="left")
        self.t_clk = tk.Label(tbc, text="", font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG2); self.t_clk.pack(side="right")

        tk.Frame(self, bg=AMBER, height=1).pack(fill="x")

        # Header
        hd = tk.Frame(self, bg=BG, height=26); hd.pack(fill="x"); hd.pack_propagate(False)
        hc = tk.Frame(hd, bg=BG); hc.pack(fill="both", expand=True, padx=10)
        tk.Label(hc, text="AURUM", font=(FONT, 8, "bold"), fg=AMBER, bg=BG).pack(side="left")
        self.h_path = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG); self.h_path.pack(side="left", padx=(8,0))
        self.h_stat = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG); self.h_stat.pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        self.main = tk.Frame(self, bg=BG); self.main.pack(fill="both", expand=True)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Footer
        ft = tk.Frame(self, bg=BG2, height=20); ft.pack(fill="x"); ft.pack_propagate(False)
        fc = tk.Frame(ft, bg=BG2); fc.pack(fill="both", expand=True, padx=10)
        self.f_lbl = tk.Label(fc, text="", font=(FONT, 7), fg=DIM, bg=BG2); self.f_lbl.pack(side="right")
        tk.Label(fc, text="v2.0", font=(FONT, 7), fg=DIM2, bg=BG2).pack(side="left")

    def _clr(self):
        for w in self.main.winfo_children(): w.destroy()

    def _unbind(self):
        for k in ["<Return>","<space>","<Escape>","<BackSpace>",
                   *[f"<Key-{i}>" for i in range(10)],
                   *[f"<F{i}>" for i in range(1, 13)]]:
            try: self.unbind(k)
            except: pass
        try: self.main.unbind("<Button-1>")
        except: pass
        self._in_engine = False

    def _kb(self, key, callback):
        """Safe key bind — skips if an Entry widget has focus."""
        def wrapper(event):
            focused = self.focus_get()
            if focused and isinstance(focused, tk.Entry):
                return  # let Entry handle the keystroke
            callback()
        self.bind(key, wrapper)

    def _tick(self):
        self.t_clk.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.t_lbl.configure(text=_ticker_str(), fg=AMBER_D)
        self.after(3000, self._tick)

    # ─── SPLASH ──────────────────────────────────────────
    def _splash(self):
        self._clr(); self._unbind(); self.history.clear()
        self.h_path.configure(text=""); self.h_stat.configure(text="READY", fg=GREEN)
        self.f_lbl.configure(text="ENTER continue  |  F1-F6 direct access")

        f = tk.Frame(self.main, bg=BG); f.pack(expand=True)
        tk.Label(f, text=BANNER, font=(FONT, 13, "bold"), fg=AMBER, bg=BG, justify="left").pack()
        tk.Label(f, text="QUANTITATIVE TRADING TERMINAL", font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG).pack()
        tk.Frame(f, bg=BORDER, height=1, width=380).pack(pady=12)

        # System block
        for txt, c in [
            (f"BUILD {datetime.now().strftime('%Y.%m.%d')}   PYTHON {sys.version.split()[0]}   ENGINES 10", DIM),
            ("", DIM),
            ("ENGINE       MODE       DESCRIPTION", AMBER_D),
            ("─"*56, DIM2),
            ("AZOTH        BACKTEST   Systematic momentum fractal", DIM),
            ("MERCURIO     BACKTEST   Order flow CVD analysis", DIM),
            ("THOTH        BACKTEST   Sentiment quantified", DIM),
            ("NEWTON       BACKTEST   Pairs mean-reversion", DIM),
            ("HADRON       BACKTEST   Multi-strategy ensemble", DIM),
            ("PROMETEU     BACKTEST   ML meta-ensemble", DIM),
            ("GRAVITON     LIVE       Live trading engine", DIM),
            ("NEUTRINO     LIVE       Cross-exchange arbitrage", DIM),
            ("DARWIN       TOOL       Strategy evolution", DIM),
            ("NEXUS        TOOL       REST API server", DIM),
        ]:
            tk.Label(f, text=f"  {txt}", font=(FONT, 7), fg=c, bg=BG, anchor="w").pack(anchor="w", padx=70)

        tk.Frame(f, bg=BG, height=12).pack()
        tk.Label(f, text="(c) 2026 AURUM Finance", font=(FONT, 7), fg=DIM2, bg=BG).pack()

        for ev in ["<Button-1>","<Return>","<space>"]:
            if ev == "<Button-1>": self.main.bind(ev, lambda e: self._menu("main"))
            else: self._kb(ev, lambda: self._menu("main"))
        for i, (_, key, _) in enumerate(MAIN_MENU):
            self._kb(f"<F{i+1}>", (lambda k=key: lambda: self._menu(k) if k not in ("data","procs","config") else self._special(k))(key))

    # ─── MENU ────────────────────────────────────────────
    def _menu(self, key):
        if key in ("data", "procs", "config"):
            self._special(key); return

        self._clr(); self._unbind()
        self.h_stat.configure(text="SELECT", fg=AMBER_D)

        if key == "main":
            self.history.clear()
            items = [(n, k, d) for n, k, d in MAIN_MENU]
            title = "MAIN"
            self.h_path.configure(text="")
            self.f_lbl.configure(text="ESC quit  |  number to select")
            self._kb("<Escape>", self._quit)
        else:
            self.history = ["main"]
            items = [(n, s, d) for n, s, d in SUB_MENUS.get(key, [])]
            title = key.upper()
            self.h_path.configure(text=f"> {title}")
            self.f_lbl.configure(text="ESC back  |  number to select  |  0 back")
            self._kb("<Escape>", lambda: self._menu("main"))
            self._kb("<BackSpace>", lambda: self._menu("main"))
            self._kb("<Key-0>", lambda: self._menu("main"))

        # ─── MAIN MENU: Fibonacci design ─────────────────
        if key == "main":
            f = tk.Frame(self.main, bg=BG); f.pack(fill="both", expand=True)

            # Fibonacci spiral overlay (canvas behind everything)
            fib_canvas = tk.Canvas(f, bg=BG, highlightthickness=0, width=800, height=500)
            fib_canvas.place(relx=0.5, rely=0.5, anchor="center")

            # Golden ratio proportions
            phi = 1.618
            cx, cy = 400, 250

            # Fibonacci arcs (subtle, decorative)
            fib_sizes = [21, 34, 55, 89, 144, 233]
            for i, r in enumerate(fib_sizes):
                opacity_hex = ["08", "06", "05", "04", "03", "02"][i]
                fib_canvas.create_arc(cx - r, cy - r, cx + r, cy + r,
                    start=90 * i, extent=90, outline=f"#ff8c00",
                    width=1, style="arc", dash=(2, 4 + i))

            # Corner ornaments — golden ratio rectangles
            for ox, oy, anchor in [(24, 24, "nw"), (776, 24, "ne"), (24, 476, "sw"), (776, 476, "se")]:
                # Small golden rect (phi proportioned)
                w, h = 34, int(34 / phi)
                x0 = ox if "w" in anchor else ox - w
                y0 = oy if "n" in anchor else oy - h
                fib_canvas.create_rectangle(x0, y0, x0 + w, y0 + h, outline=AMBER_D, width=1, dash=(1, 3))
                # Dot at corner
                dx = x0 if "w" in anchor else x0 + w
                dy = y0 if "n" in anchor else y0 + h
                fib_canvas.create_oval(dx - 2, dy - 2, dx + 2, dy + 2, fill=AMBER_D, outline="")

            # Horizontal golden lines connecting the grid
            for y_off in [-120, -48, 24, 96, 168]:
                y = cy + y_off
                fib_canvas.create_line(80, y, 720, y, fill=BORDER, width=1, dash=(1, 8))
                # Fibonacci tick marks at phi positions
                for px in [0.236, 0.382, 0.5, 0.618, 0.786]:
                    tx = 80 + px * 640
                    fib_canvas.create_line(tx, y - 3, tx, y + 3, fill=DIM2, width=1)

            # Vertical guide lines at phi ratios
            for px in [0.382, 0.618]:
                x = 80 + px * 640
                fib_canvas.create_line(x, cy - 140, x, cy + 200, fill=BORDER, width=1, dash=(1, 12))

            # Golden spiral hint (quarter arcs)
            fib_canvas.create_arc(cx - 89, cy - 89, cx + 89, cy + 89,
                start=0, extent=90, outline=AMBER_D, width=1, dash=(3, 6))
            fib_canvas.create_arc(cx - 55, cy - 55, cx + 55, cy + 55,
                start=90, extent=90, outline=AMBER_D, width=1, dash=(3, 6))
            fib_canvas.create_arc(cx - 34, cy - 34, cx + 34, cy + 34,
                start=180, extent=90, outline=AMBER_D, width=1, dash=(3, 6))

            # Phi label
            fib_canvas.create_text(cx + 100, cy - 130, text="φ = 1.618", font=(FONT, 7),
                                    fill=DIM2, anchor="w")

            # Title over canvas
            title_frame = tk.Frame(f, bg=BG)
            title_frame.place(relx=0.5, rely=0.12, anchor="center")
            tk.Label(title_frame, text="MAIN", font=(FONT, 16, "bold"), fg=AMBER, bg=BG).pack()
            tk.Label(title_frame, text="Select operation", font=(FONT, 8), fg=DIM, bg=BG).pack()

            # Menu items overlaid on canvas — positioned with Fibonacci spacing
            menu_frame = tk.Frame(f, bg=BG)
            menu_frame.place(relx=0.5, rely=0.52, anchor="center")

            for i, (name, target, desc) in enumerate(items):
                num = i + 1
                row = tk.Frame(menu_frame, bg=BG, cursor="hand2")
                row.pack(fill="x", pady=2)

                # Left accent — fibonacci height (proportional)
                accent_h = max(2, int(8 / phi ** (i * 0.3)))

                tk.Label(row, text=f" {num} ", font=(FONT, 9, "bold"), fg=BG, bg=AMBER, width=3).pack(side="left")

                # Connecting dot
                tk.Label(row, text="─", font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left")

                nl = tk.Label(row, text=f" {name}", font=(FONT, 10, "bold"), fg=WHITE, bg=BG3,
                              anchor="w", padx=8, pady=5, width=14)
                nl.pack(side="left")

                dl = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3, anchor="w", padx=8, pady=5)
                dl.pack(side="left", fill="x", expand=True)

                # Right phi indicator
                tk.Label(row, text="›", font=(FONT, 10), fg=DIM2, bg=BG3, padx=6).pack(side="right")

                if target in ("data", "procs", "config"):
                    cmd = lambda t=target: self._special(t)
                else:
                    cmd = lambda t=target: self._menu(t)

                for w in [row, nl, dl]:
                    w.bind("<Enter>", lambda e, r=row, n=nl: (r.configure(bg=BG3), n.configure(fg=AMBER)))
                    w.bind("<Leave>", lambda e, r=row, n=nl: (r.configure(bg=BG), n.configure(fg=WHITE)))
                    w.bind("<Button-1>", lambda e, c=cmd: c())

                self._kb(f"<Key-{num}>", cmd)

        # ─── SUBMENUS: clean list ─────────────────────────
        else:
            f = tk.Frame(self.main, bg=BG); f.pack(expand=True)
            tk.Label(f, text=title, font=(FONT, 14, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 6))
            tk.Label(f, text="Select engine", font=(FONT, 8), fg=DIM, bg=BG).pack(pady=(0, 16))

            for i, (name, target, desc) in enumerate(items):
                num = i + 1
                row = tk.Frame(f, bg=BG, cursor="hand2")
                row.pack(fill="x", padx=60, pady=1)

                tk.Label(row, text=f" {num} ", font=(FONT, 9, "bold"), fg=BG, bg=AMBER, width=3).pack(side="left")
                nl = tk.Label(row, text=f"  {name}", font=(FONT, 10, "bold"), fg=WHITE, bg=BG3, anchor="w", padx=6, pady=4, width=14)
                nl.pack(side="left")
                dl = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3, anchor="w", padx=6, pady=4)
                dl.pack(side="left", fill="x", expand=True)

                cmd = lambda n=name, t=target, d=desc, k=key: self._brief(n, t, d, k)

                for w in [row, nl, dl]:
                    w.bind("<Enter>", lambda e, r=row, n=nl: (r.configure(bg=BG3), n.configure(fg=AMBER)))
                    w.bind("<Leave>", lambda e, r=row, n=nl: (r.configure(bg=BG), n.configure(fg=WHITE)))
                    w.bind("<Button-1>", lambda e, c=cmd: c())

                self._kb(f"<Key-{num}>", cmd)

            # Back row
            tk.Frame(f, bg=BG, height=10).pack()
            brow = tk.Frame(f, bg=BG, cursor="hand2"); brow.pack(fill="x", padx=60, pady=1)
            tk.Label(brow, text=" 0 ", font=(FONT, 9, "bold"), fg=WHITE, bg=DIM2, width=3).pack(side="left")
            bl = tk.Label(brow, text="  BACK", font=(FONT, 10), fg=DIM, bg=BG3, anchor="w", padx=6, pady=4)
            bl.pack(side="left", fill="x", expand=True)
            for w in [brow, bl]:
                w.bind("<Button-1>", lambda e: self._menu("main"))

    # ─── STRATEGY BRIEFING ──────────────────────────────
    def _brief(self, name, script, desc, parent_menu):
        """Show strategy philosophy and logic before running."""
        self._clr(); self._unbind()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name}")
        self.h_stat.configure(text="BRIEFING", fg=AMBER_D)
        self.f_lbl.configure(text="ENTER execute  |  ESC back")

        brief = BRIEFINGS.get(name, {})

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True, padx=30, pady=16)

        # Header
        hdr = tk.Frame(f, bg=BG)
        hdr.pack(fill="x", pady=(0, 12))
        tk.Label(hdr, text=f" {name} ", font=(FONT, 10, "bold"), fg=BG, bg=AMBER).pack(side="left")
        tk.Label(hdr, text=f"  {desc}", font=(FONT, 9), fg=DIM, bg=BG).pack(side="left", padx=6)

        tk.Frame(f, bg=AMBER_D, height=1).pack(fill="x", pady=(0, 14))

        # Philosophy (italic feel with dimmer color)
        if brief.get("philosophy"):
            tk.Label(f, text='"' + brief["philosophy"] + '"', font=(FONT, 9), fg=AMBER_D,
                     bg=BG, wraplength=700, justify="left", anchor="w").pack(fill="x", pady=(0, 14))

        # Logic steps
        if brief.get("logic"):
            tk.Label(f, text="LOGIC", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
            tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))
            for i, step in enumerate(brief["logic"]):
                row = tk.Frame(f, bg=BG)
                row.pack(fill="x", pady=1)
                tk.Label(row, text=f"  {i+1}.", font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, width=4, anchor="e").pack(side="left")
                tk.Label(row, text=step, font=(FONT, 8), fg=WHITE, bg=BG, anchor="w").pack(side="left", padx=4)

        # Edge + Risk side by side
        if brief.get("edge") or brief.get("risk"):
            tk.Frame(f, bg=BG, height=10).pack()
            er = tk.Frame(f, bg=BG)
            er.pack(fill="x")
            if brief.get("edge"):
                ef = tk.Frame(er, bg=BG)
                ef.pack(side="left", fill="x", expand=True)
                tk.Label(ef, text="EDGE", font=(FONT, 7, "bold"), fg=GREEN, bg=BG, anchor="w").pack(anchor="w")
                tk.Label(ef, text=brief["edge"], font=(FONT, 8), fg=DIM, bg=BG, anchor="w", wraplength=350).pack(anchor="w")
            if brief.get("risk"):
                rf = tk.Frame(er, bg=BG)
                rf.pack(side="right", fill="x", expand=True)
                tk.Label(rf, text="RISK", font=(FONT, 7, "bold"), fg=RED, bg=BG, anchor="w").pack(anchor="w")
                tk.Label(rf, text=brief["risk"], font=(FONT, 8), fg=DIM, bg=BG, anchor="w", wraplength=350).pack(anchor="w")

        tk.Frame(f, bg=BG, height=14).pack()

        # Route to correct config screen
        is_bt = parent_menu == "backtest"
        is_live = parent_menu == "live"
        is_tool = parent_menu == "tools"

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack()

        if is_bt:
            next_fn = lambda: self._config_backtest(name, script, desc, parent_menu)
            btn_text = "  CONFIGURE & RUN  "
        elif is_live:
            next_fn = lambda: self._config_live(name, script, desc, parent_menu)
            btn_text = "  SELECT MODE & RUN  "
        else:
            next_fn = lambda: self._exec(name, script, desc, parent_menu, [])
            btn_text = "  EXECUTE  "

        run_btn = tk.Label(btn_f, text=btn_text, font=(FONT, 10, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2", padx=12, pady=4)
        run_btn.pack(side="left", padx=4)
        run_btn.bind("<Button-1>", lambda e: next_fn())
        self._kb("<Return>", next_fn)

        back_btn = tk.Label(btn_f, text="  BACK  ", font=(FONT, 10), fg=DIM, bg=BG3,
                            cursor="hand2", padx=12, pady=4)
        back_btn.pack(side="left", padx=4)
        back_btn.bind("<Button-1>", lambda e: self._menu(parent_menu))
        self._kb("<Escape>", lambda: self._menu(parent_menu))

    # ─── BACKTEST CONFIG (clickable inputs) ──────────────
    def _config_backtest(self, name, script, desc, parent_menu):
        self._clr(); self._unbind()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name} > CONFIG")
        self.h_stat.configure(text="CONFIGURE", fg=AMBER_D)
        self.f_lbl.configure(text="Click options to select  |  ENTER run with selections")

        # State
        self._cfg_period = "90"
        self._cfg_basket = ""  # empty = default
        self._cfg_plots = "n"
        self._cfg_leverage = ""

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True, padx=30, pady=16)

        tk.Label(f, text=f"{name} — BACKTEST CONFIG", font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(anchor="w", pady=(0, 14))

        # ── PERIOD ──
        tk.Label(f, text="PERIOD", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))
        per_f = tk.Frame(f, bg=BG)
        per_f.pack(fill="x", pady=(0, 14))

        self._per_btns = []
        for label, hint, val in PERIODS_UI:
            btn = tk.Label(per_f, text=f" {label} ", font=(FONT, 9, "bold"),
                           fg=BG if val == "90" else DIM, bg=AMBER if val == "90" else BG3,
                           cursor="hand2", padx=10, pady=4)
            btn.pack(side="left", padx=2)
            self._per_btns.append((btn, val))

            def select_period(event, v=val):
                self._cfg_period = v
                for b, bv in self._per_btns:
                    b.configure(fg=BG if bv == v else DIM, bg=AMBER if bv == v else BG3)
            btn.bind("<Button-1>", select_period)

        # ── BASKET ──
        tk.Label(f, text="ASSET BASKET", font=(FONT, 8, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))

        # Basket buttons — row 1
        bsk_f = tk.Frame(f, bg=BG)
        bsk_f.pack(fill="x")

        self._bsk_btns = []
        self._bsk_assets = {b[1]: b[2] for b in BASKETS_UI}  # val -> asset list

        for label, val, assets in BASKETS_UI[:5]:
            btn = tk.Label(bsk_f, text=f" {label} ", font=(FONT, 8, "bold"),
                           fg=BG if val == "" else DIM, bg=AMBER if val == "" else BG3,
                           cursor="hand2", padx=8, pady=3)
            btn.pack(side="left", padx=2)
            self._bsk_btns.append((btn, val))
            btn.bind("<Button-1>", lambda e, v=val: self._select_basket(v))

        # Row 2
        bsk_f2 = tk.Frame(f, bg=BG)
        bsk_f2.pack(fill="x", pady=(2, 0))
        for label, val, assets in BASKETS_UI[5:]:
            btn = tk.Label(bsk_f2, text=f" {label} ", font=(FONT, 8, "bold"),
                           fg=DIM, bg=BG3, cursor="hand2", padx=8, pady=3)
            btn.pack(side="left", padx=2)
            self._bsk_btns.append((btn, val))
            btn.bind("<Button-1>", lambda e, v=val: self._select_basket(v))

        # Preview bar — shows selected assets
        self._bsk_preview_f = tk.Frame(f, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        self._bsk_preview_f.pack(fill="x", pady=(6, 14))
        self._bsk_preview_count = tk.Label(self._bsk_preview_f, text="", font=(FONT, 7, "bold"),
                                            fg=AMBER, bg=BG2, padx=6)
        self._bsk_preview_count.pack(side="left", pady=4)
        self._bsk_preview_lbl = tk.Label(self._bsk_preview_f, text="", font=(FONT, 7),
                                          fg=DIM, bg=BG2, anchor="w", padx=4)
        self._bsk_preview_lbl.pack(side="left", fill="x", expand=True, pady=4)

        # Show default basket on load
        self._select_basket("")

        # ── OPTIONS ──
        opt_f = tk.Frame(f, bg=BG)
        opt_f.pack(fill="x", pady=(0, 14))

        # Charts toggle
        self._plot_btn = tk.Label(opt_f, text=" CHARTS OFF ", font=(FONT, 8, "bold"),
                                   fg=DIM, bg=BG3, cursor="hand2", padx=8, pady=3)
        self._plot_btn.pack(side="left", padx=2)
        def toggle_plots(event):
            self._cfg_plots = "s" if self._cfg_plots == "n" else "n"
            on = self._cfg_plots == "s"
            self._plot_btn.configure(text=" CHARTS ON " if on else " CHARTS OFF ",
                                      fg=BG if on else DIM, bg=GREEN if on else BG3)
        self._plot_btn.bind("<Button-1>", toggle_plots)

        # Leverage
        tk.Label(opt_f, text="  LEVERAGE:", font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG).pack(side="left", padx=(12, 4))
        self._lev_btns = []
        for lev in ["1.0", "2.0", "3.0", "5.0"]:
            btn = tk.Label(opt_f, text=f" {lev}x ", font=(FONT, 8, "bold"),
                           fg=BG if lev == "1.0" else DIM, bg=AMBER if lev == "1.0" else BG3,
                           cursor="hand2", padx=6, pady=3)
            btn.pack(side="left", padx=1)
            self._lev_btns.append((btn, lev))
            def select_lev(event, v=lev):
                self._cfg_leverage = "" if v == "1.0" else v
                for b, bv in self._lev_btns:
                    b.configure(fg=BG if bv == v else DIM, bg=AMBER if bv == v else BG3)
            btn.bind("<Button-1>", select_lev)

        tk.Frame(f, bg=BG, height=10).pack()

        # Summary
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(0, 10))

        # Run button
        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack()

        def do_run():
            # Build inputs to auto-send: period, basket, plots (if azoth), leverage, enter to start
            inputs = [self._cfg_period, self._cfg_basket]
            if name == "AZOTH":
                inputs.append(self._cfg_plots)
            inputs.append(self._cfg_leverage)
            inputs.append("")  # enter to start
            self._exec(name, script, desc, parent_menu, inputs)

        run_btn = tk.Label(btn_f, text="  RUN BACKTEST  ", font=(FONT, 11, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2", padx=16, pady=5)
        run_btn.pack(side="left", padx=4)
        run_btn.bind("<Button-1>", lambda e: do_run())
        self._kb("<Return>", do_run)

        back_btn = tk.Label(btn_f, text="  BACK  ", font=(FONT, 10), fg=DIM, bg=BG3,
                            cursor="hand2", padx=12, pady=5)
        back_btn.pack(side="left", padx=4)
        back_btn.bind("<Button-1>", lambda e: self._brief(name, script, desc, parent_menu))
        self._kb("<Escape>", lambda: self._brief(name, script, desc, parent_menu))

    # ─── LIVE CONFIG (clickable mode select) ───────────
    def _config_live(self, name, script, desc, parent_menu):
        """Config screen for live engines — select mode then run."""
        self._clr(); self._unbind()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name} > CONFIG")
        self.h_stat.configure(text="CONFIGURE", fg=AMBER_D)
        self.f_lbl.configure(text="Select mode then RUN  |  ESC back to briefing")

        # For arbitrage vs live, different modes
        is_arb = "arbitrage" in script
        if is_arb:
            modes = [
                ("DASHBOARD", "1", "Scan all venues and show opportunities"),
                ("PAPER",     "2", "Simulated — no real orders"),
                ("DEMO",      "3", "Exchange demo/sandbox API"),
                ("LIVE",      "4", "REAL CAPITAL — extreme caution"),
            ]
        else:
            modes = [
                ("PAPER",    "1", "Simulated execution — observe without risk"),
                ("DEMO",     "2", "Binance Futures Demo API — real orderbook, fake money"),
                ("TESTNET",  "3", "Binance Testnet — test environment"),
                ("LIVE",     "4", "REAL CAPITAL — your money on the line"),
            ]

        self._live_mode = modes[0][1]  # default to first

        f = tk.Frame(self.main, bg=BG)
        f.pack(fill="both", expand=True, padx=30, pady=16)

        tk.Label(f, text=f"{name} — SELECT MODE", font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(anchor="w", pady=(0, 14))

        self._mode_btns = []
        for label, val, hint in modes:
            row = tk.Frame(f, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=2)

            color = RED if "LIVE" == label else AMBER if "DEMO" == label else GREEN
            is_default = val == self._live_mode

            btn = tk.Label(row, text=f" {label} ", font=(FONT, 9, "bold"),
                           fg=BG if is_default else DIM, bg=color if is_default else BG3,
                           cursor="hand2", padx=10, pady=4)
            btn.pack(side="left", padx=2)

            hl = tk.Label(row, text=f"  {hint}", font=(FONT, 8), fg=DIM, bg=BG, anchor="w", padx=4)
            hl.pack(side="left")

            self._mode_btns.append((btn, val, color))

            def select_mode(event, v=val):
                self._live_mode = v
                for b, bv, c in self._mode_btns:
                    b.configure(fg=BG if bv == v else DIM, bg=c if bv == v else BG3)
            btn.bind("<Button-1>", select_mode)
            hl.bind("<Button-1>", select_mode)

        tk.Frame(f, bg=BG, height=16).pack()
        tk.Frame(f, bg=DIM2, height=1).pack(fill="x", pady=(0, 10))

        btn_f = tk.Frame(f, bg=BG)
        btn_f.pack()

        def do_run():
            self._exec(name, script, desc, parent_menu, [self._live_mode])

        run_btn = tk.Label(btn_f, text="  START ENGINE  ", font=(FONT, 11, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2", padx=16, pady=5)
        run_btn.pack(side="left", padx=4)
        run_btn.bind("<Button-1>", lambda e: do_run())
        self._kb("<Return>", do_run)

        back_btn = tk.Label(btn_f, text="  BACK  ", font=(FONT, 10), fg=DIM, bg=BG3,
                            cursor="hand2", padx=12, pady=5)
        back_btn.pack(side="left", padx=4)
        back_btn.bind("<Button-1>", lambda e: self._brief(name, script, desc, parent_menu))
        self._kb("<Escape>", lambda: self._brief(name, script, desc, parent_menu))

    def _select_basket(self, val):
        """Update basket selection — highlight button + show asset preview."""
        self._cfg_basket = val
        # Update button highlights
        for b, bv in self._bsk_btns:
            b.configure(fg=BG if bv == val else DIM, bg=AMBER if bv == val else BG3)
        # Update preview
        assets = self._bsk_assets.get(val, [])
        if assets:
            count = len(assets)
            asset_str = "  ".join(assets)
            self._bsk_preview_count.configure(text=f" {count} ASSETS ")
            self._bsk_preview_lbl.configure(text=asset_str)
        else:
            self._bsk_preview_count.configure(text="")
            self._bsk_preview_lbl.configure(text="")

    # ─── EXECUTE ENGINE ──────────────────────────────────
    def _exec(self, name, script, desc, parent_menu, auto_inputs):
        self._clr(); self._unbind()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name}")
        self.h_stat.configure(text="RUNNING", fg=GREEN)
        self.f_lbl.configure(text="Type input below + ENTER  |  empty = accept default")

        f = tk.Frame(self.main, bg=BG); f.pack(fill="both", expand=True)

        # Top bar
        top = tk.Frame(f, bg=BG2); top.pack(fill="x")
        tk.Label(top, text=f" {name} ", font=(FONT, 8, "bold"), fg=BG, bg=AMBER).pack(side="left", padx=6, pady=3)
        tk.Label(top, text=desc, font=(FONT, 8), fg=DIM, bg=BG2, padx=6).pack(side="left", pady=3)

        tk.Button(top, text=" STOP ", font=(FONT, 7, "bold"), fg=RED, bg=BG2, border=0, cursor="hand2",
                  activeforeground=WHITE, activebackground=BG3, command=self._stop).pack(side="right", padx=4, pady=3)
        tk.Button(top, text=" BACK ", font=(FONT, 7, "bold"), fg=DIM, bg=BG2, border=0, cursor="hand2",
                  activeforeground=WHITE, activebackground=BG3,
                  command=lambda: (self._stop(), self._menu(parent_menu))).pack(side="right", pady=3)

        tk.Frame(f, bg=AMBER_D, height=1).pack(fill="x")

        # Console
        cf = tk.Frame(f, bg=PANEL); cf.pack(fill="both", expand=True)
        sb = tk.Scrollbar(cf, bg=BG, troughcolor=BG, highlightthickness=0, bd=0)
        sb.pack(side="right", fill="y")
        self.con = tk.Text(cf, bg=PANEL, fg=WHITE, font=(FONT, 9), wrap="word",
                           borderwidth=0, highlightthickness=0, insertbackground=AMBER,
                           padx=10, pady=6, state="disabled", cursor="arrow",
                           yscrollcommand=sb.set)
        self.con.pack(fill="both", expand=True)
        sb.config(command=self.con.yview)
        self.con.tag_configure("a", foreground=AMBER)
        self.con.tag_configure("g", foreground=GREEN)
        self.con.tag_configure("r", foreground=RED)
        self.con.tag_configure("d", foreground=DIM)
        self.con.tag_configure("w", foreground=WHITE)

        # Input bar
        tk.Frame(f, bg=AMBER, height=1).pack(fill="x")
        ib = tk.Frame(f, bg=BG2, height=34); ib.pack(fill="x"); ib.pack_propagate(False)

        self._inp_lbl = tk.Label(ib, text=" INPUT ", font=(FONT, 7, "bold"), fg=BG, bg=AMBER)
        self._inp_lbl.pack(side="left", padx=(6,4), pady=5)

        tk.Label(ib, text=">", font=(FONT, 10, "bold"), fg=AMBER, bg=BG2).pack(side="left")
        self.inp = tk.Entry(ib, bg=BG3, fg=WHITE, font=(FONT, 10), insertbackground=AMBER,
                             border=0, highlightthickness=1, highlightcolor=AMBER_D, highlightbackground=BORDER)
        self.inp.pack(side="left", fill="x", expand=True, padx=4, pady=5, ipady=1)
        self.inp.focus_set()
        self.inp.bind("<Return>", self._send)

        tk.Label(ib, text="ENTER send | empty=default", font=(FONT, 7), fg=DIM2, bg=BG2).pack(side="right", padx=6)

        # Blink indicator
        self._blink = True
        def blink():
            if not hasattr(self, '_inp_lbl') or not self._inp_lbl.winfo_exists(): return
            if self.proc and self.proc.poll() is None:
                self._blink = not self._blink
                self._inp_lbl.configure(bg=AMBER if self._blink else BG2, fg=BG if self._blink else AMBER)
            else:
                self._inp_lbl.configure(text=" DONE ", bg=DIM2, fg=DIM)
            self.after(500, blink)
        blink()

        # Print header
        self._p(f" {name}  {desc}  {datetime.now().strftime('%H:%M:%S')}\n", "a")
        self._p("─"*60 + "\n", "d")

        # Launch
        path = ROOT / script
        if not path.exists():
            self._p(f"ERROR: {path} not found\n", "r"); return

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"; env["PYTHONUTF8"] = "1"
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0

        try:
            self.proc = subprocess.Popen(
                [sys.executable, "-X", "utf8", "-u", str(path)], cwd=str(ROOT),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
                text=True, bufsize=1, encoding="utf-8", errors="replace",
                startupinfo=si, creationflags=subprocess.CREATE_NO_WINDOW, env=env)
            threading.Thread(target=self._read, daemon=True).start()
            self._poll()

            # Auto-send configured inputs (from clickable config)
            if auto_inputs:
                def _auto():
                    time.sleep(0.8)
                    for val in auto_inputs:
                        if self.proc and self.proc.poll() is None and self.proc.stdin:
                            try:
                                self.proc.stdin.write(val + "\n")
                                self.proc.stdin.flush()
                                time.sleep(0.4)
                            except: break
                threading.Thread(target=_auto, daemon=True).start()

        except Exception as e:
            self._p(f"FAILED: {e}\n", "r")

    def _send(self, ev=None):
        t = self.inp.get(); self.inp.delete(0, "end")
        if self.proc and self.proc.poll() is None and self.proc.stdin:
            try:
                self.proc.stdin.write(t + "\n"); self.proc.stdin.flush()
                self._p(f"> {t}\n", "a")
            except: pass

    def _read(self):
        try:
            for line in iter(self.proc.stdout.readline, ""):
                if line: self.oq.put(line)
            self.proc.stdout.close()
        except: pass
        self.oq.put(None)

    def _poll(self):
        try:
            for _ in range(80):
                line = self.oq.get_nowait()
                if line is None:
                    rc = self.proc.poll() if self.proc else -1
                    self._p(f"\n{'─'*60}\n", "d")
                    self._p(f"  EXIT {rc}\n", "g" if rc == 0 else "r")
                    self.h_stat.configure(text="DONE" if rc == 0 else f"EXIT {rc}", fg=GREEN if rc == 0 else RED)
                    self.proc = None; return
                self._p(line)
        except queue.Empty: pass
        self.after(30 if self.proc and self.proc.poll() is None else 100, self._poll)

    def _p(self, text, tag="w"):
        self.con.configure(state="normal")
        self.con.insert("end", text, tag)
        self.con.see("end")
        self.con.configure(state="disabled")

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            self._p("\n  >> SIGTERM\n", "r")
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except: self.proc.kill()
            self._p("  >> STOPPED\n", "r")
            self.h_stat.configure(text="STOPPED", fg=RED)
            self.proc = None

    # ─── SPECIAL SCREENS ─────────────────────────────────
    def _special(self, key):
        if key == "data":    self._data()
        elif key == "procs": self._procs()
        elif key == "config": self._config()

    def _data(self):
        self._clr(); self._unbind()
        self.h_path.configure(text="> DATA"); self.h_stat.configure(text="BROWSE", fg=AMBER_D)
        self.f_lbl.configure(text="ESC back  |  click to open file")
        self._kb("<Escape>", lambda: self._menu("main"))

        f = tk.Frame(self.main, bg=BG); f.pack(fill="both", expand=True, padx=16, pady=12)
        tk.Label(f, text="DATA & REPORTS", font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(anchor="w", pady=(0,8))

        reports = []
        dd = ROOT / "data"
        if dd.exists():
            for r in sorted(dd.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                if "reports" in str(r) or "darwin" in str(r): reports.append(r)

        canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(f, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0,0), window=sf, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")

        tk.Label(sf, text=f"  {'FILE':<55} {'DATE':<18} {'SIZE':>8}", font=(FONT, 7, "bold"), fg=AMBER_D, bg=BG, anchor="w").pack(fill="x")
        tk.Frame(sf, bg=DIM2, height=1).pack(fill="x", pady=1)

        if not reports:
            tk.Label(sf, text="  No reports found.", font=(FONT, 9), fg=DIM, bg=BG).pack(anchor="w", pady=8)
        for r in reports[:50]:
            rel = str(r.relative_to(ROOT)); mt = datetime.fromtimestamp(r.stat().st_mtime).strftime("%m-%d %H:%M")
            sz = f"{r.stat().st_size/1024:.0f}K"
            lbl = tk.Label(sf, text=f"  {rel:<55} {mt:<18} {sz:>8}", font=(FONT, 7), fg=DIM, bg=BG, anchor="w", cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Enter>", lambda e, l=lbl: l.configure(bg=BG3, fg=WHITE))
            lbl.bind("<Leave>", lambda e, l=lbl: l.configure(bg=BG, fg=DIM))
            lbl.bind("<Button-1>", lambda e, p=r: os.startfile(str(p)) if sys.platform=="win32" else None)

    def _procs(self):
        self._clr(); self._unbind()
        self.h_path.configure(text="> PROCS"); self.h_stat.configure(text="MANAGE", fg=GREEN)
        self.f_lbl.configure(text="ESC back  |  R refresh")
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-r>", self._procs)

        f = tk.Frame(self.main, bg=BG); f.pack(expand=True)
        tk.Label(f, text="PROCESSES", font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(pady=(0,12))
        try:
            from core.proc import list_procs, stop_proc
            ps = [p for p in list_procs() if p.get("alive")]
        except: ps = []
        if not ps:
            tk.Label(f, text="No engines running.", font=(FONT, 9), fg=DIM, bg=BG).pack(pady=8)
        for p in ps:
            row = tk.Frame(f, bg=BG3); row.pack(fill="x", padx=60, pady=2)
            tk.Label(row, text=f" {p.get('engine','?').upper()} ", font=(FONT, 8, "bold"), fg=BG, bg=GREEN).pack(side="left")
            tk.Label(row, text=f"  PID {p.get('pid','?')}", font=(FONT, 9), fg=WHITE, bg=BG3, padx=6, pady=3).pack(side="left")
            tk.Button(row, text="STOP", font=(FONT, 7, "bold"), fg=RED, bg=BG3, border=0, cursor="hand2",
                      command=lambda pid=p.get("pid"): (stop_proc(pid), self._procs())).pack(side="right", padx=4, pady=2)

    def _config(self):
        self._clr(); self._unbind()
        self.h_path.configure(text="> CONFIG"); self.h_stat.configure(text="SETTINGS", fg=AMBER_D)
        self.f_lbl.configure(text="ESC back  |  number to select")
        self._kb("<Escape>", lambda: self._menu("main"))

        f = tk.Frame(self.main, bg=BG); f.pack(expand=True)
        tk.Label(f, text="CONFIG", font=(FONT, 14, "bold"), fg=AMBER, bg=BG).pack(pady=(0,16))

        cfgs = [
            ("API KEYS",  "Binance Demo / Testnet / Live",   self._cfg_keys),
            ("TELEGRAM",  "Bot token & chat ID",              self._cfg_tg),
            ("VPS",       "Remote server SSH connection",     self._cfg_vps),
            ("VPN",       "WireGuard / OpenVPN tunnel",       self._cfg_vpn),
        ]
        for i, (name, desc, cmd) in enumerate(cfgs):
            row = tk.Frame(f, bg=BG, cursor="hand2"); row.pack(fill="x", padx=60, pady=1)
            tk.Label(row, text=f" {i+1} ", font=(FONT, 9, "bold"), fg=BG, bg=AMBER, width=3).pack(side="left")
            nl = tk.Label(row, text=f"  {name}", font=(FONT, 10, "bold"), fg=WHITE, bg=BG3, anchor="w", padx=6, pady=4, width=14)
            nl.pack(side="left")
            dl = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3, anchor="w", padx=6, pady=4)
            dl.pack(side="left", fill="x", expand=True)
            for w in [row, nl, dl]:
                w.bind("<Enter>", lambda e, n=nl: n.configure(fg=AMBER))
                w.bind("<Leave>", lambda e, n=nl: n.configure(fg=WHITE))
                w.bind("<Button-1>", lambda e, c=cmd: c())
            self._kb(f"<Key-{i+1}>", cmd)

        tk.Frame(f, bg=BG, height=10).pack()
        brow = tk.Frame(f, bg=BG, cursor="hand2"); brow.pack(fill="x", padx=60, pady=1)
        tk.Label(brow, text=" 0 ", font=(FONT, 9, "bold"), fg=WHITE, bg=DIM2, width=3).pack(side="left")
        bl = tk.Label(brow, text="  BACK", font=(FONT, 10), fg=DIM, bg=BG3, anchor="w", padx=6, pady=4)
        bl.pack(side="left", fill="x", expand=True)
        for w in [brow, bl]: w.bind("<Button-1>", lambda e: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))

    # ─── CONFIG EDITORS ──────────────────────────────────
    def _cfg_edit(self, title, fields, load_fn, save_fn):
        self._clr(); self._unbind()
        self.h_path.configure(text=f"> CONFIG > {title}")
        self.f_lbl.configure(text="ESC back  |  CTRL+S save")
        self._kb("<Escape>", self._config)

        f = tk.Frame(self.main, bg=BG); f.pack(expand=True)
        tk.Label(f, text=title, font=(FONT, 13, "bold"), fg=AMBER, bg=BG).pack(pady=(0,16))

        data = load_fn()
        entries = {}
        for key, label, hint, masked in fields:
            row = tk.Frame(f, bg=BG); row.pack(fill="x", padx=50, pady=2)
            tk.Label(row, text=label, font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, width=16, anchor="w").pack(side="left")
            e = tk.Entry(row, bg=BG3, fg=WHITE, font=(FONT, 9), insertbackground=AMBER, border=0,
                         highlightthickness=1, highlightcolor=AMBER_D, highlightbackground=BORDER, width=48)
            e.pack(side="left", fill="x", expand=True, padx=4, ipady=3)
            val = data.get(key, "")
            if val: e.insert(0, str(val))
            if masked: e.configure(show="*")
            if hint: tk.Label(row, text=hint, font=(FONT, 7), fg=DIM2, bg=BG).pack(side="right", padx=4)
            entries[key] = e

        tk.Frame(f, bg=BG, height=14).pack()
        br = tk.Frame(f, bg=BG); br.pack()

        def save():
            vals = {k: e.get().strip() for k, e in entries.items()}
            save_fn(vals)
            self.h_stat.configure(text="SAVED", fg=GREEN)
            self.after(1500, lambda: self.h_stat.configure(text="", fg=DIM))

        sv = tk.Label(br, text="  SAVE  ", font=(FONT, 10, "bold"), fg=BG, bg=GREEN, cursor="hand2", padx=12, pady=3)
        sv.pack(side="left", padx=4); sv.bind("<Button-1>", lambda e: save())
        cn = tk.Label(br, text="  CANCEL  ", font=(FONT, 10), fg=DIM, bg=BG3, cursor="hand2", padx=12, pady=3)
        cn.pack(side="left", padx=4); cn.bind("<Button-1>", lambda e: self._config())
        self._kb("<Control-s>", save)

    def _load_json(self, name):
        p = ROOT / "config" / name
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f: return json.load(f)
            except: pass
        return {}

    def _save_json(self, name, data):
        p = ROOT / "config" / name; p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f: json.dump(data, f, indent=4)

    def _cfg_keys(self):
        def load():
            k = self._load_json("keys.json")
            return {"demo_key": k.get("demo",{}).get("api_key",""), "demo_sec": k.get("demo",{}).get("api_secret",""),
                    "test_key": k.get("testnet",{}).get("api_key",""), "test_sec": k.get("testnet",{}).get("api_secret",""),
                    "live_key": k.get("live",{}).get("api_key",""), "live_sec": k.get("live",{}).get("api_secret","")}
        def save(v):
            k = self._load_json("keys.json")
            k.setdefault("demo",{})["api_key"]=v["demo_key"]; k["demo"]["api_secret"]=v["demo_sec"]
            k.setdefault("testnet",{})["api_key"]=v["test_key"]; k["testnet"]["api_secret"]=v["test_sec"]
            k.setdefault("live",{})["api_key"]=v["live_key"]; k["live"]["api_secret"]=v["live_sec"]
            self._save_json("keys.json", k)
        self._cfg_edit("API KEYS", [
            ("demo_key","DEMO KEY","",True), ("demo_sec","DEMO SECRET","",True),
            ("test_key","TESTNET KEY","",True), ("test_sec","TESTNET SECRET","",True),
            ("live_key","LIVE KEY","REAL $",True), ("live_sec","LIVE SECRET","REAL $",True),
        ], load, save)

    def _cfg_tg(self):
        def load():
            k = self._load_json("keys.json"); t = k.get("telegram",{})
            return {"token": t.get("bot_token",""), "chat": t.get("chat_id","")}
        def save(v):
            k = self._load_json("keys.json"); k.setdefault("telegram",{})
            k["telegram"]["bot_token"]=v["token"]; k["telegram"]["chat_id"]=v["chat"]
            self._save_json("keys.json", k)
        self._cfg_edit("TELEGRAM", [
            ("token","BOT TOKEN","@BotFather",True), ("chat","CHAT ID","@userinfobot",False),
        ], load, save)

    def _cfg_vps(self):
        self._cfg_edit("VPS — SSH", [
            ("host","HOST / IP","",False), ("port","PORT","22",False),
            ("user","USER","root",False), ("key_path","SSH KEY","path to id_rsa",False),
            ("remote_dir","REMOTE DIR","/opt/aurum",False),
        ], lambda: self._load_json("vps.json"), lambda v: self._save_json("vps.json", v))

    def _cfg_vpn(self):
        self._cfg_edit("VPN", [
            ("type","TYPE","wireguard/openvpn",False), ("config_path","CONFIG FILE",".conf/.ovpn",False),
            ("server","SERVER IP","",False), ("private_key","PRIVATE KEY","",True),
            ("dns","DNS","1.1.1.1",False),
        ], lambda: self._load_json("vpn.json"), lambda v: self._save_json("vpn.json", v))

    # ─── QUIT ────────────────────────────────────────────
    def _quit(self):
        if self.proc and self.proc.poll() is None:
            r = messagebox.askyesnocancel("AURUM", "Engine running. Stop before closing?")
            if r is None: return
            if r:
                self.proc.terminate()
                try: self.proc.wait(timeout=3)
                except: self.proc.kill()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
