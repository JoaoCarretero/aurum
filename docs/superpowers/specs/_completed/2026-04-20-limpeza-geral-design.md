# Limpeza Geral — Design (2026-04-20)

## Resumo

Varredura coordenada em três eixos — **A) disk hygiene**, **B) performance**,
**C) dead code** — pra deixar o software mais organizado, mais limpo, e
mais rápido sem tocar no CORE PROTEGIDO de trading. Alvo:
~2 GB a menos no OneDrive, −40% walkforward CITADEL, −20% suite pytest,
~4 arquivos órfãos resolvidos.

**Não-alvos:** Lane 1 launcher split (continua em paralelo), slice de
`engines_live_view.py`/`janestreet.py`/`report_html.py` (subprojetos
D/E/F, ficam pra outra sessão), qualquer mudança em lógica de sinal,
sizing, custos ou risco.

---

## Contexto

**Estado atual (varredura 2026-04-20):**

- `data/` = 2.9 GB total. `bridgewater/` = 1.4 GB em 230 runs;
  `aurum.db` = 440 MB; runs de deshaw/millennium/runs somam ~600 MB.
- Walkforward CITADEL 180d = 47s. `GaussianHMMNp.fit` = 43% (~20s).
- Pytest completo = 85s pra 1374 testes; fixtures I/O-heavy, +30 dirs
  órfãos em `tests/_tmp/`.
- `core/ui/ui_palette.py` puxa pandas + requests eager no import chain
  — atraso no launcher cold start.
- `server/website/dist/assets/index-*.js` (684 KB) trackeado em git
  indevidamente.
- 4 candidatos a dead code: `engines/meanrev.py`,
  `tools/meanrev_*_search.py` (2), `code_viewer.py` (root),
  `engines/millennium_live.py`.
- Bridgewater flagado **BUG_SUSPECT** no OOS verdict 2026-04-16 —
  runs antigas não são confiáveis.

**Por que atacar agora:** OneDrive sync pesado, dia-a-dia de iteração
custa tempo em backtest + suite, e dead code suspeito acumula dívida
de atenção.

---

## Princípios

1. **Reversibilidade total.** Nada é `rm -rf` direto. Tudo que sai do
   repo vai antes pra `~/aurum-archive/` em zip. Worst-case, unzip traz
   de volta.
2. **CORE PROTEGIDO intocado.** Zero linhas em `core/indicators.py`,
   `core/signals.py`, `core/portfolio.py`, `config/params.py`.
3. **Incrementos commitáveis.** A, B e C são commits separados. Cada um
   verificável individualmente por `smoke_test.py` + suite.
4. **Observação → ação.** Antes de deletar/arquivar qualquer arquivo
   suspeito de dead code, fazer grep final pra confirmar zero
   referências ativas.
5. **Sem hotfixes de teste.** Testes existentes devem continuar
   passando. Se quebrar, a regressão tá no nosso lado, não no teste.

---

## Sub-projeto A — Disk hygiene

### Alvo
Reduzir `data/` de 2.9 GB pra ~900 MB (−69%). Remover build artifacts
indevidos do git. Limpar lixo de teste.

### Ações

**A.1 — Bridgewater runs:** zipar todas as 230 run dirs em
`~/aurum-archive/bridgewater_runs_2026-04-20.zip`, apagar
`data/bridgewater/*` do repo. Recuperação: unzip sob demanda.

**A.2 — `data/aurum.db` VACUUM:**
- Script `tools/maintenance/db_vacuum.py` que:
  1. Faz backup em `~/aurum-backups/aurum.db.<stamp>.bak` (fora do
     OneDrive).
  2. Roda `VACUUM` via sqlite3 (fecha conexões primeiro).
  3. Reporta tamanho antes/depois + top 5 tabelas por linha.
- Se após VACUUM ainda >200 MB, reportar ao Joao antes de mexer.

**A.3 — Retenção de runs por engine:** nova política **keep-last-10**
por engine. Script `tools/maintenance/archive_old_runs.py` que:
- Aplica em `data/{deshaw,millennium,runs,renaissance,jump,citadel,
  jane_street,de_shaw,...}/`
