# Lane 3 — Fluxo de Trabalho — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduzir fricção do ritual (session/daily log scaffolding), formalizar coordenação Claude↔Codex (ACTIVE.md vivo + PROTOCOL.md estático), e dividir `config/params.py` em camadas via shim.

**Architecture:** 3 sub-lanes independentes. 3.1 ganha amortização no dia 1 (usado imediatamente por outras lanes). 3.3 é shim-only no core protegido — aprovação registrada.

**Tech Stack:** Python 3.14 stdlib, git, Markdown.

**Spec:** `docs/superpowers/specs/2026-04-18-lane-3-fluxo-de-trabalho-design.md`

---

## Sub-lane 3.1 — Session/Daily log helper

### Task 1.1: Definir contrato do helper via test

**Files:**
- Create: `tests/integration/test_new_session_log.py`
- Create: `tools/maintenance/new_session_log.py` (stub a seguir)

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_new_session_log.py`:
```python
import subprocess
import sys
from pathlib import Path


def test_scaffold_session_log_from_head_creates_file(tmp_path, monkeypatch):
    """Dado um git repo com 1+ commits, o script gera markdown com cabeçalho, tabela de commits e placeholders."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "x.txt").write_text("hi")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "feat(x): inicial"], cwd=repo, check=True)

    script = Path(__file__).resolve().parents[2] / "tools" / "maintenance" / "new_session_log.py"
    out = repo / "docs" / "sessions" / "2026-04-18_1200.md"
    result = subprocess.run(
        [sys.executable, str(script), "--last-commit", "--out", str(out)],
        cwd=repo, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    content = out.read_text()
    assert "# Session Log —" in content
    assert "## Commits" in content
    assert "| Hash | Mensagem | Arquivos |" in content
    assert "feat(x): inicial" in content
    assert "<!-- TODO:" in content  # placeholders pra prosa
    assert "## Arquivos Modificados" in content
```

- [ ] **Step 2: Run test to confirm fail**

Run: `pytest tests/integration/test_new_session_log.py -v`
Expected: FAIL — script não existe.

### Task 1.2: Implementar helper

**Files:**
- Create: `tools/maintenance/new_session_log.py`

- [ ] **Step 1: Escrever script**

Create `tools/maintenance/new_session_log.py`:
```python
"""Scaffold a session log with mechanical sections pre-filled.

Mechanical: commits table, files modified list, smoke state (if available).
Human: Resumo, Mudanças Críticas, Achados, Notas pro Joao.

Usage:
  python -m tools.maintenance.new_session_log --last-commit --out docs/sessions/2026-04-18_1400.md
  python -m tools.maintenance.new_session_log --since "2 hours ago" --out ...
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


def _git(*args: str, cwd: Path = Path(".")) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def _commits_since(ref: str, cwd: Path) -> list[dict]:
    fmt = "%H%x1f%s%x1f%an"
    raw = _git("log", f"{ref}..HEAD", f"--pretty=format:{fmt}", cwd=cwd)
    if not raw:
        return []
    rows = []
    for line in raw.splitlines():
        h, msg, author = line.split("\x1f")
        files = _git("show", "--pretty=", "--name-only", h, cwd=cwd).splitlines()
        rows.append({"hash": h[:7], "msg": msg, "files": files, "author": author})
    return rows


def _files_changed(ref: str, cwd: Path) -> list[str]:
    raw = _git("diff", "--stat", f"{ref}..HEAD", cwd=cwd)
    return raw.splitlines() if raw else []


def _smoke_state(cwd: Path) -> str:
    path = cwd / "tests" / "reports" / "latest_smoke.json"
    if not path.exists():
        return "TBD (sem tests/reports/latest_smoke.json)"
    try:
        data = json.loads(path.read_text())
        return f"{data.get('passed', '?')}/{data.get('total', '?')}"
    except Exception:
        return "TBD (parse falhou)"


