# Research Desk — Quant↔Agent Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar feedback-loop quant→agent→quant na Research Desk screen do launcher, reusando o módulo `launcher_support/research_desk/` existente.

**Architecture:** 5 fixes (A1-A5) + 4 silenciadores (B). Extensão in-place de 6 arquivos + 1 módulo novo (`issue_detail.py`). Testes pytest puros, sem Tk real (pattern do subsystem). Commits por tarefa.

**Tech Stack:** Python 3.11, TkInter (launcher), pytest, stdlib only (urllib para Paperclip, `@dataclass(frozen=True)` pro shape layer).

**Spec:** `docs/superpowers/specs/2026-04-24-research-desk-quant-agent-loop-design.md`

---

## File structure

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `launcher_support/research_desk/live_runs.py` | MODIFY | Adiciona `STATUS_STALE` em `_classify_status` |
| `launcher_support/research_desk/artifact_scanner.py` | MODIFY | Adiciona `_scan_backtests`, `_detect_origin`, `list_backtest_runs`; extende `ArtifactEntry` |
| `launcher_support/research_desk/artifact_linking.py` | MODIFY | Adiciona `LinkedChain.backtest_run_id` + populator |
| `launcher_support/research_desk/ticket_form.py` | MODIFY | Adiciona `run_id` em `TicketDraft` + validate + payload + UI combobox |
| `launcher_support/research_desk/issue_detail.py` | CREATE | `IssueDetailModal` Toplevel novo, ~200 linhas |
| `launcher_support/screens/research_desk.py` | MODIFY | Wire modal + CONFIGURE + silenciadores |
| `tests/launcher/research_desk/test_live_runs.py` | MODIFY | Adiciona test de stale |
| `tests/launcher/research_desk/test_artifact_scanner.py` | MODIFY | Adiciona tests de backtest scan + origin |
| `tests/launcher/research_desk/test_artifact_linking.py` | MODIFY | Adiciona test de LinkedChain.backtest_run_id |
| `tests/launcher/research_desk/test_ticket_form.py` | MODIFY | Adiciona tests de run_id validate + payload |
| `tests/launcher/research_desk/test_issue_detail.py` | CREATE | Tests do novo modal (API pura) |
| `tests/launcher/research_desk/test_research_desk_actions.py` | CREATE | Test do `_on_configure_click` wiring |

---

## Task 1: A3 — STATUS_STALE no live_runs.py

**Files:**
- Modify: `launcher_support/research_desk/live_runs.py` (add constants + update `_classify_status`)
- Test: `tests/launcher/research_desk/test_live_runs.py` (append)

### - [ ] Step 1: Escrever test falhando

Append no final de `tests/launcher/research_desk/test_live_runs.py`:

```python
from launcher_support.research_desk.live_runs import STATUS_STALE


def test_classify_stale_when_started_long_ago_no_end() -> None:
    """AUR-12 failure mode: agent setou started mas nunca escreveu ended."""
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(1000),  # 16min atrás (>15min)
    })
    assert view.status == STATUS_STALE


def test_classify_running_when_started_recent_no_end() -> None:
    """Regressão: started recente ainda é RUNNING, não STALE."""
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(300),  # 5min atrás (<15min)
    })
    assert view.status == STATUS_RUNNING


def test_classify_explicit_running_overrides_stale_heuristic() -> None:
    """status explícito 'running' vence heurística de timeout."""
    view = shape_run({
        "id": "r1",
        "status": "running",
        "started_at": _iso_minus(2000),
    })
    assert view.status == STATUS_RUNNING
```

### - [ ] Step 2: Rodar test — deve falhar

```bash
cd C:/Users/Joao/projects/aurum.finance
python -m pytest tests/launcher/research_desk/test_live_runs.py -v -k stale
```
Expected: `ImportError: cannot import name 'STATUS_STALE'`

### - [ ] Step 3: Implementar

Em `launcher_support/research_desk/live_runs.py`, após linha 19:

```python
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_ERROR = "error"
STATUS_STALE = "stale"
STATUS_UNKNOWN = "unknown"

STALE_THRESHOLD_SEC = 900  # 15 min — started sem ended = stale
```

Atualizar `_STATUS_ICON`:

```python
_STATUS_ICON: dict[str, str] = {
    STATUS_RUNNING: "◐",
    STATUS_SUCCESS: "●",
    STATUS_ERROR: "✕",
    STATUS_STALE: "⏸",
    STATUS_UNKNOWN: "○",
}
```

Atualizar `_classify_status` (substituir bloco `if started and not ended:`):

```python
def _classify_status(raw: dict) -> str:
    """running/stale/success/error/unknown. Stale = started+sem ended
    com timeout; AUR-12 failure mode."""
    explicit = (_str(raw, "status", "state") or "").lower()
    if explicit in ("running", "in_progress"):
        return STATUS_RUNNING
    if explicit in ("error", "failed", "failure"):
        return STATUS_ERROR
    if explicit in ("success", "completed", "done", "ok"):
        return STATUS_SUCCESS

    ended = _str(raw, "ended_at", "finished_at", "completed_at")
    started = _str(raw, "started_at", "created_at")
    if started and not ended:
        started_epoch = _parse_when(started)
        if started_epoch > 0:
            import time
            if time.time() - started_epoch > STALE_THRESHOLD_SEC:
                return STATUS_STALE
        return STATUS_RUNNING

    exit_code = raw.get("exit_code")
    if isinstance(exit_code, (int, float)):
        return STATUS_SUCCESS if int(exit_code) == 0 else STATUS_ERROR

    return STATUS_UNKNOWN
```

### - [ ] Step 4: Rodar tests — todos verdes

```bash
python -m pytest tests/launcher/research_desk/test_live_runs.py -v
```
Expected: todos PASS (tests novos + pre-existentes como regressão).

### - [ ] Step 5: Commit

```bash
git add launcher_support/research_desk/live_runs.py \
        tests/launcher/research_desk/test_live_runs.py
git commit -m "feat(research-desk): STATUS_STALE em _classify_status (A3)

Detecta AUR-12 failure mode: agent seta started_at mas nunca escreve
ended_at. Threshold 15min. Pinta card do agent laranja em vez de ficar
em RUNNING pra sempre.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: A4.1 — Backtest scan + origin tag em artifact_scanner.py

**Files:**
- Modify: `launcher_support/research_desk/artifact_scanner.py`
- Test: `tests/launcher/research_desk/test_artifact_scanner.py` (append)

### - [ ] Step 1: Escrever test de `_scan_backtests`

Append em `tests/launcher/research_desk/test_artifact_scanner.py`:

```python
from launcher_support.research_desk.artifact_scanner import (
    list_backtest_runs,
    scan_artifacts,
)


