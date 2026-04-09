"""
AURUM Finance — PROMETEU Engine v1.0
ML Meta-Ensemble (LightGBM)

Conceito: modelo que decide QUAL engine usar em cada momento.
Walk-forward training: treina em 70%, valida em 30%, re-treina periodicamente.

Features: omega_score, struct_strength, taker_ratio, vol_regime, macro_bias,
          rsi, atr_pct, cascade_n, cvd_trend, funding_z (quando disponível)

Target: qual engine teve melhor R-multiple nos próximos trades

Fallback: se LightGBM não instalado, usa ensemble estático.
"""
import sys
import math
import logging
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.params import *
from analysis.stats import equity_stats, calc_ratios

try:
    import lightgbm as lgb
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False

log = logging.getLogger("PROMETEU")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

SEP = "─" * 80

# ── RUN IDENTITY ─────────────────────────────────────────────
RUN_ID  = datetime.now().strftime("%Y-%m-%d_%H%M")
RUN_DIR = Path(f"data/prometeu/{RUN_ID}")
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

_fh = logging.FileHandler(RUN_DIR / "logs" / "prometeu.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
log.addHandler(_fh)


# ══════════════════════════════════════════════════════════════
#  FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════

# Engines we can weight
ENGINE_KEYS = ["GRAVITON", "PHOTON", "NEWTON", "MERCURIO", "THOTH"]

# Map vol_regime / macro_bias to numeric
_VOL_MAP = {"LOW": 0, "NORMAL": 1, "HIGH": 2, "EXTREME": 3}
_MACRO_MAP = {"BULL": 2, "CHOP": 1, "BEAR": 0}
_DIR_MAP = {"BULLISH": 1, "BEARISH": 0}
_STRAT_MAP = {k: i for i, k in enumerate(ENGINE_KEYS)}


def trades_to_features(trades: list[dict]) -> pd.DataFrame:
    """
    Convert list of trade dicts into feature matrix for ML training.
    Each row = one trade, features = market context at entry.
    """
    rows = []
    for t in trades:
        if t["result"] not in ("WIN", "LOSS"):
            continue
        row = {
            "score":        t.get("score", 0.5),
            "struct_str":   t.get("struct_str", 0.5),
            "rsi":          t.get("rsi", 50.0),
            "taker_ma":     t.get("taker_ma", 0.5),
            "cascade_n":    t.get("cascade_n", 0),
            "dist_ema21":   t.get("dist_ema21", 0.0),
            "rr":           t.get("rr", 1.5),
            "dd_scale":     t.get("dd_scale", 1.0),
            "corr_mult":    t.get("corr_mult", 1.0),
            "vol_regime":   _VOL_MAP.get(t.get("vol_regime", "NORMAL"), 1),
            "macro_bias":   _MACRO_MAP.get(t.get("macro_bias", "CHOP"), 1),
            "direction":    _DIR_MAP.get(t.get("direction", "BULLISH"), 1),
            "in_transition": int(t.get("in_transition", False)),
            # target
            "strategy":     t.get("strategy", "GRAVITON"),
            "pnl":          t.get("pnl", 0.0),
            "result":       t.get("result"),
            "timestamp":    t.get("timestamp"),
        }
        # extra features if available
        row["funding_z"] = t.get("funding_z", 0.0)
        row["vimb"] = t.get("vimb", 0.5)
        row["zscore_entry"] = t.get("zscore_entry", 0.0)
        row["sentiment"] = t.get("sentiment", 0.0)
        rows.append(row)

    return pd.DataFrame(rows)


def build_target(df: pd.DataFrame, lookahead: int = 10) -> pd.Series:
    """
    For each trade, which engine performed best in the next `lookahead` trades?
    Returns categorical target: index into ENGINE_KEYS.
    """
    targets = []
    for i in range(len(df)):
        window = df.iloc[i:i + lookahead]
        if len(window) < 3:
            targets.append(-1)  # insufficient data
            continue

        # best engine by average R-multiple in window
        by_strat = window.groupby("strategy")["pnl"].mean()
        if len(by_strat) == 0:
            targets.append(-1)
            continue

        best = by_strat.idxmax()
        targets.append(_STRAT_MAP.get(best, 0))

    return pd.Series(targets, index=df.index)


FEATURE_COLS = [
    "score", "struct_str", "rsi", "taker_ma", "cascade_n",
    "dist_ema21", "rr", "dd_scale", "corr_mult",
    "vol_regime", "macro_bias", "direction", "in_transition",
    "funding_z", "vimb", "zscore_entry", "sentiment",
]


# ══════════════════════════════════════════════════════════════
#  PROMETEU ENSEMBLE CLASS
# ══════════════════════════════════════════════════════════════

class PrometeuEnsemble:
    """
    ML-based meta-ensemble that predicts optimal engine weights.
    Walk-forward training with periodic retraining.
    """

    def __init__(self, retrain_every: int = 500):
        self.model = None
        self.retrain_every = retrain_every
        self.last_train_idx = 0
        self.feature_importance = {}
        self.static_weights = {k: 1.0 / len(ENGINE_KEYS) for k in ENGINE_KEYS}

    def train(self, trades_df: pd.DataFrame, train_ratio: float = 0.7) -> dict:
        """
        Train LightGBM model on trade features.
        Returns training metrics.
        """
        if not HAS_LGBM:
            log.warning("LightGBM not installed — using static weights")
            return {"status": "no_lgbm"}

        if len(trades_df) < 50:
            log.warning(f"insufficient data ({len(trades_df)} trades) — using static weights")
            return {"status": "insufficient_data"}

        # build target
        trades_df = trades_df.copy()
        trades_df["target"] = build_target(trades_df)
        valid = trades_df[trades_df["target"] >= 0].copy()

        if len(valid) < 30:
            return {"status": "insufficient_valid"}

        # train/test split (walk-forward: first N% for train)
        split_idx = int(len(valid) * train_ratio)
        train = valid.iloc[:split_idx]
        test = valid.iloc[split_idx:]

        X_train = train[FEATURE_COLS].values
        y_train = train["target"].values
        X_test = test[FEATURE_COLS].values
        y_test = test["target"].values

        n_classes = len(ENGINE_KEYS)

        train_data = lgb.Dataset(X_train, label=y_train)
        test_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

        params = {
            "objective": "multiclass",
            "num_class": n_classes,
            "metric": "multi_logloss",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "max_depth": 6,
            "min_child_samples": 10,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "verbose": -1,
            "seed": 42,
        }

        callbacks = [lgb.log_evaluation(period=0)]
        self.model = lgb.train(
            params, train_data,
            num_boost_round=200,
            valid_sets=[test_data],
            callbacks=callbacks,
        )

        # feature importance
        importance = self.model.feature_importance(importance_type="gain")
        self.feature_importance = dict(zip(FEATURE_COLS, importance))

        # test accuracy
        preds = self.model.predict(X_test)
        pred_classes = np.argmax(preds, axis=1)
        accuracy = np.mean(pred_classes == y_test) * 100

        log.info(f"  PROMETEU trained  ·  accuracy {accuracy:.1f}%  ·  "
                 f"train {len(train)}  test {len(test)}")

        return {
            "status": "ok",
            "accuracy": accuracy,
            "n_train": len(train),
            "n_test": len(test),
        }

    def predict_weights(self, trade: dict) -> dict:
        """
        Predict optimal engine weights for current market context.
        Returns dict[engine_key] = weight (0-1, normalized).
        """
        if self.model is None:
            return self.static_weights.copy()

        features = np.array([[
            trade.get("score", 0.5),
            trade.get("struct_str", 0.5),
            trade.get("rsi", 50.0),
            trade.get("taker_ma", 0.5),
            trade.get("cascade_n", 0),
            trade.get("dist_ema21", 0.0),
            trade.get("rr", 1.5),
            trade.get("dd_scale", 1.0),
            trade.get("corr_mult", 1.0),
            _VOL_MAP.get(trade.get("vol_regime", "NORMAL"), 1),
            _MACRO_MAP.get(trade.get("macro_bias", "CHOP"), 1),
            _DIR_MAP.get(trade.get("direction", "BULLISH"), 1),
            int(trade.get("in_transition", False)),
            trade.get("funding_z", 0.0),
            trade.get("vimb", 0.5),
            trade.get("zscore_entry", 0.0),
            trade.get("sentiment", 0.0),
        ]])

        probs = self.model.predict(features)[0]
        weights = {}
        for i, key in enumerate(ENGINE_KEYS):
            if i < len(probs):
                weights[key] = float(probs[i])
            else:
                weights[key] = 0.0

        # normalize
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    def reweight_trades(self, all_trades: list[dict]) -> list[dict]:
        """
        Apply ML-predicted weights to trades.
        Adjusts PnL based on predicted optimal engine.
        """
        if self.model is None:
            log.info("  PROMETEU: no model, returning original trades")
            return all_trades

        reweighted = []
        for t in all_trades:
            t = t.copy()
            weights = self.predict_weights(t)
            strategy = t.get("strategy", "GRAVITON")
            engine_w = weights.get(strategy, 0.2)

            # static weight = 1/N engines
            static_w = 1.0 / len(ENGINE_KEYS)

            # adjust PnL proportionally
            if static_w > 0:
                w_ratio = engine_w / static_w
                # clamp to prevent extreme adjustments
                w_ratio = max(0.3, min(2.5, w_ratio))
                t["pnl_pre_ml"] = t["pnl"]
                t["pnl"] = round(t["pnl"] * w_ratio, 2)
                t["ml_weight"] = round(engine_w, 4)
                t["ml_w_ratio"] = round(w_ratio, 4)

            reweighted.append(t)

        return reweighted


# ══════════════════════════════════════════════════════════════
#  MAIN — standalone backtest of PROMETEU
# ══════════════════════════════════════════════════════════════

def run_prometeu(engine_trades: dict[str, list]) -> list[dict]:
    """
    Run PROMETEU on trades from multiple engines.
    Args:
        engine_trades: {"GRAVITON": [...], "PHOTON": [...], "NEWTON": [...], ...}
    Returns:
        reweighted trades
    """
    # merge all trades
    all_trades = []
    for engine, trades in engine_trades.items():
        for t in trades:
            t = t.copy()
            if "strategy" not in t:
                t["strategy"] = engine
            all_trades.append(t)

    all_trades.sort(key=lambda t: t.get("timestamp", pd.Timestamp.min))

    if len(all_trades) < 50:
        log.warning(f"  PROMETEU: only {len(all_trades)} trades — need 50+")
        return all_trades

    # build feature matrix
    trades_df = trades_to_features(all_trades)

    # train model
    prometeu = PrometeuEnsemble()
    metrics = prometeu.train(trades_df)

    if metrics["status"] != "ok":
        log.info(f"  PROMETEU: {metrics['status']} — returning original trades")
        return all_trades

    # apply weights
    reweighted = prometeu.reweight_trades(all_trades)

    # print feature importance
    if prometeu.feature_importance:
        print(f"\n{SEP}\n  PROMETEU — Feature Importance\n{SEP}")
        sorted_fi = sorted(prometeu.feature_importance.items(), key=lambda x: -x[1])
        for feat, imp in sorted_fi[:10]:
            bar = "█" * int(imp / max(1, sorted_fi[0][1]) * 20)
            print(f"  {feat:16s}  {imp:>8.1f}  {bar}")

    # compare static vs ML
    static_pnl = sum(t["pnl"] for t in all_trades if t["result"] in ("WIN", "LOSS"))
    ml_pnl = sum(t["pnl"] for t in reweighted if t["result"] in ("WIN", "LOSS"))

    print(f"\n{SEP}\n  PROMETEU — Static vs ML\n{SEP}")
    print(f"  Static PnL    ${static_pnl:>+10,.0f}")
    print(f"  ML PnL        ${ml_pnl:>+10,.0f}")
    print(f"  Delta         ${ml_pnl - static_pnl:>+10,.0f}")
    print(f"  Accuracy      {metrics.get('accuracy', 0):.1f}%")

    # weight distribution
    print(f"\n  Average predicted weights:")
    weight_sums = defaultdict(list)
    for t in reweighted:
        if "ml_weight" in t:
            weight_sums[t.get("strategy", "?")].append(t["ml_weight"])
    for eng in sorted(weight_sums):
        avg_w = np.mean(weight_sums[eng])
        print(f"    {eng:12s}  {avg_w:.3f}")

    return reweighted


if __name__ == "__main__":
    print(f"\n{SEP}")
    print(f"  PROMETEU  ·  ML Meta-Ensemble")
    print(f"  {SEP}")

    if not HAS_LGBM:
        print("  lightgbm nao instalado — pip install lightgbm")
        print("  a usar ensemble estatico como fallback")

    print(f"\n  PROMETEU requer trades de outros engines.")
    print(f"  Usa via multistrategy.py opcao [8] ou importa run_prometeu().")
    print(f"\n  Para testar standalone:")
    print(f"    1. Corre backtest dos engines individuais")
    print(f"    2. Importa os trades de cada um")
    print(f"    3. Passa para run_prometeu()")

    print(f"\n{SEP}\n  output  ·  {RUN_DIR}/\n{SEP}\n")
