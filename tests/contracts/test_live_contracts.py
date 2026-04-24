"""Safety contract tests for engines/live.py.

Cada teste documenta um cenário do mundo real cuja violação causa dano:
keys reais expostas em paper, gates degradados em live, KillSwitch que
não dispara quando deveria, ordens reais executadas em paper.
"""
from __future__ import annotations

import pytest
import asyncio


def test_paper_order_manager_does_not_load_keys(monkeypatch):
    """Cenário protegido: paper mode acidentalmente puxa keys reais via
    init silencioso, expondo credenciais a um path de log/exception."""
    import engines.live as live

    calls = []

    def _spy_load_keys(mode):
        calls.append(mode)
        return ("DUMMY_KEY", "DUMMY_SECRET", "spy")

    monkeypatch.setattr(live, "_load_keys", _spy_load_keys)

    om = live.OrderManager(paper=True)

    assert calls == [], f"_load_keys foi chamado em paper mode: {calls}"
    assert om.client is None, "Binance Client foi instanciado em paper mode"
    assert om.paper is True


def test_guard_real_money_gates_blocks_live_with_default_cfg():
    """Cenário protegido: risk_gates.json some/quebra; load_gate_config
    silencia para defaults permissivos; live arranca com gates off e
    perde a conta numa hora ruim."""
    import engines.live as live
    from core.risk_gates import RiskGateConfig

    cfg = RiskGateConfig()
    assert cfg.is_default(), "Sanity: RiskGateConfig() deve ser default"

    with pytest.raises(RuntimeError, match="REFUSING to start"):
        live._guard_real_money_gates("live", cfg)


def test_guard_real_money_gates_passes_paper_with_default_cfg():
    """Caso negativo: paper mode aceita gates default (esperado, paper nao
    movimenta capital). Falha aqui = guard ficou agressivo demais e
    bloqueia uso legítimo."""
    import engines.live as live
    from core.risk_gates import RiskGateConfig

    live._guard_real_money_gates("paper", RiskGateConfig())  # not raises


def test_kill_switch_dispara_em_fast_dd(monkeypatch):
    """Cenário protegido: drawdown rapido em poucas trades — KillSwitch
    DEVE disparar antes de a estrategia continuar a perder."""
    import engines.live as live

    monkeypatch.setattr(live, "ACCOUNT_SIZE", 10000.0)
    monkeypatch.setattr(live, "BASE_RISK", 0.01)
    # fast_threshold = -KS_FAST_DD_MULT(2.0) * 10000 * 0.01 = -200

    ks = live.KillSwitch()
    for _ in range(live.KS_FAST_DD_N):  # 5 trades
        ks.record(pnl=-100.0, result="LOSS")
    # sum = -500 < -200 → dispara

    triggered, reason = ks.check()
    assert triggered is True, f"KillSwitch deveria ter disparado. reason={reason!r}"
    assert "Fast-DD" in reason


def test_kill_switch_nao_dispara_dentro_do_limite(monkeypatch):
    """Caso negativo: pequenas perdas dentro do orçamento NÃO devem
    pausar trading. Falso-positivo aqui = strategy fica congelada."""
    import engines.live as live

    monkeypatch.setattr(live, "ACCOUNT_SIZE", 10000.0)
    monkeypatch.setattr(live, "BASE_RISK", 0.01)
    # fast_threshold = -200

    ks = live.KillSwitch()
    for _ in range(live.KS_FAST_DD_N):
        ks.record(pnl=-10.0, result="LOSS")
    # sum = -50 > -200 → NAO dispara

    triggered, reason = ks.check()
    assert triggered is False, f"KillSwitch disparou indevidamente. reason={reason!r}"


def test_paper_order_manager_zero_external_http(monkeypatch):
    """Cenário protegido: OrderManager paper acidentalmente cai num path
    que chama requests.post/binance.client. Resultado seria ordem real
    com capital nao alocado."""
    import engines.live as live

    http_calls = []

    def _block_http(*args, **kwargs):
        http_calls.append(("requests", args, kwargs))
        raise RuntimeError("paper mode tocou em requests externos")

    # Bloquear qualquer HTTP externo
    monkeypatch.setattr("requests.post", _block_http)
    monkeypatch.setattr("requests.get", _block_http)

    om = live.OrderManager(paper=True)

    result = asyncio.run(om.place_order(
        symbol="BTCUSDT",
        direction="BULLISH",
        signal_price=50000.0,
        size=0.01,
        stop=49500.0,
        target=51000.0,
    ))

    assert http_calls == [], f"Paper OrderManager bateu HTTP: {http_calls}"
    assert result["order_id"].startswith("PAPER_"), result
    assert result["status"] == "FILLED"