def test_scan_backtests_picks_dated_subdirs(tmp_path):
    """Varre data/<engine>/<YYYY-MM-DD_HHMM>/ e retorna ArtifactEntry."""
    (tmp_path / "data" / "citadel" / "2026-04-23_1403").mkdir(parents=True)
    (tmp_path / "data" / "phi" / "2026-04-20_0900").mkdir(parents=True)
    (tmp_path / "data" / "citadel" / "not_a_run").mkdir(parents=True)

    entries = scan_artifacts(tmp_path)
    backtests = [e for e in entries if e.kind == "backtest"]

    assert len(backtests) == 2
    stems = {(e.engine, e.run_id) for e in backtests}
    assert ("citadel", "2026-04-23_1403") in stems
    assert ("phi", "2026-04-20_0900") in stems


def test_scan_backtests_empty_when_data_missing(tmp_path):
    """data/ não existe = lista vazia, sem crash."""
    entries = scan_artifacts(tmp_path)
    backtests = [e for e in entries if e.kind == "backtest"]
    assert backtests == []


def test_list_backtest_runs_sorted_recent_first(tmp_path):
    import os, time
    d1 = tmp_path / "data" / "citadel" / "2026-04-20_0900"
    d2 = tmp_path / "data" / "citadel" / "2026-04-23_1403"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    # Força mtime diferente
    os.utime(d1, (time.time() - 1000, time.time() - 1000))

    runs = list_backtest_runs(tmp_path)
    assert len(runs) == 2
    # Mais recente primeiro
    assert runs[0][0] == "citadel" and runs[0][1] == "2026-04-23_1403"
    assert runs[1][0] == "citadel" and runs[1][1] == "2026-04-20_0900"


def test_detect_origin_agent_when_label_matches(tmp_path):
    from launcher_support.research_desk.artifact_scanner import _detect_origin
    issues = [
        {"id": "1", "labels": ["run:citadel/2026-04-23_1403"]},
    ]
    origin = _detect_origin(tmp_path, "citadel", "2026-04-23_1403", issues)
    assert origin == "agent"


def test_detect_origin_human_when_no_label_no_branch(tmp_path):
    from launcher_support.research_desk.artifact_scanner import _detect_origin
    origin = _detect_origin(tmp_path, "citadel", "2026-04-23_1403", [])
    assert origin == "human"
```

### - [ ] Step 2: Rodar tests — devem falhar

```bash
python -m pytest tests/launcher/research_desk/test_artifact_scanner.py -v -k "backtests or origin or list_backtest"
```
Expected: `ImportError: cannot import name 'list_backtest_runs'` etc.

### - [ ] Step 3: Estender `ArtifactEntry`

Em `artifact_scanner.py` substituir a dataclass (linhas 26-34):

```python
@dataclass(frozen=True)
class ArtifactEntry:
    """Um artefato producido por um agente ou run de backtest."""
    agent_key: str               # "RESEARCH" | "REVIEW" | "BUILD" | "CURATE" | "AUDIT" | ""
    kind: str                    # "spec" | "review" | "branch" | "audit" | "backtest"
    title: str
    path: str
    mtime_epoch: float
    is_markdown: bool
    engine: str = ""             # só backtest: "citadel", "phi", ...
    run_id: str = ""             # só backtest: "2026-04-23_1403"
    origin: str = ""             # "agent" | "human" | "" (não-backtest)
```

### - [ ] Step 4: Adicionar `_scan_backtests` + `_detect_origin` + `list_backtest_runs`

Adicionar no final de `artifact_scanner.py`:

```python
import re as _re

_RUN_SUBDIR = _re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}$")


def _scan_backtests(
    root: Path, issues: list[dict] | None = None,
) -> list[ArtifactEntry]:
    """Varre data/<engine>/<YYYY-MM-DD_HHMM>/ e retorna entries
    com kind='backtest'. Retorna [] se data/ não existe."""
    base = root / "data"
    if not base.exists() or not base.is_dir():
        return []
    issues = issues or []
    out: list[ArtifactEntry] = []
    for engine_dir in base.iterdir():
        if not engine_dir.is_dir():
            continue
        engine = engine_dir.name
        for run_dir in engine_dir.iterdir():
            if not run_dir.is_dir():
                continue
            if not _RUN_SUBDIR.match(run_dir.name):
                continue
            try:
                stat = run_dir.stat()
            except OSError:
                continue
            run_id = run_dir.name
            origin = _detect_origin(root, engine, run_id, issues)
            out.append(ArtifactEntry(
                agent_key="",
                kind="backtest",
                title=f"{engine}/{run_id}",
                path=str(run_dir.relative_to(root)).replace("\\", "/"),
                mtime_epoch=stat.st_mtime,
                is_markdown=False,
                engine=engine,
                run_id=run_id,
                origin=origin,
            ))
    return out


def _detect_origin(
    root: Path, engine: str, run_id: str, issues: list[dict],
) -> str:
    """agent se label 'run:<engine>/<run_id>' em alguma issue OR body tem
    '**run_id:** <engine>/<run_id>'. Senão human."""
    needle = f"{engine}/{run_id}"
    label_needle = f"run:{needle}"
    body_needle = f"**run_id:** {needle}"
    for issue in issues:
        labels = issue.get("labels") or []
        if isinstance(labels, list) and label_needle in labels:
            return "agent"
        desc = issue.get("description") or issue.get("body") or ""
        if isinstance(desc, str) and body_needle in desc:
            return "agent"
    return "human"


def list_backtest_runs(
    root: Path, limit: int = 50,
) -> list[tuple[str, str, float]]:
    """(engine, run_id, mtime) ordenado desc por mtime."""
    entries = _scan_backtests(root, issues=[])
    entries.sort(key=lambda e: e.mtime_epoch, reverse=True)
    return [(e.engine, e.run_id, e.mtime_epoch) for e in entries[:limit]]
