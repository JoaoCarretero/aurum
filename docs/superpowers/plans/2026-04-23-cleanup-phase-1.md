# Cleanup Phase 1 — "Clear The Decks" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deletar 4 engines arquivados (deshaw/kepos/medallion/ornstein = 5,187 LOC) + todas suas referências + unused imports via ruff F401, preservando funcionalidade dos engines ativos.

**Architecture:** Branch dedicada `feat/cleanup-phase-1` de `chore/repo-cleanup`. Commits atômicos em 3 fases: (A) remover referências aos engines arquivados em código ativo, (B) deletar os arquivos `.py`, (C) polir com ruff F401. Cada commit tem gate de validação (pytest + launcher import) antes do próximo.

**Tech Stack:** Python 3.11.5, pytest 8.4.2, ruff (instalar ad-hoc), git.

**Spec:** `docs/superpowers/specs/2026-04-23-cleanup-phase-1-design.md` (commit 8f7a55a)

**Descobertas do mapeamento de refs (mudanças vs spec):**
- **hmmlearn + arch NÃO são órfãs** — `core/chronos.py` (WINTON engine ativo) e `launcher_support/briefings.py` usam ambas. Task de "remove orphan deps" vira **task de verificação** (no-op documentado).
- **Mais tests a atualizar do que previsto** — `tests/contracts/test_deshaw_contracts.py` (file inteiro, deletar), `tests/contracts/test_db_contracts.py` (2 lines de `_normalize_engine("newton") == "deshaw"`), `tests/integration/test_engines_live_view.py` (assertions + uso de "deshaw"/"kepos" como examples experimentais).
- **launcher.py tem 14+ refs hardcoded** (menu, dir mappings, dict) — task dedicada.
- **engines/aqr.py linha 144** tem print help apontando pra `python -m engines.deshaw` — pequena fix.

---

## File Structure

### Arquivos a MODIFICAR (referências)

| File | Linhas relevantes | Change type |
|------|-------------------|-------------|
| `config/engines.py` | 16, 21, 23, 25 (ENGINES dict), 65, 67, 68, 69 (EXPERIMENTAL_SLUGS), 96-99 (newton→deshaw), 130-134 (kepos), 140-144 (medallion) | Remove entries |
| `engines/millennium.py` | ~2047-2063, ~2102-2116, ~2166-2180 | Remove 3 DE SHAW blocks |
| `engines/aqr.py` | 144 | Remove print line |
| `launcher.py` | 250, 254, 256 (menu), 382, 385, 386 (dict), 6891, 8496, 8673, 8729, 9114, 9120, 9121, 9124 (dir mappings) | Remove entries |
| `launcher_support/bootstrap.py` | 25-27 (newton→deshaw alias), 44 (prefix list) | Remove entries |
| `launcher_support/briefings.py` | 462-463 (deshaw briefing block — likely whole dict key) | Remove deshaw briefing |
| `tools/anti_overfit_grid.py` | 122-127 (deshaw), 186-191 (kepos), 258-263 (medallion), 343-356 (config dicts) | Remove specs |
| `tools/audits/full_registry_audit.py` | 78-133 (4 engine entries) | Remove entries |
| `tools/audits/engine_validation.py` | 54 (deshaw entry) | Remove entry |
| `tests/contracts/test_db_contracts.py` | 80, 100-101 (newton→deshaw tests) | Remove 2 test cases |
| `tests/integration/test_engines_live_view.py` | 24-25, 118-120 | Substitute "deshaw"/"kepos" por um engine active (ex: phi ou winton) |

### Arquivos a DELETAR

| File | LOC |
|------|-----|
| `engines/deshaw.py` | 1,539 |
| `engines/kepos.py` | 961 |
| `engines/medallion.py` | 998 |
| `engines/ornstein.py` | 1,689 |
| `tests/engines/test_kepos.py` | 32 tests |
| `tests/engines/test_ornstein.py` | 22 tests |
| `tests/engines/test_medallion.py` | 5 tests |
| `tests/contracts/test_deshaw_contracts.py` | full file |
| `docs/engines/deshaw/` | dir |
| `docs/engines/kepos/` | dir |
| `docs/engines/medallion/` | dir |
| `docs/engines/ornstein_v2/` | dir |

### Arquivos intocados (fora de escopo)

- CORE: `config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`
- `core/chronos.py` (usa hmmlearn/arch — STAY)
- `launcher_support/briefings.py` hmmlearn/arch imports — STAY (outros briefings usam)
- Audits em `docs/audits/*{deshaw,kepos,medallion,ornstein}*.md` — STAY (justificam archive)

---

## Task 1: Setup — branch + ruff + baseline

**Files:** (nenhum modificado; só infra)

- [ ] **Step 1: Criar branch dedicada**

```bash
git checkout chore/repo-cleanup
git pull origin chore/repo-cleanup
git checkout -b feat/cleanup-phase-1
```

