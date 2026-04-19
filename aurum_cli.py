#!/usr/bin/env python3
"""
AURUM Finance — Terminal UI v2

Architecture: Method × Strategy matrix
  Methods:    Backtest | Simulator | Live
  Strategies: CITADEL | RENAISSANCE | JANE STREET | MILLENNIUM
"""
import os, sys, time, argparse, subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
os.chdir(_ROOT)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

VERSION = "2.0.0"

# ══════════════════════════════════════════════════════════════
#  TERMINAL
# ══════════════════════════════════════════════════════════════

def _enable_vt100():
    if sys.platform == "win32":
        try:
            import ctypes
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            m = ctypes.c_ulong()
            k.GetConsoleMode(h, ctypes.byref(m))
            k.SetConsoleMode(h, m.value | 0x0004)
        except Exception:
            os.system("")

# Palette
D  = "\033[90m"      # dim grey
W  = "\033[97m"      # white
G  = "\033[38;5;35m" # green
R  = "\033[38;5;196m"# red
C  = "\033[38;5;81m" # cyan
Y  = "\033[38;5;220m"# gold/yellow
M  = "\033[38;5;99m" # purple
B  = "\033[1m"       # bold
Z  = "\033[0m"       # reset
BG = "\033[48;5;234m"# subtle row highlight bg

# Gradient palette for banner
_G1 = "\033[38;5;220m"  # gold
_G2 = "\033[38;5;214m"  # orange-gold
_G3 = "\033[38;5;208m"  # deep orange
_G4 = "\033[38;5;172m"  # amber
_G5 = "\033[38;5;136m"  # dark gold

def cls():
    sys.stdout.write("\033[H\033[J"); sys.stdout.flush()

def tw():
    try: return os.get_terminal_size().columns
    except Exception: return 100

def _get_key():
    if sys.platform == "win32":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            return {"H": "up", "P": "down"}.get(ch2)
        if ch == "\r": return "enter"
        if ch == "\x1b": return "esc"
        return ch.lower()
    else:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    return {"A": "up", "B": "down"}.get(ch3)
                return "esc"
            if ch in ("\r", "\n"): return "enter"
            return ch.lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

def _inp(prompt: str) -> str:
    sys.stdout.write(f"  {prompt}"); sys.stdout.flush()
    try: return input().strip()
    except (EOFError, KeyboardInterrupt): return ""

def _confirm(msg: str) -> bool:
    sys.stdout.write(f"  {msg} {D}[s/N]{Z} "); sys.stdout.flush()
    return _get_key() in ("s", "y")

def _wait(msg: str = ""):
    print(f"\n  {D}{msg or 'qualquer tecla...'}{Z}"); _get_key()


# ══════════════════════════════════════════════════════════════
#  STRATEGY REGISTRY
# ══════════════════════════════════════════════════════════════

