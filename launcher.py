#!/usr/bin/env python3
"""
AURUM Finance — Terminal v4
Bloomberg Terminal aesthetic. Clean, functional, no bugs.
"""
import os, sys, subprocess, threading, queue, json, time, math
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _configure_windows_tk() -> None:
    """Prefer the Tcl/Tk bundled with the active Python installation."""
    if sys.platform != "win32":
        return
    py_root = Path(sys.executable).resolve().parent
    tcl_root = py_root / "tcl"
    tcl_lib = tcl_root / "tcl8.6"
    tk_lib = tcl_root / "tk8.6"
    if (tcl_lib / "init.tcl").exists():
        os.environ["TCL_LIBRARY"] = str(tcl_lib)
    if (tk_lib / "tk.tcl").exists():
        os.environ["TK_LIBRARY"] = str(tk_lib)


def _boot_workers_enabled() -> bool:
    return os.getenv("AURUM_DISABLE_BOOT_WORKERS", "").strip().lower() not in {
        "1", "true", "yes", "on",
    }


def _test_mode_enabled() -> bool:
    return os.getenv("AURUM_TEST_MODE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _lazy_connections():
    """Import and return (ConnectionManager, MARKETS) on-demand.

    core.data.connections transitively pulls pandas (~350ms) and
    requests (~200ms). Deferring to first actual use shaves ~640ms off
    launcher boot import time. After first call, sys.modules caches the
    import — subsequent calls are ~10us.
    """
    from core.data.connections import ConnectionManager, MARKETS
    return ConnectionManager, MARKETS


_conn_singleton = None  # lazy ConnectionManager instance


def _get_conn():
    """Return the module-level ConnectionManager singleton, creating it on
    first call. Defers the pandas/requests import until the user first
    interacts with a connections/markets screen."""
    global _conn_singleton
    if _conn_singleton is None:
        ConnectionManager, _MARKETS = _lazy_connections()
        _conn_singleton = ConnectionManager()
    return _conn_singleton


def _ensure_main_groups():
    """Populate the module-level MAIN_GROUPS list on first call.

    Called from App.__init__ and also via module __getattr__ when
    mod.MAIN_GROUPS is accessed before App() instantiation (e.g. in tests).
    Defers the core.data.connections import (pandas + requests, ~640ms)
    to first actual access rather than module import time.

    Safe to call multiple times — idempotent via globals() check.
    """
    _g = globals()
    if _g.get("MAIN_GROUPS") is None:
        _CM, _MARKETS = _lazy_connections()
        _g["MAIN_GROUPS"] = _menu_main_groups(
            _MARKETS, TILE_MARKETS, TILE_EXECUTE, TILE_RESEARCH, TILE_CONTROL
        )


_configure_windows_tk()

import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox

from config.engines import SCRIPT_TO_KEY
from core.ops.python_runtime import preferred_python_executable
from core.ops.health import runtime_health
from core.ops.persistence import atomic_write_json
from launcher_support.bootstrap import (
    ENGINE_PREFIX_ALIASES as _BOOTSTRAP_ENGINE_PREFIX_ALIASES,
    NO_WINDOW as _BOOTSTRAP_NO_WINDOW,
    build_vps_ssh_command as _BOOTSTRAP_BUILD_VPS_SSH_COMMAND,
    build_vps_log_tail_command as _BOOTSTRAP_BUILD_VPS_LOG_TAIL_COMMAND,
    build_vps_stop_command as _BOOTSTRAP_BUILD_VPS_STOP_COMMAND,
    build_millennium_bootstrap_launch_command as _BOOTSTRAP_BUILD_MILLENNIUM_BOOTSTRAP_LAUNCH_COMMAND,
    current_vps_host as _BOOTSTRAP_CURRENT_VPS_HOST,
    current_vps_project as _BOOTSTRAP_CURRENT_VPS_PROJECT,
    VPS_LIVE_SCREEN as _BOOTSTRAP_VPS_LIVE_SCREEN,
    VPS_MILLENNIUM_SCREEN as _BOOTSTRAP_VPS_MILLENNIUM_SCREEN,
    VPS_HOST as _BOOTSTRAP_VPS_HOST,
    VPS_PROJECT as _BOOTSTRAP_VPS_PROJECT,
    canonical_engine_key as _bootstrap_canonical_engine_key,
    engine_display_name as _bootstrap_engine_display_name,
    fetch_ticker_loop as _bootstrap_fetch_ticker_loop,
    run_vps_cmd as _bootstrap_run_vps_cmd,
    ticker_str as _bootstrap_ticker_str,
)
from launcher_support.execution import (
    live_launch_plan,
    script_to_proc_key as _script_to_proc_key,
    strategies_progress_target as _strategies_progress_target_helper,
)
from launcher_support import cockpit_tab as cockpit_tab_mod
from launcher_support import command_center as command_center_mod
from launcher_support import dashboard_controls as dashboard_controls_mod
from launcher_support.screens._metrics import emit_timing_metric, timed_legacy_switch
from launcher_support.screens._persistence import (
    configure_screen_logging as _configure_screen_logging,
    dump_screen_metrics as _dump_screen_metrics,
)
from launcher_support.menu_data import (
    BLOCK_DESCRIPTIONS as _MENU_BLOCK_DESCRIPTIONS,
    COMMAND_ROADMAPS as _MENU_COMMAND_ROADMAPS,
    MAIN_MENU as _MENU_MAIN_MENU,
    main_groups as _menu_main_groups,
)

# -----------------------------------------------------------
# PALETTE — imported from core/ui_palette (SSOT)
# -----------------------------------------------------------
from core.ui.ui_palette import (
    BG, BG2, BG3, PANEL, BORDER, BORDER_H,
    AMBER, AMBER_D, AMBER_B,
    WHITE, DIM, DIM2, GREEN, RED,
    FONT,
)

# --- 3D MENU — tile accents (SSOT: core/ui_palette) --------
from core.ui.ui_palette import (
    TILE_MARKETS, TILE_EXECUTE, TILE_RESEARCH, TILE_CONTROL, TILE_DIM_FACTOR,
)

# -----------------------------------------------------------
# MENUS
# -----------------------------------------------------------
ENGINE_PREFIX_ALIASES = _BOOTSTRAP_ENGINE_PREFIX_ALIASES
VPS_HOST = _BOOTSTRAP_VPS_HOST
VPS_PROJECT = _BOOTSTRAP_VPS_PROJECT
_NO_WINDOW = _BOOTSTRAP_NO_WINDOW
canonical_engine_key = _bootstrap_canonical_engine_key
engine_display_name = _bootstrap_engine_display_name
_vps_cmd = _bootstrap_run_vps_cmd
_fetch = _bootstrap_fetch_ticker_loop
_ticker_str = _bootstrap_ticker_str
_build_vps_ssh_command = _BOOTSTRAP_BUILD_VPS_SSH_COMMAND
_build_vps_log_tail_command = _BOOTSTRAP_BUILD_VPS_LOG_TAIL_COMMAND
_build_vps_stop_command = _BOOTSTRAP_BUILD_VPS_STOP_COMMAND
_build_millennium_bootstrap_launch_command = _BOOTSTRAP_BUILD_MILLENNIUM_BOOTSTRAP_LAUNCH_COMMAND
_vps_host = _BOOTSTRAP_CURRENT_VPS_HOST
_vps_project = _BOOTSTRAP_CURRENT_VPS_PROJECT
_vps_live_screen = _BOOTSTRAP_VPS_LIVE_SCREEN
_vps_millennium_screen = _BOOTSTRAP_VPS_MILLENNIUM_SCREEN

MAIN_MENU = [
    ("MARKETS",        "markets",     "Seleccionar mercado activo"),
    ("CONNECTIONS",    "connections", "Contas & exchanges"),
    ("TERMINAL",       "terminal",    "Charts, macro, research"),
    ("DATA",           "data",        "Backtests · engine logs · reports"),
    ("STRATEGIES",     "strategies",  "Backtest & live engines"),
    ("ARBITRAGE",      "alchemy",     "CEX·CEX execution + DEX·DEX / CEX·DEX scanner"),
    ("MACRO BRAIN",    "macro_brain", "Autonomous CIO · regime → thesis → paper positions"),
    ("RISK",           "risk",        "Portfolio & risk console"),
    ("COMMAND CENTER", "command",     "Site, servers, admin panel"),
    ("SETTINGS",       "settings",    "Config, keys, Telegram"),
]

# --- MAIN_GROUPS: 9 destinos agrupados em 4 tiles (Bloomberg 3D) ----
# Format: (label, key_num, color, [(child_label, method_name), ...])
# MAIN_MENU (above) kept for legacy Fibonacci fallback + descriptions.
def _markets_children():
    """Build MARKETS tile children dynamically from the MARKETS registry —
    each market gets its own row (CRYPTO FUTURES / CRYPTO SPOT / FOREX /
    EQUITIES / COMMODITIES / INDICES / ON-CHAIN). Click activates the
    market + routes to its dashboard (or shows COMING SOON for stubs).
    Note: this definition is superseded by the _menu_main_groups() call
    below — kept here only for documentation purposes."""
    _CM, _MARKETS = _lazy_connections()
    out = []
    for mk in _MARKETS:
        method = f"_market_{mk}"
        label = _MARKETS[mk]["label"]
        out.append((label, method))
    return out


# NOTE: this MAIN_GROUPS definition is kept for documentation only.
# The real MAIN_GROUPS is populated lazily via module __getattr__ (see end of
# imports section) or via _ensure_main_groups() called from App.__init__.

BLOCK_DESCRIPTIONS = {
    "_markets": "quotes, universe e mercado ativo",
    "_crypto_dashboard": "snapshot visual do cripto book",
    "_market_crypto_futures": "Binance · Bybit · OKX · Hyperliquid · Gate",
    "_market_crypto_spot":    "Binance · Coinbase · Kraken (em breve)",
    "_market_forex":          "Forex / CFDs via MetaTrader 5 (em breve)",
    "_market_equities":       "Equities via IB / Alpaca (em breve)",
    "_market_commodities":    "Gold · Oil · Nat Gas (em breve)",
    "_market_indices":        "S&P · NASDAQ · DXY (em breve)",
    "_market_onchain":        "DeFi · DEX data · on-chain (em breve)",
    "_strategies": "engines · backtest · live",
    "_strategies_backtest": "engines históricas · walkforward · MC",
    "_strategies_live": "engines ao vivo · demo · testnet",
    "_arbitrage_hub": "cex/cex, dex/dex e cex/dex routes",
    "_macro_brain_menu": "cio autonomo, regime e thesis",
    "_risk_menu": "portfolio, limites e kill-switch",
    "_terminal": "charts, macro e research terminal",
    "_data_center": "backtests, logs e reports",
    "_connections": "exchanges, contas e credenciais",
    "_command_center": "site, servers e operacao",
    "_config": "settings, keys e telegram",
}

# Per-feature roadmap lines for the COMMAND CENTER coming-soon screens.
COMMAND_ROADMAPS = {
    "DEPLOY": [
        "Git push (origin/main, tags)",
        "Vercel / Netlify deploy hooks",
        "Docker build + registry push",
        "VPS rsync + systemctl restart",
    ],
    "SERVERS": [
        "VPS list (Hetzner / Vultr / Linode)",
        "Inline SSH terminal",
        "Status monitor (uptime, load, disk)",
        "Tail journalctl / nginx logs",
    ],
    "DATABASES": [
        "SQLite browser (read-only schema + query)",
        "PostgreSQL connect via DSN",
        "Backup / restore snapshots",
        "Migration runner",
    ],
    "SERVICES": [
        "systemd unit list + start/stop",
        "PM2 process tree",
        "Docker containers (ps / logs / restart)",
        "Cron / scheduled tasks viewer",
    ],
    "SYSTEM": [
        "CPU / RAM / disk via psutil",
        "Network interfaces & throughput",
        "Uptime + load average",
        "Top processes",
    ],
}

# Extracted navigation data re-bound here so launcher.py keeps the same
# public constants while the menu topology moves out incrementally.
MAIN_MENU = list(_MENU_MAIN_MENU)
# MAIN_GROUPS: populated lazily on first App() instantiation (see _ensure_main_groups).
# Deferring here avoids the ~640ms pandas+requests import at module load time.
BLOCK_DESCRIPTIONS = dict(_MENU_BLOCK_DESCRIPTIONS)
COMMAND_ROADMAPS = {k: list(v) for k, v in _MENU_COMMAND_ROADMAPS.items()}

SUB_MENUS = {
    "backtest": [
        ("CITADEL",      "engines/citadel.py",      "Systematic momentum — trend-following + fractal alignment"),
        ("JUMP",         "engines/jump.py",       "Order flow — CVD divergence + volume imbalance"),
        ("BRIDGEWATER",  "engines/bridgewater.py",          "Macro sentiment — funding + OI + LS ratio contrarian"),
        ("MILLENNIUM",   "engines/millennium.py",  "Multi-strategy pod — ensemble orchestrator"),
        ("TWO SIGMA",    "engines/twosigma.py",       "ML meta-ensemble — LightGBM walk-forward"),
        ("RENAISSANCE",  "engines/renaissance.py", "Harmonic patterns — Bayesian + entropy + Hurst"),
        ("GRAHAM",       "engines/graham.py",      "Endogenous momentum — trend + Hawkes ENDO regime gate"),
    ],
    "live": [
        ("PAPER",        "engines/live.py",           "Execução simulada — sem ordens reais"),
        ("DEMO",         "engines/live.py",           "Binance Futures Demo API"),
        ("TESTNET",      "engines/live.py",           "Binance Futures Testnet"),
        ("LIVE",         "engines/live.py",           "CAPITAL REAL — extremo cuidado"),
        ("JANE STREET",  "engines/janestreet.py",      "Cross-venue arb — funding/basis multi-exchange"),
    ],
    "tools": [
        ("AQR",          "engines/aqr.py",         "Adaptive allocation — evolutionary parameter optimization"),
        ("NEXUS API",    "run_api.py",               "REST API + WebSocket (porta 8000)"),
        ("WINTON",       "core/chronos.py",           "Time-series intelligence — HMM + GARCH + Hurst"),
    ],
}

BANNER = """\
 ¦¦¦¦¦+ ¦¦+   ¦¦+¦¦¦¦¦¦+ ¦¦+   ¦¦+¦¦¦+   ¦¦¦+
¦¦+--¦¦+¦¦¦   ¦¦¦¦¦+--¦¦+¦¦¦   ¦¦¦¦¦¦¦+ ¦¦¦¦¦
¦¦¦¦¦¦¦¦¦¦¦   ¦¦¦¦¦¦¦¦¦++¦¦¦   ¦¦¦¦¦+¦¦¦¦+¦¦¦
¦¦+--¦¦¦¦¦¦   ¦¦¦¦¦+--¦¦+¦¦¦   ¦¦¦¦¦¦+¦¦++¦¦¦
¦¦¦  ¦¦¦+¦¦¦¦¦¦++¦¦¦  ¦¦¦+¦¦¦¦¦¦++¦¦¦ +-+ ¦¦¦
+-+  +-+ +-----+ +-+  +-+ +-----+ +-+     +-+\
"""

# -----------------------------------------------------------
# STRATEGY BRIEFINGS — philosophy + logic before execution
# -----------------------------------------------------------
BANNER_PREMIUM = """\
A U R U M
F I N A N C E
"""

SYSTEM_TAGLINE = "INSTITUTIONAL QUANT TERMINAL"

from launcher_support.briefings import BRIEFINGS


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
    ("30 DIAS",   "~1 mês — validação rápida",        "30"),
    ("90 DIAS",   "~3 meses — backtest padrão",        "90"),
    ("180 DIAS",  "~6 meses — médio prazo",            "180"),
    ("365 DIAS",  "~1 ano — ciclo completo",           "365"),
]


# -----------------------------------------------------------
# BACKTEST LIST COLUMNS — single source of truth
# -----------------------------------------------------------
# (label, widget width in chars). Used by both the crypto-futures
# dashboard Backtest tab and the standalone DATA > BACKTESTS screen,
# plus the row renderer in _dash_backtest_render. Keeping the widths
# here instead of duplicating them in three places is what stopped
# the header and the rows from drifting out of alignment. Monospace
# char widths only match at the same font size AND weight, so header
# and rows both render at (FONT, 8, *).
_BT_COLS: list[tuple[str, int]] = [
    ("DATE / TIME",  19),
    ("STRATEGY",     14),
    # TF: 5 → 6 chars. "15m"/"1h"/"4h" cabem facil em 5, mas
    # a coluna encostava no DAYS; 6 da respiro visual e fica
    # na mesma largura da coluna DAYS/TRADES — visual mais consistente.
    ("TF",            6),
    ("DAYS",          5),
    ("BASKET",       10),
    ("RUN",          14),
    ("TRADES",        8),
    ("WIN%",          8),
    ("PNL",          12),
    ("SHARPE",        8),
    ("DD",            8),
]


# -----------------------------------------------------------
# BACKTEST RUNS TABLE — per-engine view (ENGINE column dropped)
# -----------------------------------------------------------
# Used by the right-bottom runs list in the BACKTEST tab after
# the engine → run → metrics hierarchy refactor. Same char widths
# as _BT_COLS so the existing row renderer can be reused; the
# STRATEGY column is omitted because the list is already filtered
# to a single engine (picked in the left panel).
_BT_RUN_COLS: list[tuple[str, int]] = [
    ("DATE / TIME",  19),
    ("TF",            5),
    ("DAYS",          5),
    ("BASKET",       10),
    ("RUN",          14),
    ("TRADES",        8),
    ("WIN%",          8),
    ("PNL",          12),
    ("SHARPE",        8),
    ("DD",            8),
]


# -----------------------------------------------------------
# BACKTEST ENGINE BADGES — OOS status glyphs for the left panel
# -----------------------------------------------------------
# Static map: CLAUDE.md engine table + 2026-04-16 OOS audit
# verdicts. Keys cover both institutional slugs and their legacy
# lowercase aliases (e.g. "thoth" → bridgewater) so runs written
# before the engine rename still get the right glyph.
_ENGINE_BADGES: dict[str, str] = {
    "citadel":            "?",
    "backtest":           "?",
    "jump":               "?",
    "mercurio":           "?",
    "renaissance":        "??",
    "harmonics":          "??",
    "harmonics_backtest": "??",
    "bridgewater":        "??",
    "thoth":              "??",
    "phi":                "??",
    "two_sigma":          "?",
    "twosigma":           "?",
    "prometeu":           "?",
    "aqr":                "?",
    "darwin":             "?",
    "jane_street":        "?",
    "janestreet":         "?",
    "arbitrage":          "?",
    "millennium":         "·",
    "multistrategy":      "·",
    "winton":             "·",
    "graham":             "???",
}


def _boot_tunnel_manager():
    """Lazy construct TunnelManager from keys.json -> vps_ssh block.

    Returns None silently if config missing or malformed — launcher
    keeps working in local-disk mode. Singleton lives em
    launcher_support/tunnel_registry pra sobreviver ao problema
    __main__-vs-launcher (quando `python launcher.py` roda, o modulo
    launcher vira `__main__` e `from launcher import X` de outro lugar
    carrega um modulo separado sem o singleton).
    """
    from launcher_support.tunnel_registry import (
        get_tunnel_manager as _reg_get,
        set_tunnel_manager as _reg_set,
        set_tunnel_boot_error as _reg_set_err,
    )
    current = _reg_get()
    if current is not None:
        return current
    _reg_set_err(None)  # clear any prior boot error
    try:
        # Encrypted-aware: fail-closed quando enc ativo. Fallback
        # manual pro plaintext so em ImportError (cryptography ausente).
        # KeyStoreLockedError/Corrupt nao caem pra plaintext stale.
        from core.risk.key_store import (
            load_runtime_keys,
            KeyStoreError,
        )
        try:
            data = load_runtime_keys(
                allow_plaintext_env="_LAUNCHER_NEVER_PLAINTEXT_"
            )
        except KeyStoreError:
            return None
        except (ImportError, ModuleNotFoundError):
            from pathlib import Path as _Path
            import json as _json
            keys_path = _Path("config/keys.json")
            if not keys_path.exists():
                return None
            data = _json.loads(keys_path.read_text(encoding="utf-8"))
        block = (data or {}).get("vps_ssh")
        if not block or not block.get("host"):
            return None
        # Reject obvious placeholders from the 2026-04-19 keys wipe template.
        # Without this check, TunnelManager spawns ssh with "cole_aqui_o_host"
        # and floods data/.cockpit_cache/tunnel.log with hundreds of dead
        # reconnect attempts while the cockpit UI silently shows no data.
        if _vps_block_has_placeholders(block):
            import logging as _log
            reason = ("vps_ssh config com placeholders (COLE_AQUI_*). "
                      "Edit config/keys.json + restart launcher.")
            _log.getLogger("aurum.launcher").error("tunnel: %s", reason)
            _reg_set_err(reason)
            return None
        from launcher_support.ssh_tunnel import TunnelConfig, TunnelManager
        from pathlib import Path as _Path
        cfg = TunnelConfig(
            host=block["host"],
            user=block.get("user", "root"),
            ssh_port=int(block.get("ssh_port", 22)),
            local_port=int(block.get("local_port", 8787)),
            remote_host=block.get("remote_host", "localhost"),
            remote_port=int(block.get("remote_port", 8787)),
            key_path=block.get("key_path"),
            # Cockpit tunnel uses a dedicated known_hosts file so a stale
            # global ~/.ssh/known_hosts entry doesn't black-hole the UI.
            known_hosts_path=str((_Path("data/.cockpit_cache/known_hosts")).resolve()),
        )
        manager = TunnelManager(cfg, log_dir=_Path("data/.cockpit_cache"))
        _reg_set(manager)
        return manager
    except Exception:
        return None


def _vps_block_has_placeholders(block: dict) -> bool:
    """True se qualquer campo critico contem template-placeholder string.

    O wipe 2026-04-19 substituiu segredos por COLE_AQUI_*; sem rejeitar
    aqui, o launcher spawna ssh com hostname invalido e o watchdog gasta
    retries eternos. Checagem case-insensitive — placeholder pode vir com
    variantes de capitalizacao.
    """
    markers = ("cole_aqui", "COLE_AQUI", "<paste", "<your")
    critical = (block.get("host"), block.get("key_path"), block.get("user"))
    for v in critical:
        if v is None:
            continue
        vs = str(v)
        for m in markers:
            if m.lower() in vs.lower():
                return True
    return False


def get_tunnel_manager():
    """Public accessor — delega pro tunnel_registry singleton."""
    from launcher_support.tunnel_registry import get_tunnel_manager as _reg_get
    return _reg_get()


class App(tk.Tk):
    _SPLASH_DESIGN_W = 920
    _SPLASH_DESIGN_H = 640
    _MENU_DESIGN_W = 920
    _MENU_DESIGN_H = 540

    def __init__(self):
        boot_t0 = time.perf_counter()
        self._shutdown_done = False
        _tk_t0 = time.perf_counter()
        super().__init__()
        emit_timing_metric("boot.tk_root", ms=(time.perf_counter() - _tk_t0) * 1000.0)
        _logging_t0 = time.perf_counter()
        try:
            _configure_screen_logging()
        except Exception:
            pass
        emit_timing_metric("boot.screen_logging", ms=(time.perf_counter() - _logging_t0) * 1000.0)

        self.title("AURUM Terminal")
        self.configure(bg=BG)
        # Defensive: forca Tk default palette pra BG em tudo. Se alguma
        # Frame em algum canto esquecer bg=BG explicito, o Windows
        # mostraria SystemButtonFace (~#F0F0F0) = "branco" no fundo.
        # tk_setPalette varre todos widget defaults e seta em massa —
        # inclui menu/dialog/messagebox criados internamente. Chamado
        # ANTES de chrome/widgets serem criados.
        _palette_t0 = time.perf_counter()
        try:
            self.tk_setPalette(
                background=BG, foreground=WHITE,
                activeBackground=BG3, activeForeground=WHITE,
                highlightColor=BORDER, highlightBackground=BG,
            )
        except Exception:
            pass
        emit_timing_metric("boot.palette", ms=(time.perf_counter() - _palette_t0) * 1000.0)
        _dpi_t0 = time.perf_counter()
        self._configure_windows_dpi()
        self.geometry("960x660")
        self.minsize(860, 560)
        emit_timing_metric("boot.dpi_geometry", ms=(time.perf_counter() - _dpi_t0) * 1000.0)

        # Taskbar icon: deferred via after_idle to avoid ~70ms boot hit.
        # Icon and AppUserModelID are cosmetic; apply after window renders.
        _icon_scheduled_t0 = time.perf_counter()
        def _apply_taskbar_icon():
            _icon_t0 = time.perf_counter()
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("aurum.finance.terminal")
            except: pass
            try:
                ico = ROOT / "server" / "logo" / "aurum.ico"
                if ico.exists(): self.iconbitmap(str(ico))
            except: pass
            emit_timing_metric("boot.icon_deferred", ms=(time.perf_counter() - _icon_t0) * 1000.0)
        self.after_idle(_apply_taskbar_icon)
        emit_timing_metric("boot.icon", ms=(time.perf_counter() - _icon_scheduled_t0) * 1000.0)

        _state_t0 = time.perf_counter()
        self.proc = None
        self.oq = queue.Queue()
        self._ui_task_queue = queue.Queue()
        self._ui_task_after_id = None
        self._ui_alive = True
        self.history = []  # nav history for back
        self._exec_progress_after_id = None
        self._exec_visual_mode = None
        self._exec_progress_value = 0.0
        self._exec_progress_target = 0.0
        self._exec_progress_pulse = 0
        self._exec_recent_lines = []
        self._exec_stage_label = None
        self._exec_file_label = None
        self._exec_pct_label = None
        self._exec_bar_canvas = None
        self._exec_recent_labels = []
        self._exec_live_tail_label = None
        self._exec_progress_last_paint = 0.0
        self._exec_last_feed_at = 0.0
        self._exec_managed_info = None

        # --- Bloomberg 3D main menu state ----------------
        self._start_t = time.monotonic()
        self._menu_live = {
            "markets":  {},
            "execute":  {},
            "research": {},
            "control":  {},
        }
        self._menu_focused_tile = 0      # 0..3 index into MAIN_GROUPS
        self._menu_expanded_tile = None  # None or 0..3 when drilled in
        self._menu_sub_focus = 0         # 0..2 within expanded sub-menu
        self._menu_canvas = None         # tk.Canvas handle, set on render
        self._menu_live_after_id = None  # after() handle for 5s refresh
        self._active_tile_slots = self._TILE_SLOTS         # overridden by splash
        self._active_cd_center = (self._CD_CX, self._CD_CY)  # overridden by splash
        self._splash_viewport = (0, 0, self._SPLASH_DESIGN_W, self._SPLASH_DESIGN_H)
        self._menu_viewport = (0, 0, self._MENU_DESIGN_W, self._MENU_DESIGN_H)
        self._splash_render_scale = 1.0
        self._menu_render_scale = 1.0

        # --- Splash HL1 gate state ------------------------
        self._splash_cursor_on = True
        self._splash_pulse_after_id = None
        self._splash_canvas = None
        self._timing_starts: dict[str, float] = {}
        emit_timing_metric("boot.state_init", ms=(time.perf_counter() - _state_t0) * 1000.0)

        # Lazy-init MAIN_GROUPS (deferred to avoid ~640ms pandas+requests import
        # at module level; pays the cost here on first App() instantiation).
        _ensure_main_groups()

        chrome_t0 = time.perf_counter()
        if _boot_workers_enabled():
            threading.Thread(target=_fetch, daemon=True).start()
        self._chrome()
        emit_timing_metric("boot.chrome", ms=(time.perf_counter() - chrome_t0) * 1000.0)
        self._ui_schedule_drain()
        splash_t0 = time.perf_counter()
        self._splash()
        emit_timing_metric("boot.enter_splash", ms=(time.perf_counter() - splash_t0) * 1000.0)
        self._tick()
        self.protocol("WM_DELETE_WINDOW", self._quit)
        emit_timing_metric("boot.until_shell_ready", ms=(time.perf_counter() - boot_t0) * 1000.0)

        # SSH tunnel pro cockpit API.
        # Boot sync so prepara o manager; o start real vai pro loop do Tk
        # para nao deixar a janela branca enquanto o ssh handshaking roda.
        tunnel_t0 = time.perf_counter()
        self._aurum_tunnel = None
        if _boot_workers_enabled():
            try:
                tunnel = _boot_tunnel_manager()
                if tunnel is not None:
                    self._aurum_tunnel = tunnel
                    self.after(25, self._start_tunnel_async)
            except Exception:
                # Tunnel falhou -> launcher segue em local-mode.
                self._aurum_tunnel = None
        emit_timing_metric("boot.tunnel_start", ms=(time.perf_counter() - tunnel_t0) * 1000.0)

        # ShadowPoller: le cockpit API em thread separada e cacheia.
        # UI thread nunca faz HTTP sync (evita freeze da mainloop).
        self._aurum_shadow_poller = None
        poller_t0 = time.perf_counter()
        if _boot_workers_enabled():
            try:
                from launcher_support.shadow_poller import ShadowPoller
                from launcher_support.tunnel_registry import set_shadow_poller
                from launcher_support.engines_live_view import _get_cockpit_client
                poller = ShadowPoller(
                    client_factory=_get_cockpit_client,
                    engine="millennium",
                    poll_sec=5.0,
                )
                poller.start()
                set_shadow_poller(poller)
                self._aurum_shadow_poller = poller
            except Exception:
                pass
        emit_timing_metric("boot.shadow_poller_start", ms=(time.perf_counter() - poller_t0) * 1000.0)

        # Pre-warm cockpit runs + paper snapshot caches off the main thread
        # so first click on ENGINES renders from cache. Shadow is already
        # covered by ShadowPoller above.
        warm_t0 = time.perf_counter()
        tunnel_ref = self._aurum_tunnel
        app_ref = self
        if _boot_workers_enabled():
            try:
                def _warm_cockpit_caches() -> None:
                    import time as _t
                    # SSH tunnel starts async; wait for UP before firing the
                    # HTTP fetch (connection refused otherwise -> cache []).
                    if tunnel_ref is not None:
                        deadline = _t.monotonic() + 15.0
                        while _t.monotonic() < deadline:
                            # Bail if the app is shutting down so we don't
                            # block quit on a straggling HTTP fetch.
                            if not getattr(app_ref, "_ui_alive", True):
                                return
                            try:
                                st = tunnel_ref.status
                                if hasattr(st, "name") and st.name == "UP":
                                    break
                            except Exception:
                                pass
                            _t.sleep(0.2)
                        else:
                            return
                    if not getattr(app_ref, "_ui_alive", True):
                        return
                    try:
                        from launcher_support.engines_live_view import (
                            _load_cockpit_runs_sync,
                            _fetch_paper_extras_sync,
                            _fetch_remote_shadow_run_sync,
                            _COCKPIT_RUNS_CACHE,
                            _COCKPIT_RUNS_LOCK,
                            _PAPER_SNAPSHOT_CACHE,
                            _PAPER_SNAPSHOT_LOCK,
                            _REMOTE_SHADOW_RUN_CACHE,
                            _REMOTE_SHADOW_RUN_LOCK,
                        )
                        rows = _load_cockpit_runs_sync()
                        if not rows:
                            return
                        with _COCKPIT_RUNS_LOCK:
                            _COCKPIT_RUNS_CACHE["ts"] = _t.monotonic()
                            _COCKPIT_RUNS_CACHE["runs"] = list(rows)
                            _COCKPIT_RUNS_CACHE["loading"] = False
                        for row in rows:
                            engine_ok = str(row.get("engine") or "").lower() == "millennium"
                            status_ok = str(row.get("status") or "").lower() == "running"
                            mode = str(row.get("mode") or "").lower()
                            rid = str(row.get("run_id") or "")
                            if not (engine_ok and status_ok and rid):
                                continue
                            if mode == "paper":
                                try:
                                    payload = _fetch_paper_extras_sync(rid)
                                    with _PAPER_SNAPSHOT_LOCK:
                                        _PAPER_SNAPSHOT_CACHE[rid] = (_t.monotonic(), payload)
                                except Exception:
                                    pass
                            elif mode == "shadow":
                                # Warm the per-run shadow cache too — sem isso
                                # o primeiro click no picker RUNNING NOW ainda
                                # espera o worker assíncrono terminar o fetch
                                # inicial (heartbeat + trades via VPS).
                                try:
                                    payload = _fetch_remote_shadow_run_sync(rid)
                                    with _REMOTE_SHADOW_RUN_LOCK:
                                        _REMOTE_SHADOW_RUN_CACHE[rid] = (_t.monotonic(), payload)
                                except Exception:
                                    pass
                    except Exception:
                        pass
                threading.Thread(
                    target=_warm_cockpit_caches,
                    name="aurum-cockpit-cache-warmup",
                    daemon=True,
                ).start()
            except Exception:
                pass
        emit_timing_metric(
            "boot.cockpit_cache_warmup_start",
            ms=(time.perf_counter() - warm_t0) * 1000.0,
        )

    def _start_tunnel_async(self) -> None:
        """Start the cockpit tunnel off the critical paint path."""
        tunnel = getattr(self, "_aurum_tunnel", None)
        if tunnel is None:
            return

        def _worker():
            t0 = time.perf_counter()
            try:
                tunnel.start()
            except Exception:
                pass
            emit_timing_metric(
                "boot.tunnel_start_async",
                ms=(time.perf_counter() - t0) * 1000.0,
            )

        threading.Thread(
            target=_worker,
            name="aurum-tunnel-start",
            daemon=True,
        ).start()

    def _shutdown_runtime(self) -> None:
        """Stop background services idempotently for WM_DELETE and tests.

        Fase FAST (sync, ~10ms): flags + after_cancel. Tudo que e cheap.
        Fase SLOW (daemon thread): poller.stop + tunnel.stop. Antes rodava
        sync e bloqueava o close button por ate 3s (tunnel.terminate ->
        wait 1s -> kill -> wait 1s -> watchdog join 1s no pior caso com
        SSH.exe preso no Windows). Isso fazia o operador ter que apertar
        X duas vezes — primeiro clique congelava aguardando cleanup,
        segundo clique fechava a janela.

        Agora: FAST part + kick daemon thread e destroy() retorna em
        <50ms. Daemon thread termina quando process exit (SSH.exe
        orphan eh reapado no proximo startup via _reap_orphan_tunnel_on_port).
        """
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        self._ui_alive = False
        try:
            aid = getattr(self, "_ui_task_after_id", None)
            if aid:
                try:
                    self.after_cancel(aid)
                except Exception:
                    pass
                self._ui_task_after_id = None
        except Exception:
            pass

        # SLOW phase em daemon thread — nao bloqueia destroy()
        poller = getattr(self, "_aurum_shadow_poller", None)
        tunnel = getattr(self, "_aurum_tunnel", None)
        self._aurum_shadow_poller = None
        self._aurum_tunnel = None
        if poller is None and tunnel is None:
            return  # nada pra limpar

        try:
            from launcher_support.tunnel_registry import (
                set_shadow_poller, set_tunnel_manager,
            )
        except Exception:
            set_shadow_poller = None
            set_tunnel_manager = None

        def _bg_cleanup() -> None:
            if poller is not None:
                try:
                    poller.stop(timeout_sec=0.5)
                except Exception:
                    pass
                if set_shadow_poller is not None:
                    try:
                        set_shadow_poller(None)
                    except Exception:
                        pass
            if tunnel is not None:
                try:
                    tunnel.stop(timeout_sec=1.0)
                except Exception:
                    pass
                if set_tunnel_manager is not None:
                    try:
                        set_tunnel_manager(None)
                    except Exception:
                        pass

        import threading
        threading.Thread(
            target=_bg_cleanup, daemon=True,
            name="aurum-shutdown-cleanup",
        ).start()

    def destroy(self):
        self._shutdown_runtime()
        return super().destroy()

    def _configure_windows_dpi(self) -> None:
        """Prefer per-monitor DPI awareness on Windows laptops with scaling."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

    # --- CHROME ------------------------------------------
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
        tk.Label(hc, text="AURUM", font=(FONT, 8, "bold"), fg=WHITE, bg=BG).pack(side="left")
        # Neutral header nav buttons — all share the terminal chrome palette
        # (BG2 fill, WHITE text, subtle BG3/AMBER_B hover). No per-button hue.
        def _mk_nav_btn(text: str, cmd) -> tk.Label:
            btn = tk.Label(
                hc, text=text, font=(FONT, 8, "bold"),
                fg=WHITE, bg=BG2, cursor="hand2", padx=6, pady=0,
            )
            btn.pack(side="left", padx=(4, 0))
            btn.bind("<Button-1>", lambda e: cmd())
            btn.bind("<Enter>",
                     lambda e: btn.configure(bg=BG3, fg=AMBER_B))
            btn.bind("<Leave>",
                     lambda e: btn.configure(bg=BG2, fg=WHITE))
            return btn

        self.h_macro_btn    = _mk_nav_btn(" ▸ MACRO ",     self._macro_brain_menu)
        self.h_main_btn     = _mk_nav_btn(" = MAIN ",      lambda: self._menu("main"))
        self.h_backtest_btn = _mk_nav_btn(" ◆ BACKTEST ",  self._strategies_backtest)
        self.h_engines_btn  = _mk_nav_btn(" ▣ ENGINES ",   self._strategies_live)
        self.h_data_btn     = _mk_nav_btn(" ▤ DATA ",      self._data_center)
        self.h_arb_btn      = _mk_nav_btn(" ⇄ ARBITRAGE ", self._arbitrage_hub)
        # Extra left padding for the first button so it clears the AURUM brand.
        self.h_macro_btn.pack_configure(padx=(8, 0))

        self.h_path = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG); self.h_path.pack(side="left", padx=(8,0))
        self.h_stat = tk.Label(hc, text="", font=(FONT, 8), fg=DIM, bg=BG); self.h_stat.pack(side="right")
        # Persistent badge that lights up while the COMMAND CENTER dev server is alive.
        self.h_site = tk.Label(hc, text="", font=(FONT, 8, "bold"), fg=GREEN, bg=BG)
        self.h_site.pack(side="right", padx=(0, 12))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        self.main = tk.Frame(self, bg=BG); self.main.pack(fill="both", expand=True)
        # screens_container is a SIBLING of self.main (direct child of root),
        # NOT a child of self.main — because _clr() destroys all children of
        # self.main in legacy path. Sibling survives across switches.
        self.screens_container = tk.Frame(self, bg=BG)
        # Packed lazily on first screens.show(); pack_forget-ed when legacy path active.
        from launcher_support.screens.manager import ScreenManager
        from launcher_support.screens.registry import register_default_screens
        self.screens = ScreenManager(parent=self.screens_container)
        register_default_screens(
            self.screens,
            app=self,
            conn=_get_conn(),
            root_path=ROOT,
            tagline=SYSTEM_TAGLINE,
        )
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Footer
        ft = tk.Frame(self, bg=BG2, height=20); ft.pack(fill="x"); ft.pack_propagate(False)
        fc = tk.Frame(ft, bg=BG2); fc.pack(fill="both", expand=True, padx=10)
        self.f_lbl = tk.Label(fc, text="", font=(FONT, 7), fg=DIM, bg=BG2); self.f_lbl.pack(side="right")
        tk.Label(fc, text="v2.0", font=(FONT, 7), fg=DIM2, bg=BG2).pack(side="left")

    def _clr(self):
        aid = getattr(self, "_exec_progress_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._exec_progress_after_id = None
        self._exec_visual_mode = None
        self._exec_visual = None
        self._exec_console = None
        self._exec_stage_label = None
        self._exec_file_label = None
        self._exec_pct_label = None
        self._exec_bar_canvas = None
        self._exec_recent_labels = []
        self._exec_live_tail_label = None
        self._exec_progress_last_paint = 0.0
        self._exec_last_feed_at = 0.0
        self._exec_managed_info = None
        # Crypto dashboard owns a recurring after() timer — kill it on any screen change
        aid = getattr(self, "_dash_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._dash_after_id = None
        self._dash_alive = False

        # Macro Brain + Arbitrage cockpits each own their own timers —
        # kill them before any screen change so refresh ticks from an
        # abandoned page can't teleport the user back to it.
        for attr in ("_macro_render_after", "_macro_cycle_after",
                     "_arb_refresh_after"):
            aid = getattr(self, attr, None)
            if aid:
                try: self.after_cancel(aid)
                except Exception: pass
            setattr(self, attr, None)
        # Invalidate the page-token sentinels so any in-flight tick
        # that got past the cancel no-ops instead of re-rendering.
        self._macro_page_token = None
        # Site console poll loop self-terminates when this flag flips false.
        # The SiteRunner subprocess itself keeps running independently.
        self._site_screen_alive = False
        # Funding scanner screen uses a self-rearming after() tick. Flip the
        # alive flag off and clear the armed flag so re-entry starts a fresh
        # chain instead of stacking.
        self._funding_alive = False
        self._funding_timer_armed = False
        # ENGINES LIVE cockpit owns ShadowPoller + WSPriceFeed + detail
        # tickers. Without this teardown, navigating away (BACKTEST, MAIN,
        # DATA, ...) leaves those pollers alive in background threads,
        # contending for aurum.db and the GIL. The 2026-04-20 freeze
        # reproduced when the user clicked BACKTEST after ENGINES LIVE —
        # picker render never got enough main-thread time to complete.
        prior_live = getattr(self, "_engines_live_handle", None)
        if prior_live and callable(prior_live.get("cleanup")):
            try:
                prior_live["cleanup"]()
            except Exception:
                pass
            self._engines_live_handle = None
        for w in self.main.winfo_children(): w.destroy()
        # Default to LEGACY mode: self.main visible, screens_container hidden.
        # Migrated-screen wrappers (e.g. _splash) flip this AFTER _clr.
        sc = getattr(self, "screens_container", None)
        if sc is not None and sc.winfo_manager():
            sc.pack_forget()
        if not self.main.winfo_manager():
            self.main.pack(fill="both", expand=True)
        # If a migrated screen is currently active, give it an on_exit tick
        # so timers/bindings get cancelled when legacy navigation happens
        # without going through ScreenManager.show().
        mgr = getattr(self, "screens", None)
        if mgr is not None and mgr.current_name() is not None:
            current = mgr._cache.get(mgr.current_name())
            if current is not None:
                try:
                    current.on_exit()
                except Exception:
                    pass
                current.pack_forget()
                mgr._current_name = None

    def _clear_kb(self):
        """Clear our custom global keybindings before a screen switch.
        Renamed from `_unbind` because that name collides with tkinter's
        internal Misc._unbind method — overriding it breaks unbind_all()
        and other builtin binding APIs."""
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

    def _ui_call_soon(self, callback):
        """Queue a UI callback from any thread; drained on Tk main thread."""
        if not getattr(self, "_ui_alive", False):
            return
        try:
            self._ui_task_queue.put_nowait(callback)
        except Exception:
            return

    def _ui_schedule_drain(self):
        if not getattr(self, "_ui_alive", False):
            return
        try:
            self._ui_task_after_id = self.after(50, self._ui_drain_tasks)
        except (RuntimeError, tk.TclError):
            self._ui_task_after_id = None

    def _ui_drain_tasks(self):
        self._ui_task_after_id = None
        if not getattr(self, "_ui_alive", False):
            return
        drained = 0
        max_drain = 200
        while drained < max_drain:
            try:
                callback = self._ui_task_queue.get_nowait()
            except queue.Empty:
                break
            drained += 1
            try:
                callback()
            except Exception:
                pass
        self._ui_schedule_drain()

    def _tick(self):
        self.t_clk.configure(text=datetime.now().strftime("%H:%M:%S"))
        self.t_lbl.configure(text=_ticker_str(), fg=AMBER_D)
        # COMMAND CENTER site indicator (visible from any screen while server is alive)
        sr = getattr(self, "_site_runner_inst", None)
        if sr and sr.is_running():
            try:
                port = int(sr.config.get("port", 3000) or 3000)
            except (TypeError, ValueError):
                port = 3000
            self.h_site.configure(text=f"● SITE :{port}", fg=GREEN)
        else:
            self.h_site.configure(text="")
        self.after(3000, self._tick)

    # --- Bloomberg 3D menu — live data fetchers ----------
    # Each fetcher returns {"line1","line2","line3","line4"} of strings.
    # Any failure → "—". Never raises. Called from a worker thread.

    @staticmethod
    def _fallback_lines() -> dict:
        return {"line1": "—", "line2": "—", "line3": "—", "line4": "—"}

    def _fetch_tile_markets(self) -> dict:
        try:
            from config.params import UNIVERSE
            lines = {"line1": "—", "line2": "—", "line3": "—", "line4": "—"}
            try:
                from core.data import fetch_spot_price
                btc = fetch_spot_price("BTCUSDT")
                lines["line1"] = f"BTC {btc/1000:.1f}k" if btc else "BTC —"
            except Exception:
                lines["line1"] = "BTC —"
            try:
                from core.data import fetch_spot_price
                eth = fetch_spot_price("ETHUSDT")
                lines["line2"] = f"ETH {eth/1000:.2f}k" if eth else "ETH —"
            except Exception:
                lines["line2"] = "ETH —"
            lines["line3"] = f"{len(UNIVERSE)} pairs"
            try:
                from core.risk.portfolio import detect_macro
                lines["line4"] = f"MACRO {detect_macro()}"
            except Exception:
                lines["line4"] = "MACRO —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_execute(self) -> dict:
        try:
            lines = self._fallback_lines()
            try:
                from core import proc
                n = len(proc.list_active()) if hasattr(proc, "list_active") else 0
                lines["line1"] = f"procs {n}"
            except Exception:
                lines["line1"] = "procs 0"
            try:
                ps = json.loads((ROOT / "config" / "paper_state.json").read_text(encoding="utf-8"))
                pnl = float(ps.get("day_pnl", 0.0))
                sign = "+" if pnl >= 0 else ""
                lines["line2"] = f"pnl {sign}{pnl:.1f}%"
                pos = ps.get("open_positions", [])
                lines["line3"] = f"{len(pos)} pos" if isinstance(pos, list) else "0 pos"
            except Exception:
                lines["line2"] = "pnl —"
                lines["line3"] = "0 pos"
            try:
                rg = json.loads((ROOT / "config" / "risk_gates.json").read_text(encoding="utf-8"))
                active = sum(1 for v in rg.values() if isinstance(v, dict) and v.get("active"))
                lines["line4"] = f"risk {active}/5"
            except Exception:
                lines["line4"] = "risk —/5"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_research(self) -> dict:
        try:
            lines = self._fallback_lines()
            idx_path = ROOT / "data" / "index.json"
            if idx_path.exists():
                try:
                    runs = json.loads(idx_path.read_text(encoding="utf-8"))
                    if isinstance(runs, list) and runs:
                        last = runs[-1] if isinstance(runs[-1], dict) else {}
                        eng = str(last.get("engine", "—"))[:4].upper()
                        sharpe = last.get("sharpe") or last.get("metrics", {}).get("sharpe")
                        lines["line1"] = f"last {eng}"
                        lines["line2"] = f"sharpe {float(sharpe):.1f}" if sharpe else "sharpe —"
                        lines["line3"] = f"{len(runs)} runs"
                    else:
                        lines["line1"] = "no runs"
                        lines["line3"] = "0 runs"
                except Exception:
                    lines["line1"] = "last —"
                    lines["line3"] = "— runs"
            else:
                lines["line1"] = "no runs"
                lines["line3"] = "0 runs"
            try:
                from core import chronos
                active = bool(getattr(chronos, "hmm_enabled", lambda: False)())
                lines["line4"] = "HMM active" if active else "HMM idle"
            except Exception:
                lines["line4"] = "HMM —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _fetch_tile_control(self) -> dict:
        try:
            lines = self._fallback_lines()
            try:
                conn = json.loads((ROOT / "config" / "connections.json").read_text(encoding="utf-8"))
                if isinstance(conn, dict):
                    items = conn.get("connections") or list(conn.values())
                elif isinstance(conn, list):
                    items = conn
                else:
                    items = []
                total = len(items)
                up = sum(1 for c in items
                         if isinstance(c, dict) and c.get("status", "").lower() in {"up", "ok", "connected"})
                lines["line1"] = f"conn {up}/{total}" if total else "conn —"
            except Exception:
                lines["line1"] = "conn —"
            try:
                elapsed = time.monotonic() - self._start_t
                h = int(elapsed // 3600)
                m = int((elapsed % 3600) // 60)
                lines["line2"] = f"up {h}h{m:02d}m"
            except Exception:
                lines["line2"] = "up —"
            try:
                from bot import telegram as tg_mod
                ok = bool(getattr(tg_mod, "is_online", lambda: False)())
                lines["line3"] = "tg ONLINE" if ok else "tg OFFLINE"
            except Exception:
                lines["line3"] = "tg —"
            lines["line4"] = "vps —"
            return lines
        except Exception:
            return self._fallback_lines()

    def _menu_live_fetch_sync(self) -> None:
        """Populate self._menu_live in-thread. Used by tests and by the async worker."""
        self._menu_live["markets"]  = self._fetch_tile_markets()
        self._menu_live["execute"]  = self._fetch_tile_execute()
        self._menu_live["research"] = self._fetch_tile_research()
        self._menu_live["control"]  = self._fetch_tile_control()

    def _menu_live_fetch_async(self) -> None:
        """Spawn a worker thread that refreshes the cache, then schedules a repaint."""
        def _worker():
            try:
                self._menu_live_fetch_sync()
            except Exception:
                pass
            try:
                self.after(0, self._menu_live_apply)
            except Exception:
                pass
        threading.Thread(target=_worker, daemon=True).start()

    def _menu_live_apply(self) -> None:
        """Main-thread: redraw tile texts from self._menu_live if the main menu is shown.

        Skip when a tile is expanded — the 4 isometric tiles are not on
        screen, repainting them would draw over the desk panel and look
        like a glitch.
        """
        if self._menu_canvas is None:
            return
        if getattr(self, "_menu_expanded_tile", None) is not None:
            return
        try:
            self._menu_tiles_repaint_text()
        except Exception:
            pass

    # --- Bloomberg 3D menu — canvas renderers ------------
    # All drawing happens on one full-frame canvas. Tiles are isometric
    # boxes built from lines/polygons; the CD at the center uses ovals/arcs.

    _TILE_SLOTS = [
        ("nw", 192, 150),
        ("ne", 728, 150),
        ("sw", 192, 380),
        ("se", 728, 380),
    ]
    # Splash screen uses the same 2x2 grid but shifted DOWN ~100px so the
    # BANNER wordmark has room at the top of the canvas.
    _SPLASH_TILE_SLOTS = [
        ("nw", 192, 250),
        ("ne", 728, 250),
        ("sw", 192, 480),
        ("se", 728, 480),
    ]
    _TILE_W = 340
    _TILE_H = 200
    _TILE_DEPTH = 16

    _CD_CX = 460
    _CD_CY = 265
    _CD_R  = 52
    # CD center on the splash canvas — sits between the shifted 2x2 grid.
    _SPLASH_CD = (460, 365)

    def _dim_color(self, hex_color: str, factor: float) -> str:
        """Scale an #rrggbb color by factor (0..1)."""
        try:
            h = hex_color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            r = max(0, min(255, int(r * factor)))
            g = max(0, min(255, int(g * factor)))
            b = max(0, min(255, int(b * factor)))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return hex_color

    @staticmethod
    def _calc_centered_viewport(
        canvas_w: int,
        canvas_h: int,
        design_w: int,
        design_h: int,
    ) -> tuple[int, int, int, int]:
        """Return a centered design-space viewport within the live canvas."""
        live_w = max(int(canvas_w or 0), design_w)
        live_h = max(int(canvas_h or 0), design_h)
        x0 = max((live_w - design_w) // 2, 0)
        y0 = max((live_h - design_h) // 2, 0)
        return x0, y0, x0 + design_w, y0 + design_h

    def _center_canvas_items(self, canvas, design_w: int, design_h: int) -> tuple[int, int, int, int]:
        """Center an already-rendered fixed-layout canvas within the live viewport."""
        viewport = self._calc_centered_viewport(
            canvas.winfo_width(),
            canvas.winfo_height(),
            design_w,
            design_h,
        )
        items = canvas.find_all()
        if not items:
            return viewport
        bbox = canvas.bbox(*items)
        if not bbox:
            return viewport
        cur_cx = (bbox[0] + bbox[2]) / 2
        cur_cy = (bbox[1] + bbox[3]) / 2
        target_cx = viewport[0] + (design_w / 2)
        target_cy = viewport[1] + (design_h / 2)
        canvas.move("all", target_cx - cur_cx, target_cy - cur_cy)
        return viewport

    @staticmethod
    def _scale_canvas_text_fonts(canvas, ratio: float) -> None:
        if abs(ratio - 1.0) < 0.001:
            return
        for item in canvas.find_all():
            if canvas.type(item) != "text":
                continue
            font_name = canvas.itemcget(item, "font")
            if not font_name:
                continue
            try:
                actual = tkfont.Font(font=font_name).actual()
                size = int(actual.get("size", 8) or 8)
                family = actual.get("family", FONT)
                weight = actual.get("weight", "normal")
                slant = actual.get("slant", "roman")
                underline = int(actual.get("underline", 0) or 0)
                overstrike = int(actual.get("overstrike", 0) or 0)
                new_size = max(6, int(round(abs(size) * ratio)))
                if size < 0:
                    new_size = -new_size
                canvas.itemconfigure(
                    item,
                    font=(family, new_size, weight, slant, underline, overstrike),
                )
            except Exception:
                continue

    def _apply_canvas_scale(self, canvas, design_w: int, design_h: int, previous_scale: float) -> tuple[tuple[int, int, int, int], float]:
        live_w = max(canvas.winfo_width(), 1)
        live_h = max(canvas.winfo_height(), 1)
        scale = max(min(live_w / design_w, live_h / design_h), 1.0)
        ratio = scale / max(previous_scale, 0.001)
        if canvas.find_all():
            if abs(scale - previous_scale) >= 0.01:
                canvas.scale("all", 0, 0, ratio, ratio)
                self._scale_canvas_text_fonts(canvas, ratio)
            scaled_w = int(round(design_w * scale))
            scaled_h = int(round(design_h * scale))
            x0 = max((live_w - scaled_w) // 2, 0)
            y0 = max((live_h - scaled_h) // 2, 0)
            bbox = canvas.bbox("all")
            if bbox:
                canvas.move("all", x0 - bbox[0], y0 - bbox[1])
            return (x0, y0, x0 + scaled_w, y0 + scaled_h), scale
        viewport = self._calc_centered_viewport(live_w, live_h, design_w, design_h)
        return viewport, scale

    def _schedule_first_paint_metric(self, name: str) -> None:
        self._timing_starts[name] = time.perf_counter()

        def _emit() -> None:
            started = self._timing_starts.pop(name, None)
            if started is None:
                return
            emit_timing_metric(
                f"paint.{name}",
                ms=(time.perf_counter() - started) * 1000.0,
            )

        try:
            self.after_idle(_emit)
        except Exception:
            self._timing_starts.pop(name, None)

    def _tile_rect(self, idx: int) -> tuple:
        slots = getattr(self, "_active_tile_slots", None) or self._TILE_SLOTS
        _, cx, cy = slots[idx]
        scale = max(getattr(self, "_menu_render_scale", 1.0), 1.0)
        w = int(round(self._TILE_W * scale))
        h = int(round(self._TILE_H * scale))
        return (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)

    def _draw_cd_center(self, canvas, r=None) -> None:
        center = getattr(self, "_active_cd_center", None) or (self._CD_CX, self._CD_CY)
        cx, cy = center
        if r is None:
            r = self._CD_R
        canvas.delete("cd")
        canvas.create_rectangle(cx - r - 18, cy - r - 12, cx + r + 18, cy + r + 12,
                                outline=BORDER, fill=PANEL, width=1, tags="cd")
        canvas.create_rectangle(cx - r - 18, cy - r - 12, cx + r + 18, cy - r + 6,
                                outline="", fill=BG2, tags="cd")
        canvas.create_text(cx - r - 8, cy - r - 3, anchor="w",
                           text="AURUM ROUTER", font=(FONT, 8, "bold"),
                           fill=AMBER, tags="cd")
        canvas.create_text(cx + r + 10, cy - r - 3, anchor="e",
                           text="MAIN HUB", font=(FONT, 7),
                           fill=DIM, tags="cd")
        canvas.create_rectangle(cx - r + 8, cy - r + 18, cx + r - 8, cy + r - 8,
                                outline=AMBER_D, fill=BG, width=1, tags="cd")
        canvas.create_rectangle(cx - 24, cy - 24, cx + 24, cy + 24,
                                outline=AMBER, fill=BG2, width=1, tags="cd")
        self._draw_aurum_logo(canvas, cx, cy - 6, scale=15, tag="cd")
        canvas.create_text(cx, cy + 20, text="A U R U M", font=(FONT, 8, "bold"),
                           fill=WHITE, tags="cd")
        canvas.create_text(cx, cy + r - 14, text="DESK ROUTER", font=(FONT, 7),
                           fill=DIM, tags="cd")
        canvas.create_line(cx - r + 16, cy - r + 30, cx + r - 16, cy - r + 30,
                           fill=BORDER, width=1, tags="cd")
        canvas.create_line(cx, cy + r - 8, cx, cy + r + 8,
                           fill=AMBER_D, width=1, tags="cd")

    def _draw_aurum_logo(self, canvas, cx: int, cy: int, scale: int = 18, tag: str = "logo") -> None:
        s = scale
        canvas.create_polygon(
            cx, cy - s,
            cx + s, cy + s,
            cx + s * 0.46, cy + s,
            cx + s * 0.24, cy + s * 0.30,
            cx - s * 0.24, cy + s * 0.30,
            cx - s * 0.46, cy + s,
            cx - s, cy + s,
            fill=AMBER, outline="", tags=tag,
        )
        canvas.create_polygon(
            cx, cy - s,
            cx + s, cy + s,
            cx + s * 0.58, cy + s,
            cx, cy - s * 0.10,
            fill=WHITE, outline="", tags=tag,
        )

    def _draw_warning_stripe(self, canvas, y: int, height: int, text: str) -> None:
        """Solid yellow bar with dark text — HL1 hazard stripe."""
        w = 920
        canvas.create_rectangle(0, y, w, y + height, fill="#ffd700",
                                outline="#ffd700", tags="warning")
        canvas.create_text(w // 2, y + height // 2,
                           text=text, font=(FONT, 7, "bold"),
                           fill="#1a1a00", tags="warning")

    def _draw_stamp(self, canvas, cx: int, cy: int, w: int, h: int, lines: list) -> None:
        """Dashed rectangular stamp with N centered text lines — HL1 clearance tags."""
        x1, y1 = cx - w // 2, cy - h // 2
        x2, y2 = cx + w // 2, cy + h // 2
        canvas.create_rectangle(x1, y1, x2, y2,
                                outline=AMBER, width=1,
                                dash=(2, 3), tags="stamp")
        n = len(lines)
        if n == 0:
            return
        line_h = h // (n + 1)
        for i, line in enumerate(lines):
            canvas.create_text(cx, y1 + line_h * (i + 1),
                               text=line, font=(FONT, 8, "bold"),
                               fill=AMBER, tags="stamp")

    def _draw_status_block(self, canvas, x: int, y: int, rows: list) -> None:
        """CRT-style status rows: '> LABEL .......... VALUE' with per-row color.

        rows is a list of (label, value, color_hex) tuples. Dots fill the
        gap between label and value to a fixed column width so the values
        align vertically.
        """
        total_width = 48
        line_step = 18
        for i, (label, value, color) in enumerate(rows):
            prefix = f"> {label} "
            value_str = f" {value}"
            dots = "." * max(2, total_width - len(prefix) - len(value_str))
            text = f"{prefix}{dots}{value_str}"
            canvas.create_text(x, y + i * line_step, anchor="w",
                               text=text, font=(FONT, 9),
                               fill=color, tags="status")

    def _draw_panel(self, canvas, x1: int, y1: int, x2: int, y2: int,
                    title: str = "", accent: str = AMBER, tag: str = "panel") -> None:
        """Panel com enquadramento visível: perímetro completo em accent dim,
        top rail accent vivo, corner brackets, title chip."""
        perim = self._dim_color(accent, 0.45)
        canvas.create_rectangle(x1, y1, x2, y2, outline=perim, fill=PANEL,
                                width=1, tags=tag)
        # Top accent rail
        canvas.create_line(x1, y1, x2, y1, fill=accent, width=2, tags=tag)
        # Corner brackets — dá vida sem poluir
        L = 10
        for (bx, by, dx, dy) in (
            (x1, y1 + 2, +1, +1),
            (x2, y1 + 2, -1, +1),
            (x1, y2,     +1, -1),
            (x2, y2,     -1, -1),
        ):
            canvas.create_line(bx, by, bx + dx * L, by,
                               fill=accent, width=2, tags=tag)
            canvas.create_line(bx, by, bx, by + dy * L,
                               fill=accent, width=2, tags=tag)
        # Bottom line (subtle)
        canvas.create_line(x1 + L, y2, x2 - L, y2, fill=perim, width=1, tags=tag)
        if title:
            tw = max(90, len(title) * 7 + 20)
            canvas.create_rectangle(x1 + 14, y1 - 10, x1 + 14 + tw, y1 + 12,
                                    outline=accent, fill=BG, width=1, tags=tag)
            canvas.create_text(x1 + 22, y1 + 1, anchor="w",
                               text=title, font=(FONT, 8, "bold"),
                               fill=accent, tags=tag)

    def _draw_kv_rows(self, canvas, x: int, y: int, rows: list[tuple[str, str, str]],
                      value_x: int = 290, line_h: int = 18, tag: str = "kv") -> None:
        for i, (label, value, color) in enumerate(rows):
            yy = y + i * line_h
            canvas.create_text(x, yy, anchor="w", text=label, font=(FONT, 8),
                               fill=DIM, tags=tag)
            canvas.create_text(value_x, yy, anchor="w", text=value, font=(FONT, 8, "bold"),
                               fill=color, tags=tag)

    def _bind_canvas_window_width(self, canvas, window_id, pad_x: int = 0, min_width: int = 0) -> None:
        def _fit(_event=None):
            live_w = max(canvas.winfo_width(), 1)
            inner_w = max(live_w - pad_x, min_width)
            canvas.coords(window_id, 0, 0)
            canvas.itemconfigure(window_id, width=inner_w)
        canvas.bind("<Configure>", _fit)
        _fit()

    def _ui_page_shell(self, title: str, subtitle: str = "",
                       pad_x: int = 28, pad_y: int = 18,
                       content_width: int | None = None) -> tuple[tk.Frame, tk.Frame]:
        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True, padx=pad_x, pady=pad_y)

        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=28).pack(side="left", padx=(0, 8))
        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(title_wrap, text=title, font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        if subtitle:
            tk.Label(title_wrap, text=subtitle, font=(FONT, 8),
                     fg=DIM, bg=BG, anchor="w").pack(anchor="w", pady=(3, 0))
        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 12))

        body = tk.Frame(outer, bg=BG)
        if content_width is not None:
            body.pack(fill="both", expand=True)
            canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
            sb = tk.Scrollbar(body, orient="vertical", command=canvas.yview)
            inner = tk.Frame(canvas, bg=BG, width=content_width)
            inner.bind("<Configure>", lambda e: canvas.configure(
                scrollregion=canvas.bbox("all")))
            window_id = canvas.create_window((0, 0), window=inner, anchor="nw",
                                             width=content_width)
            def _fit_inner(_event=None):
                live_w = max(canvas.winfo_width(), 1)
                gutter = 28
                inner_w = max(content_width, live_w - gutter)
                offset_x = max((live_w - inner_w) // 2, 0)
                canvas.coords(window_id, offset_x, 0)
                canvas.itemconfigure(window_id, width=inner_w)
            canvas.bind("<Configure>", _fit_inner)
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            _fit_inner()
            def _on_wheel(event):
                canvas.yview_scroll(-1 * (event.delta // 120), "units")
            def _enter_canvas(event):
                canvas.bind_all("<MouseWheel>", _on_wheel)
            def _leave_canvas(event):
                try: canvas.unbind_all("<MouseWheel>")
                except Exception: pass
            canvas.bind("<Enter>", _enter_canvas)
            canvas.bind("<Leave>", _leave_canvas)
            canvas.bind("<Destroy>", _leave_canvas)
            return outer, inner

        body.pack(fill="both", expand=True)
        return outer, body

    def _ui_panel_frame(self, parent, title: str = "", subtitle: str = "") -> tk.Frame:
        shell = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        shell.pack(fill="x", pady=(0, 12))
        panel = tk.Frame(shell, bg=BG)
        panel.pack(fill="x", pady=(0, 12))

        if title or subtitle:
            hdr = tk.Frame(panel, bg=BG)
            hdr.pack(fill="x", pady=(8, 8), padx=10)
            tk.Frame(hdr, bg=AMBER_D, width=3, height=28).pack(side="left", padx=(0, 8))
            text_wrap = tk.Frame(hdr, bg=BG)
            text_wrap.pack(side="left", fill="x", expand=True)
            if title:
                tk.Label(text_wrap, text=title, font=(FONT, 8, "bold"),
                         fg=AMBER_D, bg=BG, anchor="w").pack(anchor="w")
            if subtitle:
                tk.Label(text_wrap, text=subtitle, font=(FONT, 8),
                         fg=DIM, bg=BG, anchor="w").pack(anchor="w", pady=(2, 0))
            tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 8))

        return panel

    def _ui_section(self, parent, title: str, note: str | None = None,
                    badge: str | None = None) -> tk.Frame:
        wrap = tk.Frame(parent, bg=BG2, highlightbackground=BORDER, highlightthickness=1)
        wrap.pack(fill="x", pady=(0, 10))

        head = tk.Frame(wrap, bg=BG2)
        head.pack(fill="x", pady=(0, 4), padx=8)
        tk.Frame(head, bg=AMBER_D, width=3, height=22).pack(side="left", padx=(0, 8))
        tk.Label(head, text=title, font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG2, anchor="w").pack(side="left")
        if badge:
            tk.Label(head, text=f" {badge} ", font=(FONT, 7, "bold"),
                     fg=BG, bg=AMBER_D, padx=3).pack(side="left", padx=8)
        if note:
            tk.Label(head, text=note, font=(FONT, 7),
                     fg=DIM, bg=BG2, anchor="e").pack(side="right")
        tk.Frame(wrap, bg=DIM2, height=1).pack(fill="x", padx=8, pady=(0, 6))
        return wrap

    def _ui_action_row(self, parent, key_label: str, title: str, desc: str,
                       command=None, available: bool = True,
                       tag: str | None = None, tag_fg: str | None = None,
                       tag_bg: str | None = None, title_width: int = 20,
                       key_bg: str | None = None) -> tuple[tk.Frame, tk.Label, tk.Label]:
        row = tk.Frame(parent, bg=BG, cursor="hand2" if command else "arrow")
        row.pack(fill="x", pady=1)
        rail = tk.Frame(row, bg=key_bg or (AMBER_D if available else DIM2), width=3)
        rail.pack(side="left", fill="y")

        key = tk.Label(row, text=f" {key_label} ", font=(FONT, 8, "bold"),
                       fg=BG if available else WHITE,
                       bg=key_bg or (AMBER if available else DIM2),
                       width=3)
        key.pack(side="left", padx=(4, 0))

        title_l = tk.Label(row, text=f"  {title}", font=(FONT, 9, "bold"),
                           fg=WHITE if available else DIM, bg=BG3,
                           anchor="w", padx=6, pady=4, width=title_width)
        title_l.pack(side="left")

        desc_l = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3,
                          anchor="w", padx=6, pady=4)
        desc_l.pack(side="left", fill="x", expand=True)

        if tag:
            tk.Label(row, text=f" {tag} ", font=(FONT, 7, "bold" if available else "normal"),
                     fg=tag_fg or (BG if available else DIM),
                     bg=tag_bg or (GREEN if available else BG2),
                     padx=4).pack(side="right", padx=4)

        if command:
            def _enter(_e=None):
                title_l.configure(fg=AMBER if available else DIM)
                desc_l.configure(fg=WHITE if available else DIM)
                rail.configure(bg=AMBER if available else DIM2)
            def _leave(_e=None):
                title_l.configure(fg=WHITE if available else DIM)
                desc_l.configure(fg=DIM)
                rail.configure(bg=key_bg or (AMBER_D if available else DIM2))
                row.configure(bg=BG)
            for w in (row, rail, key, title_l, desc_l):
                w.bind("<Button-1>", lambda e, c=command: c())
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

        return row, title_l, desc_l

    def _ui_kv_grid(self, parent, rows: list[tuple[str, str, str]]) -> None:
        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill="x", pady=(0, 8))
        for label, value, color in rows:
            row = tk.Frame(grid, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, font=(FONT, 8), fg=DIM, bg=BG,
                     width=16, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=(FONT, 8, "bold"), fg=color, bg=BG,
                     anchor="w").pack(side="left")

    def _ui_note(self, parent, text: str, fg: str = DIM) -> None:
        tk.Label(parent, text=text, font=(FONT, 8),
                 fg=fg, bg=BG, anchor="w", justify="left").pack(fill="x", pady=(0, 6))

    def _ui_back_row(self, parent, command, label: str = "RETURN") -> None:
        wrap = tk.Frame(parent, bg=BG)
        wrap.pack(fill="x", pady=(2, 0))
        self._ui_action_row(
            wrap,
            "0",
            label,
            "Return to previous routing screen",
            command=command,
            available=True,
            tag="BACK",
            tag_fg=BG,
            tag_bg=AMBER_D,
            title_width=20,
            key_bg=DIM2,
        )

    def _draw_spokes(self, canvas, focused_idx: int) -> None:
        canvas.delete("spokes")
        slots = getattr(self, "_active_tile_slots", None) or self._TILE_SLOTS
        center = getattr(self, "_active_cd_center", None) or (self._CD_CX, self._CD_CY)
        cd_cx, cd_cy = center
        for idx in range(4):
            x1, y1, x2, y2 = self._tile_rect(idx)
            _, cx, cy = slots[idx]
            anchor_x = x2 if cx < cd_cx else x1
            anchor_y = cy
            _, _, color, _ = MAIN_GROUPS[idx]
            line_color = color if idx == focused_idx else DIM2
            width = 2 if idx == focused_idx else 1
            mid_x = cd_cx - 68 if cx < cd_cx else cd_cx + 68
            canvas.create_line(
                anchor_x, anchor_y, mid_x, anchor_y,
                fill=line_color, width=width, tags="spokes",
            )
            canvas.create_line(
                mid_x, anchor_y, mid_x, cd_cy,
                fill=line_color, width=width, tags="spokes",
            )
            canvas.create_line(
                mid_x, cd_cy, cd_cx, cd_cy,
                fill=line_color, width=width, tags="spokes",
            )
            canvas.create_rectangle(mid_x - 2, anchor_y - 2, mid_x + 2, anchor_y + 2,
                                    outline=line_color, fill=BG, width=1, tags="spokes")

    def _menu_tiles_repaint_text(self) -> None:
        if self._menu_canvas is None:
            return
        try:
            screen = getattr(self, "screens", None)._cache.get("main_menu")
        except Exception:
            screen = None
        if screen is not None and hasattr(screen, "redraw_tiles"):
            try:
                screen.redraw_tiles()
                return
            except Exception:
                pass

    def _menu_tile_focus(self, idx: int) -> None:
        if not (0 <= idx <= 3):
            return
        self._menu_focused_tile = idx
        if self._menu_canvas is None:
            return
        if getattr(self, "_menu_expanded_tile", None) is None:
            self._menu_tiles_repaint_text()
            return
        self._draw_spokes(self._menu_canvas, idx)

    def _menu_tile_focus_delta(self, delta: int) -> None:
        self._menu_tile_focus((self._menu_focused_tile + delta) % 4)

    def _menu_sub_focus_delta(self, delta: int) -> None:
        if self._menu_expanded_tile is None:
            return
        children = MAIN_GROUPS[self._menu_expanded_tile][3]
        self._menu_sub_focus = (self._menu_sub_focus + delta) % len(children)
        # Full rebuild keeps chrome + submenu in the same scale space;
        # incremental _menu_sub_render drew at design coords on an already
        # scaled canvas and left the new rows off-center.
        self._menu_tile_expand_impl(self._menu_expanded_tile, preserve_sub_focus=True)

    def _menu_sub_select(self, tile_idx: int, sub_idx: int) -> None:
        if not (0 <= tile_idx <= 3):
            return
        children = MAIN_GROUPS[tile_idx][3]
        if not (0 <= sub_idx < len(children)):
            return
        label, method_name = children[sub_idx]
        fn = getattr(self, method_name, None)
        if not callable(fn):
            # Surface missing target — bug was silently failing before
            try:
                messagebox.showerror("Menu", f"{label}: method {method_name} not wired")
            except Exception:
                pass
            return
        self._menu_expanded_tile = None
        self._menu_canvas = None
        try:
            fn()
        except Exception as exc:
            try:
                messagebox.showerror(
                    "Menu",
                    f"{label} failed:\n{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
            # Restore main menu so user isn't stuck on a broken screen
            try:
                self._menu("main")
            except Exception:
                pass

    def _menu_tile_collapse(self) -> None:
        self._menu_expanded_tile = None
        self._menu_sub_focus = 0
        self._menu_main_bloomberg()

    def _menu_live_schedule(self) -> None:
        """Re-arm the 5s live-data refresh while the Bloomberg menu is active.

        Pause while a tile is expanded — tiles aren't visible, the refresh
        would just redraw them on top of the desk panel (the 'click bug').
        """
        if self._menu_canvas is None:
            self._menu_live_after_id = None
            return
        if getattr(self, "_menu_expanded_tile", None) is not None:
            # Re-check in 1s so it resumes quickly after ESC/collapse.
            try:
                self._menu_live_after_id = self.after(1000, self._menu_live_schedule)
            except Exception:
                self._menu_live_after_id = None
            return
        self._menu_live_fetch_async()
        try:
            self._menu_live_after_id = self.after(5000, self._menu_live_schedule)
        except Exception:
            self._menu_live_after_id = None

    # --- SPLASH (Layer 0) — HL1 Black Mesa gate ----------
    def _splash_on_click(self) -> None:
        """Click / ENTER / space handler — route to Macro Brain cockpit first."""
        if self._splash_pulse_after_id is not None:
            try:
                self.after_cancel(self._splash_pulse_after_id)
            except Exception:
                pass
            self._splash_pulse_after_id = None
        try:
            self.main.unbind("<Button-1>")
        except Exception:
            pass
        self._splash_canvas = None
        # Macro Brain cockpit é a intro — rich market data. User clica
        # "ENTER TERMINAL" pra ir pro main menu com as trade engines.
        self._macro_brain_menu()

    def _cd_draw(self):
        """Animate the CD radar on the splash screen."""
        if not getattr(self, "_cd_alive", False):
            return
        cv = self._cd_canvas
        sz = self._cd_size
        self._cd_t += 0.015
        t = self._cd_t
        cx, cy = sz / 2, sz / 2
        R = sz * 0.44

        cv.delete("all")

        # Grid rings
        for pct in (0.2, 0.4, 0.6, 0.8, 1.0):
            r = R * pct
            alpha = "#2a1800" if pct < 1.0 else "#3d2200"
            cv.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline=alpha, width=1)

        # Crosshairs
        for angle_deg in (0, 45, 90, 135):
            a = math.radians(angle_deg)
            cv.create_line(cx + math.cos(a) * R, cy + math.sin(a) * R,
                           cx - math.cos(a) * R, cy - math.sin(a) * R,
                           fill="#1a1000", width=1)

        # Data spiral — binary encoded
        N = 400
        for i in range(N):
            ang = (i / N) * math.pi * 12 + t * 0.3
            r = 6 + (i / N) * R
            x = cx + math.cos(ang) * r
            y = cy + math.sin(ang) * r
            signal = math.sin(i * 0.73 + t * 12) > 0.2
            if signal:
                # Brighter toward edge
                c = "#4d2800" if i < N * 0.5 else "#663800"
                cv.create_rectangle(x, y, x + 1, y + 1, fill=c, outline="")

        # Sweep line
        sweep = t * 1.2
        sx = cx + math.cos(sweep) * R
        sy = cy + math.sin(sweep) * R
        cv.create_line(cx, cy, sx, sy, fill="#3d2200", width=1)

        # Read head
        rr = ((t * 10) % R) + 6
        lx = cx + math.cos(sweep) * rr
        ly = cy + math.sin(sweep) * rr
        cv.create_oval(lx - 1.5, ly - 1.5, lx + 1.5, ly + 1.5,
                       fill=AMBER, outline="")

        # Center dot
        cv.create_oval(cx - 2, cy - 2, cx + 2, cy + 2,
                       fill=AMBER_D, outline="")

        # Label
        cv.create_text(cx, cy + R + 12, text="O  SIGNAL  TOPOLOGY",
                       font=(FONT, 7), fill=DIM2, anchor="center")

        self.after(33, self._cd_draw)  # ~30 fps

    def _splash(self):
        """Premium institutional landing screen (migrated to ScreenManager)."""
        self._clr()
        self._clear_kb()
        self.history.clear()
        # Hide legacy main body; show screens_container (sibling of self.main).
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        # Legacy compat: ENTER/space still routed via Terminal-level kb.
        # Registered here because _clear_kb wipes them on every switch.
        self._kb("<Return>", self._splash_on_click)
        self._kb("<space>", self._splash_on_click)
        self._schedule_first_paint_metric("splash")
        screen = self.screens.show("splash")
        # Expose canvas handle for legacy callers (_splash_pulse_tick, etc).
        self._splash_canvas = screen.canvas
        self._menu_canvas = screen.canvas
        try:
            self.focus_set()
        except Exception:
            pass

    def _render_splash(self, _event=None) -> None:
        canvas = self._splash_canvas
        if canvas is None:
            return
        self._splash_viewport, self._splash_render_scale = self._apply_canvas_scale(
            canvas,
            self._SPLASH_DESIGN_W,
            self._SPLASH_DESIGN_H,
            self._splash_render_scale,
        )

    def _splash_pulse_tick(self):
        canvas = self._splash_canvas
        if canvas is None:
            self._splash_pulse_after_id = None
            return
        self._splash_cursor_on = not self._splash_cursor_on
        new_text = "[ ENTER TO ACCESS DESK ]_" if self._splash_cursor_on else "[ ENTER TO ACCESS DESK ] "
        new_color = AMBER_B if self._splash_cursor_on else AMBER
        try:
            canvas.itemconfig("prompt2", text=new_text, fill=new_color)
        except Exception:
            self._splash_pulse_after_id = None
            return
        try:
            self._splash_pulse_after_id = self.after(500, self._splash_pulse_tick)
        except Exception:
            self._splash_pulse_after_id = None

    def _menu_main_bloomberg(self) -> None:
        self._clr()
        self._clear_kb()
        self.history.clear()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self._schedule_first_paint_metric("main_menu")
        self.screens.show("main_menu")
        try:
            self.focus_set()
        except Exception:
            pass

    def _render_main_menu(self, _event=None) -> None:
        canvas = self._menu_canvas
        if canvas is None:
            return
        viewport, self._menu_render_scale = self._apply_canvas_scale(
            canvas,
            self._MENU_DESIGN_W,
            self._MENU_DESIGN_H,
            self._menu_render_scale,
        )
        # _apply_canvas_scale aligns bbox-TL to viewport-TL, which ignores
        # the 24/18 design padding of the frame chrome and leaves content
        # visually shifted. Re-center the bbox against the live window
        # (same compensation splash.py applies in _render_resize). Without
        # this, _active_tile_slots (computed below from viewport origin)
        # ends up ~24*scale off from where tiles actually render, and any
        # redraw via _tile_rect pulls tiles to the right.
        live_w = max(canvas.winfo_width(), 1)
        live_h = max(canvas.winfo_height(), 1)
        bbox = canvas.bbox("all")
        if bbox:
            bbox_cx = (bbox[0] + bbox[2]) / 2
            bbox_cy = (bbox[1] + bbox[3]) / 2
            canvas.move("all", live_w / 2 - bbox_cx, live_h / 2 - bbox_cy)
        self._menu_viewport = viewport
        dx, dy = viewport[0], viewport[1]
        scale = self._menu_render_scale
        self._active_tile_slots = [
            ("nw", int(round(202 * scale)) + dx, int(round(150 * scale)) + dy),
            ("ne", int(round(718 * scale)) + dx, int(round(150 * scale)) + dy),
            ("sw", int(round(202 * scale)) + dx, int(round(390 * scale)) + dy),
            ("se", int(round(718 * scale)) + dx, int(round(390 * scale)) + dy),
        ]
        self._active_cd_center = (int(round(460 * scale)) + dx, int(round(270 * scale)) + dy)

    def _menu_tile_expand(self, idx: int) -> None:
        try:
            self._menu_tile_expand_impl(idx)
        except Exception as exc:
            try:
                messagebox.showerror(
                    "Menu expand",
                    f"{type(exc).__name__}: {exc}",
                )
                self._menu("main")
            except Exception:
                pass

    def _menu_tile_expand_impl(self, idx: int, preserve_sub_focus: bool = False) -> None:
        if not (0 <= idx <= 3) or self._menu_canvas is None:
            return
        self._menu_expanded_tile = idx
        if not preserve_sub_focus:
            self._menu_sub_focus = 0

        canvas = self._menu_canvas
        # Rebuild from scratch at design (scale-1) coords. Previously we
        # kept the already-scaled "frame" and drew the expanded content at
        # design coords on top, which left the two at different scales —
        # expanded panel drifted relative to the frame. Clearing + chrome
        # redraw + end-of-method _render_main_menu() keeps them aligned.
        canvas.delete("all")
        self._menu_render_scale = 1.0
        screen = getattr(self, "_main_menu_screen", None)
        if screen is not None:
            screen.draw_chrome()

        label, key_num, color, children = MAIN_GROUPS[idx]
        # Expand uses the full inner area (leaves room for outer frame + top bar)
        x1, y1, x2, y2 = 52, 58, 868, 498
        self._draw_panel(canvas, x1, y1, x2, y2,
                         title=f"  {label} · DESK-{key_num}  ",
                         accent=color, tag=f"tile{idx}")
        # Compact desk header — single thin strip at the top
        canvas.create_rectangle(x1 + 8, y1 + 16, x2 - 8, y1 + 46,
                                outline=self._dim_color(color, 0.5),
                                fill=BG2, width=1, tags=f"tile{idx}")
        canvas.create_line(x1 + 8, y1 + 16, x2 - 8, y1 + 16,
                           fill=color, width=1, tags=f"tile{idx}")
        self._draw_aurum_logo(canvas, x1 + 22, y1 + 31, scale=6, tag=f"tile{idx}")
        canvas.create_text(x1 + 34, y1 + 31, anchor="w",
                           text=label,
                           font=(FONT, 9, "bold"), fill=color, tags=f"tile{idx}")
        # Module count — discreet right-of-label, mono
        canvas.create_text(x1 + 34 + len(label) * 7 + 14, y1 + 31, anchor="w",
                           text=f"[ {len(children)} MOD ]",
                           font=(FONT, 7), fill=DIM, tags=f"tile{idx}")
        # BACK chip on the right (no overlap — moved above the rows band)
        bx1, by1, bx2, by2 = x2 - 92, y1 + 20, x2 - 16, y1 + 42
        canvas.create_rectangle(bx1, by1, bx2, by2,
                                outline=self._dim_color(color, 0.6),
                                fill=BG3, width=1, tags=f"tile{idx}")
        canvas.create_line(bx1, by1, bx2, by1, fill=color, width=1, tags=f"tile{idx}")
        canvas.create_text((bx1 + bx2) // 2, (by1 + by2) // 2,
                           text="◂ BACK · ESC",
                           font=(FONT, 6, "bold"), fill=WHITE, tags=f"tile{idx}")
        self._back_btn_rect = (bx1, by1, bx2, by2)

        self._menu_sub_render(idx)

        # Footer — terse, right-aligned like a terminal status line
        foot_y = y2 - 22
        canvas.create_line(x1 + 16, foot_y, x2 - 16, foot_y,
                           fill=BORDER,
                           width=1, tags=f"tile{idx}")
        canvas.create_text(x2 - 16, foot_y + 10, anchor="e",
                           text=f"ESC BACK · 1-{len(children)} SELECT · ⏎ OPEN",
                           font=(FONT, 7),
                           fill=DIM,
                           tags=f"tile{idx}")

        def _sub_click(event, _idx=idx):
            ex, ey = event.x, event.y
            br = getattr(self, "_back_btn_rect", None)
            if br and br[0] <= ex <= br[2] and br[1] <= ey <= br[3]:
                self._menu_tile_collapse()
                return "break"
            _children = MAIN_GROUPS[_idx][3]
            n = len(_children)
            row_h = 34 if n <= 5 else 30 if n <= 7 else 28
            start_y = 118
            for i in range(n):
                ry1 = start_y + i * row_h
                ry2 = ry1 + (row_h - 6)
                if 72 <= ex <= 848 and ry1 <= ey <= ry2:
                    self._menu_sub_select(_idx, i)
                    return "break"
        canvas.bind("<Button-1>", _sub_click)

        self._clear_kb()
        for i, (_clabel, _method) in enumerate(children):
            n = i + 1
            self._kb(f"<Key-{n}>", lambda _i=i, _tile=idx: self._menu_sub_select(_tile, _i))
        self._kb("<Down>", lambda: self._menu_sub_focus_delta(+1))
        self._kb("<Up>", lambda: self._menu_sub_focus_delta(-1))
        self._kb("<Return>", lambda _tile=idx: self._menu_sub_select(_tile, self._menu_sub_focus))
        self._kb("<Escape>", self._menu_tile_collapse)
        self._kb("<Key-0>", self._menu_tile_collapse)
        self._bind_global_nav()
        self.f_lbl.configure(text="1-N select path  |  click item  |  enter confirm  |  esc back")
        # Re-apply scale now that chrome + expanded content are drawn at
        # design coords. Without this, expand on a zoomed window leaves
        # content at scale 1 while the header remains in design coords —
        # equivalent layout but looks shrunk-and-off-center.
        self._render_main_menu()

    def _menu_sub_render(self, idx: int) -> None:
        if self._menu_canvas is None:
            return
        canvas = self._menu_canvas
        canvas.delete("submenu")
        _label, _key, color, children = MAIN_GROUPS[idx]
        n = len(children)
        # Denser rows — Bloomberg uses ~28-34px per line, not 54.
        row_h = 34 if n <= 5 else 30 if n <= 7 else 28
        h_inner = row_h - 6
        start_y = 118
        row_x1, row_x2 = 72, 848
        # Two-line rows only when there's breathing room
        compact = row_h < 32
        dim_band = self._dim_color(color, 0.45)
        for i, (child_label, _method) in enumerate(children):
            y1 = start_y + i * row_h
            y2 = y1 + h_inner
            focused = i == self._menu_sub_focus
            fill = BG2 if focused else PANEL
            outline = self._dim_color(color, 0.55) if focused else BORDER
            text_color = AMBER_B if focused else WHITE
            band = color if focused else dim_band
            # Outer row frame — thin, uniform
            canvas.create_rectangle(row_x1, y1, row_x2, y2, outline=outline,
                                    fill=fill, width=1, tags="submenu")
            # Single accent stripe on the left (no filled gutter)
            canvas.create_line(row_x1, y1, row_x1, y2,
                               fill=band, width=2 if focused else 1,
                               tags="submenu")
            # Index pill: quiet mono number, no color unless focused
            canvas.create_text(row_x1 + 18, (y1 + y2) // 2,
                               text=f"{i+1:02d}", anchor="center",
                               font=(FONT, 8),
                               fill=(color if focused else DIM),
                               tags="submenu")
            desc = BLOCK_DESCRIPTIONS.get(_method, "open module")
            if compact:
                # Single line: label + inline desc, everything small and mono
                canvas.create_text(row_x1 + 36, (y1 + y2) // 2, anchor="w",
                                   text=child_label,
                                   font=(FONT, 10, "bold"), fill=text_color,
                                   tags="submenu")
                canvas.create_text(row_x1 + 210, (y1 + y2) // 2, anchor="w",
                                   text=desc[:64], font=(FONT, 7), fill=DIM,
                                   tags="submenu")
            else:
                canvas.create_text(row_x1 + 36, y1 + 10, anchor="w",
                                   text=child_label,
                                   font=(FONT, 10, "bold"), fill=text_color,
                                   tags="submenu")
                canvas.create_text(row_x1 + 36, y1 + 22, anchor="w",
                                   text=desc, font=(FONT, 7), fill=DIM,
                                   tags="submenu")
            # ENTER affordance ONLY on the focused row — kills repeated noise
            if focused:
                canvas.create_text(row_x2 - 10, (y1 + y2) // 2, anchor="e",
                                   text="⏎ OPEN",
                                   font=(FONT, 7, "bold"),
                                   fill=color,
                                   tags="submenu")

    def _draw_isometric_tile(self, canvas, idx: int, focused: bool) -> None:
        label, key_num, color, _children = MAIN_GROUPS[idx]
        x1, y1, x2, y2 = self._tile_rect(idx)
        face_color = color if focused else self._dim_color(color, TILE_DIM_FACTOR)
        panel_fill = BG2 if focused else PANEL
        text_color = WHITE if focused else "#b8b8b8"
        sub_color = AMBER_B if focused else DIM
        tag = f"tile{idx}"

        canvas.delete(tag)
        canvas.create_rectangle(x1, y1, x2, y2, outline=face_color,
                                fill=panel_fill, width=2 if focused else 1, tags=tag)
        # Accent stripe on left edge (full height) — dá vida sem ruído
        canvas.create_rectangle(x1, y1, x1 + 3, y2, outline="",
                                fill=face_color, tags=tag)
        # Header band
        canvas.create_rectangle(x1 + 3, y1, x2, y1 + 22, outline="", fill=BG3, tags=tag)
        canvas.create_line(x1, y1 + 22, x2, y1 + 22, fill=face_color, width=1, tags=tag)

        # Key chip — always solid accent, bg-on-accent for strong contrast
        canvas.create_rectangle(x1 + 9, y1 + 5, x1 + 27, y1 + 18,
                                outline="",
                                fill=(face_color if focused else self._dim_color(color, 0.55)),
                                tags=tag)
        canvas.create_text(x1 + 18, y1 + 11, anchor="center",
                           text=key_num, font=(FONT, 8, "bold"),
                           fill=BG, tags=tag)

        # Tile label
        canvas.create_text(x1 + 36, y1 + 11, anchor="w",
                           text=label,
                           font=(FONT, 10, "bold"),
                           fill=text_color, tags=tag)
        # Modules count pill (right aligned)
        canvas.create_text(x2 - 10, y1 + 11, anchor="e",
                           text=f"{len(_children)} MOD",
                           font=(FONT, 6, "bold"),
                           fill=(face_color if focused else DIM), tags=tag)

        # Section divider
        canvas.create_line(x1 + 10, y1 + 30, x2 - 10, y1 + 30, fill=BORDER, width=1, tags=tag)
        canvas.create_text(x1 + 12, y1 + 40, anchor="w",
                           text="MODULES",
                           font=(FONT, 6, "bold"),
                           fill=(face_color if focused else DIM), tags=tag)

        # Module preview (up to 2 rows)
        preview_y = y1 + 48
        shown = _children[:2]
        for child_idx, (child_label, _method) in enumerate(shown):
            py1 = preview_y + child_idx * 17
            py2 = py1 + 13
            chip_fill = BG3 if focused else BG
            canvas.create_rectangle(x1 + 12, py1, x2 - 12, py2,
                                    outline=BORDER, fill=chip_fill, width=1, tags=tag)
            canvas.create_rectangle(x1 + 12, py1, x1 + 16, py2,
                                    outline="",
                                    fill=(color if focused else self._dim_color(color, 0.55)),
                                    tags=tag)
            label_txt = child_label[:24]
            canvas.create_text(x1 + 22, py1 + 6, anchor="w",
                               text=label_txt,
                               font=(FONT, 6, "bold"),
                               fill=text_color, tags=tag)
        if len(_children) > 2:
            hint_y = preview_y + 2 * 17 + 4
            canvas.create_text(x2 - 14, hint_y, anchor="e",
                               text=f"+{len(_children) - 2} MORE",
                               font=(FONT, 6, "bold"), fill=sub_color, tags=tag)

        # Footer hint (no more LIVE STATUS — removido a pedido do usuário)
        hint_y = y2 - 14
        canvas.create_line(x1 + 12, hint_y - 4, x2 - 12, hint_y - 4,
                           fill=BORDER, width=1, tags=tag)
        canvas.create_text(x1 + 12, hint_y + 1, anchor="w",
                           text="PRESS  " + key_num + "  /  CLICK",
                           font=(FONT, 6, "bold"),
                           fill=(face_color if focused else DIM), tags=tag)
        canvas.create_text(x2 - 12, hint_y + 1, anchor="e",
                           text="OPEN ▸",
                           font=(FONT, 6, "bold"),
                           fill=(face_color if focused else DIM2), tags=tag)

    def _bind_global_nav(self):
        """Bind global navigation keys available on all screens."""
        self._kb("<Key-h>", lambda: self._menu("main"))
        self._kb("<Key-m>", lambda: self._menu("markets"))
        self._kb("<Key-s>", lambda: self._menu("strategies"))
        self._kb("<Key-r>", lambda: self._menu("risk"))
        self._kb("<Key-q>", self._quit)

    # --- MENU --------------------------------------------
    def _menu(self, key):
        # Route to specialized screens
        if key == "main":
            self._menu_main_bloomberg()
            return
        if key in ("markets", "connections", "terminal", "risk", "settings", "alchemy", "data", "macro_brain"):
            {
                "markets": self._markets,
                "connections": self._connections,
                "terminal": self._terminal,
                "risk": self._risk_menu,
                "settings": self._config,
                "alchemy": self._arbitrage_hub,
                "data": self._data_center,
                "macro_brain": self._macro_brain_menu,
            }[key]()
            return
        if key == "strategies":
            self._strategies(); return
        if key == "command":
            self._command_center(); return
        if key == "dash-backtest":
            # Back-from-metrics: return to crypto dashboard BACKTEST tab.
            self._crypto_dashboard()
            try:
                self._dash_render_tab("backtest")
            except Exception as exc:
                import traceback as _tb
                _tb.print_exc()
                try:
                    self.h_stat.configure(
                        text=f"BACKTEST RENDER FAIL: {type(exc).__name__}",
                        fg=RED,
                    )
                except Exception:
                    pass
            return
        if key == "backtest":
            # Legacy alias — same as dash-backtest for older call sites.
            self._crypto_dashboard()
            try:
                self._dash_render_tab("backtest")
            except Exception as exc:
                import traceback as _tb
                _tb.print_exc()
                try:
                    self.h_stat.configure(
                        text=f"BACKTEST RENDER FAIL: {type(exc).__name__}",
                        fg=RED,
                    )
                except Exception:
                    pass
            return

        if key == "live":
            self._strategies_live()
            return

        self._clr(); self._clear_kb()
        self.h_stat.configure(text="SELECIONAR", fg=AMBER_D)

        if key == "main":
            self.history.clear()
            items = [(n, k, d) for n, k, d in MAIN_MENU]
            title = "PRINCIPAL"
            self.h_path.configure(text="")
            self.f_lbl.configure(text="ESC sair  |  H hub  |  S strategies  |  Q quit")
            self._kb("<Escape>", self._splash)
            self._bind_global_nav()
        else:
            self.history = ["main"]
            items = [(n, s, d) for n, s, d in SUB_MENUS.get(key, [])]
            title = key.upper()
            self.h_path.configure(text=f"> {title}")
            self.f_lbl.configure(text="ESC voltar  |  número para selecionar  |  0 voltar")
            self._kb("<Escape>", lambda: self._menu("main"))
            self._kb("<BackSpace>", lambda: self._menu("main"))
            self._kb("<Key-0>", lambda: self._menu("main"))
            self._bind_global_nav()

        # --- MAIN MENU: Fibonacci design -----------------
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
                    start=90 * i, extent=90, outline=f"#C8C8C8",
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
            fib_canvas.create_text(cx + 100, cy - 130, text="f = 1.618", font=(FONT, 7),
                                    fill=DIM2, anchor="w")

            # Title over canvas
            title_frame = tk.Frame(f, bg=BG)
            title_frame.place(relx=0.5, rely=0.12, anchor="center")
            tk.Label(title_frame, text="PRINCIPAL", font=(FONT, 16, "bold"), fg=AMBER, bg=BG).pack()
            tk.Label(title_frame, text="Selecionar operação", font=(FONT, 8), fg=DIM, bg=BG).pack()

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
                tk.Label(row, text="-", font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left")

                nl = tk.Label(row, text=f" {name}", font=(FONT, 10, "bold"), fg=WHITE, bg=BG3,
                              anchor="w", padx=8, pady=5, width=14)
                nl.pack(side="left")

                dl = tk.Label(row, text=desc, font=(FONT, 8), fg=DIM, bg=BG3, anchor="w", padx=8, pady=5)
                dl.pack(side="left", fill="x", expand=True)

                # Right phi indicator
                tk.Label(row, text="›", font=(FONT, 10), fg=DIM2, bg=BG3, padx=6).pack(side="right")

                cmd = lambda t=target: self._menu(t)

                for w in [row, nl, dl]:
                    w.bind("<Enter>", lambda e, r=row, n=nl: (r.configure(bg=BG3), n.configure(fg=AMBER)))
                    w.bind("<Leave>", lambda e, r=row, n=nl: (r.configure(bg=BG), n.configure(fg=WHITE)))
                    w.bind("<Button-1>", lambda e, c=cmd: c())

                if num < 10:  # Tk only supports single-digit <Key-N> bindings
                    self._kb(f"<Key-{num}>", cmd)

        # --- SUBMENUS: clean list -------------------------
        else:
            f = tk.Frame(self.main, bg=BG); f.pack(expand=True)

            # Hermes cameo background for backtest submenu
            if key == "backtest":
                _HERMES = (
                    "                ?------?          \n"
                    "             ?--?¦¦¦¦¦¦?--?       \n"
                    "          ?--?¦¦¦¦¦¦¦¦¦¦¦¦?-?     \n"
                    "    ---- ?¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦     \n"
                    "   ----?¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦     \n"
                    "       ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦?      \n"
                    "       ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦?        \n"
                    "       ¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦¦?          \n"
                    "       ¦¦¦¦¦¦¦¦¦¦¦¦¦¦?            \n"
                    "       ¦¦¦¦¦¦¦¦¦¦¦¦?              \n"
                    "       ¦¦¦¦¦¦¦¦¦¦¦¦               \n"
                    "       ??¦¦¦¦¦¦¦¦?                \n"
                    "        ??¦¦¦¦¦?                  \n"
                    "         ??¦¦?                    \n"
                    "          ??                      \n"
                    "      f = 1.618                   \n"
                )
                tk.Label(f, text=_HERMES, font=(FONT, 7), fg="#1a1a2e",
                         bg=BG, justify="right", anchor="e").place(relx=0.92, rely=0.5, anchor="e")

            tk.Label(f, text=title, font=(FONT, 14, "bold"), fg=AMBER, bg=BG).pack(pady=(0, 6))
            tk.Label(f, text="Selecionar engine", font=(FONT, 8), fg=DIM, bg=BG).pack(pady=(0, 16))

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

                if num < 10:  # Tk only supports single-digit <Key-N> bindings
                    self._kb(f"<Key-{num}>", cmd)

            # Back row
            tk.Frame(f, bg=BG, height=10).pack()
            brow = tk.Frame(f, bg=BG, cursor="hand2"); brow.pack(fill="x", padx=60, pady=1)
            tk.Label(brow, text=" 0 ", font=(FONT, 9, "bold"), fg=WHITE, bg=DIM2, width=3).pack(side="left")
            bl = tk.Label(brow, text="  VOLTAR", font=(FONT, 10), fg=DIM, bg=BG3, anchor="w", padx=6, pady=4)
            bl.pack(side="left", fill="x", expand=True)
            for w in [brow, bl]:
                w.bind("<Button-1>", lambda e: self._menu("main"))

    # --- STRATEGY BRIEFING ------------------------------
    def _brief(self, name, script, desc, parent_menu):
        """Delegate to launcher_support.screens.brief.render. Full
        implementation (4-section Bloomberg-style briefing + code viewer
        button) lives there. Kept as a method shim so every internal call
        site (_strategies rows, backtest/live menu entries, tests) stays
        unchanged.
        """
        from launcher_support.screens.brief import render as _render_brief
        _render_brief(self, name, script, desc, parent_menu)

    # --- CALIBRATED CONFIG RESOLVER -----------------------
    @staticmethod
    def _best_calibrated_config(engine_name: str) -> dict:
        """Resolve the best validated config for an engine.

        Priority:
          1. BRIEFINGS[name]["best_config"] — battery-validated (strongest signal)
          2. ENGINE_INTERVALS / ENGINE_BASKETS fallbacks (longrun)
          3. Generic defaults (360d / default / 1x / plots ON)

        Returns dict with keys {period, basket, leverage, plots}. Period
        is always the longest validated horizon (180d if briefing says so,
        else 360d). Basket is the validated one (default vs bluechip etc).
        """
        import re
        # Generic safe baseline
        out = {"period": "360", "basket": "", "leverage": "", "plots": "s"}

        # Layer 1 — BRIEFINGS best_config
        try:
            brief = BRIEFINGS.get(engine_name, {}) or {}
            bc = brief.get("best_config", {}) or {}

            # Period: parse "180 dias" / "360" / "90 days"
            per = str(bc.get("Período") or bc.get("Period") or "").lower()
            m = re.search(r"(\d+)", per)
            if m:
                out["period"] = m.group(1)

            # Basket: extract first word ("default", "bluechip", "majors", etc)
            bsk = str(bc.get("Basket") or bc.get("Cesta") or "").strip().lower()
            m = re.match(r"([a-z0-9_-]+)", bsk)
            if m:
                token = m.group(1)
                # Map to BASKET option codes
                _basket_map = {
                    "default": "", "top12": "2", "defi": "3", "l1": "4",
                    "layer": "4", "l2": "5", "ai": "6", "meme": "7",
                    "majors": "8", "bluechip": "9",
                }
                out["basket"] = _basket_map.get(token, "")
        except Exception:
            pass

        # Layer 2 — fallback to ENGINE_INTERVALS/BASKETS for unknown engines
        try:
            from config.params import ENGINE_BASKETS
            key = engine_name.upper().replace(" ", "")
            if not out["basket"]:
                bsk = str(ENGINE_BASKETS.get(key, "default")).lower()
                _basket_map = {"default": "", "bluechip": "9", "majors": "8"}
                out["basket"] = _basket_map.get(bsk, "")
        except Exception:
            pass
        return out

    @staticmethod
    def _engine_extra_cli_flags(engine_name: str) -> list[str]:
        """Engine-specific CLI overrides injected by the launcher.

        Extend here for future engines whose params differ from config.params
        defaults. Flags applied here don't touch config.params (core-
        protected) — they only change the in-process dataclass for the run.
        """
        name = engine_name.upper().replace(" ", "").replace("_", "")
        return []

    # --- INLINE LIVE EXEC (from picker RUN chip in LIVE mode) ------
    def _exec_live_inline(self, name, script, desc, mode_preset, cfg):
        """Fire a strategy in live mode (paper/demo/testnet/live) directly
        from the picker. Routes via engines/live.py for the unified live
        runner; janestreet uses its own dedicated arbitrage runner.

        mode_preset ? {'paper','demo','testnet','live'}.
        cfg may carry leverage/basket overrides (basket only relevant for
        engines that filter their universe). Refuses to dispatch LIVE mode
        without an explicit confirm dialog — capital safety gate.
        """
        if mode_preset == "live":
            try:
                ok = messagebox.askyesno(
                    "LIVE EXECUTION — capital real",
                    f"Você está prestes a rodar {name} em LIVE mode\n"
                    f"com capital real. Confirma?",
                    icon="warning",
                )
            except Exception:
                ok = False
            if not ok:
                self.h_stat.configure(text="LIVE cancelado", fg=AMBER_D)
                return

        plan = live_launch_plan(script, mode_preset, cfg)
        if plan["uses_dedicated_runner"]:
            self._exec(name, plan["script"], desc, "live", plan["stdin_inputs"])
            return

        # Default: route via engines/live.py with --mode + leverage CLI
        live_script = plan["script"]
        cli: list[str] = plan["cli_args"]

        # Hint + status — let the user know which strategy is being routed
        self.h_stat.configure(
            text=f"{name} → {mode_preset.upper()}",
            fg={"paper": GREEN, "demo": AMBER, "testnet": AMBER_B, "live": RED}[mode_preset],
        )
        self._exec(name, live_script, desc, "live", [], cli_args=cli)

    # --- INLINE BACKTEST EXEC (from picker RUN chip) ------
    def _exec_backtest_inline(self, name, script, desc, parent_menu, cfg):
        """Fire backtest directly from engine_picker RUN chip — no intermediate
        pages. cfg = {preset, period, basket, leverage, plots}.
        preset='calibrated' → use ENGINE_INTERVALS/ENGINE_BASKETS defaults for
        the engine (just pass --days). preset='custom' → honor picker cfg."""
        preset = (cfg or {}).get("preset", "custom")

        if preset == "calibrated":
            # CALIBRATED = best validated config per engine (BRIEFINGS) +
            # ENGINE_INTERVALS / ENGINE_BASKETS for sweet-spot defaults.
            # Always picks the longest validated period × the basket where
            # the engine showed the strongest edge.
            best_cfg = self._best_calibrated_config(name)
            period   = best_cfg["period"]
            basket   = best_cfg["basket"]
            leverage = best_cfg["leverage"]
            plots    = best_cfg["plots"]
        else:
            period   = str(cfg.get("period", "90") or "90")
            basket   = str(cfg.get("basket", "") or "")
            leverage = str(cfg.get("leverage", "") or "")
            plots    = str(cfg.get("plots", "s") or "s")

        # stdin auto-inputs (legacy engines with prompts)
        inputs = [period, basket]
        if name == "CITADEL":
            inputs.append(plots)
        inputs.append(leverage)
        inputs.append("")  # enter to start

        # CLI args (modern engines w/ argparse + --no-menu)
        cli: list[str] = []
        try:
            _days = int(period.strip()) if period.strip() else 0
            if _days >= 7:
                cli += ["--days", str(_days)]
        except (ValueError, TypeError):
            pass
        _bsk = basket.strip()
        if _bsk and not _bsk.isdigit():
            cli += ["--basket", _bsk]
        elif _bsk.isdigit():
            try:
                from config.params import BASKETS
                _bnames = [k for k in BASKETS if k != "custom"]
                _idx = int(_bsk) - 1
                if 0 <= _idx < len(_bnames):
                    cli += ["--basket", _bnames[_idx]]
            except Exception:
                pass
        try:
            _lev = float(leverage.replace("x", "").strip()) if leverage.strip() else 0
            if 0.1 <= _lev <= 125:
                cli += ["--leverage", str(_lev)]
        except (ValueError, TypeError):
            pass
        cli += self._engine_extra_cli_flags(name)
        cli += ["--no-menu"]

        if getattr(self, "_strategies_picker", None):
            if self._strategies_spawn_inline_backtest(name, script, cli, inputs):
                return

        self._exec(name, script, desc, parent_menu, inputs, cli_args=cli)

    def _strategies_progress_target(self, clean: str) -> tuple[float, str]:
        return _strategies_progress_target_helper(clean)

    def _strategies_spawn_inline_backtest(self, name, script, cli_args, auto_inputs) -> bool:
        handle = getattr(self, "_strategies_picker", None)
        if not handle:
            return False
        try:
            from core.ops.proc import spawn, _is_alive
        except Exception:
            return False

        proc_key = self._exec_script_to_proc_key(script)
        if proc_key is None:
            return False

        slug = canonical_engine_key(SCRIPT_TO_KEY.get(script.replace("\\", "/"), ""))
        try:
            handle["set_progress"](slug, 4.0, "preparing backtest runtime", True)
        except Exception:
            pass

        info = spawn(proc_key, stdin_lines=auto_inputs or None, cli_args=cli_args or None)
        if not info:
            try:
                handle["set_progress"](slug, 0.0, "engine already running or launch failed", False)
            except Exception:
                pass
            return True

        self._strategies_inline_runs = getattr(self, "_strategies_inline_runs", {})
        self._strategies_inline_runs[slug] = {
            "pid": int(info["pid"]),
            "log_file": info["log_file"],
            "pct": 8.0,
            "tail": "background active",
        }
        try:
            handle["set_progress"](slug, 8.0, f"managed pid {info['pid']} | background active", True)
        except Exception:
            pass

        def _tail():
            last = 0
            pct = 8.0
            tail = "background active"
            log_path = Path(info["log_file"])
            # Engines como MILLENNIUM logam centenas de linhas por segundo
            # durante walk-forward / monte carlo. Dispatchar set_progress
            # por linha (via self.after(0, ...)) enfila dezenas de rebuilds
            # do picker na main thread, travando a UI e o Windows. Batch:
            # processa todas as linhas do chunk, mas so dispara UM
            # set_progress por ciclo do loop (cada ~150ms), usando o ultimo
            # pct/tail acumulado.
            while True:
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last)
                        chunk = f.read()
                        last = f.tell()
                except OSError:
                    chunk = ""

                if chunk:
                    saw_line = False
                    for raw in chunk.splitlines():
                        clean = raw.strip()
                        if not clean:
                            continue
                        saw_line = True
                        next_pct, stage = self._strategies_progress_target(clean)
                        if next_pct > 0:
                            pct = max(pct, next_pct)
                            tail = stage
                        else:
                            pct = min(88.0, pct + 0.2)
                            tail = clean[:180]
                        self._strategies_inline_runs[slug]["pct"] = pct
                        self._strategies_inline_runs[slug]["tail"] = tail
                    if saw_line:
                        try:
                            self.after(0, lambda s=slug, p=pct, t=tail: handle["set_progress"](s, p, t, True))
                        except Exception:
                            return

                if not _is_alive(int(info["pid"]), expected=info):
                    try:
                        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                            f.seek(last)
                            chunk = f.read()
                    except OSError:
                        chunk = ""
                    if chunk:
                        for raw in chunk.splitlines():
                            clean = raw.strip()
                            if clean:
                                tail = clean[:180]
                    self._strategies_inline_runs[slug]["pct"] = 100.0
                    self._strategies_inline_runs[slug]["tail"] = tail or "backtest complete"
                    try:
                        self.after(0, lambda s=slug, t=(tail or "backtest complete"): handle["set_progress"](s, 100.0, t, False))
                    except Exception:
                        pass
                    try:
                        self.after(1400, lambda: self._try_results("backtest"))
                    except Exception:
                        pass
                    return
                time.sleep(0.15)

        threading.Thread(target=_tail, daemon=True).start()
        return True

    # --- BACKTEST CONFIG (clickable inputs) --------------
    def _config_backtest(self, name, script, desc, parent_menu):
        """Delegate to launcher_support.screens.config_backtest.render.
        Full dialog (period + basket + charts + leverage selectors and
        do_run that assembles stdin-inputs + CLI args) lives there.
        """
        from launcher_support.screens.config_backtest import render as _render_config_backtest
        _render_config_backtest(self, name, script, desc, parent_menu)

    # --- LIVE CONFIG (clickable mode select) -----------
    def _config_live(self, name, script, desc, parent_menu):
        """Config screen for live engines — select mode then run."""
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name} > CONFIG")
        self.h_stat.configure(text="CONFIGURAR", fg=AMBER_D)
        self.f_lbl.configure(text="Selecionar modo e RODAR  |  ESC voltar ao briefing")

        # For arbitrage vs live, different modes
        is_arb = "arbitrage" in script
        if is_arb:
            modes = [
                ("DASHBOARD", "1", "Escanear venues e mostrar oportunidades"),
                ("PAPER",     "2", "Simulado — sem ordens reais"),
                ("DEMO",      "3", "Exchange demo/sandbox API"),
                ("LIVE",      "4", "CAPITAL REAL — extremo cuidado"),
            ]
        else:
            modes = [
                ("PAPER",    "1", "Execução simulada — observar sem risco"),
                ("DEMO",     "2", "Binance Futures Demo API — book real, dinheiro fictício"),
                ("TESTNET",  "3", "Binance Testnet — ambiente de teste"),
                ("LIVE",     "4", "CAPITAL REAL — seu dinheiro em jogo"),
            ]

        self._live_mode = modes[0][1]  # default to first

        _outer, f = self._ui_page_shell(
            f"{name} · MODE SELECT",
            "Select execution environment before starting the engine",
            content_width=920,
        )

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

        run_btn = tk.Label(btn_f, text="  INICIAR ENGINE  ", font=(FONT, 11, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2", padx=16, pady=5)
        run_btn.pack(side="left", padx=4)
        run_btn.bind("<Button-1>", lambda e: do_run())
        self._kb("<Return>", do_run)

        back_btn = tk.Label(btn_f, text="  VOLTAR  ", font=(FONT, 10), fg=DIM, bg=BG3,
                            cursor="hand2", padx=12, pady=5)
        back_btn.pack(side="left", padx=4)
        back_btn.bind("<Button-1>", lambda e: self._brief(name, script, desc, parent_menu))
        self._kb("<Escape>", lambda: self._brief(name, script, desc, parent_menu))

    @staticmethod
    def _normalize_summary(data: dict) -> dict:
        """Return a unified `summary` dict regardless of report format.

        CITADEL legacy reports embed metrics under ``data["summary"]``. Modern
        engines (BRIDGEWATER, JUMP, DESHAW, RENAISSANCE) write them flat at
        top level with different key names (``n_trades`` vs ``total_trades``,
        ``roi`` vs ``ret``, etc). This helper merges both into a single dict
        using the legacy keys so the overview code doesn't need to branch.
        """
        s = dict(data.get("summary") or {})
        # Key aliases: (top-level source, normalized dest)
        aliases = [
            ("total_pnl",    "total_pnl"),
            ("pnl",          "total_pnl"),
            ("ret",          "ret"),
            ("roi",          "ret"),
            ("roi_pct",      "ret"),
            ("sharpe",       "sharpe"),
            ("sortino",      "sortino"),
            ("calmar",       "calmar"),
            ("win_rate",     "win_rate"),
            ("total_trades", "total_trades"),
            ("n_trades",     "total_trades"),
            ("closed",       "closed"),
            ("final_equity", "final_equity"),
            ("max_dd_pct",   "max_dd_pct"),
            ("max_dd",       "max_dd_pct"),
        ]
        for src, dst in aliases:
            if dst in s and s[dst] not in (None, ""):
                continue
            if src in data and data[src] not in (None, ""):
                s[dst] = data[src]
        # Derive total_pnl if still missing but we have account+final_equity
        if s.get("total_pnl") in (None, "") and "final_equity" in data and "account_size" in data:
            try:
                s["total_pnl"] = float(data["final_equity"]) - float(data["account_size"])
            except (TypeError, ValueError):
                pass
        # Derive ret if missing but we have total_pnl + account_size
        if s.get("ret") in (None, "") and s.get("total_pnl") is not None and "account_size" in data:
            try:
                acct = float(data["account_size"])
                if acct > 0:
                    s["ret"] = float(s["total_pnl"]) / acct * 100
            except (TypeError, ValueError):
                pass
        return s

    def _try_results(self, parent, run_id=None):
        try:
            self._show_results(parent, run_id=run_id)
        except Exception as e:
            self._p(f"\n  Erro no dashboard de resultados: {e}\n", "r")
            self._p("  Use o menu DADOS para navegar relatórios manualmente.\n", "d")

    # --- RESULTS DASHBOARD (Overview + Trade Inspector) ------
    def _show_results(self, parent_menu, run_id=None):
        """Delegate to launcher_support.screens.results.render. Report
        resolution (explicit run_id → latest data/runs/ → legacy layout),
        JSON parsing, state parking, tab strip + Overview kick-off live
        there.
        """
        from launcher_support.screens.results import render as _render_results
        _render_results(self, parent_menu, run_id=run_id)

    @timed_legacy_switch("results_tab")
    def _results_render_tab(self, tab):
        if not hasattr(self, "_results_body") or not self._results_body.winfo_exists():
            return
        for w in self._results_body.winfo_children():
            try: w.destroy()
            except Exception: pass
        self._results_tab = tab
        for tab_id, btn in self._results_tab_btns.items():
            if tab_id == tab:
                btn.configure(bg=BG, fg=AMBER)
            else:
                btn.configure(bg=BG, fg=DIM)
        if tab == "overview":
            self._results_build_overview(self._results_body)
        else:
            self._results_build_trades(self._results_body)

    # -- OVERVIEW TAB --------------------------------------
    def _results_build_overview(self, parent):
        """Delegate to launcher_support.screens.results_overview.render.
        The 340-line implementation (metrics, per-strategy breakdown,
        equity curve, Monte Carlo paths + distribution, regime, actions)
        lives there. This shim preserves the method dispatch site at
        launcher.py:~3190 (_show_results flow).
        """
        from launcher_support.screens.results_overview import render as _render_results_overview
        _render_results_overview(self, parent)

    # -- TRADES TAB (inspector) -----------------------------
    def _results_build_trades(self, parent):
        if not self._results_trades:
            tk.Label(parent, text="Sem trades fechadas neste run.",
                     font=(FONT, 10), fg=DIM, bg=BG).pack(pady=40)
            return

        outer = tk.Frame(parent, bg=BG); outer.pack(fill="both", expand=True)
        top_row = tk.Frame(outer, bg=BG); top_row.pack(fill="both", expand=True)

        # Left sidebar: trade list + filters
        side = tk.Frame(top_row, bg=PANEL, width=210)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._results_build_list(side)

        tk.Frame(top_row, bg=DIM2, width=1).pack(side="left", fill="y")

        # Right: chart + data panel
        right = tk.Frame(top_row, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        self._results_chart_frame = tk.Frame(right, bg="#0d1117", height=320)
        self._results_chart_frame.pack(fill="x", pady=(0, 8))
        self._results_chart_frame.pack_propagate(False)

        self._results_data_panel = tk.Frame(right, bg=PANEL)
        self._results_data_panel.pack(fill="both", expand=True)

        # Bottom nav bar
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x")
        nav = tk.Frame(outer, bg=BG, height=28); nav.pack(fill="x")
        nav.pack_propagate(False)

        prev_btn = tk.Label(nav, text="  ◄ prev  ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG, cursor="hand2", padx=8, pady=6)
        prev_btn.pack(side="left", padx=4)
        prev_btn.bind("<Button-1>", lambda e: self._results_prev_trade())

        self._results_counter = tk.Label(nav, text="", font=(FONT, 8),
                                         fg=DIM, bg=BG)
        self._results_counter.pack(side="left", padx=8)

        next_btn = tk.Label(nav, text="  next ►  ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG, cursor="hand2", padx=8, pady=6)
        next_btn.pack(side="left", padx=4)
        next_btn.bind("<Button-1>", lambda e: self._results_next_trade())

        self._results_stats = tk.Label(nav, text="", font=(FONT, 8),
                                       fg=DIM, bg=BG2)
        self._results_stats.pack(side="right", padx=8)

        # Initial render
        if self._results_filtered:
            self._results_active_idx = min(self._results_active_idx,
                                           len(self._results_filtered) - 1)
            self._results_inspect(self._results_filtered[self._results_active_idx])
        else:
            self._results_update_nav()

    def _results_build_list(self, parent):
        # Filter row
        filt = tk.Frame(parent, bg=BG2); filt.pack(fill="x")
        for tag in ("all", "win", "loss"):
            label = tag.upper()
            active = self._results_filter == tag
            btn = tk.Label(filt, text=f" {label} ", font=(FONT, 7, "bold"),
                           fg=BG if active else DIM,
                           bg=AMBER if active else BG3,
                           padx=8, pady=3, cursor="hand2")
            btn.pack(side="left", padx=2, pady=4)
            btn.bind("<Button-1>", lambda e, t=tag: self._results_filter_set(t))

        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x")

        # Scrollable list
        list_outer = tk.Frame(parent, bg=PANEL)
        list_outer.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_outer, bg=PANEL, highlightthickness=0)
        sb = tk.Scrollbar(list_outer, orient="vertical", command=canvas.yview)
        self._results_list_inner = tk.Frame(canvas, bg=PANEL)
        self._results_list_inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=self._results_list_inner, anchor="nw")
        self._bind_canvas_window_width(canvas, window_id, pad_x=4)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def _on_enter(_e=None, c=canvas):
            c.bind_all("<MouseWheel>",
                       lambda ev: c.yview_scroll(-1 * (ev.delta // 120), "units"))
        def _on_leave(_e=None, c=canvas):
            try: c.unbind_all("<MouseWheel>")
            except Exception: pass
        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)

        self._results_list_canvas = canvas
        self._results_build_list_items()

    @timed_legacy_switch("results_list")
    def _results_build_list_items(self):
        if self._results_list_inner is None:
            return
        for w in self._results_list_inner.winfo_children():
            try: w.destroy()
            except Exception: pass

        self._results_item_widgets = {}
        for list_idx, trade_idx in enumerate(self._results_filtered):
            t = self._results_trades[trade_idx]
            is_win = t.get("result") == "WIN"
            is_long = t.get("direction") == "BULLISH"
            side = "LONG" if is_long else "SHORT"
            result = "WIN" if is_win else "LOSS"
            pnl = float(t.get("pnl", 0) or 0)
            active = list_idx == self._results_active_idx
            bg = BG3 if active else PANEL

            row = tk.Frame(self._results_list_inner, bg=bg, cursor="hand2")
            row.pack(fill="x")

            accent = tk.Frame(row, bg=AMBER if active else PANEL, width=3)
            accent.pack(side="left", fill="y")

            body = tk.Frame(row, bg=bg)
            body.pack(side="left", fill="x", expand=True, padx=6, pady=4)

            head = tk.Label(body, text=f"#{trade_idx + 1}", font=(FONT, 7),
                            fg=DIM, bg=bg, anchor="w")
            head.pack(fill="x")

            sym_short = str(t.get("symbol", "?")).replace("USDT", "")
            mid = tk.Label(body, text=sym_short, font=(FONT, 10, "bold"),
                           fg=AMBER, bg=bg, anchor="w")
            mid.pack(fill="x")

            srl = tk.Label(body, text=f"{side} {result}",
                           font=(FONT, 7, "bold"),
                           fg=GREEN if is_win else RED, bg=bg, anchor="w")
            srl.pack(fill="x")

            pnl_l = tk.Label(body,
                             text=f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",
                             font=(FONT, 9, "bold"),
                             fg=GREEN if pnl >= 0 else RED, bg=bg, anchor="w")
            pnl_l.pack(fill="x")

            def _click(_e=None, idx=trade_idx):
                if idx in self._results_filtered:
                    self._results_active_idx = self._results_filtered.index(idx)
                self._results_inspect(idx)

            widgets = (row, accent, body, head, mid, srl, pnl_l)
            for w in widgets:
                w.bind("<Button-1>", _click)
            self._results_item_widgets[list_idx] = (row, accent, body,
                                                    [head, mid, srl, pnl_l])

    def _results_repaint_list(self):
        for list_idx, (row, accent, body, labels) in self._results_item_widgets.items():
            active = list_idx == self._results_active_idx
            bg = BG3 if active else PANEL
            try:
                row.configure(bg=bg)
                accent.configure(bg=AMBER if active else PANEL)
                body.configure(bg=bg)
                for l in labels:
                    l.configure(bg=bg)
            except Exception:
                pass
        # Scroll the active item into view
        canvas = self._results_list_canvas
        if canvas is not None and self._results_filtered:
            try:
                n = len(self._results_filtered)
                frac = self._results_active_idx / max(n - 1, 1)
                canvas.yview_moveto(max(0.0, frac - 0.15))
            except Exception:
                pass

    def _results_filter_set(self, kind):
        self._results_filter = kind
        trades = self._results_trades
        if kind == "win":
            self._results_filtered = [i for i, t in enumerate(trades)
                                      if t.get("result") == "WIN"]
        elif kind == "loss":
            self._results_filtered = [i for i, t in enumerate(trades)
                                      if t.get("result") == "LOSS"]
        else:
            self._results_filtered = list(range(len(trades)))
        self._results_active_idx = 0
        self._results_render_tab("trades")

    def _results_next_trade(self):
        if self._results_tab != "trades" or not self._results_filtered:
            return
        n = len(self._results_filtered)
        self._results_active_idx = (self._results_active_idx + 1) % n
        self._results_inspect(self._results_filtered[self._results_active_idx])

    def _results_prev_trade(self):
        if self._results_tab != "trades" or not self._results_filtered:
            return
        n = len(self._results_filtered)
        self._results_active_idx = (self._results_active_idx - 1) % n
        self._results_inspect(self._results_filtered[self._results_active_idx])

    def _results_inspect(self, trade_idx):
        if trade_idx < 0 or trade_idx >= len(self._results_trades):
            return
        trade = self._results_trades[trade_idx]
        self._results_render_chart(trade)
        self._results_render_data_panel(trade)
        self._results_repaint_list()
        self._results_update_nav()

    def _results_update_nav(self):
        if self._results_counter is not None:
            try:
                n = len(self._results_filtered)
                pos = self._results_active_idx + 1 if n else 0
                self._results_counter.configure(text=f"{pos} / {n}")
            except Exception: pass
        if self._results_stats is not None:
            try:
                trades = [self._results_trades[i] for i in self._results_filtered]
                total = len(trades)
                wins = sum(1 for t in trades if t.get("result") == "WIN")
                wr = (wins / total * 100) if total else 0
                pnl = sum(float(t.get("pnl", 0) or 0) for t in trades)
                sharpe = self._results_data.get("summary", {}).get("sharpe") or 0
                self._results_stats.configure(
                    text=f"WR {wr:.1f}%   PnL ${pnl:+,.0f}   Sharpe {sharpe:.2f}")
            except Exception: pass

    # -- CHART RENDER (matplotlib via FigureCanvasTkAgg) --
    @timed_legacy_switch("results_chart")
    def _results_render_chart(self, trade):
        # Destroy previous canvas (releases the Figure)
        for w in self._results_chart_frame.winfo_children():
            try: w.destroy()
            except Exception: pass
        self._results_canvas = None

        sym = trade.get("symbol", "")
        ohlc = self._price_data.get(sym) if self._price_data else None
        if not ohlc or "close" not in ohlc:
            tk.Label(self._results_chart_frame,
                     text="OHLC data não disponível para este run",
                     font=(FONT, 9), fg=DIM, bg="#0d1117").pack(expand=True)
            return

        try:
            # Import locally so the launcher only loads matplotlib when
            # the Trade Inspector is actually used.
            from matplotlib.figure import Figure
            from matplotlib.patches import Rectangle
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        except Exception as e:
            tk.Label(self._results_chart_frame,
                     text=f"matplotlib indisponível: {e}",
                     font=(FONT, 9), fg=RED, bg="#0d1117").pack(expand=True)
            return

        idx = int(trade.get("entry_idx", 0) or 0)
        dur = max(1, int(trade.get("duration", 1) or 1))
        total = len(ohlc["close"])
        start = max(0, idx - 30)
        end   = min(total, idx + dur + 15)
        if end - start < 2:
            tk.Label(self._results_chart_frame, text="Janela OHLC insuficiente",
                     font=(FONT, 9), fg=DIM, bg="#0d1117").pack(expand=True)
            return

        o = ohlc["open"][start:end]
        h = ohlc["high"][start:end]
        l = ohlc["low"][start:end]
        c = ohlc["close"][start:end]
        n = len(c)

        fig = Figure(figsize=(8, 3.6), dpi=90, facecolor="#0d1117")
        ax = fig.add_subplot(111, facecolor="#0d1117")

        # Candlesticks
        for i in range(n):
            oi, hi, li, ci = o[i], h[i], l[i], c[i]
            col = "#26d47c" if ci >= oi else "#e85d5d"
            ax.plot([i, i], [li, hi], color=col, linewidth=0.8)
            body_lo = min(oi, ci)
            body_hi = max(oi, ci)
            body_h  = max(body_hi - body_lo, (hi - li) * 0.02 if hi > li else 0)
            ax.add_patch(Rectangle(
                (i - 0.35, body_lo), 0.7, body_h,
                facecolor=col, edgecolor=col, linewidth=0.5))

        local_entry = idx - start
        local_exit  = min(idx + dur - start, n - 1)

        entry_p  = float(trade.get("entry", 0) or 0)
        stop_p   = float(trade.get("stop", entry_p) or entry_p)
        target_p = float(trade.get("target", entry_p) or entry_p)
        exit_p   = float(trade.get("exit_p", entry_p) or entry_p)

        ax.axhline(entry_p,  color="#C8C8C8", linewidth=1.2)
        ax.axhline(stop_p,   color="#e85d5d", linewidth=1.0, linestyle="--")
        ax.axhline(target_p, color="#26d47c", linewidth=1.0, linestyle="--")
        ax.axhline(exit_p,   color="#ffffff", linewidth=0.8, linestyle=":", alpha=0.7)

        is_win  = trade.get("result") == "WIN"
        is_long = trade.get("direction") == "BULLISH"
        shade = "#26d47c" if is_win else "#e85d5d"
        ax.axvspan(local_entry, local_exit, alpha=0.06, color=shade)

        # Entry arrow (points toward stop)
        dy = (stop_p - entry_p) * 0.6
        try:
            ax.annotate("",
                        xy=(local_entry, entry_p),
                        xytext=(local_entry, entry_p + dy),
                        arrowprops=dict(arrowstyle="->", color="#C8C8C8", lw=2))
        except Exception:
            pass

        # Exit marker
        exit_color = "#26d47c" if is_win else "#e85d5d"
        ax.plot(local_exit, exit_p, "o", color=exit_color,
                markersize=8, zorder=5)

        # Right-side labels
        x_lbl = n + 0.5
        ax.text(x_lbl, entry_p,  f"E {entry_p:.4f}", fontsize=7,
                color="#C8C8C8", va="center", fontfamily="monospace")
        ax.text(x_lbl, stop_p,   f"S {stop_p:.4f}",  fontsize=7,
                color="#e85d5d", va="center", fontfamily="monospace")
        ax.text(x_lbl, target_p, f"T {target_p:.4f}", fontsize=7,
                color="#26d47c", va="center", fontfamily="monospace")
        ax.text(x_lbl, exit_p,   f"X {exit_p:.4f}",  fontsize=7,
                color="#ffffff", va="center", fontfamily="monospace", alpha=0.7)

        ax.tick_params(colors="#8b949e", labelsize=7)
        for spine in ax.spines.values():
            spine.set_color("#1b2028")
        ax.grid(True, color="#1b2028", linestyle="--", alpha=0.3)
        ax.set_xlim(-1, n + 7)

        side   = "LONG" if is_long else "SHORT"
        result = trade.get("result", "?")
        pnl    = float(trade.get("pnl", 0) or 0)
        score  = float(trade.get("score", 0) or 0)
        fig.suptitle(
            f"{sym}  {side}  {result}  ${pnl:+,.2f}  O={score:.3f}",
            fontsize=10, color="#C8C8C8",
            fontfamily="monospace", fontweight="bold")

        fig.subplots_adjust(left=0.09, right=0.88, top=0.90, bottom=0.12)
        fig.text(0.88, 0.02, "AURUM · CITADEL",
                 fontsize=7, color="#1b2028",
                 fontfamily="monospace", ha="right")

        canvas = FigureCanvasTkAgg(fig, master=self._results_chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        # Keep reference so gc doesn't collect the figure while it's visible
        self._results_canvas = canvas

    @timed_legacy_switch("results_data")
    def _results_render_data_panel(self, trade):
        for w in self._results_data_panel.winfo_children():
            try: w.destroy()
            except Exception: pass

        inner = tk.Frame(self._results_data_panel, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=12, pady=8)

        tk.Label(inner, text="TRADE DATA", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x")
        tk.Frame(inner, bg=DIM2, height=1).pack(fill="x", pady=(2, 6))

        entry   = float(trade.get("entry", 0) or 0)
        stop    = float(trade.get("stop", 0) or 0)
        exit_p  = float(trade.get("exit_p", 0) or 0)
        target  = float(trade.get("target", 0) or 0)
        pnl     = float(trade.get("pnl", 0) or 0)
        is_long = trade.get("direction") == "BULLISH"
        risk    = abs(entry - stop)
        if risk > 0:
            move = (exit_p - entry) if is_long else (entry - exit_p)
            rmult = move / risk
        else:
            rmult = 0.0
        pnl_col = GREEN if pnl >= 0 else RED
        rm_col  = GREEN if rmult >= 0 else RED

        grid = tk.Frame(inner, bg=PANEL); grid.pack(fill="x")

        fields = [
            ("Symbol",   str(trade.get("symbol", "?")),              WHITE),
            ("Score O",  f"{float(trade.get('score', 0) or 0):.3f}", AMBER),
            ("Side",     "LONG" if is_long else "SHORT",             WHITE),
            ("Regime",   str(trade.get("macro_bias", "?")),          WHITE),
            ("Entry",    f"${entry:,.4f}",                           WHITE),
            ("Stop",     f"${stop:,.4f}",                            RED),
            ("Exit",     f"${exit_p:,.4f}",                          WHITE),
            ("Target",   f"${target:,.4f}",                          GREEN),
            ("PnL",      f"{'+' if pnl >= 0 else ''}${pnl:,.2f}",    pnl_col),
            ("R-Mult",   f"{rmult:+.2f}R",                           rm_col),
            ("Duration", f"{int(trade.get('duration', 0) or 0)} candles", DIM),
            ("RR Plan",  f"{float(trade.get('rr', 0) or 0):.2f}x",   DIM),
            ("Vol",      str(trade.get("vol_regime", "?")),          DIM),
            ("DD Scale", f"{float(trade.get('dd_scale', 1) or 1):.2f}", DIM),
        ]
        for i, (label, value, col) in enumerate(fields):
            r, c = divmod(i, 2)
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=r, column=c, sticky="w", padx=(0, 24), pady=2)
            tk.Label(cell, text=label, font=(FONT, 7),
                     fg=DIM, bg=PANEL, width=10, anchor="w").pack(side="left")
            tk.Label(cell, text=value, font=(FONT, 9, "bold"),
                     fg=col, bg=PANEL, anchor="w").pack(side="left", padx=4)

        # Omega component bars
        tk.Frame(inner, bg=PANEL, height=10).pack()
        tk.Label(inner, text="O COMPONENTS", font=(FONT, 7, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x")
        tk.Frame(inner, bg=DIM2, height=1).pack(fill="x", pady=(2, 4))

        omega_rows = [
            ("STRUCT",   "omega_struct"),
            ("FLOW",     "omega_flow"),
            ("CASCADE",  "omega_cascade"),
            ("MOMENTUM", "omega_momentum"),
            ("PULLBACK", "omega_pullback"),
        ]
        for name, key in omega_rows:
            val = float(trade.get(key, 0) or 0)
            row = tk.Frame(inner, bg=PANEL); row.pack(fill="x", pady=1)
            tk.Label(row, text=name, font=(FONT, 7), fg=DIM, bg=PANEL,
                     width=10, anchor="w").pack(side="left")
            bar_bg = tk.Frame(row, bg=BG3, height=8, width=160)
            bar_bg.pack(side="left", padx=4)
            bar_bg.pack_propagate(False)
            fill_w = max(1, int(160 * min(max(val, 0.0), 1.0)))
            tk.Frame(bar_bg, bg=AMBER, height=8, width=fill_w).pack(side="left")
            tk.Label(row, text=f"{val:.2f}", font=(FONT, 7, "bold"),
                     fg=WHITE, bg=PANEL).pack(side="left", padx=6)

    def _open_file(self, path):
        # timeout=5 so a stuck ``open`` / ``xdg-open`` (e.g. DE not responding,
        # file on a slow mount) never freezes the whole launcher UI.
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], timeout=5)
            else:
                subprocess.run(["xdg-open", str(path)], timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass

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
            self._bsk_preview_count.configure(text=f" {count} ATIVOS ")
            self._bsk_preview_lbl.configure(text=asset_str)
        else:
            self._bsk_preview_count.configure(text="")
            self._bsk_preview_lbl.configure(text="")

    # --- EXECUTE ENGINE ----------------------------------
    def _exec(self, name, script, desc, parent_menu, auto_inputs, cli_args=None):
        self._clr(); self._clear_kb()
        self._exec_parent = parent_menu  # save for results screen
        self.oq = queue.Queue()
        is_bt = parent_menu == "backtest"
        self.h_path.configure(text=f"> {parent_menu.upper()} > {name}")
        self.h_stat.configure(text="RODANDO", fg=GREEN)
        self.f_lbl.configure(
            text="M mapa de install  |  C console runtime  |  ENTER enviar  |  vazio = aceitar padrão"
            if is_bt else
            "Digite abaixo + ENTER  |  vazio = aceitar padrão"
        )

        f = tk.Frame(self.main, bg=BG); f.pack(fill="both", expand=True)

        # Top bar
        top = tk.Frame(f, bg=BG2); top.pack(fill="x")
        tk.Label(top, text=f" {name} ", font=(FONT, 8, "bold"), fg=BG, bg=AMBER).pack(side="left", padx=6, pady=3)
        tk.Label(top, text=desc, font=(FONT, 8), fg=DIM, bg=BG2, padx=6).pack(side="left", pady=3)

        tk.Button(top, text=" STOP ", font=(FONT, 7, "bold"), fg=WHITE, bg=BG2, border=0, cursor="hand2",
                  activeforeground=WHITE, activebackground=BG3, command=self._stop).pack(side="right", padx=4, pady=3)
        tk.Button(top, text=" BACK ", font=(FONT, 7, "bold"), fg=WHITE, bg=BG2, border=0, cursor="hand2",
                  activeforeground=WHITE, activebackground=BG3,
                  command=lambda: (self._stop(), self._menu(parent_menu))).pack(side="right", pady=3)
        if is_bt:
            tk.Button(top, text=" CMD ", font=(FONT, 7, "bold"), fg=WHITE, bg=BG2, border=0, cursor="hand2",
                      activeforeground=WHITE, activebackground=BG3,
                      command=lambda: self._exec_show_view("console")).pack(side="right", padx=(0, 4), pady=3)
            tk.Button(top, text=" MAPA ", font=(FONT, 7, "bold"), fg=WHITE, bg=BG2, border=0, cursor="hand2",
                      activeforeground=WHITE, activebackground=BG3,
                      command=lambda: self._exec_show_view("visual")).pack(side="right", padx=(0, 4), pady=3)

        tk.Frame(f, bg=AMBER_D, height=1).pack(fill="x")

        body = tk.Frame(f, bg=BG)
        body.pack(fill="both", expand=True)
        self._exec_body = body

        if is_bt:
            self._exec_visual = tk.Frame(body, bg=BG)
            self._exec_visual.pack(fill="both", expand=True)
            self._exec_init_progress_ui(self._exec_visual, name, desc)
        else:
            self._exec_visual = None

        # Console
        cf = tk.Frame(body, bg=PANEL)
        if not is_bt:
            cf.pack(fill="both", expand=True)
        self._exec_console = cf
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
        if is_bt:
            self._exec_show_view("visual")
            self._kb("<Key-c>", lambda: self._exec_show_view("console"))
            self._kb("<Key-m>", lambda: self._exec_show_view("visual"))

        # Input bar
        tk.Frame(f, bg=AMBER, height=1).pack(fill="x")
        ib = tk.Frame(f, bg=BG2, height=34); ib.pack(fill="x"); ib.pack_propagate(False)

        self._inp_lbl = tk.Label(ib, text=" ENTRADA ", font=(FONT, 7, "bold"), fg=BG, bg=AMBER)
        self._inp_lbl.pack(side="left", padx=(6,4), pady=5)

        tk.Label(ib, text=">", font=(FONT, 10, "bold"), fg=AMBER, bg=BG2).pack(side="left")
        self.inp = tk.Entry(ib, bg=BG3, fg=WHITE, font=(FONT, 10), insertbackground=AMBER,
                             border=0, highlightthickness=1, highlightcolor=AMBER_D, highlightbackground=BORDER)
        self.inp.pack(side="left", fill="x", expand=True, padx=4, pady=5, ipady=1)
        self.inp.focus_set()
        self.inp.bind("<Return>", self._send)
        if is_bt:
            self.inp.configure(state="disabled")

        tk.Label(
            ib,
            text="BACKGROUND MANAGED | live log only" if is_bt else "ENTER send | empty=default",
            font=(FONT, 7), fg=DIM2, bg=BG2
        ).pack(side="right", padx=6)

        # Blink indicator
        self._blink = True
        def blink():
            if not hasattr(self, '_inp_lbl') or not self._inp_lbl.winfo_exists(): return
            if self._exec_is_running():
                self._blink = not self._blink
                self._inp_lbl.configure(bg=AMBER if self._blink else BG2, fg=BG if self._blink else AMBER)
            else:
                self._inp_lbl.configure(text=" DONE ", bg=DIM2, fg=DIM)
            self.after(500, blink)
        blink()

        # Print header
        self._p(f" {name}  {desc}  {datetime.now().strftime('%H:%M:%S')}\n", "a")
        self._p("-"*60 + "\n", "d")

        # Launch
        path = ROOT / script
        if not path.exists():
            self._p(f"ERROR: {path} not found\n", "r"); return

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"; env["PYTHONUTF8"] = "1"
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0

        try:
            if is_bt:
                proc_key = self._exec_script_to_proc_key(script)
                if proc_key is None:
                    self._p(f"FAILED: background mapping not found for {script}\n", "r")
                    return
                # Spawn off the UI thread — Popen on Windows takes 100-500ms
                # to create a Python subprocess; doing it inline freezes the
                # window. Worker spawns then marshals back to main via after().
                self.h_stat.configure(text="STARTING…", fg=AMBER)
                self._p(f"  spawning {name} in background…\n", "d")

                def _spawn_worker(_proc_key=proc_key,
                                  _inputs=auto_inputs,
                                  _cli=cli_args,
                                  _name=name):
                    try:
                        from core.ops.proc import spawn as _spawn
                        info = _spawn(_proc_key,
                                      stdin_lines=_inputs or None,
                                      cli_args=_cli or None)
                    except Exception as exc:
                        info = None
                        err = f"{type(exc).__name__}: {exc}"
                    else:
                        err = None

                    def _apply(_info=info, _err=err, _name2=_name):
                        if _info is None:
                            self.h_stat.configure(text="FAILED", fg=RED)
                            if _err:
                                self._p(f"FAILED: {_err}\n", "r")
                            else:
                                self._p(f"FAILED: {_name2} already running or could not start\n", "r")
                                self._p("Open TERMINAL > ENGINE LOGS to inspect existing managed runs.\n", "d")
                            return
                        self._exec_managed_info = _info
                        self.h_stat.configure(text="BACKGROUND", fg=GREEN)
                        self._p(f"  managed pid {_info['pid']}  ·  background active\n", "g")
                        self._p(f"  log {_info['log_file']}\n", "d")
                        threading.Thread(
                            target=self._read_managed_log,
                            args=(Path(_info["log_file"]), _info),
                            daemon=True,
                        ).start()
                        self._poll()
                    try:
                        self.after(0, _apply)
                    except (RuntimeError, tk.TclError):
                        pass

                threading.Thread(target=_spawn_worker, daemon=True).start()
                return

            _cmd = [preferred_python_executable(), "-X", "utf8", "-u", str(path)]
            if cli_args:
                _cmd.extend(cli_args)

            # Same UI-freeze concern as background spawn — Popen blocks the
            # main loop. Move the spawn off the UI thread.
            self.h_stat.configure(text="STARTING…", fg=AMBER)

            def _fg_spawn_worker(_cmd_=_cmd, _env=env, _si=si,
                                 _inputs=auto_inputs):
                try:
                    proc = subprocess.Popen(
                        _cmd_, cwd=str(ROOT),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        stdin=subprocess.PIPE,
                        text=True, bufsize=1, encoding="utf-8", errors="replace",
                        startupinfo=_si, creationflags=subprocess.CREATE_NO_WINDOW,
                        env=_env)
                except Exception as exc:
                    err_msg = f"{type(exc).__name__}: {exc}"
                    def _fail(msg=err_msg):
                        self.h_stat.configure(text="FAILED", fg=RED)
                        self._p(f"FAILED: {msg}\n", "r")
                    try: self.after(0, _fail)
                    except Exception: pass
                    return

                def _attach(p=proc, _ins=_inputs):
                    self.proc = p
                    self.h_stat.configure(text="RODANDO", fg=GREEN)
                    threading.Thread(target=self._read, daemon=True).start()
                    self._poll()
                    if _ins:
                        def _auto(p=p, ins=_ins):
                            time.sleep(0.8)
                            for val in ins:
                                if p and p.poll() is None and p.stdin:
                                    try:
                                        p.stdin.write(val + "\n")
                                        p.stdin.flush()
                                        time.sleep(0.4)
                                    except Exception:
                                        break
                        threading.Thread(target=_auto, daemon=True).start()
                try: self.after(0, _attach)
                except Exception: pass

            threading.Thread(target=_fg_spawn_worker, daemon=True).start()

        except Exception as e:
            self._exec_progress_target = self._exec_progress_value
            if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                self._exec_stage_label.configure(text="launcher failed to start process")
            self._p(f"FAILED: {e}\n", "r")

    def _exec_script_to_proc_key(self, script: str) -> str | None:
        return _script_to_proc_key(script)

    def _exec_is_running(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        info = getattr(self, "_exec_managed_info", None)
        if info:
            try:
                from core.ops.proc import _is_alive
                return _is_alive(int(info["pid"]), expected=info)
            except Exception:
                return False
        return False

    def _exec_init_progress_ui(self, parent, name, desc):
        self._exec_progress_value = 2.0
        self._exec_progress_target = 7.0
        self._exec_progress_pulse = 0
        self._exec_recent_lines = []

        self._exec_progress_last_paint = 0.0
        self._exec_last_feed_at = 0.0

        wrap = tk.Frame(parent, bg=BG, padx=30, pady=26)
        wrap.pack(fill="both", expand=True)

        hdr = tk.Frame(wrap, bg=BG)
        hdr.pack(fill="x", pady=(0, 18))
        tk.Label(hdr, text=name.upper(), font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG).pack(anchor="w")
        tk.Label(hdr, text=f"{name}  ·  institutional build pipeline  ·  {desc}",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=(3, 0))
        tk.Label(hdr, text=desc,
                 font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=(4, 0))

        top = tk.Frame(wrap, bg=BG)
        top.pack(fill="x", pady=(0, 12))

        left = tk.Frame(top, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True)

        left_head = tk.Frame(left, bg=PANEL)
        left_head.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(left_head, text="BACKTEST", font=(FONT, 8, "bold"),
                 fg=BG, bg=AMBER, padx=6, pady=2).pack(side="left")
        self._exec_pct_label = tk.Label(left_head, text="2%", font=(FONT, 12, "bold"),
                                        fg=AMBER_B, bg=PANEL)
        self._exec_pct_label.pack(side="right")

        self._exec_stage_label = tk.Label(left, text="preparing backtest runtime",
                                          font=(FONT, 10, "bold"), fg=WHITE, bg=PANEL,
                                          anchor="w")
        self._exec_stage_label.pack(fill="x", padx=14)
        self._exec_file_label = tk.Label(left, text="waiting for first engine event",
                                         font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w")
        self._exec_file_label.pack(fill="x", padx=14, pady=(4, 8))

        self._exec_bar_canvas = tk.Canvas(left, bg=BG2, highlightthickness=0, height=34)
        self._exec_bar_canvas.pack(fill="x", padx=14, pady=(0, 12))

        hints = tk.Frame(left, bg=PANEL)
        hints.pack(fill="x", padx=14, pady=(0, 12))
        for lbl, txt, col in [
            ("route", "local subprocess attached to launcher runtime", AMBER_D),
            ("view",  "M visual map  ·  C cmd console", DIM),
            ("mode",  "no separate cmd pop-up during backtests", GREEN),
        ]:
            row = tk.Frame(hints, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=lbl.upper(), font=(FONT, 7, "bold"), fg=col, bg=PANEL,
                     width=8, anchor="w").pack(side="left")
            tk.Label(row, text=txt, font=(FONT, 7), fg=WHITE if lbl == "mode" else DIM,
                     bg=PANEL, anchor="w").pack(side="left")

        right = tk.Frame(top, bg=PANEL, width=220, highlightbackground=BORDER, highlightthickness=1)
        right.pack(side="left", fill="both", padx=(12, 0))
        right.pack_propagate(False)

        tk.Label(right, text="LIVE", font=(FONT, 8, "bold"),
                 fg=BG, bg=GREEN, padx=6, pady=2).pack(anchor="nw", padx=12, pady=(12, 8))
        self._exec_recent_labels = []
        for _ in range(2):
            lbl = tk.Label(right, text="",
                           font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w", justify="left",
                           wraplength=235)
            lbl.pack(fill="x", padx=12, pady=2)
            self._exec_recent_labels.append(lbl)

        note = tk.Frame(wrap, bg=BG)
        note.pack(fill="x")
        tk.Label(note, text="Visual by default. Open CMD only when needed.",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w").pack(anchor="w")
        actions = tk.Frame(note, bg=BG)
        actions.pack(anchor="w", pady=(8, 0))
        live_cmd = tk.Label(actions, text="  ABRIR CMD AO VIVO  ", font=(FONT, 8, "bold"),
                            fg=BG, bg=GREEN, cursor="hand2", padx=8, pady=4)
        live_cmd.pack(side="left")
        live_cmd.bind("<Button-1>", lambda e: self._exec_open_live_cmd())
        live_cmd.bind("<Enter>", lambda e: live_cmd.configure(bg="#36d86b"))
        live_cmd.bind("<Leave>", lambda e: live_cmd.configure(bg=GREEN))
        back_map = tk.Label(actions, text="  VOLTAR PRO MAPA  ", font=(FONT, 8),
                            fg=DIM, bg=BG3, cursor="hand2", padx=8, pady=4)
        back_map.pack(side="left", padx=(8, 0))
        back_map.bind("<Button-1>", lambda e: self._exec_show_view("visual"))
        back_map.bind("<Enter>", lambda e: back_map.configure(fg=AMBER))
        back_map.bind("<Leave>", lambda e: back_map.configure(fg=DIM))

        self._exec_progress_tick()

    def _exec_show_view(self, mode):
        self._exec_visual_mode = mode
        visual = getattr(self, "_exec_visual", None)
        console = getattr(self, "_exec_console", None)
        if visual is None or console is None:
            return
        visual.pack_forget()
        console.pack_forget()
        if mode == "console":
            console.pack(fill="both", expand=True)
            self.h_stat.configure(text="CMD VIEW", fg=AMBER_D)
        else:
            visual.pack(fill="both", expand=True)
            self.h_stat.configure(text="INSTALL MAP", fg=GREEN)

    def _exec_open_live_cmd(self):
        self._exec_show_view("console")
        if hasattr(self, "inp") and self.inp.winfo_exists():
            try:
                self.inp.focus_set()
            except Exception:
                pass

    def _exec_progress_feed(self, clean: str):
        low = clean.strip().lower()
        if not low:
            return

        targets = [
            (("iniciado", "started"), 10, "allocating launch package"),
            (("dados", "fetch", "loading"), 24, "downloading candle archives"),
            (("sentiment", "funding", "open interest", "long/short"), 40, "installing sentiment bundles"),
            (("scan", "scanning"), 58, "building route graph and trade cache"),
            (("total:", "resultados", "wr=", "pnl="), 74, "compiling execution manifests"),
            (("metricas", "metrics", "sharpe", "sortino"), 86, "verifying institutional metrics"),
            (("monte", "walk", "robust", "json"), 94, "packing report artifacts"),
            (("backtest complete", "loading results dashboard"), 100, "installation complete"),
        ]
        for keys, target, stage in targets:
            if any(k in low for k in keys):
                self._exec_progress_target = max(self._exec_progress_target, float(target))
                if self._exec_stage_label is not None:
                    self._exec_stage_label.configure(text=stage)
                break
        else:
            self._exec_progress_target = min(88.0, self._exec_progress_target + 0.2)

        if self._exec_file_label is not None:
            token = low.replace("  ", " ")[:56]
            self._exec_file_label.configure(text=token)

        now = time.monotonic()
        if now - getattr(self, "_exec_last_feed_at", 0.0) < 0.18:
            return
        self._exec_last_feed_at = now

        self._exec_recent_lines.append(clean.strip())
        self._exec_recent_lines = self._exec_recent_lines[-3:]
        tail = "  |  ".join(self._exec_recent_lines[-2:])
        live_lbl = getattr(self, "_exec_live_tail_label", None)
        if live_lbl is not None and live_lbl.winfo_exists():
            live_lbl.configure(text=tail[:180])

        if self._exec_recent_labels:
            first = self._exec_recent_labels[0]
            if first.winfo_exists():
                first.configure(text=tail[:80] or " ", fg=WHITE if tail else DIM)
            for lbl in self._exec_recent_labels[1:]:
                if lbl.winfo_exists():
                    lbl.configure(text=" ", fg=DIM)

    def _exec_progress_tick(self):
        canvas = getattr(self, "_exec_bar_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            self._exec_progress_after_id = None
            return

        if self._exec_is_running():
            self._exec_progress_value = min(
                self._exec_progress_target,
                self._exec_progress_value + max(0.4, (self._exec_progress_target - self._exec_progress_value) * 0.08)
            )
        elif self._exec_progress_target >= 100.0:
            self._exec_progress_value = 100.0
        elif self._exec_progress_value < self._exec_progress_target:
            self._exec_progress_value = min(
                self._exec_progress_target,
                self._exec_progress_value + max(0.8, (self._exec_progress_target - self._exec_progress_value) * 0.2)
            )
        now = time.monotonic()
        if now - getattr(self, "_exec_progress_last_paint", 0.0) < 0.12:
            self._exec_progress_after_id = self.after(120, self._exec_progress_tick)
            return
        self._exec_progress_last_paint = now

        self._exec_progress_pulse = (self._exec_progress_pulse + 5) % 300
        pct = max(0, min(100, int(round(self._exec_progress_value))))

        w = max(canvas.winfo_width(), 10)
        h = max(canvas.winfo_height(), 10)
        pad = 2
        bar_w = w - pad * 2
        fill_w = int(bar_w * (pct / 100))

        canvas.delete("all")
        canvas.create_rectangle(pad, pad, w - pad, h - pad, outline=BORDER, width=1, fill=BG2)
        if fill_w > 0:
            canvas.create_rectangle(pad + 1, pad + 1, pad + fill_w, h - pad - 1,
                                    outline="", fill=GREEN)
            shine_x = pad + (self._exec_progress_pulse % max(fill_w, 16))
            canvas.create_rectangle(max(pad + 1, shine_x - 6), pad + 1,
                                    min(pad + fill_w, shine_x + 6), h - pad - 1,
                                    outline="", fill=AMBER_B)

        if self._exec_pct_label is not None and self._exec_pct_label.winfo_exists():
            self._exec_pct_label.configure(text=f"{pct}%")

        if self._exec_is_running() or self._exec_progress_value < self._exec_progress_target:
            self._exec_progress_after_id = self.after(140, self._exec_progress_tick)
        else:
            self._exec_progress_after_id = None

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

    def _read_managed_log(self, log_path: Path, info: dict):
        from core.ops.proc import _is_alive

        last = 0
        while True:
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(last)
                    chunk = f.read()
                    last = f.tell()
                if chunk:
                    for line in chunk.splitlines(True):
                        self.oq.put(line)
            except OSError:
                pass

            if not _is_alive(int(info["pid"]), expected=info):
                time.sleep(0.2)
                try:
                    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(last)
                        chunk = f.read()
                    if chunk:
                        for line in chunk.splitlines(True):
                            self.oq.put(line)
                except OSError:
                    pass
                break
            time.sleep(0.15)

        self.oq.put(None)

    def _poll(self):
        try:
            for _ in range(32):
                line = self.oq.get_nowait()
                if line is None:
                    rc = self.proc.poll() if self.proc else -1
                    if self._exec_managed_info is not None:
                        rc = 0
                    self._exec_progress_target = 100.0
                    if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                        self._exec_stage_label.configure(
                            text="installation complete" if rc == 0 else f"installation failed  ·  exit {rc}"
                        )
                    self._p(f"\n{'-'*60}\n", "d")
                    self._p(f"  EXIT {rc}\n", "g" if rc == 0 else "r")
                    self.h_stat.configure(text="DONE" if rc == 0 else f"EXIT {rc}", fg=GREEN if rc == 0 else RED)
                    self.proc = None
                    self._exec_managed_info = None
                    # Show results dashboard for backtests
                    parent = getattr(self, '_exec_parent', 'main')
                    if parent == "backtest" and rc == 0:
                        self._p("\n  >> BACKTEST COMPLETE — loading results dashboard...\n", "a")
                        self.after(2000, lambda: self._try_results(parent))
                    return
                self._p(line)
        except queue.Empty: pass
        self.after(80 if self._exec_is_running() else 140, self._poll)

    def _p(self, text, tag="w"):
        import re
        # Strip ANSI escape codes for clean output
        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', text)
        if hasattr(self, "con") and self.con.winfo_exists():
            self.con.configure(state="normal")
            self.con.insert("end", clean, tag)
            self.con.see("end")
            self.con.configure(state="disabled")
        if getattr(self, "_exec_visual", None) is not None:
            self._exec_progress_feed(clean)

    def _stop(self):
        if self.proc and self.proc.poll() is None:
            self._exec_progress_target = max(self._exec_progress_target, self._exec_progress_value)
            if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                self._exec_stage_label.configure(text="operator stopped installation")
            self._p("\n  >> SIGTERM\n", "r")
            self.proc.terminate()
            try: self.proc.wait(timeout=5)
            except: self.proc.kill()
            self._p("  >> STOPPED\n", "r")
            self.h_stat.configure(text="STOPPED", fg=RED)
            self.proc = None
        elif self._exec_managed_info is not None:
            self._exec_progress_target = max(self._exec_progress_target, self._exec_progress_value)
            if self._exec_stage_label is not None and self._exec_stage_label.winfo_exists():
                self._exec_stage_label.configure(text="operator stopped installation")
            try:
                from core.ops.proc import stop_proc
                stop_proc(int(self._exec_managed_info["pid"]), expected=self._exec_managed_info)
                self._p(f"\n  >> BACKGROUND STOP {self._exec_managed_info['pid']}\n", "r")
            except Exception as e:
                self._p(f"\n  >> STOP FAILED: {e}\n", "r")
            self.h_stat.configure(text="STOPPED", fg=RED)
            self._exec_managed_info = None

    # --- MARKETS (Layer 2) -------------------------------
    # --- MARKET ROUTES — direct entries from MARKETS tile ---------
    def _market_route(self, market_key: str) -> None:
        """Activate `market_key` and route to its dashboard. Stubs (not yet
        wired) show COMING SOON in h_stat instead of crashing."""
        _CM, _MARKETS = _lazy_connections()
        info = _MARKETS.get(market_key, {})
        label = info.get("label", market_key.upper())
        if not info.get("available"):
            self.h_stat.configure(text=f"{label} · COMING SOON", fg=AMBER_D)
            try:
                messagebox.showinfo(
                    f"{label}",
                    f"{label} ainda não está disponível.\n\n"
                    f"Pendente: integração com {info.get('exchanges', [])}.",
                )
            except Exception:
                pass
            return
        try:
            _get_conn().active_market = market_key
        except Exception:
            pass
        # Crypto futures has its own dashboard; others fall back to _markets
        if market_key == "crypto_futures":
            self._crypto_dashboard()
        else:
            self._markets()

    def _market_crypto_futures(self): self._market_route("crypto_futures")
    def _market_crypto_spot(self):    self._market_route("crypto_spot")
    def _market_forex(self):          self._market_route("forex")
    def _market_equities(self):       self._market_route("equities")
    def _market_commodities(self):    self._market_route("commodities")
    def _market_indices(self):        self._market_route("indices")
    def _market_onchain(self):        self._market_route("onchain")

    def _markets(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("markets")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- CONNECTIONS (Layer 2) ----------------------------
    def _connections(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("connections")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- ARBITRAGE (Layer 2) ------------------------------
    def _alchemy_enter(self):
        """Redirect to the unified ARBITRAGE DESK (engine tab).

        The old 9-panel ALCHEMY cockpit has been consolidated into the
        tabbed desk. All JANE STREET controls, risk gauges and log tail
        now live in the ENGINE tab of _arbitrage_hub. Keeping this
        method as a thin redirect so existing entry points (main menu,
        legacy shortcuts) still work.
        """
        self._arbitrage_hub(tab="engine")

    def _alchemy_exit(self, event=None):
        """Exit the cockpit. Confirm if engine is running."""
        if self.proc and self.proc.poll() is None:
            from tkinter import messagebox
            if not messagebox.askyesno(
                "ARBITRAGE",
                "Engine is still running. Stop it before exiting?",
                parent=self):
                return
            self._stop()

        try:
            self._alch_tick.stop()
        except Exception:
            pass
        try:
            self.unbind("<Escape>")
        except Exception:
            pass

        self._menu("main")

    # ---------------------------------------------------------------
    # ARBITRAGE HUB — MP3-style router
    # Five legs of funding/basis arbitrage, one minimalist menu:
    #   C  CEX ↔ CEX  → JANE STREET cockpit (execution)
    #   D  DEX ↔ DEX  → funding scanner (observation)
    #   X  CEX ↔ DEX  → funding scanner (observation)
    #   B  BASIS TRADE → spot-perp basis screen
    #   S  SPOT ↔ SPOT → cross-venue spot spread screen
    # ---------------------------------------------------------------
    _ARB_HUB_ITEMS = [
        ("C", "CEX  \u2194  CEX",
         "jane street execution cockpit",
         "_alchemy_enter"),
        ("D", "DEX  \u2194  DEX",
         "pure cross-dex funding spread",
         ("_funding_scanner_screen", "dex-dex")),
        ("X", "CEX  \u2194  DEX",
         "cex/dex spread  \u2014  biggest apr",
         ("_funding_scanner_screen", "cex-dex")),
        ("B", "BASIS  TRADE",
         "spot-perp basis  \u00b7  execution ready",
         "_arb_basis_screen"),
        ("S", "SPOT  \u2194  SPOT",
         "cross-venue spot spread",
         "_arb_spot_screen"),
    ]

    # --------------------------------------------------------------
    # ARBITRAGE DESK — unified tabbed view
    # Single entry point for everything arbitrage-related. Internal tabs
    # cover all modes (CEX-CEX, DEX-DEX, CEX-DEX, BASIS, SPOT) plus the
    # JANE STREET engine control panel. Replaces the old row-menu hub,
    # _arb_basis_screen, _arb_spot_screen, and _funding_scanner_screen
    # (those stay as thin redirects for back-compat).
    # --------------------------------------------------------------

    _ARB_TAB_DEFS = [
        # (key, tab_id, label, color) — collapsed 6→3 tabs in Phase 1
        # redesign (2026-04-22). All legacy tab ids route into these.
        ("1", "opps",      "OPPS",       "#ffd700"),
        ("2", "positions", "POSITIONS",  "#00ff80"),
        ("3", "history",   "HISTORY",    "#c084fc"),
    ]

    # Legacy 6-tab ids routed into the new 3-tab layout (Phase 1 redesign).
    _ARB_LEGACY_TAB_MAP = {
        "cex-cex": "opps", "dex-dex": "opps", "cex-dex": "opps",
        "basis": "opps", "spot": "opps",
        "engine": "positions",
    }

    def _arbitrage_hub(self, tab: str = "opps"):
        """Delegate to launcher_support.screens.arbitrage_hub.render.
        Full hub (status strip + tab strip + content area + scanner +
        refresh loop) lives there. Tab renderers (_arb_render_*) stay
        on App and are dispatched via the app parameter.
        """
        # Route legacy tab ids to their new home
        tab = self._ARB_LEGACY_TAB_MAP.get(tab, tab)
        # Speed: if already on the requested tab with live widgets, just
        # repaint from cache instead of tearing down and rebuilding the
        # whole shell (status strip, tab strip, etc.). Saves ~40 widget
        # destroys + re-creates per tab click.
        current = getattr(self, "_arb_tab", None)
        labels = getattr(self, "_arb_tab_labels", None)
        if current == tab and labels:
            try:
                first = next(iter(labels.values()), None)
                if first is not None and first.winfo_exists():
                    self._arb_rerender_current_tab()
                    return
            except Exception:
                pass
        from launcher_support.screens.arbitrage_hub import render as _render_arbitrage_hub
        _render_arbitrage_hub(self, tab=tab)

    # -- Auto-refresh loop -------------------------------------
    def _arb_schedule_refresh(self, delay_ms: int = 15_000):
        """Re-scan every delay_ms while the arbitrage desk is on screen.

        We identify "on screen" by checking that self._arb_tab_labels still
        exists and isn't destroyed — the moment the user leaves the hub
        (back to main menu, another page), that dict is replaced or the
        widgets are gone, and the scheduled tick no-ops instead of trying
        to repaint dead Tk widgets.
        """
        try:
            # Cancel previous pending refresh if any
            prev = getattr(self, "_arb_refresh_after", None)
            if prev:
                try:
                    self.after_cancel(prev)
                except Exception:
                    pass
            def _tick():
                labels = getattr(self, "_arb_tab_labels", None)
                if not labels:
                    return
                first = next(iter(labels.values()), None)
                try:
                    if first is None or not first.winfo_exists():
                        return
                except Exception:
                    return
                # Skip network fetch if scanner cache is still fresh —
                # triggered when a manual R-refresh or tab switch already
                # kicked a scan a few seconds ago.
                if not self._arb_scan_is_fresh():
                    self._arb_hub_scan_async()
                self._arb_refresh_after = self.after(delay_ms, _tick)
            self._arb_refresh_after = self.after(delay_ms, _tick)
        except Exception:
            pass

    def _arb_schedule_clock(self):
        """Tick every second — updates scan staleness + engine pill."""
        def _tick():
            # Short-circuit if status strip widgets gone (user left hub)
            scan_lbl = getattr(self, "_arb_scan_age", None)
            if scan_lbl is None:
                return
            try:
                if not scan_lbl.winfo_exists():
                    return
                self._arb_update_status_strip()
                self.after(1000, _tick)
            except Exception:
                pass
        try:
            self.after(1000, _tick)
        except Exception:
            pass

    def _arb_update_status_strip(self):
        """Refresh scan staleness + engine pill in the hub status strip."""
        import time as _time
        # Scan staleness
        scan_lbl = getattr(self, "_arb_scan_age", None)
        if scan_lbl is not None:
            try:
                last = getattr(self, "_arb_last_scan_ts", 0) or 0
                if last > 0:
                    age = int(_time.time() - last)
                    if age < 60:
                        txt, fg = f"SCAN {age}s ago", GREEN if age <= 20 else AMBER
                    else:
                        txt, fg = f"SCAN {age // 60}m ago", RED
                else:
                    txt, fg = "SCAN —", DIM
                scan_lbl.configure(text=txt, fg=fg)
            except Exception:
                pass
        # Engine pill
        pill = getattr(self, "_arb_engine_pill", None)
        acctlbl = getattr(self, "_arb_engine_acctlbl", None)
        ddlbl = getattr(self, "_arb_engine_ddlbl", None)
        engine = getattr(self, "_arb_simple_engine", None)
        if pill is not None:
            try:
                if engine is not None and engine.running:
                    snap = engine.snapshot()
                    mode = snap.get("mode", "paper").upper()
                    pill.configure(
                        text=f" {mode} RUN ",
                        bg=GREEN if not snap.get("killed") else RED,
                        fg=BG,
                    )
                    if acctlbl is not None:
                        acctlbl.configure(
                            text=f"ACCT ${snap.get('account', 0):,.0f}",
                            fg=WHITE)
                    if ddlbl is not None:
                        dd = float(snap.get("drawdown_pct", 0) or 0)
                        ddlbl.configure(
                            text=f"DD {dd:+.2f}%",
                            fg=RED if dd > 5 else (AMBER if dd > 1 else DIM))
                else:
                    pill.configure(text=" OFF ", bg=DIM, fg=BG)
                    if acctlbl is not None:
                        acctlbl.configure(text="", fg=DIM)
                    if ddlbl is not None:
                        ddlbl.configure(text="", fg=DIM)
            except Exception:
                pass

    # -- Table helper used by every tab -------------------------
    def _arb_make_table(self, parent, cols: list[tuple[str, int, str]],
                         on_click=None):
        """Build a grid-aligned header + body. Returns (body_frame, repaint_fn).

        cols: list of (label, width_chars, anchor). Header and body share the
        same grid column configuration, so cells stay perfectly aligned no
        matter the row content. Previous pack-based implementation drifted
        when cell text lengths varied.

        on_click(row_idx): optional callback fired when the user clicks any
        cell of a body row. Lets each tab attach a detail pane that reacts
        to the selected pair.
        """
        # Header row
        hdr = tk.Frame(parent, bg=BG)
        hdr.pack(fill="x", padx=2)
        for i, (label, w, anchor) in enumerate(cols):
            hdr.grid_columnconfigure(i, minsize=w * 7, weight=0, uniform="arb")
            sticky = "w" if anchor == "w" else "e"
            tk.Label(hdr, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG, anchor=anchor).grid(
                row=0, column=i, sticky=sticky + "ns", padx=3, pady=(0, 2))
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(0, 2))

        # Body uses the same column config so each column lines up to header
        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True, padx=2)
        for i, (_, w, _) in enumerate(cols):
            body.grid_columnconfigure(i, minsize=w * 7, weight=0, uniform="arb")

        # In-place row cache: list of (cells, hover_bg) per current row.
        # repaint() diffs rows against this cache and only mutates cells
        # that actually changed, so a 15s scan refresh doesn't flicker —
        # text just updates like a terminal ticker.
        state = {"rows": [], "placeholder": None}

        def _clear_placeholder():
            if state["placeholder"] is not None:
                state["placeholder"].destroy()
                state["placeholder"] = None

        def _set_placeholder(msg: str):
            # Only replace the message if different — avoid flicker cycles.
            ph = state["placeholder"]
            if ph is not None:
                try:
                    if ph.cget("text") == msg:
                        return
                    ph.configure(text=msg)
                    return
                except Exception:
                    pass
            # Remove any rows first (placeholder = empty state)
            for (cells, _) in state["rows"]:
                for c in cells:
                    c.destroy()
            state["rows"] = []
            state["placeholder"] = tk.Label(
                body, text=msg, font=(FONT, 8),
                fg=DIM2, bg=BG, justify="center")
            state["placeholder"].grid(
                row=0, column=0, columnspan=len(cols), pady=16)

        def _make_row(ri: int, row, bg_row: str):
            cells = []
            for ci, ((txt, fg), (_, _, anchor)) in enumerate(zip(row, cols)):
                sticky = "w" if anchor == "w" else "e"
                cursor = "hand2" if on_click else "arrow"
                cell = tk.Label(body, text=txt, font=(FONT, 8),
                                 fg=fg, bg=bg_row, anchor=anchor,
                                 cursor=cursor)
                cell.grid(row=ri, column=ci,
                          sticky=sticky + "nsew", padx=3, pady=1)
                cells.append(cell)
                if on_click is not None:
                    cell.bind(
                        "<Button-1>", lambda _e, _i=ri: on_click(_i))
            if on_click is not None:
                def _hover_in(_e, cells=cells):
                    for c in cells:
                        c.configure(bg=BG3)
                def _hover_out(_e, cells=cells, bgx=bg_row):
                    for c in cells:
                        c.configure(bg=bgx)
                for c in cells:
                    c.bind("<Enter>", _hover_in)
                    c.bind("<Leave>", _hover_out)
            return cells

        def _update_row(cells, row, bg_row):
            for c, (txt, fg) in zip(cells, row):
                # Only push changes — comparing beforehand keeps Tk from
                # redrawing cells whose text/fg are identical to current.
                try:
                    if c.cget("text") != txt:
                        c.configure(text=txt)
                    if c.cget("fg") != fg:
                        c.configure(fg=fg)
                    if c.cget("bg") != bg_row:
                        c.configure(bg=bg_row)
                except Exception:
                    pass

        def repaint(rows: list[list[tuple[str, str]]]):
            """Diff-update rows in place. No destroy+rebuild on normal
            refresh, so the table reads like a ticker instead of blinking."""
            if not rows:
                has_scan = getattr(self, "_arb_cache", None) is not None
                msg = ("  \u2014 no pairs match current filters \u2014\n"
                       "  click filter chips above to relax"
                       if has_scan else
                       "  \u2014 scanning venues, hold on \u2014")
                _set_placeholder(msg)
                return

            _clear_placeholder()
            # Update existing rows in place where possible
            for ri, row in enumerate(rows):
                bg_row = BG if ri % 2 == 0 else BG2
                if ri < len(state["rows"]):
                    cells, _ = state["rows"][ri]
                    _update_row(cells, row, bg_row)
                    state["rows"][ri] = (cells, bg_row)
                else:
                    cells = _make_row(ri, row, bg_row)
                    state["rows"].append((cells, bg_row))
            # Trim excess rows (previous refresh had more data than this one)
            while len(state["rows"]) > len(rows):
                cells, _ = state["rows"].pop()
                for c in cells:
                    c.destroy()

        return body, repaint

    # -- Shared filter bar (click to cycle each chip) ---------
    _ARB_APR_OPTS   = [5, 10, 20, 50, 100]
    _ARB_VOL_OPTS   = [0, 100_000, 500_000, 1_000_000, 5_000_000]
    _ARB_OI_OPTS    = [0, 50_000, 100_000, 500_000, 1_000_000]
    _ARB_RISK_OPTS  = ["HIGH", "MED", "LOW"]
    _ARB_GRADE_OPTS = ["SKIP", "MAYBE", "GO"]
    # Phase 2 redesign: default ships with GRADE=MAYBE (≈ +WAIT), hiding
    # SKIP noise of the day. User clicks "ALL" to see everything or
    # "GO ONLY" to tighten.
    _ARB_FILTER_DEFAULTS = {
        "min_apr": 5.0, "min_volume": 0, "min_oi": 0,
        "risk_max": "HIGH", "grade_min": "MAYBE",
        "exclude_risky_venues": False,
        "realistic_only": True,
    }

    # Venues considered "risky" for the [NO RISKY VENUES] toggle —
    # reliability ≤ 94 from core.arb.arb_scoring._DEFAULT_VENUE_RELIABILITY.
    _ARB_RISKY_VENUES = frozenset({"bingx", "bitget", "paradex"})

    # REALISTIC filter cutoffs. APR > 500% is almost always stale funding
    # on a thinly-traded perp — looks juicy in the list, impossible to
    # actually execute. Vol < $5M means >20bps slippage on a $1k position
    # which eats the whole edge.
    _ARB_REALISTIC_APR_MAX = 500.0
    _ARB_REALISTIC_VOL_MIN = 5_000_000.0

    def _arb_filter_state(self) -> dict:
        if not hasattr(self, "_arb_filters"):
            # First access — try loading persisted state, else defaults
            self._arb_filters = self._arb_load_filters()
        return self._arb_filters

    @staticmethod
    def _arb_filters_path():
        from pathlib import Path as _P
        return _P("data") / "arb_hub" / "filters.json"

    def _arb_load_filters(self) -> dict:
        """Load persisted filter state from disk. Falls back to defaults."""
        import json as _json
        base = dict(self._ARB_FILTER_DEFAULTS)
        try:
            path = self._arb_filters_path()
            if path.exists():
                raw = _json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    # Only accept keys the defaults know about — prevents
                    # stale schema entries from polluting the state.
                    for k, v in raw.items():
                        if k in base:
                            base[k] = v
        except Exception:
            pass
        return base

    def _arb_save_filters(self) -> None:
        """Persist current filter state to disk (atomic write)."""
        import json as _json
        try:
            path = self._arb_filters_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                _json.dumps(self._arb_filters, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass

    def _arb_fmt_filter(self, key: str, val) -> str:
        if key == "min_apr":
            return f"APR\u2265{int(val)}%"
        if key == "min_volume":
            if val == 0: return "VOL\u2265OFF"
            if val >= 1_000_000: return f"VOL\u2265{int(val/1_000_000)}M"
            return f"VOL\u2265{int(val/1_000)}K"
        if key == "min_oi":
            if val == 0: return "OI\u2265OFF"
            if val >= 1_000_000: return f"OI\u2265{int(val/1_000_000)}M"
            return f"OI\u2265{int(val/1_000)}K"
        if key == "risk_max":
            return f"RISK\u2264{val}"
        if key == "grade_min":
            return f"GRADE\u2265{val}"
        return f"{key}={val}"

    def _arb_rerender_current_tab(self) -> None:
        """Repaint the active tab from cached scan data (no network)."""
        cache = getattr(self, "_arb_cache", None)
        if not cache:
            return
        try:
            self._arb_hub_telem_update(
                cache.get("stats"), cache.get("top"),
                cache.get("opps", []), cache.get("arb_cc", []),
                cache.get("arb_dd", []), cache.get("arb_cd", []),
                cache.get("basis", []), cache.get("spot", []))
        except Exception:
            pass

    def _arb_set_grade_min(self, grade: str) -> None:
        """Set grade_min filter (for [GO ONLY]/[+WAIT]/[ALL] toolbar)."""
        self._arb_filter_state()["grade_min"] = grade
        # Refresh chip display if visible
        lbl = getattr(self, "_arb_filter_labels", {}).get("grade_min")
        if lbl is not None:
            try:
                lbl.configure(text=f" {self._arb_fmt_filter('grade_min', grade)} ")
            except Exception:
                pass
        self._arb_refresh_viab_toolbar()
        self._arb_save_filters()
        self._arb_rerender_current_tab()

    def _arb_toggle_risky_venues(self) -> None:
        state = self._arb_filter_state()
        state["exclude_risky_venues"] = not state.get("exclude_risky_venues", False)
        self._arb_refresh_viab_toolbar()
        self._arb_save_filters()
        self._arb_rerender_current_tab()

    def _arb_toggle_realistic(self) -> None:
        state = self._arb_filter_state()
        state["realistic_only"] = not state.get("realistic_only", True)
        self._arb_refresh_viab_toolbar()
        self._arb_save_filters()
        self._arb_rerender_current_tab()

    def _arb_refresh_viab_toolbar(self) -> None:
        """Repaint the top viability toolbar's active/inactive states."""
        btns = getattr(self, "_arb_viab_btns", {})
        if not btns:
            return
        state = self._arb_filter_state()
        active = state.get("grade_min", "MAYBE")
        palette = {
            "GO":    (GREEN, BG),      # [GO ONLY]
            "MAYBE": (AMBER, BG),      # [+WAIT]
            "SKIP":  (DIM, BG),        # [ALL]
        }
        for key, (btn, grade) in btns.items():
            if key == "risky":
                continue
            try:
                if grade == active:
                    fg, _bg = BG, palette[grade][0]
                    btn.configure(fg=fg, bg=_bg)
                else:
                    fg, _bg = palette[grade][0], palette[grade][1]
                    btn.configure(fg=fg, bg=_bg)
            except Exception:
                pass
        risky_btn = btns.get("risky", (None,))[0]
        if risky_btn is not None:
            try:
                on = state.get("exclude_risky_venues", False)
                risky_btn.configure(
                    text=f" {'[X]' if on else '[ ]'} NO RISKY VENUES ",
                    fg=RED if on else DIM, bg=BG)
            except Exception:
                pass
        real_btn = btns.get("realistic", (None,))[0]
        if real_btn is not None:
            try:
                on = state.get("realistic_only", True)
                real_btn.configure(
                    text=f" {'[X]' if on else '[ ]'} REALISTIC ",
                    fg=AMBER if on else DIM, bg=BG)
            except Exception:
                pass

    def _arb_build_viab_toolbar(self, parent):
        """Phase 2: 3-button viability toolbar + NO RISKY VENUES toggle.

        Sits ABOVE the advanced filter chips. User picks a viability
        bucket ([GO ONLY]/[+WAIT]/[ALL]) and optionally excludes venues
        with low reliability. Simpler than the 5-chip cycling bar and
        answers the "does this position make sense?" question directly.
        """
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", pady=(0, 3))

        # VIAB label dropped — legend row above already establishes the
        # semantics, and the GO/WAIT/ALL chips are self-explanatory.

        state = self._arb_filter_state()
        active = state.get("grade_min", "MAYBE")
        self._arb_viab_btns = {}

        viab_buttons = [
            ("GO ONLY", "GO",    GREEN),
            ("+WAIT",   "MAYBE", AMBER),
            ("ALL",     "SKIP",  DIM),
        ]
        for label, grade, color in viab_buttons:
            is_active = (grade == active)
            fg = BG if is_active else color
            bg = color if is_active else BG
            btn = tk.Label(
                bar, text=f"  {label}  ",
                font=(FONT, 8, "bold"),
                fg=fg, bg=bg, cursor="hand2",
                padx=8, pady=3, bd=0, highlightthickness=0,
            )
            btn.pack(side="left", padx=(0, 2))
            btn.bind("<Button-1>", lambda _e, _g=grade: self._arb_set_grade_min(_g))
            self._arb_viab_btns[label] = (btn, grade)

        # Divider
        tk.Frame(bar, bg=BORDER, width=1, height=18).pack(
            side="left", fill="y", padx=(10, 10))

        # [NO RISKY VENUES] toggle
        on = state.get("exclude_risky_venues", False)
        risky_btn = tk.Label(
            bar,
            text=f" {'[X]' if on else '[ ]'} NO RISKY VENUES ",
            font=(FONT, 8, "bold"),
            fg=RED if on else DIM, bg=BG,
            cursor="hand2", padx=6, pady=3,
        )
        risky_btn.pack(side="left")
        risky_btn.bind("<Button-1>", lambda _e: self._arb_toggle_risky_venues())
        self._arb_viab_btns["risky"] = (risky_btn, None)

        # [REALISTIC] toggle — hides APR>500% (stale funding) and vol<$5M
        # (can't execute without slippage eating the edge). Default ON so
        # the first-open view is clean.
        real_on = state.get("realistic_only", True)
        real_btn = tk.Label(
            bar,
            text=f" {'[X]' if real_on else '[ ]'} REALISTIC ",
            font=(FONT, 8, "bold"),
            fg=AMBER if real_on else DIM, bg=BG,
            cursor="hand2", padx=6, pady=3,
        )
        real_btn.pack(side="left", padx=(6, 0))
        real_btn.bind("<Button-1>", lambda _e: self._arb_toggle_realistic())
        self._arb_viab_btns["realistic"] = (real_btn, None)

    def _arb_build_filter_bar(self, parent):
        """Render the shared filter chip strip. Click a chip to cycle its value.

        Filters persist across tab switches via self._arb_filters. Any value
        change re-renders the active tab from the cached scan (no network).
        """
        # Phase 2: viability toolbar on top, chips below as "advanced"
        self._arb_build_viab_toolbar(parent)

        # Phase 4: ADVANCED chips collapsed by default. Clickable toggle.
        state = self._arb_filter_state()
        adv_container = tk.Frame(parent, bg=BG)
        adv_container.pack(fill="x", pady=(0, 4))

        header = tk.Frame(adv_container, bg=BG)
        header.pack(fill="x")
        advanced_expanded = getattr(self, "_arb_advanced_expanded", False)
        arrow = "▼" if advanced_expanded else "▶"
        toggle = tk.Label(
            header, text=f" {arrow} ADVANCED FILTERS ",
            font=(FONT, 7, "bold"),
            fg=DIM, bg=BG, cursor="hand2", padx=4)
        toggle.pack(side="left")

        def _toggle_advanced(_e=None):
            self._arb_advanced_expanded = not getattr(self, "_arb_advanced_expanded", False)
            # Force full rebuild (not fast-path) by clearing tab labels
            self._arb_tab_labels = None
            self._arbitrage_hub(self._arb_tab)
        toggle.bind("<Button-1>", _toggle_advanced)

        # Early-return if collapsed — chip bar never mounted
        if not advanced_expanded:
            return

        bar = tk.Frame(adv_container, bg=BG2)
        bar.pack(fill="x", pady=(2, 0))
        tk.Label(bar, text=" click pra ciclar ",
                 font=(FONT, 6), fg=DIM, bg=BG2).pack(
            side="left", padx=(0, 6))

        self._arb_filter_labels = {}
        filter_defs = [
            ("min_apr",    self._ARB_APR_OPTS),
            ("min_volume", self._ARB_VOL_OPTS),
            ("min_oi",     self._ARB_OI_OPTS),
            ("risk_max",   self._ARB_RISK_OPTS),
            ("grade_min",  self._ARB_GRADE_OPTS),
        ]
        for fkey, fopts in filter_defs:
            cur = state.get(fkey)
            lbl = tk.Label(bar, text=f" {self._arb_fmt_filter(fkey, cur)} ",
                           font=(FONT, 7, "bold"), fg=AMBER, bg=BG3,
                           cursor="hand2", padx=6, pady=2)
            lbl.pack(side="left", padx=2, pady=2)
            self._arb_filter_labels[fkey] = lbl
            # Hover signals "this is a chip you can click to cycle"
            # — previously only the cursor changed, easy to miss.
            lbl.bind("<Enter>",
                     lambda _e, w=lbl: w.config(bg=BORDER_H, fg=AMBER_B))
            lbl.bind("<Leave>",
                     lambda _e, w=lbl: w.config(bg=BG3, fg=AMBER))

            def _cycle(_e=None, _k=fkey, _opts=fopts):
                s = self._arb_filter_state()
                cur = s.get(_k)
                try:
                    idx = _opts.index(cur)
                except ValueError:
                    idx = 0
                nxt = _opts[(idx + 1) % len(_opts)]
                s[_k] = nxt
                self._arb_filter_labels[_k].configure(
                    text=f" {self._arb_fmt_filter(_k, nxt)} ")
                # Keep viability toolbar in sync when grade_min changes
                if _k == "grade_min":
                    self._arb_refresh_viab_toolbar()
                self._arb_save_filters()
                self._arb_rerender_current_tab()
            lbl.bind("<Button-1>", _cycle)

    # -- Detail pane (populated on row click) ------------------
    def _arb_build_detail_pane(self, parent):
        """Reserve a detail panel below the table. Empty-state is just a
        single-line hint (no separate title + body frames) so the OPPS
        table keeps the full vertical budget until the user clicks a row.
        Body is BG2 so _arb_show_detail's BG2 child labels render as a
        cohesive card when populated.
        """
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(4, 0))
        body = tk.Frame(parent, bg=BG2)
        body.pack(fill="x", pady=(0, 0))
        default = tk.Label(
            body,
            text="  DETAIL  ›  clique numa linha pra simular posição",
            font=(FONT, 7), fg=DIM, bg=BG2)
        default.pack(anchor="w", padx=4, pady=(2, 2))
        self._arb_detail_body = body
        self._arb_detail_default = default

    # Size chips for the detail simulator. Matches the reasonable range
    # for paper mode ($5k account, max 3 positions — $500 to $5k per leg).
    _ARB_SIM_SIZES = (500.0, 1000.0, 2500.0, 5000.0)

    def _arb_simulate(self, pair: dict, size_usd: float) -> dict:
        """Project funding / fees / net for a given position size.

        Formula matches SimpleArbEngine:
          - entry fee: size × (10 + 5) / 10_000 = 0.15% at open
          - exit fee: same 0.15% at close → RT = 30 bps
          - funding: size × apr/100 × hours / 8760  (continuous approx
            of 3× 8h funding payments/day × 365)

        Decay scenario: 4h at full APR, then APR halves, hold to 24h.
        Gives a concrete "what if the spread fades" number alongside
        the "if it holds" row.
        """
        apr = abs(float(pair.get("net_apr") or pair.get("apr")
                         or pair.get("basis_apr") or 0))
        rt_fee_bps = 30.0
        rt_fee_usd = size_usd * rt_fee_bps / 10_000.0

        def _funding(hold_h: float, apr_pct: float) -> float:
            return size_usd * (apr_pct / 100.0) * (hold_h / 8760.0)

        holds = [8, 24, 72]
        rows = []
        for h in holds:
            f = _funding(h, apr)
            rows.append({
                "hold_h": h,
                "funding": round(f, 2),
                "fees":    round(rt_fee_usd, 2),
                "net":     round(f - rt_fee_usd, 2),
            })
        # Decay scenario: 4h @ full, 20h @ 50%, exit at 24h total
        decay_funding = _funding(4.0, apr) + _funding(20.0, apr * 0.5)
        decay_row = {
            "label":   "decay→50% @4h, hold 24h",
            "funding": round(decay_funding, 2),
            "fees":    round(rt_fee_usd, 2),
            "net":     round(decay_funding - rt_fee_usd, 2),
        }

        bkevn_h = round(rt_fee_bps * 87.6 / apr, 2) if apr > 0 else None

        # Risk block. Liquidation distances assume exchange defaults
        # (~20x short perp, ~25x long perp with small maintenance buffer).
        # These are rough — real launcher doesn't set leverage here.
        liq_short_pct = 4.5
        liq_long_pct  = 3.5

        vol = (pair.get("volume_24h")
               or self._pair_min(pair.get("volume_24h_short"),
                                  pair.get("volume_24h_long")) or 0)
        vol_f = float(vol) if vol else 0.0
        vol_ratio = vol_f / size_usd if (vol_f > 0 and size_usd > 0) else None
        # Slippage ballpark: 10bps baseline, scales down with sqrt(ratio/10).
        # Not a market impact model — just "small / ok / concerning" flag.
        slippage_bps = None
        if vol_ratio and vol_ratio > 0:
            slippage_bps = round(10.0 / max((vol_ratio / 10.0) ** 0.5, 0.1), 2)

        from core.arb.arb_scoring import _DEFAULT_VENUE_RELIABILITY
        sv = (pair.get("short_venue") or pair.get("venue_perp")
              or pair.get("venue_a") or "").lower()
        lv = (pair.get("long_venue") or pair.get("venue_spot")
              or pair.get("venue_b") or "").lower()

        return {
            "size_usd":   size_usd,
            "apr":        apr,
            "rt_fee_usd": round(rt_fee_usd, 2),
            "bkevn_h":    bkevn_h,
            "rows":       rows,
            "decay":      decay_row,
            "risk": {
                "liq_short_pct": liq_short_pct,
                "liq_long_pct":  liq_long_pct,
                "slippage_bps":  slippage_bps,
                "vol":           vol_f,
                "vol_ratio":     vol_ratio,
                "short_venue":   sv,
                "long_venue":    lv,
                "short_rel":     _DEFAULT_VENUE_RELIABILITY.get(sv),
                "long_rel":      _DEFAULT_VENUE_RELIABILITY.get(lv),
            },
        }

    @timed_legacy_switch("arb_detail")
    def _arb_show_detail(self, pair: dict):
        """Render the simulator detail pane for a selected pair.

        Layout (top-down): header | status line (APR/VIAB/SCORE/BKEVN) |
        size chips | simulation table (8h/24h/72h + decay row) | risk
        block (liq/slip/venues) | why-line | collapsible ADVANCED factor
        breakdown | size-aware OPEN AS PAPER button.
        """
        body = getattr(self, "_arb_detail_body", None)
        if body is None:
            return
        for w in body.winfo_children():
            w.destroy()

        # Track selected pair + size + ADVANCED expansion between clicks
        self._arb_detail_pair = pair
        if not hasattr(self, "_arb_detail_size"):
            self._arb_detail_size = 1000.0
        if not hasattr(self, "_arb_detail_adv"):
            self._arb_detail_adv = False
        size_usd = self._arb_detail_size

        try:
            from core.arb.arb_scoring import score_opp
            res = score_opp(pair)
        except Exception:
            res = None

        # -- Header -----------------------------------------------
        tk.Label(body, text=self._arb_pair_label(pair),
                 font=(FONT, 9, "bold"), fg=AMBER, bg=BG2,
                 anchor="w").pack(fill="x", padx=6, pady=(4, 1))

        # -- Status line: APR / VIAB / SCORE / BKEVN --------------
        apr_val = float(pair.get("net_apr") or pair.get("apr") or 0)
        status = tk.Frame(body, bg=BG2); status.pack(fill="x", padx=6)
        tk.Label(status, text=f"APR {apr_val:+.1f}%",
                 font=(FONT, 9, "bold"),
                 fg=GREEN if abs(apr_val) >= 50 else AMBER,
                 bg=BG2).pack(side="left")
        if res is not None:
            viab = getattr(res, "viab", res.grade)
            viab_fg = (GREEN if viab == "GO" else
                       AMBER if viab in ("WAIT", "MAYBE") else DIM)
            tk.Label(status, text=f"  ·  {viab}",
                     font=(FONT, 9, "bold"), fg=viab_fg, bg=BG2).pack(side="left")
            tk.Label(status, text=f"  ·  score {res.score:.0f}",
                     font=(FONT, 8), fg=WHITE, bg=BG2).pack(side="left")
            be = getattr(res, "breakeven_h", None)
            if be is not None:
                be_fg = GREEN if be <= 24 else (AMBER if be <= 72 else DIM)
                tk.Label(status, text=f"  ·  bkevn {be:.1f}h",
                         font=(FONT, 8), fg=be_fg, bg=BG2).pack(side="left")

        # -- Size chips -------------------------------------------
        size_row = tk.Frame(body, bg=BG2)
        size_row.pack(fill="x", padx=6, pady=(6, 2))
        tk.Label(size_row, text="SIZE", font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG2).pack(side="left", padx=(0, 6))
        for s in self._ARB_SIM_SIZES:
            is_sel = abs(s - size_usd) < 0.01
            chip = tk.Label(
                size_row,
                text=f"  ${int(s):,}  " if s >= 1000 else f"  ${int(s)}  ",
                font=(FONT, 8, "bold"),
                fg=BG if is_sel else WHITE,
                bg=AMBER if is_sel else BG3,
                cursor="hand2", padx=4, pady=2,
            )
            chip.pack(side="left", padx=(0, 3))
            chip.bind("<Button-1>",
                      lambda _e, _s=s: self._arb_set_detail_size(_s))

        # -- Simulation table -------------------------------------
        sim = self._arb_simulate(pair, size_usd)
        sim_frame = tk.Frame(body, bg=BG2)
        sim_frame.pack(fill="x", padx=6, pady=(4, 4))
        cols = [("HOLD", 10, "w"), ("FUNDING", 10, "e"),
                ("FEES", 9, "e"), ("NET", 10, "e")]
        for j, (c, w, a) in enumerate(cols):
            tk.Label(sim_frame, text=c, font=(FONT, 7, "bold"),
                     fg=AMBER, bg=BG2, width=w, anchor=a).grid(
                row=0, column=j, sticky=a, padx=2)
        for i, r in enumerate(sim["rows"], start=1):
            hold_txt = f"{r['hold_h']}h"
            if sim["bkevn_h"] is not None and r["hold_h"] >= sim["bkevn_h"]:
                hold_txt += "  ✓"
            tk.Label(sim_frame, text=hold_txt, font=(FONT, 8),
                     fg=WHITE, bg=BG2, width=10, anchor="w").grid(
                row=i, column=0, sticky="w", padx=2)
            tk.Label(sim_frame, text=f"+${r['funding']:.2f}",
                     font=(FONT, 8), fg=GREEN, bg=BG2,
                     width=10, anchor="e").grid(
                row=i, column=1, sticky="e", padx=2)
            tk.Label(sim_frame, text=f"-${r['fees']:.2f}",
                     font=(FONT, 8), fg=RED, bg=BG2,
                     width=9, anchor="e").grid(
                row=i, column=2, sticky="e", padx=2)
            net_fg = GREEN if r["net"] > 0 else RED
            tk.Label(sim_frame, text=f"${r['net']:+.2f}",
                     font=(FONT, 8, "bold"), fg=net_fg, bg=BG2,
                     width=10, anchor="e").grid(
                row=i, column=3, sticky="e", padx=2)
        # Decay scenario row
        decay_i = len(sim["rows"]) + 1
        d = sim["decay"]
        tk.Label(sim_frame, text=d["label"], font=(FONT, 7, "italic"),
                 fg=DIM2, bg=BG2, width=20, anchor="w").grid(
            row=decay_i, column=0, columnspan=2, sticky="w",
            padx=2, pady=(3, 0))
        tk.Label(sim_frame, text=f"-${d['fees']:.2f}",
                 font=(FONT, 7, "italic"), fg=DIM2, bg=BG2,
                 width=9, anchor="e").grid(
            row=decay_i, column=2, sticky="e", padx=2, pady=(3, 0))
        decay_fg = GREEN if d["net"] > 0 else RED
        tk.Label(sim_frame, text=f"${d['net']:+.2f}",
                 font=(FONT, 7, "italic"), fg=decay_fg, bg=BG2,
                 width=10, anchor="e").grid(
            row=decay_i, column=3, sticky="e", padx=2, pady=(3, 0))

        # -- Risk block -------------------------------------------
        tk.Frame(body, bg=BORDER, height=1).pack(
            fill="x", padx=6, pady=(2, 2))
        risk = sim["risk"]
        risk_frame = tk.Frame(body, bg=BG2)
        risk_frame.pack(fill="x", padx=6, pady=(2, 2))
        tk.Label(risk_frame, text="RISK", font=(FONT, 7, "bold"),
                 fg=AMBER, bg=BG2).grid(row=0, column=0, sticky="w",
                                         padx=(0, 8))
        liq_txt = (f"liq {risk['liq_short_pct']:.1f}% short · "
                   f"{risk['liq_long_pct']:.1f}% long")
        tk.Label(risk_frame, text=liq_txt, font=(FONT, 7),
                 fg=DIM2, bg=BG2).grid(row=0, column=1, sticky="w")
        if risk["slippage_bps"] is not None:
            slip_fg = (GREEN if risk["slippage_bps"] < 5 else
                       AMBER if risk["slippage_bps"] < 15 else RED)
            slip_txt = (f"slip ~{risk['slippage_bps']:.1f}bps "
                        f"(vol ratio {risk['vol_ratio']:,.0f}x)")
        else:
            slip_fg = DIM
            slip_txt = "slip —"
        tk.Label(risk_frame, text=slip_txt, font=(FONT, 7),
                 fg=slip_fg, bg=BG2).grid(row=1, column=1, sticky="w")
        venue_bits = []
        for name, rel in (("short", risk["short_rel"]),
                          ("long",  risk["long_rel"])):
            ven = risk["short_venue"] if name == "short" else risk["long_venue"]
            if rel is not None:
                venue_bits.append(f"{ven} {rel:.0f}")
            elif ven:
                venue_bits.append(f"{ven} ?")
        ven_fg = DIM2
        if risk["short_rel"] and risk["long_rel"]:
            worst = min(risk["short_rel"], risk["long_rel"])
            ven_fg = GREEN if worst >= 97 else (AMBER if worst >= 94 else RED)
        tk.Label(risk_frame, text="venues " + " · ".join(venue_bits),
                 font=(FONT, 7), fg=ven_fg, bg=BG2).grid(
            row=2, column=1, sticky="w")

        # -- Why line ---------------------------------------------
        if res is not None:
            reason = self._arb_viab_reason(pair, res)
            if reason:
                tk.Label(body, text=reason,
                         font=(FONT, 7), fg=DIM, bg=BG2,
                         anchor="w", justify="left", wraplength=600).pack(
                    fill="x", padx=6, pady=(2, 2))

        # -- ADVANCED (collapsible factor breakdown) --------------
        if res is not None:
            adv_on = self._arb_detail_adv
            adv_head = tk.Label(
                body,
                text=("▼ ADVANCED  (factor breakdown)" if adv_on
                      else "▶ ADVANCED  (factor breakdown)"),
                font=(FONT, 7), fg=DIM, bg=BG2,
                anchor="w", cursor="hand2",
            )
            adv_head.pack(fill="x", padx=6, pady=(2, 0))
            adv_head.bind(
                "<Button-1>",
                lambda _e: self._arb_toggle_detail_adv())
            if adv_on:
                adv_grid = tk.Frame(body, bg=BG2)
                adv_grid.pack(fill="x", padx=12, pady=(2, 4))
                factor_rows = [
                    ("NET APR", res.factors.get("net_apr"),
                        f"{apr_val:+.1f}%"),
                    ("VOLUME",  res.factors.get("volume"),
                        self._fmt_vol(pair.get("volume_24h")
                                      or self._pair_min(pair.get("volume_24h_short"),
                                                         pair.get("volume_24h_long")))),
                    ("OI",      res.factors.get("oi"),
                        self._fmt_vol(pair.get("open_interest")
                                      or self._pair_min(pair.get("open_interest_short"),
                                                         pair.get("open_interest_long")))),
                    ("RISK",    res.factors.get("risk"),
                        pair.get("risk", "—")),
                    ("SLIP",    res.factors.get("slippage"), "—"),
                    ("VENUE",   res.factors.get("venue"),
                        self._arb_venue_label(pair)),
                ]
                for i, (label, score, value) in enumerate(factor_rows):
                    adv_grid.grid_columnconfigure(1, weight=1)
                    tk.Label(adv_grid, text=label, font=(FONT, 7, "bold"),
                             fg=DIM, bg=BG2, width=8, anchor="w").grid(
                        row=i, column=0, sticky="w", padx=(0, 6))
                    tk.Label(adv_grid, text=value, font=(FONT, 8),
                             fg=WHITE, bg=BG2, anchor="w").grid(
                        row=i, column=1, sticky="w")
                    s_txt = "—" if score is None else f"{score:.0f}/100"
                    s_fg = (GREEN if (score or 0) >= 70 else
                            AMBER if (score or 0) >= 40 else DIM)
                    tk.Label(adv_grid, text=s_txt, font=(FONT, 7),
                             fg=s_fg, bg=BG2, width=10, anchor="e").grid(
                        row=i, column=2, sticky="e")

        # -- Action bar: size-aware OPEN AS PAPER POSITION --------
        tk.Frame(body, bg=BORDER, height=1).pack(
            fill="x", padx=6, pady=(2, 2))
        action = tk.Frame(body, bg=BG2)
        action.pack(fill="x", padx=6, pady=(2, 6))

        engine = getattr(self, "_arb_simple_engine", None)
        engine_running = engine is not None and engine.running
        size_label = (f"${int(size_usd):,}" if size_usd >= 1000
                      else f"${int(size_usd)}")
        if engine_running:
            btn_text = f" OPEN AS PAPER — {size_label} "
            btn_fg, btn_bg = BG, GREEN
            btn_cmd = lambda _e=None, _p=pair, _s=size_usd: (
                self._arb_open_as_paper(_p, size_usd=_s))
        else:
            btn_text = " START ENGINE FIRST (POSITIONS tab) "
            btn_fg, btn_bg = DIM, BG3
            btn_cmd = lambda _e=None: None
        btn = tk.Label(action, text=btn_text,
                       font=(FONT, 8, "bold"),
                       fg=btn_fg, bg=btn_bg,
                       cursor="hand2" if engine_running else "arrow",
                       padx=10, pady=4)
        btn.pack(side="left")
        btn.bind("<Button-1>", btn_cmd)

    def _arb_set_detail_size(self, size_usd: float) -> None:
        """Size chip click - re-render detail with new size."""
        self._arb_detail_size = float(size_usd)
        pair = getattr(self, "_arb_detail_pair", None)
        if pair is not None:
            self._arb_show_detail(pair)

    def _arb_toggle_detail_adv(self) -> None:
        """ADVANCED section expand/collapse toggle."""
        self._arb_detail_adv = not getattr(self, "_arb_detail_adv", False)
        pair = getattr(self, "_arb_detail_pair", None)
        if pair is not None:
            self._arb_show_detail(pair)

    def _arb_viab_reason(self, pair: dict, res) -> str:
        """Human-readable reason for the VIAB verdict (top 2-3 factors)."""
        viab = getattr(res, "viab", res.grade)
        apr = abs(float(pair.get("net_apr") or pair.get("apr") or 0))
        be = getattr(res, "breakeven_h", None)
        vol_score = (res.factors.get("volume") or 0)
        if viab == "GO":
            parts = [f"high APR ({apr:.0f}%)"]
            if be is not None:
                parts.append(f"fast breakeven ({be:.1f}h)")
            if vol_score >= 40:
                parts.append("liquid")
            return "  Why GO: " + ", ".join(parts)
        if viab in ("WAIT", "MAYBE"):
            parts = [f"APR {apr:.0f}%"]
            if be is not None:
                parts.append(f"bkevn {be:.1f}h")
            if vol_score < 40:
                parts.append("liquidity moderate")
            return "  Why WAIT: " + ", ".join(parts)
        # SKIP
        reasons = []
        if apr < 20:
            reasons.append(f"APR too low ({apr:.0f}%)")
        if be is not None and be > 72:
            reasons.append(f"slow breakeven ({be:.1f}h)")
        if vol_score < 20:
            reasons.append("illiquid")
        return "  Why SKIP: " + ", ".join(reasons) if reasons else ""

    def _arb_open_as_paper(self, pair: dict, *, size_usd: float | None = None) -> None:
        """Open this opp as a paper position immediately (bypass tick).

        When size_usd is given, temporarily override engine.size_usd for
        this one open so the user-chosen size from the detail chips is
        honored. Restores the original default after so the tick loop
        keeps opening at its configured default.
        """
        engine = getattr(self, "_arb_simple_engine", None)
        if engine is None or not engine.running:
            return
        import time as _time
        try:
            opp = dict(pair)
            if "net_apr" not in opp:
                opp["net_apr"] = opp.get("apr") or opp.get("basis_apr") or 0
            if "short_venue" not in opp:
                opp["short_venue"] = opp.get("venue_perp") or opp.get("venue_a") or ""
            if "long_venue" not in opp:
                opp["long_venue"] = opp.get("venue_spot") or opp.get("venue_b") or ""
            if "mark_price" not in opp:
                opp["mark_price"] = opp.get("spot_price") or opp.get("price_a") or 0
            original_size = engine.size_usd
            try:
                if size_usd is not None:
                    engine.size_usd = float(size_usd)
                engine._open(opp, _time.time())
            finally:
                engine.size_usd = original_size
            engine._persist()
            self.after(200, lambda: self._arbitrage_hub("positions"))
        except Exception as e:
            import logging
            logging.getLogger("aurum.arb_hub").warning(
                "open_as_paper failed for %s: %s", pair.get("symbol"), e,
                exc_info=True)

    @staticmethod
    def _pair_min(a, b):
        vals = [v for v in (a, b) if v is not None]
        return min(vals) if vals else None

    @staticmethod
    def _fmt_vol(v):
        if v is None:
            return "\u2014"
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "\u2014"
        if v >= 1_000_000:
            return f"${v / 1_000_000:.1f}M"
        if v >= 1_000:
            return f"${v / 1_000:.0f}K"
        return f"${v:.0f}"

    @staticmethod
    def _arb_venue_label(pair: dict) -> str:
        if pair.get("long_venue") and pair.get("short_venue"):
            return f"{pair['long_venue']} \u2192 {pair['short_venue']}"
        return str(pair.get("venue") or "\u2014")

    @staticmethod
    def _arb_pair_label(pair: dict) -> str:
        sym = pair.get("symbol") or pair.get("sym") or "\u2014"
        venue = (f"{pair.get('long_venue', '')} \u2194 {pair.get('short_venue', '')}"
                 if pair.get("long_venue") else pair.get("venue", ""))
        venue_clean = venue.strip(" \u2194")
        return f"{sym}  \u00b7  {venue_clean}"

    # -- Scoring filter ---------------------------------------
    def _arb_score_fallback(self, pair: dict):
        """Synthesize a ScoreResult from net_apr alone.

        arb_pairs() doesn't propagate volume_24h / open_interest per leg,
        so score_opp returns mostly-None factors and grades SKIP for
        everything. When that happens, fall back to a pure-APR score so the
        table doesn't look all-SKIP.
        """
        from core.arb.arb_scoring import ScoreResult
        apr = abs(float(pair.get("net_apr") or pair.get("apr") or 0))
        # APR → score mapping: 0% = 0, 50%+ = 100
        score = min(100.0, apr * 2.0)
        if score >= 70:
            grade = "GO"
        elif score >= 40:
            grade = "MAYBE"
        else:
            grade = "SKIP"
        return ScoreResult(score=round(score, 0), grade=grade,
                            factors={"net_apr": score})

    def _arb_filter_and_score(self, pairs: list) -> list[tuple[dict, object]]:
        """Apply user filters + scoring to each pair.

        Scores via arb_scoring.score_opp — cached by (symbol, venues,
        apr_round_1dp) with TTL = scan interval to avoid re-scoring the
        same pair on tab switches within 15s. Falls back to APR-only
        heuristic when scoring factors are all None.
        Returns (pair_dict, ScoreResult) in descending score order.
        """
        from core.arb.arb_scoring import score_opp
        state = self._arb_filter_state()
        min_apr    = state.get("min_apr", 0)
        min_volume = state.get("min_volume", 0)
        min_oi     = state.get("min_oi", 0)
        risk_max   = state.get("risk_max", "HIGH")
        grade_min  = state.get("grade_min", "SKIP")
        _R = {"LOW": 0, "MED": 1, "HIGH": 2}
        _G = {"GO": 0, "MAYBE": 1, "SKIP": 2}
        risk_cap  = _R.get(risk_max, 2)
        grade_cap = _G.get(grade_min, 2)

        # Score cache — TTL matches scanner cache (30s is the scan ttl,
        # so scoring is the same for 30s regardless of tab flips).
        import time as _time
        cache = getattr(self, "_arb_score_cache", None)
        if cache is None or (_time.time() - cache.get("ts", 0)) > 30.0:
            cache = {"ts": _time.time(), "map": {}}
            self._arb_score_cache = cache
        cache_map = cache["map"]

        exclude_risky = state.get("exclude_risky_venues", False)
        realistic_only = state.get("realistic_only", True)
        apr_max = self._ARB_REALISTIC_APR_MAX
        vol_min_realistic = self._ARB_REALISTIC_VOL_MIN
        risky_venues = self._ARB_RISKY_VENUES
        out = []
        for p in (pairs or []):
            # Cheap filters first
            apr = abs(float(p.get("net_apr") or p.get("apr") or 0))
            if apr < min_apr:
                continue
            # REALISTIC filter — cap APR at 500% (stale funding territory)
            # before the other checks so we spend zero cycles on them.
            if realistic_only and apr > apr_max:
                continue
            vol = (p.get("volume_24h")
                   or self._pair_min(p.get("volume_24h_short"),
                                      p.get("volume_24h_long")) or 0)
            if min_volume and float(vol) < min_volume:
                continue
            if realistic_only and float(vol) < vol_min_realistic:
                continue
            oi = (p.get("open_interest")
                  or self._pair_min(p.get("open_interest_short"),
                                     p.get("open_interest_long")) or 0)
            if min_oi and float(oi) < min_oi:
                continue
            risk = p.get("risk", "HIGH")
            if _R.get(risk, 2) > risk_cap:
                continue
            # [NO RISKY VENUES] toolbar toggle — drop pairs involving
            # low-reliability venues (bingx, bitget, paradex).
            if exclude_risky:
                sv = (p.get("short_venue") or p.get("venue_perp") or
                      p.get("venue_a") or "").lower()
                lv = (p.get("long_venue") or p.get("venue_spot") or
                      p.get("venue_b") or "").lower()
                if sv in risky_venues or lv in risky_venues:
                    continue

            # Cache key: symbol + venues + apr rounded to 1dp (the only
            # field that changes meaningfully between scans).
            ckey = (
                p.get("symbol", ""),
                p.get("short_venue", "") or p.get("venue_perp", "") or p.get("venue_a", ""),
                p.get("long_venue", "") or p.get("venue_spot", "") or p.get("venue_b", ""),
                round(apr, 1),
                p.get("_type", ""),
            )
            sr = cache_map.get(ckey)
            if sr is None:
                try:
                    sr = score_opp(p)
                    populated = sum(1 for v in sr.factors.values() if v is not None)
                    if populated <= 1:
                        sr = self._arb_score_fallback(p)
                except Exception:
                    sr = self._arb_score_fallback(p)
                cache_map[ckey] = sr

            if _G.get(sr.grade, 2) > grade_cap:
                continue
            out.append((p, sr))
        # Sort: grade bucket (GO first), then BKEVN asc (fastest payback),
        # then SCORE desc as tiebreaker. Fastest-to-breakeven is what
        # actually matters — high score with 80h bkevn is a trap.
        def _key(t):
            _p, _sr = t
            be = getattr(_sr, "breakeven_h", None)
            be_val = be if be is not None else 9999.0
            return (_G.get(_sr.grade, 2), be_val, -_sr.score)
        out.sort(key=_key)
        return out

    # -- Tab renderers ------------------------------------------
    _ARB_PAIRS_COLS = [
        ("#",     3,  "e"), ("SYM",    7, "w"),
        ("LONG",  10, "w"), ("SHORT",  10, "w"),
        ("APR",   8,  "e"), ("VOL",    8, "e"),
        ("OI",    8,  "e"), ("RISK",   5, "e"),
        ("GRADE", 8,  "e"),
    ]

    # Legacy renderers (cex_cex, dex_dex, cex_dex, basis, spot) removed
    # in Phase 4 organize (2026-04-22). Their data now flows into the
    # unified OPPS tab. The _arb_*_repaint/_selected fields they wrote
    # to are no longer referenced; if you need the raw pair lists they
    # live in self._arb_cache (populated by _arb_hub_scan_async).

    def _arb_render_engine(self, parent):
        """SimpleArbEngine (in-process) controls + live risk + positions."""
        engine = getattr(self, "_arb_simple_engine", None)
        if engine is not None and engine.running:
            snap = engine.snapshot()
            running_badge = ("RUN", GREEN)
        else:
            snap = {
                "mode": "—", "running": False, "killed": False,
                "account": 0, "peak": 0, "drawdown_pct": 0,
                "realized_pnl": 0, "unrealized_pnl": 0, "exposure_usd": 0,
                "losses_streak": 0, "trades_count": 0, "positions": [],
            }
            running_badge = ("OFF", RED)

        # Status strip (engine-specific)
        top = tk.Frame(parent, bg=BG)
        top.pack(fill="x", pady=(0, 4))
        tk.Label(top, text="ARB ENGINE",
                 font=(FONT, 9, "bold"), fg=AMBER, bg=BG).pack(side="left")
        tk.Label(top, text=f"  ·  {running_badge[0]}  ·  mode {snap.get('mode', '—')}",
                 font=(FONT, 8), fg=running_badge[1], bg=BG).pack(side="left")
        if snap.get("killed"):
            tk.Label(top, text="  ·  KILLED", font=(FONT, 8, "bold"),
                     fg=RED, bg=BG).pack(side="left")

        # Live risk gauges
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 4))
        gauges = tk.Frame(parent, bg=BG)
        gauges.pack(fill="x", pady=(0, 4))
        for k, label, fmt in [
            ("account", "ACCT", "${:,.0f}"),
            ("drawdown_pct", "DD", "{:+.2f}%"),
            ("exposure_usd", "EXPO", "${:,.0f}"),
            ("realized_pnl", "REAL", "${:+,.2f}"),
            ("unrealized_pnl", "UPNL", "${:+,.2f}"),
            ("losses_streak", "STREAK", "{}"),
            ("trades_count", "TRADES", "{}"),
        ]:
            val = snap.get(k, 0) or 0
            try:
                vtxt = fmt.format(val)
            except Exception:
                vtxt = "—"
            col = tk.Frame(gauges, bg=BG)
            col.pack(side="left", padx=(0, 16))
            tk.Label(col, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG).pack(anchor="w")
            tk.Label(col, text=vtxt, font=(FONT, 10, "bold"),
                     fg=WHITE, bg=BG).pack(anchor="w")

        # Controls
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
        ctrls = tk.Frame(parent, bg=BG)
        ctrls.pack(fill="x", pady=(0, 4))
        tk.Label(ctrls, text="  controls:",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(side="left")
        for text, cmd, color in [
            ("START PAPER", lambda: self._arb_engine_start("paper"), GREEN),
            ("STOP",        self._arb_engine_stop,                    RED),
        ]:
            b = tk.Label(ctrls, text=f"  {text}  ", font=(FONT, 7, "bold"),
                         fg=BG, bg=color, cursor="hand2", padx=6, pady=1)
            b.pack(side="left", padx=(6, 0))
            b.bind("<Button-1>", lambda _e, _c=cmd: _c())

        # Live positions table (Phase 3: proper diff-updating _arb_make_table
        # instead of tk.Text — gains colored APR/PnL, click-to-detail, etc.)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
        tk.Label(parent, text="OPEN POSITIONS",
                 font=(FONT, 7, "bold"), fg=DIM, bg=BG).pack(anchor="w")
        positions = snap.get("positions", [])
        pos_cols = [
            ("SYM",      10, "w"),
            ("VENUES",   18, "w"),
            ("APR NOW",  9,  "e"),
            ("ACCRUED",  9,  "e"),
            ("NET P&L",  9,  "e"),
            ("OPEN",     7,  "e"),
        ]
        _, pos_repaint = self._arb_make_table(parent, pos_cols)
        if positions:
            pos_rows = []
            for p in positions:
                entry_apr = float(p.get("entry_apr", 0) or 0)
                cur_apr = float(p.get("current_apr", 0) or 0)
                # APR decay color: RED if below 50% of entry
                if abs(entry_apr) > 0 and abs(cur_apr) / abs(entry_apr) < 0.5:
                    apr_fg = RED
                elif abs(cur_apr) >= 50:
                    apr_fg = GREEN
                else:
                    apr_fg = AMBER
                accrued = float(p.get("funding_accrued", 0) or 0)
                fees = float(p.get("fees_paid", 0) or 0)
                # Entry fees already deducted; approximate exit fee for
                # net-P&L preview (matches SimpleArbEngine._close math).
                exit_fee_est = fees  # symmetric
                net_pnl = accrued - fees - exit_fee_est
                sv = (p.get("venue_short", "") or "")[:8]
                lv = (p.get("venue_long", "") or "")[:8]
                pos_rows.append([
                    ((p.get("symbol", "") or "—")[:10], WHITE),
                    (f"{lv}>{sv}"[:18], AMBER_D),
                    (f"{cur_apr:+.1f}%", apr_fg),
                    (f"${accrued:+.2f}", GREEN if accrued >= 0 else RED),
                    (f"${net_pnl:+.2f}", GREEN if net_pnl >= 0 else RED),
                    (f"{p.get('hours_open', 0):.1f}h", DIM),
                ])
            pos_repaint(pos_rows)
        else:
            pos_repaint([])
            tk.Label(parent, text="  no positions open — start engine in POSITIONS tab",
                     font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=4)

        # Recent closed trades (tail, proper table)
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(6, 4))
        tk.Label(parent, text="RECENT CLOSES",
                 font=(FONT, 7, "bold"), fg=DIM, bg=BG).pack(anchor="w")
        closed_cols = [
            ("SYM",     10, "w"),
            ("REASON",  11, "w"),
            ("HOLD",    6,  "e"),
            ("P&L",     9,  "e"),
        ]
        _, closed_repaint = self._arb_make_table(parent, closed_cols)
        recent = (snap.get("closed_recent", []) or
                  (engine.closed[-10:] if engine is not None else []))
        if recent:
            closed_rows = []
            for c in reversed(recent):
                pnl = float(c.get("pnl", 0) or 0)
                closed_rows.append([
                    ((c.get("symbol", "") or "—")[:10], WHITE),
                    ((c.get("exit_reason", "") or "")[:11], DIM),
                    (f"{c.get('hours_open', 0):.1f}h", DIM),
                    (f"${pnl:+.2f}", GREEN if pnl >= 0 else RED),
                ])
            closed_repaint(closed_rows)
        else:
            closed_repaint([])
            tk.Label(parent, text="  no closes yet",
                     font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="w", padx=4)

    # ═══════════════════════════════════════════════════════════
    # Phase 1 redesign (2026-04-22): 3-tab layout
    # ═══════════════════════════════════════════════════════════
    # 6-column layout after organize pass (2026-04-22):
    # Dropped TYPE (~always PERP_PERP, goes in detail) and VOL
    # (REALISTIC filter already gates anything uninvestable, and the
    # detail pane shows vol ratio at the actual trade size). Left with
    # the 6 columns that actually drive the "take this or not?" call.
    _ARB_OPPS_COLS = [
        ("VIAB",    5,  "w"),
        ("SYM",    11,  "w"),
        ("VENUES", 22,  "w"),
        ("APR",     9,  "e"),
        ("BKEVN",   7,  "e"),
        ("SCORE",   5,  "e"),
    ]

    def _arb_render_opps(self, parent):
        """Unified OPPS table. All 5 legacy tabs (cex-cex / dex-dex /
        cex-dex / basis / spot) merged here, scored + bucketed by VIAB.

        Header collapses the tab title + VIAB legend into one row so
        the table shows up within ~80px of the status strip.
        """
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(0, 3))
        # GO / WAIT / SKIP legend inline — surfaces the triage rule
        # without burning a second row on it. Colors match the table
        # cells so the eye bridges legend→rows automatically.
        tk.Label(head, text="GO", font=(FONT, 7, "bold"),
                 fg=GREEN, bg=BG).pack(side="left", padx=(0, 3))
        tk.Label(head, text="score≥70 · bkevn≤24h · líquido",
                 font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left", padx=(0, 8))
        tk.Label(head, text="WAIT", font=(FONT, 7, "bold"),
                 fg=AMBER, bg=BG).pack(side="left", padx=(0, 3))
        tk.Label(head, text="score≥40 · bkevn≤72h OU vol moderada",
                 font=(FONT, 7), fg=DIM2, bg=BG).pack(side="left", padx=(0, 8))
        tk.Label(head, text="SKIP", font=(FONT, 7, "bold"),
                 fg=DIM, bg=BG).pack(side="left", padx=(0, 3))
        tk.Label(head, text="resto", font=(FONT, 7),
                 fg=DIM2, bg=BG).pack(side="left")
        self._arb_build_filter_bar(parent)
        self._arb_opps_selected = []

        def _on_click(ri: int):
            if 0 <= ri < len(self._arb_opps_selected):
                self._arb_show_detail(self._arb_opps_selected[ri])

        _, repaint = self._arb_make_table(parent, self._ARB_OPPS_COLS,
                                          on_click=_on_click)
        self._arb_opps_repaint = repaint
        repaint([])
        self._arb_build_detail_pane(parent)

    def _arb_render_positions(self, parent):
        """Live paper engine positions + controls. Inherits body from
        legacy _arb_render_engine — no destruction, just routed via
        the new 3-tab layout."""
        self._arb_render_engine(parent)

    def _arb_render_history(self, parent):
        """Closed trades log from SimpleArbEngine. Newest first, realized
        PnL total at top. Read-only; rebuilds only when len(closed)
        changes."""
        engine = getattr(self, "_arb_simple_engine", None)
        closed = (engine.closed if engine is not None else [])

        total_pnl = round(sum(c.get("pnl", 0) for c in closed), 2)
        n = len(closed)
        header = tk.Frame(parent, bg=BG)
        header.pack(fill="x", pady=(0, 4))
        tk.Label(header, text="HISTORY",
                 font=(FONT, 9, "bold"), fg=AMBER, bg=BG).pack(side="left")
        tk.Label(header, text=f"  ·  {n} trades closed  ·  realized ",
                 font=(FONT, 8), fg=DIM, bg=BG).pack(side="left")
        pnl_fg = GREEN if total_pnl >= 0 else RED
        tk.Label(header, text=f"${total_pnl:+,.2f}",
                 font=(FONT, 9, "bold"), fg=pnl_fg, bg=BG).pack(side="left")

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", pady=(2, 6))

        if not closed:
            tk.Label(parent,
                     text="  No closed trades yet. Start the engine in POSITIONS tab.",
                     font=(FONT, 8), fg=DIM, bg=BG).pack(anchor="w", pady=8)
            return

        cols = [
            ("SYM",    9,  "w"),
            ("VENUES", 16, "w"),
            ("REASON", 11, "w"),
            ("HOLD",   6,  "e"),
            ("PNL",    9,  "e"),
        ]
        _, repaint = self._arb_make_table(parent, cols)
        rows = []
        for c in reversed(closed):  # newest first
            pnl = c.get("pnl", 0) or 0
            pnl_fg = GREEN if pnl >= 0 else RED
            venues = f"{c.get('venue_short','')}/{c.get('venue_long','')}"[:16]
            rows.append([
                (c.get("symbol", "")[:9], WHITE),
                (venues, AMBER_D),
                (c.get("exit_reason", "")[:11], DIM),
                (f"{c.get('hours_open', 0):.1f}h", DIM),
                (f"${pnl:+,.2f}", pnl_fg),
            ])
        repaint(rows)

    def _arb_paint_opps(self, arb_cc, arb_dd, arb_cd, basis, spot):
        """Unified OPPS painter — merges 5 opp types, applies filter+score,
        caps at 50 rows, paints with VIAB column."""
        repaint = getattr(self, "_arb_opps_repaint", None)
        if repaint is None:
            return

        # Tag each type
        tagged: list[dict] = []
        for p in (arb_cc or []):
            pp = dict(p); pp["_type"] = "CC"; tagged.append(pp)
        for p in (arb_dd or []):
            pp = dict(p); pp["_type"] = "DD"; tagged.append(pp)
        for p in (arb_cd or []):
            pp = dict(p); pp["_type"] = "CD"; tagged.append(pp)
        for p in (basis or []):
            pp = dict(p); pp["_type"] = "BS"
            # Adapt basis to look like an arb pair for scoring
            pp.setdefault("net_apr", pp.get("basis_apr"))
            pp.setdefault("short_venue", pp.get("venue_perp"))
            pp.setdefault("long_venue", pp.get("venue_spot"))
            pp.setdefault("volume_24h_short", pp.get("volume_perp"))
            pp.setdefault("volume_24h_long", pp.get("volume_spot"))
            pp.setdefault("volume_24h", min(
                pp.get("volume_perp", 0) or 0,
                pp.get("volume_spot", 0) or 0))
            tagged.append(pp)
        for p in (spot or []):
            pp = dict(p); pp["_type"] = "SP"
            # Spot spread: convert bps to rough APR equivalent — treat
            # as a one-shot trade (no funding cycle), so scoring is only
            # meaningful for viewing. Use spread_bps as APR proxy.
            pp.setdefault("net_apr", abs(pp.get("spread_bps", 0) or 0) / 100.0)
            pp.setdefault("short_venue", pp.get("venue_a"))
            pp.setdefault("long_venue", pp.get("venue_b"))
            pp.setdefault("volume_24h_short", pp.get("volume_a"))
            pp.setdefault("volume_24h_long", pp.get("volume_b"))
            pp.setdefault("volume_24h", min(
                pp.get("volume_a", 0) or 0,
                pp.get("volume_b", 0) or 0))
            tagged.append(pp)

        # Apply filter+score (with cache) and render cap
        filtered = self._arb_filter_and_score(tagged)[:50]
        self._arb_opps_selected = [p for p, _ in filtered]

        rows = []
        for a, sr in filtered:
            viab = getattr(sr, "viab", sr.grade)
            if viab == "GO":
                viab_fg = GREEN
            elif viab in ("WAIT", "MAYBE"):
                viab_fg = AMBER
            else:
                viab_fg = DIM
            net_apr = float(a.get("net_apr", 0) or 0)
            apr_fg = GREEN if abs(net_apr) >= 50 else (
                AMBER if abs(net_apr) >= 20 else DIM)
            be = getattr(sr, "breakeven_h", None)
            be_txt = f"{be:.1f}h" if be is not None and be < 999 else "—"
            be_fg = GREEN if (be is not None and be <= 24) else (
                AMBER if (be is not None and be <= 72) else DIM)
            short_v = (a.get("short_venue") or "")[:10].lower()
            long_v = (a.get("long_venue") or "")[:10].lower()
            # Long leg goes first (the one you BUY), then short. Arrow
            # direction (→) reads naturally as "take long from here,
            # short to there". Width 22 fits "binance → bybit" plus
            # slack for longer venue names.
            venues = f"{long_v} → {short_v}"[:22]
            rows.append([
                (viab, viab_fg),
                ((a.get("symbol", "") or "—")[:11], WHITE),
                (venues, AMBER_D),
                (f"{net_apr:+.1f}%", apr_fg),
                (be_txt, be_fg),
                (f"{int(sr.score):>3}", DIM),
            ])
        repaint(rows)

    # -- Engine control shortcuts ------------------------------
    def _arb_engine_start(self, mode: str):
        """Start SimpleArbEngine (in-process, paper mode)."""
        if mode == "demo":
            # Demo/testnet requires venue auth — not supported in the simple
            # in-process engine. Fall back to paper silently.
            mode = "paper"
        engine = getattr(self, "_arb_simple_engine", None)
        if engine is None:
            from core.arb.engine import SimpleArbEngine
            engine = SimpleArbEngine()
            self._arb_simple_engine = engine
        if not engine.running:
            engine.start(mode=mode)
        try:
            self.after(500, lambda: self._arbitrage_hub("engine"))
        except Exception:
            pass

    def _arb_engine_stop(self):
        """Stop the in-process SimpleArbEngine."""
        engine = getattr(self, "_arb_simple_engine", None)
        if engine is not None and engine.running:
            engine.stop()
        try:
            self.after(500, lambda: self._arbitrage_hub("engine"))
        except Exception:
            pass

    # -- Background scan: populates status strip + active tab ----
    _ARB_SCAN_FRESH_SECS = 10  # within this window, skip new scan

    def _arb_scan_is_fresh(self) -> bool:
        """True if last scan is within the fresh window (no need to rescan)."""
        import time as _time
        last = getattr(self, "_arb_last_scan_ts", 0) or 0
        return (_time.time() - last) < self._ARB_SCAN_FRESH_SECS

    def _arb_hub_scan_async(self):
        """Run FundingScanner in a worker thread and push results to the UI.

        The scanner is cached (CACHE_TTL) so hopping between tabs doesn't
        hammer venue APIs. After the scan returns, the status strip is
        always refreshed; the active tab's table is repainted with live
        data via whichever ``_arb_*_repaint`` callback is registered.
        """
        import threading
        if _test_mode_enabled():
            self._ui_call_soon(lambda: self._arb_hub_telem_update(
                {"dex_online": 0, "cex_online": 0, "total": 0},
                None, [], [], [], [], [], []))
            return
        try:
            from core.ui.funding_scanner import FundingScanner
        except Exception as e:
            self._arb_set_status_error(f"scanner unavailable: {str(e)[:40]}")
            return
        scanner = getattr(self, "_funding_scanner", None)
        if scanner is None:
            scanner = FundingScanner()
            self._funding_scanner = scanner

        def _worker():
            try:
                opps = scanner.scan()
                stats = scanner.stats()
                # Lower min_spread_apr from 5% to 1% — the UI filter handles
                # tighter thresholds now; we want the scanner to hand us as
                # many candidates as possible so the post-filter has options
                # to display.
                arb_cc = scanner.arb_pairs(mode="cex-cex", min_spread_apr=1.0)
                arb_dd = scanner.arb_pairs(mode="dex-dex", min_spread_apr=1.0)
                arb_cd = scanner.arb_pairs(mode="cex-dex", min_spread_apr=1.0)
                basis = []
                spot = []
                try:
                    scanner.scan_spot()
                    basis = scanner.basis_pairs(min_basis_bps=5)[:20]
                    spot = scanner.spot_arb_pairs(min_spread_bps=3)[:20]
                except Exception:
                    pass
                top = opps[0] if opps else None
                try:
                    self._ui_call_soon(lambda: self._arb_hub_telem_update(
                        stats, top, opps, arb_cc, arb_dd, arb_cd, basis, spot))
                except (RuntimeError, tk.TclError):
                    # Tk root gone (test teardown / app shutdown) — drop update
                    pass
            except Exception as e:
                try:
                    self._ui_call_soon(lambda: self._arb_set_status_error(
                        f"scan failed: {str(e)[:40]}"))
                except (RuntimeError, tk.TclError):
                    pass

        threading.Thread(target=_worker, daemon=True).start()

    def _arb_set_status_error(self, msg: str):
        """Paint the right side of the status strip with an error tag
        and flip the live dot to red so the scan state is obvious at a
        glance (green = fresh data, red = scan failed, dim = pending)."""
        dot = getattr(self, "_arb_live_dot", None)
        if dot is not None:
            try: dot.configure(fg=RED)
            except Exception: pass
        lbl = getattr(self, "_arb_sum_best", None)
        if lbl is not None:
            try:
                lbl.configure(text=msg, fg=RED)
            except Exception:
                pass

    def _arb_hub_telem_update(self, stats, top, opps, arb_cc, arb_dd, arb_cd,
                               basis, spot):
        """Populate the status strip and the active tab's table.

        stats     : dict from FundingScanner.stats() — dex_online / cex_online
        top       : top FundingOpp across all venues (or None)
        opps      : full list of FundingOpp from scanner.scan()
        arb_cc    : list of CEX↔CEX arb pairs (dict) — paired funding diff
        arb_dd    : list of DEX↔DEX arb pairs
        arb_cd    : list of CEX↔DEX arb pairs
        basis     : list of basis (spot-perp) pairs from scanner.basis_pairs
        spot      : list of spot spread pairs from scanner.spot_arb_pairs

        Each tab renderer registers a repaint callback (e.g. _arb_cex_repaint);
        we only call the one for the currently active tab.
        """
        # Status strip — data flowed in, flip the live dot to green.
        dex_on = (stats or {}).get("dex_online", 0)
        cex_on = (stats or {}).get("cex_online", 0)
        try:
            dot = getattr(self, "_arb_live_dot", None)
            if dot is not None:
                dot.configure(fg=GREEN)
            self._arb_sum_cex.configure(text=f"CEX  {cex_on}", fg=WHITE)
            self._arb_sum_dex.configure(text=f"DEX  {dex_on}", fg=WHITE)
            top_s = "—"
            top_fg = DIM2
            if top is not None and getattr(top, "apr", None) is not None:
                try:
                    apr_v = float(top.apr)
                    top_s = f"{apr_v:+.2f}%"
                    top_fg = GREEN if apr_v > 0 else (RED if apr_v < 0 else DIM2)
                except Exception:
                    pass
            self._arb_sum_best.configure(text=f"TOP  {top_s}", fg=top_fg)
        except Exception:
            pass

        # Cache raw results so tab switches can repaint without rescanning
        import time as _time
        self._arb_last_scan_ts = _time.time()
        self._arb_cache = {
            "stats": stats, "top": top, "opps": opps,
            "arb_cc": arb_cc, "arb_dd": arb_dd, "arb_cd": arb_cd,
            "basis": basis, "spot": spot,
        }
        # Push scan age + engine state into the status strip right away
        try:
            self._arb_update_status_strip()
        except Exception:
            pass

        # Route to the repaint callback for the active tab.
        # Phase 1 redesign: unified OPPS table consolidates 5 old tabs.
        tab = getattr(self, "_arb_tab", "opps")
        if tab == "opps":
            self._arb_paint_opps(arb_cc, arb_dd, arb_cd, basis, spot)
        # positions + history tabs don't consume scanner data directly —
        # they read from _arb_simple_engine via their render fn.

        # Feed SimpleArbEngine — any tab keeps the engine ticking as long
        # as scanner returns data. The engine only processes FUNDING opps
        # (arb_cc + arb_cd) and enriches with per-venue 24h volume from
        # the raw FundingOpp list.
        engine = getattr(self, "_arb_simple_engine", None)
        if engine is not None and engine.running:
            try:
                self._arb_feed_engine(engine, opps, arb_cc + arb_cd)
            except Exception as e:
                # Never let engine errors kill the scan loop
                try:
                    import logging
                    logging.getLogger("aurum.arb_hub").warning(
                        "engine tick failed: %s", e, exc_info=True)
                except Exception:
                    pass

    @staticmethod
    def _arb_feed_engine(engine, raw_opps, arb_pairs_merged):
        """Enrich arb pairs with volume_24h per leg, then tick engine."""
        vol_lookup: dict[tuple[str, str], float] = {}
        for o in raw_opps:
            try:
                vol_lookup[(o.symbol, o.venue)] = float(o.volume_24h)
            except Exception:
                continue
        enriched: list[dict] = []
        for ap in arb_pairs_merged:
            sym = ap.get("symbol")
            short_v = ap.get("short_venue", "")
            long_v = ap.get("long_venue", "")
            ap2 = dict(ap)
            ap2["volume_short"] = vol_lookup.get((sym, short_v), 0)
            ap2["volume_long"] = vol_lookup.get((sym, long_v), 0)
            enriched.append(ap2)
        engine.tick(enriched)

    def _arb_paint_pairs(self, pairs, repaint, selected_attr: str):
        """Render the 9-column pair table with scoring filter applied.

        selected_attr: name of the instance attribute that holds the filtered
        pair list, so click handlers can map row index → pair dict.
        """
        if repaint is None:
            return
        filtered = self._arb_filter_and_score(pairs)[:20]
        # Expose filtered list so _on_click resolves correctly
        setattr(self, selected_attr, [p for p, _ in filtered])

        rows = []
        for i, (a, sr) in enumerate(filtered, 1):
            net_apr = float(a.get("net_apr", 0) or 0)
            apr_fg = GREEN if net_apr >= 20 else (AMBER if net_apr >= 10 else DIM)
            risk = a.get("risk", "\u2014")
            risk_fg = RED if risk == "HIGH" else (AMBER if risk == "MED" else GREEN)
            vol = (a.get("volume_24h") or
                   self._pair_min(a.get("volume_24h_short"),
                                   a.get("volume_24h_long")) or 0)
            oi = (a.get("open_interest") or
                  self._pair_min(a.get("open_interest_short"),
                                  a.get("open_interest_long")) or 0)
            grade_fg = (GREEN if sr.grade == "GO" else
                        AMBER if sr.grade == "MAYBE" else DIM)
            grade_txt = f"{int(sr.score):>2} {sr.grade}"
            rows.append([
                (f"{i:>2}", DIM),
                ((a.get("symbol", "\u2014") or "\u2014")[:7], WHITE),
                ((a.get("long_venue") or "\u2014")[:10].lower(), AMBER_D),
                ((a.get("short_venue") or "\u2014")[:10].lower(), AMBER_D),
                (f"{net_apr:+.1f}%", apr_fg),
                (self._fmt_vol(vol), DIM),
                (self._fmt_vol(oi), DIM),
                (risk, risk_fg),
                (grade_txt, grade_fg),
            ])
        repaint(rows)

    def _arb_paint_basis(self, basis):
        repaint = getattr(self, "_arb_basis_repaint", None)
        if repaint is None:
            return
        # Filter: basis pairs can be scored via arb_scoring — each leg has a
        # net_apr-equivalent (basis_apr). Use the user's APR floor + grade
        # filter; volume/OI filters don't apply (basis data is thinner).
        state = self._arb_filter_state()
        min_apr = state.get("min_apr", 0)
        filtered_list = []
        for p in (basis or []):
            if abs(float(p.get("basis_apr", 0) or 0)) < min_apr:
                continue
            filtered_list.append(p)
        filtered_list = filtered_list[:20]
        self._arb_basis_selected = filtered_list
        rows = []
        for i, p in enumerate(filtered_list, 1):
            bps = p.get("basis_bps", 0)
            bps_fg = GREEN if abs(bps) >= 20 else (AMBER if abs(bps) >= 10 else DIM)
            rows.append([
                (f"{i:>2}", DIM),
                (p.get("symbol", "\u2014")[:7], WHITE),
                (p.get("venue_perp", "\u2014")[:9].lower(), AMBER_D),
                (p.get("venue_spot", "\u2014")[:9].lower(), AMBER_D),
                (f"${p.get('mark_price', 0):,.2f}", DIM),
                (f"${p.get('spot_price', 0):,.2f}", DIM),
                (f"{bps:+.0f}bps", bps_fg),
                (f"{p.get('basis_apr', 0):.0f}%", bps_fg),
            ])
        repaint(rows)

    def _arb_paint_spot(self, spot):
        repaint = getattr(self, "_arb_spot_repaint", None)
        if repaint is None:
            return
        # Spot spreads have bps but no APR; apply a minimum-bps tripwire via
        # the risk filter as a loose proxy — HIGH = =3bps, MED = =8, LOW = =15.
        state = self._arb_filter_state()
        risk_max = state.get("risk_max", "HIGH")
        thresholds = {"HIGH": 3, "MED": 8, "LOW": 15}
        min_bps = thresholds.get(risk_max, 3)
        filtered_list = [p for p in (spot or [])
                         if float(p.get("spread_bps", 0) or 0) >= min_bps][:20]
        self._arb_spot_selected = filtered_list
        rows = []
        for i, p in enumerate(filtered_list, 1):
            bps = p.get("spread_bps", 0)
            bps_fg = GREEN if bps >= 15 else (AMBER if bps >= 8 else DIM)
            rows.append([
                (f"{i:>2}", DIM),
                (p.get("symbol", "\u2014")[:7], WHITE),
                (p.get("venue_a", "\u2014")[:9].lower(), AMBER_D),
                (p.get("venue_b", "\u2014")[:9].lower(), AMBER_D),
                (f"${p.get('price_a', 0):,.4f}", DIM),
                (f"${p.get('price_b', 0):,.4f}", DIM),
                (f"{bps:.1f}bps", bps_fg),
            ])
        repaint(rows)

    # ---------------------------------------------------------------
    # LEGACY SCREENS — thin redirects to the unified ARBITRAGE DESK.
    # The old standalone basis / spot / funding screens were folded into
    # tabs. These stubs keep external call sites working until callers
    # migrate to _arbitrage_hub(tab=…).
    # ---------------------------------------------------------------
    def _arb_basis_screen(self):
        """Redirect: old basis screen → BASIS tab of the unified desk."""
        self._arbitrage_hub(tab="basis")

    def _arb_basis_screen_legacy(self):
        """Spot-perp basis trade screen — shows basis opportunities."""
        self._clr(); self._clear_kb()
        self.history.append("_arbitrage_hub")
        self.h_path.configure(text="> ARBITRAGE > BASIS TRADE")
        self.h_stat.configure(text="SCANNING\u2026", fg=AMBER_D)
        self.f_lbl.configure(text="R refresh  |  ESC back")

        self._kb("<Escape>", lambda: self._arbitrage_hub())
        self._kb("<Key-r>", lambda: self._arb_basis_screen())
        self._bind_global_nav()

        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=12)

        tk.Label(outer, text="BASIS TRADE", font=(FONT, 10, "bold"),
                 fg=AMBER, bg=BG).pack(anchor="center")
        tk.Label(outer, text="spot-perp basis  \u00b7  buy spot, short perp",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="center", pady=(1, 4))
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(4, 4))

        # Table
        cols = [("#", 3, "e"), ("SYMBOL", 8, "w"), ("PERP", 10, "w"),
                ("SPOT", 10, "w"), ("MARK", 10, "e"), ("SPOT$", 10, "e"),
                ("BASIS", 8, "e"), ("APR", 8, "e")]
        hrow = tk.Frame(outer, bg=BG); hrow.pack(fill="x")
        for label, w, anchor in cols:
            tk.Label(hrow, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG, width=w, anchor=anchor).pack(side="left")
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(1, 2))

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="both", expand=True)

        # Fetch basis pairs in background
        import threading
        def _worker():
            try:
                from core.ui.funding_scanner import FundingScanner
                scanner = getattr(self, "_funding_scanner", None)
                if scanner is None:
                    scanner = FundingScanner()
                    self._funding_scanner = scanner
                scanner.scan()
                scanner.scan_spot()
                pairs = scanner.basis_pairs(min_basis_bps=5)[:20]
                self._ui_call_soon(lambda: self._arb_basis_paint(inner, cols, pairs))
            except Exception as e:
                self._ui_call_soon(lambda: tk.Label(inner,
                    text=f"  scan failed: {e}", font=(FONT, 8), fg=RED, bg=BG).pack())
        threading.Thread(target=_worker, daemon=True).start()

    @timed_legacy_switch("arb_basis")
    def _arb_basis_paint(self, inner, cols, pairs):
        for w in inner.winfo_children():
            w.destroy()
        try:
            self.h_stat.configure(text=f"{len(pairs)} BASIS", fg=AMBER)
        except Exception:
            pass
        if not pairs:
            tk.Label(inner, text="  \u2014 no basis opportunities above 5bps \u2014",
                     font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)
            return
        for i, p in enumerate(pairs, 1):
            bg = BG if i % 2 == 1 else BG2
            rf = tk.Frame(inner, bg=bg); rf.pack(fill="x")
            basis_fg = GREEN if abs(p["basis_bps"]) >= 20 else (AMBER if abs(p["basis_bps"]) >= 10 else DIM)
            cells = [
                (f"{i:>3}", DIM), (p["symbol"], WHITE),
                (p["venue_perp"], AMBER_D), (p["venue_spot"], AMBER_D),
                (f"${p['mark_price']:,.2f}", DIM),
                (f"${p['spot_price']:,.2f}", DIM),
                (f"{p['basis_bps']:+.0f}bps", basis_fg),
                (f"{p['basis_apr']:.0f}%", basis_fg),
            ]
            for (txt, fg), (_, w, anchor) in zip(cells, cols):
                tk.Label(rf, text=txt, font=(FONT, 8), fg=fg, bg=bg,
                         width=w, anchor=anchor).pack(side="left")

    # ---------------------------------------------------------------
    # SPOT ↔ SPOT SCREEN — cross-venue spot price divergence
    # ---------------------------------------------------------------
    def _arb_spot_screen(self):
        """Redirect: old spot screen → SPOT tab of the unified desk."""
        self._arbitrage_hub(tab="spot")

    def _arb_spot_screen_legacy(self):
        """Spot-spot spread screen — cross-venue spot price divergence."""
        self._clr(); self._clear_kb()
        self.history.append("_arbitrage_hub")
        self.h_path.configure(text="> ARBITRAGE > SPOT \u2194 SPOT")
        self.h_stat.configure(text="SCANNING\u2026", fg=AMBER_D)
        self.f_lbl.configure(text="R refresh  |  ESC back")

        self._kb("<Escape>", lambda: self._arbitrage_hub())
        self._kb("<Key-r>", lambda: self._arb_spot_screen())
        self._bind_global_nav()

        outer = tk.Frame(self.main, bg=BG)
        outer.pack(fill="both", expand=True, padx=24, pady=12)

        tk.Label(outer, text="SPOT SPREAD", font=(FONT, 10, "bold"),
                 fg=AMBER, bg=BG).pack(anchor="center")
        tk.Label(outer, text="cross-venue spot price divergence",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(anchor="center", pady=(1, 4))
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(4, 4))

        cols = [("#", 3, "e"), ("SYMBOL", 8, "w"), ("VENUE A", 10, "w"),
                ("VENUE B", 10, "w"), ("PRICE A", 12, "e"), ("PRICE B", 12, "e"),
                ("SPREAD", 10, "e")]
        hrow = tk.Frame(outer, bg=BG); hrow.pack(fill="x")
        for label, w, anchor in cols:
            tk.Label(hrow, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG, width=w, anchor=anchor).pack(side="left")
        tk.Frame(outer, bg=BORDER, height=1).pack(fill="x", pady=(1, 2))

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="both", expand=True)

        import threading
        def _worker():
            try:
                from core.ui.funding_scanner import FundingScanner
                scanner = getattr(self, "_funding_scanner", None)
                if scanner is None:
                    scanner = FundingScanner()
                    self._funding_scanner = scanner
                scanner.scan_spot()
                pairs = scanner.spot_arb_pairs(min_spread_bps=3)[:20]
                self._ui_call_soon(lambda: self._arb_spot_paint(inner, cols, pairs))
            except Exception as e:
                self._ui_call_soon(lambda: tk.Label(inner,
                    text=f"  scan failed: {e}", font=(FONT, 8), fg=RED, bg=BG).pack())
        threading.Thread(target=_worker, daemon=True).start()

    @timed_legacy_switch("arb_spot")
    def _arb_spot_paint(self, inner, cols, pairs):
        for w in inner.winfo_children():
            w.destroy()
        try:
            self.h_stat.configure(text=f"{len(pairs)} SPREADS", fg=AMBER)
        except Exception:
            pass
        if not pairs:
            tk.Label(inner, text="  \u2014 no spot spreads above 3bps \u2014",
                     font=(FONT, 8), fg=DIM2, bg=BG).pack(pady=20)
            return
        for i, p in enumerate(pairs, 1):
            bg = BG if i % 2 == 1 else BG2
            rf = tk.Frame(inner, bg=bg); rf.pack(fill="x")
            spread_fg = GREEN if p["spread_bps"] >= 15 else (AMBER if p["spread_bps"] >= 8 else DIM)
            cells = [
                (f"{i:>3}", DIM), (p["symbol"], WHITE),
                (p["venue_a"], AMBER_D), (p["venue_b"], AMBER_D),
                (f"${p['price_a']:,.4f}", DIM), (f"${p['price_b']:,.4f}", DIM),
                (f"{p['spread_bps']:.1f}bps", spread_fg),
            ]
            for (txt, fg), (_, w, anchor) in zip(cells, cols):
                tk.Label(rf, text=txt, font=(FONT, 8), fg=fg, bg=bg,
                         width=w, anchor=anchor).pack(side="left")

    # ---------------------------------------------------------------
    # FUNDING SCANNER SCREEN — shared between DEX-DEX and CEX-DEX modes
    # ---------------------------------------------------------------
    def _funding_scanner_screen(self, mode: str = "dex-dex"):
        """Redirect: old funding scanner → DEX-DEX or CEX-DEX tab."""
        tab = "cex-dex" if mode == "cex-dex" else "dex-dex"
        self._arbitrage_hub(tab=tab)


    def _funding_refresh(self, force: bool = False):
        """Fire a background scan and repaint on completion."""
        if not getattr(self, "_funding_alive", False):
            return
        import threading
        from core.ui.funding_scanner import FundingScanner

        scanner = getattr(self, "_funding_scanner", None)
        if scanner is None:
            scanner = FundingScanner()
            self._funding_scanner = scanner

        try:
            self.h_stat.configure(text="SCANNING\u2026", fg=AMBER_D)
        except Exception:
            pass

        mode = getattr(self, "_funding_mode", "dex-dex")

        def _worker():
            try:
                scanner.scan(force=force)
                stats = scanner.stats()
                if mode == "dex-dex":
                    rows = scanner.top(n=40, min_apr=5.0, venue_type="DEX")
                else:
                    rows = scanner.top(n=40, min_apr=20.0)
                arb = scanner.arb_pairs(mode=mode, min_spread_apr=5.0)[:5]
                # fire optional telegram alerts for the biggest opps
                try:
                    from core.ui.funding_scanner import maybe_alert_telegram
                    maybe_alert_telegram(rows, apr_threshold=100.0)
                except Exception:
                    pass
                self._ui_call_soon(lambda: self._funding_paint(rows, arb, stats))
            except Exception as e:
                self._ui_call_soon(lambda: self._funding_fail(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

        # schedule next auto-refresh (60s) — only once per screen
        if not getattr(self, "_funding_timer_armed", False):
            self._funding_timer_armed = True
            def _tick():
                if not getattr(self, "_funding_alive", False):
                    return
                self._funding_refresh(force=False)
                try:
                    self.after(60_000, _tick)
                except tk.TclError:
                    pass
            self.after(60_000, _tick)

    @timed_legacy_switch("funding_paint")
    def _funding_paint(self, rows, arb, stats):
        """Delegate to launcher_support.screens.funding_paint.render.
        The 170-line score+filter+paint logic for the funding scanner
        opportunities table (and its arb-pairs strip + meta) lives there.
        """
        from launcher_support.screens.funding_paint import render as _render_funding_paint
        _render_funding_paint(self, rows, arb, stats)

    def _funding_fail(self, reason: str):
        if not getattr(self, "_funding_alive", False):
            return
        try:
            self.h_stat.configure(text="SCAN FAILED", fg=RED)
            meta = getattr(self, "_funding_meta", None)
            if meta:
                meta.configure(text=f"  scan failed: {reason[:80]}  ", fg=RED)
        except Exception:
            pass

    def _funding_repaint_filtered(self):
        """Re-run _funding_paint with cached data (called on filter change)."""
        cached = getattr(self, "_funding_cached", None)
        if cached is None:
            return
        rows, arb, stats = cached
        self._funding_paint(rows, arb, stats)

    def _funding_filter_toggle(self):
        """Toggle filter bar visibility (bound to F key)."""
        fbar = getattr(self, "_funding_filter_bar", None)
        if fbar is None:
            return
        try:
            if fbar.winfo_ismapped():
                fbar.pack_forget()
            else:
                fbar.pack(fill="x", pady=(0, 3))
        except tk.TclError:
            pass

    # --- TERMINAL (Layer 2) -------------------------------
    def _terminal(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("terminal")
        try:
            self.focus_set()
        except Exception:
            pass

    def _deploy_pipeline(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("deploy_pipeline")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- DATA CENTER (hub) ---------------------------------
    def _data_center(self):
        """Unified entry point for everything data: backtest metrics,
        running/finished engine logs, and raw report files.

        The hub has three cards. Each card opens a focused screen:

          BACKTESTS  →  crypto-futures dashboard routed to its Backtest tab
                        (reuses _dash_backtest_render + detail panel with
                        OPEN HTML / DELETE buttons).
          ENGINE LOGS → _data_engines (new screen with proc list +
                        live log tail streaming).
          REPORTS    →  legacy _data raw JSON/log file browser.
        """
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("data_center")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- DATA > OHLCV LAKE (cache browser + downloader) -------
    def _data_lake(self):
        """Delegate to launcher_support.screens.data_lake.render. Full
        implementation (split-pane cache browser + download form) lives
        there; this shim keeps the menu-dispatch contract
        (launcher_support/screens/data_center.py uses ``app._data_lake``).
        """
        from launcher_support.screens.data_lake import render as _render_data_lake
        _render_data_lake(self)

    # -- Counts used by the DATA CENTER cards ------------------
    def _data_count_backtests(self) -> int:
        try:
            runs_dir = ROOT / "data" / "runs"
            if runs_dir.exists():
                return sum(1 for d in runs_dir.iterdir() if d.is_dir())
        except OSError:
            pass
        return 0

    def _data_count_procs(self) -> tuple[int, int]:
        try:
            from core.ops.proc import list_procs
            procs = list_procs()
            running = sum(1 for p in procs if p.get("alive"))
            return running, len(procs)
        except Exception:
            return 0, 0

    def _data_count_reports(self) -> int:
        total = 0
        try:
            dd = ROOT / "data"
            if not dd.exists():
                return 0
            for sub in ("runs", "darwin", "arbitrage",
                        "mercurio", "thoth",
                        "prometeu", "multistrategy", "live"):
                p = dd / sub
                if p.exists():
                    total += sum(1 for _ in p.rglob("*.json"))
        except OSError:
            pass
        return total

    # --- DATA > EXPORT ANALYSIS (single-file snapshot) --------
    def _export_analysis(self):
        """Generate a single-file analysis snapshot for external review.

        Runs the aggregation off the Tk main thread because walking
        ``data/runs`` on a populated OneDrive mirror can take a couple
        of seconds. The status bar reflects progress/result; on success
        we also copy the absolute path to the clipboard so the user can
        just Ctrl+V into a Claude.ai upload dialog.
        """
        import threading
        from datetime import datetime
        try:
            self.h_stat.configure(text="GERANDO EXPORT...", fg=AMBER_D)
        except Exception:
            pass

        def _worker():
            try:
                from core.analysis.analysis_export import export_analysis
                ts = datetime.now().strftime("%Y-%m-%d_%H%M")
                out_dir = ROOT / "data" / "exports"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"analysis_{ts}.json"
                export_analysis(output_path=out_path)
                try:
                    size_mb = out_path.stat().st_size / (1024 * 1024)
                except Exception:
                    size_mb = 0.0
                self.after(0, lambda: self._export_analysis_done(out_path, size_mb))
            except Exception as e:
                self.after(0, lambda: self._export_analysis_failed(str(e)))

        threading.Thread(target=_worker, daemon=True).start()

    def _export_analysis_done(self, out_path, size_mb: float):
        try:
            self.h_stat.configure(
                text=f"EXPORT OK · {size_mb:.2f} MB",
                fg=AMBER,
            )
        except Exception:
            pass
        # Best-effort clipboard copy of the absolute path.
        try:
            self.clipboard_clear()
            self.clipboard_append(str(out_path))
        except Exception:
            pass
        try:
            from tkinter import messagebox
            messagebox.showinfo(
                "Analysis Export",
                f"Arquivo gerado ({size_mb:.2f} MB):\n\n{out_path}\n\n"
                "Caminho copiado pro clipboard. "
                "Anexa no Claude.ai e pede pra analisar.",
            )
        except Exception:
            pass

    def _export_analysis_failed(self, reason: str):
        try:
            self.h_stat.configure(text="EXPORT FALHOU", fg=AMBER_D)
        except Exception:
            pass
        try:
            from tkinter import messagebox
            messagebox.showerror("Analysis Export", f"Falhou:\n\n{reason}")
        except Exception:
            pass

    def _open_backtest_metrics(self):
        """Legacy shortcut: jump to the crypto-futures dashboard > Backtest tab.

        Kept for any code path that still wants the tabbed dashboard view.
        The new primary entry for DATA > BACKTESTS is the standalone
        _data_backtests screen — same list, same detail panel, same DELETE
        button, but decoupled from Markets > Crypto Futures navigation.
        """
        self._crypto_dashboard()
        self.after(0, lambda: self._dash_render_tab("backtest"))

    # --- DATA > BACKTESTS (standalone) ------------------------
    def _data_backtests(self):
        """Delegate to launcher_support.screens.data_backtests.render.

        Standalone backtest browser decoupled from the crypto-futures
        tab; reuses the dashboard's shared (bt_list, bt_count, bt_detail)
        widget keys via app._dash_widgets so the existing click handlers
        work without duplication. Reached from DATA CENTER > BACKTESTS.
        """
        from launcher_support.screens.data_backtests import render as _render_data_backtests
        _render_data_backtests(self)

    # --- LIVE RUNS (historico de runs live/paper/shadow/demo/testnet) ----
    def _data_live_runs(self):
        """LIVE RUNS screen — histórico de runs em modos live/paper/shadow/demo/testnet."""
        self._clr(); self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("live_runs")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- RUNS HISTORY (unified database of every run) ------------
    def _data_runs_history(self):
        """Tela institucional de todas as runs via ScreenManager."""
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("runs_history")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- ENGINES — tela unificada (HISTORY / LIVE / LOGS) --------
    def _data_engines(self):
        """Abre /engines — wrapper com chip bar HISTORY/LIVE/LOGS.

        Consolida o que antes eram 3 entradas separadas no DATA CENTER
        (RUNS HISTORY, LIVE RUNS, ENGINE LOGS) numa tela unica com a
        mesma organizacao visual do /backtests. Os 3 sub-screens
        originais continuam registrados, pra atalhos legacy e navegacao
        direta (ex: live_runs -> runs_history via tecla R).
        """
        self._clr(); self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if hasattr(self, "screens") and getattr(self, "screens", None) is not None:
            if not self.screens_container.winfo_manager():
                self.screens_container.pack(fill="both", expand=True)
            self.screens.show("engines")
            try:
                self.focus_set()
            except Exception:
                pass
            return

    @timed_legacy_switch("eng_refresh")
    def _eng_refresh(self):
        """Rebuild the proc list with RUNNING + STOPPED sections, always
        visible. Each section sorted by recency DESC. Reschedules 2s tick."""
        from launcher_support import engine_logs_view

        engine_logs_view.refresh_list(self)

    def _eng_normalize_local_proc(self, proc: dict) -> dict:
        from core.ops import run_catalog

        return run_catalog.normalize_engine_log_local_proc(proc)

    def _eng_known_slugs(self) -> set[str]:
        from core.ops import run_catalog

        try:
            from core.ops.proc import ENGINES as _ENGINES
            proc_engines = _ENGINES
        except Exception:
            proc_engines = {}
        return run_catalog.engine_known_slugs(proc_engines)

    def _eng_base_slug(self, row: dict) -> str:
        from core.ops import run_catalog

        return run_catalog.engine_base_slug(row)

    def _eng_is_engine_row(self, row: dict) -> bool:
        from core.ops import run_catalog

        return run_catalog.is_engine_log_row(
            row,
            known_slugs=self._eng_known_slugs(),
        )

    def _eng_matches_mode_filter(self, row: dict) -> bool:
        from core.ops import run_catalog

        return run_catalog.matches_engine_mode_filter(
            row,
            getattr(self, "_eng_mode_filter", "all"),
        )

    def _eng_row_key(self, row: dict) -> str:
        from core.ops import run_catalog

        return run_catalog.engine_log_row_key(row)

    def _eng_set_mode_filter(self, mode_name: str) -> None:
        self._eng_mode_filter = mode_name
        self._eng_selected_key = None
        self._eng_selected_pid = None
        try:
            self._eng_log_text.config(state="normal")
            self._eng_log_text.delete("1.0", "end")
            self._eng_log_text.config(state="disabled")
            self._eng_log_header.configure(
                text=f" — select an engine log in {mode_name.upper()} — ",
                fg=DIM,
            )
        except Exception:
            pass
        self._eng_refresh()

    def _eng_refresh_filter_tabs(self) -> None:
        from launcher_support import engine_logs_view

        engine_logs_view.refresh_filter_tabs(self)

    def _eng_run_id_of(self, row: dict) -> str | None:
        from core.ops import run_catalog

        return run_catalog.engine_log_run_id_of(row)

    def _eng_recency_key(self, row: dict) -> float:
        """Higher = more recent. Delegated to shared run-catalog helpers."""
        from core.ops import run_catalog

        return run_catalog.engine_log_recency_key(row)

    def _eng_scan_vps_runs(self, limit: int = 10) -> list[dict]:
        """Resolve VPS engine-log rows via the shared run catalog."""
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            from core.ops import run_catalog
            client = _get_cockpit_client()
        except Exception:
            return []
        try:
            return run_catalog.collect_engine_log_vps_rows(client, limit=limit)
        except Exception:
            return []

    def _eng_scan_historical_runs(self, *, limit: int = 15,
                                   hours: int = 48) -> list[dict]:
        """Resolve recent local historical rows via the shared run catalog."""
        now_ts = time.time()
        cached = getattr(self, "_eng_historical_cache", None)
        cached_ts = float(getattr(self, "_eng_historical_cache_ts", 0.0) or 0.0)
        if cached is not None and (now_ts - cached_ts) < 30.0:
            return list(cached[:limit])
        try:
            from core.ops import run_catalog
            result = run_catalog.collect_engine_log_local_rows(
                limit=limit,
                hours=hours,
            )
        except Exception:
            result = []
        self._eng_historical_cache = result
        self._eng_historical_cache_ts = now_ts
        return result[:limit]

    def _eng_render_row(self, proc: dict):
        from launcher_support import engine_logs_view

        engine_logs_view.render_row(self, proc)

    def _eng_uptime_of(self, proc: dict, hb: dict) -> str:
        """Short uptime string (e.g. '2h15m', '45m'). Empty if unknown."""
        from datetime import datetime, timezone
        started_raw = (hb.get("started_at") or proc.get("started_at")
                       or proc.get("started") or "")
        if not started_raw:
            return "—"
        try:
            t0 = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
            if t0.tzinfo is None:
                t0 = t0.replace(tzinfo=timezone.utc)
        except Exception:
            return "—"
        if not proc.get("alive"):
            stopped_raw = hb.get("stopped_at")
            try:
                t1 = datetime.fromisoformat(
                    str(stopped_raw).replace("Z", "+00:00"))
                if t1.tzinfo is None:
                    t1 = t1.replace(tzinfo=timezone.utc)
            except Exception:
                t1 = datetime.now(timezone.utc)
        else:
            t1 = datetime.now(timezone.utc)
        secs = max(0, int((t1 - t0).total_seconds()))
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        hours = secs // 3600
        mins = (secs % 3600) // 60
        return f"{hours}h{mins:02d}m" if hours < 24 else f"{hours // 24}d{hours % 24}h"

    def _eng_select(self, proc: dict):
        from launcher_support import engine_logs_view

        engine_logs_view.select_proc(self, proc)

    def _eng_load_entries(self, proc: dict) -> None:
        from launcher_support import engine_logs_view

        engine_logs_view.load_entries(self, proc)

    def _eng_fetch_entries(self, proc: dict,
                           stop: threading.Event) -> tuple[list[str], str]:
        """Blocking fetch of entries. Returns (formatted_lines, summary)."""
        from core.ops import run_catalog

        if proc.get("_remote"):
            rid = proc.get("_run_id")
            if not rid:
                return [], "no run_id"
            try:
                from launcher_support.engines_live_view import _get_cockpit_client
                client = _get_cockpit_client()
            except Exception:
                return [], "cockpit client unavailable"
            lines, summary = run_catalog.fetch_remote_entries(
                client,
                rid,
                mode=str(proc.get("mode") or "").lower(),
                limit=50,
            )
            if stop.is_set():
                return [], summary
            return lines, summary

        # Local
        rd = proc.get("run_dir")
        lines, summary = run_catalog.read_local_entries(rd, limit=50)
        if stop.is_set():
            return [], summary
        return lines, summary

    def _eng_apply_entries(self, lines: list[str], summary: str) -> None:
        from launcher_support import engine_logs_view

        engine_logs_view.apply_entries(self, lines, summary)

    def _eng_tail_remote_worker(self, run_id: str,
                                stop_event: threading.Event):
        from launcher_support import engine_logs_view

        engine_logs_view.tail_remote_worker(self, run_id, stop_event)

    def _eng_tail_worker(self, log_path: Path, stop_event: threading.Event):
        from launcher_support import engine_logs_view

        engine_logs_view.tail_worker(self, log_path, stop_event)

    def _eng_poll_logs(self):
        from launcher_support import engine_logs_view

        engine_logs_view.poll_logs(self)

    # --- STRATEGIES (Layer 2) -----------------------------
    def _strategies(self, filter_group: str | None = None):
        """Delegate to launcher_support.screens.strategies.render. Full
        engine-picker implementation (title strip, segmented pills,
        counts, picker host + hydrate thread) lives there. Internal
        recursive calls (pill clicks) loop back through this method so
        the segmented nav keeps working via the App surface.
        """
        from launcher_support.screens.strategies import render as _render_strategies
        _render_strategies(self, filter_group=filter_group)

    def _engines_now_playing(self, host, tracks, running_map):
        """NOW PLAYING strip — running live engines as clickable pills above
        the picker. Clicking a pill: focuses that track + opens the LOG chip
        on the right panel so the user lands on the live tail (iPod feel).
        """
        from datetime import datetime as _dt
        bar = tk.Frame(host, bg=BG2,
                       highlightbackground=BORDER, highlightthickness=1)
        bar.pack(fill="x", pady=(0, 6))
        tk.Label(bar, text="  NOW PLAYING ", font=(FONT, 7, "bold"),
                 fg=BG, bg=GREEN, padx=6, pady=2).pack(side="left", padx=(4, 8), pady=4)

        slug_to_idx = {t.slug: i for i, t in enumerate(tracks)}
        for slug, proc in running_map.items():
            idx = slug_to_idx.get(slug)
            if idx is None:
                continue
            name = tracks[idx].name
            mode = (proc.get("engine") or "").upper()
            # Uptime — derive from started timestamp (ISO)
            up_lbl = "—"
            try:
                started = proc.get("started")
                if started:
                    t0 = _dt.fromisoformat(started)
                    secs = (_dt.now() - t0).total_seconds()
                    h, rem = divmod(int(secs), 3600)
                    m, _ = divmod(rem, 60)
                    up_lbl = f"{h}h{m:02d}m" if h else f"{m}m"
            except Exception:
                pass

            pill = tk.Frame(bar, bg=BG3,
                            highlightbackground=GREEN, highlightthickness=1,
                            cursor="hand2")
            pill.pack(side="left", padx=2, pady=4)
            tk.Label(pill, text="●", font=(FONT, 9, "bold"),
                     fg=GREEN, bg=BG3, padx=4).pack(side="left")
            tk.Label(pill, text=name, font=(FONT, 8, "bold"),
                     fg=WHITE, bg=BG3).pack(side="left", padx=(0, 4))
            tk.Label(pill, text=f" {up_lbl} ", font=(FONT, 7),
                     fg=DIM, bg=BG3).pack(side="left")

            def _focus(_e=None, _i=idx):
                handle = getattr(self, "_strategies_picker", None)
                if not handle:
                    return
                try:
                    handle["select_index"](_i)
                except Exception:
                    pass
                try:
                    handle["open_chip"]("LOG")
                except Exception:
                    pass
            for w in (pill,) + tuple(pill.winfo_children()):
                w.bind("<Button-1>", _focus)

    def _strategies_hydrate_metrics(self, tracks, picker_handle=None) -> None:
        """Populate track metrics from the DB. Runs in a background thread
        so the picker renders immediately — metrics fill in shortly after."""
        try:
            import sqlite3
            from pathlib import Path as _P
            db = _P("data/aurum.db")
            if not db.exists():
                return
            # Map slug → engine key in the runs table
            slug_to_engine = {
                "citadel":     "citadel",
                "renaissance": "renaissance",
                "jump":        "jump",
                "bridgewater": "bridgewater",
                "millennium":  "millennium",
                "twosigma":    "twosigma",
                "janestreet":  "janestreet",
                "aqr":         "aqr",
            }
            conn = sqlite3.connect(str(db))
            try:
                # Latest row per engine, ordered by run_id DESC (timestamp-based)
                rows = conn.execute(
                    """
                    SELECT engine, sharpe, sortino, max_dd, win_rate, roi, n_trades
                    FROM runs r
                    WHERE run_id = (
                      SELECT run_id FROM runs r2
                      WHERE r2.engine = r.engine
                      ORDER BY run_id DESC LIMIT 1
                    )
                    """
                ).fetchall()
            finally:
                conn.close()
            by_engine = {r[0]: r for r in rows}
            for t in tracks:
                eng = slug_to_engine.get(t.slug)
                if not eng:
                    continue
                r = by_engine.get(eng)
                if not r:
                    continue
                _, sh, so, dd, wr, roi, nt = r
                try:
                    t.sharpe = float(sh) if sh is not None else None
                    t.sortino = float(so) if so is not None else None
                    t.max_dd = (float(dd) / 100.0) if dd is not None else None
                    t.win_rate = (float(wr) / 100.0) if wr is not None else None
                except (TypeError, ValueError):
                    pass
            # If a picker handle was passed, schedule a refresh on the UI
            # thread so the OVERVIEW chip pulls in the freshly hydrated
            # numbers without the user clicking anything.
            if picker_handle is not None:
                try:
                    self.after(0, picker_handle.get("refresh", lambda: None))
                except Exception:
                    pass
        except Exception:
            return

    def _strategies_backtest(self):
        """Backtest-only entry point (research, no real money)."""
        self._strategies(filter_group="BACKTEST")

    def _strategies_live(self):
        """Live/demo/testnet entry point routed via ScreenManager."""
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("engines_live")
        try:
            self.focus_set()
        except Exception:
            pass

    def _strategies_render_tab(self, tab):
        if not hasattr(self, "_strategies_inner") or self._strategies_inner is None:
            return

        self._clear_kb()
        self._kb("<Escape>", lambda: self._menu("main"))
        self._kb("<Key-0>", lambda: self._menu("main"))
        self._bind_global_nav()

        for idx, (tab_id, _items, _parent_key) in enumerate(getattr(self, "_strategies_sections", []), start=1):
            self._kb(f"<Key-{idx}>", lambda t=tab_id: self._strategies_render_tab(t))

        for tab_id, btn in getattr(self, "_strategies_tab_btns", {}).items():
            btn.configure(fg=AMBER if tab_id == tab else DIM, bg=BG)

        for w in self._strategies_inner.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        items = []
        parent_key = "backtest"
        for section_name, section_items, section_parent in getattr(self, "_strategies_sections", []):
            if section_name == tab:
                items = section_items
                parent_key = section_parent
                break

        sec = self._ui_section(self._strategies_inner, tab, note=f"{len(items)} routes")
        for num, (name, script, desc) in enumerate(items, start=1):
            if num <= 9:
                key_label = str(num)
                key_bind = f"<Key-{num}>"
            else:
                letter_idx = num - 10
                if letter_idx < 26:
                    key_label = chr(ord("a") + letter_idx)
                    key_bind = f"<Key-{key_label}>"
                else:
                    key_label = " "
                    key_bind = None

            cmd = lambda n=name, s=script, d=desc, k=parent_key: self._brief(n, s, d, k)
            row, nl, dl = self._ui_action_row(
                sec, key_label, name, desc,
                command=cmd,
                title_width=16,
            )

            if key_bind:
                self._kb(key_bind, cmd)

    # --- RISK (Layer 2) ----------------------------------
    def _macro_brain_menu(self):
        """Macro Brain cockpit routed via ScreenManager."""
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("macro_brain")
        try:
            self.focus_set()
        except Exception:
            pass

    def _risk_menu(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("risk")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- SPECIAL SCREENS ---------------------------------
    def _special(self, key):
        if key == "data":    self._data()
        elif key == "procs": self._procs()
        elif key == "config": self._config()

    def _data(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("data_reports")
        try:
            self.focus_set()
        except Exception:
            pass

    def _procs(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("processes")
        try:
            self.focus_set()
        except Exception:
            pass

    def _config(self):
        self._clr()
        self._clear_kb()
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("settings")
        try:
            self.focus_set()
        except Exception:
            pass

    # --- CONFIG EDITORS ----------------------------------
    def _cfg_edit(self, title, fields, load_fn, save_fn, back_fn=None):
        back = back_fn or self._config
        self._clr(); self._clear_kb()
        self.h_path.configure(text=f"> CONFIG > {title}")
        self.f_lbl.configure(text="ESC back  |  CTRL+S save")
        self._kb("<Escape>", back)

        _outer, body = self._ui_page_shell(title, "Edit and persist configuration values", content_width=860)
        panel = self._ui_panel_frame(body, "CONFIG EDITOR", "Fields are persisted immediately on save")

        data = load_fn()
        entries = {}
        for key, label, hint, masked in fields:
            row = tk.Frame(panel, bg=BG); row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, width=16, anchor="w").pack(side="left")
            e = tk.Entry(row, bg=BG3, fg=WHITE, font=(FONT, 9), insertbackground=AMBER, border=0,
                         highlightthickness=1, highlightcolor=AMBER_D, highlightbackground=BORDER, width=48)
            e.pack(side="left", fill="x", expand=True, padx=4, ipady=3)
            val = data.get(key, "")
            if val: e.insert(0, str(val))
            if masked: e.configure(show="*")
            if hint: tk.Label(row, text=hint, font=(FONT, 7), fg=DIM2, bg=BG).pack(side="right", padx=4)
            entries[key] = e

        tk.Frame(panel, bg=BG, height=14).pack()
        br = tk.Frame(panel, bg=BG); br.pack(anchor="w")

        def save():
            vals = {k: e.get().strip() for k, e in entries.items()}
            save_fn(vals)
            self.h_stat.configure(text="SAVED", fg=GREEN)
            self.after(1500, lambda: self.h_stat.configure(text="", fg=DIM))
            # Clear Entry widgets so masked values (API keys, tokens) don't
            # linger in the form. User can re-navigate to this screen to see
            # what was stored (load_fn() will re-read from disk).
            for entry_w in entries.values():
                try: entry_w.delete(0, "end")
                except tk.TclError: pass

        sv = tk.Label(br, text="  SAVE  ", font=(FONT, 10, "bold"), fg=BG, bg=GREEN, cursor="hand2", padx=12, pady=3)
        sv.pack(side="left", padx=4); sv.bind("<Button-1>", lambda e: save())
        cn = tk.Label(br, text="  CANCEL  ", font=(FONT, 10), fg=DIM, bg=BG3, cursor="hand2", padx=12, pady=3)
        cn.pack(side="left", padx=4); cn.bind("<Button-1>", lambda e: back())
        self._kb("<Control-s>", save)
        self._ui_note(panel, "CTRL+S saves immediately to the local configuration store.", fg=DIM)

    def _load_json(self, name):
        # keys.json: se store criptografado existir, usa load_runtime_keys
        # (encrypted-first) pra nao ler plaintext stale divergente.
        if name == "keys.json":
            enc_path = ROOT / "config" / "keys.json.enc"
            if enc_path.exists():
                try:
                    from core.risk.key_store import load_runtime_keys, KeyStoreError
                    # Forca fail-closed ignorando AURUM_ALLOW_PLAINTEXT_KEYS.
                    # Se o operador quer editar via launcher, tem que rodar
                    # encrypt_keys.py e passar AURUM_KEY_PASSWORD — nunca
                    # cair em plaintext stale enquanto enc existe.
                    return load_runtime_keys(
                        allow_plaintext_env="_LAUNCHER_NEVER_PLAINTEXT_"
                    )
                except KeyStoreError:
                    runtime_health.record("launcher.keys_locked")
                    return {}
                except Exception:
                    runtime_health.record("launcher.config_load_failure")
                    return {}
        p = ROOT / "config" / name
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f: return json.load(f)
            except Exception:
                runtime_health.record("launcher.config_load_failure")
        return {}

    def _save_json(self, name, data):
        # Bloqueia edicao de keys.json em modo encrypted pra nao criar divergencia
        # silenciosa entre plaintext (launcher) e keys.json.enc (engines/live).
        if name == "keys.json":
            enc_path = ROOT / "config" / "keys.json.enc"
            if enc_path.exists():
                runtime_health.record("launcher.config_save_blocked_encrypted")
                raise RuntimeError(
                    "config/keys.json.enc esta ativo; edicao pelo launcher foi bloqueada. "
                    "Use tools/maintenance/encrypt_keys.py pra atualizar o store criptografado."
                )
        p = ROOT / "config" / name; p.parent.mkdir(parents=True, exist_ok=True)
        try:
            atomic_write_json(p, data, indent=4)
        except OSError:
            runtime_health.record("launcher.config_save_failure")
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

    def _cfg_macro_keys(self):
        """Macro Brain API keys — free/freemium data sources."""
        def load():
            k = self._load_json("keys.json"); m = k.get("macro_brain", {})
            return {
                "fred":    m.get("fred_api_key", ""),
                "newsapi": m.get("newsapi_key", ""),
            }
        def save(v):
            k = self._load_json("keys.json")
            k.setdefault("macro_brain", {})
            k["macro_brain"]["fred_api_key"] = v["fred"]
            k["macro_brain"]["newsapi_key"]  = v["newsapi"]
            self._save_json("keys.json", k)
        self._cfg_edit("MACRO BRAIN APIS", [
            ("fred",    "FRED API KEY",    "free @ stlouisfed.org",       True),
            ("newsapi", "NEWSAPI KEY",     "free 500/day @ newsapi.org",  True),
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

    # --- CRYPTO FUTURES DASHBOARD -------------------------
    def _crypto_dashboard(self):
        """Bloomberg-style dashboard for the crypto futures market.
        Runs all HTTP fetches in a worker thread, refreshes every 30s,
        and is cleaned up automatically by _clr() on any screen change."""
        self._clr(); self._clear_kb()
        self.h_path.configure(text="> MARKETS > CRYPTO FUTURES")
        self.h_stat.configure(text="CONECTANDO...", fg=AMBER_D)
        self.f_lbl.configure(text="ESC voltar  |  H hub  |  R refresh")

        # Lazy imports — fail soft if a module is missing
        try:
            from core.data.market_data import MarketDataFetcher
            from config.params import SYMBOLS as _SYMS
        except Exception as e:
            tk.Label(self.main, text=f"Erro ao iniciar dashboard: {e}",
                     font=(FONT, 9), fg=RED, bg=BG).pack(pady=20)
            self._kb("<Escape>", lambda: self._menu("markets"))
            self._bind_global_nav()
            return

        # Symbol set: ensure BTC is always present so the footer can show its price
        syms = list(_SYMS[:8])
        if "BTCUSDT" not in syms:
            syms = ["BTCUSDT"] + syms[:7]
        self._dash_symbols = syms
        self._dash_fetcher = MarketDataFetcher(syms)
        self._dash_widgets: dict = {}
        self._dash_latency = None
        self._dash_balance = None
        self._dash_alive   = True
        self._dash_after_id = None
        # Tab state
        self._dash_tab = "home"
        self._dash_tab_btns: dict = {}
        self._dash_inner = None
        self._dash_portfolio_account = "paper"  # safe default — always loads
        self._dash_trades_filter = {"result": "all", "symbol": "all"}
        self._dash_trades_page = 0
        # HOME tab aggregated snapshot (populated by _dash_home_fetch_async)
        self._dash_home_snap: dict = {}
        # COCKPIT tab state (VPS remote control)
        self._dash_cockpit_snap: dict = {}
        self._dash_cockpit_stream = None      # subprocess.Popen handle while streaming
        self._dash_cockpit_streaming = False  # bool
        self._dash_cockpit_stream_pending = False

        # Navigation
        self._kb("<Escape>", self._dash_exit_to_markets)
        self._bind_global_nav()
        self._kb("<Key-r>", self._dash_force_refresh)  # override global R
        # Keys 1-5 switch tabs (MARKET removido — quotes ficam no HOME/QUOTE BOARD)
        self._kb("<Key-1>", lambda: self._dash_render_tab("home"))
        self._kb("<Key-2>", lambda: self._dash_render_tab("portfolio"))
        self._kb("<Key-3>", lambda: self._dash_render_tab("trades"))
        self._kb("<Key-4>", lambda: self._dash_render_tab("backtest"))
        self._kb("<Key-5>", lambda: self._dash_render_tab("cockpit"))

        # Layout: sidebar + separator + main column (tab strip + body inner)
        root = tk.Frame(self.main, bg=BG); root.pack(fill="both", expand=True)

        side = tk.Frame(root, bg=PANEL, width=200); side.pack(side="left", fill="y")
        side.pack_propagate(False)
        self._dash_build_sidebar(side)

        tk.Frame(root, bg=BORDER, width=1).pack(side="left", fill="y")

        body = tk.Frame(root, bg=BG); body.pack(side="left", fill="both", expand=True)
        self._dash_build_tabs(body)

        # Mark this market active so the rest of the app sees the choice
        try:
            _get_conn().active_market = "crypto_futures"
        except Exception: pass

        # First tab render kicks off its own fetch loop
        self._dash_render_tab("home")

    # -- DASHBOARD: SIDEBAR --------------------------------
    def _dash_build_sidebar(self, parent):
        """CS 1.6 style sidebar — connection status only, no balance placeholders.
        Two sections: DATA FEEDS (exchanges) and ACCOUNTS (paper/testnet/demo/live)."""

        def section(title):
            tk.Frame(parent, bg=PANEL, height=8).pack(fill="x")
            tk.Label(parent, text=f"[ {title} ]",
                     font=(FONT, 7, "bold"), fg=AMBER, bg=PANEL,
                     anchor="w").pack(fill="x", padx=10)
            tk.Frame(parent, bg=AMBER_D, height=1).pack(fill="x", padx=10, pady=(1, 3))

        # === DATA FEEDS ===
        section("DATA FEEDS")

        _CM, _MARKETS = _lazy_connections()
        exchanges = _MARKETS.get("crypto_futures", {}).get("exchanges", [])
        for ex_key in exchanges:
            info = _get_conn().get(ex_key) or {}
            label = info.get("label", ex_key).upper().replace("BINANCE ", "BINANCE\n")
            is_conn = info.get("connected", False)

            row = tk.Frame(parent, bg=PANEL, cursor="hand2")
            row.pack(fill="x", padx=10, pady=1)

            status_l = tk.Label(row, text="●" if is_conn else "○",
                                font=(FONT, 9, "bold"),
                                fg=GREEN if is_conn else DIM2, bg=PANEL, width=2)
            status_l.pack(side="left")
            name_l = tk.Label(row, text=info.get("label", ex_key).upper(),
                              font=(FONT, 7, "bold"),
                              fg=WHITE if is_conn else DIM, bg=PANEL,
                              anchor="w")
            name_l.pack(side="left", fill="x", expand=True)
            lat_l = tk.Label(row, text="—",
                             font=(FONT, 7), fg=DIM2, bg=PANEL,
                             anchor="e", width=6)
            lat_l.pack(side="right")

            self._dash_widgets[("ex_status",  ex_key)] = status_l
            self._dash_widgets[("ex_name",    ex_key)] = name_l
            self._dash_widgets[("ex_latency", ex_key)] = lat_l

            if ex_key == "binance_futures":
                def _goto_conn(_e=None):
                    self._dash_alive = False
                    self._connections()
                for w in (row, name_l, status_l, lat_l):
                    w.bind("<Button-1>", _goto_conn)
                    w.bind("<Enter>", lambda e, n=name_l: n.configure(fg=AMBER))
                    w.bind("<Leave>", lambda e, n=name_l, c=is_conn:
                           n.configure(fg=WHITE if c else DIM))

        # === ACCOUNTS ===
        section("ACCOUNTS")

        pm = self._get_portfolio_monitor()
        acc_colors = {"paper": AMBER_D, "testnet": GREEN,
                      "demo": AMBER, "live": RED}
        for acc in ("paper", "testnet", "demo", "live"):
            status = pm.status(acc)
            has_keys = status != "no_keys"
            icon = "●" if (has_keys or acc == "paper") else "○"
            icon_col = acc_colors[acc] if (has_keys or acc == "paper") else DIM2

            row = tk.Frame(parent, bg=PANEL, cursor="hand2")
            row.pack(fill="x", padx=10, pady=1)

            status_l = tk.Label(row, text=icon, font=(FONT, 9, "bold"),
                                fg=icon_col, bg=PANEL, width=2)
            status_l.pack(side="left")
            name_l = tk.Label(row, text=acc.upper(), font=(FONT, 7, "bold"),
                              fg=WHITE if (has_keys or acc == "paper") else DIM,
                              bg=PANEL, anchor="w")
            name_l.pack(side="left", fill="x", expand=True)
            hint = "active" if acc == "paper" else ("keys" if has_keys else "—")
            hint_l = tk.Label(row, text=hint, font=(FONT, 7),
                              fg=DIM2, bg=PANEL, anchor="e", width=6)
            hint_l.pack(side="right")
            self._dash_widgets[("acc_status", acc)] = status_l
            self._dash_widgets[("acc_name",   acc)] = name_l
            self._dash_widgets[("acc_hint",   acc)] = hint_l

            def _pick(_e=None, a=acc):
                self._dash_portfolio_account = a
                self._dash_render_tab("portfolio")
            for w in (row, status_l, name_l, hint_l):
                w.bind("<Button-1>", _pick)
                w.bind("<Enter>", lambda e, n=name_l: n.configure(fg=AMBER))
                w.bind("<Leave>", lambda e, n=name_l, h=(has_keys or acc == "paper"):
                       n.configure(fg=WHITE if h else DIM))

        # === MARKET footer ===
        tk.Frame(parent, bg=PANEL).pack(fill="both", expand=True)
        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x", padx=10)
        st = _get_conn().status_summary()
        tk.Label(parent, text=f"market: {st['market']}",
                 font=(FONT, 7), fg=AMBER_D, bg=PANEL,
                 anchor="w").pack(fill="x", padx=10, pady=(4, 0))
        tk.Label(parent, text="R refresh   ESC back",
                 font=(FONT, 7), fg=DIM2, bg=PANEL,
                 anchor="w").pack(fill="x", padx=10, pady=(0, 8))

        # Start a background sidebar pinger that updates latencies every 15s
        self._dash_sidebar_ping_start()

    def _dash_sidebar_ping_start(self):
        """Background thread that pings binance_futures every 15s and updates
        the sidebar widgets on the main thread. Stops when dashboard dies."""
        def _alive_widget(key):
            """Return widget only if it's still packed and usable."""
            w = self._dash_widgets.get(key) if self._dash_widgets is not None else None
            if w is None:
                return None
            try:
                if w.winfo_exists():
                    return w
            except Exception:
                pass
            return None

        def loop():
            while getattr(self, "_dash_alive", False):
                try:
                    lat = _get_conn().ping("binance_futures")
                except Exception:
                    lat = None
                def apply(lat=lat):
                    if not getattr(self, "_dash_alive", False):
                        return
                    status_l = _alive_widget(("ex_status", "binance_futures"))
                    lat_l    = _alive_widget(("ex_latency", "binance_futures"))
                    name_l   = _alive_widget(("ex_name", "binance_futures"))
                    try:
                        if lat is not None:
                            if status_l: status_l.configure(text="●", fg=GREEN)
                            if lat_l:    lat_l.configure(text=f"{int(lat)}ms", fg=DIM)
                            if name_l:   name_l.configure(fg=WHITE)
                        else:
                            if status_l: status_l.configure(text="○", fg=RED)
                            if lat_l:    lat_l.configure(text="—", fg=DIM2)
                    except tk.TclError:
                        # Widget was destroyed between winfo_exists and configure
                        pass
                try: self.after(0, apply)
                except Exception: pass
                # Sleep 15s in small chunks so we exit quickly when _dash_alive flips
                for _ in range(30):
                    if not getattr(self, "_dash_alive", False):
                        return
                    time.sleep(0.5)

        threading.Thread(target=loop, daemon=True).start()

    # -- DASHBOARD: MAIN COLUMN ----------------------------
    def _dash_section_header(self, parent, text):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(0, 3))
        tk.Label(head, text=text, font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG, anchor="w").pack(side="left")
        tk.Frame(head, bg=DIM2, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0), pady=(6, 0))

    def _dash_build_market_tab(self, parent):
        inner = tk.Frame(parent, bg=BG); inner.pack(fill="both", expand=True, padx=14, pady=10)

        # === MARKET OVERVIEW ===
        self._dash_section_header(inner, "MARKET OVERVIEW")
        ov = tk.Frame(inner, bg=BG); ov.pack(fill="x", pady=(2, 8))
        for sym in self._dash_symbols:
            row = tk.Frame(ov, bg=BG, cursor="hand2"); row.pack(fill="x", pady=1)
            short = sym.replace("USDT", "")
            sym_l   = tk.Label(row, text=short, font=(FONT, 9, "bold"),
                               fg=AMBER, bg=BG, width=8, anchor="w")
            sym_l.pack(side="left")
            price_l = tk.Label(row, text="loading...", font=(FONT, 9),
                               fg=DIM, bg=BG, width=14, anchor="w")
            price_l.pack(side="left")
            pct_l   = tk.Label(row, text="—", font=(FONT, 9),
                               fg=DIM, bg=BG, width=10, anchor="w")
            pct_l.pack(side="left")
            bar_l   = tk.Label(row, text="¦" * 10, font=(FONT, 9),
                               fg=DIM, bg=BG, anchor="w")
            bar_l.pack(side="left")
            extra_l = tk.Label(row, text="", font=(FONT, 8),
                               fg=DIM, bg=BG, anchor="w")
            extra_l.pack(side="left", padx=(8, 0))

            self._dash_widgets[("ticker", sym)] = {
                "row": row, "sym": sym_l, "price": price_l,
                "pct": pct_l, "bar": bar_l, "extra": extra_l,
            }

            def _flash(_e=None, l=sym_l):
                l.configure(fg=AMBER_B)
                self.after(180, lambda: l.configure(fg=AMBER))
            for w in (row, sym_l, price_l, pct_l, bar_l, extra_l):
                w.bind("<Button-1>", _flash)
                w.bind("<Enter>", lambda e, r=row: r.configure(bg=BG3))
                w.bind("<Leave>", lambda e, r=row: r.configure(bg=BG))

        # === TOP MOVERS ===
        self._dash_section_header(inner, "TOP MOVERS (24h)")
        movers = tk.Frame(inner, bg=BG); movers.pack(fill="x", pady=(2, 8))
        up_l = tk.Label(movers, text="↑ —", font=(FONT, 8),
                        fg=GREEN, bg=BG, anchor="w")
        up_l.pack(fill="x")
        dn_l = tk.Label(movers, text="↓ —", font=(FONT, 8),
                        fg=RED, bg=BG, anchor="w")
        dn_l.pack(fill="x")
        self._dash_widgets[("movers_up",)] = up_l
        self._dash_widgets[("movers_dn",)] = dn_l

        # === SENTIMENTO ===
        self._dash_section_header(inner, "SENTIMENTO")
        sent = tk.Frame(inner, bg=BG); sent.pack(fill="x", pady=(2, 8))

        fng_l = tk.Label(sent, text="Fear & Greed: —",
                         font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        fng_l.pack(fill="x")
        self._dash_widgets[("fng",)] = fng_l

        dom_l = tk.Label(sent, text="BTC Dominance: — (requer CoinGlass API)",
                         font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        dom_l.pack(fill="x")
        self._dash_widgets[("dom",)] = dom_l

        fund_l = tk.Label(sent, text="Funding AVG: —",
                          font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        fund_l.pack(fill="x")
        self._dash_widgets[("fund",)] = fund_l

        oi_l = tk.Label(sent, text="OI Total: — (requer CoinGlass API)",
                        font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        oi_l.pack(fill="x")
        self._dash_widgets[("oi",)] = oi_l

        ls_l = tk.Label(sent, text="Long/Short Ratio: —",
                        font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        ls_l.pack(fill="x")
        self._dash_widgets[("ls",)] = ls_l

        # === COMING SOON ===
        self._dash_section_header(inner, "COMING SOON")
        cs = tk.Frame(inner, bg=BG); cs.pack(fill="x", pady=(2, 8))
        items = [
            "News Feed (crypto headlines)",
            "Liquidation Heatmap",
            "Correlation Matrix real-time",
            "Volatility Surface (ATR por TF)",
            "On-chain Metrics (Glassnode)",
            "Order Flow Imbalance (bookmap-style)",
        ]
        for item in items:
            row = tk.Frame(cs, bg=BG, cursor="hand2"); row.pack(fill="x")
            l = tk.Label(row, text=f"  □ {item}", font=(FONT, 8),
                         fg=DIM, bg=BG, anchor="w")
            l.pack(fill="x")
            def _coming(_e=None, label=l):
                self.h_stat.configure(text="Em desenvolvimento", fg=AMBER_D)
                label.configure(fg=AMBER_D)
                self.after(700, lambda: label.configure(fg=DIM))
            for w in (row, l):
                w.bind("<Button-1>", _coming)
                w.bind("<Enter>", lambda e, x=l: x.configure(fg=AMBER))
                w.bind("<Leave>", lambda e, x=l: x.configure(fg=DIM))

    # -- DASHBOARD: ASYNC FETCH + APPLY --------------------
    def _dash_fetch_async(self):
        """Run market data fetch + ping in a daemon thread, then post results to UI."""
        if not getattr(self, "_dash_alive", False):
            return

        def worker():
            try:
                self._dash_fetcher.fetch_all()
            except Exception:
                pass
            try:
                self._dash_latency = _get_conn().ping("binance_futures")
            except Exception:
                self._dash_latency = None
            try:
                self._dash_balance = _get_conn().get_balance("binance_futures")
            except Exception:
                self._dash_balance = None
            if getattr(self, "_dash_alive", False):
                try:
                    self.after(0, self._dash_apply)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_apply(self):
        """Apply the latest snapshot to the UI. Runs on the main thread.
        Only touches the MARKET tab widgets — silently no-ops if the user
        has switched tabs (the widgets registered in _dash_widgets were
        destroyed by the rebuild)."""
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "market") != "market":
            return

        snap = self._dash_fetcher.snapshot()
        tickers = snap["tickers"]
        fng     = snap["fear_greed"]

        # -- header status --
        if tickers:
            self.h_stat.configure(text="LIVE", fg=GREEN)
        else:
            self.h_stat.configure(text="OFFLINE", fg=RED)

        # -- sidebar: binance status + latency --
        bf_status = self._dash_widgets.get(("ex_status", "binance_futures"))
        bf_lat    = self._dash_widgets.get(("ex_latency", "binance_futures"))
        bf_name   = self._dash_widgets.get(("ex_name", "binance_futures"))
        if bf_status and bf_lat:
            if self._dash_latency is not None:
                bf_status.configure(text="●", fg=GREEN)
                bf_lat.configure(text=f"{int(self._dash_latency)}ms", fg=DIM)
                if bf_name: bf_name.configure(fg=WHITE)
            else:
                bf_status.configure(text="○", fg=RED)
                bf_lat.configure(text="—", fg=DIM2)

        # Balance/wallets widgets were removed from the sidebar — nothing to update.

        # -- market overview rows --
        for sym in self._dash_symbols:
            w = self._dash_widgets.get(("ticker", sym))
            if not w:
                continue
            t = tickers.get(sym)
            if t:
                sign  = "+" if t["pct"] >= 0 else ""
                color = GREEN if t["pct"] >= 0 else RED
                w["price"].configure(text=f"${t['price']:,.4f}".rstrip("0").rstrip(".") if t['price'] < 10 else f"${t['price']:,.2f}", fg=WHITE)
                w["pct"].configure(text=f"{sign}{t['pct']:.2f}%", fg=color)
                clamp = max(-1.0, min(1.0, t["pct"] / 5.0))
                n_filled = int(round((clamp + 1) / 2 * 10))
                w["bar"].configure(text="¦" * n_filled + "¦" * (10 - n_filled), fg=color)
                vol_b = t["vol"] / 1e9
                extra = f"vol24h ${vol_b:.2f}B" if vol_b >= 1 else f"vol24h ${t['vol']/1e6:.0f}M"
                w["extra"].configure(text=extra, fg=DIM)
            else:
                w["price"].configure(text="—", fg=DIM)
                w["pct"].configure(text="offline", fg=DIM)
                w["bar"].configure(text="¦" * 10, fg=DIM)
                w["extra"].configure(text="")

        # -- top movers --
        sorted_t = sorted(tickers.items(), key=lambda kv: kv[1]["pct"], reverse=True)
        up3 = sorted_t[:3]
        dn3 = sorted_t[-3:][::-1] if len(sorted_t) >= 3 else []

        def _fmt_movers(items, prefix):
            if not items:
                return f"{prefix} —"
            parts = []
            for sym, t in items:
                short = sym.replace("USDT", "")
                sign = "+" if t["pct"] >= 0 else ""
                parts.append(f"{short} {sign}{t['pct']:.1f}%")
            return f"{prefix}  " + "    ".join(parts)

        up_l = self._dash_widgets.get(("movers_up",))
        dn_l = self._dash_widgets.get(("movers_dn",))
        if up_l: up_l.configure(text=_fmt_movers(up3, "↑"))
        if dn_l: dn_l.configure(text=_fmt_movers(dn3, "↓"))

        # -- sentimento --
        fng_l = self._dash_widgets.get(("fng",))
        if fng_l:
            if fng:
                v = fng["value"]; c = fng["classification"]
                n_filled = max(0, min(10, int(round(v / 10))))
                bar = "¦" * n_filled + "¦" * (10 - n_filled)
                color = GREEN if v >= 60 else (RED if v <= 40 else AMBER)
                fng_l.configure(text=f"Fear & Greed: {v} ({c})  {bar}", fg=color)
            else:
                fng_l.configure(text="Fear & Greed: — (offline)", fg=DIM)

        fund_l = self._dash_widgets.get(("fund",))
        if fund_l:
            avg = self._dash_fetcher.funding_avg()
            if avg is not None:
                sign = "+" if avg >= 0 else ""
                tone = ("ligeiramente bullish" if avg > 0 else
                        "ligeiramente bearish" if avg < 0 else "neutro")
                fund_l.configure(
                    text=f"Funding AVG: {sign}{avg*100:.4f}% ({tone})",
                    fg=GREEN if avg >= 0 else RED)
            else:
                fund_l.configure(text="Funding AVG: —", fg=DIM)

        ls_l = self._dash_widgets.get(("ls",))
        if ls_l:
            ls = snap["ls_ratio"]
            if ls is not None:
                tone  = ("mais longs"  if ls > 1.05 else
                         "mais shorts" if ls < 0.95 else "equilibrado")
                color = GREEN if ls > 1.05 else (RED if ls < 0.95 else AMBER)
                ls_l.configure(text=f"Long/Short Ratio: {ls:.2f} ({tone})", fg=color)
            else:
                ls_l.configure(text="Long/Short Ratio: —", fg=DIM)

        # -- footer summary --
        btc_t = tickers.get("BTCUSDT")
        btc_str = f"BTC ${btc_t['price']:,.0f}" if btc_t else "BTC —"
        fng_str = f"Fear {fng['value']}" if fng else "Fear —"
        upd     = (snap["last_update"].strftime("%H:%M:%S")
                   if snap["last_update"] else "—")
        self.f_lbl.configure(
            text=(f"CRYPTO FUTURES · {len(self._dash_symbols)} ativos · "
                  f"{btc_str} · {fng_str} · upd {upd} · refresh 30s · "
                  f"ESC voltar  R refresh")
        )

        # -- schedule next market refresh (only while still on this tab) --
        if getattr(self, "_dash_alive", False) and getattr(self, "_dash_tab", "market") == "market":
            aid = getattr(self, "_dash_after_id", None)
            if aid:
                try: self.after_cancel(aid)
                except Exception: pass
            self._dash_after_id = self.after(30000, self._dash_tick_refresh)

    def _dash_tick_refresh(self):
        """Tab-aware periodic refresher. Each tab uses its own interval and
        the per-tab apply functions schedule the next call."""
        if not getattr(self, "_dash_alive", False):
            return
        self._dash_after_id = None
        tab = getattr(self, "_dash_tab", "home")
        if tab == "home":
            self._dash_home_fetch_async()
        elif tab == "market":
            self._dash_fetch_async()
        elif tab == "portfolio":
            self._dash_portfolio_fetch_async()
        elif tab == "trades":
            self._dash_trades_render()
            self._dash_after_id = self.after(30000, self._dash_tick_refresh)
        elif tab == "cockpit":
            self._dash_cockpit_fetch_async()

    def _dash_force_refresh(self):
        if not getattr(self, "_dash_alive", False):
            return
        self.h_stat.configure(text="REFRESHING...", fg=AMBER_D)
        aid = getattr(self, "_dash_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._dash_after_id = None
        tab = getattr(self, "_dash_tab", "home")
        if tab == "home":
            self._dash_home_fetch_async()
        elif tab == "market":
            self._dash_fetch_async()
        elif tab == "portfolio":
            self._dash_portfolio_fetch_async()
        elif tab == "trades":
            self._dash_trades_render()
        elif tab == "backtest":
            self._dash_backtest_render()
        elif tab == "cockpit":
            self._dash_cockpit_fetch_async()

    # -- DASHBOARD: TABS (MARKET / PORTFOLIO / TRADES / ENGINES) --
    def _get_portfolio_monitor(self):
        pm = getattr(self, "_dash_pm", None)
        if pm is None:
            from core.ui.portfolio_monitor import PortfolioMonitor
            pm = PortfolioMonitor()
            self._dash_pm = pm
        return pm

    def _dash_build_tabs(self, parent):
        """Build the tab strip + an empty body_inner the tabs render into."""
        strip = tk.Frame(parent, bg=BG, height=30); strip.pack(fill="x")
        strip.pack_propagate(False)

        tabs = [
            ("home",      "HOME",      "1"),
            ("portfolio", "PORTFOLIO", "2"),
            ("trades",    "TRADES",    "3"),
            ("backtest",  "BACKTEST",  "4"),
            ("cockpit",   "COCKPIT",   "5"),
        ]
        self._dash_tab_btns = {}
        for tab_id, label, key in tabs:
            btn = tk.Label(
                strip, text=f" {key} {label} ",
                font=(FONT, 9, "bold"),
                fg=DIM, bg=BG, padx=10, pady=5, cursor="hand2",
            )
            btn.pack(side="left", padx=(0, 10), pady=1)
            btn.bind("<Button-1>", lambda e, t=tab_id: self._dash_render_tab(t))
            self._dash_tab_btns[tab_id] = btn

        tk.Frame(parent, bg=DIM2, height=1).pack(fill="x")
        self._dash_inner = tk.Frame(parent, bg=BG)
        self._dash_inner.pack(fill="both", expand=True)

    def _dash_render_tab(self, tab):
        """Switch active tab: clear body_inner, set state, build the tab body,
        kick off its initial fetch + reschedule under the new tab."""
        if not getattr(self, "_dash_alive", False):
            return
        if self._dash_inner is None:
            return

        # Cancel any pending refresh from the previous tab
        aid = getattr(self, "_dash_after_id", None)
        if aid:
            try: self.after_cancel(aid)
            except Exception: pass
        self._dash_after_id = None

        self._dash_tab = tab

        # Repaint tab buttons
        for tab_id, btn in self._dash_tab_btns.items():
            if tab_id == tab:
                btn.configure(bg=BG, fg=AMBER)
            else:
                btn.configure(bg=BG, fg=DIM)

        # Reset widget registry per tab so apply() never writes into stale handles
        self._dash_widgets = {}

        for w in self._dash_inner.winfo_children():
            try: w.destroy()
            except Exception: pass

        # Kill any in-flight log stream if user leaves cockpit
        if tab != "cockpit":
            self._dash_cockpit_kill_stream()
        # Note: backtest mousewheel is scoped via Enter/Leave on its canvas,
        # so no global unbind is needed on tab switch.

        if tab == "home":
            self._dash_build_home_tab(self._dash_inner)
            self._dash_home_fetch_async()
        elif tab == "portfolio":
            self._dash_build_portfolio_tab(self._dash_inner)
            self._dash_portfolio_fetch_async()
        elif tab == "trades":
            self._dash_build_trades_tab(self._dash_inner)
            self._dash_after_id = self.after(30000, self._dash_tick_refresh)
        elif tab == "backtest":
            self._dash_build_backtest_tab(self._dash_inner)
            # On-demand refresh only — no periodic loop.
        elif tab == "cockpit":
            self._dash_build_cockpit_tab(self._dash_inner)
            self._dash_cockpit_fetch_async()

    # -- PORTFOLIO TAB -------------------------------------
    def _dash_build_portfolio_tab(self, parent):
        pm = self._get_portfolio_monitor()

        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True)

        # Inner accounts column
        col = tk.Frame(wrap, bg=PANEL, width=170); col.pack(side="left", fill="y")
        col.pack_propagate(False)

        tk.Label(col, text=" ACCOUNTS ", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w").pack(fill="x", padx=10, pady=(10, 4))
        tk.Frame(col, bg=DIM2, height=1).pack(fill="x", padx=10)

        accounts = [
            ("testnet", "TESTNET", GREEN),
            ("demo",    "DEMO",    AMBER),
            ("live",    "LIVE",    RED),
            ("paper",   "PAPER",   DIM),
        ]
        self._dash_widgets[("portfolio_account_btns",)] = {}
        for acc_id, label, color in accounts:
            status = pm.status(acc_id)
            row = tk.Frame(col, bg=PANEL, cursor="hand2")
            row.pack(fill="x", padx=8, pady=(6, 0))
            icon = "●" if status in ("live", "paper") else "○"
            icon_color = color if status in ("live", "paper") else DIM

            top_l = tk.Label(row, text=f"{icon} {label}", font=(FONT, 9, "bold"),
                             fg=WHITE if status in ("live", "paper") else DIM,
                             bg=PANEL, anchor="w")
            top_l.pack(fill="x")
            tk.Label(row, text=icon, font=(FONT, 7), fg=icon_color,
                     bg=PANEL).place(in_=top_l, x=-2, y=2)

            sub_l = tk.Label(row, text="…",
                             font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w")
            sub_l.pack(fill="x")
            self._dash_widgets[("portfolio_account_btns",)][acc_id] = (row, top_l, sub_l)

            def _click(_e=None, a=acc_id):
                self._dash_portfolio_account = a
                self._dash_portfolio_fetch_async()
                self._dash_portfolio_repaint_account_btns()
            for w in (row, top_l, sub_l):
                w.bind("<Button-1>", _click)
                w.bind("<Enter>", lambda e, l=top_l, s=status:
                       l.configure(fg=AMBER))
                w.bind("<Leave>", lambda e, l=top_l, s=status:
                       l.configure(fg=WHITE if s in ("live", "paper") else DIM))

        self._dash_portfolio_repaint_account_btns()

        # Right details panel — built/refreshed by _dash_portfolio_render
        details = tk.Frame(wrap, bg=BG)
        details.pack(side="left", fill="both", expand=True, padx=12, pady=10)
        self._dash_widgets[("portfolio_details",)] = details

        # Cached-first: if we have a snapshot for the active account, render it
        # immediately instead of showing a "Loading..." placeholder. The async
        # refresh will replace it as soon as fresh data arrives.
        mode = getattr(self, "_dash_portfolio_account", "paper")
        if pm.get_cached(mode) is not None:
            # Defer render so the details frame is fully packed first
            self.after(0, self._dash_portfolio_render)
        else:
            tk.Label(details, text="Loading account…",
                     font=(FONT, 9), fg=DIM, bg=BG).pack(pady=20)

    def _dash_portfolio_repaint_account_btns(self):
        btns = self._dash_widgets.get(("portfolio_account_btns",)) or {}
        active = getattr(self, "_dash_portfolio_account", "paper")
        pm = self._get_portfolio_monitor()
        for acc_id, (row, top_l, sub_l) in btns.items():
            cached = pm.get_cached(acc_id) or {}
            status = pm.status(acc_id)
            if status == "no_keys":
                sub_l.configure(text="sem keys", fg=DIM)
            elif status == "paper":
                eq = cached.get("equity", 0) or 0
                sub_l.configure(text=f"${eq:,.0f}", fg=AMBER_D)
            else:
                eq = cached.get("equity")
                if eq is None:
                    sub_l.configure(text="…", fg=DIM)
                else:
                    sub_l.configure(text=f"${eq:,.2f}", fg=GREEN)
            row.configure(bg=BG3 if acc_id == active else PANEL)
            top_l.configure(bg=BG3 if acc_id == active else PANEL)
            sub_l.configure(bg=BG3 if acc_id == active else PANEL)

    def _dash_portfolio_fetch_async(self):
        if not getattr(self, "_dash_alive", False):
            return
        if getattr(self, "_dash_tab", "market") != "portfolio":
            return
        mode = getattr(self, "_dash_portfolio_account", "paper")
        pm = self._get_portfolio_monitor()

        def worker():
            try:
                pm.refresh(mode)
            except Exception:
                pass
            if getattr(self, "_dash_alive", False):
                try: self.after(0, self._dash_portfolio_render)
                except Exception: pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_portfolio_render(self):
        """Delegate to launcher_support.screens.dash_portfolio.render. Full
        rendering (header KPIs, positions, equity canvas, trades, metrics,
        running engines, 15s re-schedule) lives there.
        """
        from launcher_support.screens.dash_portfolio import render as _render_dash_portfolio
        _render_dash_portfolio(self)

    def _dash_draw_equity_canvas(self, canvas, eq):
        try:
            canvas.delete("all")
            w = canvas.winfo_width() or 600
            h = canvas.winfo_height() or 140
        except Exception:
            return
        if not eq or len(eq) < 2:
            try:
                canvas.create_text(w // 2, h // 2, text="(no equity data)",
                                   fill=DIM, font=(FONT, 9))
            except Exception:
                pass
            return
        pad_l, pad_r, pad_t, pad_b = 56, 14, 10, 16
        inner_w = max(1, w - pad_l - pad_r)
        inner_h = max(1, h - pad_t - pad_b)
        try:
            vmin = min(eq) * 0.998
            vmax = max(eq) * 1.002
        except (TypeError, ValueError):
            return
        vspan = (vmax - vmin) or 1.0
        n = len(eq)

        # Grid + Y labels
        for i in range(5):
            frac = i / 4
            v = vmax - frac * vspan
            y = pad_t + frac * inner_h
            canvas.create_line(pad_l, y, w - pad_r, y, fill=DIM2)
            canvas.create_text(pad_l - 4, y, text=f"${v:,.0f}",
                               fill=DIM, font=(FONT, 7), anchor="e")

        # Polyline
        coords = []
        for i, v in enumerate(eq):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            x = pad_l + (i / max(n - 1, 1)) * inner_w
            y = pad_t + (1 - (fv - vmin) / vspan) * inner_h
            coords.extend([x, y])
        if len(coords) >= 4:
            canvas.create_line(coords, fill="#58a6ff", width=2)

        # High water mark
        try:
            hwm = max(eq)
            y_hwm = pad_t + (1 - (hwm - vmin) / vspan) * inner_h
            canvas.create_line(pad_l, y_hwm, w - pad_r, y_hwm,
                               fill=GREEN, dash=(4, 4))
        except Exception:
            pass

    # -- TRADES TAB -----------------------------------------
    def _dash_build_trades_tab(self, parent):
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=12, pady=10)

        # Filter row
        filt = tk.Frame(wrap, bg=BG); filt.pack(fill="x", pady=(0, 6))
        tk.Label(filt, text="FILTROS:", font=(FONT, 8, "bold"),
                 fg=AMBER, bg=BG).pack(side="left", padx=(0, 6))

        for tag in ("all", "win", "loss"):
            label = tag.upper()
            btn = tk.Label(filt, text=f" {label} ", font=(FONT, 8, "bold"),
                           fg=BG if self._dash_trades_filter["result"] == tag else DIM,
                           bg=AMBER if self._dash_trades_filter["result"] == tag else BG3,
                           padx=8, pady=2, cursor="hand2")
            btn.pack(side="left", padx=2)
            def _click(_e=None, t=tag):
                self._dash_trades_filter["result"] = t
                self._dash_trades_page = 0
                self._dash_render_tab("trades")
            btn.bind("<Button-1>", _click)

        tk.Label(filt, text="  Conta:", font=(FONT, 8),
                 fg=DIM, bg=BG).pack(side="left", padx=(10, 4))
        accs = ("paper", "testnet", "demo", "live")
        for a in accs:
            active = self._dash_portfolio_account == a
            btn = tk.Label(filt, text=f" {a.upper()} ", font=(FONT, 8, "bold"),
                           fg=BG if active else DIM,
                           bg=AMBER if active else BG3,
                           padx=6, pady=2, cursor="hand2")
            btn.pack(side="left", padx=1)
            def _aclick(_e=None, x=a):
                self._dash_portfolio_account = x
                # Make sure we have data for this account
                pm = self._get_portfolio_monitor()
                if pm.get_cached(x) is None:
                    threading.Thread(target=lambda m=x: pm.refresh(m), daemon=True).start()
                self._dash_trades_page = 0
                self._dash_render_tab("trades")
            btn.bind("<Button-1>", _aclick)

        # Table
        tbl = tk.Frame(wrap, bg=PANEL,
                       highlightbackground=BORDER, highlightthickness=1)
        tbl.pack(fill="both", expand=True)
        self._dash_widgets[("trades_table",)] = tbl

        # Footer (page nav)
        nav = tk.Frame(wrap, bg=BG); nav.pack(fill="x", pady=(6, 0))
        prev_btn = tk.Label(nav, text=" ◄ prev ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG3, padx=8, pady=2, cursor="hand2")
        prev_btn.pack(side="left", padx=2)
        prev_btn.bind("<Button-1>", lambda e: self._dash_trades_page_change(-1))
        page_lbl = tk.Label(nav, text="", font=(FONT, 8), fg=DIM, bg=BG)
        page_lbl.pack(side="left", padx=8)
        next_btn = tk.Label(nav, text=" next ► ", font=(FONT, 8, "bold"),
                            fg=AMBER, bg=BG3, padx=8, pady=2, cursor="hand2")
        next_btn.pack(side="left", padx=2)
        next_btn.bind("<Button-1>", lambda e: self._dash_trades_page_change(+1))
        stats_lbl = tk.Label(nav, text="", font=(FONT, 8), fg=DIM, bg=BG)
        stats_lbl.pack(side="right")
        self._dash_widgets[("trades_page",)]  = page_lbl
        self._dash_widgets[("trades_stats",)] = stats_lbl

        # Initial render
        self._dash_trades_render()

    def _dash_trades_page_change(self, delta):
        self._dash_trades_page = max(0, self._dash_trades_page + delta)
        self._dash_trades_render()

    def _dash_trades_render(self):
        """Delegate to launcher_support.screens.dash_trades.render. Full
        rendering (filter, pagination, trade table, page/stats labels,
        30s reschedule) lives there.
        """
        from launcher_support.screens.dash_trades import render as _render_dash_trades
        _render_dash_trades(self)

    # -- HOME TAB (personal snapshot) -----------------------
    def _dash_build_home_tab(self, parent):
        """CS 1.6 style HOME: connection status + account management + engines.
        No heavy aggregations — only what's immediately actionable.
        Renders instantly with cached state; background refresh is lightweight."""
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=14, pady=8)

        # -- HUD header --
        hdr = tk.Frame(wrap, bg=BG); hdr.pack(fill="x")
        tk.Label(hdr, text="[ HOME ]", font=(FONT, 9, "bold"),
                 fg=AMBER, bg=BG).pack(side="left")
        tk.Label(hdr, text="personal control panel",
                 font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=(8, 0))
        clock_l = tk.Label(hdr, text="", font=(FONT, 7), fg=DIM2, bg=BG)
        clock_l.pack(side="right")
        self._dash_widgets[("home_clock",)] = clock_l
        tk.Frame(wrap, bg=AMBER_D, height=1).pack(fill="x", pady=(2, 8))

        # -- CONNECTIONS box --
        def box(title, parent_):
            f = tk.Frame(parent_, bg=PANEL,
                         highlightbackground=BORDER, highlightthickness=1)
            tk.Label(f, text=f" [ {title} ] ",
                     font=(FONT, 7, "bold"), fg=BG, bg=AMBER,
                     padx=6, pady=2).pack(side="top", anchor="nw", padx=6, pady=(6, 2))
            return f

        conn_box = box("CONNECTIONS", wrap)
        conn_box.pack(fill="x", pady=(0, 6))
        conn_inner = tk.Frame(conn_box, bg=PANEL)
        conn_inner.pack(fill="x", padx=10, pady=(0, 8))
        self._dash_widgets[("home_conn",)] = conn_inner

        # -- ACCOUNTS box --
        acc_box = box("ACCOUNTS", wrap)
        acc_box.pack(fill="x", pady=(0, 6))
        acc_inner = tk.Frame(acc_box, bg=PANEL)
        acc_inner.pack(fill="x", padx=10, pady=(0, 8))
        self._dash_widgets[("home_accs",)] = acc_inner

        # -- ENGINES box --
        eng_box = box("RUNNING ENGINES", wrap)
        eng_box.pack(fill="x", pady=(0, 6))
        eng_inner = tk.Frame(eng_box, bg=PANEL)
        eng_inner.pack(fill="x", padx=10, pady=(0, 8))
        self._dash_widgets[("home_engines",)] = eng_inner

        self.f_lbl.configure(
            text="HOME · connections + accounts + engines · "
                 "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit · R refresh"
        )

        # Show a brief "connecting..." placeholder inside each panel until the
        # first fetch completes and populates real data. Avoids a blank flash
        # on tab switch.
        for key in ("home_conn", "home_accs", "home_engines"):
            inner = self._dash_widgets.get((key,))
            if inner is not None:
                tk.Label(inner, text="  connecting...",
                         font=(FONT, 8), fg=DIM2, bg=PANEL,
                         anchor="w").pack(fill="x", pady=2)
        # First real render comes from _dash_home_fetch_async which is
        # invoked by _dash_render_tab right after this build method returns.

    def _dash_home_fetch_async(self):
        """Lightweight background refresh: only ping exchange + list_procs.
        Does NOT call PortfolioMonitor.refresh for live accounts (too slow) —
        only loads the paper state locally, which is instant."""
        if not getattr(self, "_dash_alive", False):
            return

        def worker():
            snap: dict = {}
            # Paper state: local file read — instant
            try:
                from core.ui.portfolio_monitor import PortfolioMonitor
                snap["paper"] = PortfolioMonitor.paper_state_load()
            except Exception:
                snap["paper"] = None
            # Exchange latency
            try:
                snap["latency"] = _get_conn().ping("binance_futures")
            except Exception:
                snap["latency"] = None
            # Running engines
            try:
                from core.ops.proc import list_procs
                snap["procs"] = list_procs()
            except Exception:
                snap["procs"] = []
            # Check which accounts have keys (instant — reads keys.json)
            try:
                pm = self._get_portfolio_monitor()
                snap["has_keys"] = {m: pm.has_keys(m)
                                    for m in ("testnet", "demo", "live")}
            except Exception:
                snap["has_keys"] = {}

            self._dash_home_snap = snap
            if getattr(self, "_dash_alive", False):
                try: self.after(0, self._dash_home_render)
                except Exception: pass

        threading.Thread(target=worker, daemon=True).start()

    def _dash_home_render(self):
        """Delegate to launcher_support.screens.dash_home.render. The
        three panels (connections, accounts, engines) + clock + header
        status + 10s reschedule live there.
        """
        from launcher_support.screens.dash_home import render as _render_dash_home
        _render_dash_home(self)

    # -- BACKTEST TAB (browse data/runs/) -------------------
    def _dash_build_backtest_tab(self, parent):
        """Two-column browser: list of runs (left) + detail panel (right).
        Click a row to show its real metrics from summary.json inline.
        Detail panel has a secondary button to open report.html in a browser."""
        wrap = tk.Frame(parent, bg=BG); wrap.pack(fill="both", expand=True, padx=14, pady=8)

        hdr = tk.Frame(wrap, bg=BG); hdr.pack(fill="x")
        tk.Label(hdr, text="[ BACKTEST ]", font=(FONT, 9, "bold"),
                 fg=AMBER, bg=BG).pack(side="left")
        count_l = tk.Label(hdr, text="", font=(FONT, 7), fg=DIM, bg=BG)
        count_l.pack(side="right")
        self._dash_widgets[("bt_count",)] = count_l
        tk.Frame(wrap, bg=AMBER_D, height=1).pack(fill="x", pady=(2, 8))

        # Main split: list (left, 60%) + detail (right, 40%)
        split = tk.Frame(wrap, bg=BG); split.pack(fill="both", expand=True)
        split.grid_columnconfigure(0, weight=3, uniform="bt_dash_split")
        split.grid_columnconfigure(1, weight=2, uniform="bt_dash_split")
        split.grid_rowconfigure(0, weight=1)

        # -- LEFT: run list --
        left = tk.Frame(split, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # Column headers — widths pulled from _BT_COLS so header and row
        # widgets always render at the same character positions. Same
        # font size (8, bold dim) as the rows in _dash_backtest_render,
        # otherwise monospace char widths desync and the whole list
        # skews by a few pixels per column.
        hrow = tk.Frame(left, bg=BG); hrow.pack(fill="x")
        for label, width in _BT_COLS:
            tk.Label(hrow, text=label, font=(FONT, 8, "bold"),
                     fg=DIM, bg=BG, width=width,
                     anchor="w").pack(side="left")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        # Scrollable list (Canvas + inner frame)
        canvas_wrap = tk.Frame(left, bg=BG)
        canvas_wrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_wrap, bg=BG, bd=0, highlightthickness=0)
        scroll = tk.Scrollbar(canvas_wrap, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        inner = tk.Frame(canvas, bg=BG)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        self._bind_canvas_window_width(canvas, window_id, pad_x=4)
        def _on_configure(event, c=canvas): c.configure(scrollregion=c.bbox("all"))
        inner.bind("<Configure>", _on_configure)

        # Mouse wheel — scoped: only active while the mouse is over the list.
        # Using bind_all would leak the handler to every other tab.
        def _on_wheel(event, c=canvas):
            try: c.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except tk.TclError: pass
        def _enter(_e=None, c=canvas):
            c.bind_all("<MouseWheel>", _on_wheel)
        def _leave(_e=None, c=canvas):
            try: c.unbind_all("<MouseWheel>")
            except tk.TclError: pass
        canvas.bind("<Enter>", _enter)
        canvas.bind("<Leave>", _leave)
        inner.bind("<Enter>", _enter)
        inner.bind("<Leave>", _leave)

        self._dash_widgets[("bt_list",)] = inner
        self._dash_widgets[("bt_canvas",)] = canvas

        # -- RIGHT: detail panel --
        right = tk.Frame(split, bg=PANEL,
                         highlightbackground=BORDER, highlightthickness=1,
                         width=360)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_propagate(False)

        tk.Label(right, text=" [ DETAILS ] ",
                 font=(FONT, 7, "bold"), fg=BG, bg=AMBER,
                 padx=6, pady=2).pack(anchor="nw", padx=6, pady=(6, 2))

        detail_body = tk.Frame(right, bg=PANEL)
        detail_body.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._dash_widgets[("bt_detail",)] = detail_body

        # Initial placeholder
        tk.Label(detail_body,
                 text="\n← click a run to load its metrics",
                 font=(FONT, 8), fg=DIM, bg=PANEL,
                 justify="left").pack(anchor="w")

        self.f_lbl.configure(
            text="BACKTEST · click row for details · "
                 "1=Home 2=Market 3=Portfolio 4=Trades 5=Backtest 6=Cockpit · R refresh"
        )

        self._dash_backtest_render()

    @staticmethod
    def _bt_fmt_timestamp(ts_raw) -> str:
        """Format a run timestamp as 'YYYY-MM-DD  HH:MM'. Accepts:
        - ISO string: '2026-04-10T11:50:23.123'
        - Unix seconds: 1712745023 (int or float)
        - Unix milliseconds: 1712745023000 (int or float)
        - None / empty / unparseable → '—'"""
        if ts_raw is None or ts_raw == "":
            return "—"
        # Numeric (unix timestamp)
        if isinstance(ts_raw, (int, float)):
            try:
                # Treat values > 1e12 as milliseconds, otherwise seconds
                t = float(ts_raw)
                if t > 1e12:
                    t /= 1000.0
                return datetime.fromtimestamp(t).strftime("%Y-%m-%d  %H:%M")
            except (ValueError, OSError, OverflowError):
                return "—"
        # String
        try:
            dt = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d  %H:%M")
        except (ValueError, TypeError):
            return str(ts_raw)[:16].replace("T", " ")

    def _bt_read_json(self, path: Path) -> dict:
        """Read a JSON file, cached by (path, mtime).

        The backtest tab rebuilds its list on every switch and each row
        needs its summary.json + config.json parsed — 70+ runs × 2 files ×
        multi-ms parse per file adds visible lag. mtime-keyed cache means
        we only pay the parse cost once until the file actually changes on
        disk (e.g., after a new run completes).
        """
        cache = getattr(self, "_bt_json_cache", None)
        if cache is None:
            cache = self._bt_json_cache = {}
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return {}
        key = str(path)
        entry = cache.get(key)
        if entry is not None and entry[0] == mtime:
            return entry[1]
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {}
        result = data if isinstance(data, dict) else {}
        cache[key] = (mtime, result)
        return result

    def _bt_legacy_engine_dirs(self) -> list[Path]:
        # Engine-specific run dirs use institutional names (post-rename
        # commit). Skip set covers shared/non-engine dirs that should
        # never be treated as engine runs by the dashboard scanner.
        data_dir = ROOT / "data"
        skip = {
            ".proc_logs", "runs", "audit", "exports",
            "funding_scanner", "live", "param_search", "validation",
            "janestreet",  # scanner snapshots, not backtests
            "aqr",          # aggregator, reads from other engines
        }
        try:
            return sorted(
                [
                    p for p in data_dir.iterdir()
                    if p.is_dir() and p.name not in skip and not p.name[:4].isdigit()
                ]
            )
        except OSError:
            return []

    def _bt_report_candidates(self, run_dir: Path) -> list[Path]:
        rep_dir = run_dir / "reports"
        if not rep_dir.exists():
            return []
        skip_names = {
            "config.json", "equity.json", "index.json", "overfit.json",
            "price_data.json", "summary.json", "trades.json",
            "simulate_historical.json",
        }
        try:
            files = [
                p for p in rep_dir.iterdir()
                if p.is_file() and p.suffix.lower() == ".json" and p.name not in skip_names
            ]
        except OSError:
            return []
        files.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        return files

    def _bt_entry_from_report(self, engine_dir: Path, run_dir: Path, report_path: Path) -> dict:
        report = self._bt_read_json(report_path)
        engine_name = str(report.get("engine") or engine_dir.name).strip()
        engine_slug = canonical_engine_key(engine_name)
        raw_run_id = str(report.get("run_id") or run_dir.name).strip() or run_dir.name
        run_id = raw_run_id if raw_run_id.startswith(f"{engine_slug}_") else f"{engine_slug}_{raw_run_id}"
        account_size = report.get("account_size")
        final_equity = report.get("final_equity")
        pnl = report.get("pnl")
        if pnl is None and account_size is not None and final_equity is not None:
            try:
                pnl = float(final_equity) - float(account_size)
            except (TypeError, ValueError):
                pnl = None

        report_html = run_dir / "report.html"
        if not report_html.exists():
            try:
                html_candidates = [p for p in (run_dir / "reports").iterdir() if p.suffix.lower() == ".html"]
            except OSError:
                html_candidates = []
            if html_candidates:
                html_candidates.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
                report_html = html_candidates[0]

        return {
            "run_id": run_id,
            "engine": engine_slug,
            "timestamp": report.get("timestamp"),
            "interval": report.get("interval"),
            "period_days": report.get("period_days"),
            "basket": report.get("basket", "default"),
            "n_symbols": report.get("n_symbols"),
            "n_candles": report.get("n_candles"),
            "n_trades": report.get("n_trades"),
            "win_rate": report.get("win_rate"),
            "pnl": pnl,
            "roi_pct": report.get("roi_pct", report.get("roi")),
            "sharpe": report.get("sharpe"),
            "sortino": report.get("sortino"),
            "max_dd_pct": report.get("max_dd_pct", report.get("max_dd")),
            "account_size": account_size,
            "leverage": report.get("leverage"),
            "final_equity": final_equity,
            "summary_path": str(report_path),
            "report_json_path": str(report_path),
            "config_path": str(run_dir / "config.json"),
            "report_html_path": str(report_html) if report_html.exists() else "",
            "run_dir": str(run_dir),
            "source": "legacy",
        }

    def _bt_collect_runs(self) -> list[dict]:
        idx_path = ROOT / "data" / "index.json"
        runs_by_id: dict[str, dict] = {}

        # engine slug → actual data dir (for post-rename paths)
        _SLUG_TO_DIR = {
            "citadel":     ROOT / "data" / "runs",
            "bridgewater": ROOT / "data" / "bridgewater",
            "jump":        ROOT / "data" / "jump",
            "renaissance": ROOT / "data" / "renaissance",
            "janestreet":  ROOT / "data" / "janestreet",
            "millennium":  ROOT / "data" / "millennium",
            "twosigma":    ROOT / "data" / "twosigma",
            "aqr":         ROOT / "data" / "aqr",
        }

        if idx_path.exists():
            try:
                rows = json.loads(idx_path.read_text(encoding="utf-8"))
                if isinstance(rows, list):
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        run_id = str(row.get("run_id") or "").strip()
                        if not run_id:
                            continue
                        explicit_run_dir = str(row.get("run_dir") or "").strip()
                        if explicit_run_dir:
                            run_dir = Path(explicit_run_dir)
                        else:
                        # Resolve run_dir via engine slug — run_ids are now
                        # prefixed (e.g. "bridgewater_2026-04-14_1029")
                            engine_slug = str(row.get("engine") or "").lower()
                            base_dir = _SLUG_TO_DIR.get(engine_slug, ROOT / "data" / "runs")
                            # Strip engine prefix from run_id to get folder name
                            folder = run_id
                            if engine_slug and folder.startswith(f"{engine_slug}_"):
                                folder = folder[len(engine_slug) + 1:]
                            run_dir = base_dir / folder
                            # Citadel keeps the prefixed form as folder name
                            if engine_slug == "citadel" and not run_dir.exists():
                                run_dir = base_dir / run_id
                        entry = dict(row)
                        entry.setdefault("run_dir", str(run_dir))
                        entry.setdefault("summary_path", str(run_dir / "summary.json"))
                        entry.setdefault("config_path", str(run_dir / "config.json"))
                        report_html = run_dir / "report.html"
                        entry.setdefault("report_html_path", str(report_html) if report_html.exists() else "")
                        # Find the real report JSON in reports/ dir (Millennium
                        # + legacy engines save there as <engine>_<tf>_v1.json,
                        # never as summary.json at run_dir root). Without this
                        # _show_results falls through to data/runs/ fallback
                        # and loads a completely different run.
                        if not entry.get("report_json_path"):
                            cands = self._bt_report_candidates(run_dir)
                            if cands:
                                entry["report_json_path"] = str(cands[0])
                        entry.setdefault("source", "index")
                        # Fallback: read summary.json for fields that might be
                        # missing in older index entries (basket, period_days...)
                        if not entry.get("basket"):
                            try:
                                _sj = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
                                entry["basket"] = _sj.get("basket") or "default"
                                if not entry.get("period_days"):
                                    entry["period_days"] = _sj.get("period_days")
                                if not entry.get("interval"):
                                    entry["interval"] = _sj.get("interval")
                            except (OSError, json.JSONDecodeError):
                                pass
                        runs_by_id[run_id] = entry
            except (json.JSONDecodeError, OSError, TypeError):
                pass

        runs_root = ROOT / "data" / "runs"
        if runs_root.exists():
            try:
                for run_dir in runs_root.iterdir():
                    if not run_dir.is_dir():
                        continue
                    run_id = run_dir.name
                    summary_path = run_dir / "summary.json"
                    config_path = run_dir / "config.json"
                    summary = self._bt_read_json(summary_path)
                    config = self._bt_read_json(config_path)
                    entry = runs_by_id.get(run_id, {}).copy()
                    entry.setdefault("run_id", run_id)
                    entry.setdefault("engine", str(entry.get("engine") or run_id.split("_", 1)[0]).lower())
                    entry.setdefault("timestamp", summary.get("timestamp"))
                    entry.setdefault("interval", summary.get("interval", config.get("INTERVAL", config.get("ENTRY_TF"))))
                    entry.setdefault("period_days", summary.get("period_days", config.get("SCAN_DAYS")))
                    entry.setdefault("basket", summary.get("basket", config.get("BASKET_EFFECTIVE", "default")))
                    entry.setdefault("n_symbols", summary.get("n_symbols"))
                    entry.setdefault("n_candles", summary.get("n_candles", config.get("N_CANDLES")))
                    entry.setdefault("n_trades", summary.get("n_trades"))
                    entry.setdefault("win_rate", summary.get("win_rate"))
                    entry.setdefault("pnl", summary.get("pnl", summary.get("total_pnl")))
                    entry.setdefault("roi_pct", summary.get("roi_pct", summary.get("roi")))
                    entry.setdefault("sharpe", summary.get("sharpe"))
                    entry.setdefault("sortino", summary.get("sortino"))
                    entry.setdefault("max_dd_pct", summary.get("max_dd_pct", summary.get("max_dd")))
                    entry.setdefault("account_size", summary.get("account_size", config.get("ACCOUNT_SIZE")))
                    entry.setdefault("leverage", summary.get("leverage", config.get("LEVERAGE")))
                    entry.setdefault("final_equity", summary.get("final_equity"))
                    entry["run_dir"] = str(run_dir)
                    entry["summary_path"] = str(summary_path)
                    entry["config_path"] = str(config_path)
                    report_html = run_dir / "report.html"
                    entry["report_html_path"] = str(report_html) if report_html.exists() else entry.get("report_html_path", "")
                    if not entry.get("report_json_path"):
                        cands = self._bt_report_candidates(run_dir)
                        if cands:
                            entry["report_json_path"] = str(cands[0])
                    entry.setdefault("source", "runs")
                    runs_by_id[run_id] = entry
            except OSError:
                pass

        for engine_dir in self._bt_legacy_engine_dirs():
            try:
                run_dirs = [p for p in engine_dir.iterdir() if p.is_dir()]
            except OSError:
                continue
            for run_dir in run_dirs:
                report_files = self._bt_report_candidates(run_dir)
                if not report_files:
                    continue
                entry = self._bt_entry_from_report(engine_dir, run_dir, report_files[0])
                runs_by_id.setdefault(entry["run_id"], entry)

        runs = list(runs_by_id.values())
        runs.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
        self._bt_run_map = {str(r.get("run_id")): r for r in runs if r.get("run_id")}
        self._bt_recent_run_id = runs[0]["run_id"] if runs else None
        return runs

    def _bt_resolve_run(self, run_id: str) -> dict:
        cache = getattr(self, "_bt_run_map", {}) or {}
        row = cache.get(run_id)
        if row:
            return row
        for row in self._bt_collect_runs():
            if row.get("run_id") == run_id:
                return row
        return {}

    def _dash_backtest_render(self):
        list_wrap = self._dash_widgets.get(("bt_list",))
        count_l   = self._dash_widgets.get(("bt_count",))
        if list_wrap is None:
            return
        try:
            if not list_wrap.winfo_exists():
                return
        except Exception:
            return

        for w in list_wrap.winfo_children():
            try: w.destroy()
            except Exception: pass

        runs = self._bt_collect_runs()

        if count_l:
            count_l.configure(text=f"{len(runs)} runs")

        if not runs:
            tk.Label(list_wrap, text="  — no runs found in data/runs/ —",
                     font=(FONT, 8), fg=DIM, bg=BG,
                     anchor="w").pack(fill="x", pady=10)
            return

        def _fmt_n(v, suffix=""): return f"{v:.2f}{suffix}" if v is not None else "—"
        def _fmt_m(v): return f"${v:+,.0f}" if v is not None else "—"
        # Code-name → institutional-name (battery/marketing taxonomy).
        # Maps both legacy lowercase file names (thoth, mercurio)
        # and uppercase variants. Falls back to upper() for unknowns.
        _ENGINE_NAMES = {
            "backtest":      "CITADEL",
            "citadel":       "CITADEL",
            "thoth":         "BRIDGEWATER",
            "bridgewater":   "BRIDGEWATER",
            "mercurio":      "JUMP",
            "jump":          "JUMP",
            "prometeu":      "TWO SIGMA",
            "twosigma":      "TWO SIGMA",
            "two_sigma":     "TWO SIGMA",
            "darwin":        "AQR",
            "aqr":           "AQR",
            "multistrategy": "MILLENNIUM",
            "millennium":    "MILLENNIUM",
            "harmonics":     "RENAISSANCE",
            "harmonics_backtest": "RENAISSANCE",
            "renaissance":   "RENAISSANCE",
            "arbitrage":     "JANE STREET",
            "jane_street":   "JANE STREET",
            "janestreet":    "JANE STREET",
        }
        def _fmt_engine(v):
            raw = str(v or "—").strip().lower()
            name = _ENGINE_NAMES.get(raw, raw.replace("_", " ").upper())
            return name[:13]

        # [Backlog #7] Pre-L6 warning badge for engines whose pre-fix
        # reports are potentially inflated. Runs written before commit
        # ea1f6ba (2026-04-11) are tagged in the RUN column with a "?"
        # prefix. All five engines that only got the aggregate notional
        # cap in that commit are flagged; historical runs of citadel
        # (backtest.py) are untagged because L6 landed earlier there.
        _L6_FIX_DATE = "2026-04-11"
        _L6_AFFECTED = {"mercurio", "thoth", "harmonics",
                         "multistrategy"}

        for run in runs[:50]:
            run_id = run.get("run_id", "?")
            engine = str(run.get("engine") or "").lower()
            ts_raw = run.get("timestamp") or ""
            ts     = self._bt_fmt_timestamp(ts_raw)
            tf     = str(run.get("interval") or "—")
            days   = run.get("period_days")
            days_s = f"{int(days)}" if days else "—"
            basket = str(run.get("basket") or "—")[:9]
            n_tr   = run.get("n_trades") or 0
            wr     = run.get("win_rate")
            pnl    = run.get("pnl")
            sh     = run.get("sharpe")
            dd     = run.get("max_dd_pct")

            pre_l6 = (engine in _L6_AFFECTED
                      and isinstance(ts_raw, str)
                      and ts_raw < _L6_FIX_DATE)

            row = tk.Frame(list_wrap, bg=BG, cursor="hand2")
            row.pack(fill="x", pady=0)

            pnl_col = GREEN if (pnl or 0) > 0 else (RED if (pnl or 0) < 0 else DIM)
            short_id = run_id
            for prefix in (
                "citadel_", "thoth_", "bridgewater_",
                "mercurio_", "jump_", "multistrategy_", "millennium_",
                "prometeu_", "twosigma_", "renaissance_", "harmonics_",
            ):
                if short_id.startswith(prefix):
                    short_id = short_id[len(prefix):]
                    break
            if pre_l6:
                short_id = ("! " + short_id)[:13]
            else:
                short_id = short_id[:13]

            # Widths pulled from _BT_COLS to guarantee header ↔ row parity.
            (_dw, _ew, _tfw, _dyw, _bkw, _rw, _tw, _ww, _pw, _shw, _ddw) = [w for _, w in _BT_COLS]
            # Pre-L6 runs render the RUN cell in RED to match the "!"
            # prefix; the rest of the row keeps its normal coloring so
            # the PnL/Sharpe contrast still works.
            run_col = RED if pre_l6 else AMBER
            cells = [
                (ts,                  _dw,  WHITE,   "normal"),
                (_fmt_engine(engine), _ew,  AMBER,   "bold"),
                (tf,                  _tfw, AMBER_D, "normal"),
                (days_s,              _dyw, WHITE,   "normal"),
                (basket,              _bkw, WHITE,   "normal"),
                (short_id,            _rw,  run_col, "bold"),
                (f"{n_tr}",           _tw,  WHITE,   "normal"),
                (_fmt_n(wr),          _ww,  WHITE,   "normal"),
                (_fmt_m(pnl),         _pw,  pnl_col, "bold"),
                (_fmt_n(sh),          _shw, WHITE,   "normal"),
                (_fmt_n(dd, "%"),     _ddw,
                 RED if (dd or 0) > 5 else DIM, "normal"),
            ]
            row_labels = []
            for text, width, color, weight in cells:
                lbl = tk.Label(row, text=text,
                               font=(FONT, 8, weight),
                               fg=color, bg=BG, width=width, anchor="w")
                lbl.pack(side="left")
                row_labels.append(lbl)

            def _select(_e=None, rid=run_id):
                self._dash_backtest_select(rid)
            def _enter(_e=None, labels=row_labels):
                for l in labels:
                    try: l.configure(bg=BG3)
                    except Exception: pass
            def _leave(_e=None, labels=row_labels):
                for l in labels:
                    try: l.configure(bg=BG)
                    except Exception: pass

            for w in (row, *row_labels):
                w.bind("<Button-1>", _select)
                w.bind("<Enter>", _enter)
                w.bind("<Leave>", _leave)

    def _dash_backtest_select(self, run_id: str):
        """Load the full summary.json for a run and populate the detail panel."""
        body = self._dash_widgets.get(("bt_detail",))
        if body is None:
            return
        try:
            if not body.winfo_exists():
                return
        except Exception:
            return

        for w in body.winfo_children():
            try: w.destroy()
            except Exception: pass

        run_meta = self._bt_resolve_run(run_id)
        run_dir = Path(run_meta.get("run_dir")) if run_meta.get("run_dir") else (ROOT / "data" / "runs" / run_id)
        summary_path = Path(run_meta.get("summary_path")) if run_meta.get("summary_path") else (run_dir / "summary.json")
        config_path  = Path(run_meta.get("config_path")) if run_meta.get("config_path") else (run_dir / "config.json")

        # Index entry for timestamp + period_days fallback
        idx_entry = dict(run_meta) if run_meta else {}

        summary: dict = {}
        if summary_path.exists():
            try:
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        config: dict = {}
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        # Header: run_id + timestamp
        tk.Label(body, text=run_id, font=(FONT, 9, "bold"),
                 fg=AMBER, bg=PANEL, anchor="w",
                 wraplength=270, justify="left").pack(fill="x")
        ts_raw = idx_entry.get("timestamp") or summary.get("timestamp") or ""
        tk.Label(body, text=self._bt_fmt_timestamp(ts_raw),
                 font=(FONT, 8), fg=DIM, bg=PANEL,
                 anchor="w").pack(fill="x", pady=(0, 4))
        tk.Frame(body, bg=DIM2, height=1).pack(fill="x", pady=(0, 6))

        # === PRIMARY ACTIONS — at the top of the detail panel ===
        # Buttons render here FIRST, right after the header. The metric
        # blocks below can be as tall as they want; OPEN HTML and DELETE
        # are always visible regardless of window height or right-panel
        # overflow. Previously they lived at the bottom of the panel and
        # were clipped off-screen when the metric content was taller than
        # the window — user saw "no buttons" even though they were wired
        # correctly, just rendered below the fold.
        actions = tk.Frame(body, bg=PANEL)
        actions.pack(fill="x", anchor="w", pady=(0, 4))

        report = run_dir / "report.html"
        if report.exists():
            btn = tk.Label(actions, text="  OPEN HTML  ",
                           font=(FONT, 8, "bold"),
                           fg=BG, bg=AMBER, cursor="hand2",
                           padx=8, pady=5)
            btn.pack(side="left", padx=(0, 4))
            btn.bind("<Button-1>", lambda e: self._dash_backtest_open(run_id))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=AMBER_B))
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=AMBER))

        metrics_btn = tk.Label(actions, text="  METRICS  ",
                               font=(FONT, 8, "bold"),
                               fg=BG, bg=GREEN, cursor="hand2",
                               padx=8, pady=5)
        metrics_btn.pack(side="left", padx=(0, 4))
        metrics_btn.bind("<Button-1>", lambda e: self._dash_backtest_metrics(run_id))
        metrics_btn.bind("<Enter>", lambda e, b=metrics_btn: b.configure(bg="#36d86b"))
        metrics_btn.bind("<Leave>", lambda e, b=metrics_btn: b.configure(bg=GREEN))

        del_btn = tk.Label(actions, text="  DELETE  ",
                           font=(FONT, 8, "bold"),
                           fg=WHITE, bg=RED, cursor="hand2",
                           padx=8, pady=5)
        del_btn.pack(side="left")
        del_btn.bind("<Button-1>", lambda e: self._dash_backtest_delete(run_id))
        del_btn.bind("<Enter>", lambda e, b=del_btn: b.configure(bg="#c00000"))
        del_btn.bind("<Leave>", lambda e, b=del_btn: b.configure(bg=RED))

        tk.Frame(body, bg=DIM2, height=1).pack(fill="x", pady=(8, 4))

        if not summary and not idx_entry:
            tk.Label(body, text="\n✗ summary.json missing",
                     font=(FONT, 8), fg=RED, bg=PANEL).pack(anchor="w")
            return

        # Metric rows — use summary first, fall back to index entry
        def g(key, default=None):
            return summary.get(key, idx_entry.get(key, default))

        pnl   = g("pnl", g("total_pnl"))
        roi   = g("roi_pct", g("roi"))
        dd    = g("max_dd_pct", g("max_dd"))
        wr    = g("win_rate")
        sh    = g("sharpe")
        so    = g("sortino")
        ca    = g("calmar")
        ntr   = g("n_trades")
        ns    = g("n_symbols")
        nc    = g("n_candles")
        pd    = g("period_days")
        interval = g("interval")
        fe    = g("final_equity")
        acct  = g("account_size")
        lev   = g("leverage")

        def row(label, value, color=WHITE, bold=False):
            r = tk.Frame(body, bg=PANEL); r.pack(fill="x", pady=0)
            tk.Label(r, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=PANEL, width=10,
                     anchor="w").pack(side="left")
            tk.Label(r, text=value,
                     font=(FONT, 8, "bold" if bold else "normal"),
                     fg=color, bg=PANEL, anchor="w").pack(side="left")

        def _fn(v, suf="", digits=2):
            if v is None: return "—"
            try: return f"{float(v):.{digits}f}{suf}"
            except (TypeError, ValueError): return "—"
        def _fm(v):
            if v is None: return "—"
            try: return f"${float(v):+,.2f}"
            except (TypeError, ValueError): return "—"

        pnl_col = GREEN if (pnl or 0) > 0 else (RED if (pnl or 0) < 0 else DIM)

        # === PERFORMANCE block ===
        tk.Label(body, text="PERFORMANCE", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(fill="x", pady=(4, 2))
        row("PnL",       _fm(pnl),            pnl_col, bold=True)
        row("ROI",       _fn(roi, "%"),       pnl_col, bold=True)
        row("Sharpe",    _fn(sh),             WHITE)
        row("Sortino",   _fn(so),             WHITE)
        row("Calmar",    _fn(ca),             WHITE)
        row("Max DD",    _fn(dd, "%"),
            RED if (dd or 0) > 5 else AMBER_D)

        # === TRADES block ===
        tk.Label(body, text="TRADES", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(fill="x", pady=(8, 2))
        row("Total",      str(ntr) if ntr is not None else "—")
        row("Win rate",   _fn(wr, "%"))
        row("Symbols",    str(ns) if ns is not None else "—")
        row("Candles",    f"{nc:,}" if isinstance(nc, (int, float)) else "—")

        # === CONFIG block ===
        tk.Label(body, text="CONFIG", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(fill="x", pady=(8, 2))
        row("Interval",   str(interval or "—"))
        row("Period",     f"{pd} days" if pd else "—")
        row("Account",    _fm(acct) if acct else "—")
        row("Leverage",   f"{lev}x" if lev else "—")
        row("Final eq",   _fm(fe))

        # Config hash (small) — last entry in the metric stack. The
        # action buttons are already rendered at the top of the panel,
        # so there's nothing below this line.
        ch = g("config_hash")
        if ch:
            tk.Label(body, text=f"hash  {str(ch)[:16]}...",
                     font=(FONT, 6), fg=DIM2, bg=PANEL,
                     anchor="w").pack(fill="x", pady=(8, 0))

    def _dash_backtest_delete(self, run_id: str):
        """Delete a backtest run — index row first, disk second.

        Ordering matters: we remove the row from data/index.json BEFORE
        trying to rmtree the directory. The JSON write is atomic and
        always succeeds; the filesystem delete can fail transiently on
        Windows + OneDrive when the sync engine has a handle on
        freshly-closed files. Doing the index edit first means:

        - The run disappears from the user's UI immediately (the row is
          re-rendered without it).
        - If the disk delete fails, the run is effectively tombstoned —
          hidden from all UI code paths — and reconcile_runs.py can
          clean up the leftover directory later.
        - The user never sees "I clicked DELETE, nothing happened" — the
          worst case is "deleted from view, disk cleanup deferred" with
          an explicit messagebox explaining what to do.

        Any exception is caught and surfaced via messagebox.showerror so
        silent failures (previous bug) can't hide behind a 2s h_stat flash.
        """
        if not messagebox.askyesno(
                "Delete backtest",
                f"Apagar definitivamente o run\n\n  {run_id}\n\n"
                f"Todos os ficheiros em data/runs/{run_id}/ serão removidos."):
            return

        try:
            from core.ops.fs import robust_rmtree
            idx_path = ROOT / "data" / "index.json"
            run_dir = Path((getattr(self, "_bt_run_map", {}) or {}).get(run_id, {}).get("run_dir") or (ROOT / "data" / "runs" / run_id))

            # -- Step 1: remove the row from index.json (atomic). --
            index_removed = False
            if idx_path.exists():
                try:
                    idx = json.loads(idx_path.read_text(encoding="utf-8"))
                    if isinstance(idx, list):
                        before = len(idx)
                        idx = [r for r in idx if r.get("run_id") != run_id]
                        if len(idx) != before:
                            atomic_write_json(idx_path, idx, indent=2)
                            index_removed = True
                except (json.JSONDecodeError, OSError) as e:
                    messagebox.showerror(
                        "Delete failed — index.json",
                        f"Could not update data/index.json:\n\n{e}")
                    return

            # -- Step 2: clear the detail panel + refresh the list. --
            body = self._dash_widgets.get(("bt_detail",))
            if body is not None:
                try:
                    for w in body.winfo_children():
                        w.destroy()
                    tk.Label(body, text="  — deleted —",
                             font=(FONT, 8), fg=DIM, bg=PANEL,
                             anchor="w").pack(fill="x", pady=10)
                except tk.TclError:
                    pass
            self._dash_backtest_render()

            # -- Step 3: disk delete (best-effort, robust against locks). --
            disk_removed = True
            if run_dir.exists():
                disk_removed = robust_rmtree(run_dir)

            # -- Step 4: report. --
            if index_removed and disk_removed:
                self.h_stat.configure(text=f"DELETED {run_id[:20]}", fg=AMBER)
                self.after(2000,
                           lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            elif index_removed and not disk_removed:
                # The most common failure mode: OneDrive lock on an empty
                # charts/ or similar. The run is already hidden; we just
                # surface the disk leftover so the user knows to retry.
                self.h_stat.configure(text="DELETED (disk cleanup deferred)",
                                      fg=AMBER_D)
                self.after(3000,
                           lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
                messagebox.showinfo(
                    "Disk cleanup deferred",
                    f"The run has been removed from the backtest list.\n\n"
                    f"However, the directory\n\n"
                    f"  data/runs/{run_id}/\n\n"
                    f"could not be deleted right now — usually OneDrive / "
                    f"antivirus is still holding a handle on a file inside.\n\n"
                    f"Run `python tools/reports/reconcile_runs.py --apply` in a "
                    f"minute or two and it will be cleaned up automatically.")
            else:
                # Neither index nor disk changed — the run_id probably
                # wasn't in the index and the directory is already gone
                # or locked. Say so clearly.
                self.h_stat.configure(text="NOTHING TO DELETE", fg=AMBER_D)
                self.after(2000,
                           lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
        except Exception as e:
            # Last-resort: any unexpected exception goes to a messagebox
            # instead of being swallowed. Silent failures are what got us
            # here in the first place.
            messagebox.showerror(
                "Delete failed — unexpected error",
                f"{type(e).__name__}: {e}")

    def _dash_backtest_delete_all(self):
        """Wipe TODOS os backtest runs: index.json + disk dirs referenciados.

        Escopo = apenas run_dirs listados em data/index.json. Nao toca em
        data/live/, data/millennium_shadow/, data/.proc_logs/, etc — esses
        nao sao backtests e nao aparecem no index. Logo: essa operacao e
        idempotente com o que a UI mostra: apagou aqui → sumiu no DATA >
        BACKTEST RUNS e no engine picker LAST RUNS (ambos releem index.json
        com cache por mtime — reescrever invalida).

        Flow (espelha _dash_backtest_delete):
        1. Dupla confirmacao (destrutivo).
        2. Coletar run_dirs do index antes de zerar.
        3. Escrever index.json = [] (atomico).
        4. rmtree best-effort em cada run_dir (swallow OneDrive locks).
        5. Invalidar cache local (self._bt_run_map) + refresh da lista.
        """
        idx_path = ROOT / "data" / "index.json"
        try:
            rows = json.loads(idx_path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = []
        except (OSError, json.JSONDecodeError):
            rows = []
        total = len(rows)
        if total == 0:
            self.h_stat.configure(text="NOTHING TO DELETE", fg=AMBER_D)
            self.after(1800,
                       lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            return
        if not messagebox.askyesno(
                "Apagar TODOS os backtests",
                f"Voce esta prestes a apagar {total} backtest runs.\n\n"
                f"Isso inclui:\n"
                f"  • {total} linhas de data/index.json\n"
                f"  • Os diretorios data/*/<run_id>/ de cada um\n\n"
                f"Sessoes live (data/live/) NAO sao afetadas.\n"
                f"Processos ativos NAO sao matados.\n\n"
                f"Continuar?"):
            return
        if not messagebox.askyesno(
                "Confirmar novamente",
                f"Ultima chance. {total} runs serao removidos.\n\n"
                f"Certeza?"):
            return

        try:
            from core.ops.fs import robust_rmtree

            # Collect (run_id, run_dir) tuples before zeroing the index.
            _SLUG_TO_DIR = {
                "citadel":     ROOT / "data" / "runs",
                "bridgewater": ROOT / "data" / "bridgewater",
                "jump":        ROOT / "data" / "jump",
                "renaissance": ROOT / "data" / "renaissance",
                "janestreet":  ROOT / "data" / "janestreet",
                "millennium":  ROOT / "data" / "millennium",
                "twosigma":    ROOT / "data" / "twosigma",
                "aqr":         ROOT / "data" / "aqr",
                "graham":      ROOT / "data" / "graham",
                "phi":         ROOT / "data" / "phi",
            }
            targets: list[Path] = []
            for r in rows:
                rid = str(r.get("run_id") or "").strip()
                if not rid:
                    continue
                explicit = str(r.get("run_dir") or "").strip()
                if explicit:
                    targets.append(Path(explicit))
                    continue
                eng = str(r.get("engine") or "").lower()
                base = _SLUG_TO_DIR.get(eng, ROOT / "data" / "runs")
                folder = rid[len(eng) + 1:] if eng and rid.startswith(f"{eng}_") else rid
                candidate = base / folder
                if not candidate.exists() and eng == "citadel":
                    candidate = base / rid  # citadel keeps the prefixed form
                targets.append(candidate)

            # Step 1a: zero index.json atomically.
            atomic_write_json(idx_path, [], indent=2)
            self._bt_run_map = {}
            self._bt_recent_run_id = None

            # Step 1b: zero o SQLite tbm. _query_last_runs faz fallback
            # pra data/aurum.db quando index retorna []; sem isto, o
            # engine picker ainda mostraria as runs antigas via DB.
            # Truncar runs + trades (trades.run_id FK-ish logico).
            db_path = ROOT / "data" / "aurum.db"
            if db_path.exists():
                try:
                    import sqlite3 as _sq
                    _c = _sq.connect(str(db_path))
                    try:
                        _c.execute("DELETE FROM trades")
                        _c.execute("DELETE FROM runs")
                        _c.commit()
                    finally:
                        _c.close()
                except Exception:
                    # DB wipe e best-effort — se falhar, index.json ja
                    # esta vazio e a UI principal (DATA > BACKTEST RUNS)
                    # reflete sumico. Picker pode mostrar stale ate rodar
                    # reconcile, mas nao e bloqueante.
                    pass

            # Step 2: rebuild list (now empty), then refresh detail panel placeholder.
            body = self._dash_widgets.get(("bt_detail",))
            if body is not None:
                try:
                    for w in body.winfo_children():
                        w.destroy()
                    tk.Label(body, text="\n  all runs deleted",
                             font=(FONT, 9, "bold"), fg=DIM, bg=PANEL,
                             justify="left").pack(anchor="w", padx=10)
                except tk.TclError:
                    pass
            try:
                self._dash_backtest_render()
            except Exception:
                pass

            # Step 3: best-effort disk cleanup (background not needed — 400 dirs rmtree fast).
            deleted = 0
            deferred = 0
            for d in targets:
                if not d.exists():
                    continue
                try:
                    if robust_rmtree(d):
                        deleted += 1
                    else:
                        deferred += 1
                except Exception:
                    deferred += 1

            # Step 4: report.
            if deferred == 0:
                self.h_stat.configure(text=f"DELETED {total} RUNS", fg=AMBER)
            else:
                self.h_stat.configure(
                    text=f"DELETED {total} ({deferred} disk deferred)",
                    fg=AMBER_D,
                )
                messagebox.showinfo(
                    "Disk cleanup deferred",
                    f"{deleted} diretorios apagados do disco.\n"
                    f"{deferred} ainda segurados por OneDrive / antivirus.\n\n"
                    f"Rode `python tools/reports/reconcile_runs.py --apply` em "
                    f"1-2 min pra limpar o restante.")
            self.after(3000,
                       lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
        except Exception as e:
            messagebox.showerror(
                "Delete ALL failed — unexpected error",
                f"{type(e).__name__}: {e}")

    def _dash_backtest_open(self, run_id: str):
        """Open the HTML report for a given run in the default browser."""
        run_meta = self._bt_resolve_run(run_id)
        report_path = str(run_meta.get("report_html_path") or "")
        report = Path(report_path) if report_path else (ROOT / "data" / "runs" / run_id / "report.html")
        if not report.exists():
            self.h_stat.configure(text="NO REPORT", fg=RED)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
            return
        try:
            import webbrowser
            webbrowser.open(report.as_uri())
            self.h_stat.configure(text="OPENED", fg=GREEN)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))
        except Exception:
            self.h_stat.configure(text="OPEN FAILED", fg=RED)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))

    # -- COCKPIT TAB (VPS remote control over SSH) ---------
    def _dash_backtest_metrics(self, run_id: str):
        """Open the internal metrics/results view for a specific run.

        Parent=\"dash-backtest\" so ESC/back returns to the crypto dashboard
        backtest tab instead of falling through to the generic menu router.
        """
        try:
            self._show_results("dash-backtest", run_id=run_id)
        except Exception as exc:
            try:
                messagebox.showerror(
                    "METRICS failed",
                    f"{type(exc).__name__}: {exc}",
                )
            except Exception:
                pass
            self.h_stat.configure(text="METRICS FAILED", fg=RED)
            self.after(1500, lambda: self.h_stat.configure(text="LIVE", fg=GREEN))

    def _dash_build_cockpit_tab(self, parent):
        """VPS remote cockpit: screen session status, positions, controls, logs."""
        cockpit_tab_mod.build_tab(
            self,
            parent,
            tk_mod=tk,
            colors={
                "BG": BG,
                "PANEL": PANEL,
                "BORDER": BORDER,
                "AMBER": AMBER,
                "AMBER_B": AMBER_B,
                "DIM": DIM,
                "DIM2": DIM2,
                "WHITE": WHITE,
                "GREEN": GREEN,
                "RED": RED,
            },
            font_name=FONT,
            vps_host=_vps_host,
            vps_project=_vps_project,
        )

    def _dash_cockpit_fetch_async(self):
        """Single SSH round-trip for full status: screen, logs, positions."""
        cockpit_tab_mod.fetch_async(
            self,
            vps_cmd=_vps_cmd,
            vps_project=_vps_project,
            vps_live_screen=_vps_live_screen,
            vps_millennium_screen=_vps_millennium_screen,
        )

    def _dash_cockpit_render(self):
        cockpit_tab_mod.render(
            self,
            tk_mod=tk,
            colors={
                "PANEL": PANEL,
                "AMBER": AMBER,
                "AMBER_B": AMBER_B,
                "AMBER_D": AMBER_D,
                "DIM": DIM,
                "DIM2": DIM2,
                "WHITE": WHITE,
                "GREEN": GREEN,
                "RED": RED,
            },
            font_name=FONT,
            vps_live_screen=_vps_live_screen,
            vps_millennium_screen=_vps_millennium_screen,
        )

    def _dash_cockpit_action(self, label: str, cmd: str,
                             success_msg: str = "ok", timeout: int = 15):
        """Run an SSH command in a worker thread, flash a status message."""
        cockpit_tab_mod.action(
            self,
            label,
            cmd,
            vps_cmd=_vps_cmd,
            colors={"AMBER_D": AMBER_D, "GREEN": GREEN, "RED": RED},
            success_msg=success_msg,
            timeout=timeout,
        )

    def _dash_cockpit_start_demo(self):
        project = _vps_project()
        cmd = (f"screen -dmS {_vps_live_screen} bash -c "
               f"'cd {project} && python3 -m engines.live demo "
               "2>&1 | tee /tmp/aurum.log'")
        self._dash_cockpit_action("START DEMO", cmd, "engine spawned")

    def _dash_cockpit_start_millennium_bootstrap(self):
        cmd = _build_millennium_bootstrap_launch_command(_vps_project(), mode="diag")
        self._dash_cockpit_action("START MLN", cmd, "bootstrap spawned")

    def _dash_cockpit_stop(self):
        self._dash_cockpit_action("STOP", _build_vps_stop_command(), "Ctrl+C sent")

    def _dash_cockpit_deploy(self):
        cmd = f"cd {_vps_project()} && git pull"
        self._dash_cockpit_action("DEPLOY", cmd, "git pull done", timeout=30)

    def _dash_cockpit_toggle_stream(self):
        """Toggle live streaming of the log file via `ssh ... tail -f`."""
        cockpit_tab_mod.toggle_stream(
            self,
            subprocess_mod=subprocess,
            threading_mod=threading,
            no_window=_NO_WINDOW,
            build_vps_ssh_command=_build_vps_ssh_command,
            build_vps_log_tail_command=_build_vps_log_tail_command,
            vps_project=_vps_project,
            colors={"AMBER": AMBER, "AMBER_B": AMBER_B},
        )

    def _dash_cockpit_attach_stream(self, proc):
        cockpit_tab_mod.attach_stream(
            self,
            proc,
            colors={"RED": RED},
            threading_mod=threading,
        )

    def _dash_cockpit_stream_reader(self, proc):
        cockpit_tab_mod.stream_reader(self, proc, tk_mod=tk)

    def _dash_cockpit_kill_stream(self):
        """Idempotent — safe to call multiple times even if no stream exists.
        Explicitly closes stdout to unblock the reader thread."""
        cockpit_tab_mod.kill_stream(self, subprocess_mod=subprocess)

    def _dash_paper_edit_dialog(self):
        """Modal-ish dialog to edit the persistent paper account state.
        Lets the user set balance, deposit, withdraw, or reset."""
        dashboard_controls_mod.dash_paper_edit_dialog(
            self,
            tk_mod=tk,
            colors={
                "BG": BG,
                "BG3": BG3,
                "PANEL": PANEL,
                "AMBER": AMBER,
                "AMBER_B": AMBER_B,
                "AMBER_D": AMBER_D,
                "WHITE": WHITE,
                "DIM": DIM,
                "DIM2": DIM2,
                "GREEN": GREEN,
                "RED": RED,
            },
            font_name=FONT,
            root_path=ROOT,
        )

    def _dash_exit_to_markets(self):
        dashboard_controls_mod.dash_exit_to_markets(self)

    # --- COMMAND CENTER ----------------------------------
    def _get_site_runner(self):
        """Lazily instantiate the singleton SiteRunner."""
        return command_center_mod.get_site_runner(self)

    def _command_center(self):
        command_center_mod.command_center(
            self,
            colors={
                "AMBER_D": AMBER_D,
                "DIM": DIM,
                "BG": BG,
                "BG2": BG2,
                "GREEN": GREEN,
                "AMBER": AMBER,
                "WHITE": WHITE,
            },
            command_roadmaps=COMMAND_ROADMAPS,
        )

    def _command_coming_soon(self, name):
        command_center_mod.command_coming_soon(
            self,
            name,
            colors={"DIM": DIM},
            command_roadmaps=COMMAND_ROADMAPS,
        )

    # -- COMMAND CENTER · SITE LOCAL ----------------------
    def _site_local(self):
        command_center_mod.site_local(self)

    def _site_config_screen(self, sr):
        command_center_mod.site_config_screen(
            self,
            sr,
            tk_mod=tk,
            colors={
                "BG": BG,
                "BG3": BG3,
                "AMBER": AMBER,
                "AMBER_D": AMBER_D,
                "DIM": DIM,
                "WHITE": WHITE,
                "GREEN": GREEN,
                "RED": RED,
            },
            font_name=FONT,
        )

    def _site_running_screen(self, sr):
        command_center_mod.site_running_screen(
            self,
            sr,
            tk_mod=tk,
            colors={
                "BG": BG,
                "PANEL": PANEL,
                "AMBER": AMBER,
                "AMBER_D": AMBER_D,
                "DIM": DIM,
                "WHITE": WHITE,
                "GREEN": GREEN,
                "RED": RED,
            },
            font_name=FONT,
        )

    def _site_print(self, line, default_tag="w"):
        command_center_mod.site_print(self, line, default_tag=default_tag)

    def _site_poll(self):
        command_center_mod.site_poll(self)

    def _site_start(self):
        command_center_mod.site_start(
            self,
            path_cls=Path,
            colors={"AMBER_D": AMBER_D, "RED": RED},
        )

    def _site_stop(self):
        command_center_mod.site_stop(self)

    def _site_open_browser(self):
        command_center_mod.site_open_browser(
            self,
            colors={"AMBER_D": AMBER_D, "GREEN": GREEN, "RED": RED},
        )

    def _site_clear_console(self):
        command_center_mod.site_clear_console(self)

    def _site_config_edit(self):
        command_center_mod.site_config_edit(self)

    # --- QUIT --------------------------------------------
    def _quit(self):
        # Flip the alive flag first so any background worker (warmup thread,
        # poller tick, log tail reader) checking it can exit promptly.
        self._ui_alive = False
        aid = getattr(self, "_ui_task_after_id", None)
        if aid is not None:
            try:
                self.after_cancel(aid)
            except Exception:
                pass
            self._ui_task_after_id = None
        # User-facing confirmations for running work. User already clicked X;
        # answering "no" returns without shutdown so we don't freeze their work.
        if self.proc and self.proc.poll() is None:
            r = messagebox.askyesnocancel("AURUM", "Engine running. Stop before closing?")
            if r is None:
                return
            if r:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=1)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
        elif self._exec_managed_info is not None:
            r = messagebox.askyesnocancel("AURUM", "Background backtest running. Stop before closing?")
            if r is None:
                return
            if r:
                try:
                    from core.ops.proc import stop_proc
                    stop_proc(int(self._exec_managed_info["pid"]), expected=self._exec_managed_info)
                except Exception:
                    pass
        sr = getattr(self, "_site_runner_inst", None)
        if sr and sr.is_running():
            r = messagebox.askyesnocancel("AURUM", "Dev server running. Stop before closing?")
            if r is None:
                return
            if r:
                try:
                    sr.stop()
                except Exception:
                    pass
        try:
            _dump_screen_metrics(reason="quit")
        except Exception:
            pass
        # Everything else (shadow poller, ssh tunnel) is stopped by
        # destroy() -> _shutdown_runtime. Centralizing avoids the
        # double-stop path that used to hang on the 3s tunnel timeout.
        self.destroy()


def __getattr__(name: str):
    """Module-level lazy attribute for MAIN_GROUPS.

    Python 3.7+ calls this when `name` is not found in the module's __dict__.
    Since MAIN_GROUPS is intentionally absent until first access, any code that
    reads `launcher.MAIN_GROUPS` (including tests that bypass App.__init__)
    will trigger population here — paying the pandas+requests import cost once.
    """
    if name == "MAIN_GROUPS":
        _ensure_main_groups()
        return globals()["MAIN_GROUPS"]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    App().mainloop()

