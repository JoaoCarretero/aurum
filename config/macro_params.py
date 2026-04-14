"""AURUM Macro Brain — configuration params.

Separate from config/params.py (trade engines) by design.
Nothing here touches engine behavior.
"""
import os
from pathlib import Path

# ── ACCOUNT ──────────────────────────────────────────────────
# Conta separada das trade engines. P&L independente.
MACRO_ACCOUNT_SIZE = 10_000.0
MACRO_BASE_RISK_PER_THESIS = 0.01       # 1% da conta por tese
MACRO_MAX_CONFIDENCE_MULT = 2.0         # conf=1.0 duplica sizing, conf=0 mete 0.5
MACRO_MAX_SINGLE_POSITION = 0.10        # 10% da conta por posição individual

# ── PORTFOLIO RISK ───────────────────────────────────────────
MACRO_MAX_CONCURRENT_THESES = 5
MACRO_MAX_GROSS_EXPOSURE = 0.50         # 50% (longs + shorts)
MACRO_MAX_CORRELATED_THESES = 2         # evita dupla exposure
MACRO_DRAWDOWN_KILL_SWITCH = 0.15       # pausa novas aberturas em -15%
MACRO_TIME_STOP_DAYS = 90               # fecha tese parada após 90d
MACRO_MIN_THESIS_CONFIDENCE = 0.55      # threshold pra aprovar tese

# ── EXECUTION MODE ───────────────────────────────────────────
# paper = simulação interna, sem ordens reais
# demo  = Binance Futures Demo API
# live  = capital real
MACRO_EXEC_MODE = os.environ.get("AURUM_MACRO_MODE", "paper")

# ── SCHEDULE (crontab-like, em segundos) ─────────────────────
MACRO_SCHED_NEWS_SEC = 15 * 60          # 15min
MACRO_SCHED_MACRO_SEC = 24 * 60 * 60    # daily
MACRO_SCHED_REGIME_SEC = 4 * 60 * 60    # 4h
MACRO_SCHED_THESIS_SEC = 24 * 60 * 60   # daily
MACRO_SCHED_REVIEW_SEC = 60 * 60        # hourly

# ── DATA SOURCES ─────────────────────────────────────────────
# Keys resolution (prioridade):
#   1. Env vars (FRED_API_KEY, NEWSAPI_KEY)
#   2. config/keys.json → macro_brain.{fred_api_key, newsapi_key}
#   3. vazio (collector skipa graceful)
#
# GDELT e Fear&Greed não precisam key — funcionam sempre.


def _load_macro_key(env_name: str, json_key: str) -> str:
    v = os.environ.get(env_name, "").strip()
    if v:
        return v
    import json
    keys_path = Path(__file__).resolve().parent / "keys.json"
    if keys_path.exists():
        try:
            data = json.loads(keys_path.read_text(encoding="utf-8"))
            return (data.get("macro_brain") or {}).get(json_key, "") or ""
        except (OSError, json.JSONDecodeError):
            return ""
    return ""


FRED_API_KEY = _load_macro_key("FRED_API_KEY", "fred_api_key")
NEWSAPI_KEY = _load_macro_key("NEWSAPI_KEY", "newsapi_key")

# FRED series monitoradas (ticker → nossa label)
FRED_SERIES = {
    "FEDFUNDS":    "FED_RATE",
    "DGS10":       "US10Y",
    "DGS2":        "US2Y",
    "DXY":         "DXY",
    "CPIAUCSL":    "CPI_US",
    "UNRATE":      "UNEMPLOYMENT_US",
    "T10Y2Y":      "YIELD_SPREAD_10_2",
    "VIXCLS":      "VIX",
    "DCOILWTICO":  "WTI_OIL",
    "GOLDAMGBD228NLBM": "GOLD",
}

# ── STORAGE ──────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
MACRO_DATA_DIR = _ROOT / "data" / "macro"
MACRO_DB_PATH = MACRO_DATA_DIR / "macro_brain.db"
MACRO_RAW_DIR = MACRO_DATA_DIR / "raw"
MACRO_MODELS_DIR = MACRO_DATA_DIR / "models"

# ── REGIME THRESHOLDS (rule-based MVP) ───────────────────────
# Tuning inicial — ajustar após primeiro backtest histórico.
REGIME_THRESHOLDS = {
    "risk_off": {
        "dxy_z_min": 1.5,          # DXY z-score 30d > 1.5
        "vix_z_min": 1.0,          # VIX spike
        "sentiment_ema_max": -0.3, # news sentiment EMA 7d negativo
    },
    "risk_on": {
        "dxy_z_max": -0.5,
        "vix_z_max": 0.0,
        "sentiment_ema_min": 0.2,
    },
    # transition e uncertainty são fallbacks derivados
}

# ── UNIVERSE (assets tradáveis pelo macro brain) ─────────────
# Começar pequeno. Expande em Fase 2.
MACRO_UNIVERSE = [
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BNBUSDT",
]