STRATEGIES = {
    "citadel": {
        "name": "CITADEL",
        "tag": "CTD",
        "desc": "Systematic momentum — trend-following fractal",
        "methods": ["backtest","simulator","live"],
        "info": [
            "Detecta tendencias macro via slope EMA200 + estrutura",
            "de swings fractais em multiplos timeframes.",
            "",
            "Omega Score 5D   struct · flow · cascade · momentum · pullback",
            "Regime-aware     BULL / BEAR / CHOP com thresholds adaptivos",
            "Risk sizing      Kelly fraccional + Omega risk table + DD scale",
            "Filtros          SoftCorr · RegimeTrans · VolExtreme · Streak",
            "CHOP mode        Mean-reversion BB+RSI quando regime lateral",
        ],
    },
    "renaissance": {
        "name": "RENAISSANCE",
        "tag": "REN",
        "desc": "Pattern recognition — harmonic geometry + Bayesian",
        "methods": ["backtest"],
        "info": [
            "Identifica padroes harmonicos classicos (Gartley, Bat,",
            "Butterfly, Crab) com scoring Bayesiano adaptivo.",
            "",
            "Patterns        Gartley · Bat · Butterfly · Crab",
            "Filtros         Shannon entropy + Hurst exponent",
            "Scoring         Bayesian win rate × regime risk",
            "Confluencia     Fibonacci levels + fractal alignment",
        ],
    },
    "janestreet": {
        "name": "JANE STREET",
        "tag": "JST",
        "desc": "Cross-venue arb — funding/basis multi-exchange",
        "methods": ["simulator","live"],
        "info": [
            "Captura spread de funding rate entre 13 exchanges",
            "com execucao delta-neutral (long+short simultaneo).",
            "",
            "Venues          Binance · Bybit · OKX · Gate · Bitget + 8",
            "Scoring         OmegaV2 + fill probability + adversarial",
            "Execution       Split orders (5 parts) · latency profiler",
            "Risk            Regime detection · hedge monitor · kill-switch",
        ],
    },
    "deshaw": {
        "name": "DE SHAW",
        "tag": "DSH",
        "desc": "Statistical arb — pairs cointegration + mean reversion",
        "methods": ["backtest"],
        "info": [
            "Cointegration Engle-Granger entre pares do universo.",
            "",
            "Spread          Z-score rolling com half-life OLS",
            "Entry           |z| > 2.0 · Exit z cruza 0 · Stop |z| > 3.5",
            "Filtros         Half-life 5-50 candles · vol != EXTREME",
            "Sizing          Proporcional a confianca (p-value)",
        ],
    },
    "jump": {
        "name": "JUMP",
        "tag": "JMP",
        "desc": "Order flow — CVD divergence + volume imbalance",
        "methods": ["backtest"],
        "info": [
            "Edge do fluxo de ordens — taker buy/sell delta.",
            "",
            "CVD             Cumulative Volume Delta + divergence",
            "Imbalance       Taker buy ratio rolling",
            "Liquidation     Spikes vol + ATR simultaneos",
            "Confluencia     CVD div + imbalance + structure",
        ],
    },
    "bridgewater": {
        "name": "BRIDGEWATER",
        "tag": "BDW",
        "desc": "Macro sentiment — funding + OI + LS ratio contrarian",
        "methods": ["backtest"],
        "info": [
            "Extremos de sentiment precedem reversoes.",
            "",
            "Funding Rate    Z-score contrarian",
            "Open Interest   Delta OI vs preco",
            "LS Ratio        Long/Short crowd contrarian",
            "Composite       0.4 funding + 0.3 OI + 0.3 LS",
        ],
    },
    "millennium": {
        "name": "MILLENNIUM",
        "tag": "MLN",
        "desc": "Multi-strategy pod — meta portfolio orchestrator",
        "methods": ["backtest","simulator","live"],
        "composite": True,
        "meta_engine": True,
        "components": ["citadel","renaissance","jump"],
        "info": [
            "Orquestrador multi-strategy sobre os engines validados.",
            "",
            "Aggregator      Signal-level merge",
            "Weighting       Sortino rolling + regime boost",
            "Kill-switch     Pausa se Sortino(20) < -0.5",
            "Core            CITADEL + RENAISSANCE + JUMP",
            "Bootstrap live  runner dedicado prepara preflight; execucao real segue bloqueada",
        ],
    },
    "kepos": {
        "name": "KEPOS",
        "tag": "KEP",
        "desc": "Critical endogeneity fade — Hawkes η reversal plays",
        "methods": ["backtest"],
        "info": [
            "Fade de extensoes criticas via branching ratio de Hawkes.",
            "",
            "Signal          η >= eta_critical sustentado N barras",
            "Entry           Contra o movimento (H1 fade)",
            "Exit            η < eta_exit ou time-stop",
            "Flag            --invert ride extension (H1-INV)",
        ],
    },
    "graham": {
        "name": "GRAHAM",
        "tag": "GRH",
        "desc": "Endogenous momentum — trend gated by Hawkes ENDO regime",
        "methods": ["backtest"],
        "info": [
            "Trend-following so quando regime Hawkes e endogeno.",
            "",
            "Gate            eta_lower <= eta <= eta_upper",
            "Trend           slope EMA + breakout de estrutura",
            "Exit            eta fora da banda ou stop",
            "Flag            --invert mean-reversion (H2-INV)",
        ],
    },
    "medallion": {
        "name": "MEDALLION",
        "tag": "MED",
        "desc": "Berlekamp-Laufer — 7-signal ensemble + Kelly sizing",
        "methods": ["backtest"],
        "info": [
            "Filosofia Simons/Renaissance 1988-90 em codigo.",
            "",
            "Ensemble        7 sub-sinais (z-return, z-vol, ema-dev,",
            "                autocorr, RSI, seasonality, HMM chop)",
            "Gate            autocorr < 0 + HMM regime + ensemble>=th",
            "Sizing          quarter-Kelly rolling empirical, cap 2%",
            "Exit            tp/stop ATR + time-stop curto",
            "Flag            --invert momentum (calibrado pra cripto)",
        ],
    },
    "twosigma": {
        "name": "TWO SIGMA",
        "tag": "TSG",
        "desc": "ML meta-ensemble — LightGBM walk-forward (requires prior runs)",
        "methods": ["backtest"],
        "composite": True,
        "meta_engine": True,
        "components": ["citadel","renaissance","jump","bridgewater"],
        "info": [
            "Re-pondera trades de outros engines via LightGBM.",
            "",
            "Requer          backtests previos do universo meta-engine",
            "Features        regime HMM + Hurst + volatilidade + decay",
            "Output          feature importance + static vs ML PnL",
            "Standalone      imprime instrucoes se nao ha trades em disco",
        ],
    },
    "aqr": {
        "name": "AQR",
        "tag": "AQR",
        "desc": "Evolutionary allocation — fitness-driven strategy weighting",
        "methods": ["backtest"],
        "info": [
            "Selecao natural entre engines ja testadas.",
            "",
            "Input           trades.json dos backtests em data/",
            "Evolucao        fitness via Sortino + MaxDD + stability",
            "Output          alocacao final de capital por engine",
            "Report          data/aqr/darwin_report_YYYY-MM-DD_HHMM.json",
        ],
    },
}