def _build_markdown(commits: list[dict], files: list[str], smoke: str, when: dt.datetime) -> str:
    lines = [f"# Session Log — {when.strftime('%Y-%m-%d %H:%M')}", "", "## Resumo", "<!-- TODO: 1-3 frases do que foi feito -->", ""]
    lines += ["## Commits", "", "| Hash | Mensagem | Arquivos |", "|------|----------|----------|"]
    if commits:
        for c in commits:
            files_cell = ", ".join(c["files"][:3]) + (" ..." if len(c["files"]) > 3 else "")
            lines.append(f"| `{c['hash']}` | {c['msg']} | {files_cell} |")
    else:
        lines.append("| — | (sem commits no range) | — |")
    lines += [""]
    lines += ["## Mudanças Críticas",
              "<!-- TODO: mudanças em lógica de sinais, custos, sizing ou risco.",
              "    Se nenhuma: \"Nenhuma mudança em lógica de trading.\" -->", ""]
    lines += ["## Achados", "<!-- TODO: bugs, comportamentos inesperados, métricas suspeitas -->", ""]
    lines += ["## Estado do Sistema",
              f"- Smoke test: {smoke}",
              "- Backlog restante: TBD",
              "- Próximo passo sugerido: TBD", ""]
    lines += ["## Arquivos Modificados", "```"]
    lines += files if files else ["(nenhum)"]
    lines += ["```", "", "## Notas para o Joao", "<!-- TODO: preencher pelo agente -->", ""]
    return "\n".join(lines) + "\n"


def _update_daily_log(out_path: Path, when: dt.datetime) -> None:
    day_path = out_path.parent.parent / "days" / f"{when.strftime('%Y-%m-%d')}.md"
    day_path.parent.mkdir(parents=True, exist_ok=True)
    entry_line = f"- {when.strftime('%H:%M')} — [1 linha do que foi feito] — [{out_path.name}]({out_path.name})"
    if day_path.exists():
        content = day_path.read_text()
        if "## Sessões do dia" in content:
            content = content.replace(
                "## Sessões do dia\n",
                f"## Sessões do dia\n{entry_line}\n",
                1,
            )
        else:
            content = f"## Sessões do dia\n{entry_line}\n\n" + content
        day_path.write_text(content)
    else:
        day_path.write_text(
            f"# Daily Log — {when.strftime('%Y-%m-%d')}\n\n"
            f"## Sessões do dia\n{entry_line}\n\n"
            f"## Entregas principais (consolidado)\n- TBD\n\n"
            f"## Commits do dia: (atualizar ao final do dia)\n\n"
            f"## Estado final\n- Suite: TBD\n- Mudanças em CORE de trading? TBD\n- Backlog top: TBD\n\n"
            f"## Pendências pra amanhã\n- TBD\n\n"
            f"## Nota do dia\nTBD\n"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--last-commit", action="store_true", help="Usa HEAD^ como base")
    grp.add_argument("--since", type=str, help='Passado a git log --since (ex: "2 hours ago")')
    grp.add_argument("--range", type=str, help="Ex: abc1234..HEAD")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    cwd = args.cwd.resolve()
    if args.last_commit:
        ref = "HEAD^"
    elif args.since:
        # git log --since devolve commits; usar a primeira linha pra derivar um ref antigo
        raw = _git("log", f"--since={args.since}", "--pretty=format:%H", cwd=cwd).splitlines()
        ref = raw[-1] + "^" if raw else "HEAD^"
    else:
        ref = args.range.split("..")[0]

    commits = _commits_since(ref, cwd)
    files = _files_changed(ref, cwd)
    smoke = _smoke_state(cwd)
    now = dt.datetime.now()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(_build_markdown(commits, files, smoke, now))
    _update_daily_log(args.out, now)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/integration/test_new_session_log.py -v`
Expected: PASS.

- [ ] **Step 3: Smoke do script em diretório real**

```bash
python -m tools.maintenance.new_session_log --last-commit --out /tmp/test_session_log.md
cat /tmp/test_session_log.md
```
Expected: markdown com cabeçalho, tabela de commits do último commit, placeholders.

- [ ] **Step 4: Commit**

```bash
git add tools/maintenance/new_session_log.py tests/integration/test_new_session_log.py
git commit -m "feat(maintenance): helper pra scaffold session+daily log"
```

### Task 1.3: Atualizar CLAUDE.md referenciando o helper

**Files:**
- Modify: `CLAUDE.md` — seção "REGRA PERMANENTE — SESSION LOG"

- [ ] **Step 1: Adicionar nota sobre o helper**

Edit `CLAUDE.md` — localizar a seção "REGRA PERMANENTE — SESSION LOG" e adicionar depois do formato de markdown:
```markdown
**Helper disponível:**
Em vez de escrever o scaffold manualmente, rodar:
```bash
python -m tools.maintenance.new_session_log --last-commit --out docs/sessions/YYYY-MM-DD_HHMM.md
```
O helper gera commits table, lista de arquivos, estado do smoke. A prosa
(Resumo, Mudanças Críticas, Achados, Notas pro Joao) é responsabilidade
do agente.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): referenciar helper de session log"
```

---

## Sub-lane 3.2 — Orchestration Claude↔Codex

### Task 2.1: Escrever PROTOCOL.md estático

**Files:**
- Create: `docs/orchestration/PROTOCOL.md`

- [ ] **Step 1: Criar diretório**

Run: `mkdir -p docs/orchestration`

- [ ] **Step 2: Escrever PROTOCOL**

Create `docs/orchestration/PROTOCOL.md`:
```markdown
# AURUM — Agent Orchestration Protocol

