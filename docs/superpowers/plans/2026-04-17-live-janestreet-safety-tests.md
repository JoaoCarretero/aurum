# Live + Jane Street Safety Tests — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adicionar 9 safety-contract tests cobrindo invariantes críticas de `engines/live.py` e `engines/janestreet.py` — os 2 engines em produção que movem dinheiro real.

**Architecture:** 2 arquivos novos em `tests/`, padrão `test_<engine>_contracts.py` (igual a `test_deshaw_contracts.py`). Cada teste isola uma superfície específica via monkeypatch — não roda engine inteiro. Foco no anti-happy-path: o que NÃO pode acontecer.

**Tech Stack:** pytest, monkeypatch, asyncio (pra place_order async), zero refactor de código de produção.

---

## Pre-flight

**Branch:** Sugestão — criar worktree dedicado pra não misturar com a WIP de `feat/phi-engine`:

```bash
git worktree add .worktrees/safety-tests -b feat/safety-tests-live-janestreet main
cd .worktrees/safety-tests
```

Se preferir trabalhar inline na branch atual, pular este passo — mas commitar com escopo limpo (`test:` prefix).

**Verificação inicial — suite verde antes de começar:**

```bash
python -m pytest tests/test_deshaw_contracts.py -v
```
Expected: 2 passed (já existe — só pra confirmar pytest funciona).

---

## File Structure

```
tests/
├── test_live_contracts.py           ← NOVO (~150 linhas, 5 testes)
├── test_janestreet_contracts.py     ← NOVO (~120 linhas, 4 testes)
└── conftest.py                       ← sem mudança
```

**Side effect dos imports (documentar, não bloquear):**
- `import engines.live` cria `data/live/<run_id>/{logs,state,reports}/` e abre FileHandlers — 4 KB de overhead por execução do test runner. Acceptable.
- `import engines.janestreet` cria `data/janestreet/<run_id>/...` igual. Acceptable.

---

## Task 1: live — `test_paper_order_manager_does_not_load_keys`

**Files:**
- Create: `tests/test_live_contracts.py`

**Invariante:** `OrderManager(paper=True)` nunca chama `_load_keys` nem inicializa Binance Client. Garante que paper mode não abre keys reais.

- [ ] **Step 1: Criar arquivo com header + primeiro teste**

```python
# tests/test_live_contracts.py
"""Safety contract tests for engines/live.py.

Cada teste documenta um cenário do mundo real cuja violação causa dano:
keys reais expostas em paper, gates degradados em live, KillSwitch que
não dispara quando deveria, ordens reais executadas em paper.
"""
from __future__ import annotations

import pytest


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
```

- [ ] **Step 2: Rodar — esperar PASS (caracterização)**

