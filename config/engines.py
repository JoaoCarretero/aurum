"""
AURUM Finance — Canonical Engine Registry
==========================================
Single source of truth for engine names, scripts, and descriptions.
All UIs (launcher.py, aurum_cli.py, core/proc.py) import from here.

Naming convention: institutional hedge fund references that evoke
the trading style each engine implements.
"""

ENGINES = {
    "citadel":     {"script": "engines/citadel.py",      "display": "CITADEL",     "desc": "Cross-timeframe momentum with fractal confirmation"},
    "renaissance": {"script": "engines/renaissance.py",  "display": "RENAISSANCE", "desc": "Harmonic pattern recognition with Bayesian scoring"},
    "jump":        {"script": "engines/jump.py",         "display": "JUMP",        "desc": "Order-flow microstructure with CVD divergence"},
    "bridgewater": {"script": "engines/bridgewater.py",  "display": "BRIDGEWATER", "desc": "Cross-sectional sentiment contrarian"},
    "deshaw":      {"script": "engines/deshaw.py",       "display": "DE SHAW",     "desc": "Engle-Granger pairs statistical arbitrage"},
    "millennium":  {"script": "engines/millennium.py",   "display": "MILLENNIUM",  "desc": "Multi-strategy portfolio orchestrator"},
    "twosigma":    {"script": "engines/twosigma.py",     "display": "TWO SIGMA",   "desc": "LightGBM meta-allocator on regime features"},
    "janestreet":  {"script": "engines/janestreet.py",   "display": "JANE STREET", "desc": "Cross-venue basis arbitrage, delta-neutral"},
    "aqr":         {"script": "engines/aqr.py",          "display": "AQR",         "desc": "Evolutionary parameter allocation"},
    "kepos":       {"script": "engines/kepos.py",        "display": "KEPOS",       "desc": "Critical endogeneity fade via Hawkes η"},
    "graham":      {"script": "engines/graham.py",       "display": "GRAHAM",      "desc": "Endogenous momentum with Hawkes regime gate"},
    "medallion":   {"script": "engines/medallion.py",    "display": "MEDALLION",   "desc": "Short-horizon ensemble with Kelly sizing"},
    "phi":         {"script": "engines/phi.py",          "display": "PHI",         "desc": "Fibonacci confluence at 0.618 retracement"},
    "winton":      {"script": "core/chronos.py",         "display": "WINTON",      "desc": "Time-series regime suite (HMM, GARCH, Hurst)"},
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
