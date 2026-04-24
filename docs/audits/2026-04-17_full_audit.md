# AURUM Finance — Full System Audit (2026-04-17)

**Escopo:** auditoria full-stack em 4 dimensões (trading core, segurança, qualidade/testes, engines+branch).
**Método:** 4 agentes paralelos, cada um com escopo específico. Resultados consolidados abaixo.
**Branch:** `feat/phi-engine` (45 commits ahead of main, 58 arquivos tocados).

---

## TL;DR — Top 10 achados ordenados por impacto

| # | Severidade | Área | Achado | Ação sugerida |
|---|-----------|------|--------|----------------|
| 1 | 🔴 CRITICAL | Security | `.gitignore` não cobre `config/keys.json.enc` — migração futura pode vazar ciphertext | 1 linha no `.gitignore` |
| 2 | 🔴 CRITICAL | Security | `risk_gates.json` ausente no VPS = **todos os circuit breakers desligados** em modos `testnet`/`demo` | Verificar/commitar defaults conservadores |
| 3 | 🟠 HIGH | Trading | `vol_regime` passado para `position_size()` mas **silenciosamente ignorado** — `VOL_RISK_SCALE` não afeta sizing | Decidir: aplicar a escala, ou remover `VOL_RISK_SCALE` de params.py |
| 4 | 🟠 HIGH | Security | `pickle.load` em `core/cache.py` e `launcher.py` — RCE via OneDrive sync comprometido | Migrar cache para parquet/feather |
| 5 | 🟠 HIGH | Security | Telegram auth usa `chat_id == from_id` — frágil em grupos | Allowlist explícita de user IDs |
| 6 | 🟠 HIGH | Security | `engines/live.py` usa `_REST_BASE["live"] = None` — depende de defaults da lib Binance | Hardcodar `https://fapi.binance.com` |
| 7 | 🟠 HIGH | Branch | BRIDGEWATER **BUG_SUSPECT** confirmado (10 field fails no OOS 2026-04-17) | Fix ou quarentena explícita antes de merge |
| 8 | 🟡 MEDIUM | Trading | `_omega_risk_mult` definido e importado, **nunca chamado** — `OMEGA_RISK_TABLE` sem efeito | Ativar ou remover |
| 9 | 🟡 MEDIUM | Trading | `label_trade` pode marcar LOSS no bar do sinal, antes da execução em `open[idx+1]` | Adicionar teste sintético |
| 10 | 🟡 MEDIUM | Quality | 11 de 14 engines sem teste dedicado (só phi, kepos, graham têm) | Prioridade baixa — contracts cobrem core |

**Estado geral:** sistema saudável na estrutura (test suite 178/178, 1005 tests, zero TODOs reais). Riscos concentrados em: (1) *configuração por omissão* em segurança, (2) parâmetros no `params.py` sem efeito real no pipeline.

---

## 1. Trading Core Audit