Protocolo fixo. Referência permanente para trabalho multi-agente
(Claude, Codex, outros).

## Quem pode tocar o CORE PROTEGIDO

`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`
(e suas localizações pós-refactor: `core/signals/indicators.py`,
`core/signals/core.py`, `core/risk/portfolio.py`, `config/_params/**`).

**Ninguém** sem aprovação explícita do Joao na sessão atual. Aprovação dada
em sessão anterior não transita — cada sessão reavalia.

## Como sinalizar edição em progresso

1. Antes de tocar arquivo "high-risk" (qualquer do CORE protegido, ou
   arquivos que outro agente está editando), declarar em `ACTIVE.md`
   via `python -m tools.maintenance.orchestration_snapshot --claim ...`.
2. Commit e push frequente — outro agente precisa ver o diff pra evitar
   colisão.
3. Se precisar pausar >1h, liberar o claim (`--release`).

## Protocolo de conflito

Dois agentes querem o mesmo arquivo:
1. Quem fez o claim primeiro (timestamp em ACTIVE.md) tem prioridade.
2. O segundo espera o primeiro terminar (ou pede handoff explícito).
3. Merge conflict em run real: resolver favorecendo **a mudança mais
   atômica** (preservar ambas se possível; nunca `git checkout --ours`
   ou `--theirs` sem inspeção).

## Ordem de merge

Quando dois branches tocam arquivos partilhados:
1. Merge primeiro o branch com menor escopo / blast radius.
2. Segundo branch faz rebase e resolve conflitos localmente.
3. Nunca force-push em main/master.

## High-risk files (atualizar conforme projeto evolui)

- `CORE PROTEGIDO` (ver acima)
- `launcher.py` — arquivo grande, mudanças de múltiplos agentes viram
  conflitos feios. Coordenar.
- `config/engines.py` — registro central de engines.
- `api/server.py` — servidor de cockpit.
```

- [ ] **Step 3: Commit**

```bash
git add docs/orchestration/PROTOCOL.md
git commit -m "docs(orchestration): PROTOCOL.md — regras fixas de multi-agente"
```

### Task 2.2: Helper script pra ACTIVE.md

**Files:**
- Create: `tools/maintenance/orchestration_snapshot.py`
- Create: `tests/integration/test_orchestration_snapshot.py`

- [ ] **Step 1: Write failing test**

Create `tests/integration/test_orchestration_snapshot.py`:
```python
import subprocess
import sys
from pathlib import Path


