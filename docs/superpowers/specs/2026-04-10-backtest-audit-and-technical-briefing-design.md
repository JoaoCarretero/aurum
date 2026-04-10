# Backtest Physics Audit + Technical Briefing Menu — Design

**Data:** 2026-04-10
**Status:** draft, aguardando aprovação do usuário
**Escopo:** audit de correção matemática/lógica do motor de backtest + refactor do menu de explicação de estratégias no launcher.

---

## 1. Motivação

O menu atual de explicação das 7 estratégias (`launcher.py:_brief()`) mostra 4 campos narrativos
(`philosophy`, `logic`, `edge`, `risk`) hardcoded em `BRIEFINGS` (`launcher.py:145-249`).
Dois problemas:

1. **Conteúdo baixa densidade**: o briefing não revela o que o código realmente faz — é
   descrição de marketing, não especificação. Antes de rodar R$ de verdade, o usuário não
   consegue ver as fórmulas, parâmetros efetivos, ou invariantes que a estratégia assume.
2. **Audit nunca foi feito**: o motor de backtest (`engines/backtest.py`) e os indicadores
   (`core/indicators.py`, `core/signals.py`) podem ter bugs de "lei física" do backtest
   (look-ahead bias, fees mal aplicados, funding incorreto, position sizing sem cap de
   capital). Nada foi formalmente verificado.

Este spec une os dois trabalhos num ciclo único: o audit extrai conhecimento estruturado
(fórmulas, params, invariantes) que vira o conteúdo do novo briefing técnico — então o
trabalho de entender o código rende dois artefatos ao mesmo tempo.

---

## 2. Escopo

**Incluído:**

- Audit de correção (`docs/audits/backtest-physics-2026-04-10.md`) cobrindo:
    - Motor central: `engines/backtest.py`, `core/signals.py`, `core/indicators.py`
    - 7 estratégias: CITADEL, JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA, JANE STREET
- Refactor de `launcher.py:_brief()` pra renderizar 4 blocos técnicos estruturados.
- Novo dict `BRIEFINGS_V2` em `launcher.py` substituindo `BRIEFINGS`.
- Nova classe `CodeViewer` em `launcher.py` (Tk Toplevel modal com syntax highlight).
- Backlog de bugs encontrados (`docs/audits/backtest-fixes-backlog.md`).

**Excluído (deliberadamente):**

- **Aplicação de fixes** pros bugs encontrados. O audit documenta; os fixes vão pra um
  spec separado depois, com o backlog como input.
- Alterações em `core/`, `engines/` fora da leitura pro audit.
- Testes automatizados do launcher (é Tk desktop, validação é manual).
- Qualquer mudança no fluxo pós-briefing (`_config_backtest`, `_config_live`, `_exec`).
- Refactor de `BRIEFINGS` pra outros lugares onde possa estar usado (será verificado no
  plan).

---

## 3. Arquitetura

### 3.1 Forma geral do trabalho

Iterativo por estratégia, CITADEL primeiro como piloto. Cada iteração produz:

```
[1. AUDIT]  → lê arquivos da estratégia → aplica checklist L1-L12 →
                  append ao docs/audits/backtest-physics-2026-04-10.md

[2. EXTRAIR] → do audit recém-escrito, destilar pseudo-código, params,
                  fórmulas, invariantes → entrada em BRIEFINGS_V2 no launcher.py

[3. BACKLOG] → bugs não-PASS → append ao docs/audits/backtest-fixes-backlog.md
```

**Ordem:** CITADEL → JUMP → BRIDGEWATER → DE SHAW → MILLENNIUM → TWO SIGMA → JANE STREET.

CITADEL primeiro porque ela usa todo o motor central (`backtest.py` + `core/signals.py` +
`core/indicators.py`), então o audit dela gera de brinde a cobertura do core. Após a
primeira iteração, o usuário valida o formato visual antes de replicar nas outras 6.

### 3.2 Componentes novos no `launcher.py`

**`BRIEFINGS_V2` — dict** substituindo `BRIEFINGS`. Schema por estratégia:

| Campo | Tipo | Descrição |
|---|---|---|
| `source_files` | `list[str]` | Paths (relativos ao repo) dos arquivos relevantes, ordem de relevância. |
| `main_function` | `tuple[str, str]` | `(arquivo, nome_função)` — ponto de entrada a destacar. |
| `one_liner` | `str` | Headline técnica de uma linha (substitui `edge`). |
| `pseudocode` | `str` multi-linha | Python-like legível (não precisa executar). |
| `params` | `list[dict]` | Cada dict tem as chaves: `name`, `default`, `range`, `unit`, `effect`. |
| `formulas` | `list[str]` | Notação Unicode (·, ², √, Σ, α). Uma por linha. |
| `invariants` | `list[str]` | Pré-condições e assunções. Bullet list. |

**Exemplo (CITADEL):**

```python
"CITADEL": {
    "source_files": ["engines/backtest.py", "core/signals.py", "core/indicators.py"],
    "main_function": ("engines/backtest.py", "scan_symbol"),
    "one_liner": "Trend-following fractal multi-timeframe com omega score e modo CHOP.",
    "pseudocode": """\
for idx in range(min_idx, len(df) - MAX_HOLD - 2):
    regime = detect_regime(df, idx)
    if regime == "transition": continue
    direction = decide_direction(df, idx, regime)
    if direction is None: continue
    entry, stop, target = calc_levels(df, idx, direction)
    if not portfolio_allows(open_positions, symbol): continue
    size = kelly_sized(capital, entry, stop, KELLY_FRAC)
    trade = label_trade(df, entry_idx=idx+1, entry, stop, target, size)
    apply_fees_and_funding(trade)
""",
    "params": [
        {"name": "MAX_HOLD",     "default": 40,    "range": "20-100",    "unit": "bars",  "effect": "trade timeout"},
        {"name": "KELLY_FRAC",   "default": 0.25,  "range": "0.1-0.5",   "unit": "—",     "effect": "fração do Kelly ótimo no sizing"},
        {"name": "ATR_MIN",      "default": 0.005, "range": "0.002-0.02","unit": "ratio", "effect": "vol mínima pra operar"},
        {"name": "OMEGA_THRESH", "default": 0.65,  "range": "0.5-0.85",  "unit": "—",     "effect": "score mínimo pra aceitar sinal"},
    ],
    "formulas": [
        "omega = w_rsi·rsi_score + w_ema·ema_align + w_vol·vol_ratio + w_struct·struct_score",
        "RSI = 100 − 100/(1 + RS),  RS = EMA(gain,14)/EMA(loss,14)",
        "ATR = EMA(TR, 14),  TR = max(H−L, |H−Cₚ|, |L−Cₚ|)",
        "kelly_size = (p·W − q·L) / W,  W = |entry−target|, L = |entry−stop|",
        "PnL_net = qty·(exit−entry)·sign − fee_in − fee_out − Σ funding_k − slippage",
    ],
    "invariants": [
        "Requer ≥ 200 bars pré-sinal (EMA200 baseline)",
        "Entrada executa em open[idx+1] — nunca no mesmo bar do sinal",
        "Stop/target são price absolutos, não percentuais",
        "Assume ausência de gaps > 1 ATR (não tratado)",
        "Funding aplicado a cada 8h",
        "Não opera se portfolio_correlation(symbol, open_positions) > 0.7",
    ],
}
```

Valores exatos dos params, fórmulas e invariantes vêm do audit — o exemplo acima é
ilustrativo baseado no skim inicial.

**`_brief()` refatorado** — mesma assinatura `(name, script, parent_menu)`. Fluxo:

```python
def _brief(self, name, script, parent_menu):
    data = BRIEFINGS_V2[name]
    win = self._new_panel(name, parent_menu)
    self._render_header(win, name, data["one_liner"])
    self._render_pseudocode(win, data["pseudocode"])
    self._render_params_table(win, data["params"])
    self._render_formulas(win, data["formulas"])
    self._render_invariants(win, data["invariants"])
    self._render_action_buttons(win, data, script, parent_menu)
```