- [ ] **Step 2: Instalar ruff no venv**

```bash
.venv/Scripts/python.exe -m pip install ruff
```

Expected output: `Successfully installed ruff-X.Y.Z`

- [ ] **Step 3: Rodar baseline de tests pra confirmar 1,740 pass**

```bash
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q 2>&1 | tail -5
```

Expected output: `1740 passed, 8 skipped` (or very close). **Anote o número exato** — será o baseline pra comparar ao final.

- [ ] **Step 4: Contar LOC baseline (pra métrica de sucesso)**

```bash
wc -l engines/deshaw.py engines/kepos.py engines/medallion.py engines/ornstein.py
```

Expected: total 5,187.

- [ ] **Step 5: Push branch vazia pro origin (checkpoint)**

```bash
git push -u origin feat/cleanup-phase-1
```

---

## Task 2: Remove archived engines from `config/engines.py`

**Files:**
- Modify: `config/engines.py` (remove 4 entries from ENGINES dict, 4 from EXPERIMENTAL_SLUGS, 3 from canonical mappings)

- [ ] **Step 1: Read current state**

```bash
.venv/Scripts/python.exe -c "from config.engines import ENGINES, EXPERIMENTAL_SLUGS; print(f'engines={len(ENGINES)} experimental={len(EXPERIMENTAL_SLUGS)}')"
```

Anote os 2 números (serão 16 engines + 5 experimental atualmente; após = 12 engines + 1 experimental).

- [ ] **Step 2: Edit `config/engines.py` — remove from ENGINES dict**

Remove linhas que matcham (use Edit tool com `replace_all=false` per ocorrência):

```python
    "deshaw":      {"script": "engines/deshaw.py",       "display": "DE SHAW",     "desc": "Engle-Granger pairs statistical arbitrage",               "module": "BACKTEST", "stage": "experimental",       "sort_weight": 30,  "live_ready": False},
```
```python
    "kepos":       {"script": "engines/kepos.py",        "display": "KEPOS",       "desc": "Critical endogeneity fade via Hawkes η",                  "module": "BACKTEST", "stage": "experimental",       "sort_weight": 72,  "live_ready": False},
```
```python
    "medallion":   {"script": "engines/medallion.py",    "display": "MEDALLION",   "desc": "Short-horizon ensemble with Kelly sizing",                "module": "BACKTEST", "stage": "experimental",       "sort_weight": 76,  "live_ready": False},
```
```python
    "ornstein":    {"script": "engines/ornstein.py",     "display": "ORNSTEIN",    "desc": "Mean-reversion ARCHIVED 2026-04-22 (regime mismatch — crypto nao e mean-reverting em 15m/1h)",      "module": "BACKTEST", "stage": "experimental",      "sort_weight": 79,  "live_ready": False},
```

- [ ] **Step 3: Edit `config/engines.py` — remove from EXPERIMENTAL_SLUGS**

Remove estas 4 linhas do frozenset (com os comentários trail):

```python
    "deshaw",    # ARCHIVED 2026-04-22 (verdict docs/audits/2026-04-22_deshaw_phi_ornstein). Backtest 360d bluechip 1h: Sharpe −0.19, ROI −0.33%. 4 gates do overfit audit falharam (walk-forward, regime concentration, symbol concentration FETUSDT 363% do PnL negativo, temporal decay 246%). Grid esgotado.
    "ornstein",  # ARCHIVED 2026-04-22 (verdict docs/audits/2026-04-22_deshaw_phi_ornstein). Strict filter zera sample; exploratory solto colapsa Sharpe −31.98. Regime mismatch: crypto 15m/1h e trending (H ~0.8+), nao mean-reverting. Grid esgotado.
    "kepos",     # Smoke last-360d 2026-04-17 pós-fixes completos (cost asymmetry + eta 0.95→0.75 + sustained 10→5 + k_sigma 2.0→1.0): 164 trades, Sharpe -2.08, ROI -36%, MDD 46%. Rodável mas "fade extensions" thesis sem edge em mercado atual.
    "medallion", # Smoke last-360d 2026-04-17 pós-fix cost asymmetry: Sharpe -3.69, ROI -35%, MDD 35%. Grid-best in-sample foi overfit canônico (Codex audit flag).
```

- [ ] **Step 4: Edit `config/engines.py` — remove canonical mappings**

Remove estes 3 blocos de `LEGACY_ALIASES` / canonical dict (uses `replace_all=false`):

Block 1 (newton→deshaw mapping):
```python
    "newton": {
        "script": ENGINES["deshaw"]["script"],
        "display": "DE SHAW",
        "canonical": "deshaw",
    },
```

Block 2 (kepos canonical):
```python
    "kepos": {
        "script": ENGINES["kepos"]["script"],
        "display": "KEPOS",
        "canonical": "kepos",
    },
```

