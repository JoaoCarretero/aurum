# Cockpit API Fase 1a Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expor o estado do MILLENNIUM shadow runner (rodando no VPS) para o launcher TkInter (Windows) via HTTP API tipada, read-only, acessada por SSH tunnel — tornando o painel `SHADOW LOOP` funcional sem tocar em `core/` e deixando a fundação pronta para futuros runners (CITADEL paper, JUMP shadow, etc).

**Architecture:** 3-tier institucional. Runner (existente) escreve state files. API nova (FastAPI read-only em localhost:8787) descobre runs via glob e expõe via bearer token. Cockpit client typed (urllib stdlib, zero deps novas) consome a API com circuit breaker e cache. Painel existente (`_render_shadow_panel`) ganha suporte remoto via edit cirúrgico.

**Tech Stack:** Python 3.14 · FastAPI 0.135 · pydantic 2.12 (já instalados local; VPS precisa confirmar) · stdlib urllib (client) · systemd unit (deploy VPS) · pytest (testes)

**Spec:** `docs/superpowers/specs/2026-04-18-cockpit-api-fase1a-design.md`

**Branch:** criar worktree em `.worktrees/cockpit-api` a partir de `feat/phi-engine` (convenção do João — ver memory `project_worktree_convention`).

**CORE protegido:** este plano NÃO toca em `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, ou `config/params.py`. Acceptance criteria valida isso.

---

## File structure

### Novos arquivos

| Arquivo | Responsabilidade | Linhas est. |
|---|---|---|
| `tools/cockpit_api.py` | FastAPI app: discovery + endpoints + auth | ~350 |
| `launcher_support/cockpit_client.py` | Typed client com circuit breaker + cache | ~180 |
| `core/shadow_contract.py` | Schemas pydantic compartilhados (Manifest, Heartbeat, RunSummary, TradeRecord) + helpers de discovery | ~120 |
| `deploy/aurum_cockpit_api.service` | systemd unit | ~35 |
| `deploy/install_cockpit_api_vps.sh` | Installer one-shot | ~60 |
| `tests/test_shadow_contract.py` | Testes de schemas + discovery | ~120 |
| `tests/test_cockpit_api.py` | Testes de endpoints + auth | ~200 |
| `tests/test_cockpit_client.py` | Testes de circuit breaker + cache | ~140 |

### Arquivos editados

| Arquivo | Mudança | Linhas |
|---|---|---|
| `tools/millennium_shadow.py` | Escreve `manifest.json` no start; calcula `config_hash` | +40 |
| `launcher_support/engines_live_view.py` | `_find_latest_shadow_run` + STOP wired ao client | +25 |
| `.gitignore` | `data/.cockpit_cache/` | +1 |

### Zero mudança

`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`, `engines/millennium.py`, qualquer engine.

---

## Dependency graph

```
Task 0 (worktree)
   │
   ├─► Task 1 (schemas core/shadow_contract.py)
   │      │
   │      ├─► Task 2 (manifest writer no shadow runner)
   │      ├─► Task 3 (API healthz + /runs)
   │      ├─► Task 4 (API detail + heartbeat + trades)
   │      ├─► Task 5 (API kill)
   │      │
   │      └─► Task 6 (cockpit_client.py)
   │             │
   │             └─► Task 7 (launcher integration)
   │
   ├─► Task 8 (systemd + installer)
   └─► Task 9 (deploy VPS + smoke)
```

Tasks 2–5 são independentes após 1; podem ser paralelizadas se quiseres.
Task 7 precisa 6. Task 9 precisa 2 + 3 + 4 + 5 + 8.

---

## Task 0: Setup worktree

**Files:** nenhum (git ops)

- [ ] **Step 1: Criar worktree a partir de feat/phi-engine**

```bash
git worktree add -b feat/cockpit-api .worktrees/cockpit-api feat/phi-engine
cd .worktrees/cockpit-api
```

- [ ] **Step 2: Confirmar diretório e branch**

```bash
pwd && git branch --show-current
```

Expected: path termina em `.worktrees/cockpit-api`; branch `feat/cockpit-api`.

- [ ] **Step 3: Confirmar suite verde baseline**

```bash
python -m pytest -q 2>&1 | tail -3
```

Expected: `1141 passed, 7 skipped` (ou superior se Codex subiu mais testes).

---

## Task 1: Schemas + discovery em core/shadow_contract.py

**Files:**
- Create: `core/shadow_contract.py`
- Test: `tests/test_shadow_contract.py`

### Por que existe

Schemas compartilhados entre runner (escreve), API (lê e serve), e client (consome). Single source of truth do shape — se eu mudar uma vez, os 3 consomem.

Discovery helper (`find_runs`) é testável em isolamento e reusável. API e client NÃO reimplementam a varredura.

- [ ] **Step 1: Write the failing test — schema básico**

Create `tests/test_shadow_contract.py`:

```python
"""Tests for shared shadow-runner contract: pydantic models + discovery."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.shadow_contract import (
    Manifest,
    Heartbeat,
    RunSummary,
    find_runs,
    compute_config_hash,
)


def test_manifest_parses_valid_payload():
    payload = {
        "run_id": "2026-04-18_0229",
        "engine": "millennium",
        "mode": "shadow",
        "started_at": "2026-04-18T02:29:38.754671+00:00",
        "commit": "3fa328b",
        "branch": "feat/phi-engine",
        "config_hash": "sha256:deadbeef",
        "host": "vmi3200601",
    }
    m = Manifest(**payload)
    assert m.run_id == "2026-04-18_0229"
    assert m.engine == "millennium"
    assert m.mode == "shadow"


def test_manifest_rejects_unknown_mode():
    with pytest.raises(ValueError):
        Manifest(
            run_id="x", engine="millennium", mode="bogus",
            started_at=datetime.now(timezone.utc),
            commit="a", branch="b", config_hash="c", host="d",
        )


def test_heartbeat_accepts_null_last_error():
    hb = Heartbeat(
        run_id="x", status="running",
        ticks_ok=5, ticks_fail=0, novel_total=100,
        last_tick_at=datetime.now(timezone.utc),
        last_error=None, tick_sec=900,
    )
    assert hb.last_error is None


def test_heartbeat_rejects_unknown_status():
    with pytest.raises(ValueError):
        Heartbeat(
            run_id="x", status="bogus",
            ticks_ok=0, ticks_fail=0, novel_total=0,
            last_tick_at=None, last_error=None, tick_sec=900,
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_shadow_contract.py -v
```

Expected: FAIL `ModuleNotFoundError: No module named 'core.shadow_contract'`.

- [ ] **Step 3: Implement schemas**

Create `core/shadow_contract.py`:

```python
"""Shared contract for shadow/paper/live runners consumed by cockpit API.

Runners write manifest.json + heartbeat.json to `<run_dir>/state/`. The
cockpit API discovers runs via `find_runs` and validates payloads against
these pydantic models. Cockpit client imports the same models for typed
responses. One source of truth avoids schema drift.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RunMode = Literal["shadow", "paper", "testnet", "live", "backtest"]
RunStatus = Literal["running", "stopped", "failed"]


class Manifest(BaseModel):
    """Imutável: escrito uma vez no start do runner."""
    run_id: str
    engine: str
    mode: RunMode
    started_at: datetime
    commit: str
    branch: str
    config_hash: str
    host: str
    python_version: str | None = None


class Heartbeat(BaseModel):
    """Mutável: atualizado a cada tick pelo runner.

    extra='allow' — runner pode evoluir o shape; client consome o que
    conhece e preserva o resto.
    """
    run_id: str
    status: RunStatus
    ticks_ok: int = 0
    ticks_fail: int = 0
    novel_total: int = 0
    last_tick_at: datetime | None = None
    last_error: str | None = None
    tick_sec: int = 0
    started_at: datetime | None = None
    run_hours: float = 0.0
    stopped_at: datetime | None = None
    stopped_reason: str | None = None
    model_config = ConfigDict(extra="allow")