Cada helper `_render_*` é independente, <25 linhas, testável visualmente.

**Layout visual** (cima → baixo):

```
┌─────────────────────────────────────────────────────────┐
│  CITADEL                                          [ X ] │  ← header
│  Trend-following fractal multi-timeframe com omega...   │     (nome + one_liner)
├─────────────────────────────────────────────────────────┤
│ PSEUDOCODE                                              │  ← mono font,
│ ┌─────────────────────────────────────────────────────┐ │     fundo escuro,
│ │ for idx in range(min_idx, len(df) - MAX_HOLD - 2):  │ │     bloco destacado
│ │     regime = detect_regime(df, idx)                 │ │
│ │     ...                                             │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ PARAMETERS                                              │  ← ttk.Treeview
│ ┌──────────────┬────────┬──────────┬──────┬─────────┐   │     com 5 colunas
│ │ name         │ default│ range    │ unit │ effect  │   │
│ ├──────────────┼────────┼──────────┼──────┼─────────┤   │
│ │ MAX_HOLD     │ 40     │ 20-100   │ bars │ trade…  │   │
│ └──────────────┴────────┴──────────┴──────┴─────────┘   │
│                                                         │
│ FORMULAS                                                │  ← mono, uma
│   omega = w_rsi·rsi_score + w_ema·ema_align + …         │     por linha
│                                                         │
│ INVARIANTS                                              │  ← bullet list
│   • Requer ≥ 200 bars pré-sinal                         │
│   • Entrada executa em open[idx+1]                      │
├─────────────────────────────────────────────────────────┤
│      [ VER CÓDIGO ]         [ CONFIGURAR BACKTEST ]     │  ← ou CONFIGURAR LIVE
└─────────────────────────────────────────────────────────┘
```

**`CodeViewer` — nova classe** (`launcher.py`, depois de `_brief`):

```python
class CodeViewer(tk.Toplevel):
    """Read-only syntax-highlighted viewer for strategy source files.

    Modal. Opens with ttk.Notebook, one tab per source file.
    First tab scrolled to main_function. ESC to close.
    """

    KEYWORDS = frozenset({
        "def", "class", "for", "if", "elif", "else", "return",
        "import", "from", "while", "in", "not", "and", "or",
        "True", "False", "None", "try", "except", "with", "as",
        "lambda", "yield", "raise", "pass", "break", "continue",
    })

    def __init__(self, parent, source_files: list[str],
                 main_function: tuple[str, str]):
        super().__init__(parent)
        self.title(f"source — {main_function[1]}")
        self.geometry("1100x750")
        self.transient(parent)
        self.grab_set()
        self.bind("<Escape>", lambda e: self.destroy())
        self._build_ui(source_files, main_function)

    def _build_ui(self, files, main_fn):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        for path in files:
            frame = ttk.Frame(nb)
            txt = tk.Text(frame, wrap="none", font=("Consolas", 10),
                          bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4")
            sb_y = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
            sb_x = ttk.Scrollbar(frame, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
            content = Path(path).read_text(encoding="utf-8")
            txt.insert("1.0", content)
            self._highlight(txt, content)
            txt.config(state="disabled")
            sb_y.pack(side="right", fill="y")
            sb_x.pack(side="bottom", fill="x")
            txt.pack(side="left", fill="both", expand=True)
            nb.add(frame, text=Path(path).name)
            if path == main_fn[0]:
                self._scroll_to_function(txt, content, main_fn[1])
                nb.select(frame)

    def _highlight(self, text_widget, content):
        """Regex-based 5-pass highlight. Not AST. Not perfect. Good enough."""
        # pass 1: comments (grey)     — r"#.*?$"
        # pass 2: strings (green)     — r'(".*?"|\'.*?\')' (naive, ok)
        # pass 3: keywords (blue)     — r"\b(def|class|...)\b"
        # pass 4: numbers (orange)    — r"\b\d+\.?\d*\b"
        # pass 5: def/class names (yellow) — r"(?:def|class)\s+(\w+)"
        ...

    def _scroll_to_function(self, text_widget, content, fn_name):
        idx = content.find(f"def {fn_name}")
        if idx < 0:
            return
        line = content.count("\n", 0, idx) + 1
        text_widget.see(f"{line}.0")
```

