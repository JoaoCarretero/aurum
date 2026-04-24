"""Feature engineering for Macro Brain.

Consome dados persistidos em macro_data/events tables e produz features
numericamente úteis pro regime classifier: z-scores, YoY changes, EMAs,
rolling stats, event counts.

Design: sem pandas/numpy como dep obrigatória — stdlib + math só.
Permite rodar em ambientes sem ML stack. pandas usado só se disponível
para paths mais rápidos.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from macro_brain.persistence.store import macro_series, recent_events

log = logging.getLogger("macro_brain.ml.features")


@dataclass
class FeatureVector:
    """Snapshot de features no tempo T."""
    ts: str
    numeric: dict[str, float] = field(default_factory=dict)
    events: dict[str, float] = field(default_factory=dict)

    def flat(self) -> dict[str, float]:
        out = {}
        out.update({f"n.{k}": v for k, v in self.numeric.items()})
        out.update({f"e.{k}": v for k, v in self.events.items()})
        return out


# ── STAT HELPERS (stdlib) ────────────────────────────────────

def _z_score(values: list[float], reference: float | None = None) -> float | None:
    """z-score do último valor (ou de `reference`) vs a série."""
    if len(values) < 5:
        return None
    ref = values[-1] if reference is None else reference
    try:
        mean = statistics.mean(values)
        stdev = statistics.pstdev(values)
        return (ref - mean) / stdev if stdev > 0 else 0.0
    except statistics.StatisticsError:
        return None


def _yoy_change(values: list[float], dates: list[str]) -> float | None:
    """Mudança % YoY do último ponto vs ~365d atrás (simples)."""
    if not dates or not values or len(values) < 2:
        return None
    try:
        last_dt = datetime.fromisoformat(dates[-1][:19])
    except ValueError:
        return None
    target = last_dt - timedelta(days=365)
    # Find closest prior point
    best_i = None
    best_gap = None
    for i, d in enumerate(dates[:-1]):
        try:
            dt = datetime.fromisoformat(d[:19])
        except ValueError:
            continue
        gap = abs((dt - target).days)
        if best_gap is None or gap < best_gap:
            best_gap = gap
            best_i = i
    if best_i is None or best_gap is None or best_gap > 45:
        return None  # não achou match razoável
    prev = values[best_i]
    if prev == 0:
        return None
    return (values[-1] / prev - 1.0) * 100


def _ema(values: list[float], span: int) -> float | None:
    if not values:
        return None
    alpha = 2 / (span + 1)
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _pct_change(values: list[float], lookback: int = 1) -> float | None:
    if len(values) <= lookback:
        return None
    prev = values[-lookback - 1]
    if prev == 0:
        return None
    return (values[-1] / prev - 1.0) * 100


# ── FEATURE BUILDER ──────────────────────────────────────────

def build_features(
    lookback_days: int = 90,
    sentiment_lookback_days: int = 7,
) -> FeatureVector:
    """Constrói snapshot de features do estado atual.

    Numeric features:
      For each metric in FRED_SERIES + CoinGecko set:
        <metric>_z30d    z-score 30d
        <metric>_yoy     YoY change %
        <metric>_pct7d   7d pct change

    Event features:
      news_sentiment_ema    EMA do sentiment últimos N dias
      news_count_24h        count de events categoria news
      news_high_impact_24h  count onde impact > 0.7
      fear_greed_latest     último valor F&G (0-100)
    """
    fv = FeatureVector(ts=datetime.utcnow().isoformat())

    # Métricas numéricas
    tracked_metrics = [
        "FED_RATE", "US10Y", "US2Y", "DXY", "CPI_US", "VIX", "WTI_OIL", "GOLD",
        "YIELD_SPREAD_10_2", "UNEMPLOYMENT_US",
        "BTC_DOMINANCE", "TOTAL_CRYPTO_MCAP", "BTC_SPOT", "ETH_SPOT",
        "CRYPTO_FEAR_GREED",
    ]
    since_iso = (datetime.utcnow() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    for metric in tracked_metrics:
        series = macro_series(metric, since=since_iso)
        if not series:
            continue
        values = [r["value"] for r in series]
        dates = [r["ts"] for r in series]

        z = _z_score(values[-30:] if len(values) >= 30 else values)
        yoy = _yoy_change(values, dates)
        p7 = _pct_change(values, lookback=7) if len(values) >= 8 else None

        if z is not None:     fv.numeric[f"{metric}_z30d"] = round(z, 4)
        if yoy is not None:   fv.numeric[f"{metric}_yoy"] = round(yoy, 4)
        if p7 is not None:    fv.numeric[f"{metric}_pct7d"] = round(p7, 4)

    # Features de eventos
    since_ev = (datetime.utcnow() - timedelta(days=sentiment_lookback_days)).isoformat()
    news = [e for e in recent_events(limit=500)
            if e.get("ts", "") >= since_ev and e.get("category") in ("news", "monetary",
                                                                     "macro", "geopolitics",
                                                                     "commodities", "crypto")]
    if news:
        sents = [float(e["sentiment"]) for e in news if e.get("sentiment") is not None]
        if sents:
            fv.events["news_sentiment_ema"] = round(_ema(sents, span=min(len(sents), 20)) or 0, 4)
            fv.events["news_sentiment_mean"] = round(sum(sents) / len(sents), 4)
        fv.events["news_count"] = len(news)
        fv.events["news_high_impact_count"] = sum(
            1 for e in news if (e.get("impact") or 0) > 0.7
        )

    # Fear & Greed latest
    fg = macro_series("CRYPTO_FEAR_GREED", since=since_iso)
    if fg:
        fv.events["fear_greed_latest"] = fg[-1]["value"]
        # Classify régime-adjacent
        last = fg[-1]["value"]
        fv.events["fg_is_extreme_fear"] = 1.0 if last <= 25 else 0.0
        fv.events["fg_is_extreme_greed"] = 1.0 if last >= 75 else 0.0

    return fv


def describe(fv: FeatureVector) -> str:
    """Pretty-print pra debug."""
    lines = [f"FeatureVector @ {fv.ts}"]
    if fv.numeric:
        lines.append("  numeric:")
        for k, v in sorted(fv.numeric.items()):
            lines.append(f"    {k:<30} {v:>10.4f}")
    if fv.events:
        lines.append("  events:")
        for k, v in sorted(fv.events.items()):
            lines.append(f"    {k:<30} {v:>10.4f}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db
    init_db()

    fv = build_features()
    print(describe(fv))
    print(f"\nTotal features: {len(fv.flat())}")