Block 3 (medallion canonical):
```python
    "medallion": {
        "script": ENGINES["medallion"]["script"],
        "display": "MEDALLION",
        "canonical": "medallion",
    },
```

- [ ] **Step 5: Verify config/engines.py imports and shape**

```bash
.venv/Scripts/python.exe -c "from config.engines import ENGINES, EXPERIMENTAL_SLUGS; print(f'engines={len(ENGINES)} experimental={len(EXPERIMENTAL_SLUGS)}'); assert 'deshaw' not in ENGINES; assert 'kepos' not in ENGINES; assert 'medallion' not in ENGINES; assert 'ornstein' not in ENGINES; print('config/engines.py OK')"
```

Expected: `engines=12 experimental=1 ... config/engines.py OK`

- [ ] **Step 6: Run tests — expect some failures (callsites still reference these engines)**

```bash
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q 2>&1 | tail -10
```

Expected: failures em tests que importam ou dependem de `ENGINES["deshaw"]` etc. Esperado — próximas tasks limpam callsites.

**Anote os failures** — servem de checklist pro que ainda falta limpar.

- [ ] **Step 7: Commit**

```bash
git add config/engines.py
git commit -m "chore(config): remove archived engines from ENGINES registry

Remove deshaw, kepos, medallion, ornstein from config/engines.py
ENGINES dict, EXPERIMENTAL_SLUGS frozenset, and canonical mapping
dict. Callsites (millennium.py, launcher.py, tools/) cleaned in
subsequent commits.

Audits justifying archive live in docs/audits/ and stay preserved.
Branches backup on origin: feat/claude-{deshaw,kepos,medallion}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 3: Clean `engines/millennium.py` DE SHAW references

**Files:**
- Modify: `engines/millennium.py` (3 DE SHAW blocks)

- [ ] **Step 1: Locate exact blocks**

```bash
grep -n "from engines.deshaw import" engines/millennium.py
```

Expected: 3 matches at lines ~2047, ~2102, ~2166 (line numbers may shift).

- [ ] **Step 2: Edit block 1 — interactive menu option "4"**

Localize o bloco em `engines/millennium.py` que começa com `elif op == "4":` e contém `from engines.deshaw import find_cointegrated_pairs, scan_pair`. O bloco termina antes do próximo `elif` ou `else`.

Remove o **bloco inteiro** (o elif + body). Exemplo do bloco:

```python
    elif op == "4":
        from engines.deshaw import find_cointegrated_pairs, scan_pair
        print(f"\n{SEP}\n  COINTEGRATION ANALYSIS\n{SEP}")
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        newton_all.sort(key=lambda t: t["timestamp"])
        if not newton_all: print("  Sem trades."); sys.exit(1)
        _resultados_por_simbolo(newton_all, show_he=False)
        _metricas_e_export(newton_all, label="DE SHAW")
```

Find o `elif op == "4":` block exact, remove it whole.

- [ ] **Step 3: Edit blocks 2 and 3 — "run all engines" aggregate blocks**

2 blocos adicionais seguem padrão idêntico (2 ocorrências em ~linha 2102 e ~2166):

```python
        from engines.deshaw import find_cointegrated_pairs, scan_pair
        pairs = find_cointegrated_pairs(all_dfs)
        newton_all = []
        for pair in pairs:
            df_a = all_dfs.get(pair["sym_a"])
            df_b = all_dfs.get(pair["sym_b"])
            if df_a is None or df_b is None: continue
            trades, _ = scan_pair(df_a.copy(), df_b, pair["sym_a"], pair["sym_b"],
                                  pair, macro_series, corr)
            newton_all.extend(trades)
        engine_trades["DE SHAW"] = newton_all
```

Remove ambos blocos. Como são idênticos ou quase, use Edit com `replace_all=true` se forem 100% idênticos, ou dois Edit separados se houver diferenças sutis (verifique com `diff`).

- [ ] **Step 4: Verify no more deshaw refs in millennium.py**

```bash
grep -n "deshaw" engines/millennium.py
```

Expected: empty (0 matches).

- [ ] **Step 5: Run millennium-related tests**

```bash
.venv/Scripts/python.exe -m pytest tests/engines/ tests/contracts/ -q --ignore=tests/test_cockpit_paper_endpoints.py 2>&1 | tail -5
```

Expected: tests de engines ativos passam. Tests de deshaw/kepos/medallion ainda existem, vão falhar/error — OK.

- [ ] **Step 6: Smoke import millennium**

```bash
.venv/Scripts/python.exe -c "from engines.millennium import _scan_one_engine_live; print('millennium imports OK')"
```

Expected: `millennium imports OK`

- [ ] **Step 7: Commit**

```bash
git add engines/millennium.py
git commit -m "chore(millennium): remove DE SHAW cointegration blocks

Remove 3 blocks that imported engines.deshaw and ran pair
cointegration scans:
- interactive menu option '4' (COINTEGRATION ANALYSIS)
- 2 aggregate 'run all engines' blocks populating DE SHAW

