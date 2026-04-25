"""Safety contract tests for engines/janestreet.py.

Cada teste documenta um cenário do mundo real cuja violação causa dano:
default acidentalmente live, hedge dessimétrico nao detectado, omega
recompensando arb perdedor, gates de live frouxos como paper.
"""
from __future__ import annotations

import pytest


def test_parse_mode_default_is_paper(monkeypatch):
    """Cenário protegido: usuario invoca janestreet sem --mode (default
    de UI/launcher). NAO pode cair em live por omissao. Testa o estado
    real do módulo (ARB_PAPER/ARB_LIVE), não só o retorno do parser."""
    import sys
    import importlib
    monkeypatch.setattr(sys, "argv", ["janestreet.py"])  # zero flags

    import engines.janestreet as js
    importlib.reload(js)  # força re-execução do _parse_mode() em module level

    assert js._ARGS.mode is None, f"_ARGS.mode deve ser None, foi {js._ARGS.mode!r}"
    assert js.ARB_PAPER is True, "ARB_PAPER deve True por default"
    assert js.ARB_LIVE is False, "ARB_LIVE NUNCA pode ser True por default"
    assert js.ARB_MODE == "paper", f"ARB_MODE deve 'paper', foi {js.ARB_MODE!r}"


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


def test_risk_gate_config_loads_per_mode():
    """Cenário protegido: config/risk_gates.json existe mas seções
    arbitrage_live e arbitrage_paper sao iguais (copy-paste). Live
    arranca com gates de paper — exposicao descontrolada."""
    import engines.janestreet as js
    from pathlib import Path

    cfg_path = Path(__file__).parent.parent.parent / "config" / "risk_gates.json"
    if not cfg_path.exists():
        pytest.skip("config/risk_gates.json ausente — teste depende do real config")

    paper_cfg = js._load_risk_gate_config("paper")
    live_cfg = js._load_risk_gate_config("live")

    # As duas devem existir e nao ser ambas default (config real esta presente)
    assert not (paper_cfg.is_default() and live_cfg.is_default()), \
        "Ambas configs vieram default — risk_gates.json existe mas nao tem secoes arbitrage_*"

    # Pelo menos UM campo diferente. Se identicas → operador descuidado.
    same = (
        paper_cfg.max_daily_dd_pct == live_cfg.max_daily_dd_pct
        and paper_cfg.max_consecutive_losses == live_cfg.max_consecutive_losses
        and paper_cfg.max_concurrent_positions == live_cfg.max_concurrent_positions
        and paper_cfg.max_gross_notional_pct == live_cfg.max_gross_notional_pct
    )
    assert not same, (
        "Configs paper e live identicas em todos campos cruciais — "
        "config/risk_gates.json provavelmente tem copy-paste"
    )


# ────────────────────────────────────────────────────────────
# omega_score edge cases — audit 2026-04-25 Lane 4 backfill
#
# Existing test_omega_score_penaliza_spread_negativo cobre <=0 spread.
# Additional cases pin behaviors that, if silently changed, would let
# the scanner score fictitious or marginal arb opportunities — the
# operator opens trades with negative expected value or below-liquidity
# venues.
# ────────────────────────────────────────────────────────────

def test_omega_score_caps_runaway_spread_at_two_pct():
    """Spread acima de 2% é capped antes da multiplicação.

    Cenário protegido: feed de book com snapshot inconsistente pode
    reportar spread de 5-10% (gap entre venues que não existe na realidade).
    Sem o cap em 0.02, o omega_score escalonava linearmente e a engine
    abriria pair com expected slippage gigantesco. Linha 1153 do engine.
    """
    import engines.janestreet as js

    # Spread irrealista de 5% — deve ser tratado como se fosse 2%
    score_runaway = js.omega_score(
        spread=0.05, vol_a=10_000_000, vol_b=10_000_000,
        cost_a=0.0001, cost_b=0.0001,
    )
    score_capped = js.omega_score(
        spread=0.02, vol_a=10_000_000, vol_b=10_000_000,
        cost_a=0.0001, cost_b=0.0001,
    )
    assert score_runaway == score_capped, (
        f"Spread cap broken: 5% spread scored {score_runaway} ≠ "
        f"2% spread {score_capped}. Engine iria abrir pairs em "
        "anomalias de feed."
    )