```

### - [ ] Step 5: Integrar em `scan_artifacts`

Substituir `scan_artifacts` (linhas 45-55):

```python
def scan_artifacts(
    root: Path, limit: int = 50, issues: list[dict] | None = None,
) -> list[ArtifactEntry]:
    """Combina filesystem + git refs + backtests; limit mais recentes."""
    entries: list[ArtifactEntry] = []
    for agent_key, kind, rel_dir in _AGENT_KINDS:
        entries.extend(_scan_markdown_dir(
            root=root, rel_dir=rel_dir, agent_key=agent_key, kind=kind,
        ))
    entries.extend(_scan_experiment_branches(root=root))
    entries.extend(_scan_backtests(root, issues=issues))

    entries.sort(key=lambda e: e.mtime_epoch, reverse=True)
    return entries[:limit]
```

### - [ ] Step 6: Rodar tests — todos verdes

```bash
python -m pytest tests/launcher/research_desk/test_artifact_scanner.py -v
```
Expected: todos PASS.

### - [ ] Step 7: Commit

```bash
git add launcher_support/research_desk/artifact_scanner.py \
        tests/launcher/research_desk/test_artifact_scanner.py
git commit -m "feat(research-desk): backtest scan + origin tag (A4.1)

artifact_scanner agora varre data/<engine>/<YYYY-MM-DD_HHMM>/ e retorna
ArtifactEntry com kind='backtest', engine, run_id, origin. origin=agent
se label 'run:<engine>/<id>' ou '**run_id:** <id>' num ticket existente;
senão human. list_backtest_runs() pro autocomplete do NewTicketModal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: A4.2 — LinkedChain.backtest_run_id

**Files:**
- Modify: `launcher_support/research_desk/artifact_linking.py`
- Test: `tests/launcher/research_desk/test_artifact_linking.py` (append)

### - [ ] Step 1: Escrever test falhando

Append em `test_artifact_linking.py`:

```python
def test_linked_chain_holds_backtest_run_id():
    from launcher_support.research_desk.artifact_linking import LinkedChain
    chain = LinkedChain(stem="phi-fib", backtest_run_id="phi/2026-04-23_1403")
    assert chain.backtest_run_id == "phi/2026-04-23_1403"


def test_link_artifacts_populates_backtest_from_entries():
    from launcher_support.research_desk.artifact_scanner import ArtifactEntry
    from launcher_support.research_desk.artifact_linking import link_artifacts
    spec = ArtifactEntry(
        agent_key="RESEARCH", kind="spec", title="phi-fib",
        path="docs/specs/phi-fib.md", mtime_epoch=100.0, is_markdown=True,
    )
    bt = ArtifactEntry(
        agent_key="", kind="backtest", title="phi/2026-04-23_1403",
        path="data/phi/2026-04-23_1403", mtime_epoch=200.0, is_markdown=False,
        engine="phi", run_id="2026-04-23_1403", origin="agent",
    )
    chains = link_artifacts([spec, bt])
    assert len(chains) == 1
    assert chains[0].backtest_run_id == "phi/2026-04-23_1403"
```

### - [ ] Step 2: Rodar — deve falhar

```bash
python -m pytest tests/launcher/research_desk/test_artifact_linking.py -v -k backtest
```
Expected: `AttributeError: 'LinkedChain' object has no attribute 'backtest_run_id'` ou similar.

### - [ ] Step 3: Adicionar slot + populator

Em `artifact_linking.py`, adicionar em `LinkedChain` (após `audit`):

```python
@dataclass(frozen=True)
class LinkedChain:
    """Uma cadeia de trabalho relacionada por stem comum."""
    stem: str
    spec: ArtifactEntry | None = None
    review: ArtifactEntry | None = None
    branch: ArtifactEntry | None = None
    audit: ArtifactEntry | None = None
    backtest_run_id: str = ""    # "engine/run_id" se backtest linkado
    engine: str | None = None
    # ... resto igual
```

Em `link_artifacts`, modificar o loop de indexação pra capturar backtests:

```python
def link_artifacts(artifacts: Iterable[ArtifactEntry]) -> list[LinkedChain]:
    by_stem: dict[str, dict[str, ArtifactEntry]] = {}
    backtests_by_engine: dict[str, ArtifactEntry] = {}

    for art in artifacts:
        if art.kind == "backtest":
            # Guarda o backtest mais recente por engine (vem pré-ordenado)
            key = art.engine.lower()
            if key not in backtests_by_engine:
                backtests_by_engine[key] = art
            continue
        stem = normalize_stem(art.title)
        slot = by_stem.setdefault(stem, {})
        if art.kind not in slot:
            slot[art.kind] = art

    chains: list[LinkedChain] = []
    for stem, slots in by_stem.items():
        if len(slots) < 2:
            continue
        engine_key = detect_engine(stem)
        bt_entry = None
        if engine_key is not None:
            bt_entry = backtests_by_engine.get(engine_key.lower())
        chains.append(LinkedChain(
            stem=stem,
            spec=slots.get("spec"),
            review=slots.get("review"),
            branch=slots.get("branch"),
            audit=slots.get("audit"),
            backtest_run_id=(
                f"{bt_entry.engine}/{bt_entry.run_id}" if bt_entry else ""
            ),
            engine=engine_key,
        ))

    def _latest_mtime(chain: LinkedChain) -> float:
        return max((p.mtime_epoch for p in chain.parts), default=0.0)
    chains.sort(key=_latest_mtime, reverse=True)
    return chains
```

### - [ ] Step 4: Rodar — todos verdes

```bash
python -m pytest tests/launcher/research_desk/test_artifact_linking.py -v
```
Expected: todos PASS (novos + regressão antigos).

### - [ ] Step 5: Commit

```bash
git add launcher_support/research_desk/artifact_linking.py \
        tests/launcher/research_desk/test_artifact_linking.py
git commit -m "feat(research-desk): LinkedChain.backtest_run_id (A4.2)

Chain completa agora ganha ponteiro pro backtest mais recente do engine
detectado, populado automaticamente a partir do mesmo input de
ArtifactEntry via link_artifacts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: A2 — run_id em TicketDraft + NewTicketModal

**Files:**
- Modify: `launcher_support/research_desk/ticket_form.py`
- Test: `tests/launcher/research_desk/test_ticket_form.py` (append)

### - [ ] Step 1: Escrever tests falhando

Append em `test_ticket_form.py`:

```python
def test_validate_accepts_optional_run_id():
    result, draft = validate_draft(
        title="Investigate phi overfit",
        description="",
        assignee_key="AUDIT",
        priority="medium",
        run_id="phi/2026-04-23_1403",
    )
    assert result.ok is True
    assert draft.run_id == "phi/2026-04-23_1403"


def test_validate_without_run_id_default_none():
    _, draft = validate_draft(
        title="title ok",
        description="",
        assignee_key="RESEARCH",
        priority="low",
    )
    assert draft.run_id is None


