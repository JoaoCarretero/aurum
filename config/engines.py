"""
AURUM Finance — Canonical Engine Registry
==========================================
Single source of truth for engine names, scripts, and descriptions.
All UIs (launcher.py, aurum_cli.py, core/proc.py) import from here.

Naming convention: institutional hedge fund references that evoke
the trading style each engine implements.
"""

ENGINES = {
    "citadel":     {"script": "engines/citadel.py",      "display": "CITADEL",     "desc": "Systematic momentum — trend-following + fractal alignment",         "live_ready": True},
    "renaissance": {"script": "engines/renaissance.py",   "display": "RENAISSANCE", "desc": "Pattern recognition — harmonic geometry + Bayesian scoring",        "live_ready": False},
    "jump":        {"script": "engines/jump.py",      "display": "JUMP",        "desc": "Order flow — CVD divergence + volume imbalance",                    "live_ready": False},
    "bridgewater": {"script": "engines/bridgewater.py",         "display": "BRIDGEWATER", "desc": "Macro sentiment — funding + OI + LS ratio contrarian",              "live_ready": False},
    "deshaw":      {"script": "engines/deshaw.py",        "display": "DE SHAW",     "desc": "Statistical arb — pairs cointegration + mean reversion",            "live_ready": False},
    "millennium":  {"script": "engines/millennium.py", "display": "MILLENNIUM",  "desc": "Multi-strategy pod — ensemble orchestrator",                        "live_ready": False},
    "twosigma":    {"script": "engines/twosigma.py",      "display": "TWO SIGMA",   "desc": "ML meta-ensemble — LightGBM walk-forward",                          "live_ready": False},
    "janestreet":  {"script": "engines/janestreet.py",     "display": "JANE STREET", "desc": "Cross-venue arb — funding/basis multi-exchange",                    "live_ready": True},
    "aqr":         {"script": "engines/aqr.py",        "display": "AQR",         "desc": "Adaptive allocation — evolutionary parameter optimization",         "live_ready": False},
    "kepos":       {"script": "engines/kepos.py",      "display": "KEPOS",       "desc": "Critical endogeneity fade — Hawkes η≥0.95 reversal plays",          "live_ready": False},
    "graham":      {"script": "engines/graham.py",     "display": "GRAHAM",      "desc": "Endogenous momentum — trend-following gated by Hawkes ENDO regime", "live_ready": False},
    "phi":         {"script": "engines/phi.py",       "display": "PHI",         "desc": "Fibonacci fractal — multi-TF 0.618 confluence + Golden Trigger",    "live_ready": False},
    "winton":      {"script": "core/chronos.py",          "display": "WINTON",      "desc": "Time-series intelligence — HMM + GARCH + Hurst + seasonality",      "live_ready": False},
    "live":        {"script": "engines/live.py",          "display": "LIVE",        "desc": "Live execution — paper / demo / testnet / real",                    "live_ready": True},
}

# Convenience lookups
ENGINE_NAMES = {k: v["display"] for k, v in ENGINES.items()}
ENGINE_SCRIPTS = {k: v["script"] for k, v in ENGINES.items()}

# Reverse lookup: script path -> canonical key
SCRIPT_TO_KEY = {v["script"]: k for k, v in ENGINES.items()}

# Engines with a validated live runner (paper/demo/testnet/live modes).
# Consumed by launcher_support/engines_live_view.py to split the picker
# into READY LIVE vs RESEARCH buckets. Update this flag per engine only
# after a run-paper smoke test confirms the live entrypoint works.
LIVE_READY_SLUGS = frozenset(k for k, v in ENGINES.items() if v.get("live_ready"))

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
    "prefetch": {
        "script": "tools/prefetch.py",
        "display": "PREFETCH",
        "canonical": "prefetch",
    },
}

PROC_NAMES = {k: v["display"] for k, v in PROC_ENGINES.items()}