def test_omega_score_returns_zero_below_min_volume():
    """Volume abaixo de MIN_VOL retorna score 0 (liquidity floor).

    Cenário protegido: venue exótica com 100k notional / day. Spread
    pode parecer atrativo mas execution slippage seria múltiplos do
    spread. Engine 1166: `if min_vol < MIN_VOL: return 0`. Mudar isso
    pra warning silencioso = trades em venues que matam sizing.
    """
    import engines.janestreet as js

    # Volume 100k abaixo do MIN_VOL (default ~1M+ depending on config)
    score_thin = js.omega_score(
        spread=0.001,
        vol_a=100_000, vol_b=100_000,  # tiny
        cost_a=0.0001, cost_b=0.0001,
    )
    assert score_thin == 0, (
        f"omega_score com volume {100_000} < MIN_VOL retornou {score_thin}, "
        "esperado 0 (liquidity floor quebrado)"
    )


def test_omega_score_returns_zero_when_break_even_too_far():
    """Break-even periods > 12 retorna score 0.

    Cenário protegido: spread pequeno + cost ratio alto = pair só
    paga custo após muitos períodos. Engine 1159: `if be_periods > 12:
    return 0`. O 12 é o teto pragmático: arb que precisa segurar 13+
    períodos pra zerar custo está exposto demais a regime change.

    Math da fórmula (engine linhas 1153-1159):
        total_cost   = (cost_a + cost_b) * 2
        slip_buffer  = spread * 0.2
        latency_pen  = spread * 0.1
        net_per_period = spread - slip_buffer - latency_pen
        be_periods   = total_cost / net_per_period
    Pra triggerar be_periods > 12: spread=0.0003, cost=0.001 each →
    total_cost=0.004, net_per_period≈0.00021, be≈19.
    """
    import engines.janestreet as js

    score_marginal = js.omega_score(
        spread=0.0003,
        vol_a=10_000_000, vol_b=10_000_000,
        cost_a=0.0010, cost_b=0.0010,
    )
    assert score_marginal == 0, (
        f"omega_score com break-even longo retornou {score_marginal}, "
        "esperado 0. Marginal arb é trade infectado por regime risk."
    )


def test_hedge_monitor_detects_drift_in_either_direction():
    """Drift de qty_b tambem é detectado, não só qty_a.

    Cenário protegido: o test existente `test_hedge_monitor_detecta_delta_drift`
    cobre só qty_a perdendo 30%. Confirma simetria — venue B pode falhar
    igualmente.
    """
    import engines.janestreet as js

    monitor = js.HedgeMonitor(
        imbalance_warn_pct=5.0,
        imbalance_rehedge_pct=15.0,
    )
    monitor.register(symbol="ETHUSDT", v_a="binance", v_b="bybit", qty=2.0)

    # Perna B fill parcial (50% missing)
    monitor.update_quantities("ETHUSDT", qty_a=2.0, qty_b=1.0)
    state = monitor._states["ETHUSDT"]

    assert state.imbalance_pct > 0, "qty_b drift deve gerar imbalance positiva"
    assert state.imbalance_pct >= monitor.imb_rehedge, (
        f"Drift de 50% em qty_b deveria exceder rehedge {monitor.imb_rehedge}%"
    )


def test_engine_does_not_import_other_engines():
    """MEMORY §9: engines import from core.* / config.*, never each other.

    Cenário protegido: JANE STREET (arb) é independente das directional
    engines. Cross-import quebra o contrato flat e cria implicit ordering.
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent.parent
           / "engines" / "janestreet.py").read_text(encoding="utf-8")
    forbidden = ["from engines.", "import engines."]
    for marker in forbidden:
        for line_no, line in enumerate(src.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""'):
                continue
            assert marker not in stripped, (
                f"janestreet.py:{line_no} imports another engine "
                f"({stripped!r}) — violates MEMORY §9"
            )


def test_arb_live_default_false_module_state():
    """Module-level ARB_LIVE NUNCA é True por construção sem --mode live.

    Pin já existente em test_parse_mode_default_is_paper, mas reforçado
    aqui sem reload (estado actual do módulo). Catch-all: se alguém
    introduzir lógica que define ARB_LIVE=True por env var, etc.
    """
    import engines.janestreet as js

    # Em ambiente de teste, pytest invoca sem --mode live.
    assert js.ARB_LIVE is False, (
        f"ARB_LIVE={js.ARB_LIVE} no estado atual do módulo. "
        "Engine roda live SEM flag explícito = catastrophic default."
    )