def _resolve(strategy, method, config):
    days  = config.get("days","90")
    plots = "s" if config.get("plots") else "n"
    lev   = config.get("leverage","")
    mode  = config.get("mode","1")
    if method == "backtest":
        if strategy == "citadel":     return "backtest","engines/citadel.py",[days,plots,lev,""]
        if strategy == "renaissance": return "multi","engines/millennium.py",["3",days,"","","","","",plots,""]
        if strategy == "deshaw":      return "newton","engines/deshaw.py",[days,lev,"n",""]
        if strategy == "jump":        return "mercurio","engines/jump.py",[days,lev,"n",""]
        if strategy == "bridgewater": return "thoth","engines/bridgewater.py",[days,lev,""]
        if strategy == "millennium":  return "multi","engines/millennium.py",["1",days,"","","","","",plots,""]
        if strategy == "kepos":       return "kepos","engines/kepos.py",["--days",days,"--no-menu"]
        if strategy == "graham":      return "graham","engines/graham.py",["--days",days,"--no-menu"]
        if strategy == "medallion":   return "medallion","engines/medallion.py",["--days",days,"--no-menu"]
        if strategy == "twosigma":    return "prometeu","engines/twosigma.py",[]
        if strategy == "aqr":         return "darwin","engines/aqr.py",[]
    if method == "simulator":
        if strategy == "citadel":    return "live","engines/live.py",[mode]
        if strategy == "janestreet": return "arb","engines/janestreet.py",[mode]
        if strategy == "millennium": return "multi","engines/millennium_live.py",[mode]
    if method == "live":
        if strategy == "citadel":    return "live","engines/live.py",[mode]
        if strategy == "janestreet": return "arb","engines/janestreet.py",[mode]
        if strategy == "millennium": return "multi","engines/millennium_live.py",[mode]
    return "","",[]

from config.engines import PROC_NAMES as ENGINE_NAMES
def _en(e): return ENGINE_NAMES.get(e, e.upper())


# ══════════════════════════════════════════════════════════════
#  CHROME
# ══════════════════════════════════════════════════════════════

def _box(lines: list[str], color=Y, width: int = 62):
    """Draw a centered box with double-line borders."""
    print(f"\n  {color}╔{'═'*width}╗{Z}")
    for line in lines:
        pad = width - len(line)
        lp = pad // 2; rp = pad - lp
        print(f"  {color}║{Z}{' '*lp}{line}{' '*rp}{color}║{Z}")
    print(f"  {color}╚{'═'*width}╝{Z}")

_LOGO = [
    "  ╔═╗ ╦ ╦ ╦═╗ ╦ ╦ ╔╦╗",
    "  ╠═╣ ║ ║ ╠╦╝ ║ ║ ║║║",
    "  ╩ ╩ ╚═╝ ╩╚═ ╚═╝ ╩ ╩",
]
_LOGO_COLORS = [_G1, _G3, _G5]

def _banner():
    print()
    for i, line in enumerate(_LOGO):
        c = _LOGO_COLORS[i % len(_LOGO_COLORS)]
        print(f"  {c}{line}{Z}")
    print(f"  {D}{'─' * 24}{Z}")
    print(f"  {D}finance{' ' * 11}v{VERSION}{Z}")
    print()

def _running_bar():
    try:
        from core.ops.proc import list_procs
        running = [p for p in list_procs() if p.get("alive")]
    except Exception:
        running = []
    if running:
        tags = "  ".join(f"{C}{_en(p['engine'])}{Z}" for p in running)
        print(f"  {G}●{Z} {W}{len(running)}{Z} {D}activo(s){Z}   {tags}")
    else:
        print(f"  {D}○  nenhum engine activo{Z}")

def _head(title, sub=""):
    cls(); _banner()
    t = f"  {Y}❯{Z} {B}{W}{title}{Z}"
    if sub: t += f"  {D}{sub}{Z}"
    print(t)

def _line(w=0):
    print(f"  {D}{'─'*(w or min(tw()-4, 80))}{Z}")

def _foot(hints: str):
    print(f"\n  {D}{hints}{Z}")


# ══════════════════════════════════════════════════════════════
#  SELECTOR
# ══════════════════════════════════════════════════════════════

def _sel(title, items, hotkeys=None, sub="", hdr=""):
    """Full-screen arrow selector. Returns (index|None, key)."""
    cur = 0; hk = hotkeys or {}
    hk_parts = [f"{D}{v.lower()}{Z} {W}{k}{Z}" for k,v in hk.items()]
    hints_parts = ["↑↓ navegar", "enter seleccionar"] + hk_parts + ["esc voltar"]
    hints = f"  {D}{'  ·  '.join(hints_parts)}{Z}"

    while True:
        _head(title, sub)
        print()
        if hdr:
            print(f"  {D}     {hdr}{Z}")
            _line()
        for i, label in enumerate(items):
            if i == cur:
                print(f"  {Y}❯{Z} {W}{label}{Z}")
            else:
                print(f"    {D}{label}{Z}")
        print()
        print(hints)

        k = _get_key()
        if   k == "up":    cur = (cur-1) % len(items)
        elif k == "down":  cur = (cur+1) % len(items)
        elif k == "enter": return (cur, "enter")
        elif k in ("esc","q"): return (None, "esc")
        elif k in hk:      return (cur, k)


