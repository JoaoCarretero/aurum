"""Safety contract tests for engines/janestreet.py.

Cada teste documenta um cenário do mundo real cuja violação causa dano:
default acidentalmente live, hedge dessimétrico nao detectado, omega
recompensando arb perdedor, gates de live frouxos como paper.
"""
from __future__ import annotations

import pytest


def test_parse_mode_default_is_paper(monkeypatch):
    """Cenário protegido: usuario invoca janestreet sem --mode (default
    de UI/launcher). NAO pode cair em live por omissao."""
    import sys
    monkeypatch.setattr(sys, "argv", ["janestreet.py"])  # zero flags

    import engines.janestreet as js
    args = js._parse_mode()

    assert args.mode is None, f"Default deve ser None, foi {args.mode!r}"
    # No carregamento real (line 41-45), None vira ARB_PAPER=True
    derived_paper = args.mode == "paper" or args.mode is None
    derived_live = args.mode == "live"
    assert derived_paper is True
    assert derived_live is False


def test_hedge_monitor_detecta_delta_drift():
    """Cenário protegido: arb cross-venue com uma perna parcialmente
    fechada (rejeicao de ordem, slippage assimetrico). Hedge passa de
    delta-neutral pra direcional silenciosamente."""
    import engines.janestreet as js

    monitor = js.HedgeMonitor(
        imbalance_warn_pct=5.0,
        imbalance_rehedge_pct=15.0,
    )
    monitor.register(symbol="BTCUSDT", v_a="binance", v_b="bybit", qty=1.0)

    state = monitor._states["BTCUSDT"]
    assert state.imbalance_pct == 0.0, "Hedge recém-registrado deve ter delta 0"

    # Simular: perna A perdeu 30% via fill parcial
    monitor.update_quantities("BTCUSDT", qty_a=0.7, qty_b=1.0)
    state = monitor._states["BTCUSDT"]

    assert state.imbalance_pct == pytest.approx(30.0), \
        f"Esperava ~30% imbalance, foi {state.imbalance_pct}"
    assert state.imbalance_pct > monitor.imb_warn, \
        "Drift de 30% deveria exceder warn de 5%"
    assert state.imbalance_pct > monitor.imb_rehedge, \
        "Drift de 30% deveria exceder rehedge threshold de 15%"


def test_omega_score_penaliza_spread_negativo():
    """Cenário protegido: scanner gera spreads negativos transitorios
    (latency, snapshot inconsistente). omega_score NAO pode retornar
    valor positivo para spread<=0 — abriria trade com EV negativo."""
    import engines.janestreet as js

    # Spread negativo
    score_neg = js.omega_score(
        spread=-0.001,
        vol_a=10_000_000, vol_b=10_000_000,
        cost_a=0.0001, cost_b=0.0001,
    )
    assert score_neg == 0, f"Spread negativo deveria dar score 0, deu {score_neg}"

    # Spread zero
    score_zero = js.omega_score(
        spread=0.0,
        vol_a=10_000_000, vol_b=10_000_000,
        cost_a=0.0001, cost_b=0.0001,
    )
    assert score_zero == 0, f"Spread zero deveria dar score 0, deu {score_zero}"

    # Sanity check: spread positivo amplo + volume amplo deve dar score > 0
    # (caso contrário o teste acima é trivial)
    score_pos = js.omega_score(
        spread=0.001,
        vol_a=10_000_000, vol_b=10_000_000,
        cost_a=0.0001, cost_b=0.0001,
    )
    assert score_pos > 0, f"Spread positivo deveria dar score > 0, deu {score_pos}"