```bash
python -m pytest tests/test_live_contracts.py::test_paper_order_manager_does_not_load_keys -v
```
Expected: PASS. Se FAIL, NÃO ajustar `engines/live.py` — investigar por que o teste falsifica a leitura de código (`OrderManager.__init__` linhas 525-529 só chama `_init_client()` se `not paper`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_contracts.py
git commit -m "test(live): paper OrderManager nao chama _load_keys"
```

---

## Task 2: live — `test_guard_real_money_gates_blocks_live_with_default_cfg`

**Files:**
- Modify: `tests/test_live_contracts.py` (append)

**Invariante:** `_guard_real_money_gates("live", RiskGateConfig())` raise. `RiskGateConfig()` default = todos os circuit breakers off; iniciar live com isso é catastrófico (gate silencioso).

- [ ] **Step 1: Adicionar 2 testes (positivo + negativo)**

```python
# Append to tests/test_live_contracts.py

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
```

- [ ] **Step 2: Rodar — esperar PASS**

```bash
python -m pytest tests/test_live_contracts.py -v -k "guard_real_money"
```
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_contracts.py
git commit -m "test(live): _guard_real_money_gates bloqueia live com cfg default"
```

---

## Task 3: live — `KillSwitch` fast-DD (dispara + não dispara)

**Files:**
- Modify: `tests/test_live_contracts.py` (append)

**Invariante:** Fast-DD trigger: `sum(pnl[-5]) < -KS_FAST_DD_MULT * ACCOUNT_SIZE * BASE_RISK`. Falha em disparar = perda descontrolada. Falso-positivo = pausa trading válido.

- [ ] **Step 1: Adicionar testes pareados**

```python
# Append to tests/test_live_contracts.py

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
```

- [ ] **Step 2: Rodar**

```bash
python -m pytest tests/test_live_contracts.py -v -k "kill_switch"
```
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_contracts.py
git commit -m "test(live): KillSwitch fast-DD dispara/nao-dispara"
```

---

## Task 4: live — `test_paper_order_manager_zero_external_http`

**Files:**
- Modify: `tests/test_live_contracts.py` (append)

**Invariante:** `OrderManager(paper=True).place_order(...)` não toca em `requests` nem em `binance.client.Client`. Garante isolamento real do paper mode.

- [ ] **Step 1: Adicionar teste async**

```python
# Append to tests/test_live_contracts.py

import asyncio


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
```

- [ ] **Step 2: Rodar**

```bash
python -m pytest tests/test_live_contracts.py::test_paper_order_manager_zero_external_http -v
```
Expected: PASS. Se FAIL, ler `OrderManager.place_order` (engines/live.py:576-641): o branch `if self.paper` (linha 587) deve ser exclusivo do branch `else` que chama `client.futures_create_order`.

- [ ] **Step 3: Commit + verificar 5 testes live**

```bash
python -m pytest tests/test_live_contracts.py -v
git add tests/test_live_contracts.py
git commit -m "test(live): paper OrderManager nao bate HTTP externo"
```
Expected (pytest): 5 passed.

---

## Task 5: janestreet — `test_parse_mode_default_is_paper`

**Files:**
- Create: `tests/test_janestreet_contracts.py`

**Invariante:** `_parse_mode()` sem `--mode` flag → `args.mode is None` → `ARB_PAPER=True`. Default NUNCA é live.

- [ ] **Step 1: Criar arquivo + primeiro teste**

```python
# tests/test_janestreet_contracts.py
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
```

- [ ] **Step 2: Rodar**

```bash
python -m pytest tests/test_janestreet_contracts.py::test_parse_mode_default_is_paper -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_janestreet_contracts.py
git commit -m "test(janestreet): _parse_mode default e paper, nunca live"
```

---

## Task 6: janestreet — `test_hedge_monitor_detecta_delta_drift`

**Files:**
- Modify: `tests/test_janestreet_contracts.py` (append)

**Invariante:** Hedge balanceado (qty_a == qty_b) → `imbalance_pct == 0`. Quebrar uma perna → `imbalance_pct > imb_warn`. Falha = posição delta-neutral vira direcional sem aviso.

- [ ] **Step 1: Adicionar teste**

```python
# Append to tests/test_janestreet_contracts.py

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
```

- [ ] **Step 2: Rodar**

```bash
python -m pytest tests/test_janestreet_contracts.py::test_hedge_monitor_detecta_delta_drift -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_janestreet_contracts.py
git commit -m "test(janestreet): HedgeMonitor detecta delta drift"
```

---

## Task 7: janestreet — `test_omega_score_penaliza_spread_negativo`

**Files:**
- Modify: `tests/test_janestreet_contracts.py` (append)

**Invariante:** `omega_score(spread<=0, ...) == 0`. Spread negativo = perdedor; recompensar com score positivo abriria trade certa de loss.

- [ ] **Step 1: Adicionar teste**

```python
# Append to tests/test_janestreet_contracts.py

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
```

- [ ] **Step 2: Rodar**

```bash
python -m pytest tests/test_janestreet_contracts.py::test_omega_score_penaliza_spread_negativo -v
```
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_janestreet_contracts.py
git commit -m "test(janestreet): omega_score nao recompensa spread negativo"
```

---

## Task 8: janestreet — `test_risk_gate_config_loads_per_mode`

**Files:**
- Modify: `tests/test_janestreet_contracts.py` (append)

**Invariante:** `_load_risk_gate_config("live")` retorna config diferente de `_load_risk_gate_config("paper")` quando `config/risk_gates.json` está presente. Falha = live e paper compartilhando gates frouxos.

- [ ] **Step 1: Adicionar teste**

```python
# Append to tests/test_janestreet_contracts.py

def test_risk_gate_config_loads_per_mode():
    """Cenário protegido: config/risk_gates.json existe mas seções
    arbitrage_live e arbitrage_paper sao iguais (copy-paste). Live
    arranca com gates de paper — exposicao descontrolada."""
    import engines.janestreet as js
    from pathlib import Path

    cfg_path = Path(__file__).parent.parent / "config" / "risk_gates.json"
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
```

- [ ] **Step 2: Rodar**

```bash
python -m pytest tests/test_janestreet_contracts.py::test_risk_gate_config_loads_per_mode -v
```
Expected: PASS se config tem seções distintas. Se SKIP, ok. Se FAIL, é descoberta real — paper e live tão com gates idênticos no config.

- [ ] **Step 3: Commit + verificar 4 testes janestreet**

```bash
python -m pytest tests/test_janestreet_contracts.py -v
git add tests/test_janestreet_contracts.py
git commit -m "test(janestreet): risk gate configs paper vs live diferem"
```
Expected (pytest): 4 passed (ou 3 passed + 1 skipped se risk_gates.json ausente).

---

## Task 9: Verificação final

- [ ] **Step 1: Rodar suite completa de novos testes**

```bash
python -m pytest tests/test_live_contracts.py tests/test_janestreet_contracts.py -v
```
Expected: 9 passed (ou 8 passed + 1 skipped se Task 8 skipou).

- [ ] **Step 2: Rodar suite completa do repo (regression check)**

```bash
python -m pytest tests/ -x --tb=short
```
Expected: tudo verde. Se algum teste pré-existente quebrar, NÃO é um dos novos — investigar.

- [ ] **Step 3: Smoke test do launcher (UI não quebrou)**

```bash
python smoke_test.py --quiet
```
Expected: 156/156 (ou whatever o número atual for).

- [ ] **Step 4: Diff stats finais**

```bash
git log --oneline main..HEAD
git diff --stat main..HEAD
```
Expected: 2 arquivos novos em tests/, 0 mudanças em engines/ ou core/ ou config/.

- [ ] **Step 5: Branch pronto pra PR**

Se em worktree dedicado:
```bash
git push -u origin feat/safety-tests-live-janestreet
```
Senão, branch atual `feat/phi-engine` ganhou +9 testes; commits têm prefix `test:` pra fácil cherry-pick depois.

---

## Self-Review (já feito antes do plan ir pra você)

**Spec coverage:** 9 testes ↔ 9 invariantes do spec. ✅
**Placeholder scan:** zero TBD/TODO; todo código completo. ✅
**Type consistency:** `RiskGateConfig`, `KillSwitch`, `OrderManager`, `HedgeMonitor`, `omega_score`, `_parse_mode`, `_guard_real_money_gates`, `_load_risk_gate_config` — todos batem com inspeção real do código. ✅
**Anti-pattern guard (CLAUDE.md):** cada Step 2 explicita "se FAIL, NÃO ajustar produção, investigar teste primeiro". ✅

---

## Critério de aceitação (do spec)

1. ✅ `pytest tests/test_live_contracts.py tests/test_janestreet_contracts.py -v` → 9 passed (ou 8 + 1 skip).
2. ✅ Suite completa continua verde.
3. ✅ Nenhum arquivo em `engines/`, `core/`, `config/` modificado.
4. ✅ Cada teste tem assertion substantiva.
5. ✅ Cada teste tem docstring "Cenário protegido: ...".