# ══════════════════════════════════════════════════════════════
#  LAUNCH
# ══════════════════════════════════════════════════════════════

def _launch(ek, sc, stdin, sname="", mname="", foreground=True):
    from core.ops.proc import spawn, _is_alive, get_log_path
    # Hawkes engines parse argv via argparse instead of reading interactive
    # prompts from stdin, so route their payload through cli_args.
    if ek in ("kepos", "graham", "medallion"):
        info = spawn(ek, cli_args=stdin)
    else:
        info = spawn(ek, stdin_lines=stdin)
    if not info:
        _head(sname, mname)
        print(f"\n  {Y}Ja esta a correr ou erro ao lancar.{Z}")
        _wait(); return

    pid = info["pid"]

    if not foreground:
        _head(sname, mname)
        print(f"\n  {G}✓{Z}  PID {B}{pid}{Z}  {D}a correr em background{Z}")
        return

    # ── foreground: tail the log live ──
    cls()
    print(f"  {Y}❯{Z} {B}{sname}{Z}  {D}{mname}  ·  PID {pid}{Z}")
    print(f"  {D}Ctrl+C → background{Z}")
    _line()
    print()

    log_file = info["log_file"]
    last = 0
    try:
        while True:
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last)
                    new = f.read()
                    if new:
                        sys.stdout.write(new); sys.stdout.flush()
                    last = f.tell()
            except OSError:
                pass
            if not _is_alive(pid):
                # Flush remaining output
                time.sleep(0.3)
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last)
                        rest = f.read()
                        if rest: sys.stdout.write(rest); sys.stdout.flush()
                except OSError:
                    pass
                print(f"\n  {D}processo terminou{Z}")
                _wait()
                return
            time.sleep(0.15)
    except KeyboardInterrupt:
        print(f"\n\n  {Y}❯{Z} {D}movido para background  ·  PID {B}{pid}{Z}")
        print(f"  {D}ver em Processos{Z}")
        time.sleep(1.2)


# ══════════════════════════════════════════════════════════════
#  MAIN MENU
# ══════════════════════════════════════════════════════════════

MENU = [
    ("Backtest",   "backtest"),
    ("Simulador",  "simulator"),
    ("Live",       "live"),
    None,
    ("Processos",  "procs"),
    ("Data",       "data"),
    ("Status",     "status"),
    None,
    ("Sair",       "quit"),
]

def screen_main():
    nav = [m for m in MENU if m is not None]
    cur = 0

    while True:
        cls(); _banner(); _running_bar()
        print()
        ni = 0
        for item in MENU:
            if item is None:
                print()
                continue
            name, _ = item
            if ni == cur:
                print(f"  {Y}❯{Z} {B}{W}{name}{Z}")
            else:
                print(f"    {D}{name}{Z}")
            ni += 1
        print()
        print(f"  {D}↑↓ navegar  enter seleccionar  esc sair{Z}")

        k = _get_key()
        if   k == "up":   cur = (cur-1) % len(nav)
        elif k == "down": cur = (cur+1) % len(nav)
        elif k == "enter":
            action = nav[cur][1]
            if   action == "quit":      _quit(); return
            elif action == "backtest":  screen_method("backtest")
            elif action == "simulator": screen_method("simulator")
            elif action == "live":      screen_method("live")
            elif action == "procs":     screen_procs()
            elif action == "data":      screen_data()
            elif action == "status":    screen_status()
        elif k in ("esc","q"): _quit(); return

def _quit():
    cls(); _banner()
    try:
        from core.ops.proc import list_procs, stop_proc
        running = [p for p in list_procs() if p.get("alive")]
        if running:
            print(f"\n  {Y}▲{Z} {B}{len(running)}{Z} engine(s) a correr:\n")
            for i, p in enumerate(running):
                print(f"    [{i+1}] {B}{p.get('engine','?'):<12}{Z} PID {p.get('pid','?')}")
            print(f"\n    [a] Parar todas")
            print(f"    [n] Manter todas em background")
            print()
            choice = input(f"  parar quais? (1,2,.. / a / n) > ").strip().lower()
            if choice == "a":
                for p in running:
                    stop_proc(p["pid"])
                    print(f"    {G}✓{Z} {p.get('engine','?')} (PID {p['pid']}) parado")
            elif choice != "n" and choice:
                for idx_str in choice.split(","):
                    idx_str = idx_str.strip()
                    if idx_str.isdigit():
                        idx = int(idx_str) - 1
                        if 0 <= idx < len(running):
                            p = running[idx]
                            stop_proc(p["pid"])
                            print(f"    {G}✓{Z} {p.get('engine','?')} (PID {p['pid']}) parado")
            else:
                print(f"  {D}engines continuam em background{Z}")
    except Exception:
        pass
    print(f"\n  {D}ate a proxima  ☿{Z}\n")


# ══════════════════════════════════════════════════════════════
#  METHOD → STRATEGY
# ══════════════════════════════════════════════════════════════

ML = {"backtest":"BACKTEST","simulator":"SIMULADOR","live":"LIVE"}