Archived engine per docs/audits/2026-04-22_deshaw_phi_ornstein_archive_verdict.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 4: Clean `launcher.py` archived engine references

**Files:**
- Modify: `launcher.py` (14 line refs spread across file)

- [ ] **Step 1: Snapshot current refs**

```bash
grep -n "deshaw\|kepos\|medallion\|ornstein\|DE SHAW\|KEPOS\|MEDALLION\|ORNSTEIN" launcher.py | head -30
```

Anote os line numbers — serão guia pros edits.

- [ ] **Step 2: Remove engine menu entries (lines ~250, 254, 256)**

Localize o tuple list que contém:

```python
        ("DE SHAW",      "engines/deshaw.py",         "Statistical arb — pairs cointegration + mean reversion"),
```

Remove esta linha. Também remove:

```python
        ("KEPOS",        "engines/kepos.py",       "Critical endogeneity fade — Hawkes ? reversal plays"),
```

E:

```python
        ("MEDALLION",    "engines/medallion.py",   "Berlekamp-Laufer — 7-signal ensemble + Kelly sizing"),
```

Nota: não há entry "ORNSTEIN" no menu list (verifica). Se houver, remove também.

- [ ] **Step 3: Remove icon/emoji mappings (lines ~382-386)**

Localize dict de icons (provavelmente `_ENGINE_ICONS` ou similar) com lines:

```python
    "deshaw":             "??",
```
```python
    "kepos":              "??",
```
```python
    "medallion":          "??",
```

Remove os 3.

- [ ] **Step 4: Remove dict de slugs (line ~6891)**

Localize linha:
```python
                "deshaw":      "deshaw",
```
dentro de algum mapping dict (provavelmente de slug→canonical). Remove. Também se houver kepos/medallion/ornstein no mesmo dict.

- [ ] **Step 5: Remove data dir mappings — 2 dicts (lines ~8496 e ~9114-9124)**

**Primeiro dict (line ~8496):**
```python
            "deshaw":      ROOT / "data" / "deshaw",
```

Procure se esse dict tem também `"kepos"`, `"medallion"`, `"ornstein"` — remove todos.

**Segundo dict (line ~9114-9124):**
```python
                "deshaw":      ROOT / "data" / "deshaw",
                ...
                "kepos":       ROOT / "data" / "kepos",
                "medallion":   ROOT / "data" / "medallion",
                ...
                "ornstein":    ROOT / "data" / "ornstein",
```

Remove as 4 linhas.

- [ ] **Step 6: Remove display name mappings (line ~8673)**

```python
            "deshaw":        "DE SHAW",
```

Também kepos/medallion/ornstein se aparecerem no mesmo dict.

- [ ] **Step 7: Remove prefix list for run_dir matching (line ~8729)**

Localize:
```python
                "citadel_", "thoth_", "bridgewater_", "newton_", "deshaw_",
```

Remove `"newton_"` e `"deshaw_"` desta tuple/list (se aparecerem). Verifique se há `kepos_`, `medallion_`, `ornstein_` — remove.

- [ ] **Step 8: Verify no residual refs in launcher.py**

```bash
grep -cE "deshaw|kepos|medallion|ornstein|DE SHAW|KEPOS|MEDALLION|ORNSTEIN" launcher.py
```

Expected: `0`

- [ ] **Step 9: Smoke import launcher**

```bash
.venv/Scripts/python.exe -c "import launcher; print('launcher imports OK')"
```

Expected: `launcher imports OK`

- [ ] **Step 10: Commit**

```bash
git add launcher.py
git commit -m "chore(launcher): remove archived engines from menu and mappings

Remove deshaw/kepos/medallion/ornstein entries from:
- engine menu tuple (line ~250)
- _ENGINE_ICONS dict
- slug normalization dict
- 2 data_dir mappings
- display name dict
- run_dir prefix list

Archived engines no longer callable from launcher UI.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 11: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 5: Clean `launcher_support/` archived engine references

**Files:**
- Modify: `launcher_support/bootstrap.py` (lines 25-27, 44)
- Modify: `launcher_support/briefings.py` (deshaw briefing block — exact location varies)

- [ ] **Step 1: Edit `launcher_support/bootstrap.py` — remove aliases**

Localize estas 3 linhas (provavelmente em um dict `_ENGINE_ALIASES` ou similar):

```python
    "newton": "deshaw",
    "deshaw": "deshaw",
    "de_shaw": "deshaw",
```

Remove as 3.

- [ ] **Step 2: Edit `launcher_support/bootstrap.py` — remove from prefix list**

Localize (line ~44):
```python
    "citadel_", "thoth_", "bridgewater_", "newton_", "deshaw_",