**Constraints finais do `CodeViewer`:**

- Read-only estrito (`state="disabled"` após inserção).
- Modal (`transient` + `grab_set`).
- ESC fecha.
- Um tab por arquivo (`ttk.Notebook`), primeiro tab = arquivo principal já scrollado.
- Highlight regex-based, 5 categorias. Imperfeito é aceitável — é viewer, não IDE.
- Font: `("Consolas", 10)` fixo (Windows-only por enquanto; projeto é Windows).
- Tema escuro hardcoded (`bg="#1e1e1e"`).

**Nota sobre "inline no launcher":** o usuário pediu "painel inline" em oposição a
abrir editor externo (`os.startfile`). `tk.Toplevel` é uma janela filha **do mesmo
processo Python do launcher** — não é um editor externo. A alternativa de expandir o
próprio painel do `_brief` pra comportar também um scroll de 300+ linhas piora a leitura
do briefing e da tabela de params. Trade-off aceito: abre janela filha (não popup
externo), tudo continua dentro do app.

### 3.3 Data flow do audit → conteúdo do menu

```
       ┌───────────────────┐
       │  arquivo .py da   │
       │    estratégia     │
       └─────────┬─────────┘
                 │
                 │ leitura manual + checklist L1-L12
                 ▼
       ┌───────────────────┐
       │ findings raw:     │
       │ • PASS/SMELL/FAIL │
       │ • severidade      │
       │ • fix recomendado │
       └─────────┬─────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌───────────────┐  ┌───────────────┐
│ audit doc     │  │ extração      │
│ (completo)    │  │ estruturada   │
└───────────────┘  └──────┬────────┘
                          │
                          ▼
                ┌───────────────────┐
                │ BRIEFINGS_V2      │
                │ • pseudocode      │
                │ • params          │
                │ • formulas        │
                │ • invariants      │
                └───────────────────┘
```

---

## 4. Audit: checklist e formato

### 4.1 Checklist de "lei física" (L1-L12)

Aplicada a cada estratégia. Cada check produz status
(`✓ PASS` | `⚠️ SMELL` | `✗ FAIL` | `n/a`) e, se não for PASS, 3 campos: severidade, repro, fix
recomendado.

| # | Invariante | Como verifico | Severidade se falhar |
|---|---|---|---|
| L1 | Sem look-ahead: decisão em `idx` não usa dado de `idx+k` | grep `shift(-`, `.iloc[i+`, `.iloc[idx+`; `fillna(True)` retroativo | CRÍTICO |
| L2 | Delay de execução: ordem em `idx` preenche em `open[idx+1]` | ler `label_trade()` callers; confirmar `entry_idx=idx+1` | CRÍTICO |
| L3 | Fees entrada+saída subtraídas do PnL | rastrear `pnl` até o return; ver `fee_in`/`fee_out` | ALTO |
| L4 | Slippage aplicado (preço ≠ open/close puro) | procurar `* (1 ± slippage)` ou equivalente | ALTO |
| L5 | Funding rate contabilizado por período | ler bloco funding; respeito ao sinal (long paga se funding>0) | ALTO |
| L6 | Position sizing ≤ capital × max_leverage (somado) | checar `sum(open_notionals)` antes de abrir | ALTO |
| L7 | Liquidação simulada | procurar bloco liquidation em `backtest.py` | MÉDIO |
| L8 | Indicadores causais (sem shift negativo) | ler `core/indicators.py` inteiro | CRÍTICO |
| L9 | NaN do warm-up não dispara trade | loop começa em `min_idx ≥ N_warmup` | MÉDIO |
| L10 | Timeframe alignment sem ffill look-ahead | `merge_asof`/`reindex(method="ffill")` ANTES do ponto de decisão | ALTO |
| L11 | Stop/target geometricamente coerentes | sinais corretos pra long/short em `calc_levels` | ALTO |
| L12 | Universo de símbolos sem survivorship bias | `symbols` dinâmico vs estático | INFO |