def screen_method(method):
    label = ML[method]
    directional = [(k,s) for k,s in STRATEGIES.items() if method in s["methods"] and not s.get("meta_engine")]
    meta = [(k,s) for k,s in STRATEGIES.items() if method in s["methods"] and s.get("meta_engine")]
    avail = directional + meta
    if not avail:
        _head(label); print(f"\n  {D}Nenhuma estrategia disponivel.{Z}"); _wait(); return

    section_rows = {}
    if directional:
        section_rows[0] = f"{B}{C}DIRECTIONAL / RESEARCH{Z}"
    if meta:
        section_rows[len(directional)] = f"{B}{M}META / ORCHESTRATION{Z}"

    cur = 0
    while True:
        _head(label, "seleccionar estrategia")
        print()

        # Strategy list
        for i, (k, s) in enumerate(avail):
            if i in section_rows:
                print(f"  {section_rows[i]}")
            tag = f"{C}{s['tag']}{Z}"
            star = f"{M}★{Z}" if s.get("meta_engine") else " "
            if i == cur:
                print(f"  {Y}❯{Z} {star} {tag}  {B}{W}{s['name']}{Z}  {s['desc']}")
            else:
                print(f"    {star} {tag}  {D}{s['name']:16s}  {s['desc']}{Z}")

        print()

        # Info panel for selected strategy
        _, sel_s = avail[cur]
        info_lines = sel_s.get("info", [])
        if info_lines:
            print(f"\n  {B}{sel_s['name']}{Z}  {D}{sel_s['desc']}{Z}")
            print()
            for line in info_lines:
                if not line:
                    print()
                elif "  " in line and line[0] != " ":
                    # Key-value line: highlight the key
                    parts = line.split("  ", 1)
                    print(f"    {C}{parts[0]:16s}{Z} {parts[1]}")
                else:
                    print(f"    {D}{line}{Z}")

            if sel_s.get("composite"):
                comps = [STRATEGIES[c]["name"] for c in sel_s.get("components",[]) if c in STRATEGIES]
                print(f"\n    {D}componentes{Z}  {' + '.join(f'{B}{c}{Z}' for c in comps)}")

        print(f"  {D}↑↓ navegar  enter seleccionar  esc voltar{Z}")

        k = _get_key()
        if   k == "up":   cur = (cur-1) % len(avail)
        elif k == "down": cur = (cur+1) % len(avail)
        elif k == "enter":
            _screen_config(avail[cur][0], method); return
        elif k in ("esc","q"): return


def _screen_config(strategy, method):
    s = STRATEGIES[strategy]; ml = ML[method]
    config = {}

    if method == "backtest":
        _head(s["name"], ml)
        print()
        config["days"]     = _inp(f"Periodo em dias {D}[90]{Z} > ") or "90"
        config["plots"]    = _inp(f"Graficos? {D}[s/N]{Z} > ").lower() in ("s","sim","y")
        config["leverage"] = _inp(f"Leverage {D}[1.0x]{Z} > ") or ""

    elif method == "simulator":
        if strategy == "quasar":
            modes = ["PAPER       Websocket real, sem ordens", "DEMO        Binance Futures Demo"]
            idx,_ = _sel(f"{s['name']}  {D}{ml}{Z}", modes, sub="modo")
            if idx is None: return
            config["mode"] = str(idx+1)
        elif strategy == "muon":
            modes = ["DASHBOARD   Scan venues", "PAPER       Simulacao"]
            idx,_ = _sel(f"{s['name']}  {D}{ml}{Z}", modes, sub="modo")
            if idx is None: return
            config["mode"] = str(idx+1)

    elif method == "live":
        if strategy == "quasar":
            modes = ["TESTNET     Binance Futures Testnet", "LIVE        Execucao real"]
            idx,_ = _sel(f"{s['name']}  {D}{ml}{Z}", modes, sub="modo")
            if idx is None: return
            config["mode"] = str(idx+3)
        elif strategy == "muon":
            modes = ["DEMO        Demo trading", "LIVE        Execucao real"]
            idx,_ = _sel(f"{s['name']}  {D}{ml}{Z}", modes, sub="modo")
            if idx is None: return
            config["mode"] = str(idx+3)

    ek, sc, stdin = _resolve(strategy, method, config)
    if not ek:
        _head(s["name"]); print(f"\n  {R}Combinacao nao suportada.{Z}"); _wait(); return
    _launch(ek, sc, stdin, s["name"], ml)


# ══════════════════════════════════════════════════════════════
#  PROCESSES
# ══════════════════════════════════════════════════════════════

def screen_procs():
    from core.ops.proc import list_procs, stop_proc, delete_proc

    while True:
        procs = list_procs()
        if not procs:
            _head("PROCESSOS"); print(f"\n  {D}Sem processos.{Z}"); _wait(); return

        items = []
        for p in procs:
            alive = p.get("alive")
            ico = f"{G}●{Z}" if alive else f"{D}○{Z}"
            st  = f"{G}RUN{Z}" if alive else f"{D}DONE{Z}"
            name = _en(p["engine"])
            ts = (p.get("started") or "")[:16]
            items.append(f"{ico}  {name:20s}  {st}   {D}PID {p['pid']:>6d}   {ts}{Z}")

        idx, key = _sel("PROCESSOS", items, hotkeys={"d":"Apagar","k":"Kill"})
        if idx is None: return
        p = procs[idx]

        if key == "enter": _screen_tail(p["pid"])
        elif key == "k":
            if p.get("alive"): stop_proc(p["pid"])
        elif key == "d":
            _head("PROCESSOS")
            if _confirm(f"Apagar {_en(p['engine'])} PID {p['pid']}?"):
                delete_proc(p["pid"]); print(f"  {G}✓{Z}"); time.sleep(0.4)


