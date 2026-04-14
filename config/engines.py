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

# Process manager lookup (maps proc.py engine keys to display names)
PROC_NAMES = {
    "backtest": "CITADEL",
    "multi":    "MILLENNIUM",
    "live":     "LIVE",
    "arb":      "JANE STREET",
    "newton":   "DE SHAW",
    "mercurio": "JUMP",
    "thoth":    "BRIDGEWATER",
    "renaissance": "RENAISSANCE",
    "prometeu": "TWO SIGMA",
    "darwin":   "AQR",
    "chronos":  "WINTON",
}