### 4.2 Formato do audit doc

`docs/audits/backtest-physics-2026-04-10.md`:

```markdown
# Backtest Physics Audit — 2026-04-10

## Escopo
- Motor: engines/backtest.py, core/signals.py, core/indicators.py
- Estratégias: CITADEL, JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA, JANE STREET
- Checklist: L1-L12 (ver design doc 2026-04-10-backtest-audit-and-technical-briefing-design.md §4.1)

## Sumário executivo
| Estratégia   | PASS | SMELL | FAIL | n/a |
|--------------|------|-------|------|-----|
| CITADEL      | ...  | ...   | ...  | ... |
| ...          |      |       |      |     |

## CITADEL

### L1 — Sem look-ahead: ✓ PASS
Entry em open[idx+1] (backtest.py:262); indicadores usam shift(+k) causal.

### L8 — Indicadores causais: ⚠️ SMELL
`core/indicators.py:51` — `vol_escalation = hot & calm.shift(REGIME_TRANS_WINDOW).fillna(True)`
O `fillna(True)` marca primeiros 20 bars como transição, sem sinal real.
- **Severidade:** MÉDIO
- **Repro:** rodar CITADEL com dataset de 250 bars exatos; primeiros trades rejeitados por regime transition.
- **Fix recomendado:** `fillna(False)`, ou aumentar `min_idx` pra `REGIME_TRANS_WINDOW + 200`.

### L6 — ...
```

### 4.3 Backlog de fixes

`docs/audits/backtest-fixes-backlog.md`:

```markdown
# Backtest Fixes Backlog — gerado em 2026-04-10

Só items não-PASS do audit. Ordem: CRÍTICO → ALTO → MÉDIO → BAIXO → INFO.

## CRÍTICO
(vazio ou lista)

## ALTO
- **CITADEL / L6** — position sizing sem cap total (backtest.py:270-276)
  ...

## MÉDIO
- **CITADEL / L8** — fillna(True) em regime transition (indicators.py:51)
  ...
```

É o input do próximo spec (fixes). Neste spec não aplica nada.

---

## 5. Critério de aceite

### 5.1 Audit

- `docs/audits/backtest-physics-2026-04-10.md` existe, cobre as 7 estratégias.
- Cada estratégia tem os 12 checks L1-L12 resolvidos (PASS / SMELL / FAIL / n/a).
- Nenhum check deixado como "TODO" ou "em análise".
- `docs/audits/backtest-fixes-backlog.md` é consistente: todos os SMELL/FAIL do audit
  aparecem no backlog com a mesma severidade.
- Sumário executivo no topo do audit doc está preenchido.

### 5.2 Menu

- `BRIEFINGS_V2` tem entrada pras 7 estratégias (CITADEL, JUMP, BRIDGEWATER, DE SHAW,
  MILLENNIUM, TWO SIGMA, JANE STREET).
- Cada entrada tem os 7 campos do schema (`source_files`, `main_function`, `one_liner`,
  `pseudocode`, `params`, `formulas`, `invariants`).
- `_brief()` renderiza os 4 blocos em ordem: pseudocode → params → formulas → invariants.
- Botão "VER CÓDIGO" presente e funcional.
- `CodeViewer` abre modal com todos os `source_files` como tabs, primeiro tab = arquivo
  principal scrollado até `main_function`.
- Highlight visível pras 5 categorias (keyword/string/comment/number/def-name).
- `BRIEFINGS` antigo foi removido do arquivo.
- `python -c "import launcher"` passa sem erro.

### 5.3 Smoke test manual (obrigatório antes de declarar feito)

Rodar `python launcher.py` no worktree e verificar, pra CADA uma das 7 estratégias:

1. Menu estratégias → clicar estratégia → briefing abre
2. Todos 4 blocos presentes e renderizados
3. Params table tem 5 colunas com dados
4. Fórmulas mostram Unicode correto
5. Invariantes como bullet list
6. Clicar "VER CÓDIGO" → viewer abre
7. Primeiro tab = arquivo principal, scrollado até a função principal
8. Tabs adicionais pros outros `source_files`
9. Highlight visível
10. ESC fecha o viewer
11. Clicar "CONFIGURAR BACKTEST" do briefing → fluxo normal segue funcionando

Se qualquer uma das 11 falhar, não está pronto.

### 5.4 Regression gate

- `python -c "import launcher"` deve passar antes de cada commit.
- Nenhum outro arquivo fora de `launcher.py`, `docs/audits/*`, `docs/superpowers/specs/*`
  é modificado neste spec.

---

## 6. Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Audit de uma estratégia revela bug crítico que bloqueia o próprio menu (ex: estratégia referencia módulo inexistente) | Baixa | Marca como FAIL, deixa entrada `BRIEFINGS_V2` com `pseudocode="# strategy is broken, see audit"`, segue |
| Regex highlight quebra em casos patológicos (strings com `#` dentro, f-strings aninhadas) | Média | Aceito. É viewer, não compilador. Se ficar inutilizável, cai pra sem highlight (plaintext) |
| `ttk.Treeview` fica feio com 5 colunas no tamanho atual do painel | Média | Ajuste de width das colunas no plan. Último recurso: tabela ASCII num `tk.Text` |
| Unicode nas fórmulas não renderiza em fonte padrão | Baixa | Testei: Consolas no Windows suporta ·, ², √, Σ, α, β, etc. Se falhar, fallback ASCII (`*`, `^2`, `sqrt`, `sum`) |
| O audit de TWO SIGMA é mais difícil (ML meta-ensemble, lógica em training/inference separada) | Alta | Pode virar entrada com `pseudocode` mais alto nível ("treina LightGBM por regime, escolhe engine com maior EV") e `formulas` com loss function do modelo. Aceitável |
| `BRIEFINGS` é usado em outro lugar além de `_brief()` | Média | O plan começa com grep por `BRIEFINGS` antes de remover. Se for usado, faz alias temporário |

---

## 7. Fora de escopo (para referência futura)

- **Aplicar os fixes do backlog**: próximo spec.
- **Testes automatizados do launcher Tk**: não há infra de teste de UI; manual é o caminho.
- **Tema customizável** no `CodeViewer`: dark hardcoded por enquanto.
- **Editor real** (code folding, busca, go-to-definition): é viewer, não IDE.
- **Suporte Linux/Mac**: projeto é Windows-only, fonte Consolas é assumida.
- **Exportar briefing pra PDF**: não pedido.
- **Comparar estratégias lado a lado**: interessante mas fora de escopo.

---

## 8. Transição pra implementação

Após aprovação deste spec pelo usuário, invocar `superpowers:writing-plans` pra gerar o
implementation plan detalhado. O plan vai quebrar em tasks:

1. Grep por uses de `BRIEFINGS` fora de `_brief()` (pre-flight check)
2. Criar estrutura de `BRIEFINGS_V2` com entrada vazia/placeholder pras 7 estratégias
3. Criar `CodeViewer` isolado e testar manualmente com arquivo qualquer
4. Refatorar `_brief()` pra consumir `BRIEFINGS_V2` (inicialmente com placeholder)
5. Smoke test do layout novo com dados placeholder
6. Criar `docs/audits/backtest-physics-2026-04-10.md` com sumário + template vazio
7. **Iteração CITADEL**: audit → preencher BRIEFINGS_V2["CITADEL"] → smoke → commit → **checkpoint user**
8. Iterações restantes (JUMP, BRIDGEWATER, DE SHAW, MILLENNIUM, TWO SIGMA, JANE STREET) —
   podem paralelizar via subagents após CITADEL validado
9. Gerar `backlog.md` a partir do audit final
10. Smoke test end-to-end das 7 estratégias
11. Remover `BRIEFINGS` antigo
12. Commit final