def _screen_tail(pid):
    from core.ops.proc import _is_alive, get_log_path, _load_state
    log_file = get_log_path(pid)
    if not log_file: return
    info = _load_state()["procs"].get(str(pid), {})
    name = _en(info.get("engine",""))

    cls()
    print(f"  {Y}❯{Z} {B}{name}{Z}  {D}PID {pid}{Z}")
    print(f"  {D}Ctrl+C → voltar{Z}")
    _line()
    print()

    last = 0
    try:
        while True:
            try:
                with open(log_file,"r",encoding="utf-8",errors="replace") as f:
                    f.seek(last); new = f.read()
                    if new: sys.stdout.write(new); sys.stdout.flush()
                    last = f.tell()
            except OSError: pass
            if not _is_alive(pid):
                time.sleep(0.3)
                try:
                    with open(log_file,"r",encoding="utf-8",errors="replace") as f:
                        f.seek(last); r=f.read()
                        if r: sys.stdout.write(r); sys.stdout.flush()
                except OSError: pass
                print(f"\n\n  {D}processo terminou{Z}"); _wait(); break
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass


# ══════════════════════════════════════════════════════════════
#  DATA BROWSER
# ══════════════════════════════════════════════════════════════

def screen_data():
    from core.ops.db import list_runs, delete_run

    while True:
        runs = list_runs(limit=30)
        if not runs:
            _head("DATA"); print(f"\n  {D}Sem runs.{Z}"); _wait(); return

        items = []
        for r in runs:
            roi = r.get("roi")
            rc = G if roi and roi >= 0 else R if roi else D
            roi_s = f"{rc}{roi:+.1f}%{Z}" if roi is not None else f"{D}  —{Z}"
            sh = r.get("sharpe"); sh_s = f"{sh:.2f}" if sh else f"{D}—{Z}"
            wr = r.get("win_rate"); wr_s = f"{wr:.0f}%" if wr else f"{D}—{Z}"
            n  = r.get("n_trades") or "—"
            eq = r.get("final_equity"); eq_s = f"${eq:,.0f}" if eq else f"{D}—{Z}"
            name = _en(r["engine"])
            items.append(f"{r['run_id']:18s}  {name:18s}  {roi_s:>16s}  {sh_s:>6s}  {wr_s:>4s}  {str(n):>4s}  {eq_s:>9s}")

        hdr = f"{'RUN':18s}  {'ENGINE':18s}  {'ROI':>7s}  {'Sh':>6s}  {'WR':>4s}  {'N':>4s}  {'FINAL':>9s}"
        idx, key = _sel("DATA", items, hotkeys={"d":"Apagar","o":"Abrir"}, hdr=hdr)
        if idx is None: return
        run = runs[idx]

        if key == "enter": screen_run_detail(run)
        elif key == "o":   _open_folder(run)
        elif key == "d":
            _head("DATA")
            print(f"\n  {B}{_en(run['engine'])}{Z}  {run['run_id']}")
            if _confirm("Apagar da DB?"):
                also = _confirm("Apagar ficheiros?")
                delete_run(run["run_id"], delete_files=also)
                print(f"  {G}✓{Z}"); time.sleep(0.4)


# ══════════════════════════════════════════════════════════════
#  RUN DETAIL
# ══════════════════════════════════════════════════════════════

def _charts(run):
    jp = run.get("json_path")
    if not jp: return {}
    d = Path(jp).parent.parent / "charts"
    if not d.exists(): return {}
    r = {"mc":[],"eq":[],"tr":[]}
    for f in sorted(d.glob("*.png")):
        n = f.name.lower()
        if "montecarlo" in n:   r["mc"].append(f)
        elif "dashboard" in n or "equity" in n: r["eq"].append(f)
        elif "trades_" in n:    r["tr"].append(f)
    return r

