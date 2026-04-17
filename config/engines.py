"""
AURUM Finance — Canonical Engine Registry
==========================================
Single source of truth for engine names, scripts, and descriptions.
All UIs (launcher.py, aurum_cli.py, core/proc.py) import from here.

Naming convention: institutional hedge fund references that evoke
the trading style each engine implements.
"""

ENGINES = {
    "citadel":     {"script": "engines/citadel.py",      "display": "CITADEL",     "desc": "Cross-timeframe momentum with fractal confirmation",       "module": "BACKTEST", "stage": "validated",          "sort_weight": 10,  "live_ready": True},
    "renaissance": {"script": "engines/renaissance.py",  "display": "RENAISSANCE", "desc": "Harmonic pattern recognition with Bayesian scoring",      "module": "BACKTEST", "stage": "research",           "sort_weight": 50,  "live_ready": False},
    "jump":        {"script": "engines/jump.py",         "display": "JUMP",        "desc": "Order-flow microstructure with CVD divergence",           "module": "BACKTEST", "stage": "research",           "sort_weight": 40,  "live_ready": False},
    "bridgewater": {"script": "engines/bridgewater.py",  "display": "BRIDGEWATER", "desc": "Cross-sectional sentiment contrarian",                    "module": "BACKTEST", "stage": "quarantined",        "sort_weight": 20,  "live_ready": False},
    "deshaw":      {"script": "engines/deshaw.py",       "display": "DE SHAW",     "desc": "Engle-Granger pairs statistical arbitrage",               "module": "BACKTEST", "stage": "experimental",       "sort_weight": 30,  "live_ready": False},
    "millennium":  {"script": "engines/millennium.py",   "display": "MILLENNIUM",  "desc": "Multi-strategy portfolio orchestrator · live bootstrap staged", "module": "BACKTEST", "stage": "bootstrap_staging", "sort_weight": 60,  "live_ready": False, "live_bootstrap": True},
    "twosigma":    {"script": "engines/twosigma.py",     "display": "TWO SIGMA",   "desc": "LightGBM meta-allocator on regime features",              "module": "BACKTEST", "stage": "research",           "sort_weight": 70,  "live_ready": False},
    "janestreet":  {"script": "engines/janestreet.py",   "display": "JANE STREET", "desc": "Cross-venue basis arbitrage, delta-neutral",              "module": "LIVE",     "stage": "validated",          "sort_weight": 90,  "live_ready": True},
    "aqr":         {"script": "engines/aqr.py",          "display": "AQR",         "desc": "Evolutionary parameter allocation",                       "module": "TOOLS",    "stage": "research",           "sort_weight": 100, "live_ready": False},
    "kepos":       {"script": "engines/kepos.py",        "display": "KEPOS",       "desc": "Critical endogeneity fade via Hawkes η",                  "module": "BACKTEST", "stage": "experimental",       "sort_weight": 72,  "live_ready": False},
    "graham":      {"script": "engines/graham.py",       "display": "GRAHAM",      "desc": "Endogenous momentum with Hawkes regime gate",             "module": "BACKTEST", "stage": "experimental",       "sort_weight": 74,  "live_ready": False},
    "medallion":   {"script": "engines/medallion.py",    "display": "MEDALLION",   "desc": "Short-horizon ensemble with Kelly sizing",                "module": "BACKTEST", "stage": "experimental",       "sort_weight": 76,  "live_ready": False},
    "phi":         {"script": "engines/phi.py",          "display": "PHI",         "desc": "Fibonacci confluence at 0.618 retracement",               "module": "BACKTEST", "stage": "research",           "sort_weight": 78,  "live_ready": False},
    "winton":      {"script": "core/chronos.py",         "display": "WINTON",      "desc": "Time-series regime suite (HMM, GARCH, Hurst)",            "module": "TOOLS",    "stage": "research",           "sort_weight": 110, "live_ready": False},
    "live":        {"script": "engines/live.py",         "display": "LIVE",        "desc": "Live execution — paper / demo / testnet / real",          "module": "LIVE",     "stage": "validated",          "sort_weight": 80,  "live_ready": True},
}

# Convenience lookups
ENGINE_NAMES = {k: v["display"] for k, v in ENGINES.items()}
ENGINE_SCRIPTS = {k: v["script"] for k, v in ENGINES.items()}

# Reverse lookup: script path -> canonical key
SCRIPT_TO_KEY = {v["script"]: k for k, v in ENGINES.items()}
ENGINE_GROUPS = {k: v.get("module", "ENGINES") for k, v in ENGINES.items()}
ENGINE_SORT_WEIGHTS = {k: int(v.get("sort_weight", 999)) for k, v in ENGINES.items()}
ENGINE_STAGES = {k: str(v.get("stage", "research")) for k, v in ENGINES.items()}