def test_claim_creates_active_md(tmp_path):
    active = tmp_path / "docs" / "orchestration" / "ACTIVE.md"
    active.parent.mkdir(parents=True)

    script = Path(__file__).resolve().parents[2] / "tools" / "maintenance" / "orchestration_snapshot.py"
    result = subprocess.run(
        [sys.executable, str(script),
         "--claim", "Lane 1",
         "--files", "launcher.py,core/",
         "--agent", "Claude",
         "--branch", "feat/phi-engine",
         "--active-file", str(active)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    content = active.read_text()
    assert "Claude" in content
    assert "Lane 1" in content
    assert "launcher.py" in content


def test_release_removes_entry(tmp_path):
    active = tmp_path / "docs" / "orchestration" / "ACTIVE.md"
    active.parent.mkdir(parents=True)
    active.write_text(
        "# Agent Orchestration — ACTIVE — 2026-04-18 12:00\n\n"
        "## Lanes ativas\n"
        "| Agente | Branch | Lane | Arquivos | Status |\n"
        "|--------|--------|------|----------|--------|\n"
        "| Claude | feat/phi-engine | Lane 1 | launcher.py | em andamento |\n"
    )

    script = Path(__file__).resolve().parents[2] / "tools" / "maintenance" / "orchestration_snapshot.py"
    result = subprocess.run(
        [sys.executable, str(script),
         "--release", "Lane 1",
         "--agent", "Claude",
         "--active-file", str(active)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    content = active.read_text()
    assert "Lane 1" not in content
```

- [ ] **Step 2: Run test — expect fail**

Run: `pytest tests/integration/test_orchestration_snapshot.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement script**

Create `tools/maintenance/orchestration_snapshot.py`:
```python
"""Manage docs/orchestration/ACTIVE.md — live state of multi-agent work.

Usage:
  python -m tools.maintenance.orchestration_snapshot \\
    --claim "Lane 1" --files "launcher.py,core/" --agent Claude --branch feat/phi-engine
  python -m tools.maintenance.orchestration_snapshot --release "Lane 1" --agent Claude
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path


HEADER_PREFIX = "# Agent Orchestration — ACTIVE —"
TABLE_HEADER = "| Agente | Branch | Lane | Arquivos | Status |"
TABLE_SEP = "|--------|--------|------|----------|--------|"


def _read(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text().splitlines()


def _write(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _ensure_skeleton(lines: list[str]) -> list[str]:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not lines or not any(l.startswith(HEADER_PREFIX) for l in lines):
        return [
            f"{HEADER_PREFIX} {now}",
            "",
            "## Lanes ativas",
            TABLE_HEADER,
            TABLE_SEP,
        ]
    return lines


def _claim(lines: list[str], agent: str, branch: str, lane: str, files: str) -> list[str]:
    lines = _ensure_skeleton(lines)
    # Localiza separador; insere logo depois
    idx = next(i for i, l in enumerate(lines) if l == TABLE_SEP)
    row = f"| {agent} | {branch} | {lane} | {files} | em andamento |"
    # Se já existe linha com mesmo agent+lane, substitui
    for j in range(idx + 1, len(lines)):
        if lines[j].startswith("| ") and f"| {lane} |" in lines[j] and f"| {agent} |" in lines[j]:
            lines[j] = row
            return lines
        if not lines[j].startswith("|"):
            break
    lines.insert(idx + 1, row)
    return lines


def _release(lines: list[str], agent: str, lane: str) -> list[str]:
    pattern = re.compile(rf"^\| {re.escape(agent)} \|.*\| {re.escape(lane)} \|")
    return [l for l in lines if not pattern.match(l)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--claim", metavar="LANE", type=str)
    action.add_argument("--release", metavar="LANE", type=str)
    parser.add_argument("--files", type=str, default="")
    parser.add_argument("--agent", type=str, required=True)
    parser.add_argument("--branch", type=str, default="")
    parser.add_argument("--active-file", type=Path, default=Path("docs/orchestration/ACTIVE.md"))
    args = parser.parse_args(argv)

    lines = _read(args.active_file)
    if args.claim:
        lines = _claim(lines, args.agent, args.branch or "?", args.claim, args.files or "?")
    else:
        lines = _release(lines, args.agent, args.release)
    _write(args.active_file, lines)
    print(f"{args.active_file} atualizado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest tests/integration/test_orchestration_snapshot.py -v`
Expected: PASS.

- [ ] **Step 5: Criar ACTIVE.md inicial**

Run:
```bash
python -m tools.maintenance.orchestration_snapshot \
  --claim "Lane 3" --files "docs/orchestration/,tools/maintenance/,config/params.py" \
  --agent Claude --branch feat/phi-engine
```

- [ ] **Step 6: Commit**

```bash
git add tools/maintenance/orchestration_snapshot.py tests/integration/test_orchestration_snapshot.py docs/orchestration/ACTIVE.md
git commit -m "feat(orchestration): helper pra ACTIVE.md + ACTIVE inicial"
```

### Task 2.3: Referenciar orchestration em CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Adicionar seção referenciando PROTOCOL**

Edit `CLAUDE.md` — adicionar na seção "Regras para Claude Code":
```markdown
### Multi-agente (Claude ↔ Codex)

Regras fixas: `docs/orchestration/PROTOCOL.md`
Estado atual: `docs/orchestration/ACTIVE.md`

Antes de tocar arquivo high-risk:
```bash
python -m tools.maintenance.orchestration_snapshot --claim "<lane>" --files "<lista>" --agent <nome>
```

Ao terminar:
```bash
python -m tools.maintenance.orchestration_snapshot --release "<lane>" --agent <nome>
```
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): referenciar orchestration PROTOCOL + ACTIVE"
```

---

## Sub-lane 3.3 — config/params.py split

### Task 3.1: Baseline pré-split

⚠️ **config/params.py** é CORE PROTEGIDO. Aprovação registrada no design (shim only, zero mudança de valor).

**Files:**
- Create: `data/refactor_baseline/2026-04-18_lane3_params_digest.json`

- [ ] **Step 1: Gerar digest do params.py atual**

Run:
```bash
python -c "
import hashlib, json
import config.params as p
values = {k: repr(getattr(p, k)) for k in dir(p) if not k.startswith('_')}
digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
print(json.dumps({'n_symbols': len(values), 'digest': digest}, indent=2))
" > data/refactor_baseline/2026-04-18_lane3_params_digest.json
cat data/refactor_baseline/2026-04-18_lane3_params_digest.json
```
Expected: JSON com contagem de símbolos e digest SHA-256 dos valores.

- [ ] **Step 2: Gerar digest de backtest de referência (se não veio da Lane 1)**

Run:
```bash
python aurum_cli.py --engine citadel --days 30 --out /tmp/citadel_30d_pre_split.csv
python -c "import hashlib; print(hashlib.sha256(open('/tmp/citadel_30d_pre_split.csv','rb').read()).hexdigest())" \
  > data/refactor_baseline/2026-04-18_lane3_backtest.sha256
cat data/refactor_baseline/2026-04-18_lane3_backtest.sha256
```

- [ ] **Step 3: Commit baseline**

```bash
git add data/refactor_baseline/
git commit -m "chore(lane3): baseline pre-split do config/params.py"
```

### Task 3.2: Criar estrutura `config/_params/`

**Files:**
- Create: `config/_params/__init__.py`, `config/_params/costs.py`, `config/_params/risk.py`, `config/_params/universe.py`, `config/_params/signals.py`, `config/_params/engines/__init__.py`

- [ ] **Step 1: Criar diretórios**

```bash
mkdir -p config/_params/engines
touch config/_params/__init__.py config/_params/engines/__init__.py
```

- [ ] **Step 2: Confirmar nada quebrou**

Run: `python smoke_test.py --quiet`
Expected: baseline.

- [ ] **Step 3: Commit**

```bash
git add config/_params/
git commit -m "refactor(config): criar estrutura de _params/ vazia"
```

### Task 3.3: Mover costs para `_params/costs.py`

**Files:**
- Create: `config/_params/costs.py`
- Modify: `config/params.py` — remover linhas de costs + adicionar shim no topo

- [ ] **Step 1: Identificar constantes de custos em params.py**

Run: `grep -nE "^(SLIPPAGE|SPREAD|COMMISSION|FUNDING|C1_|C2_|COST_)" config/params.py`
Registrar linhas.

- [ ] **Step 2: Copiar essas linhas (e comentários adjacentes) pra `_params/costs.py`**

Write `config/_params/costs.py`: (conteúdo exato das linhas identificadas no Step 1)
```python
"""Layer: costs.

C1 (per-trade: SLIPPAGE + SPREAD + COMMISSION) + C2 (funding rates).
"""
# (colar as linhas exatas do params.py)
SLIPPAGE = 0.0005
SPREAD = 0.0002
COMMISSION = 0.0004
FUNDING_PER_8H = 0.0001
# ... (outras constantes do grupo)
```

- [ ] **Step 3: Adicionar re-export no topo de `config/params.py`**

Edit `config/params.py` — adicionar logo após docstring / imports top:
```python
# Compatibility layer — valores movidos para config._params.costs
from config._params.costs import *  # noqa: F401,F403
```

- [ ] **Step 4: Verificar valor inalterado**

Run:
```bash
python -c "from config.params import SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H; print(SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H)"
```
Expected: mesmos valores pré-split.

- [ ] **Step 5: Re-digest e comparar**

Run: comando do Task 3.1 Step 1 → comparar digest.
Expected: **mesmo digest** (os valores não mudaram, só a origem).

- [ ] **Step 6: Se digest bateu, remover as linhas originais do params.py**

Edit `config/params.py` — remover as linhas de custos já duplicadas em `_params/costs.py` (pois vêm agora via `from … import *`).

- [ ] **Step 7: Re-digest final**

```bash
python -c "
import hashlib, json, importlib
import config.params
importlib.reload(config.params)
values = {k: repr(getattr(config.params, k)) for k in dir(config.params) if not k.startswith('_')}
print(hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest())
"
```
Expected: **mesmo digest do baseline** (Task 3.1 Step 1).

- [ ] **Step 8: Smoke + backtest SHA check**

```bash
python smoke_test.py --quiet
python aurum_cli.py --engine citadel --days 30 --out /tmp/citadel_30d_post_costs.csv
python -c "import hashlib; print(hashlib.sha256(open('/tmp/citadel_30d_post_costs.csv','rb').read()).hexdigest())"
```
Expected: SHA idêntico ao baseline (Task 3.1 Step 2).

- [ ] **Step 9: Se qualquer digest divergir → REVERT**

```bash
git checkout -- config/params.py config/_params/costs.py
```

- [ ] **Step 10: Commit se tudo bateu**

```bash
git add config/params.py config/_params/costs.py
git commit -m "refactor(params): extrair camada costs para config/_params/costs (digest match)"
```

### Task 3.4: Mover risk para `_params/risk.py`

Mesmo padrão da Task 3.3.

**Constantes:** Kelly, MAX_DD, CORR_*, MAX_OPEN_POSITIONS, SIZE_MULT, DD_SCALE_*

- [ ] **Step 1: Identificar via grep**

Run: `grep -nE "^(KELLY|MAX_DD|CORR_|MAX_OPEN|SIZE_MULT|DD_SCALE|KELLY_CAP)" config/params.py`

- [ ] **Step 2: Copiar pra `config/_params/risk.py`** com docstring explicativo

- [ ] **Step 3: Adicionar `from config._params.risk import *` em `config/params.py`**

- [ ] **Step 4: Verificar imports e digest**

```bash
python -c "from config.params import KELLY_CAP, MAX_DD, MAX_OPEN_POSITIONS; print(KELLY_CAP, MAX_DD, MAX_OPEN_POSITIONS)"
# + re-digest do Task 3.1 Step 1
```

- [ ] **Step 5: Remover linhas originais de params.py**

- [ ] **Step 6: Re-digest final + smoke + backtest SHA**

Mesmo protocolo da Task 3.3.

- [ ] **Step 7: Commit**

```bash
git add config/params.py config/_params/risk.py
git commit -m "refactor(params): extrair camada risk (digest match)"
```

### Task 3.5: Mover universe para `_params/universe.py`

**Constantes:** BASKETS, ACCOUNT_SIZE, symbol lists, TIMEFRAMES, INTERVAL_*

- [ ] **Step 1-7:** mesmo padrão da Task 3.4.

```bash
git commit -m "refactor(params): extrair camada universe (digest match)"
```

### Task 3.6: Mover signals para `_params/signals.py`

**Constantes:** OMEGA_WEIGHTS, SCORE_THRESHOLD, SCORE_BY_REGIME, STOP_ATR_M, TARGET_RR, trailing params

- [ ] **Step 1-7:** mesmo padrão.

```bash
git commit -m "refactor(params): extrair camada signals (digest match)"
```

### Task 3.7: Mover params por engine para `_params/engines/<engine>.py`

**Files:**
- Create: `config/_params/engines/phi.py`, `config/_params/engines/citadel.py`, `config/_params/engines/millennium.py`, etc — um por engine que tem constantes prefixadas.

- [ ] **Step 1: Listar prefixes**

Run: `grep -cE "^(PHI|CITADEL|MILLENNIUM|JUMP|RENAISSANCE|BRIDGEWATER|JANE|DESHAW|DE_SHAW|MEDALLION|KEPOS|GRAHAM|AQR|TWO_SIGMA|ORNSTEIN|MEANREV)_" config/params.py`

Se > 0, proceder.

- [ ] **Step 2: Para cada prefix com ≥ 3 constantes, criar arquivo dedicado**

Exemplo PHI:
Write `config/_params/engines/phi.py`:
```python
"""PHI engine parameters (Fibonacci fractal + cluster scoring)."""
# (copiar todas as linhas `PHI_*` de params.py)
```

- [ ] **Step 3: Para cada engine, adicionar re-export em `config/_params/engines/__init__.py`**

Edit `config/_params/engines/__init__.py`:
```python
from config._params.engines.phi import *  # noqa: F401,F403
from config._params.engines.citadel import *  # noqa: F401,F403
# ... etc
```

- [ ] **Step 4: Adicionar `from config._params.engines import *` em `config/params.py`**

- [ ] **Step 5: Remover linhas originais de params.py**

- [ ] **Step 6: Re-digest + smoke + backtest SHA**

Mesmo protocolo.

- [ ] **Step 7: Commit**

```bash
git add config/params.py config/_params/engines/
git commit -m "refactor(params): extrair params por engine (digest match)"
```

### Task 3.8: Checkpoint final Lane 3.3

- [ ] **Step 1: Contar linhas finais de params.py**

Run: `wc -l config/params.py`
Expected: ≤ 30 linhas (só shims).

- [ ] **Step 2: Listar estrutura `config/_params/`**

Run: `ls config/_params/ config/_params/engines/`
Expected: `costs.py`, `risk.py`, `universe.py`, `signals.py`, `engines/`, plus `__init__.py`s.

- [ ] **Step 3: Digest final bate com baseline**

```bash
python -c "
import hashlib, json
import config.params as p
values = {k: repr(getattr(p, k)) for k in dir(p) if not k.startswith('_')}
print(hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest())
"
```
Comparar com `data/refactor_baseline/2026-04-18_lane3_params_digest.json`.
Expected: **mesmo digest**.

- [ ] **Step 4: Backtest SHA bate com baseline**

Mesmo protocolo do Task 3.1 Step 2.

- [ ] **Step 5: Suite completa**

```bash
python smoke_test.py --quiet
pytest tests/ -q
```

- [ ] **Step 6: Se qualquer check falhou — REVERT tudo da Sub-lane 3.3 e investigar**

---

## Fechamento Lane 3

### Task 4.1: Session log + daily log via helper

- [ ] **Step 1: Rodar helper criado na Sub-lane 3.1**

```bash
python -m tools.maintenance.new_session_log --last-commit --out docs/sessions/$(date +%Y-%m-%d_%H%M).md
```

- [ ] **Step 2: Preencher prosa (Resumo, Notas pro Joao) no markdown gerado**

Editar o arquivo criado. Substituir `<!-- TODO: ... -->` pelo conteúdo real.

- [ ] **Step 3: Release claim do ACTIVE.md**

```bash
python -m tools.maintenance.orchestration_snapshot --release "Lane 3" --agent Claude
```

- [ ] **Step 4: Commit final**

```bash
git add docs/sessions/ docs/days/ docs/orchestration/ACTIVE.md
git commit -m "docs(sessions): Lane 3 fluxo de trabalho fechada"
```

---

## Critérios de sucesso (duros)

- Helper de session log funcional (tests passando, usado ao menos 1x com sucesso).
- `docs/orchestration/PROTOCOL.md` e `ACTIVE.md` commitados.
- `CLAUDE.md` referencia ambos.
- `config/params.py` ≤ 30 linhas (só shims).
- Digest SHA-256 dos valores de `config.params` **idêntico** ao baseline.
- Digest SHA-256 do backtest de referência **idêntico** ao baseline.
- Smoke 156/156.

---

## Self-Review Checklist

- [x] Spec coverage: session helper (3.1), orchestration (3.2), params split (3.3 tasks 3.1-3.8) — todos cobertos.
- [x] Placeholder scan: sem "TBD" em steps executáveis. Placeholders `<!-- TODO: -->` são conteúdo intencional do markdown gerado pelo helper (markdown user-facing).
- [x] Consistency: `ACTIVE.md`, `PROTOCOL.md`, `config/_params/`, digest protocol uniformes entre tasks.
- [x] Digest check em toda extração de params (Tasks 3.3-3.7) — critério duro consistente.
- [x] Aprovação registrada em Task 3.1 e 3.8 (CORE protegido).