- Lista diretórios timestamped, ordena por mtime desc, mantém top 10.
- Restante vai pra `~/aurum-archive/<engine>_older_2026-04-20.zip`.
- Dry-run por padrão; `--apply` pra executar.

**A.4 — `data/db_backups/`:** mesma política, `--keep 5`.

**A.5 — `nexus.db` trio:** grep de `nexus.db` no repo inteiro. Se zero
referências ativas, zipar em `~/aurum-archive/nexus_db_2026-04-20.zip`
e remover. Se tiver referência, preservar + documentar.

**A.6 — `server/website/dist/` do git:**
- `git rm -r --cached server/website/dist/`
- Adicionar `server/website/dist/` ao `.gitignore`
- Confirmar que `server/website/package.json` tem script de build
  (usuário roda antes de deploy — não precisa estar no repo).

**A.7 — `tests/_tmp/pytest-*` órfãos:** `rm -rf tests/_tmp/pytest-*/`.
Auto-recria no próximo run. Adicionar ao `.gitignore` se não estiver.

### Validação
- `smoke_test.py --quiet` — 178/178 verde.
- Suite completa — 1374 passed ou mais (pode ganhar 1 teste flaky
  recuperado se fixture pollution sumir).
- `du -sh data/` < 1 GB.
- `git status` clean.

### Commit
`chore(cleanup): disk hygiene — archive old runs, VACUUM db, remove
dist from git`

---

## Sub-projeto B — Performance

### Alvo
Walkforward CITADEL 180d: 47s → ~28s (−40%).
Pytest completo: 85s → ~68s (−20%).
Launcher cold import chain: mensurável, alvo S/M.

### Ações

**B.1 — HMM cache (`core/hmm_cache.py`):**
- Dict global in-memory com key `(symbol, bar_range_hash, param_hash)`.
  - `bar_range_hash` = sha1 de `(start_ts, end_ts, n_bars, last_close)`.
  - `param_hash` = sha1 do dict de params HMM serializado (sorted
    keys).
- Valor guardado: tuple `(trans_matrix, means, covars,
  start_probs, log_likelihood)`.
- `core.chronos.GaussianHMMNp.fit` passa a consultar o cache antes de
  rodar. Hit → retorna. Miss → fit + store.
- Opt-in persist: se `AURUM_HMM_CACHE_PERSIST=1`, serializa em
  `data/_cache/hmm/{hash}.pkl` (gitignored).
- Invalidação manual: `tools/maintenance/clear_hmm_cache.py`.

**B.2 — Pytest session fixtures OHLCV:**
- Novo `tests/conftest.py` (ou extensão do existente) com:
  - `@pytest.fixture(scope="session") synthetic_ohlcv(symbol, n_bars)`
    retornando DataFrame congelado.
  - Helper `fresh_copy()` pra testes que precisam mutar (retorna
    `.copy()`).
- Migrar testes mais lentos pra usar fixture session quando aplicável.
- **Não migrar em massa** — escolher os 10 mais lentos via
  `pytest --durations=10` e migrar cirurgicamente.

**B.3 — Lazy-import em `core/ui/ui_palette.py`:**
- Ler arquivo, identificar imports pesados top-level (pandas,
  requests, e outros não-stdlib).
- Mover pra dentro de funções que efetivamente os usam.
- Se `ui_palette` só define constantes/dicts de cor → nenhum pandas
  deve aparecer. Se aparecer via dependência transitiva (`core/ui/
  __init__.py` puxa `core/__init__.py` que puxa pandas), atacar
  a cadeia.
- Medir antes/depois com `python -X importtime -c "import launcher" |
  tail -30`.

### Validação
- `smoke_test.py --quiet` — continua 178/178.
- Suite completa — mesmos testes, tempo reduzido.
- Benchmark CITADEL walkforward 180d — tempo antes/depois reportado
  no session log.
- `python -X importtime` — delta reportado.

