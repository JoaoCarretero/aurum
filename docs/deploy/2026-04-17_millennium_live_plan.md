# MILLENNIUM · Plano de deploy em camadas

**Branch:** `feat/phi-engine`
**Config auditada:** commit `4508c60` (B_cooldowns)
**Audit:** 6/6 PASS em 360d / 720d / 1000d · docs/audits/2026-04-17_millennium_cooldowns_overfit_audit.md
**Data:** 2026-04-17

---

## Estado atual do repositório

| Componente | live-ready | Observação |
|---|---|---|
| CITADEL standalone | ✅ `live_ready: True` em `config/engines.py` | Único engine com live runner validado via `engines/live.py` |
| JANE STREET | ✅ `live_ready: True` | Delta-neutral arb, independente do pod |
| MILLENNIUM ensemble | ❌ `live_ready: False`, `live_bootstrap: True` | Só tem shadow runner + bootstrap plan |
| MILLENNIUM full execution loop | **BLOQUEADO** | RENAISSANCE e JUMP não têm streaming adapters first-class |

**Implicação:** não dá pra rodar o pod MILLENNIUM em live real hoje sem
antes construir os adapters streaming pra JUMP e RENAISSANCE. Documentado
em `engines/millennium_live.py` (bootstrap plan honesto).

---

## Camadas de deploy (ordem obrigatória)

### 🟢 Camada 0 — SHADOW (sem capital, sem ordens)

O que já tenho pronto pra subir hoje.

- `tools/millennium_shadow.py` roda o scan do MILLENNIUM em loop a cada
  15min, detecta trades novos, grava em JSONL append-only
- **Nunca envia ordem**, nunca carrega keys, nunca toca exchange API de write
- Systemd unit em `deploy/millennium_shadow.service`
- Installer one-shot: `deploy/install_shadow_vps.sh`

**Objetivo da camada 0:** colher 24–48h de sinais OOS ao vivo, comparar
distribuição de trades vs histórico 360d/720d/1000d. Se convergir,
passa pra próxima. Se divergir (ex: 0 trades, ou picos de LOSS),
investigar antes de ir adiante.

**Não requer decisão de capital.** Seguro.

### 🟡 Camada 1 — CITADEL standalone em PAPER mode

Quando camada 0 validar, o engine operacional único que pode virar live
hoje é **CITADEL sozinho** — tem live runner em `engines/live.py`.

- Ativar em `paper` primeiro: `python engines/live.py --mode paper --engine citadel`
- PortfolioMonitor registra trades simulados em banco local
- Mesmas regras de custo/slippage do backtest
- Telegram notifica cada sinal/trade

**Objetivo da camada 1:** validar que o pipeline live reproduz o edge
do backtest no engine que já tem live runner. Sem capital exposto.

### 🟠 Camada 2 — CITADEL em TESTNET (Binance)

Se paper mode bater com backtest, ir pra Binance testnet. Ordens reais
com capital fake da testnet.

- Config em `config/connections.json` (modo `testnet`)
- Keys de testnet (não são as prod)
- Mesma `engines/live.py` com `--mode testnet`

**Objetivo da camada 2:** validar integração exchange (latência, slippage
real, ordens rejeitadas, reconexão de WS). Sem capital real.

### 🔴 Camada 3 — CITADEL em LIVE REAL (capital mínimo)

**Requer aprovação explícita do João em chat.** Não executo sem isso.

- Pre-flight checklist em `deploy/preflight_live.md` (a criar)
- Capital inicial: $100–$500 (mínimo pra validar custos reais)
- Risk gates de `core/risk_gates.py` ativados com thresholds agressivos
- Kill-switch testado
- Audit trail SHA-256 em `core/audit_trail.py`

### 🔒 Camada 4 — MILLENNIUM full pod em live

**Bloqueado hoje.** Exige antes:
1. Adapter streaming pro JUMP (order-flow em tempo real)
2. Adapter streaming pro RENAISSANCE (harmônicos sobre candle live)
3. Testes de concorrência entre 3 engines + portfolio risk budget
4. Novo audit completo do full pod

Esforço estimado: 1–2 semanas por engine.

---

## O que eu executo agora sem precisar de confirmação adicional

1. **PR `feat/phi-engine` → `main`** — sincroniza trabalho do dia, 19 commits
2. **Script de deploy e docs** — `deploy/install_shadow_vps.sh` e
   `deploy/README.md` já commitados
3. **Validação final da suite** — `pytest tests/` (1103 passed expected)

## O que DEPENDE de ação tua

1. **Subir shadow no VPS** — tu executa os 3 comandos SSH no teu VPS
   (não tenho credencial)
2. **Autorização capital real** — obrigatória antes de camada 3,
   explícita em chat

---

## Estrutura final do repo pra suportar tudo isso

```
aurum.finance/
├── engines/
│   ├── citadel.py              live_ready ✅    (camada 1-3)
│   ├── millennium.py           batch + shadow   (camada 0)
│   ├── millennium_live.py      bootstrap plan   (camada 4, scaffolding)
│   └── live.py                 runtime live     (usado por camada 1-3)
├── tools/
│   ├── millennium_shadow.py    camada 0 runner
│   ├── millennium_gate_grid.py grid config sweep
│   └── ... (phi/deshaw batteries)
├── deploy/
│   ├── millennium_shadow.service  systemd unit camada 0
│   ├── install_shadow_vps.sh      installer one-shot
│   └── README.md                   deploy guide
├── docs/
│   ├── audits/                    auditorias do dia
│   ├── deploy/                    planos de deploy
│   └── methodology/               anti_overfit_protocol
└── config/
    ├── engines.py                 registry (live_ready flags)
    ├── params.py                  CORE (risk, size, costs)
    └── connections.json           exchange mode (paper/demo/testnet/live)
```
