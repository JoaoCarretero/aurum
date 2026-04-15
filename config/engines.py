"""
AURUM Finance — Canonical Engine Registry
==========================================
Single source of truth for engine names, scripts, and descriptions.
All UIs (launcher.py, aurum_cli.py, core/proc.py) import from here.

Naming convention: institutional hedge fund references that evoke
the trading style each engine implements.
"""

ENGINES = {
    "citadel":     {"script": "engines/citadel.py",      "display": "CITADEL",     "desc": "Systematic momentum — trend-following + fractal alignment"},
    "renaissance": {"script": "core/harmonics.py",        "display": "RENAISSANCE", "desc": "Pattern recognition — harmonic geometry + Bayesian scoring"},
    "jump":        {"script": "engines/jump.py",      "display": "JUMP",        "desc": "Order flow — CVD divergence + volume imbalance"},
    "bridgewater": {"script": "engines/bridgewater.py",         "display": "BRIDGEWATER", "desc": "Macro sentiment — funding + OI + LS ratio contrarian"},
    "deshaw":      {"script": "engines/deshaw.py",        "display": "DE SHAW",     "desc": "Statistical arb — pairs cointegration + mean reversion"},
    "millennium":  {"script": "engines/millennium.py", "display": "MILLENNIUM",  "desc": "Multi-strategy pod — ensemble orchestrator"},
    "twosigma":    {"script": "engines/twosigma.py",      "display": "TWO SIGMA",   "desc": "ML meta-ensemble — LightGBM walk-forward"},
    "janestreet":  {"script": "engines/janestreet.py",     "display": "JANE STREET", "desc": "Cross-venue arb — funding/basis multi-exchange"},
    "aqr":         {"script": "engines/aqr.py",        "display": "AQR",         "desc": "Adaptive allocation — evolutionary parameter optimization"},
    "winton":      {"script": "core/chronos.py",          "display": "WINTON",      "desc": "Time-series intelligence — HMM + GARCH + Hurst + seasonality"},
    "live":        {"script": "engines/live.py",          "display": "LIVE",        "desc": "Live execution — paper / demo / testnet / real"},
}

# Convenience lookups
ENGINE_NAMES = {k: v["display"] for k, v in ENGINES.items()}
ENGINE_SCRIPTS = {k: v["script"] for k, v in ENGINES.items()}

# Reverse lookup: script path -> canonical key
SCRIPT_TO_KEY = {v["script"]: k for k, v in ENGINES.items()}

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
        "script": "engines/renaissance.py",
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
}

PROC_NAMES = {k: v["display"] for k, v in PROC_ENGINES.items()}