def screen_run_detail(run):
    from core.ops.db import get_trades
    trades = get_trades(run["run_id"])
    closed = [t for t in trades if t["result"] in ("WIN","LOSS")]
    ch = _charts(run)
    name = _en(run["engine"])

    while True:
        _head(name, f"{run.get('version','')}   {run['run_id']}")
        w = min(tw()-4, 80)

        # ── Metrics bar ──
        roi=run.get("roi"); sh=run.get("sharpe"); so=run.get("sortino")
        wr=run.get("win_rate"); eq=run.get("final_equity")

        rc = G if roi and roi>=0 else R if roi else D
        metrics = [
            f"{B}ROI{Z} {rc}{roi:+.2f}%{Z}" if roi is not None else f"{B}ROI{Z} {D}—{Z}",
            f"{B}Sharpe{Z} {sh:.3f}" if sh is not None else f"{B}Sharpe{Z} {D}—{Z}",
            f"{B}Sortino{Z} {so:.3f}" if so is not None else f"{B}Sortino{Z} {D}—{Z}",
            f"{B}WR{Z} {wr:.1f}%" if wr is not None else f"{B}WR{Z} {D}—{Z}",
            f"{B}Final{Z} ${eq:,.0f}" if eq is not None else f"{B}Final{Z} {D}—{Z}",
        ]
        print(f"\n  {'   '.join(metrics)}")

        # ── Info ──
        print(f"\n  {D}Data{Z} {(run.get('timestamp') or '')[:19]}   "
              f"{D}TF{Z} {run.get('interval','—')}   "
              f"{D}Sym{Z} {run.get('n_symbols','—')}   "
              f"{D}Trades{Z} {run.get('n_trades','—')}   "
              f"{D}Capital{Z} ${run.get('account_size',0):,.0f}")

        jp = run.get("json_path")
        if jp:
            folder = Path(jp).parent.parent
            if folder.exists():
                print(f"  {D}{folder}{Z}")

        # ── Top trades ──
        if closed:
            _line(w)
            print(f"  {B}TOP TRADES{Z}")
            for t in sorted(closed, key=lambda t: t["pnl"], reverse=True)[:8]:
                c = G if t["result"]=="WIN" else R
                ico = "✓" if t["result"]=="WIN" else "✗"
                print(f"  {c}{ico}{Z}  {t['symbol']:12s} {t['direction']:8s}"
                      f"  PnL {c}${t['pnl']:>+8,.1f}{Z}  RR {t.get('rr',0):.2f}x"
                      f"  {D}{t.get('trade_time','')}{Z}")

            # ── By symbol ──
            print()
            print(f"  {B}POR SIMBOLO{Z}")
            by_sym: dict[str,list] = {}
            for t in closed: by_sym.setdefault(t["symbol"],[]).append(t)
            for sym in sorted(by_sym):
                ts=by_sym[sym]; w2=sum(1 for t in ts if t["result"]=="WIN")
                pnl=sum(t["pnl"] for t in ts)
                c = G if pnl>0 else R
                print(f"  {c}{'✓' if pnl>0 else '✗'}{Z}  {sym:12s}"
                      f"  n={len(ts):>3d}  WR={w2/len(ts)*100:>5.1f}%  PnL={c}${pnl:>+9,.0f}{Z}")

        # ── Footer ──
        _line(w)
        opts = []
        if ch.get("mc"): opts.append(f"{B}M{Z}{D}=Monte Carlo{Z}")
        if ch.get("eq"): opts.append(f"{B}E{Z}{D}=Equity{Z}")
        if ch.get("tr"): opts.append(f"{B}C{Z}{D}=Charts ({len(ch['tr'])}){Z}")
        opts.append(f"{B}O{Z}{D}=Pasta{Z}")
        opts.append(f"{D}Esc{Z}")
        print(f"  {'   '.join(opts)}")

        k = _get_key()
        if k in ("esc","q"): return
        elif k=="m" and ch.get("mc"): _openf(ch["mc"][0])
        elif k=="e" and ch.get("eq"): _openf(ch["eq"][0])
        elif k=="c" and ch.get("tr"): _trade_charts(ch["tr"])
        elif k=="o": _open_folder(run)


def _trade_charts(files):
    items = [f.stem.replace("trades_","").replace("_15m","") for f in files]
    idx,k = _sel("TRADE CHARTS", items)
    if idx is not None and k=="enter": _openf(files[idx])

def _openf(path):
    try:
        if sys.platform == "win32":
            os.startfile(str(path))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except (OSError, FileNotFoundError):
        pass

def _open_folder(run):
    jp = run.get("json_path")
    if not jp: return
    f = Path(jp).parent.parent
    if f.exists(): _openf(f)


# ══════════════════════════════════════════════════════════════
#  STATUS
# ══════════════════════════════════════════════════════════════

def screen_status(wait=True):
    from core.ops.db import stats_summary
    from core.ops.proc import list_procs

    _head("STATUS")
    procs = list_procs()
    running = [p for p in procs if p.get("alive")]
    s = stats_summary()

    w = min(tw()-4, 60)
    if running:
        print(f"\n  {G}ENGINES ACTIVOS  {B}{len(running)}{Z}")
        for p in running:
            print(f"  {G}●{Z}  {B}{_en(p['engine']):20s}{Z}  {D}PID {p['pid']}  desde {(p.get('started') or '')[:16]}{Z}")
    else:
        print(f"\n  {D}nenhum engine activo{Z}")

    print(f"\n  {B}Runs{Z}  {s['total_runs']}     {B}Trades{Z}  {s['total_trades']}")

    if s["by_engine"]:
        _line(w)
        print(f"  {'ENGINE':20s}  {'RUNS':>5s}  {'AVG ROI':>8s}  {'AVG SHARPE':>10s}")
        _line(w)
        for e in s["by_engine"]:
            roi_s = f"{e['avg_roi']:+.1f}%" if e["avg_roi"] is not None else "  —"
            sh_s  = f"{e['avg_sharpe']:.2f}" if e["avg_sharpe"] is not None else "  —"
            c = G if e.get("avg_roi",0) and e["avg_roi"]>=0 else R
            print(f"  {_en(e['engine']):20s}  {e['n']:>5d}  {c}{roi_s:>8s}{Z}  {sh_s:>10s}")

    best = s.get("best_run")
    if best:
        print(f"\n  {Y}★  {_en(best['engine'])}  {best['run_id']}"
              f"  ROI {best['roi']:+.1f}%  Sharpe {best['sharpe']:.2f}{Z}")

    if wait: _wait()