```

Remove `"newton_"` e `"deshaw_"`. Verificar se kepos_/medallion_/ornstein_ estão no mesmo — remove.

- [ ] **Step 3: Find deshaw briefing in `launcher_support/briefings.py`**

```bash
grep -n "deshaw\|kepos\|medallion\|ornstein" launcher_support/briefings.py
```

Anote ranges — cada engine deve ter um block de briefing (dict entry).

- [ ] **Step 4: Edit `launcher_support/briefings.py` — remove briefings**

Remove os dict entries correspondentes aos 4 engines. Cada entry tem formato tipicamente:

```python
    "deshaw": {
        "source_files": ["engines/deshaw.py"],
        "main_function": ("engines/deshaw.py", "scan_pair"),
        ... (multi-line)
    },
```

Remove entries pra `deshaw`, `kepos`, `medallion`, `ornstein` (pode não ter todos, depende do file).

- [ ] **Step 5: Verify no residual refs**

```bash
grep -cE "deshaw|kepos|medallion|ornstein" launcher_support/bootstrap.py launcher_support/briefings.py
```

Expected: `0` em ambos.

- [ ] **Step 6: Smoke import launcher_support**

```bash
.venv/Scripts/python.exe -c "from launcher_support import bootstrap, briefings; print('OK')"
```

- [ ] **Step 7: Commit**

```bash
git add launcher_support/bootstrap.py launcher_support/briefings.py
git commit -m "chore(launcher_support): remove archived engine aliases and briefings

Remove from launcher_support/bootstrap.py:
- newton/deshaw/de_shaw alias dict entries
- newton_/deshaw_ prefix strings from run_dir matcher

Remove from launcher_support/briefings.py:
- briefing entries for deshaw, kepos, medallion, ornstein

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 6: Clean `tools/` archived engine references

**Files:**
- Modify: `tools/anti_overfit_grid.py` (4 blocks)
- Modify: `tools/audits/full_registry_audit.py` (4 entries)
- Modify: `tools/audits/engine_validation.py` (1 entry)
- Modify: `engines/aqr.py` (1 print line)

- [ ] **Step 1: Edit `tools/anti_overfit_grid.py` — remove deshaw EngineSpec**

Remove o bloco começando em line ~122:

```python
    "deshaw": EngineSpec(
        key="deshaw",
        ...
        script="engines/deshaw.py",
        data_dir="data/deshaw",
        checklist_path="docs/engines/deshaw/checklist.md",
        ...
    ),
```

(O bloco pode ter ~5-15 linhas. Remove o dict key-value inteiro.)

- [ ] **Step 2: Edit `tools/anti_overfit_grid.py` — remove kepos EngineSpec (line ~186)**

Mesmo pattern — remove dict entry inteira pra "kepos".

- [ ] **Step 3: Edit `tools/anti_overfit_grid.py` — remove medallion EngineSpec (line ~258)**

Idem, "medallion".

- [ ] **Step 4: Edit `tools/anti_overfit_grid.py` — remove config dict entries (line ~343-356)**

Localize dict com entries:
```python
    "deshaw": {
        ...
    },
    "kepos": {
        ...
    },
    "medallion": {
        ...
    },
```

Remove os 3 blocos.

- [ ] **Step 5: Edit `tools/audits/full_registry_audit.py` — remove 4 engine entries**

```bash
grep -n 'slug="deshaw"\|slug="kepos"\|slug="medallion"\|slug="ornstein"' tools/audits/full_registry_audit.py
```

Anote line numbers. Remove cada bloco `slug="deshaw"` com todo seu conteúdo (`command=`, `data_root=`, ... até a próxima entry).

- [ ] **Step 6: Edit `tools/audits/engine_validation.py` — remove deshaw entry (line ~54)**

Localize o bloco com `script="engines/deshaw.py"` — remove dict entry inteira.

- [ ] **Step 7: Edit `engines/aqr.py` — remove help print (line 144)**

Remove esta linha única:

```python
        print("    python -m engines.deshaw     # DE SHAW")
```