class RunSummary(BaseModel):
    """Linha leve do /runs — o suficiente pra listar sem payloads pesados."""
    run_id: str
    engine: str
    mode: RunMode
    status: RunStatus
    started_at: datetime
    last_tick_at: datetime | None = None
    novel_total: int = 0


class RunDetail(BaseModel):
    """Resposta de /runs/{id}: agrega manifest + heartbeat."""
    manifest: Manifest
    heartbeat: Heartbeat


class TradeRecord(BaseModel):
    """Schema permissivo — engine schema evolve; extra fields preservados."""
    timestamp: datetime
    symbol: str
    strategy: str
    direction: str
    entry: float | None = None
    exit: float | None = None
    pnl: float | None = None
    shadow_observed_at: datetime | None = None
    model_config = ConfigDict(extra="allow")


# ─── Discovery ────────────────────────────────────────────────

def find_runs(data_root: Path, engines: list[str] | None = None) -> list[Path]:
    """Return run_dir paths containing a heartbeat.json, sorted by mtime DESC.

    Honors existing layout: `data/{engine}_shadow/{run_id}/state/heartbeat.json`
    AND future layout: `data/shadow/{engine}/{run_id}/state/heartbeat.json`.

    If `engines` is given, restricts to those engine names.
    """
    runs: list[tuple[float, Path]] = []
    if not data_root.exists():
        return []
    for engine_dir in data_root.iterdir():
        if not engine_dir.is_dir():
            continue
        # Layout A: data/{engine}_shadow/{run_id}/
        if engine_dir.name.endswith("_shadow"):
            engine = engine_dir.name.removesuffix("_shadow")
            if engines and engine not in engines:
                continue
            for run_dir in engine_dir.iterdir():
                hb = run_dir / "state" / "heartbeat.json"
                if hb.exists():
                    runs.append((hb.stat().st_mtime, run_dir))
        # Layout B: data/shadow/{engine}/{run_id}/
        elif engine_dir.name == "shadow":
            for sub_engine in engine_dir.iterdir():
                if not sub_engine.is_dir():
                    continue
                if engines and sub_engine.name not in engines:
                    continue
                for run_dir in sub_engine.iterdir():
                    hb = run_dir / "state" / "heartbeat.json"
                    if hb.exists():
                        runs.append((hb.stat().st_mtime, run_dir))
    runs.sort(key=lambda t: t[0], reverse=True)
    return [p for _, p in runs]


def load_heartbeat(run_dir: Path) -> Heartbeat:
    """Load and validate heartbeat.json. Raises pydantic ValidationError on bad shape."""
    payload = json.loads((run_dir / "state" / "heartbeat.json").read_text(encoding="utf-8"))
    return Heartbeat(**payload)


def load_manifest(run_dir: Path) -> Manifest | None:
    """Load manifest.json if present; return None for legacy runs that predate the file."""
    path = run_dir / "state" / "manifest.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Manifest(**payload)


# ─── Config hash ──────────────────────────────────────────────

_HASH_FIELDS = (
    "SLIPPAGE", "SPREAD", "COMMISSION", "FUNDING_PER_8H",
    "BASE_RISK", "MAX_RISK", "CONVEX_ALPHA",
    "TARGET_RR", "STOP_ATR_M",
    "SCORE_THRESHOLD", "SCORE_THRESHOLD_HIGH_VOL", "SCORE_THRESHOLD_LOW_VOL",
    "OMEGA_WEIGHTS", "OMEGA_MIN_COMPONENT",
    "MAX_OPEN_POSITIONS", "CORR_THRESHOLD", "CORR_SOFT_THRESHOLD",
    "STREAK_COOLDOWN", "SYM_LOSS_COOLDOWN",
)


def compute_config_hash() -> str:
    """Hash dos campos materialmente relevantes de config/params.py.

    Estável entre runs com mesma config; muda quando qualquer tuning rolou.
    """
    from config import params as P  # lazy to avoid circular imports
    payload: dict[str, object] = {}
    for field in _HASH_FIELDS:
        if hasattr(P, field):
            payload[field] = getattr(P, field)
    serial = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(serial).hexdigest()[:16]
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_shadow_contract.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Add discovery tests**

Append to `tests/test_shadow_contract.py`:

```python
def _make_run(root: Path, engine_subdir: str, run_id: str, hb_payload: dict) -> Path:
    run_dir = root / engine_subdir / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps(hb_payload))
    return run_dir


def test_find_runs_layout_a_millennium_shadow(tmp_path):
    hb = {
        "run_id": "2026-04-18_0229",
        "status": "running",
        "ticks_ok": 1, "ticks_fail": 0, "novel_total": 625,
        "last_tick_at": "2026-04-18T02:30:05+00:00",
        "last_error": None, "tick_sec": 900,
    }
    _make_run(tmp_path, "millennium_shadow", "2026-04-18_0229", hb)
    runs = find_runs(tmp_path)
    assert len(runs) == 1
    assert runs[0].name == "2026-04-18_0229"


def test_find_runs_layout_b_shadow_citadel(tmp_path):
    hb = {
        "run_id": "2026-04-18_0300",
        "status": "running",
        "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
        "last_tick_at": None, "last_error": None, "tick_sec": 900,
    }
    _make_run(tmp_path, "shadow/citadel", "2026-04-18_0300", hb)
    runs = find_runs(tmp_path)
    assert len(runs) == 1


def test_find_runs_empty_when_no_data_root(tmp_path):
    assert find_runs(tmp_path / "nonexistent") == []


def test_find_runs_filter_by_engine(tmp_path):
    hb = {
        "run_id": "r", "status": "running",
        "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
        "last_tick_at": None, "last_error": None, "tick_sec": 900,
    }
    _make_run(tmp_path, "millennium_shadow", "r1", hb)
    _make_run(tmp_path, "citadel_shadow", "r2", hb)
    only_mm = find_runs(tmp_path, engines=["millennium"])
    assert len(only_mm) == 1
    assert only_mm[0].parent.name == "millennium_shadow"


def test_load_manifest_returns_none_when_missing(tmp_path):
    hb = {
        "run_id": "x", "status": "running",
        "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
        "last_tick_at": None, "last_error": None, "tick_sec": 900,
    }
    run_dir = _make_run(tmp_path, "millennium_shadow", "x", hb)
    assert load_manifest(run_dir) is None


def test_compute_config_hash_stable_format():
    h = compute_config_hash()
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 16
```

- [ ] **Step 6: Run all tests**

```bash
python -m pytest tests/test_shadow_contract.py -v
```

Expected: 10 passed.

- [ ] **Step 7: Commit**

```bash
git add core/shadow_contract.py tests/test_shadow_contract.py
git commit -m "feat(shadow): schemas + discovery contract em core/shadow_contract.py

Single source of truth pra Manifest/Heartbeat/RunSummary/TradeRecord.
find_runs() suporta layouts A (data/{engine}_shadow/...) e B futuro
(data/shadow/{engine}/...). compute_config_hash() estabiliza sobre
campos materiais de params.py (custos, thresholds, cooldowns).
"
```

---

## Task 2: Manifest writer no shadow runner

**Files:**
- Modify: `tools/millennium_shadow.py` (após linha ~50, antes do loop principal)

### Por que

Sem manifest.json, a API não consegue responder "que commit/config produziu esses números". Runner atual escreve heartbeat.json mas não manifest. Adição é idempotente (escreve 1x no start).

- [ ] **Step 1: Write failing test primeiro**

Create `tests/test_shadow_manifest_write.py`:

```python
"""Verify that the shadow runner writes manifest.json on start."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_shadow_writes_manifest_on_help_smoke(tmp_path, monkeypatch):
    """Importing the module + calling the writer yields a valid manifest."""
    monkeypatch.chdir(tmp_path)
    # Simulate being inside ROOT so relative paths work
    # but capture writes to a temp RUN_DIR
    sys.path.insert(0, str(ROOT))
    from core.shadow_contract import Manifest
    from tools.millennium_shadow import _write_manifest  # NEW symbol

    run_dir = tmp_path / "data" / "millennium_shadow" / "2026-04-18_0000"
    (run_dir / "state").mkdir(parents=True)

    _write_manifest(run_dir, run_id="2026-04-18_0000", engine="millennium", mode="shadow")

    payload = json.loads((run_dir / "state" / "manifest.json").read_text())
    m = Manifest(**payload)  # validates shape
    assert m.engine == "millennium"
    assert m.mode == "shadow"
    assert m.commit  # non-empty
    assert m.config_hash.startswith("sha256:")
```

- [ ] **Step 2: Run test (fails)**

```bash
python -m pytest tests/test_shadow_manifest_write.py -v
```

Expected: FAIL `ImportError: cannot import name '_write_manifest'`.

- [ ] **Step 3: Add `_write_manifest` to shadow runner**

Edit `tools/millennium_shadow.py`. After the imports block (~line 50), **before** the Telegram section, add:

```python
def _git_describe() -> tuple[str, str]:
    """Return (commit_short, branch). Empty strings on failure."""
    import subprocess
    def _run(args: list[str]) -> str:
        try:
            out = subprocess.check_output(
                args, cwd=str(ROOT), text=True, timeout=2,
                stderr=subprocess.DEVNULL,
            )
            return out.strip()
        except (subprocess.SubprocessError, OSError):
            return ""
    return _run(["git", "rev-parse", "--short", "HEAD"]), _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])


def _write_manifest(run_dir: Path, run_id: str, engine: str, mode: str) -> None:
    """Write manifest.json once at runner start. Idempotent: overwrites if exists."""
    import platform
    import socket
    from core.shadow_contract import compute_config_hash

    commit, branch = _git_describe()
    payload = {
        "run_id": run_id,
        "engine": engine,
        "mode": mode,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "commit": commit or "unknown",
        "branch": branch or "unknown",
        "config_hash": compute_config_hash(),
        "host": socket.gethostname(),
        "python_version": platform.python_version(),
    }
    atomic_write(run_dir / "state" / "manifest.json", json.dumps(payload, indent=2))
```

- [ ] **Step 4: Call `_write_manifest` in the main entrypoint**

Find the line `log.info(...)` or the start of `run_shadow()` (around line 173). **Before** the loop starts (right after `stop_requested = {...}`), add:

```python
    _write_manifest(RUN_DIR, run_id=RUN_ID, engine="millennium", mode="shadow")
```

- [ ] **Step 5: Run test**

```bash
python -m pytest tests/test_shadow_manifest_write.py -v
```

Expected: PASS.

- [ ] **Step 6: Smoke: `--help` still works**

```bash
python tools/millennium_shadow.py --help
```

Expected: usage output, no crash.

- [ ] **Step 7: Commit**

```bash
git add tools/millennium_shadow.py tests/test_shadow_manifest_write.py
git commit -m "feat(shadow): escreve manifest.json no start

Runner passa a registrar commit+branch+config_hash+host no start do run.
Agrega evidência de procedência pra auditoria — qualquer observer sabe
que commit/config produziu os sinais do JSONL.
"
```

---

## Task 3: API — healthz + /runs + auth middleware

**Files:**
- Create: `tools/cockpit_api.py`
- Test: `tests/test_cockpit_api.py`

### Por que

Endpoints iniciais (healthz + lista) são a base. Auth middleware só precisa ser escrita uma vez; tasks 4–5 reusam.

- [ ] **Step 1: Write failing tests**

Create `tests/test_cockpit_api.py`:

```python
"""Tests para cockpit_api.py — endpoints, auth, schemas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_app(tmp_path, monkeypatch):
    """Build FastAPI app with a temp data root and fixed tokens."""
    monkeypatch.setenv("AURUM_COCKPIT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("AURUM_COCKPIT_READ_TOKEN", "READ123")
    monkeypatch.setenv("AURUM_COCKPIT_ADMIN_TOKEN", "ADMIN456")
    # Importa aqui pra pegar env vars na hora certa
    from tools.cockpit_api import build_app
    return build_app()


@pytest.fixture
def client(api_app):
    return TestClient(api_app)


def _make_run(data_root: Path, engine_subdir: str, run_id: str,
              heartbeat: dict, manifest: dict | None = None) -> Path:
    run_dir = data_root / engine_subdir / run_id
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "state" / "heartbeat.json").write_text(json.dumps(heartbeat))
    if manifest is not None:
        (run_dir / "state" / "manifest.json").write_text(json.dumps(manifest))
    return run_dir


def test_healthz_no_auth(client):
    r = client.get("/v1/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_runs_requires_auth(client):
    r = client.get("/v1/runs")
    assert r.status_code == 401


def test_runs_rejects_bad_token(client):
    r = client.get("/v1/runs", headers={"Authorization": "Bearer WRONG"})
    assert r.status_code == 401


def test_runs_empty_when_no_data(client):
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    assert r.json() == []


def test_runs_lists_existing(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "2026-04-18_0229",
        heartbeat={
            "run_id": "2026-04-18_0229", "status": "running",
            "ticks_ok": 5, "ticks_fail": 0, "novel_total": 625,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
        manifest={
            "run_id": "2026-04-18_0229", "engine": "millennium",
            "mode": "shadow", "started_at": "2026-04-18T02:29:38+00:00",
            "commit": "3fa328b", "branch": "feat/phi-engine",
            "config_hash": "sha256:deadbeef", "host": "vmi3200601",
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == "2026-04-18_0229"
    assert runs[0]["engine"] == "millennium"
    assert runs[0]["novel_total"] == 625


def test_runs_admin_token_works(tmp_path, client):
    """Admin token herda read scope."""
    _make_run(
        tmp_path, "millennium_shadow", "r1",
        heartbeat={
            "run_id": "r1", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 10,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_runs_handles_legacy_no_manifest(tmp_path, client):
    """Runs sem manifest.json ainda aparecem (engine derivado do path)."""
    _make_run(
        tmp_path, "millennium_shadow", "legacy_run",
        heartbeat={
            "run_id": "legacy_run", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) == 1
    assert runs[0]["engine"] == "millennium"  # derivado do diretório
    assert runs[0]["mode"] == "shadow"
```

- [ ] **Step 2: Run tests (fail)**

```bash
python -m pytest tests/test_cockpit_api.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'tools.cockpit_api'`.

- [ ] **Step 3: Implement healthz + /runs + auth**

Create `tools/cockpit_api.py`:

```python
"""Aurum Cockpit API — read-only HTTP surface pra runners shadow/paper/live.

Descobre runs via core.shadow_contract.find_runs sobre um data_root
configurável (default: ROOT/data). Expõe GET endpoints read-only e um
POST /kill admin-scoped. Bind default 127.0.0.1 — acesso externo via
SSH tunnel.

Uso standalone:
    AURUM_COCKPIT_READ_TOKEN=... AURUM_COCKPIT_ADMIN_TOKEN=... \\
        python tools/cockpit_api.py --port 8787

Config via env vars (systemd unit preenche):
    AURUM_COCKPIT_DATA_ROOT   default: <repo>/data
    AURUM_COCKPIT_READ_TOKEN  obrigatório
    AURUM_COCKPIT_ADMIN_TOKEN obrigatório
    AURUM_COCKPIT_BIND_HOST   default: 127.0.0.1
    AURUM_COCKPIT_BIND_PORT   default: 8787
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.shadow_contract import (  # noqa: E402
    Heartbeat, Manifest, RunSummary, RunDetail,
    find_runs, load_heartbeat, load_manifest,
)

VERSION = "1.0.0"
STARTED_AT = datetime.now(timezone.utc)


def _engine_from_dir(run_dir: Path) -> tuple[str, str]:
    """Derive (engine, mode) do path quando manifest ausente.

    Layout A: data/{engine}_shadow/{run_id}/ → (engine, "shadow")
    Layout B: data/shadow/{engine}/{run_id}/ → (engine, "shadow")
    """
    parent = run_dir.parent
    if parent.name.endswith("_shadow"):
        return parent.name.removesuffix("_shadow"), "shadow"
    if parent.parent.name == "shadow":
        return parent.name, "shadow"
    return "unknown", "unknown"


def _summarize_run(run_dir: Path) -> RunSummary:
    hb = load_heartbeat(run_dir)
    manifest = load_manifest(run_dir)
    if manifest:
        engine = manifest.engine
        mode = manifest.mode
        started_at = manifest.started_at
    else:
        engine, mode = _engine_from_dir(run_dir)
        started_at = hb.last_tick_at or datetime.now(timezone.utc)
    return RunSummary(
        run_id=hb.run_id,
        engine=engine,
        mode=mode,
        status=hb.status,
        started_at=started_at,
        last_tick_at=hb.last_tick_at,
        novel_total=hb.novel_total,
    )


def _find_run_by_id(data_root: Path, run_id: str) -> Path | None:
    for run_dir in find_runs(data_root):
        if run_dir.name == run_id:
            return run_dir
    return None


def build_app() -> FastAPI:
    data_root = Path(os.environ.get("AURUM_COCKPIT_DATA_ROOT", str(ROOT / "data")))
    read_token = os.environ.get("AURUM_COCKPIT_READ_TOKEN", "")
    admin_token = os.environ.get("AURUM_COCKPIT_ADMIN_TOKEN", "")

    if not read_token or not admin_token:
        raise RuntimeError(
            "AURUM_COCKPIT_READ_TOKEN e AURUM_COCKPIT_ADMIN_TOKEN devem estar setadas"
        )

    app = FastAPI(title="Aurum Cockpit API", version=VERSION)

    def _check_auth(request: Request, admin: bool = False) -> None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="unauthorized")
        token = header.removeprefix("Bearer ").strip()
        if admin:
            if token != admin_token:
                raise HTTPException(status_code=403, detail="admin scope required")
        else:
            if token not in (read_token, admin_token):
                raise HTTPException(status_code=401, detail="unauthorized")

    @app.exception_handler(HTTPException)
    async def _exc(request: Request, exc: HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.get("/v1/healthz")
    def healthz():
        return {
            "status": "ok",
            "version": VERSION,
            "started_at": STARTED_AT.isoformat(),
        }

    @app.get("/v1/runs", response_model=list[RunSummary])
    def list_runs(request: Request):
        _check_auth(request)
        return [_summarize_run(p) for p in find_runs(data_root)]

    return app


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default=os.environ.get("AURUM_COCKPIT_BIND_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("AURUM_COCKPIT_BIND_PORT", "8787")))
    args = parser.parse_args()

    import uvicorn
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_cockpit_api.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/cockpit_api.py tests/test_cockpit_api.py
git commit -m "feat(cockpit): FastAPI read-only com healthz + /v1/runs

Bearer token auth (read/admin scopes). Discovery via
core.shadow_contract.find_runs. Legacy runs sem manifest derivam
engine do path. Bind 127.0.0.1 por default — tunnel obrigatório.
"
```

---

## Task 4: API — /runs/{id}, heartbeat, trades

**Files:**
- Modify: `tools/cockpit_api.py`
- Modify: `tests/test_cockpit_api.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_cockpit_api.py`:

```python
def test_run_detail_returns_manifest_and_heartbeat(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r1",
        heartbeat={
            "run_id": "r1", "status": "running",
            "ticks_ok": 3, "ticks_fail": 0, "novel_total": 42,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
        manifest={
            "run_id": "r1", "engine": "millennium", "mode": "shadow",
            "started_at": "2026-04-18T02:29:38+00:00",
            "commit": "abc", "branch": "feat/phi-engine",
            "config_hash": "sha256:deadbeef", "host": "vmi3200601",
        },
    )
    r = client.get("/v1/runs/r1", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    body = r.json()
    assert body["manifest"]["commit"] == "abc"
    assert body["heartbeat"]["ticks_ok"] == 3


def test_run_detail_404_when_missing(client):
    r = client.get("/v1/runs/does_not_exist", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 404


def test_heartbeat_fast_endpoint(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r2",
        heartbeat={
            "run_id": "r2", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 10,
            "last_tick_at": "2026-04-18T03:00:00+00:00",
            "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get("/v1/runs/r2/heartbeat", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 200
    assert r.json()["ticks_ok"] == 1


def test_trades_tail(tmp_path, client):
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r3",
        heartbeat={
            "run_id": "r3", "status": "running",
            "ticks_ok": 1, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    reports = run_dir / "reports"
    reports.mkdir()
    jsonl = reports / "shadow_trades.jsonl"
    lines = []
    for i in range(10):
        lines.append(json.dumps({
            "timestamp": f"2026-04-18T0{i}:00:00+00:00",
            "symbol": "BTCUSDT", "strategy": "CITADEL",
            "direction": "LONG", "entry": 50000.0 + i,
        }))
    jsonl.write_text("\n".join(lines) + "\n")

    r = client.get(
        "/v1/runs/r3/trades?limit=3",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    # Últimos 3 — ordem preservada do arquivo
    assert [t["entry"] for t in body["trades"]] == [50007.0, 50008.0, 50009.0]


def test_trades_limit_capped_at_500(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r4",
        heartbeat={
            "run_id": "r4", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.get(
        "/v1/runs/r4/trades?limit=99999",
        headers={"Authorization": "Bearer READ123"},
    )
    assert r.status_code == 400  # exceeds max
```

- [ ] **Step 2: Run tests (fail)**

```bash
python -m pytest tests/test_cockpit_api.py::test_run_detail_returns_manifest_and_heartbeat -v
```

