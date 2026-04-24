# BACKTEST Panel — Hierarchy Redesign (Engine → Run → Metrics)

**Data:** 2026-04-17
**Contexto:** launcher.py · crypto dashboard · aba BACKTEST (tecla 4)
**Status:** design aprovado — pronto pra plano de implementação

---

## 1. Problema

O painel BACKTEST atual lista ~70 runs de 9+ engines misturados numa única tabela
corrida à esquerda. A direita mostra as métricas do run selecionado. Pra
encontrar "o último run da CITADEL" o usuário precisa scanear a coluna ENGINE
visualmente e caçar por data. Ruim em densidade, ruim em hierarquia.

A filosofia AURUM pede navegação em camadas (iPod Classic · Bloomberg): primeiro
o que é (engine), depois qual manifestação (run), depois como se comporta
(métricas). O painel atual pula direto pra "lista gigante indiferenciada".

## 2. Solução — Hierarquia em 3 camadas

Reorganização puramente visual. Zero mudança em `core/`, `engines/`,
`config/params.py` ou qualquer lógica de trading/backtest/data collection.

### 2.1 Layout

```
┌──────────────────────────┬──────────────────────────────────────────────┐
│ [ ENGINES ]              │ [ DETAILS ]                                  │
│                          │ ┌─ METRICS (run ativo) ──────────────────┐   │
│ ● CITADEL       ✅   23  │ │ run_id · timestamp                     │   │
│   JUMP          ✅   18  │ │ [OPEN HTML] [METRICS] [DELETE]         │   │
│   RENAISSANCE   ⚠️   12  │ │ PERFORMANCE · TRADES · CONFIG          │   │
│   MILLENNIUM    ·    9   │ │   (mesmos blocos de hoje)              │   │
│   BRIDGEWATER   🔴   7   │ └────────────────────────────────────────┘   │
│   DE SHAW       🔴   6   │ ┌─ RUNS (da engine ativa) ───────────────┐   │
│   TWO SIGMA     ⚪   4   │ │ DATE            TF  DAYS RUN    TR WR… │   │
│   PHI           🆕   2   │ │ ●2026-04-17 14:45  15m 90  a1b2 120 52 │   │
│   JANE STREET   ⚪   1   │ │  2026-04-16 11:22  15m 90  c3d4 118 49 │   │
│                          │ │  2026-04-15 09:10  1h  30  e5f6  42 55 │   │
│                          │ └────────────────────────────────────────┘   │
└──────────────────────────┴──────────────────────────────────────────────┘
```

### 2.2 Regiões

- **Esquerda — ENGINES (~35% da largura):** lista vertical de engines. Cada
  linha: `●` (só na engine ativa; espaço em branco nas demais) · NOME
  INSTITUCIONAL · badge OOS · nº de runs. Só engines com ≥1 run aparecem.
  Ordenação: engine com run mais recente no topo.
- **Direita topo — METRICS (~55% da altura):** bloco idêntico ao
  `_dash_backtest_select` atual (header run_id + timestamp + botões OPEN HTML /
  METRICS / DELETE + blocos PERFORMANCE / TRADES / CONFIG). Zero mudança de
  conteúdo — só muda quem o preenche.
- **Direita baixo — RUNS (~45% da altura):** tabela só com runs da engine ativa.
  Mesmas colunas de `_BT_COLS` **menos** a coluna ENGINE (redundante quando a
  engine já foi selecionada à esquerda). Ordenação: mais recente primeiro.

### 2.3 Fluxo de interação

1. Abrir a aba → auto-seleciona a engine com run mais recente → auto-seleciona
   o run mais recente dela → métricas já carregadas ao abrir (zero cliques pra
   ver o estado atual do sistema).
2. Clicar noutra engine (esquerda) → a lista de runs embaixo troca → o run mais
   recente daquela engine é auto-selecionado → métricas em cima atualizam.
3. Clicar noutro run (direita baixo) → só as métricas em cima atualizam; lista
   da esquerda e lista de runs não mexem.

### 2.4 Badges OOS (status institucional)

Pulam direto do CLAUDE.md, sem cálculo em runtime:

| Engine        | Badge |
|---------------|-------|
| CITADEL       | ✅    |
| JUMP          | ✅    |
| RENAISSANCE   | ⚠️    |
| BRIDGEWATER   | 🔴    |
| DE SHAW       | 🔴    |
| KEPOS         | 🔴    |
| MEDALLION     | 🔴    |
| MILLENNIUM    | ·  (meta) |
| WINTON        | ·  (meta) |
| PHI           | 🆕    |
| TWO SIGMA     | ⚪    |
| AQR           | ⚪    |
| JANE STREET   | ⚪ (arb) |
| GRAHAM        | 🗄️ (arquivado) |

