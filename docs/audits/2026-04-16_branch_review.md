# Branch Review — feat/phi-engine — 2026-04-16

## Veredicto: NEEDS WORK

1 critical, 2 high, 1 nitpick. Não mergear sem corrigir o crítico.

---

## Changes scope

**Modificados:**
- `config/engines.py` — adiciona entrada `"medallion"` no registry `ENGINES` e `PROC_ENGINES`
- `core/engine_picker.py` — adiciona `"medallion": 76` (prioridade) e type `"BACKTEST"`
- `core/run_manager.py` — adiciona `"MEDALLION"` no mapa `_ENG_TO_SLUG` e `_PARENT_TO_SLUG` dentro de `append_to_index`
- `engines/kepos.py` — pequenos ajustes (não alteraram lógica protegida, verificado)
- `launcher.py` — adiciona `BRIEFINGS["MEDALLION"]` e entrada na lista de backtest engines
- `aurum_cli.py` — adiciona entrada `"medallion"` no dict de strategies + rota `cli_args` correto
- `tools/prefetch.py` — refatoração standalone sem dependência do medallion

**Novos:**
- `engines/medallion.py` — engine MEDALLION: mean-reversion Berlekamp-Laufer, 7-signal ensemble, Kelly sizing
- `tools/medallion_finalize.py` — finalizer: normaliza trades, gera overfit audit, MC, walk-forward, patcha index.json
- `tools/medallion_grid.py` — grid search em 2 fases; reutiliza features pré-computadas para eficiência

---

## Findings

### 🔴 Critical

**`tools/medallion_grid.py:310-313` — dead code com crash latente**
Confiança: **88**

```python
final_params = replace(base_params, **{
    k: best_overall[k] for k in best_overall
    if k in {f.name for f in med.dataclasses.fields(med.MedallionParams)}
}) if hasattr(med, "dataclasses") else base_params
```

`med.dataclasses` nunca existe como atributo do módulo `engines/medallion.py`
(o módulo importa `dataclasses` internamente mas não reexporta). O `hasattr`
é `False` sempre, então o bloco é dead code. Se alguém remover o guard ou
se `medallion.py` um dia exportar `dataclasses` acidentalmente, explode com
`AttributeError`. Pior: linhas 315-317 logo abaixo **sempre sobrescrevem
`final_params`**, tornando 310-313 completamente inúteis.

**Fix:** remover linhas 310-313 inteiras.

---

### 🟠 High

**`tools/medallion_finalize.py:55` — hardcode do path do index, viola SSOT**
Confiança: **85**

```python
INDEX_PATH = ROOT / "data" / "index.json"
```

O path correto está em `config/paths.py` como `RUN_INDEX_PATH`. Todos os
outros módulos usam `from config.paths import RUN_INDEX_PATH`. Se o path
mudar em `config/paths.py`, o finalizer diverge silenciosamente.

**Fix:**
```python
from config.paths import RUN_INDEX_PATH
INDEX_PATH = RUN_INDEX_PATH
```

---

**`tools/medallion_finalize.py:248` — `len(wf)` sem defensiva**
Confiança: **82**

```python
return {
    ...
    "wf_windows": len(wf),
}
```

`wf` vem de `walk_forward(trades)` (linha 175) que retorna `[]` quando há
trades insuficientes. `len([])` é 0 — tecnicamente não crasha. Mas o bloco
200-211 usa `if wf:`. Se `walk_forward` passar a retornar `None` numa versão
futura, explode.

**Fix preventivo:** `"wf_windows": len(wf) if wf else 0`

---

### 🟢 Nitpick

**`tools/medallion_grid.py:266-267` — `_` descarta vetos na fase 2**
Confiança: **80**

```python
trades, _ = _scan_with_params(enriched, params)
```

Fase 1 (linha 213) captura vetos; fase 2 descarta silenciosamente.
Não impacta resultado, mas dificulta debug de configs fase-2 que gerem 0 trades.

---

## Core-of-trading compliance

**Verificação explícita: PASS.**

- `core/indicators.py` — apenas consumido via `indicators(df)`, nunca modificado
- `core/signals.py` — não importado por nenhum arquivo novo
- `core/portfolio.py` — não importado. MEDALLION usa Kelly local
  (`medallion_kelly_fraction`), documentado no docstring como design
  intencional. **Não é bypass — é engine standalone que ainda não passou
  pelo overfit 6/6**
- `config/params.py` — apenas lido via `from config.params import *`.
  Nenhum valor alterado. Custo C1+C2 aplicado idêntico ao KEPOS
  (verificado linha a linha em `_pnl_with_costs`)

Modelo de custos em `engines/medallion.py:664-675` é idêntico ao KEPOS
(`engines/kepos.py:496-507`). Consistente com convenção.

---

## Integration check

**`launcher.py`:** `BRIEFINGS["MEDALLION"]` presente, engine listada em
backtest panel (linha 298). Wiring correto.

**`aurum_cli.py`:**
- Entrada `"medallion"` no dict de strategies (linha 239) com
  `"methods": ["backtest"]`. Correto.
- Linha 299: `return "medallion","engines/medallion.py",["--days",days,"--no-menu"]`
  — flag `--no-menu` declarada no argparser mas nunca usada. Consistente
  com KEPOS/GRAHAM. Não é bug.
- Linha 409: `if ek in ("kepos", "graham", "medallion")` — spawn via
  `cli_args` ao invés de `stdin_lines`. Correto para engines argparse-based.

**`config/engines.py`:** entrada em `ENGINES` e `PROC_ENGINES`. Coerente.

**`core/run_manager.py`:** `"MEDALLION"` adicionado nos mapas de slug.

---

## Recomendação

**Keep working / split into smaller commits.**

Arquivos novos estão em boa forma para engine experimental — lógica
defensiva, custo model correto, Kelly documentado, integração verificada.
O crítico e os HIGH são fixes de 2 linhas cada. Corrigir antes de commitar.

Engine ainda não tem overfit 6/6 e não está em `FROZEN_ENGINES` — correto
e documentado.

---

## Top 3 ações

1. `tools/medallion_grid.py` — remover linhas 310-313 (dead code
   `med.dataclasses`)
2. `tools/medallion_finalize.py:55` — substituir hardcode por
   `from config.paths import RUN_INDEX_PATH`
3. `tools/medallion_finalize.py:248` — tornar `len(wf)` defensivo contra
   None futuro