### Status geral
Estruturalmente sólido. RSI usa EWM com `com=RSI_PERIOD-1` (correto — Wilder's smoothing). Pivots são backward-only (ataque do Codex 2026-04-15 não está presente). `label_trade` simétrico BULLISH/BEARISH. 3 issues reais, 1 de impacto direto em PnL.

### HIGH (pode afetar PnL real)

- **`core/portfolio.py:121-156` — `vol_regime` aceito mas silenciosamente ignorado em `position_size`**
  `VOL_RISK_SCALE` em `params.py` define multiplicadores por regime vol (LOW=0.85, HIGH=0.70, EXTREME=0.00), e o param é passado pelo engine (`citadel.py:317`). Mas dentro de `position_size` o argumento é recebido e nunca lido — não há `VOL_RISK_SCALE.get(vol_regime, 1.0)` aplicado ao risk.
  Em `decide_direction` (`signals.py:42-43`) é usado como gate de veto (EXTREME bloqueia), mas HIGH/LOW não afetam sizing.
  **Consequência:** em regime HIGH vol, entra com mesmo size que em NORMAL — contrário à intenção documentada (`"iter6 1080d bluechip: LOW vol avg -2 PnL/trade"`).

### MEDIUM (suspeito, merece teste)

- **`core/portfolio.py:91-103` — `_omega_risk_mult` definido, exportado, importado em `citadel.py:43`, nunca chamado**
  A função escala risco por faixa de Ω score via `OMEGA_RISK_TABLE` em params, mas não é invocada em nenhum ponto do pipeline. Backtests calibrados assumindo que a tabela está ativa produzem expectativas incorretas de sizing.

- **`core/signals.py:265-266` / `label_trade` — primeiro bar do loop pode produzir LOSS antes da execução real**
  Loop começa em `entry_idx` mas entrada real é `open[idx+1]`. Para BULLISH, se `l[entry_idx] <= stop`, trade marca LOSS ainda no bar do sinal — antes da entrada ter ocorrido. Improvável (stop fica abaixo do swing_low), mas com stops apertados em alta vol pode criar falsos LOSS.

### LOW

- **`config/params.py:229`** — comentário inline `SCORE_THRESHOLD = 0.53 # fallback global ... 0.55 seria ótimo mas colide com cliff 0.56` documenta escolha baseada em sensitivity test não arquivada em `grid.md`. Viola protocolo anti-overfit (grid fechado + DSR).

### Verificado e OK

- RSI usa EWM equivalente exato ao Wilder's smoothing (α=1/14). Ataque do Codex (rolling+tanh) ausente.
- Pivots backward-only em `indicators.py:66` — janela `[i-PIVOT_N : i+1]`, sem look-ahead.
- `label_trade` simetria BULLISH/BEARISH: liquidation, breakeven, trailing, target corretamente espelhados para SHORT.
- Mudanças em `core/cache.py` e `core/data.py` (branch `feat/phi-engine`) são puramente infraestrutura. Não tocam em coluna OHLCV nem em cálculo de indicador/sinal. **Impacto zero no core de trading.**

---

## 2. Security Audit

### Postura geral
Scaffolding bem estruturado (Fase 4): audit trail, risk gates, key store encriptado, guard obrigatório para live. Risco imediato **não é código mal-escrito** — é configuração por omissão que deixa proteções desativadas em runtime.

### CRITICAL (exploit hoje, money loss)

- **`.gitignore` não cobre `config/keys.json.enc`**
  `.gitignore:22` cobre `config/keys.json` mas não o equivalente encriptado. Se Joao migrar para o encrypted store com `encrypt_from_plaintext()`, ciphertext pode entrar num commit acidental. PBKDF2 no disco permite brute-force offline com GPU.
  **Fix:** adicionar `config/keys.json.enc` ao `.gitignore` (1 linha).

- **`core/risk_gates.py` — defaults todos permissivos**
  `RiskGateConfig` defaults: `max_daily_dd_pct=100.0`, `max_daily_loss_pct=100.0`, `max_consecutive_losses=999`, `max_gross_notional_pct=1e9`.
  `_guard_real_money_gates()` protege modo `"live"` e `"arbitrage_live"`, mas modos `"testnet"` e `"demo"` arrancam com circuit breakers desligados.
  **Se `config/risk_gates.json` não existir no VPS, nenhum gate dispara** mesmo com capital real durante validação.
  **Fix:** verificar existência do arquivo no VPS antes de qualquer sessão live + commitar defaults conservadores.

### HIGH (exploit with conditions)

- **`bot/telegram.py:327-328` — autorização por `chat_id == from_id` frágil**
  Funciona para DMs onde `chat_id == user_id`, mas em grupos o `chat_id` do grupo ≠ `user_id` de qualquer membro. Se `chat_id` em `keys.json` for de um grupo, guard passa para qualquer membro.
  Atualmente não há comandos destrutivos (só `/status`, `/trades`, `/pos`, `/kill`), mas o padrão é frágil. **Fix:** allowlist explícita de `ALLOWED_USER_IDS` separada do `chat_id`.

- **`core/cache.py:64,88` e `launcher.py:7458` — `pickle.load` em arquivos locais**
  Cache de candles usa `pickle.load` em `.pkl.gz` dentro de `data/cache/`. **Ameaça concreta:** se atacante tiver escrita no OneDrive (cloud sync comprometida, malware local), pode injetar pickle malicioso executado com permissões do processo AURUM.
  **Fix:** migrar para `pd.read_parquet` / `feather` ou verificar hash após leitura.

- **`engines/live.py` — modo `"live"` usa `_REST_BASE["live"] = None`**
  `OrderManager._init_client()` instancia `binance.Client(testnet=False)` sem URL override explícito — depende de defaults da biblioteca. Se versão instalada mudar endpoint padrão, usa produção silenciosamente.
  **Fix:** hardcodar `https://fapi.binance.com` + verificar no `_verify_api_connection`.

### MEDIUM

- **`api/auth.py:17` — `_INSECURE_DEFAULT_SECRET` visível no código-fonte**
  String `"aurum-dev-secret-change-in-production"` em texto claro. Rejeitada em runtime, mas qualquer JWT assinado com esse secret (ex: CI sem env vars) é válido. Substituir por sentinel sem semântica de secret.

- **`core/audit_trail.py` — `hash_chain=False` é o default**
  `LiveEngine.__init__` usa `True`, mas construtor default é `False`. Qualquer outro caller sem flag explícito produz trail não-encadeado, sem evidência de tampering. **Inverter default.**

- **`core/key_store.py:243-251` — `encrypt_from_plaintext` não deleta plaintext**
  Documentado explicitamente, mas `keys.json` plaintext fica no disco + OneDrive sync indefinidamente após migração.

### LOW / hygiene

- `core/connections.py` guarda `last_ping` com `datetime.now()` (local) mas resto do sistema usa UTC.
- `engines/live.py:262-265` — verificação de `chmod 600` em `keys.json` só roda em `sys.platform != "win32"`, nunca executa no Windows 11 (ambiente dev primário).
- `config/connections.json` não no `.gitignore` — pode conter endpoints internos.
- `core/exchange_api.py` silencia exceções com `except Exception: return None` — erros de rede e 401/403 ficam indistinguíveis.

### Verificado e OK

- **`api/auth.py`**: JWT com bcrypt, `_guard_real_money_gates()` recusa live com defaults permissivos, separação `get_current_user` / `require_admin`.
- **`core/db.py`**: todas queries SQLite usam parametrização (`?`), sem string formatting; path traversal bloqueado por `is_relative_to(DATA_DIR)`.
- **Telegram commands**: nenhum atualmente destrutivo; todos read-only; rate limiting 3s implementado.

---

## 3. Code Quality & Test Coverage

### Executable checks
- **Smoke test:** PASS 178/178 (subiu de 156 reportado no CLAUDE.md)
- **Pytest collection:** 1005 tests collected
- **TODOs/FIXMEs:** 0 reais (2 comentários informativos em `ablation_test.py`, não TODOs)
- **Files changed on branch:** 15

### Test coverage gaps

**MEDIUM:**
- `bot/telegram.py` — 16KB, sem teste dedicado
- `analysis/` — 14 módulos sem teste (benchmark, charts, compare_runs, diagnostics, montecarlo, overfit_audit, plots, report_html, results_gui, robustness, stats, walkforward, live_replay_test, _chart_palette)
- `core/exchange_api.py` — sem teste
- `core/alchemy_ui.py` — sem teste

**Engines sem teste (11/14):** aqr, bridgewater, citadel, deshaw, janestreet, jump, live, medallion, millennium, renaissance, twosigma. Apenas phi (417 linhas, 23 tests), kepos (458 linhas), graham (358 linhas) têm testes dedicados. *Compensado parcialmente por contract tests em core/.*

> **Nota:** agente reportou `launcher_support/engines_live_view.py` como "MISSING" gerando 24 test failures. **Falso positivo** — arquivo existe (39KB, apenas modificado). Agente foi confundido por cópia em `.worktrees/engines-live-cockpit/`.

### Dead code / imports

- **Violação arquitetural (provavelmente intencional):** `engines/millennium.py` importa de outros engines (`citadel`, `deshaw`, `jump`, `bridgewater`, `twosigma`). CLAUDE.md registra `multistrategy` como exceção documentada — mas `millennium` é o "multistrategy" de fato. **Quick win:** adicionar docstring explícito.
- **Imports não usados (cosmético):** `from __future__ import annotations` em `core/funding_scanner.py:42` e `core/exchange_api.py:10` (redundante em Python 3.14). `millennium.py` tem `ThreadPoolExecutor, as_completed, np, pd` importados e não usados diretamente.
- `core/proc.py` funções parecem dead por análise estática mas são chamadas via dynamic imports — safe.

### Print statements em produção

**1188 prints** em core/, engines/, tools/. Concentração:
- `engines/millennium.py`: 128 prints
- `engines/citadel.py`: 99 prints
- `aurum_cli.py`: 83 prints

Bypass da infraestrutura de logging. **Quick win alto retorno:** trocar por `log.info()`.

### Skipped tests (todos com reason clara)
- `test_phase_c_backtest_characterization.py` / `test_phase_c_live_characterization.py` — fixture-only replay não cableado
- `test_proc_contracts.py:189` — Windows-only identity check
- `test_signals_contracts.py:99` — depende de `LEVERAGE=1.0`

### Quick wins
1. Trocar `print()` por `log.info()` nos top 3 arquivos (1188 prints)
2. Adicionar docstring em `millennium.py` documentando o padrão multi-strategy
3. Adicionar teste contract para `bot/telegram.py` (ativo, sem teste)
4. Consolidar `core/mt5.py`, `core/transport.py`, `core/ui_palette.py` em contract tests mínimos

---

## 4. Engines Status & Branch Readiness

### Inventário de engines

| Arquivo | Status | Última modificação |
|---------|--------|---------------------|
| citadel.py | ✅ OOS ok (EDGE_DE_REGIME) | 2026-04-16 |
| renaissance.py | ⚠️ Sharpe inflado 2×; revalidado 2.421 | 2026-04-16 |
| jump.py | ✅ OOS ok (Sharpe 3.15, EDGE_DE_REGIME) | 2026-04-16 |
| bridgewater.py | 🔴 BUG_SUSPECT (10 field fails) | 2026-04-16 |
| deshaw.py | 🔴 NO_EDGE_OU_OVERFIT (Sharpe -1.726 BEAR) | 2026-04-16 |
| medallion.py | 🔴 NO_EDGE_OU_OVERFIT (Sharpe -3.218) | 2026-04-16 |
| kepos.py | 🔴 INSUFFICIENT_SAMPLE (0 trades BEAR) | 2026-04-16 |
| graham.py | 🗄️ Arquivado (4h overfit, honesto) | 2026-04-16 |
| phi.py | 🆕 Novo, scaffold completo + sweeps A/B/C | 2026-04-16 |
| janestreet.py | ⚪ Não coberto OOS (arb, não direcional) | 2026-04-15 |
| twosigma.py | ⚪ Desconhecido (não na bateria OOS) | 2026-04-14 |
| aqr.py | ⚪ Desconhecido | 2026-04-15 |
| millennium.py | Orquestrador meta | 2026-04-16 |
| live.py | Runner (não engine de sinal) | 2026-04-16 |

### Engines não listados em CLAUDE.md

- **`phi.py`** — novo, Fibonacci fractal. Em desenvolvimento neste branch.
- **`kepos.py`** — Hawkes-based (OOS INSUFFICIENT_SAMPLE).
- **`medallion.py`** — Berlekamp-Laufer 7-signal (OOS NO_EDGE).
- **`graham.py`** — arquivado mas ainda no disco.

**Ação:** atualizar tabela de engines em CLAUDE.md.

### Branch `feat/phi-engine`

- **Commits ahead of main:** 45
- **Arquivos tocados:** 58 (+13,304 / -465)
- **Magnitude:** large — contém 4 escopos distintos:
  1. Novo engine PHI (1130 linhas, 23 tests passando)
  2. Novo engine MEDALLION (945 linhas, arquivado)
  3. Cockpit engines-live-view (902 linhas)
  4. Bloco 0 OOS revalidation (tools + audits + protocolo anti-overfit + DSR)

### Mudanças em core (não-protegido) — risco de backtest

- **`core/data.py`** — param `end_time_ms` em `fetch`/`fetch_all` para retro OOS/holdout. **Risco baixo:** opcional, default `None` preserva comportamento.
- **`core/cache.py`** — `end_time_ms` (slice pré-tail) + `max_age_seconds` (TTL por mtime). **Risco baixo:** slice estritamente inclusivo (`df[time <= cutoff]`). Previne cache stale em live sem invalidar históricos.
- `core/run_manager.py`, `core/site_runner.py`, `config/paths.py` — infra não-trading.

### Phi engine — status

- ✅ Código completo: CLI main, scan_symbol loop, backtest multi-symbol, kill-switch (2.618%/6.18%), níveis fib (SL 0.786 / TPs 1.272/1.618/2.618), trailing, sizing Golden Convex cap 2%, clusters multi-TF, merge_asof HTF sem lookahead.
- ✅ Teste: 23/23 passing, inclui teste explícito de lookahead em zigzag/indicadores.
- ✅ Gatekeeping correto: registrado em `config/engines.py` mas **NÃO em FROZEN_ENGINES / ENGINE_INTERVALS** até overfit_audit 6/6 passar.
- ✅ Sweeps Stage A, B (grid 5-dim), C (universe top 4) já rodados.

### Testes de contract (novos + modificados)

- `test_cache_contracts.py` **(novo)** — valida TTL rejeita cache stale + slice histórico OK mesmo com arquivo antigo.
- `test_site_runner_contracts.py` **(novo)** — valida comando splittado em argv sem shell=True.
- `test_auth_contracts.py`, `test_data_contracts.py`, `test_structure_contracts.py` **(modificados)** — ajustes de assinatura após `end_time_ms`.
- **Resultado:** `32 passed in 1.88s` nos 5 arquivos.

### OOS revalidation 2026-04-17 (Bloco 0)

- 7 engines re-rodados, reprodutibilidade verificada, cost symmetry tabulada, lookahead scan estático.
- **6/7 PASS reprodutibilidade; BRIDGEWATER FAIL (10 field fails)** — confirma BUG_SUSPECT.
- **Zero look-ahead leaks** detectados (9 hits, todos legítimos: execução next-bar open).
- Verdicts: CITADEL/RENAISSANCE/JUMP = EDGE_DE_REGIME; DESHAW/MEDALLION = NO_EDGE_OU_OVERFIT; BRIDGEWATER = BUG_SUSPECT; KEPOS = INSUFFICIENT_SAMPLE.

### Go/no-go merge: **NEEDS WORK**

Branch tem valor real (PHI + Bloco 0 + cockpit) mas escopo muito grande para merge atômico.

**Não-bloqueadores:**
- Testes passam (32 contract + 23 phi + 178 smoke).
- Mudanças em `core/data.py` + `core/cache.py` aditivas e seguras.
- Zero look-ahead detectado.
- PHI corretamente gatekept fora de FROZEN_ENGINES.

**Bloqueadores antes do merge:**
1. **Trabalho não-committed** (10 arquivos modificados, 5 novos) — commitar antes de qualquer merge.
2. **BRIDGEWATER BUG_SUSPECT** não resolvido — fix ou flag explícita de quarentena.
3. **Escopo misto** — ideal partir em 3 PRs: (a) Bloco 0 + tools + DSR; (b) PHI engine; (c) cockpit + launcher. Merge monolítico dificulta revert cirúrgico.

**Recomendação:** commit WIP → decidir sobre split → resolver BRIDGEWATER → abrir PR(s).

---

## Ação consolidada (prioridade)

### Imediato (hoje, baixo custo, alto valor)
1. **[SEC-CRITICAL-1]** Adicionar `config/keys.json.enc` ao `.gitignore`
2. **[SEC-CRITICAL-2]** Verificar/commitar `config/risk_gates.json` com defaults conservadores
3. **[BRANCH-1]** Commitar WIP não-committed
4. **[CLAUDE.md]** Atualizar tabela de engines (faltam phi, kepos, medallion, graham)

### Curto prazo (esta semana)
5. **[TRAD-HIGH]** Decisão sobre `vol_regime`: aplicar em `position_size` ou remover `VOL_RISK_SCALE` de params
6. **[TRAD-MED]** Decisão sobre `_omega_risk_mult`: ativar ou remover `OMEGA_RISK_TABLE`
7. **[SEC-HIGH-1]** Allowlist explícita de user IDs no Telegram bot
8. **[SEC-HIGH-2]** Hardcodar `https://fapi.binance.com` em `engines/live.py`
9. **[BRANCH-2]** Decisão sobre split do branch em 3 PRs
10. **[BRANCH-3]** Resolver BRIDGEWATER BUG_SUSPECT ou quarentenar

### Médio prazo (próximas 2 semanas)
11. **[SEC-HIGH-3]** Migrar cache de pickle para parquet/feather
12. **[SEC-MED-1]** Inverter default de `AuditTrail(hash_chain=True)`
13. **[QUAL-1]** Trocar `print()` por `log.info()` em millennium/citadel/aurum_cli (310 prints)
14. **[QUAL-2]** Adicionar teste contract para `bot/telegram.py`
15. **[TRAD-MED]** Teste sintético para falso LOSS no bar do sinal em `label_trade`

---

## 5. Addendum — BRIDGEWATER deep-dive (2026-04-17)

Agente dedicado investigou o BUG_SUSPECT de BRIDGEWATER após as ondas de fix iniciais.

### Root cause

**Bug principal** — `engines/bridgewater.py:88,96,101` usa `limit=100` (funding) e `limit=200` (OI, LS ratio) hardcoded. Funding no Binance é emitido a cada 8h: 100 pontos cobrem apenas ~33 dias. Numa janela OOS de 360 dias (BEAR 2022), **as primeiras ~327 dias de barras caem antes do primeiro ponto da série de sentimento**.

`engines/bridgewater.py:143-148` — `_align_series_to_candles` propaga `values[0]` (primeiro valor disponível) para todas as barras anteriores ao início da série, em vez de usar `default=0.0`. Resultado: ~90% das barras recebem o mesmo valor de sentimento fixo.

**Consequência:** O **Sharpe 11.04 é espúrio** — artefato de truncamento, não edge real. Cada run da Binance retorna ticks ligeiramente diferentes dependendo de timing, alterando o valor constante propagado e gerando as 1630 trades de diferença (9194 → 7564 fresh).

### Bug adicional (falso positivo do audit)

`tools/oos_revalidate.py:283` verifica assinatura de `fetch_funding_rate` com string antiga (sem `end_time_ms`). O sentiment.py já foi atualizado mas o detector continua flagando como unbounded.

### Fix acionável

Três mudanças, todas fora do core protegido:

```python
# engines/bridgewater.py:88,96,101 — escalar limit com a janela
_funding_limit = min(1000, int(SCAN_DAYS * 3 * 1.2))    # 3 ticks/dia + 20% buffer
_oi_limit      = min(1500, int(SCAN_DAYS * 96 * 1.1))   # 15m: 96 pontos/dia
_ls_limit      = min(1500, int(SCAN_DAYS * 96 * 1.1))

# engines/bridgewater.py:143-148 — default em vez de values[0]
if first_valid > 0:
    aligned[:first_valid] = default   # era values[0]

# tools/oos_revalidate.py:283 — fix do detector
if "end_time_ms" not in sentiment_text.split("def fetch_funding_rate")[1].split("\n")[0]:
```

### Risco

Após o fix, **o Sharpe vai cair radicalmente** (parte do "edge" era artefato). O engine precisa re-calibração — provavelmente cai pra NO_EDGE_OU_OVERFIT. Melhor saber agora do que descobrir em capital real.

### Recomendação

Aplicar o fix, re-rodar OOS BEAR, e decidir:
- Sharpe OOS real > 1.5 → manter, marcar como re-calibrado
- Sharpe OOS real < 1.5 → arquivar (junto com DE SHAW, MEDALLION, KEPOS)

---

## 6. Addendum — Second-pass (performance / concurrency / resilience)

Agente dedicado varreu dimensões não cobertas no audit original. Novos achados:

### 🔴 CRITICAL

- **`engines/live.py:1147` — race condition em `self.positions`**
  `_reconciliation_loop` itera `self.positions` enquanto `_open_position` dá append no mesmo objeto (asyncio task paralela). Python asyncio não previne race se houver yield points — pode ver lista parcialmente atualizada ou pular entrada.
  **Fix 1 linha:** `for p in list(self.positions):` (snapshot).

- **`engines/live.py:598-611` — `futures_create_order` sem timeout explícito**
  `binance.Client` usa default da lib (~30s), mas API pode ficar lenta em burst. Sem retry. Ordem pode ficar "hanging" — engine pensa que está pending quando não foi enviada.
  **Fix:** timeout explícito + retry com backoff exponencial.

### 🟠 HIGH

- **`engines/live.py:1560-1576` — API error gate bloqueia engine 60s**
  Quando `_consecutive_api_errors >= 5`, chama `asyncio.sleep(60)` que pausa o event loop inteiro. Websockets continuam mas `on_candle_close` retorna cedo. Posições em progresso podem expirar de stop durante a pausa.

- **`core/cache.py:101-116` — file I/O race entre engines paralelos**
  Dois engines escrevendo cache do mesmo símbolo ao mesmo tempo → um perde via `os.replace`. `try/except` silencia, mas data loss em backtest paralelo.

- **`core/indicators.py:66-67` — swing pivot detection em Python puro** *[CORE PROTEGIDO]*
  Loop com `max()/min()` em slice por barra: O(n × PIVOT_N). Pandas `.rolling().max()/min()` seria O(n). ~10× mais rápido em live update (5ms → <1ms). Fora de hot path do backtest mas importante em latência de decisão.

### 🟡 MEDIUM

- **`analysis/montecarlo.py:12-24`** — 10k simulações em Python loops puros. Vetorização com numpy daria 10-50×. Off hot path (roda 1× por backtest), baixa prioridade.
- **`engines/live.py:2169-2202`** — WS reconnect não faz `log.error(exc_info=True)`. Crash de `on_candle_close` fica sem stacktrace.
- **`bot/telegram.py:95-119`** — `_post` silencia todas exceções com `return {}`. Operator cego pra falhas de API do Telegram.
- **`engines/live.py:1817-1827`** — kill-switch não idempotente. Chamar 2× tenta flatten duplo.

### ✅ Verificado OK

- Indicators vetorizados (ewm, rolling, np.select) — zero loops em hot path nos principais
- WS reconnect com backoff exponencial (5s → 300s)
- Retry logic com 429/5xx em `core/data.py`
- Kill-switch estatístico + risk gates implementados e testados
- Audit trail encadeado (intent → ack → fill)

### Quick wins (priorizado)

1. **1 linha**: `for p in list(self.positions):` em `_reconciliation_loop` — elimina CRITICAL #1 acima
2. **3 linhas**: timeout explícito em `futures_create_order` — elimina CRITICAL #2
3. **1 param**: `log.error(..., exc_info=True)` no WS handler — debug de crashes
4. **2 linhas**: check `resp.json()` em `bot/telegram.py:112` — detecta Telegram API errors

---

## 7. Errata

Correções pós-audit ao documento original:

- **TL;DR item #4 (pickle.load em `core/cache.py`)** — FALSO POSITIVO. Cache usa JSON dentro de gzip (extensão `.pkl.gz` é legacy). Zero `pickle.load` no codebase. Removido da ação required.
- **Item #3 (vol_regime ignorado)** — após investigação, confirmado que é intencional (v3.7 session log `2026-04-12_1505.md` registrou remoção de 8→3 fatores). As funções órfãs (`_omega_risk_mult`, `_global_risk_mult`) foram removidas na onda de fix. `VOL_RISK_SCALE` sobrevive como veto em `decide_direction`, não como multiplicador de sizing.

---

## 8. Addendum — Structural audit (wave 3)

Dois agentes paralelos varreram dimensões estruturais não cobertas nas waves 1–2: grafo de imports/dependências e gestão de estado/configuração/paridade backtest↔live.

### A. Arquitetura & dependências

**Saúde geral: 7/10.** Camadas estão bem separadas (`core` ← `engines` ← `analysis`), a regra "engines não importam engines" é respeitada (só MILLENNIUM viola, documentado). Ciclos: zero. God-module em `launcher.py` (12.5k linhas mistura GUI + orquestração + lógica).

**Findings acionáveis:**

- **🟠 HIGH — `analysis/live_replay_test.py:34` viola camada** importando `engines.live.LiveEngine`. Analysis não deveria depender de engine concreto. Fix: extrair `LiveEngine` ou usar injeção via callable.

- **🟡 MEDIUM — `core/engine_base.py` é dead code** (0 imports no codebase). Classe `EngineRuntime` (62 linhas) nunca foi adotada. Ou todos engines migram pra ela, ou deleta.

- **🟡 MEDIUM — Duplicação massiva em 5 engines** (graham, kepos, live, medallion, phi). Funções repetidas: `_setup_logging` (5×), `_trades_to_serializable` (4×), `_pnl_with_costs` (4×), `_resolve_exit` (3×), `scan_symbol` (5×), `save_run` (4×), `run_backtest` (6×). ~200 linhas de boilerplate por engine que deveriam estar em `core/engine_utils.py`.

- **🟡 MEDIUM — Pipeline comum `indicators → swing_structure → omega` duplicada em 8 engines**. Candidato a `core.data.apply_core_features(df)`.

- **🟢 OK — Core é coeso**: `indicators.py` (176L/7fn), `portfolio.py` (140L/6fn), `signals.py` (315L/8fn) — propósitos únicos, tamanhos saudáveis.

### B. Estado, config & paridade backtest↔live

**Saúde geral: 8/10.** `config/params.py` realmente é single source (confirmado via `__all__` + `from config.params import *` em 8 engines). Custos, sinais, sizing, filtros e cooldowns todos têm paridade bitwise backtest↔live. Atomic writes aplicados. Audit trail robusto (append-only + hash chain).

**Findings acionáveis:**

- **🔴 CRITICAL — `AURUM.spec:8` inclui `config/` inteira no bundle**
  ```python
  datas=[('C:\\Users\\Joao\\OneDrive\\aurum.finance\\config', 'config')],
  ```
  Se o `.exe` for distribuído ou roubado, `keys.json` plaintext vaza junto. **Fix:** excluir `keys.json` dos `datas` + documentar uso de `AURUM_KEY_PASSWORD` + `keys.json.enc` em produção.

- **🟠 HIGH — Timezone inconsistente**
  `datetime.now()` (naive) em `launcher.py:1195`, `engines/citadel.py:75`, `core/engine_base.py:22-23`. Resto do sistema usa `datetime.now(timezone.utc)`. No VPS Linux UTC isso funciona por coincidência, mas RUN_IDs gerados no Windows (UTC-3) divergem. Fix: mecânico, substituir em todos.

- **🟠 HIGH — Sem reconciliation automático de entry_price**
  Live roda `fetch_account_positions()` no startup, mas não compara contra `positions.json`. Se processo morre entre `trail.write(intent)` e `place_order()`, o restart não sabe que o intent nunca virou ordem real. Precisa de `--reconcile-exchange` flag explícito que aborte se divergência > threshold.

- **🟡 MEDIUM — Funding: discreto em backtest, contínuo em live**
  Backtest aplica `FUNDING_PER_8H / periods × duration_periods`. Live acumula tick-by-tick. Trades que passam uma barreira de 8h podem divergir. Mitigado por `MAX_HOLD=96` (24h) mas não zerado.

- **🟡 MEDIUM — Cache sprawl em `data/.cache/*.pkl.gz`** sem TTL. Cleanup manual. Acumula indefinidamente.

- **🟢 OK — Backtest↔Live paridade confirmada** para: custos (SLIPPAGE+SPREAD+COMMISSION+FUNDING), `decide_direction`, `score_omega`, `position_size`, `SPEED_MIN`, `SESSION_BLOCK_HOURS`, `VETO_HOURS_UTC`, `STREAK_COOLDOWN`, `SYM_LOSS_COOLDOWN`.

- **⚠️ Env vars dispersas sem registrador central:**
  `AURUM_NO_CACHE`, `AURUM_JWT_SECRET`, `AURUM_MACRO_MODE`, `AURUM_CANARY_MODE`, `AURUM_CANARY_PCT`, `AURUM_PHASE_C_CAPTURE_*`, `AURUM_KEY_PASSWORD`, `AURUM_ARB_LATENCY_BPS`, `AURUM_HL_WHALES`. Não é bug mas é surface area crescente.

### C. Prioridade consolidada (wave 3)

| # | Severidade | Área | Fix |
|---|-----------|------|-----|
| 1 | 🔴 CRITICAL | Deploy | Remover `keys.json` do PyInstaller bundle |
| 2 | 🟠 HIGH | Consistency | `datetime.now(timezone.utc)` em launcher/citadel/engine_base |
| 3 | 🟠 HIGH | Arquitetura | `analysis/live_replay_test.py` — remover import de engine concreto |
| 4 | 🟠 HIGH | Resilience | `--reconcile-exchange` flag no startup do live |
| 5 | 🟡 MEDIUM | Duplicação | `core/engine_utils.py` centralizando `_pnl_with_costs` etc |
| 6 | 🟡 MEDIUM | Cleanup | Deletar ou adotar `core/engine_base.py::EngineRuntime` |
| 7 | 🟡 MEDIUM | Ops | Cache TTL cleanup tool |
| 8 | 🟡 MEDIUM | Paridade | Funding continuous equivalente no backtest |

---

**Gerado por:** 4 agentes (wave 1) + 2 agentes (wave 2) + 2 agentes (wave 3 estrutural), Claude Opus 4.7, em 2026-04-17.
**Arquivos de referência:** `docs/audits/2026-04-16_oos_verdict.md`, `docs/audits/2026-04-17_oos_revalidation.md`, `docs/methodology/anti_overfit_protocol.md`, `docs/sessions/2026-04-12_1505.md`.