# ══════════════════════════════════════════════════════════════
#  CLI ENTRY
# ══════════════════════════════════════════════════════════════

def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    _enable_vt100()

    pa = argparse.ArgumentParser(prog="aurum", description="☿ AURUM Finance v2")
    sub = pa.add_subparsers(dest="cmd")

    # Real strategy names (must match keys in STRATEGIES dict and branches in _resolve).
    # backtest supports 6; simulator/live are limited to engines with a runtime mode.
    BT_STRATS   = ["citadel", "renaissance", "deshaw", "jump", "bridgewater", "millennium", "kepos", "graham", "medallion", "twosigma", "aqr"]
    LIVE_STRATS = ["citadel", "janestreet", "millennium"]

    p=sub.add_parser("backtest",aliases=["bt"]); p.add_argument("strategy",choices=BT_STRATS,nargs="?",default="citadel"); p.add_argument("--days",type=int,default=90); p.add_argument("--plots",action="store_true"); p.add_argument("--leverage",type=float,default=None)
    p=sub.add_parser("simulator",aliases=["sim"]); p.add_argument("strategy",choices=LIVE_STRATS,nargs="?",default="citadel"); p.add_argument("--mode",type=int,default=1)
    p=sub.add_parser("live"); p.add_argument("strategy",choices=LIVE_STRATS,nargs="?",default="citadel"); p.add_argument("--mode",type=int,default=3)
    sub.add_parser("ps")
    p=sub.add_parser("tail"); p.add_argument("pid",type=int)
    p=sub.add_parser("stop"); p.add_argument("pid",type=int)
    sub.add_parser("data",aliases=["logs"])
    sub.add_parser("status")
    p=sub.add_parser("export",help="generate a single-file analysis snapshot for external review")
    p.add_argument("-o","--output",type=str,default=None,help="custom output path (default: data/exports/analysis_YYYY-MM-DD_HHMM.json)")

    a = pa.parse_args()

    def _unsupported(strat, method):
        print(f"\n  {R}✗ strategy '{strat}' does not support method '{method}'{Z}")
        print(f"  {D}supported for {method}: {', '.join(BT_STRATS if method == 'backtest' else LIVE_STRATS)}{Z}\n")

    if a.cmd is None: screen_main()
    elif a.cmd in ("backtest","bt"):
        st = a.strategy
        lev = str(a.leverage) if a.leverage else ""
        ek,sc,si = _resolve(st,"backtest",{"days":str(a.days),"plots":a.plots,"leverage":lev})
        if ek: _launch(ek,sc,si,STRATEGIES[st]["name"],"BACKTEST")
        else:  _unsupported(st, "backtest")
    elif a.cmd in ("simulator","sim"):
        st = a.strategy
        ek,sc,si = _resolve(st,"simulator",{"mode":str(a.mode)})
        if ek: _launch(ek,sc,si,STRATEGIES[st]["name"],"SIMULADOR")
        else:  _unsupported(st, "simulator")
    elif a.cmd == "live":
        st = a.strategy
        ek,sc,si = _resolve(st,"live",{"mode":str(a.mode)})
        if ek: _launch(ek,sc,si,STRATEGIES[st]["name"],"LIVE")
        else:  _unsupported(st, "live")
    elif a.cmd == "ps":   screen_procs()
    elif a.cmd == "tail":  _screen_tail(a.pid)
    elif a.cmd == "stop":
        from core.ops.proc import stop_proc
        print(f"  {'✓' if stop_proc(a.pid) else 'nao encontrado'}")
    elif a.cmd in ("data","logs"): screen_data()
    elif a.cmd == "status": screen_status(wait=False)
    elif a.cmd == "export":
        from core.analysis.analysis_export import export_analysis
        from datetime import datetime as _dt
        if a.output:
            out = Path(a.output)
        else:
            ts = _dt.now().strftime("%Y-%m-%d_%H%M")
            out = _ROOT / "data" / "exports" / f"analysis_{ts}.json"
        print(f"  {D}generating snapshot...{Z}")
        d = export_analysis(output_path=out)
        try:
            size_mb = out.stat().st_size / (1024 * 1024)
        except Exception:
            size_mb = 0.0
        n_runs = len(d.get("runs", []))
        n_trades = d.get("analysis", {}).get("n_trades", 0)
        print(f"  {G}✓{Z} {out}")
        print(f"  {D}{size_mb:.2f} MB · {n_runs} runs · {n_trades} trades on latest{Z}")

if __name__ == "__main__":
    main()