def test_validate_rejects_malformed_run_id():
    result, _ = validate_draft(
        title="title ok",
        description="",
        assignee_key="RESEARCH",
        priority="low",
        run_id="x y z",  # espaço rejeita
    )
    assert result.ok is False
    assert any("run_id" in e for e in result.errors)


def test_payload_injects_run_id_into_description_and_labels():
    _, draft = validate_draft(
        title="Audit phi",
        description="Check regime selection bias",
        assignee_key="AUDIT",
        priority="high",
        run_id="phi/2026-04-23_1403",
    )
    payload = draft_to_api_payload(draft)
    assert "**run_id:** phi/2026-04-23_1403" in payload["description"]
    assert "Check regime selection bias" in payload["description"]
    assert "run:phi/2026-04-23_1403" in payload.get("labels", [])


def test_payload_without_run_id_unchanged():
    _, draft = validate_draft(
        title="title ok",
        description="body",
        assignee_key="RESEARCH",
        priority="medium",
    )
    payload = draft_to_api_payload(draft)
    assert payload["description"] == "body"
    assert "labels" not in payload or payload["labels"] == []
```

### - [ ] Step 2: Rodar — devem falhar

```bash
python -m pytest tests/launcher/research_desk/test_ticket_form.py -v -k run_id
```
Expected: `TypeError: validate_draft() got an unexpected keyword argument 'run_id'`.

### - [ ] Step 3: Estender `TicketDraft` + `validate_draft`

Em `ticket_form.py`:

```python
import re
from typing import Optional

_RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_/.-]{3,}$")


@dataclass(frozen=True)
class TicketDraft:
    title: str
    description: str
    assignee: AgentIdentity
    priority: str
    run_id: Optional[str] = None


def validate_draft(
    *,
    title: str,
    description: str,
    assignee_key: str,
    priority: str,
    run_id: str | None = None,
) -> tuple[ValidationResult, TicketDraft | None]:
    errors: list[str] = []

    title_clean = (title or "").strip()
    if len(title_clean) < _TITLE_MIN:
        errors.append(f"title precisa de no minimo {_TITLE_MIN} chars")
    if len(title_clean) > _TITLE_MAX:
        errors.append(f"title maximo {_TITLE_MAX} chars")

    priority_clean = (priority or "").strip().lower()
    if priority_clean not in _PRIORITIES:
        errors.append(f"priority invalida: {priority_clean!r}")

    run_id_clean: str | None = None
    if run_id and run_id.strip():
        candidate = run_id.strip()
        if not _RUN_ID_PATTERN.match(candidate):
            errors.append(f"run_id invalido: {candidate!r}")
        else:
            run_id_clean = candidate

    assignee_key_clean = (assignee_key or "").strip().upper()
    from launcher_support.research_desk.agents import BY_KEY
    assignee = BY_KEY.get(assignee_key_clean)
    if assignee is None:
        errors.append(f"assignee desconhecido: {assignee_key_clean!r}")

    if errors:
        return ValidationResult(ok=False, errors=tuple(errors)), None

    assert assignee is not None
    draft = TicketDraft(
        title=title_clean,
        description=(description or "").strip(),
        assignee=assignee,
        priority=priority_clean,
        run_id=run_id_clean,
    )
    return ValidationResult(ok=True, errors=()), draft
```

### - [ ] Step 4: Estender `draft_to_api_payload`

```python
def draft_to_api_payload(draft: TicketDraft) -> dict:
    """Converte TicketDraft em payload aceito por POST /issues.

    Se draft.run_id presente, prefixa no description + adiciona label
    'run:<id>' para detecção posterior pelo artifact_scanner._detect_origin.
    """
    body = draft.description
    labels: list[str] = []
    if draft.run_id:
        body = f"**run_id:** {draft.run_id}\n\n{body}".rstrip()
        labels.append(f"run:{draft.run_id}")

    payload: dict = {
        "title": draft.title,
        "description": body,
        "assigned_agent_id": draft.assignee.uuid,
        "priority": draft.priority,
        "status": "todo",
    }
    if labels:
        payload["labels"] = labels
    return payload
```

### - [ ] Step 5: Adicionar combobox no `NewTicketModal._build`

Após o bloco ASSIGNEE e antes de description, inserir:

```python
        # ── Run ID (optional) ──────────────────
        tk.Label(
            wrap, text="RUN ID (optional)",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(4, 2))
        self._run_id_var = tk.StringVar(value="")
        import tkinter.ttk as ttk
        self._run_id_cb = ttk.Combobox(
            wrap, textvariable=self._run_id_var, state="normal", width=50,
        )
        self._run_id_cb.pack(anchor="w", pady=(0, 10))
        self._populate_run_ids()
```

Adicionar método em `NewTicketModal`:

```python
    def _populate_run_ids(self) -> None:
        """Auto-complete com runs recentes de data/*/. Best-effort."""
        try:
            from pathlib import Path
            from launcher_support.research_desk.artifact_scanner import (
                list_backtest_runs,
            )
            # Procura root do repo subindo até achar 'data' ou 'pyproject.toml'
            here = Path(__file__).resolve()
            root = here
            for _ in range(6):
                if (root / "data").is_dir() or (root / "pyproject.toml").exists():
                    break
                root = root.parent
            values = [f"{eng}/{rid}" for eng, rid, _ in list_backtest_runs(root, limit=30)]
            self._run_id_cb.configure(values=values)
        except Exception:
            self._run_id_cb.configure(values=[])
```

Atualizar o submit handler do modal pra passar `run_id`. Grep antes pra localizar:

```bash
grep -n "validate_draft\|self._title_var" launcher_support/research_desk/ticket_form.py
```

No método `_on_submit` (ou equivalente), modificar o call a `validate_draft`:

```python
        result, draft = validate_draft(
            title=self._title_var.get(),
            description=(self._desc_widget.get("1.0", "end") if self._desc_widget else ""),
            assignee_key=self._assignee_var.get(),
            priority=self._priority_var.get(),
            run_id=self._run_id_var.get() or None,
        )
```

### - [ ] Step 6: Rodar tests — todos verdes

```bash
python -m pytest tests/launcher/research_desk/test_ticket_form.py -v
```
Expected: todos PASS.

### - [ ] Step 7: Commit

```bash
git add launcher_support/research_desk/ticket_form.py \
        tests/launcher/research_desk/test_ticket_form.py
git commit -m "feat(research-desk): run_id em TicketDraft + NewTicketModal (A2)

