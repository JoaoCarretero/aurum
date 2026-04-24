"""Computed macro analytics — derived metrics from ingested data.

Sem network calls. Cada função lê do SQLite, calcula métrica composta,
retorna valor + contexto. Usado pelo dashboard pra mostrar insights
profissionais: yield curve inversion, dollar strength, breadth, term
structure, cross-market correlations.
"""
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass

from macro_brain.persistence.store import macro_series

log = logging.getLogger("macro_brain.ml.analytics")


@dataclass
class Insight:
    name: str
    value: float | str
    signal: str             # "bullish" / "bearish" / "neutral" / "warning"
    detail: str = ""        # one-liner explanation
    confidence: float = 1.0


def _last(metric: str) -> float | None:
    s = macro_series(metric)
    if not s:
        return None
    try: return float(s[-1]["value"])
    except (TypeError, ValueError): return None


def _series(metric: str, n: int = 30) -> list[float]:
    s = macro_series(metric)
    return [r["value"] for r in s[-n:]] if s else []


def _z_score(series: list[float]) -> float | None:
    if len(series) < 5:
        return None
    try:
        mean = statistics.mean(series)
        sd = statistics.pstdev(series)
        return (series[-1] - mean) / sd if sd > 0 else 0.0
    except statistics.StatisticsError:
        return None


# ── YIELD CURVE ──────────────────────────────────────────────

def yield_curve_state() -> Insight:
    """Inversion signal: 10Y-2Y spread. Negative = inverted = recession signal."""
    spread = _last("YIELD_SPREAD_10_2") or _last("YIELD_SPREAD_10_3M")
    if spread is None:
        # Fallback: compute from raw 10Y and 2Y
        y10 = _last("US10Y")
        y2 = _last("US2Y")
        if y10 is not None and y2 is not None:
            spread = y10 - y2
    if spread is None:
        return Insight("yield_curve", "—", "neutral", "no yield data", 0.0)

    if spread < -0.10:
        signal = "warning"
        detail = f"Curve INVERTED ({spread:.2f}) — historical recession signal"
    elif spread < 0.0:
        signal = "warning"
        detail = f"Curve flat/inverted ({spread:.2f})"
    elif spread < 0.5:
        signal = "neutral"
        detail = f"Curve flat ({spread:.2f}) — transition"
    else:
        signal = "bullish"
        detail = f"Curve normal ({spread:.2f}) — economy expanding"
    return Insight("yield_curve", f"{spread:.2f}", signal, detail)


# ── DOLLAR STRENGTH ──────────────────────────────────────────

def dollar_strength() -> Insight:
    """DXY z-score 30d. Strong USD = risk-off crypto/commodities."""
    series = _series("DXY", n=30)
    if not series:
        return Insight("dxy_strength", "—", "neutral", "no DXY data", 0.0)
    z = _z_score(series)
    val = series[-1]
    if z is None:
        return Insight("dxy_strength", f"{val:.2f}", "neutral", "insufficient history", 0.5)

    if z >= 1.5:
        signal = "warning"
        detail = f"DXY strong (z={z:+.2f}) — pressure em risk assets"
    elif z >= 0.5:
        signal = "neutral"
        detail = f"DXY firming (z={z:+.2f})"
    elif z <= -1.0:
        signal = "bullish"
        detail = f"DXY weak (z={z:+.2f}) — favorable p/ risk assets"
    else:
        signal = "neutral"
        detail = f"DXY neutral (z={z:+.2f})"
    return Insight("dxy_strength", f"{val:.2f} (z {z:+.2f})", signal, detail)


# ── EQUITY VOLATILITY ────────────────────────────────────────

def vix_regime() -> Insight:
    """VIX level + percentile. <15 complacent, >25 stressed."""
    series = _series("VIX", n=60)
    if not series:
        return Insight("vix_regime", "—", "neutral", "no VIX data", 0.0)
    val = series[-1]
    # Percentile rank
    sorted_s = sorted(series)
    rank = sum(1 for v in sorted_s if v <= val) / len(sorted_s)

    if val < 15:
        signal = "warning"
        detail = f"VIX {val:.1f} — complacent; mean reversion risk"
    elif val > 30:
        signal = "bearish"
        detail = f"VIX {val:.1f} — extreme stress"
    elif val > 22:
        signal = "warning"
        detail = f"VIX {val:.1f} — elevated volatility"
    else:
        signal = "neutral"
        detail = f"VIX {val:.1f} — normal range (pct {rank:.0%})"
    return Insight("vix_regime", f"{val:.2f}", signal, detail)


# ── BREADTH (equity) ────────────────────────────────────────