Dict constante no topo do método (ou reaproveita `_ENGINE_NAMES` existente,
adicionando um `_ENGINE_BADGES` paralelo).

### 2.5 Estado inicial (edge cases)

- **Zero runs no sistema inteiro:** esquerda mostra "— no engines found —",
  direita mostra placeholder "← run a backtest first".
- **Engine sem runs (hipotético, ex.: engine recém-adicionada):** não aparece
  na lista da esquerda (ordenação por run mais recente naturalmente filtra).
- **Run com `summary.json` ausente/corrompido:** comportamento atual de
  `_dash_backtest_select` preservado (mostra "✗ summary.json missing").

### 2.6 Preservação de comportamento existente

- Botão **OPEN HTML**: abre `report.html` do run ativo — inalterado.
- Botão **METRICS**: chama `_dash_backtest_metrics(run_id)` → abre o dashboard
  completo de métricas em tela cheia — inalterado.
- Botão **DELETE**: chama `_dash_backtest_delete(run_id)` — inalterado.
  Depois de deletar, re-renderiza a lista de engines e a lista de runs da
  engine ativa (se a engine ainda tiver runs; senão auto-seleciona a próxima).
- Coleta de runs: reaproveita `_bt_collect_runs()` sem mudança.
- Cache mtime (`_bt_json_cache`): preservado.
- Timestamp format: `_bt_fmt_timestamp()` preservado.
- Pre-L6 warning badge (`⚠` em runs antigos): preservado na tabela de runs.

## 3. Arquivos afetados

Um único arquivo:

- `launcher.py` — métodos:
  - `_dash_build_backtest_tab` (linha ~10777): reestrutura o split left/right.
  - `_dash_backtest_render` (linha ~11145): renomeia/divide em dois
    renderers — `_dash_backtest_render_engines` (esquerda) e
    `_dash_backtest_render_runs` (direita baixo, recebe `engine` como arg).
  - `_dash_backtest_select` (linha ~11296): inalterado — continua
    populando `("bt_detail",)` com as métricas.
  - Novo método: `_dash_backtest_select_engine(engine: str)` — troca a engine
    ativa, repinta a lista de runs, auto-seleciona o run mais recente.

Widgets novos no `_dash_widgets`:
- `("bt_engines",)` — frame da lista de engines (esquerda).
- `("bt_runs",)` — frame da lista de runs filtrada (direita baixo).
- `("bt_active_engine",)` — string guardando a engine selecionada atual.

Widget existente mantido:
- `("bt_detail",)` — continua sendo o frame das métricas.
- `("bt_count",)` — passa a mostrar "N engines · M runs" em vez de só "M runs".

Widgets descontinuados:
- `("bt_list",)` e `("bt_canvas",)` — não são mais necessários (a lista corrida
  da esquerda some). Os callbacks de mousewheel viram escopados pra
  `bt_runs` (canvas da direita baixo).

## 4. Não-objetivos (fora de escopo)

- Qualquer mudança em engines, data fetch, backtest logic, params.
- Nova coleta de métricas, nova estatística, novo indicador.
- Persistência de preferência (qual engine foi a última selecionada entre
  sessões) — stateless por enquanto; pode virar backlog.
- Filtro por timeframe, basket, data range. A tabela de runs continua crua.
- Comparação lado-a-lado de runs. Pro futuro.
- Keyboard shortcuts pra navegar entre engines/runs. Mouse-first.

## 5. Testing

O painel é UI Tkinter, não há suite headless pra Tk no repo. Validação manual:

1. `python launcher.py` → entra no crypto dashboard → tecla `4` → aba BACKTEST.
2. Confere que a esquerda lista as engines com badges corretos.
3. Clica em cada engine → confere que a lista de runs troca e as métricas em
   cima atualizam.
4. Clica num run diferente da mesma engine → confere que só as métricas
   trocam.
5. Clica DELETE num run → confere que some da lista e a próxima métrica carrega
   (ou placeholder se era o último).
6. Clica OPEN HTML e METRICS → confere que abrem normal.
7. Smoke test: `python smoke_test.py --quiet` (valida que nada no resto do
   launcher quebrou — import, startup, construção de widgets).

## 6. Filosofia preservada

- **Polaridade:** engine ↔ run, navegação binária, hierárquica.
- **Correspondência:** fractal — cada engine tem seus runs, cada run tem suas
  métricas; o painel reflete o aninhamento da realidade.
- **Densidade Bloomberg:** sem whitespace gratuito, fontes monospace, cores
  AMBER/GREEN/RED/DIM do tema.
- **iPod Classic:** hierarquia em camadas, foco do olho dirigido pelo dot `●`.
- **Zero dependência externa:** só Tkinter + stdlib, como o resto do painel.