# Engines with a validated live runner (paper/demo/testnet/live modes).
# Consumed by launcher_support/engines_live_view.py to split the picker
# into READY LIVE vs RESEARCH buckets. Update this flag per engine only
# after a run-paper smoke test confirms the live entrypoint works.
LIVE_READY_SLUGS = frozenset(k for k, v in ENGINES.items() if v.get("live_ready"))

# Engines that may appear in the live cockpit as bootstrap-runnable even
# before the full live execution loop is validated. These remain distinct
# from LIVE_READY_SLUGS so the UI can stay honest about stage.
LIVE_BOOTSTRAP_SLUGS = frozenset(k for k, v in ENGINES.items() if v.get("live_bootstrap"))

# Engines em quarentena — rodáveis mas sem edge confirmado OOS ou com
# bugs documentados. Não vão pra paper/live sem re-calibração genuína
# + DSR. Bloco 1 do plano de alinhamento 2026-04-17.
#
# Critérios de inclusão:
#   - OOS Sharpe < 0 em janela representativa (COLLAPSED)
#   - 0 trades em janela representativa (NON_FUNCTIONAL) sem fix de
#     threshold aplicado
#   - Bug estrutural documentado sem fix aprovado
#   - Arquivado por docstring mas ainda no registry
#
# Consumo: launcher filtra em view "experimental"; CLI aurum_cli emite
# warning ao rodar; orquestrador OOS audit pode incluir/excluir via flag.
EXPERIMENTAL_SLUGS: frozenset[str] = frozenset({
    "deshaw",    # oos_sharpe=-1.73 BEAR 2022 (cointegração quebra em regime shifts). Smoke last-360d: -1.9 Sharpe / 2.0 MC / 2/6 overfit.
    "graham",    # arquivado per docstring (4h overfit)
    "kepos",     # Smoke last-360d 2026-04-17 pós-fixes completos (cost asymmetry + eta 0.95→0.75 + sustained 10→5 + k_sigma 2.0→1.0): 164 trades, Sharpe -2.08, ROI -36%, MDD 46%. Rodável mas "fade extensions" thesis sem edge em mercado atual.
    "medallion", # Smoke last-360d 2026-04-17 pós-fix cost asymmetry: Sharpe -3.69, ROI -35%, MDD 35%. Grid-best in-sample foi overfit canônico (Codex audit flag).
})

# Process-manager names are still legacy in some UI/API surfaces. Keep the
# mapping here so every consumer resolves to the same script/display pair.
PROC_ENGINES = {
    "backtest": {
        "script": ENGINES["citadel"]["script"],
        "display": "CITADEL",
        "canonical": "citadel",
    },
    "multi": {
        "script": ENGINES["millennium"]["script"],
        "display": "MILLENNIUM",
        "canonical": "millennium",
    },
    "live": {
        "script": ENGINES["live"]["script"],
        "display": "LIVE",
        "canonical": "live",
    },
    "arb": {
        "script": ENGINES["janestreet"]["script"],
        "display": "JANE STREET",
        "canonical": "janestreet",
    },
    "newton": {
        "script": ENGINES["deshaw"]["script"],
        "display": "DE SHAW",
        "canonical": "deshaw",
    },
    "mercurio": {
        "script": ENGINES["jump"]["script"],
        "display": "JUMP",
        "canonical": "jump",
    },
    "thoth": {
        "script": ENGINES["bridgewater"]["script"],
        "display": "BRIDGEWATER",
        "canonical": "bridgewater",
    },
    "renaissance": {
        "script": ENGINES["renaissance"]["script"],
        "display": "RENAISSANCE",
        "canonical": "renaissance",
    },
    "prometeu": {
        "script": ENGINES["twosigma"]["script"],
        "display": "TWO SIGMA",
        "canonical": "twosigma",
    },
    "darwin": {
        "script": ENGINES["aqr"]["script"],
        "display": "AQR",
        "canonical": "aqr",
    },
    "chronos": {
        "script": ENGINES["winton"]["script"],
        "display": "WINTON",
        "canonical": "winton",
    },
    "kepos": {
        "script": ENGINES["kepos"]["script"],
        "display": "KEPOS",
        "canonical": "kepos",
    },
    "graham": {
        "script": ENGINES["graham"]["script"],
        "display": "GRAHAM",
        "canonical": "graham",
    },
    "medallion": {
        "script": ENGINES["medallion"]["script"],
        "display": "MEDALLION",
        "canonical": "medallion",
    },
    "prefetch": {
        "script": "tools/prefetch.py",
        "display": "PREFETCH",
        "canonical": "prefetch",
    },
}

PROC_NAMES = {k: v["display"] for k, v in PROC_ENGINES.items()}