def equity_breadth() -> Insight:
    """Proxy breadth: SP500 vs VIX + Nasdaq leadership."""
    sp = _last("SP500")
    nq = _last("NASDAQ")
    vix = _last("VIX")
    if sp is None or vix is None:
        return Insight("breadth", "—", "neutral", "no SP500/VIX data", 0.0)

    # 7d pct changes
    sp_s = _series("SP500", n=8)
    nq_s = _series("NASDAQ", n=8)
    sp_pct = ((sp_s[-1] / sp_s[0]) - 1) * 100 if len(sp_s) >= 2 else 0
    nq_pct = ((nq_s[-1] / nq_s[0]) - 1) * 100 if len(nq_s) >= 2 else 0

    leadership = nq_pct - sp_pct
    if leadership > 1.0:
        lead_str = f"NASDAQ leading (+{leadership:.2f}pp)"
    elif leadership < -1.0:
        lead_str = f"SP500 leading ({leadership:+.2f}pp)"
    else:
        lead_str = f"NASDAQ/SP500 together"

    if sp_pct > 2 and vix < 20:
        return Insight("breadth", f"{sp_pct:+.2f}%",
                        "bullish", f"Equity up · {lead_str}")
    if sp_pct < -2 and vix > 22:
        return Insight("breadth", f"{sp_pct:+.2f}%",
                        "bearish", f"Equity down · VIX rising")
    return Insight("breadth", f"{sp_pct:+.2f}%",
                    "neutral", f"7d: {lead_str}")


# ── COT POSITIONING ──────────────────────────────────────────

def gold_cot_signal() -> Insight:
    """Institutional net position in Gold (CFTC)."""
    net = _last("GOLD_NET_LONGS")
    series = _series("GOLD_NET_LONGS", n=12)
    if net is None:
        return Insight("gold_cot", "—", "neutral", "no COT data", 0.0)
    z = _z_score(series)
    if z is None:
        return Insight("gold_cot", f"{int(net):+,}", "neutral", "COT sample small")
    if z >= 1.5:
        return Insight("gold_cot", f"{int(net):+,}",
                        "warning",
                        f"Gold NC net z={z:+.2f} — extreme long crowding")
    if z <= -1.5:
        return Insight("gold_cot", f"{int(net):+,}",
                        "bullish",
                        f"Gold NC net z={z:+.2f} — contrarian buy opportunity")
    return Insight("gold_cot", f"{int(net):+,}",
                    "neutral", f"NC net (z {z:+.2f})")


def btc_cot_signal() -> Insight:
    """CME Bitcoin net positioning."""
    net = _last("BTC_CME_NET_LONGS")
    if net is None:
        return Insight("btc_cot", "—", "neutral", "no BTC CME COT")
    series = _series("BTC_CME_NET_LONGS", n=12)
    z = _z_score(series)
    if z is None:
        return Insight("btc_cot", f"{int(net):+,}", "neutral")
    if z >= 1.5:
        return Insight("btc_cot", f"{int(net):+,}",
                        "warning",
                        f"BTC CME z={z:+.2f} — institutional crowded long")
    if z <= -1.5:
        return Insight("btc_cot", f"{int(net):+,}",
                        "bullish",
                        f"BTC CME z={z:+.2f} — institutional underpositioned")
    return Insight("btc_cot", f"{int(net):+,}",
                    "neutral", f"z {z:+.2f}")


# ── BTC ON-CHAIN ─────────────────────────────────────────────

def btc_network_health() -> Insight:
    """Hashrate + mempool + fees composite. Healthy network = secure."""
    hash_rate = _last("BTC_HASH_RATE")
    mempool = _last("BTC_MEMPOOL_COUNT")
    fee_fast = _last("BTC_FEE_FASTEST_SATVB")
    difficulty = _last("BTC_DIFFICULTY")

    if hash_rate is None:
        return Insight("btc_network", "—", "neutral", "no on-chain data")

    parts = []
    # Hashrate trend
    hr_series = _series("BTC_HASH_RATE", n=30)
    if len(hr_series) >= 7:
        growth = (hr_series[-1] / hr_series[0] - 1) * 100
        parts.append(f"HR {growth:+.1f}%")

    if fee_fast is not None:
        parts.append(f"fee {fee_fast:.0f} sat/vB")
    if mempool is not None:
        parts.append(f"mempool {int(mempool):,}")

    signal = "neutral"
    if fee_fast is not None and fee_fast < 5:
        signal = "bullish"
        detail = "low fees — low congestion, quiet network"
    elif fee_fast is not None and fee_fast > 50:
        signal = "warning"
        detail = "fees elevated — high usage/congestion"
    else:
        detail = " · ".join(parts) if parts else "network normal"

    return Insight("btc_network", f"{int(hash_rate / 1e9):,} EH/s", signal, detail)


# ── BATCH ────────────────────────────────────────────────────

def compute_all() -> list[Insight]:
    """Run all analytics. Order = display order in dashboard."""
    return [
        yield_curve_state(),
        dollar_strength(),
        vix_regime(),
        equity_breadth(),
        gold_cot_signal(),
        btc_cot_signal(),
        btc_network_health(),
    ]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db
    init_db()
    print("\nMACRO ANALYTICS:")
    print(f"  {'NAME':<18} {'VALUE':<20} {'SIGNAL':<10}  DETAIL")
    print(f"  {'-'*18} {'-'*20} {'-'*10}  {'-'*40}")
    for ins in compute_all():
        print(f"  {ins.name:<18} {str(ins.value):<20} {ins.signal:<10}  {ins.detail}")