### Commit
`perf(cleanup): HMM cache + session-scoped fixtures + lazy ui imports`

---

## Sub-projeto C — Dead code

### Alvo
4 arquivos suspeitos resolvidos (arquivar, deletar, ou documentar por
que ficam).

### Ações

**C.1 — `engines/meanrev.py` (626 LOC):**
- Verificar `config/engines.py` — se ausente do registry, engine
  morto.
- Grep em `tests/`, `tools/`, `launcher*`, `engines/` por `meanrev`.
- Se só auto-referência (próprio test + battery), mover pra
  `engines/_archive/meanrev.py` + atualizar qualquer import que ainda
  apontar pra ele.

**C.2 — `tools/meanrev_partial_revert_search.py`,
`tools/meanrev_snapback_search.py`:**
- Scripts soltos no root de `tools/`. Provavelmente investigação
  fechada do meanrev.
- Mover pra `tools/_archive/`.

**C.3 — `code_viewer.py` (root do repo):**
- Grep confirma 1 hit (próprio arquivo?). Ler pra entender o que faz.
- Se utility ad-hoc sem chamadores, mover pra `tools/_archive/`.
- Se é algo em uso (ex: atalho pro Joao), manter + adicionar
  comentário de propósito.

**C.4 — `engines/millennium_live.py` (209 LOC):**
- Referenciado por tests + `tools/maintenance/millennium_shadow.py`.
- Ler e decidir: é shim vivo (ativo em shadow/live) ou morto (restou
  do refactor)?
- Se vivo → adicionar header docstring explicando papel.
- Se morto → arquivar + atualizar importadores pra usar
  `engines/millennium.py` direto.

### Validação
- `smoke_test.py --quiet` — 178/178.
- Suite completa — todos passam (imports podem ter mudado).
- `git status` clean.

### Commit
`chore(cleanup): archive dead-code candidates — meanrev, meanrev_*,
code_viewer, millennium_live (if dead)`

---

## Ordem de execução

1. **A primeiro.** Mais seguro (só mexe em data/ e dist/), maior
   retorno (~2 GB). Commit atômico.
2. **B segundo.** Mexe em código real mas com escopo claro.
   Validação forte (smoke + suite + benchmark).
3. **C por último.** Requer leitura cuidadosa dos 4 arquivos pra
   decidir. Mais suscetível a quebrar imports; por isso vai depois
   de B quando a suite já tá estável.

Cada sub-projeto vira um commit separado. Session log + daily log no
final, como sempre.

---

## Riscos e mitigações

| Risco | Mitigação |
|-------|-----------|
| Arquivo zipado é necessário depois | `~/aurum-archive/` preservado com zip por tópico; unzip sob demanda |
| VACUUM corrompe `aurum.db` | Backup em `~/aurum-backups/` antes |
| HMM cache retorna stale (key colisão) | Hash inclui last_close + n_bars — muda com novos dados |
| Session fixture pollution quebra teste | `.copy()` por padrão quando teste muta |
| Lazy import quebra palette em dev | Benchmarking + smoke test cobrem caminho normal |
| Arquivo "dead" virou dead por engano (está em uso raro) | Grep triplo (tests, tools, launcher, engines) antes de mover; se dúvida, documenta e não move |

---

## Métricas a reportar no session log

- `du -sh data/` antes/depois
- `python smoke_test.py --quiet` tempo antes/depois
- `pytest tests/ -q` tempo antes/depois
- Walkforward CITADEL 180d tempo antes/depois (se rodar benchmark)
- Número de arquivos arquivados em `~/aurum-archive/`
- Arquivos dead code resolvidos (com decisão de cada)

---

## Garantias transversais

- **Zero linhas** em `core/indicators.py`, `core/signals.py`,
  `core/portfolio.py`, `config/params.py`.
- `tools/maintenance/verify_keys_intact.py` rodado antes de qualquer
  toque em config/.
- `config/keys.json` **intocado**.
- `~/aurum-archive/` preservado (não em OneDrive, fora de repo).
- Session log + daily log gerados no final.