Novo ticket pode linkar backtest run. Combobox auto-preenchido com runs
recentes de data/*/; payload injeta '**run_id:** <id>' no body + label
'run:<id>' pro artifact_scanner detectar origin=agent downstream.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: A1 — IssueDetailModal (módulo novo)

**Files:**
- Create: `launcher_support/research_desk/issue_detail.py`
- Create: `tests/launcher/research_desk/test_issue_detail.py`
- Modify: `launcher_support/screens/research_desk.py` (wire `_on_issue_click` + `_on_activity_click`)

### - [ ] Step 1: Test skeleton API pura

Criar `tests/launcher/research_desk/test_issue_detail.py`:

```python
"""Tests do IssueDetailModal — API pura + shape."""
from __future__ import annotations

from unittest.mock import MagicMock

from launcher_support.research_desk.issue_detail import (
    _parse_lineage,
    _shape_comments,
    _format_header_line,
)


def test_parse_lineage_from_description():
    desc = "from: AUR-7 (REVIEW SHIP)\n\nMain body here"
    assert _parse_lineage(desc) == "AUR-7 (REVIEW SHIP)"


def test_parse_lineage_none_when_absent():
    assert _parse_lineage("no lineage in body") is None


def test_shape_comments_sorted_oldest_first():
    raw = [
        {"id": "c2", "body": "reply", "created_at": "2026-04-24T10:00:00Z",
         "author_agent_id": "uuid-a"},
        {"id": "c1", "body": "first", "created_at": "2026-04-24T09:00:00Z",
         "author_agent_id": "uuid-b"},
    ]
    shaped = _shape_comments(raw)
    assert shaped[0].id == "c1"
    assert shaped[1].id == "c2"


def test_shape_comments_empty_when_raw_none():
    assert _shape_comments(None) == []


def test_format_header_line():
    line = _format_header_line(
        issue_id="AUR-12", title="Audit CAPULA",
        status="in_progress", priority="high", assignee_key="AUDIT",
    )
    assert "AUR-12" in line
    assert "Audit CAPULA" in line
    assert "AUDIT" in line
```

### - [ ] Step 2: Rodar — deve falhar

```bash
python -m pytest tests/launcher/research_desk/test_issue_detail.py -v
```
Expected: `ModuleNotFoundError: No module named 'launcher_support.research_desk.issue_detail'`

### - [ ] Step 3: Criar módulo com shape helpers + modal

Criar `launcher_support/research_desk/issue_detail.py`:

```python
"""IssueDetailModal — Toplevel pra ver um ticket do Paperclip ao vivo.

Abre via open_issue_detail(parent, client, issue_id, on_close=cb).
Polling interno 5s; fecha c/ ESC ou botão FECHAR; on_close dispara
refresh no caller. Circuit breaker failure → banner offline inline.

Shape layer (_parse_lineage, _shape_comments, _format_header_line) é
testável sem Tk.
"""
from __future__ import annotations

import datetime as dt
import re
import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BG2, BG3, BORDER,
    DIM, DIM2, FONT, GREEN, RED, WHITE,
)
from launcher_support.research_desk.agents import AGENTS, BY_UUID
from launcher_support.research_desk.palette import AGENT_COLORS


POLL_INTERVAL_MS = 5000
_LINEAGE_RE = re.compile(r"^from:\s*(AUR-\d+[^\n]*)", re.MULTILINE)


@dataclass(frozen=True)
class CommentView:
    id: str
    body: str
    created_at_iso: str
    age_text: str
    author_sigil: str         # agent key ou "—"
    author_color: str         # hex


def _parse_lineage(description: str | None) -> str | None:
    if not description:
        return None
    m = _LINEAGE_RE.search(description)
    if m:
        return m.group(1).strip()
    return None


def _shape_comments(raw: list[dict] | None) -> list[CommentView]:
    if not raw:
        return []
    out: list[CommentView] = []
    for c in raw:
        cid = str(c.get("id") or "")
        body = (c.get("body") or c.get("text") or "").strip()
        iso = c.get("created_at") or ""
        author_uuid = c.get("author_agent_id") or c.get("agent_id") or ""
        sigil = "—"
        color = DIM
        agent = BY_UUID.get(author_uuid) if author_uuid else None
        if agent is not None:
            sigil = agent.key
            color = AGENT_COLORS[agent.key].primary
        out.append(CommentView(
            id=cid,
            body=body,
            created_at_iso=iso,
            age_text=_iso_age(iso),
            author_sigil=sigil,
            author_color=color,
        ))
    out.sort(key=lambda v: v.created_at_iso)  # oldest first
    return out


def _iso_age(iso: str) -> str:
    if not iso:
        return "—"
    try:
        moment = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "—"
    now = dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    s = int((now - moment).total_seconds())
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}min"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def _format_header_line(
    *, issue_id: str, title: str, status: str, priority: str, assignee_key: str,
) -> str:
    return f"{issue_id}  ·  {title}  ·  {status.upper()}  ·  {priority.upper()}  ·  {assignee_key}"


class IssueDetailModal:
    """Toplevel readonly pra detail + comments com polling."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        client: Any,
        issue_id: str,
        on_close: Callable[[], None] | None = None,
    ):
        self._client = client
        self._issue_id = issue_id
        self._on_close = on_close
        self._closing = False
        self._poll_after: str | None = None

        self.top = tk.Toplevel(parent)
        self.top.title(f"ISSUE {issue_id}")
        self.top.configure(bg=BG)
        self.top.geometry("640x560")
        self.top.transient(parent)
        self.top.bind("<Escape>", lambda _e: self.close())
        self.top.protocol("WM_DELETE_WINDOW", self.close)

        self._header_var = tk.StringVar(value=f"{issue_id}  ·  loading…")
        self._offline_label: tk.Label | None = None
        self._lineage_label: tk.Label | None = None
        self._body_widget: tk.Text | None = None
        self._comments_frame: tk.Frame | None = None

        self._build()
        self._tick()  # fetch inicial + agenda poll

    def _build(self) -> None:
        wrap = tk.Frame(self.top, bg=BG, padx=16, pady=12)
        wrap.pack(fill="both", expand=True)

        self._offline_label = tk.Label(
            wrap, text="", font=(FONT, 8, "bold"),
            fg=RED, bg=BG, anchor="w",
        )
        self._offline_label.pack(anchor="w")

        tk.Label(
            wrap, textvariable=self._header_var,
            font=(FONT, 10, "bold"), fg=AMBER, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        self._lineage_label = tk.Label(
            wrap, text="", font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
        )
        self._lineage_label.pack(anchor="w", pady=(2, 8))
        tk.Frame(wrap, bg=DIM, height=1).pack(fill="x")

        tk.Label(
            wrap, text="BODY", font=(FONT, 8, "bold"),
            fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(8, 2))
        self._body_widget = tk.Text(
            wrap, height=8, bg=BG2, fg=WHITE, font=(FONT, 9),
            relief="flat", wrap="word", state="disabled",
        )
        self._body_widget.pack(fill="x")

        tk.Label(
            wrap, text="COMMENTS", font=(FONT, 8, "bold"),
            fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(12, 2))

        canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0, height=220)
        canvas.pack(fill="both", expand=True)
        self._comments_frame = tk.Frame(canvas, bg=BG)
        canvas.create_window((0, 0), window=self._comments_frame, anchor="nw")
        self._comments_canvas = canvas

        footer = tk.Frame(wrap, bg=BG); footer.pack(fill="x", pady=(10, 0))
        close_btn = tk.Label(
            footer, text="  FECHAR  ", font=(FONT, 8, "bold"),
            fg=WHITE, bg=BG3, cursor="hand2", padx=10, pady=4,
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.close())

    def _tick(self) -> None:
        if self._closing:
            return
        try:
            issue = self._client.get_issue(self._issue_id)
            comments = self._client.list_comments(self._issue_id)
            self._apply(issue, comments, offline=False)
        except Exception as exc:
            self._apply(None, None, offline=True, error=str(exc))

        if not self._closing:
            self._poll_after = self.top.after(POLL_INTERVAL_MS, self._tick)

    def _apply(
        self, issue: dict | None, comments: list[dict] | None,
        *, offline: bool, error: str = "",
    ) -> None:
        if self._closing:
            return
        if offline:
            label = self._offline_label
            if label is not None:
                label.configure(text=f"⚠  PAPERCLIP OFFLINE — {error[:40]}", fg=RED)
            return
        if self._offline_label is not None:
            self._offline_label.configure(text="")

        if issue is not None:
            assignee_uuid = issue.get("assigned_agent_id") or ""
            agent = BY_UUID.get(assignee_uuid) if assignee_uuid else None
            akey = agent.key if agent else "—"
            self._header_var.set(_format_header_line(
                issue_id=self._issue_id,
                title=(issue.get("title") or "(sem título)")[:80],
                status=issue.get("status") or "unknown",
                priority=issue.get("priority") or "medium",
                assignee_key=akey,
            ))
            lineage = _parse_lineage(issue.get("description"))
            if self._lineage_label is not None:
                self._lineage_label.configure(
                    text=f"← {lineage}" if lineage else "",
                )
            body = issue.get("description") or ""
            w = self._body_widget
            if w is not None:
                w.configure(state="normal")
                w.delete("1.0", "end")
                w.insert("1.0", body[:4000])
                w.configure(state="disabled")

        self._render_comments(_shape_comments(comments))

    def _render_comments(self, views: list[CommentView]) -> None:
        frame = self._comments_frame
        if frame is None:
            return
        for child in frame.winfo_children():
            child.destroy()
        if not views:
            tk.Label(
                frame, text="(sem comments ainda)",
                font=(FONT, 9), fg=DIM, bg=BG,
            ).pack(anchor="w", padx=4, pady=2)
            return
        for v in views:
            row = tk.Frame(frame, bg=BG)
            row.pack(fill="x", anchor="w", pady=(4, 0))
            tk.Label(
                row, text=f"{v.author_sigil}  {v.age_text}",
                font=(FONT, 8, "bold"), fg=v.author_color, bg=BG,
            ).pack(anchor="w")
            tk.Label(
                row, text=v.body[:400], font=(FONT, 9), fg=WHITE, bg=BG,
                wraplength=560, justify="left", anchor="w",
            ).pack(anchor="w", padx=(12, 0))
        try:
            self._comments_canvas.configure(
                scrollregion=self._comments_canvas.bbox("all"),
            )
        except Exception:
            pass

    def close(self) -> None:
        self._closing = True
        if self._poll_after is not None:
            try:
                self.top.after_cancel(self._poll_after)
            except Exception:
                pass
            self._poll_after = None
        try:
            self.top.destroy()
        except Exception:
            pass
        if self._on_close is not None:
            try:
                self._on_close()
            except Exception:
                pass


def open_issue_detail(
    parent: tk.Misc,
    *,
    client: Any,
    issue_id: str,
    on_close: Callable[[], None] | None = None,
) -> IssueDetailModal:
    return IssueDetailModal(parent, client=client, issue_id=issue_id, on_close=on_close)
```

### - [ ] Step 4: Rodar shape tests — verdes

```bash
python -m pytest tests/launcher/research_desk/test_issue_detail.py -v
```
Expected: todos PASS.

### - [ ] Step 5: Wire em `screens/research_desk.py`

Localizar `_on_issue_click` e `_on_activity_click`:

```bash
grep -n "_on_issue_click\|_on_activity_click" launcher_support/screens/research_desk.py
```

Adicionar import no topo do arquivo:

```python
from launcher_support.research_desk.issue_detail import open_issue_detail
```

Substituir `_on_issue_click` stub (linha ~436):

```python
    def _on_issue_click(self, issue_id: str) -> None:
        if not issue_id:
            return
        open_issue_detail(
            self,
            client=self._client,
            issue_id=issue_id,
            on_close=self._refresh_pipeline,
        )
```

Substituir o branch de issue em `_on_activity_click` (linha ~503):

```python
    def _on_activity_click(self, payload: dict) -> None:
        kind = payload.get("kind")
        if kind == "issue":
            open_issue_detail(
                self,
                client=self._client,
                issue_id=str(payload.get("id") or ""),
                on_close=self._refresh_pipeline,
            )
            return
        if kind == "artifact":
            # ... mantém lógica existente de abrir markdown viewer
```

Checar se `self._refresh_pipeline` existe — se não, usar lambda no-op ou trocar por método que dispara re-fetch do pipeline_panel. Antes de editar, grep:

```bash
grep -n "_refresh_pipeline\|_apply_pipeline\|pipeline_panel.refresh" launcher_support/screens/research_desk.py
```

Se `_refresh_pipeline` não existir, adicionar método trivial:

```python
    def _refresh_pipeline(self) -> None:
        """Re-poll forçado pro pipeline panel após ação de ticket."""
        try:
            self._poll_state()  # método existente
        except Exception:
            pass
```

### - [ ] Step 6: Smoke manual mínimo

```bash
python launcher.py
```
- Clicar AGENTS no top nav.
- Clicar num ticket no ACTIVE PIPELINE. Modal deve abrir com body + comments + lineage (se houver).
- ESC ou FECHAR deve cancelar o polling (não erro no log).
- Matar paperclip (Ctrl+C no processo) com modal aberto → banner OFFLINE aparece em 5s.

### - [ ] Step 7: Commit

```bash
git add launcher_support/research_desk/issue_detail.py \
        launcher_support/screens/research_desk.py \
        tests/launcher/research_desk/test_issue_detail.py
git commit -m "feat(research-desk): IssueDetailModal c/ polling + lineage (A1)

Novo modal readonly pra ver ticket ao vivo: header (id/title/status/
priority/assignee), breadcrumb de lineage (parse 'from: AUR-N' do body),
body markdown raw, comments list ordenada ASC. Polling 5s; CircuitOpen
pinta banner OFFLINE e mantém snapshot; close cancela after() e
dispara _refresh_pipeline no caller. Substitui 2 stubs 'em breve' no
pipeline_panel e activity_feed de _on_issue_click + _on_activity_click.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: A5 — CONFIGURE wires persona editor

**Files:**
- Modify: `launcher_support/screens/research_desk.py`
- Create: `tests/launcher/research_desk/test_research_desk_actions.py`

### - [ ] Step 1: Test falhando

Criar `tests/launcher/research_desk/test_research_desk_actions.py`:

```python
"""Tests de actions da Research Desk screen — resolve path + delegate."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from launcher_support.research_desk.agents import RESEARCH


def test_configure_action_resolves_persona_path_and_calls_editor(tmp_path, monkeypatch):
    """_on_configure_click(agent) → persona_path() → open_markdown_editor()."""
    calls = {}

    def fake_persona_path(agent_key, root):
        calls["key"] = agent_key
        calls["root"] = root
        return tmp_path / "fake_AGENTS.md"

    def fake_editor(parent, *, path, title_hint):
        calls["parent"] = parent
        calls["path"] = path
        calls["title"] = title_hint
        return MagicMock()

    monkeypatch.setattr(
        "launcher_support.screens.research_desk.persona_path", fake_persona_path,
    )
    monkeypatch.setattr(
        "launcher_support.screens.research_desk.open_markdown_editor",
        fake_editor,
    )

    from launcher_support.screens.research_desk import _on_configure_click_pure

    parent = MagicMock()
    _on_configure_click_pure(parent, RESEARCH, tmp_path)

    assert calls["key"] == "RESEARCH"
    assert calls["root"] == tmp_path
    assert calls["path"] == tmp_path / "fake_AGENTS.md"
    assert "RESEARCH persona" in calls["title"]
```

### - [ ] Step 2: Rodar — deve falhar

```bash
python -m pytest tests/launcher/research_desk/test_research_desk_actions.py -v
```
Expected: `ImportError: cannot import name '_on_configure_click_pure'`.

### - [ ] Step 3: Implementar

Em `launcher_support/screens/research_desk.py`, adicionar imports no topo:

```python
from launcher_support.research_desk.markdown_editor import (
    open_markdown_editor,
    persona_path,
)
```

Adicionar função pura + wire no método existente. Grep pra localizar o `_stub_action("configure")`:

```bash
grep -n "_stub_action\|CONFIGURE\|configure" launcher_support/screens/research_desk.py
```

Adicionar módulo-level fn (fora da classe, pra testabilidade):

```python
def _on_configure_click_pure(parent, agent, root_path) -> None:
    """Resolve persona + abre editor. Fn pura pra testar sem Tk real."""
    target = persona_path(agent.key, root_path)
    open_markdown_editor(
        parent, path=target,
        title_hint=f"{agent.key} persona · {target.name}",
    )
```

Modificar o handler do card (trocar `_stub_action("configure")` → `_on_configure_click`):

```python
    def _on_configure_click(self, agent) -> None:
        _on_configure_click_pure(self, agent, self._root_path)
```

Localizar o call site do CONFIGURE button na construção do card (pode estar em `_build_agent_card` ou similar):

```bash
grep -n "configure\|CONFIGURE" launcher_support/screens/research_desk.py
```

Substituir `command=lambda a=agent: self._stub_action("configure")` (ou equivalente) por:

```python
command=lambda a=agent: self._on_configure_click(a)
```

### - [ ] Step 4: Rodar — verde

```bash
python -m pytest tests/launcher/research_desk/test_research_desk_actions.py -v
```
Expected: PASS.

### - [ ] Step 5: Smoke manual

```bash
python launcher.py
```
- AGENTS → clicar CONFIGURE num card → editor deve abrir com `AGENTS.md` do agent.

### - [ ] Step 6: Commit

```bash
git add launcher_support/screens/research_desk.py \
        tests/launcher/research_desk/test_research_desk_actions.py
git commit -m "feat(research-desk): CONFIGURE card → persona editor (A5)

Substitui stub 'em breve' do CONFIGURE por wire direto pro
open_markdown_editor sobre AGENTS.md do agent. Fn pura
_on_configure_click_pure pra testabilidade.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: B — Silenciadores viram feedback explícito

**Files:**
- Modify: `launcher_support/screens/research_desk.py` (4 sites)

### - [ ] Step 1: Setup logging

Adicionar no topo de `research_desk.py`:

```python
import logging
from pathlib import Path

def _research_desk_logger() -> logging.Logger:
    log = logging.getLogger("aurum.research_desk")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log_dir = Path("data/.paperclip_cache")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        h = logging.FileHandler(log_dir / "research_desk.log", mode="a", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        pass
    return log

_LOG = _research_desk_logger()
```

### - [ ] Step 2: Fix `_ensure_stats_db` (screen:305)

Localizar o método (`grep -n "_ensure_stats_db" launcher_support/screens/research_desk.py`) e substituir:

```python
    def _ensure_stats_db(self) -> None:
        if getattr(self, "_stats_db_conn", None) is not None:
            return
        try:
            from config.paths import AURUM_DB_PATH
            import sqlite3
            self._stats_db_conn = sqlite3.connect(str(AURUM_DB_PATH))
        except Exception as e:
            self._stats_db_conn = None
            if not getattr(self, "_stats_db_error_flashed", False):
                _LOG.warning("stats_db indisponível: %s", e)
                self._flash_feedback(
                    ok=False, msg=f"stats_db: {e.__class__.__name__}",
                )
                self._stats_db_error_flashed = True
```

### - [ ] Step 3: Fix `_toggle_agent_pause` (screen:384)

Localizar e substituir o `except Exception: pass`:

```python
    def _toggle_agent_pause(self, agent, was_paused: bool) -> None:
        try:
            if was_paused:
                self._client.resume_agent(agent.uuid)
            else:
                self._client.pause_agent(agent.uuid)
        except Exception as e:
            # CircuitOpen ou outro — flash feedback, próximo poll corrige botão
            from launcher_support.research_desk.paperclip_client import CircuitOpen
            if isinstance(e, CircuitOpen):
                self._flash_feedback(ok=False, msg="paperclip offline")
            else:
                _LOG.warning("pause/resume falhou (%s): %s", agent.key, e)
                self._flash_feedback(
                    ok=False, msg=f"pause {agent.key}: {e.__class__.__name__}",
                )
```

### - [ ] Step 4: Fix `_apply_artifacts` (screen:626-638)

```python
    def _apply_artifacts(self) -> None:
        try:
            full_scan = scan_artifacts(self._root_path)
        except Exception as e:
            full_scan = getattr(self, "_last_full_scan", [])
            _LOG.warning("scan_artifacts falhou: %s", e)
            if not getattr(self, "_scan_error_flashed", False):
                self._flash_feedback(ok=False, msg="scan artifacts falhou")
                self._scan_error_flashed = True
        else:
            self._last_full_scan = full_scan
            self._scan_error_flashed = False

        # Apply pro artifacts panel (preserva snapshot se falhou)
        try:
            self._artifacts_panel.apply(full_scan)
        except Exception as e:
            _LOG.warning("artifacts_panel.apply falhou: %s", e)

        # Merge events pro activity feed
        try:
            events = merge_events(
                issues=self._last_issues or [],
                artifacts=full_scan,
            )
            self._activity_feed.apply(events)
        except Exception as e:
            _LOG.warning("merge_events falhou: %s", e)
            if not getattr(self, "_merge_error_flashed", False):
                self._flash_feedback(ok=False, msg="activity feed falhou")
                self._merge_error_flashed = True
```

### - [ ] Step 5: Fix `_poll_state` (screen:571)

```python
    def _poll_state(self) -> None:
        from launcher_support.research_desk.paperclip_client import CircuitOpen
        import urllib.error
        try:
            self._online = self._client.is_online()
            if self._online:
                agents_state = self._client.list_agents_cached(COMPANY_ID)
                self._last_issues = self._client.list_issues_cached(COMPANY_ID)
                budget_cents = total_budget_cents(agents_state)
                self._apply(agents_state=agents_state, budget_cents=budget_cents)
                self._apply_artifacts()
        except (CircuitOpen, urllib.error.URLError, TimeoutError):
            # Connectivity — esperado
            self._online = False
        except Exception as e:
            # Python error genuíno — separar da offline
            self._online = False
            _LOG.exception("poll_state exception: %s", e)
            self._flash_feedback(
                ok=False, msg=f"poll erro: {e.__class__.__name__}",
            )
```

### - [ ] Step 6: Smoke manual

```bash
python launcher.py
```
- AGENTS. Verificar que pill online tá verde.
- Matar paperclip process. Em 5s pill vira vermelho SEM spam no stderr.
- Log em `data/.paperclip_cache/research_desk.log` existe e tem entrada se algum erro.

### - [ ] Step 7: Commit

```bash
git add launcher_support/screens/research_desk.py
git commit -m "fix(research-desk): silenciadores viram feedback explicito (B)

4 sites com 'except Exception: pass' agora logam em
data/.paperclip_cache/research_desk.log + fazem flash na status bar:
_ensure_stats_db, _toggle_agent_pause, _apply_artifacts,
_poll_state. _poll_state separa CircuitOpen/URLError (connectivity,
esperado) de Exception genuino (bug Python, loga com traceback).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Smoke manual end-to-end

### - [ ] Step 1: Checklist completo

Launcher precisa estar rodando com Paperclip em `127.0.0.1:3100`.

- [ ] Launcher abre, pill online em Research Desk.
- [ ] **A2+A4:** NOVO TICKET → combobox RUN ID mostra `data/*/` recentes. Escolher um, assignee AUDIT, title ok, submit.
- [ ] **A1:** Clicar no ticket novo no ACTIVE PIPELINE → modal abre; body contém `**run_id:** <id>`; comments vazio; breadcrumb vazio (não há parent).
- [ ] **A1 polling:** via `curl` POST um comment no Paperclip → em 5s aparece no modal sem refresh manual.
- [ ] **A1 offline:** matar Paperclip → banner vermelho aparece em 5s; relançar → auto-recover.
- [ ] **A3:** inserir heartbeat_run manualmente com `started_at` de 20min atrás, sem `ended_at` → em próximo poll, card do agent pinta laranja (STALE).
- [ ] **A4:** `data/citadel/<recent>/` aparece na lista ARTIFACTS com badge origin=human (sem label); criar ticket com run_id=`citadel/<recent>` → re-scan mostra origin=agent.
- [ ] **A5:** CONFIGURE num card → editor abre com AGENTS.md do agent.
- [ ] **B:** tentar pause agent com Paperclip morto → banner "paperclip offline". Log em `data/.paperclip_cache/research_desk.log` tem entrada.

### - [ ] Step 2: Rodar suite completa

```bash
python -m pytest tests/launcher/research_desk/ -v
```
Expected: todos PASS, zero regressões.

### - [ ] Step 3: Commit final (se houver ajustes)

Se smoke revelou bugs, fix + commit. Senão, branch pronta pra PR.

```bash
git log --oneline feat/research-desk | head -10
```

Deve listar 7 commits novos (A3, A4.1, A4.2, A2, A1, A5, B) além do spec doc.

---

## Resumo

| Task | Item | Tempo estimado |
|---|---|---|
| 1 | A3 stale | 30 min |
| 2 | A4.1 scan + origin | 60 min |
| 3 | A4.2 LinkedChain | 30 min |
| 4 | A2 run_id ticket | 60 min |
| 5 | A1 IssueDetailModal | 2h |
| 6 | A5 configure | 20 min |
| 7 | B silenciadores | 30 min |
| 8 | Smoke E2E | 30 min |
| **Total** | | **~5h** |

Nada depende de nada fora do subsystem. Cada commit é mergeable sozinho (testes verdes em cada etapa).