- [ ] **Step 8: Verify no residual refs in tools/**

```bash
grep -rcE "deshaw|kepos|medallion|ornstein" tools/ 2>&1 | grep -v ":0$" | head -10
```

Expected: vazio ou só `_archive` / docs (se houver).

- [ ] **Step 9: Smoke import tools**

```bash
.venv/Scripts/python.exe -c "import tools.anti_overfit_grid; print('OK')"
```

- [ ] **Step 10: Commit**

```bash
git add tools/anti_overfit_grid.py tools/audits/full_registry_audit.py tools/audits/engine_validation.py engines/aqr.py
git commit -m "chore(tools): remove archived engines from audit/grid infra

Remove deshaw/kepos/medallion/ornstein entries from:
- tools/anti_overfit_grid.py (EngineSpec + config dicts)
- tools/audits/full_registry_audit.py (registry entries)
- tools/audits/engine_validation.py (deshaw entry)
- engines/aqr.py (stale help print)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 11: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 7: Clean tests — delete + modify

**Files:**
- Delete: `tests/engines/test_kepos.py`, `tests/engines/test_ornstein.py`, `tests/engines/test_medallion.py`, `tests/contracts/test_deshaw_contracts.py`
- Modify: `tests/contracts/test_db_contracts.py` (remove 2 test cases), `tests/integration/test_engines_live_view.py` (substitute examples)

- [ ] **Step 1: Delete standalone test files**

```bash
rm tests/engines/test_kepos.py tests/engines/test_ornstein.py tests/engines/test_medallion.py tests/contracts/test_deshaw_contracts.py
```

Verify:
```bash
ls tests/engines/ tests/contracts/ 2>&1 | grep -E "kepos|ornstein|medallion|deshaw"
```

Expected: empty.

- [ ] **Step 2: Edit `tests/contracts/test_db_contracts.py` — remove newton→deshaw tests**

Localize e remove o test case em line ~80:

```python
        assert db._normalize_engine("newton") == "deshaw"
```

E em line ~100-101:

```python
        payload = {"run_id": "deshaw_2026-01-01_1000"}
        assert db._normalize_engine("", payload) == "deshaw"
```

Encontre o test function envolvente — provavelmente `def test_normalize_engine_newton_alias(...)` ou `def test_normalize_engine_from_run_id(...)`. Remove o test function inteiro se só testa esse comportamento.

- [ ] **Step 3: Edit `tests/integration/test_engines_live_view.py` — substitute experimental examples**

Line ~24-25:
```python
        assert "deshaw" not in LIVE_READY_SLUGS
        assert "kepos" not in LIVE_READY_SLUGS
```

Substitua pela verificação de dois engines que continuam experimental após cleanup. O único em `EXPERIMENTAL_SLUGS` que resta é `graham` (checar). Se só `graham` restou, o assert duplo pode virar:

```python
        assert "graham" not in LIVE_READY_SLUGS
```

E line ~118-120:
```python
            experimental_items=[("deshaw", {"display": "DE SHAW"})],
        ...
        assert selected == ("deshaw", "RESEARCH")
```

Substitua "deshaw" por "graham" (ou outro experimental que reste):

```python
            experimental_items=[("graham", {"display": "GRAHAM"})],
        ...
        assert selected == ("graham", "RESEARCH")
```

- [ ] **Step 4: Run full suite — expect 1,681 pass**

```bash
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q 2>&1 | tail -5
```

Expected: `1681 passed, 8 skipped` (1740 baseline − 59 deleted tests).

**Se houver failures**, diagnosticar antes de commit. Ajuste tests com refs residuais ou volte à task anterior.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "chore(tests): remove tests for archived engines

Delete:
- tests/engines/test_kepos.py (32 tests)
- tests/engines/test_ornstein.py (22 tests)
- tests/engines/test_medallion.py (5 tests)
- tests/contracts/test_deshaw_contracts.py (full file)

Modify:
- tests/contracts/test_db_contracts.py: remove newton->deshaw
  normalization test cases
- tests/integration/test_engines_live_view.py: substitute
  experimental examples from deshaw/kepos to graham

Baseline post-delete: 1681 passed (1740 - 59 deleted).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 8: Delete engine source files

**Files:**
- Delete: `engines/deshaw.py`, `engines/kepos.py`, `engines/medallion.py`, `engines/ornstein.py`

- [ ] **Step 1: Verify no remaining references across codebase**

```bash
grep -rln "from engines.deshaw\|from engines.kepos\|from engines.medallion\|from engines.ornstein\|import deshaw\|import kepos\|import medallion\|import ornstein" --include="*.py" --exclude-dir=.venv --exclude-dir=.git --exclude-dir=.worktrees --exclude-dir=_archive
```

Expected: empty (0 files). **Se houver match, pare** — volte à task de callsite cleanup e trate.

- [ ] **Step 2: Delete the 4 files**

```bash
rm engines/deshaw.py engines/kepos.py engines/medallion.py engines/ornstein.py
```

Verify:
```bash
ls engines/ | grep -E "deshaw|kepos|medallion|ornstein"
```

Expected: empty.

- [ ] **Step 3: Run full test suite**

```bash
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q 2>&1 | tail -5
```

Expected: `1681 passed` (same as task 7 — file delete não deve tirar tests).

- [ ] **Step 4: Smoke import critical modules**

```bash
.venv/Scripts/python.exe -c "import launcher; from engines import millennium, citadel, jump; print('all OK')"
```

Expected: `all OK`

- [ ] **Step 5: Commit**

```bash
git add -A engines/
git commit -m "chore(engines): delete archived engine source files

Delete 5,187 LOC total:
- engines/deshaw.py (1,539 LOC)
- engines/kepos.py (961 LOC)
- engines/medallion.py (998 LOC)
- engines/ornstein.py (1,689 LOC)

All callsites + tests already cleaned in prior commits. Backup
preserved in origin branches feat/claude-{deshaw,kepos,medallion}.
Git history retains full source.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 9: Delete `docs/engines/` subdirs for archived engines

**Files:**
- Delete: `docs/engines/deshaw/`, `docs/engines/kepos/`, `docs/engines/medallion/`, `docs/engines/ornstein_v2/`

- [ ] **Step 1: Verify dirs exist**

```bash
ls -d docs/engines/deshaw docs/engines/kepos docs/engines/medallion docs/engines/ornstein_v2 2>&1
```

- [ ] **Step 2: Delete dirs**

```bash
rm -rf docs/engines/deshaw docs/engines/kepos docs/engines/medallion docs/engines/ornstein_v2
```

- [ ] **Step 3: Verify docs/audits/ preserved (these are the justification — NEVER delete)**

```bash
ls docs/audits/ | grep -iE "deshaw|kepos|medallion|ornstein"
```

Expected: files listed (preservados).

- [ ] **Step 4: Commit**

```bash
git add -A docs/engines/
git commit -m "chore(docs): delete archived engine docs subdirs

Delete docs/engines/{deshaw,kepos,medallion,ornstein_v2}/
(params, grid, checklist — internal engine docs).

Audits in docs/audits/ preserved (archive justifications).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 10: Verify no orphan deps (no-op expected, document)

**Files:** none modified (verification + docs in commit message)

- [ ] **Step 1: Verify hmmlearn still used**

```bash
grep -rln "from hmmlearn\|import hmmlearn" --include="*.py" --exclude-dir=.venv --exclude-dir=.git --exclude-dir=.worktrees --exclude-dir=_archive
```

Expected: `core/chronos.py` and `launcher_support/briefings.py` (at minimum). **STAY** — dep is needed.

- [ ] **Step 2: Verify arch still used**

```bash
grep -rln "from arch\b\|import arch\b" --include="*.py" --exclude-dir=.venv --exclude-dir=.git --exclude-dir=.worktrees --exclude-dir=_archive
```

Expected: `core/chronos.py` and `launcher_support/briefings.py`. **STAY**.

- [ ] **Step 3: Verify statsmodels (not in pyproject, but check if any residual usage)**

```bash
grep -rln "from statsmodels\|import statsmodels" --include="*.py" --exclude-dir=.venv --exclude-dir=.git --exclude-dir=.worktrees --exclude-dir=_archive
```

Expected: empty (was only used by archived engines — confirmed during mapping).

- [ ] **Step 4: Document decision in a no-code commit (empty commit)**

```bash
git commit --allow-empty -m "chore(deps): verify no orphan deps post-archive (no-op)

Verified hmmlearn and arch remain used by core/chronos.py (WINTON
engine) and launcher_support/briefings.py. Neither is orphaned after
archived engine deletion. statsmodels was only referenced by archived
engines but was never in pyproject.toml — nothing to remove.

pyproject.toml [ml] extras unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 11: Ruff F401 autofix

**Files:** many (whatever ruff finds)

- [ ] **Step 1: Preview F401 violations**

```bash
.venv/Scripts/python.exe -m ruff check --select F401 --no-fix . 2>&1 | tail -20
```

Anote quantas violações (`N errors found`).

- [ ] **Step 2: Preview the diff ruff would apply**

```bash
.venv/Scripts/python.exe -m ruff check --select F401 --diff . 2>&1 | head -100
```

**INSPECT the diff**. Procure:
- Remoções de `from engines.X import Y` onde Y é usado via string/getattr (lazy/dynamic)
- Remoções de `from core.X import Y` críticos
- Re-exports em `__init__.py` (import sem uso = re-export intencional)

Se alguma remoção for suspeita, marque esse arquivo pra skip (adicionar `# noqa: F401` na linha do import antes de rodar fix).

- [ ] **Step 3: Apply autofix**

```bash
.venv/Scripts/python.exe -m ruff check --select F401 --fix . 2>&1 | tail -10
```

Expected: `N fixes applied` (same N from step 1 minus any manually noqa'd).

- [ ] **Step 4: Run full test suite**

```bash
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q 2>&1 | tail -5
```

Expected: `1681 passed` (same as task 7/8).

Se houver failures, é porque ruff removeu import usado via lazy/dynamic. Diagnosticar, re-adicionar o import com `# noqa: F401`, re-testar.

- [ ] **Step 5: Smoke launcher import**

```bash
.venv/Scripts/python.exe -c "import launcher; print('OK')"
```

- [ ] **Step 6: Verify 0 residuals**

```bash
.venv/Scripts/python.exe -m ruff check --select F401 --no-fix . 2>&1 | tail -5
```

Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore(imports): ruff F401 autofix — remove unused imports

Applied ruff check --select F401 --fix across codebase. Removes
unused imports left over from refactors and archived engines.

Verified no regressions (pytest 1681 passed). Lazy/dynamic imports
preserved via manual inspection of diff before fix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 8: Push**

```bash
git push origin feat/cleanup-phase-1
```

---

## Task 12: Final gates + merge back

**Files:** none modified (validation + git merge)

- [ ] **Step 1: Compute LOC delta**

```bash
git diff --shortstat chore/repo-cleanup..feat/cleanup-phase-1
```

Expected: something like `N files changed, X insertions(+), Y deletions(-)` where Y >= 5,500 (5,187 source + tests + docs).

- [ ] **Step 2: Count engines remaining**

```bash
.venv/Scripts/python.exe -c "from config.engines import ENGINES; print(f'engines remaining: {len(ENGINES)}'); print(sorted(ENGINES.keys()))"
```

Expected: `engines remaining: 12` (was 16), sorted list excluding deshaw/kepos/medallion/ornstein.

- [ ] **Step 3: Run FULL test suite (including the skipped Windows-fatal file if it's safe now)**

```bash
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q 2>&1 | tail -5
```

Expected: `1681 passed, 8 skipped`.

- [ ] **Step 4: VPS smoke — confirm 11 systemd services still active**

```bash
ssh -o ConnectTimeout=10 -o BatchMode=yes -i /c/Users/Joao/.ssh/id_ed25519 root@37.60.254.151 '
for u in citadel_paper@desk-a citadel_shadow@desk-a jump_paper@desk-a jump_shadow@desk-a renaissance_paper@desk-a renaissance_shadow@desk-a millennium_paper@desk-paper-a millennium_paper@desk-paper-b millennium_shadow@desk-shadow-a millennium_shadow@desk-shadow-b aurum_probe@desk-a; do
  s=$(systemctl is-active ${u}.service)
  printf "%-40s %s\n" "$u" "$s"
done
'
```

Expected: todos `active`. (Ainda rodam o código antigo local do VPS — só checando que nada externo afetou eles durante cleanup.)

- [ ] **Step 5: Measure venv size (observacional)**

```bash
du -sh .venv/
```

Anote. Como não removemos deps, não espera-se mudança significativa.

- [ ] **Step 6: Merge back to chore/repo-cleanup**

```bash
git checkout chore/repo-cleanup
git merge --no-ff feat/cleanup-phase-1 -m "Merge feat/cleanup-phase-1 into chore/repo-cleanup

Phase 1 of software optimization roadmap: Clear The Decks.

- Deleted 4 archived engines: deshaw, kepos, medallion, ornstein
  (5,187 LOC of engine source + 59 tests + docs subdirs)
- Cleaned all references in config, millennium.py, launcher,
  launcher_support, tools/
- Ran ruff F401 autofix for unused imports
- Verified deps (hmmlearn, arch) still used by WINTON — no removal

Metrics:
- LOC deleted: ~5,500
- Tests: 1,740 -> 1,681 pass (-59 deleted, 0 regressions)
- Engines in registry: 16 -> 12

Spec: docs/superpowers/specs/2026-04-23-cleanup-phase-1-design.md
Plan: docs/superpowers/plans/2026-04-23-cleanup-phase-1.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 7: Push merge commit**

```bash
git push origin chore/repo-cleanup
```

- [ ] **Step 8: Print final report**

```bash
echo "=== FASE 1 CLEAR THE DECKS — CONCLUÍDA ==="
echo "Branch: feat/cleanup-phase-1 merged into chore/repo-cleanup"
echo ""
echo "Metrics:"
git diff --shortstat chore/repo-cleanup~1..chore/repo-cleanup
echo ""
echo "Engines remaining:"
.venv/Scripts/python.exe -c "from config.engines import ENGINES; print('  ' + ', '.join(sorted(ENGINES.keys())))"
echo ""
echo "Test baseline: 1,681 passed (was 1,740 pre-phase)"
echo ""
echo "Ready for Fase 2: Performance & Dev Loop"
```

---

## Self-Review (executed)

**Spec coverage:**
- ✅ Engines delete (A): Tasks 2-9
- ✅ Ruff F401 (B): Task 11
- ✅ Orphan deps verify (C): Task 10 (no-op documented — hmmlearn/arch still used)
- ✅ Gates cumulativos: cada task tem step de pytest + verify
- ✅ Rollback via push-per-commit: cada task pushada separada

**Placeholder scan:** no TBDs, TODOs, "similar to". All commands exact, all paths concrete.

**Type consistency:** N/A (no new types defined — cleanup only).

**Risk coverage:**
- ✅ Risk 1 (millennium pod): Task 3 dedicated
- ✅ Risk 2 (deps órfãs): Task 10 verify (no-op by investigation)
- ✅ Risk 3 (ruff false-positive): Task 11 Step 2 diff preview + manual inspection
- ✅ Risk 4 (launcher menu): Task 4 dedicated
- ✅ Risk 5 (tests integração): Task 7 (test_db_contracts, test_engines_live_view)

---

## Execution options

Plan complete and saved to `docs/superpowers/plans/2026-04-23-cleanup-phase-1.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