Expected: FAIL with 404 (endpoint doesn't exist yet).

- [ ] **Step 3: Add endpoints to cockpit_api.py**

Inside `build_app()`, after the `list_runs` endpoint, add:

```python
    @app.get("/v1/runs/{run_id}")
    def run_detail(run_id: str, request: Request):
        _check_auth(request)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        hb = load_heartbeat(run_dir)
        manifest = load_manifest(run_dir)
        if manifest is None:
            engine, mode = _engine_from_dir(run_dir)
            manifest = Manifest(
                run_id=hb.run_id, engine=engine, mode=mode,
                started_at=hb.last_tick_at or datetime.now(timezone.utc),
                commit="unknown", branch="unknown",
                config_hash="unknown", host="unknown",
            )
        return RunDetail(manifest=manifest, heartbeat=hb)

    @app.get("/v1/runs/{run_id}/heartbeat", response_model=Heartbeat)
    def run_heartbeat(run_id: str, request: Request):
        _check_auth(request)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        return load_heartbeat(run_dir)

    @app.get("/v1/runs/{run_id}/trades")
    def run_trades(run_id: str, request: Request, limit: int = 50, since: str | None = None):
        _check_auth(request)
        if limit < 1 or limit > 500:
            raise HTTPException(status_code=400, detail="limit must be 1..500")
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        jsonl = run_dir / "reports" / "shadow_trades.jsonl"
        if not jsonl.exists():
            return {"run_id": run_id, "count": 0, "trades": []}
        lines = jsonl.read_text(encoding="utf-8").splitlines()
        records = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                import json as _json
                records.append(_json.loads(ln))
            except ValueError:
                continue
        if since:
            records = [r for r in records if str(r.get("timestamp", "")) > since]
        tail = records[-limit:]
        return {"run_id": run_id, "count": len(tail), "trades": tail}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_cockpit_api.py -v
```

Expected: all passed (7 + 5 new = 12).

- [ ] **Step 5: Commit**

```bash
git add tools/cockpit_api.py tests/test_cockpit_api.py
git commit -m "feat(cockpit): /runs/{id}, /heartbeat, /trades endpoints

/runs/{id} retorna manifest + heartbeat; legacy runs ganham manifest
stub com 'unknown' em campos que não temos como recuperar. /trades
faz tail com limit capped em 500, filtro opcional por since=iso_ts.
"
```

---

## Task 5: API — POST /kill (admin scope)

**Files:**
- Modify: `tools/cockpit_api.py`
- Modify: `tests/test_cockpit_api.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_cockpit_api.py`:

```python
def test_kill_requires_admin(tmp_path, client):
    _make_run(
        tmp_path, "millennium_shadow", "r5",
        heartbeat={
            "run_id": "r5", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    # Read token rejected
    r = client.post("/v1/runs/r5/kill", headers={"Authorization": "Bearer READ123"})
    assert r.status_code == 403


def test_kill_drops_flag(tmp_path, client):
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r6",
        heartbeat={
            "run_id": "r6", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    r = client.post("/v1/runs/r6/kill", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 200
    assert (run_dir / ".kill").exists()


def test_kill_404_when_missing(client):
    r = client.post("/v1/runs/missing/kill", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 404


def test_kill_idempotent(tmp_path, client):
    run_dir = _make_run(
        tmp_path, "millennium_shadow", "r7",
        heartbeat={
            "run_id": "r7", "status": "running",
            "ticks_ok": 0, "ticks_fail": 0, "novel_total": 0,
            "last_tick_at": None, "last_error": None, "tick_sec": 900,
        },
    )
    (run_dir / ".kill").write_text("")  # already present
    r = client.post("/v1/runs/r7/kill", headers={"Authorization": "Bearer ADMIN456"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run (fail)**

```bash
python -m pytest tests/test_cockpit_api.py::test_kill_drops_flag -v
```

Expected: FAIL (endpoint missing, 404 or 405).

- [ ] **Step 3: Implement /kill**

Inside `build_app()`, after `run_trades`, add:

```python
    @app.post("/v1/runs/{run_id}/kill")
    def run_kill(run_id: str, request: Request):
        _check_auth(request, admin=True)
        run_dir = _find_run_by_id(data_root, run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="run not found")
        (run_dir / ".kill").touch()
        return {"status": "kill_flag_dropped", "run_id": run_id}
```

- [ ] **Step 4: Run all API tests**

```bash
python -m pytest tests/test_cockpit_api.py -v
```

Expected: all passed (12 + 4 new = 16).

- [ ] **Step 5: Commit**

```bash
git add tools/cockpit_api.py tests/test_cockpit_api.py
git commit -m "feat(cockpit): POST /runs/{id}/kill (admin scope only)

Read token rejeitado (403). Admin token drop de .kill idempotente.
Runner para no próximo tick lendo o flag.
"
```

---

## Task 6: Cockpit client em launcher_support/cockpit_client.py

**Files:**
- Create: `launcher_support/cockpit_client.py`
- Test: `tests/test_cockpit_client.py`

### Por que

Client typed, zero deps novas (usa `urllib.request` stdlib). Circuit breaker evita hang do launcher quando API cai. Cache local dá graceful degrade.

- [ ] **Step 1: Write failing tests (circuit breaker + parsing)**

Create `tests/test_cockpit_client.py`:

```python
"""Tests do cockpit_client — parsing, circuit breaker, cache."""
from __future__ import annotations

import json
import time
from unittest.mock import patch, MagicMock

import pytest

from launcher_support.cockpit_client import (
    CockpitClient,
    CockpitConfig,
    CircuitOpen,
)


@pytest.fixture
def tmp_cache(tmp_path):
    return tmp_path / "cache"


@pytest.fixture
def cfg():
    return CockpitConfig(
        base_url="http://localhost:8787",
        read_token="READ",
        admin_token="ADMIN",
        timeout_sec=1.0,
    )


def _fake_response(body: dict, status: int = 200):
    mock = MagicMock()
    mock.status = status
    mock.read.return_value = json.dumps(body).encode("utf-8")
    mock.__enter__.return_value = mock
    return mock


def test_healthz_ok(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    with patch("urllib.request.urlopen", return_value=_fake_response({"status": "ok"})):
        assert client.healthz()["status"] == "ok"


def test_list_runs_returns_list(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    body = [{
        "run_id": "r1", "engine": "millennium", "mode": "shadow",
        "status": "running",
        "started_at": "2026-04-18T02:29:38+00:00",
        "last_tick_at": "2026-04-18T03:00:00+00:00",
        "novel_total": 10,
    }]
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        runs = client.list_runs()
    assert len(runs) == 1
    assert runs[0]["engine"] == "millennium"


def test_circuit_opens_after_3_fails(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    with patch("urllib.request.urlopen", side_effect=OSError("conn refused")):
        for _ in range(3):
            with pytest.raises(OSError):
                client.list_runs()
        # 4ª chamada: circuito aberto
        with pytest.raises(CircuitOpen):
            client.list_runs()


def test_circuit_closes_after_timeout(cfg, tmp_cache, monkeypatch):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    client._breaker_open_until = time.time() - 1  # expired
    client._consecutive_failures = 3
    with patch("urllib.request.urlopen", return_value=_fake_response([])):
        runs = client.list_runs()
    assert runs == []
    assert client._consecutive_failures == 0


def test_cache_saves_on_success(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    body = [{
        "run_id": "r1", "engine": "millennium", "mode": "shadow",
        "status": "running",
        "started_at": "2026-04-18T02:29:38+00:00",
        "last_tick_at": None, "novel_total": 0,
    }]
    with patch("urllib.request.urlopen", return_value=_fake_response(body)):
        client.list_runs()
    cached = tmp_cache / "runs.json"
    assert cached.exists()


def test_get_heartbeat_uses_run_id(cfg, tmp_cache):
    client = CockpitClient(cfg, cache_dir=tmp_cache)
    hb = {
        "run_id": "r1", "status": "running",
        "ticks_ok": 5, "ticks_fail": 0, "novel_total": 100,
        "last_tick_at": "2026-04-18T03:00:00+00:00",
        "last_error": None, "tick_sec": 900,
    }
    with patch("urllib.request.urlopen", return_value=_fake_response(hb)) as mock:
        got = client.get_heartbeat("r1")
    assert got["ticks_ok"] == 5
    # Verifica que a URL contém o run_id
    req = mock.call_args[0][0]
    assert "r1/heartbeat" in req.full_url


def test_drop_kill_requires_admin_token(cfg, tmp_cache):
    # Client sem admin_token → drop_kill levanta
    cfg_no_admin = CockpitConfig(
        base_url=cfg.base_url,
        read_token=cfg.read_token,
        admin_token=None,
        timeout_sec=cfg.timeout_sec,
    )
    client = CockpitClient(cfg_no_admin, cache_dir=tmp_cache)
    with pytest.raises(PermissionError):
        client.drop_kill("r1")
```

- [ ] **Step 2: Run (fail)**

```bash
python -m pytest tests/test_cockpit_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: launcher_support.cockpit_client`.

- [ ] **Step 3: Implement client**

Create `launcher_support/cockpit_client.py`:

```python
"""Typed HTTP client para o Aurum Cockpit API.

Zero dependências externas (usa urllib.request stdlib). Circuit breaker
fecha o canal após 3 falhas consecutivas; reabre após 300s. Cache local
em cache_dir preserva último estado conhecido pra fallback offline.

Uso típico (singleton no launcher):

    cfg = CockpitConfig(base_url="http://localhost:8787",
                        read_token="...", admin_token="...")
    client = CockpitClient(cfg, cache_dir=Path("data/.cockpit_cache"))
    for run in client.list_runs():
        ...
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class CockpitConfig:
    base_url: str
    read_token: str
    admin_token: str | None = None
    timeout_sec: float = 5.0
    poll_interval_sec: float = 5.0


class CircuitOpen(RuntimeError):
    """Raised quando o breaker tá aberto — caller deve usar cache."""


@dataclass
class CockpitClient:
    cfg: CockpitConfig
    cache_dir: Path
    _consecutive_failures: int = 0
    _breaker_open_until: float = 0.0
    _BREAKER_THRESHOLD: int = 3
    _BREAKER_TIMEOUT_SEC: float = 300.0

    def __post_init__(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ─── Public API ────────────────────────────────────────────

    def healthz(self) -> dict:
        return self._get("/v1/healthz", auth=False)

    def list_runs(self) -> list[dict]:
        runs = self._get("/v1/runs")
        self._save_cache("runs.json", runs)
        return runs

    def get_run(self, run_id: str) -> dict:
        data = self._get(f"/v1/runs/{run_id}")
        self._save_cache(f"run_{run_id}.json", data)
        return data

    def get_heartbeat(self, run_id: str) -> dict:
        hb = self._get(f"/v1/runs/{run_id}/heartbeat")
        self._save_cache(f"heartbeat_{run_id}.json", hb)
        return hb

    def get_trades(self, run_id: str, limit: int = 50,
                   since: str | None = None) -> dict:
        qs = f"?limit={limit}"
        if since:
            qs += f"&since={since}"
        return self._get(f"/v1/runs/{run_id}/trades{qs}")

    def drop_kill(self, run_id: str) -> dict:
        if not self.cfg.admin_token:
            raise PermissionError("admin_token não configurado em CockpitConfig")
        return self._post(f"/v1/runs/{run_id}/kill", admin=True)

    def latest_run(self, engine: str) -> dict | None:
        """Helper: retorna o summary mais recente pro engine, ou None."""
        try:
            runs = self.list_runs()
        except (OSError, CircuitOpen, urllib.error.URLError):
            runs = self._load_cache("runs.json") or []
        for r in runs:
            if r.get("engine") == engine:
                return r
        return None

    # ─── Internals ─────────────────────────────────────────────

    def _check_breaker(self) -> None:
        if self._breaker_open_until > time.time():
            raise CircuitOpen(
                f"breaker open for {self._breaker_open_until - time.time():.0f}s more"
            )
        if self._breaker_open_until != 0 and self._breaker_open_until <= time.time():
            # Half-open: reset counter, tenta 1 request
            self._consecutive_failures = 0
            self._breaker_open_until = 0.0

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._BREAKER_THRESHOLD:
            self._breaker_open_until = time.time() + self._BREAKER_TIMEOUT_SEC

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._breaker_open_until = 0.0

    def _request(self, path: str, method: str = "GET",
                 auth: bool = True, admin: bool = False) -> dict | list:
        self._check_breaker()
        url = self.cfg.base_url.rstrip("/") + path
        headers = {}
        if auth:
            token = self.cfg.admin_token if admin else self.cfg.read_token
            if admin and not self.cfg.admin_token:
                raise PermissionError("admin_token required")
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout_sec) as resp:
                body = resp.read().decode("utf-8")
                result = json.loads(body) if body else {}
                self._record_success()
                return result
        except (urllib.error.URLError, OSError, TimeoutError):
            self._record_failure()
            raise

    def _get(self, path: str, auth: bool = True) -> dict | list:
        return self._request(path, method="GET", auth=auth)

    def _post(self, path: str, admin: bool = False) -> dict:
        result = self._request(path, method="POST", auth=True, admin=admin)
        return result if isinstance(result, dict) else {}

    # ─── Cache ──────────────────────────────────────────────────

    def _save_cache(self, fname: str, data: object) -> None:
        try:
            (self.cache_dir / fname).write_text(json.dumps(data, default=str), encoding="utf-8")
        except OSError:
            pass

    def _load_cache(self, fname: str) -> object | None:
        path = self.cache_dir / fname
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_cockpit_client.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Add .gitignore entry**

Edit `.gitignore`, add line:

```
data/.cockpit_cache/
```

- [ ] **Step 6: Commit**

```bash
git add launcher_support/cockpit_client.py tests/test_cockpit_client.py .gitignore
git commit -m "feat(cockpit): typed HTTP client com circuit breaker + cache

Zero deps novas (urllib.request stdlib). 3 falhas consecutivas abrem
circuito por 300s; half-open após timeout. Cache local em
data/.cockpit_cache/ preserva último estado pra graceful degrade.
drop_kill requer admin_token explícito (PermissionError senão).
"
```

---

## Task 7: Launcher integration — wire painel ao client

**Files:**
- Modify: `launcher_support/engines_live_view.py` (linhas ~1041–1095, ~1170–1180)

### Abordagem

Não quebrar o painel quando API ausente / tunnel caído. Client é singleton lazy: carrega config de `config/keys.json` → bloco `cockpit_api`; se ausente, retorna None → fallback pro disco local.

- [ ] **Step 1: Add client singleton helper**

Edit `launcher_support/engines_live_view.py`. Encontre a função `_find_latest_shadow_run` (linha ~1041). **Antes** dela, adicionar:

```python
_COCKPIT_CLIENT_SINGLETON: object | None = None


def _get_cockpit_client():
    """Lazy singleton. Returns None se config ausente."""
    global _COCKPIT_CLIENT_SINGLETON
    if _COCKPIT_CLIENT_SINGLETON is not None:
        return _COCKPIT_CLIENT_SINGLETON or None  # False-y sentinel = don't retry
    keys_path = Path("config/keys.json")
    if not keys_path.exists():
        _COCKPIT_CLIENT_SINGLETON = False
        return None
    try:
        import json as _json
        data = _json.loads(keys_path.read_text(encoding="utf-8"))
        block = data.get("cockpit_api")
        if not block or not block.get("base_url") or not block.get("read_token"):
            _COCKPIT_CLIENT_SINGLETON = False
            return None
        from launcher_support.cockpit_client import CockpitClient, CockpitConfig
        cfg = CockpitConfig(
            base_url=block["base_url"],
            read_token=block["read_token"],
            admin_token=block.get("admin_token"),
            timeout_sec=float(block.get("timeout_sec", 5.0)),
        )
        _COCKPIT_CLIENT_SINGLETON = CockpitClient(cfg, cache_dir=Path("data/.cockpit_cache"))
        return _COCKPIT_CLIENT_SINGLETON
    except Exception:
        _COCKPIT_CLIENT_SINGLETON = False
        return None
```

- [ ] **Step 2: Modify `_find_latest_shadow_run` to try client first**

Replace the existing `_find_latest_shadow_run` body with:

```python
def _find_latest_shadow_run() -> tuple[Path, dict] | None:
    """Return (run_dir, heartbeat_payload) for the most recent shadow run.

    Try cockpit_api client first (remoto via tunnel). Se ausente ou falha,
    cai pro disco local (dev / shadow rodando na mesma máquina).
    """
    # Remote path via cockpit API
    client = _get_cockpit_client()
    if client is not None:
        try:
            run = client.latest_run(engine="millennium")
            if run:
                # Build a virtual run_dir for compatibility with the existing
                # panel. The run_id doubles as the directory name; STOP button
                # later uses _is_remote_run to route through the client.
                virtual_dir = Path(f"remote://{run['run_id']}")
                hb = client.get_heartbeat(run["run_id"])
                return virtual_dir, hb
        except Exception:
            # Circuit open ou qualquer outro erro → fallback local silencioso
            pass

    # Local disk fallback (layout existente)
    root = Path("data/millennium_shadow")
    if not root.exists():
        return None
    latest: tuple[float, Path, dict] | None = None
    for sub in root.iterdir():
        if not sub.is_dir():
            continue
        hb = sub / "state" / "heartbeat.json"
        if not hb.exists():
            continue
        try:
            import json as _json
            payload = _json.loads(hb.read_text(encoding="utf-8"))
        except Exception:
            continue
        mtime = hb.stat().st_mtime
        if latest is None or mtime > latest[0]:
            latest = (mtime, sub, payload)
    if latest is None:
        return None
    return latest[1], latest[2]


def _is_remote_run(run_dir: Path) -> bool:
    return str(run_dir).startswith("remote://")


def _remote_run_id(run_dir: Path) -> str:
    return str(run_dir).removeprefix("remote://")
```

- [ ] **Step 3: Update STOP button to route remote vs local**

Antes de editar: **lê o `_drop_shadow_kill` original** (linhas ~1072–1090) pra anotar exatamente como ele reporta status (provavelmente via `launcher.app_state.set_status(...)` ou `launcher._set_status(...)` ou similar). Preserva EXATO esse mesmo canal pros dois caminhos (remote e local).

Esqueleto a seguir — substitui `<REPORT>(text, fg)` pela forma real que a função já usa:

```python
def _drop_shadow_kill(run_dir: Path, launcher, state) -> None:
    """Drop a `.kill` flag. Remote runs route via cockpit client."""
    if _is_remote_run(run_dir):
        client = _get_cockpit_client()
        if client is None or not getattr(client.cfg, "admin_token", None):
            <REPORT>(text="SHADOW KILL: admin_token ausente em keys.json", fg=RED)
            return
        try:
            client.drop_kill(_remote_run_id(run_dir))
            <REPORT>(text=f"SHADOW KILL dispatched ({_remote_run_id(run_dir)})", fg=AMBER)
        except Exception as exc:
            <REPORT>(text=f"SHADOW KILL fail: {type(exc).__name__}", fg=RED)
        return

    # Local path — mantém lógica original do arquivo
    try:
        (run_dir / ".kill").touch()
    except Exception as exc:
        <REPORT>(text=f"SHADOW KILL fail: {type(exc).__name__}", fg=RED)
        return
    <REPORT>(text=f"SHADOW KILL flag dropped ({run_dir.name})", fg=AMBER)
```

**Regra:** se o original chama `launcher.some_method(...)`, preserva. Se chama `state["cb"](text=..., fg=...)`, preserva. Não inventa canal novo — reusa o existente.

- [ ] **Step 4: Update `_render_shadow_panel` display of RUN line to prefer manifest run_id**

Find line ~1165 (`tk.Label(shadow, text=f"RUN {hb.get('run_id','?')}..."`).

Replace with (keeping the rest identical):

```python
    run_label = hb.get("run_id", "?")
    last = hb.get("last_tick_at") or hb.get("stopped_at") or "—"
    source = "REMOTE" if _is_remote_run(run_dir) else "LOCAL"
    tk.Label(shadow,
             text=f"[{source}]  RUN {run_label}  ·  last {last}",
             fg=DIM, bg=BG2, font=(FONT, 7), anchor="w").pack(
                 fill="x", padx=10, pady=(0, 4))
```

- [ ] **Step 5: Run full suite**

```bash
python -m pytest -q 2>&1 | tail -3
```

Expected: 1141+ passed (zero new failures from edits).

- [ ] **Step 6: Commit**

```bash
git add launcher_support/engines_live_view.py
git commit -m "feat(launcher): shadow panel ciente de cockpit API remoto

_find_latest_shadow_run tenta o client HTTP antes do disco local.
Painel mostra badge [REMOTE] vs [LOCAL]. STOP SHADOW roteia via
client.drop_kill() pra runs remotos; local permanece inalterado.
Fallback silencioso quando config ausente ou tunnel caído.
"
```

---

## Task 8: systemd unit + installer

**Files:**
- Create: `deploy/aurum_cockpit_api.service`
- Create: `deploy/install_cockpit_api_vps.sh`

- [ ] **Step 1: Create systemd unit**

Create `deploy/aurum_cockpit_api.service`:

```ini
[Unit]
Description=AURUM · Cockpit API (read-only telemetry for shadow/paper/live runners)
Documentation=file:///srv/aurum.finance/docs/superpowers/specs/2026-04-18-cockpit-api-fase1a-design.md
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/srv/aurum.finance

Environment=PYTHONUNBUFFERED=1
Environment=AURUM_COCKPIT_DATA_ROOT=/srv/aurum.finance/data
Environment=AURUM_COCKPIT_BIND_HOST=127.0.0.1
Environment=AURUM_COCKPIT_BIND_PORT=8787
EnvironmentFile=/etc/aurum/cockpit_api.env

ExecStart=/usr/bin/python3 tools/cockpit_api.py

Restart=on-failure
RestartSec=10s
TimeoutStopSec=20

MemoryMax=512M
CPUQuota=100%

NoNewPrivileges=yes
ProtectSystem=strict
ReadOnlyPaths=/srv/aurum.finance
ReadWritePaths=/srv/aurum.finance/data
PrivateTmp=yes

StandardOutput=journal
StandardError=journal
SyslogIdentifier=aurum-cockpit-api

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create installer**

Create `deploy/install_cockpit_api_vps.sh`:

```bash
#!/usr/bin/env bash
# AURUM · installer pro Cockpit API no VPS.
# Uso:  bash deploy/install_cockpit_api_vps.sh [/srv/aurum.finance] [root]
set -euo pipefail

REPO_PATH="${1:-/srv/aurum.finance}"
SERVICE_USER="${2:-$(whoami)}"
UNIT_SRC="${REPO_PATH}/deploy/aurum_cockpit_api.service"
UNIT_DST="/etc/systemd/system/aurum_cockpit_api.service"
ENV_DIR="/etc/aurum"
ENV_FILE="${ENV_DIR}/cockpit_api.env"

echo "=== AURUM cockpit_api installer ==="
echo "  repo:  ${REPO_PATH}"
echo "  user:  ${SERVICE_USER}"
echo

if [ ! -d "${REPO_PATH}" ]; then
  echo "ERRO: ${REPO_PATH} nao existe." >&2
  exit 1
fi
if [ ! -f "${UNIT_SRC}" ]; then
  echo "ERRO: unit nao encontrada em ${UNIT_SRC}. Atualize o repo." >&2
  exit 1
fi

# 1/7: smoke — imports OK
echo "[1/7] smoke: python3 -c 'from tools.cockpit_api import build_app'"
(cd "${REPO_PATH}" && python3 -c "
import os
os.environ.setdefault('AURUM_COCKPIT_READ_TOKEN','dummy')
os.environ.setdefault('AURUM_COCKPIT_ADMIN_TOKEN','dummy')
from tools.cockpit_api import build_app
build_app()
") && echo "  OK"

# 2/7: dir /etc/aurum
echo "[2/7] mkdir -p ${ENV_DIR}"
sudo mkdir -p "${ENV_DIR}"

# 3/7: gera tokens (se env file nao existir)
if [ ! -f "${ENV_FILE}" ]; then
  echo "[3/7] gerando tokens em ${ENV_FILE}"
  READ_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  ADMIN_TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
  sudo tee "${ENV_FILE}" >/dev/null <<EOF
AURUM_COCKPIT_READ_TOKEN=${READ_TOKEN}
AURUM_COCKPIT_ADMIN_TOKEN=${ADMIN_TOKEN}
EOF
  sudo chmod 600 "${ENV_FILE}"
  echo "  OK (tokens novos — vais precisar copiar pro launcher local)"
else
  echo "[3/7] ${ENV_FILE} ja existe — preservando tokens existentes"
fi

# 4/7: instala unit
echo "[4/7] instalando ${UNIT_DST}"
sed \
  -e "s|^User=.*|User=${SERVICE_USER}|" \
  -e "s|^WorkingDirectory=.*|WorkingDirectory=${REPO_PATH}|" \
  "${UNIT_SRC}" | sudo tee "${UNIT_DST}" >/dev/null

# 5/7: reload
echo "[5/7] systemctl daemon-reload"
sudo systemctl daemon-reload

# 6/7: enable + start
echo "[6/7] systemctl enable + start"
sudo systemctl enable aurum_cockpit_api.service
sudo systemctl restart aurum_cockpit_api.service

# 7/7: probe
sleep 3
echo "[7/7] probe /v1/healthz"
READ_TOKEN_FROM_ENV=$(sudo grep '^AURUM_COCKPIT_READ_TOKEN=' "${ENV_FILE}" | cut -d= -f2-)
curl -sf http://127.0.0.1:8787/v1/healthz | python3 -m json.tool

echo
echo "=== tudo pronto ==="
echo "  Tokens:  sudo cat ${ENV_FILE}"
echo "  Logs:    sudo journalctl -u aurum_cockpit_api.service -f"
echo "  Probe:   curl -sH \"Authorization: Bearer \$READ\" localhost:8787/v1/runs"
echo "  Stop:    sudo systemctl stop aurum_cockpit_api.service"
```

- [ ] **Step 3: chmod + commit**

```bash
chmod +x deploy/install_cockpit_api_vps.sh
git add deploy/aurum_cockpit_api.service deploy/install_cockpit_api_vps.sh
git commit -m "feat(deploy): cockpit API systemd unit + installer one-shot

Unit tightened (ProtectSystem=strict, ReadOnlyPaths=/srv/aurum.finance,
ReadWritePaths=/srv/aurum.finance/data). Installer gera tokens via
secrets.token_hex(32) em /etc/aurum/cockpit_api.env 0600; preserva
existentes se já geradas. Probe final faz curl no healthz.
"
```

---

## Task 9: Deploy + smoke end-to-end

**Files:** nenhum (ops-only)

Este task é executado MANUALMENTE pelo João. Claude documenta e valida que os passos funcionam.

- [ ] **Step 1: Merge worktree → feat/phi-engine**

No repo principal (não no worktree):

```bash
cd /c/Users/Joao/OneDrive/aurum.finance
git merge feat/cockpit-api --no-ff -m "merge: cockpit API fase 1a"
git push origin feat/phi-engine
```

- [ ] **Step 2: VPS — pull e instalar**

```bash
ssh root@vmi3200601
cd /srv/aurum.finance
git pull origin feat/phi-engine
bash deploy/install_cockpit_api_vps.sh /srv/aurum.finance root
```

Expected: probe `/v1/healthz` retorna `{"status":"ok", "version":"1.0.0", ...}`.

- [ ] **Step 3: VPS — copia tokens**

```bash
sudo cat /etc/aurum/cockpit_api.env
```

Copia os dois tokens pro lado de fora (em algum keep seguro, NÃO chat).

- [ ] **Step 4: Windows — edita config/keys.json**

No launcher local, adiciona bloco ao `config/keys.json`:

```json
{
  "demo": {"api_key": "", "api_secret": ""},
  "testnet": {"api_key": "", "api_secret": ""},
  "live": {"api_key": "", "api_secret": ""},
  "telegram": {"bot_token": "...", "chat_id": "..."},
  "cockpit_api": {
    "base_url": "http://localhost:8787",
    "read_token": "<cole aqui o AURUM_COCKPIT_READ_TOKEN>",
    "admin_token": "<cole aqui o AURUM_COCKPIT_ADMIN_TOKEN>",
    "timeout_sec": 5.0
  }
}
```

- [ ] **Step 5: Windows — abre tunnel**

Em terminal separado (PowerShell ou Git Bash):

```bash
ssh -N -L 8787:localhost:8787 root@vmi3200601
```

Deixa rodando. Teste em outro terminal:

```bash
curl -sH "Authorization: Bearer $READ_TOKEN" http://localhost:8787/v1/runs | python -m json.tool
```

Expected: JSON array com pelo menos 1 run (o shadow que já tá rodando lá desde 2026-04-18 02:29).

- [ ] **Step 6: Windows — reabre launcher**

Mata processo launcher (se aberto). Reabre:

```bash
python launcher.py
```

Navega pra ENGINES → MILLENNIUM. Painel SHADOW LOOP deve mostrar:
- Badge [REMOTE]
- Status RUNNING (verde)
- ticks_ok > 1
- last_tick_at recente
- Botão STOP SHADOW ativo

- [ ] **Step 7: Smoke STOP (opcional — destrutivo!)**

Se quiseres validar kill end-to-end, clica STOP SHADOW. Espera até 1 tick (~15min).

Expected no VPS:
```bash
ls /srv/aurum.finance/data/millennium_shadow/2026-04-18_0229/.kill  # exists
sudo systemctl status millennium_shadow.service
# Active: inactive (dead) — exitcode 0
cat /srv/aurum.finance/data/millennium_shadow/2026-04-18_0229/state/heartbeat.json
# status: "stopped"
```

Se sim, restart depois:
```bash
rm /srv/aurum.finance/data/millennium_shadow/2026-04-18_0229/.kill
sudo systemctl start millennium_shadow.service  # cria NOVO run_id
```

- [ ] **Step 8: Documentar em session log + daily log**

Criar `docs/sessions/2026-04-18_<HHMM>.md` + atualizar `docs/days/2026-04-18.md` per regra permanente do CLAUDE.md.

- [ ] **Step 9: Final commit**

```bash
git add docs/sessions/2026-04-18_*.md docs/days/2026-04-18.md
git commit -m "docs(sessions): 2026-04-18 cockpit API fase 1a deployed"
```

---

## Acceptance criteria (revisitado do spec)

- [ ] `/v1/healthz` responde no VPS (Task 9 step 2)
- [ ] `curl /v1/runs` lista run shadow (Task 9 step 5)
- [ ] Painel SHADOW LOOP mostra dados remotos com refresh 5s (Task 9 step 6)
- [ ] Tunnel caído → painel não crasha, fallback local (Task 7 circuit breaker)
- [ ] STOP via admin_token funciona (Task 9 step 7 opcional)
- [ ] `manifest.json` no próximo run tem commit correto (Task 2)
- [ ] Suite pytest 1141+ verde após todos os commits (Task 6 step 6, Task 7 step 5)
- [ ] Zero mudança em `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py` (4 arquivos protegidos por CLAUDE.md):

```bash
git diff feat/phi-engine...feat/cockpit-api --stat -- \
  core/indicators.py core/signals.py core/portfolio.py config/params.py
# Expected: empty output
```

Obs: `core/shadow_contract.py` é arquivo NOVO (criado neste plano) e portanto FORA da lista protegida.

---

## Rollback plan

Se algo quebrar em produção:

1. **Launcher local:** remove bloco `cockpit_api` de `config/keys.json` → volta ao shadow panel local-only.
2. **VPS API:** `sudo systemctl stop aurum_cockpit_api.service`. Shadow runner continua inalterado (API é pure reader).
3. **Revert branch:** `git revert <merge_sha>` no `feat/phi-engine`.

---

## Post-completion

Após todos os commits e deploy:

- Fase 1b (próxima sessão) — tabela "últimos 10 sinais" no painel
- Fase 1c — `tools/shadow_audit.py` carrega trades via client pra DF + compara com backtest
- Fase 1b extra — auto-tunnel gerenciado pelo launcher

Nenhum desses é parte de 1a.
