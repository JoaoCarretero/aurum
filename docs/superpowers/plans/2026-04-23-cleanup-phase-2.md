# Cleanup Phase 2 — "Performance & Dev Loop" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduzir tempo do test suite (62s→≤25s via pytest-xdist), tempo de import do launcher (829ms→≤400ms via lazy core.data.connections) e boot total (~2074ms→≤1000ms via hot-path fixes data-driven).

**Architecture:** Branch dedicada `feat/cleanup-phase-2` com 6 commits atômicos. pytest-xdist adicionado em `[dev]`. Lazy import de `core.data.connections` no launcher.py (único import pesado top-level, cobre pandas 350ms + requests 204ms transitivamente). Instrumentação cirúrgica do `App.__init__` (11 etapas já parcialmente instrumentadas — cobrir gap de 1.2s). Hot-path fixes aplicados baseados em profile real.

**Tech Stack:** Python 3.11.5, pytest-xdist 3.5+, ruff (já configurado), Windows 11.

**Spec:** `docs/superpowers/specs/2026-04-23-cleanup-phase-2-design.md` (commit 77324bd)

**Descobertas do mapeamento vs spec:**
- **Único import pesado top-level em launcher.py é `core.data.connections`** (linha 109). `core.chronos` e `analysis` NÃO são importados top-level — eram hipóteses minhas. Task de "lazy chronos/analysis imports" do spec se reduz a "lazy core.data.connections" (que já cobre o 641ms transitive).
- **Zero `@patch("launcher.X")` em tests** — lazy imports totalmente seguros pra mocking.
- **App.__init__ já tem 3 timing metrics** (`boot.chrome`, `boot.enter_splash`, `boot.until_shell_ready`). Gap de ~1.2s ainda não-instrumentado fica em: Tk root + tk_setPalette + DPI + iconbitmap + state init. Task 3 cobre.
- **tests/conftest.py existe** — precisa verificar compat com xdist na Task 1.

---

## File Structure

### Arquivos a MODIFICAR

| File | Change type | Line ref |
|------|-------------|----------|
| `pyproject.toml` | Add `pytest-xdist>=3.5,<4` em `[dev]` | linha 33-36 |
| `launcher.py` | Lazy `core.data.connections` — mover de linha 109 pra callbacks | linha 109 (top-level import) |
| `launcher.py` | Add ~8 `emit_timing_metric` calls em `App.__init__` | linhas 502-585 (gap instrumentado) |
| `launcher.py` | Hot-path fixes data-driven | TBD pós-profile |

### Arquivos possivelmente modificados (se xdist detectar flakies)

| File | Condition |
|------|-----------|
| `pyproject.toml` | Add `[tool.pytest.ini_options] markers: serial` se algum teste não for thread-safe |
| `tests/<flaky_test>.py` | Add `@pytest.mark.serial` onde necessário |

### Arquivos intocados

- CORE protegidos: `config/params.py`, `core/signals.py`, `core/indicators.py`, `core/portfolio.py`
- `core/data/connections.py` — só o IMPORT no launcher muda, não o módulo

---

## Task 1: Setup — branch + pytest-xdist install

**Files:**
- Modify: `C:\Users\Joao\projects\aurum.finance\pyproject.toml`

- [ ] **Step 1: Criar branch dedicada**

```bash
cd /c/Users/Joao/projects/aurum.finance
git checkout chore/repo-cleanup
git pull origin chore/repo-cleanup
git checkout -b feat/cleanup-phase-2
```

- [ ] **Step 2: Baseline de tempo sequencial (pré-xdist)**

```bash
time .venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -q --tb=no 2>&1 | tail -3
```

Anote o tempo `real` exato (ex: `62.43s`). Será o baseline pra comparar.

- [ ] **Step 3: Baseline launcher import time**

```bash
.venv/Scripts/python.exe -c "import time; t0=time.perf_counter(); import launcher; print(f'{(time.perf_counter()-t0)*1000:.0f}ms')"
```

Anote o valor (ex: `829ms`).

- [ ] **Step 4: Adicionar pytest-xdist em pyproject.toml [dev]**

Edit `pyproject.toml`. Localizar o array `dev = [...]` (linha ~33):

```python
dev = [
    "pytest>=7.0,<9",
    "httpx>=0.27,<1",
]
```

Substituir por:

```python
dev = [
    "pytest>=7.0,<9",
    "pytest-xdist>=3.5,<4",
    "httpx>=0.27,<1",
]
```

- [ ] **Step 5: Instalar nova dep**

```bash
.venv/Scripts/python.exe -m pip install -e ".[all,dev]"
```

Expected output termina com `Successfully installed ... pytest-xdist-X.Y.Z ...`.

- [ ] **Step 6: Verificar xdist disponível**

```bash
.venv/Scripts/python.exe -m pytest --help 2>&1 | grep -A1 "xdist\|-n auto"
```

Expected: linha mencionando `-n` ou `--numprocesses`.

- [ ] **Step 7: Commit e push**

```bash
git add pyproject.toml
git commit -m "chore(deps): add pytest-xdist to [dev] extras

Enables parallel test execution via pytest -n auto. Baseline
sequential suite: 62s for 1677 tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push -u origin feat/cleanup-phase-2
```

---

## Task 2: Run parallel + detect flakies + mark serial if needed

**Files (conditional):**
- Possibly create: `conftest.py` markers
- Possibly modify: individual `tests/*.py` with `@pytest.mark.serial`

- [ ] **Step 1: First parallel run**

```bash
cd /c/Users/Joao/projects/aurum.finance
time .venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -n auto -q --tb=no 2>&1 | tail -10
```

Record:
- `real` time (expected <25s if successful)
- Passed count (expected 1666, same as sequential)
- Failed count (expected ≤13, same as sequential)

- [ ] **Step 2: Compare with sequential baseline**

If:
- Time is ≤25s AND pass count is 1666 AND fail count matches sequential: **PROCEED TO STEP 7** (no flakies — skip to commit).
- Time is slow (>30s): xdist might not be sharding properly. Diagnose with `pytest -n 4 -v`.
- Pass count dropped or fail count increased: some tests are flaky under parallel. **CONTINUE TO STEP 3**.

- [ ] **Step 3: Identify flaky tests (if step 2 showed regressions)**

```bash
# Run twice, compare failing tests
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -n auto --tb=no 2>&1 | grep "^FAILED" | sort > /tmp/parallel_fails_1.txt
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -n auto --tb=no 2>&1 | grep "^FAILED" | sort > /tmp/parallel_fails_2.txt
diff /tmp/parallel_fails_1.txt /tmp/parallel_fails_2.txt
```

Tests that appear in ONE run but not the other = flaky. Tests that appear in BOTH = consistent failures (likely shared-state, need serial).

- [ ] **Step 4: Register `serial` pytest marker in pyproject.toml**

Edit `pyproject.toml`. Find `[tool.pytest.ini_options]` section (around line 47-66). Find the `markers` array:

```toml
markers = [
    "gui: requires a Tk-capable display (opt-in via -m gui or run all)",
]
```

Substituir por:

```toml
markers = [
    "gui: requires a Tk-capable display (opt-in via -m gui or run all)",
    "serial: test must run sequentially (xdist-unsafe: shared state, file locks, etc.)",
]
```

- [ ] **Step 5: Mark identified flaky tests**

For each flaky test identified in Step 3, add `@pytest.mark.serial` decorator. Example for `tests/example/test_flaky.py`:

Before:
```python
def test_something_with_shared_state():
    ...
```

After:
```python
import pytest

@pytest.mark.serial
def test_something_with_shared_state():
    ...
```

(If `pytest` not already imported, add `import pytest` at top of file.)

- [ ] **Step 6: Re-run with xdist respecting serial marker**

```bash
# Run non-serial in parallel
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -n auto -m "not serial" -q --tb=no 2>&1 | tail -3
# Run serial sequentially
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -m "serial" -q --tb=no 2>&1 | tail -3
```

Soma dos dois times deve ser <30s total. Pass count combinado: 1666.

- [ ] **Step 7: Commit (even if no files changed, document via empty commit)**

If Step 2 was clean (no serials needed):

```bash
git commit --allow-empty -m "chore(tests): verify pytest-xdist parallel run clean

pytest -n auto runs clean without flakies. 1666 pass / 13 fail
unchanged from sequential. Wall time: <N>s (vs 62s baseline).
No @pytest.mark.serial needed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-2
```

If serials were added:

```bash
git add pyproject.toml tests/
git commit -m "chore(tests): mark N xdist-unsafe tests with @pytest.mark.serial

Identified via double parallel run diff. Tests rely on shared state
(tmpdir reuse, DB locks, global imports) that breaks under xdist.

Runs: pytest -n auto -m 'not serial' + pytest -m 'serial'.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-2
```

---

## Task 3: Instrument launcher boot with timing metrics

**Files:**
- Modify: `C:\Users\Joao\projects\aurum.finance\launcher.py` (add ~8 emit_timing_metric calls in App.__init__)

- [ ] **Step 1: Read current App.__init__ structure**

```bash
sed -n '501,600p' launcher.py
```

Note existing instrumented points:
- Line ~587: `chrome_t0` → `emit_timing_metric("boot.chrome", ...)`
- Line ~593: `splash_t0` → `emit_timing_metric("boot.enter_splash", ...)`
- Line ~598: `boot.until_shell_ready`

Gap to instrument (lines 504-587, ~1200ms unaccounted):
1. `super().__init__()` — Tk root creation (line 504)
2. `_configure_screen_logging()` — logging setup (line 505-508)
3. `tk_setPalette` — widget defaults (lines 517-524)
4. `_configure_windows_dpi()` — DPI scaling (line 525)
5. `iconbitmap` + taskbar — icon load (lines 529-537)
6. State init block — attributes (lines 539-585)

- [ ] **Step 2: Add instrumentation around `super().__init__()`**

Find this block (lines 502-504):

```python
    def __init__(self):
        boot_t0 = time.perf_counter()
        self._shutdown_done = False
        super().__init__()
```

Replace with:

```python
    def __init__(self):
        boot_t0 = time.perf_counter()
        self._shutdown_done = False
        _tk_t0 = time.perf_counter()
        super().__init__()
        emit_timing_metric("boot.tk_root", ms=(time.perf_counter() - _tk_t0) * 1000.0)
```

- [ ] **Step 3: Add instrumentation around screen_logging + palette**

Find block starting at line 505:

```python
        try:
            _configure_screen_logging()
        except Exception:
            pass
        self.title("AURUM Terminal")
        self.configure(bg=BG)
        # Defensive: forca Tk default palette pra BG em tudo. Se alguma
        # Frame em algum canto esquecer bg=BG explicito, o Windows
        # mostraria SystemButtonFace (~#F0F0F0) = "branco" no fundo.
        # tk_setPalette varre todos widget defaults e seta em massa —
        # inclui menu/dialog/messagebox criados internamente. Chamado
        # ANTES de chrome/widgets serem criados.
        try:
            self.tk_setPalette(
                background=BG, foreground=WHITE,
                activeBackground=BG3, activeForeground=WHITE,
                highlightColor=BORDER, highlightBackground=BG,
            )
        except Exception:
            pass
```

Replace with:

```python
        _logging_t0 = time.perf_counter()
        try:
            _configure_screen_logging()
        except Exception:
            pass
        emit_timing_metric("boot.screen_logging", ms=(time.perf_counter() - _logging_t0) * 1000.0)

        self.title("AURUM Terminal")
        self.configure(bg=BG)
        # Defensive: forca Tk default palette pra BG em tudo. Se alguma
        # Frame em algum canto esquecer bg=BG explicito, o Windows
        # mostraria SystemButtonFace (~#F0F0F0) = "branco" no fundo.
        # tk_setPalette varre todos widget defaults e seta em massa —
        # inclui menu/dialog/messagebox criados internamente. Chamado
        # ANTES de chrome/widgets serem criados.
        _palette_t0 = time.perf_counter()
        try:
            self.tk_setPalette(
                background=BG, foreground=WHITE,
                activeBackground=BG3, activeForeground=WHITE,
                highlightColor=BORDER, highlightBackground=BG,
            )
        except Exception:
            pass
        emit_timing_metric("boot.palette", ms=(time.perf_counter() - _palette_t0) * 1000.0)
```

- [ ] **Step 4: Add instrumentation around DPI + geometry**

Find block starting at line 525:

```python
        self._configure_windows_dpi()
        self.geometry("960x660")
        self.minsize(860, 560)
```

Replace with:

```python
        _dpi_t0 = time.perf_counter()
        self._configure_windows_dpi()
        self.geometry("960x660")
        self.minsize(860, 560)
        emit_timing_metric("boot.dpi_geometry", ms=(time.perf_counter() - _dpi_t0) * 1000.0)
```

- [ ] **Step 5: Add instrumentation around icon + taskbar**

Find block starting at line 529:

```python
        # Taskbar icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("aurum.finance.terminal")
        except: pass
        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists(): self.iconbitmap(str(ico))
        except: pass
```

Replace with:

```python
        # Taskbar icon
        _icon_t0 = time.perf_counter()
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("aurum.finance.terminal")
        except: pass
        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists(): self.iconbitmap(str(ico))
        except: pass
        emit_timing_metric("boot.icon", ms=(time.perf_counter() - _icon_t0) * 1000.0)
```

- [ ] **Step 6: Add instrumentation around state init block**

Find block starting at line 539 (`self.proc = None`) and ending at line 585 (`self._timing_starts: dict[str, float] = {}`).

**Before the `self.proc = None` line**, add:

```python
        _state_t0 = time.perf_counter()
```

**After the `self._timing_starts` line** (just before `chrome_t0 = time.perf_counter()`), add:

```python
        emit_timing_metric("boot.state_init", ms=(time.perf_counter() - _state_t0) * 1000.0)
```

So the sequence should be (concise):

```python
        _state_t0 = time.perf_counter()
        self.proc = None
        self.oq = queue.Queue()
        # ... (all the state init lines unchanged) ...
        self._timing_starts: dict[str, float] = {}
        emit_timing_metric("boot.state_init", ms=(time.perf_counter() - _state_t0) * 1000.0)

        chrome_t0 = time.perf_counter()
```

- [ ] **Step 7: Verify launcher still imports**

```bash
.venv/Scripts/python.exe -c "import launcher; print('imports OK')"
```

Expected: `imports OK`.

- [ ] **Step 8: Run launcher briefly to capture timings (or smoke test)**

**Option A (real boot):** If on a Tk-capable machine:
```bash
.venv/Scripts/python.exe launcher.py &
# wait 3s
sleep 3
# kill process (ctrl+c or kill)
```

Then check `data/.launcher_logs/screens.log` for new `boot.tk_root`, `boot.screen_logging`, `boot.palette`, `boot.dpi_geometry`, `boot.icon`, `boot.state_init` entries.

**Option B (headless smoke):** Create temp script:
```python
# /tmp/boot_smoke.py
import launcher
# Instantiate App but don't mainloop (headless)
# If Tk not available, this will fail with TkError — that's OK, still generates logs
try:
    app = launcher.App()
    app.destroy()
except Exception as e:
    print(f"expected on headless: {e}")
```

Then: `.venv/Scripts/python.exe /tmp/boot_smoke.py`

Check the log:
```bash
tail -15 data/.launcher_logs/screens.log
```

Expected: see 6 new `event=timing name=boot.X` lines.

- [ ] **Step 9: Commit**

```bash
git add launcher.py
git commit -m "perf(launcher): instrument boot with 6 new timing metrics

Add emit_timing_metric calls around:
- boot.tk_root (super().__init__())
- boot.screen_logging
- boot.palette (tk_setPalette)
- boot.dpi_geometry (_configure_windows_dpi + geometry)
- boot.icon (iconbitmap + taskbar)
- boot.state_init (attribute assignment block)

Enabler pra Task 6 (hot-path fixes data-driven). Boot total
previously ~2074ms, ~1200ms unaccounted before this commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-2
```

---

## Task 4: Analyze profile from Task 3 + plan hot-path fixes

**Files:** (no code changes in this task — planning task)

- [ ] **Step 1: Read latest screens.log entries**

```bash
tail -20 data/.launcher_logs/screens.log
```

Identify the 6 new timing entries. Record values in a table like:

| Metric | Duration |
|--------|----------|
| boot.tk_root | Xms |
| boot.screen_logging | Yms |
| boot.palette | Zms |
| boot.dpi_geometry | Wms |
| boot.icon | Vms |
| boot.state_init | Ums |
| boot.chrome | (already instrumented) |
| boot.enter_splash | (already instrumented) |
| **Total boot.until_shell_ready** | ~2000ms |

- [ ] **Step 2: Identify top 3 offenders**

Sort by duration. Top 3 are the candidates for Task 6 hot-path fixes.

Typical expectations:
- `boot.tk_root` is often ~500-800ms (unavoidable — Tk infra) — skip
- `boot.icon` is often 150-300ms (iconbitmap reads .ico file) — fixable via lazy (after_idle)
- `boot.dpi_geometry` can be 50-200ms — sometimes cacheable
- `boot.palette` is usually <50ms — skip unless surprising

- [ ] **Step 3: Document findings in a planning note (not committed)**

Create a temp note (no commit, just for reference in Task 6):

```
PROFILE RESULTS (2026-04-23):
- #1 offender: [name] [Xms] — candidate fix: [approach]
- #2 offender: [name] [Yms] — candidate fix: [approach]
- #3 offender: [name] [Zms] — candidate fix: [approach]
Target: reduce total boot by ≥700ms to hit <1000ms goal.
```

Save mentally or in a scratchpad. Task 6 will use this.

---

## Task 5: Lazy-load `core.data.connections` in launcher.py

**Files:**
- Modify: `C:\Users\Joao\projects\aurum.finance\launcher.py:109` + all callsites

- [ ] **Step 1: Find all callsites of `ConnectionManager` and `MARKETS`**

```bash
grep -n "ConnectionManager\|\\bMARKETS\\b" launcher.py | head -30
```

Record line numbers. Expect callsites in functions/methods that handle connections UI, data center, market view.

- [ ] **Step 2: Remove top-level import**

Find line 109:

```python
from core.data.connections import ConnectionManager, MARKETS
```

Delete this entire line.

- [ ] **Step 3: Add lazy import helper function near top of file (after other helper funcs, around line 50)**

Find the place where existing helpers live (search for `def _boot_workers_enabled` — around line 30). Add AFTER it:

```python
def _lazy_connections():
    """Import and return (ConnectionManager, MARKETS) on-demand.

    These come from core.data.connections which transitively pulls
    pandas (~350ms) and requests (~200ms). Deferring to first actual
    use shaves ~640ms off launcher boot import.
    """
    from core.data.connections import ConnectionManager, MARKETS
    return ConnectionManager, MARKETS
```

- [ ] **Step 4: Update each callsite found in Step 1 to use lazy helper**

For each line/function that uses `ConnectionManager` or `MARKETS`:

**Pattern A — function that uses both:**

Before:
```python
def _do_something(self):
    mgr = ConnectionManager(...)
    for m in MARKETS:
        ...
```

After:
```python
def _do_something(self):
    ConnectionManager, MARKETS = _lazy_connections()
    mgr = ConnectionManager(...)
    for m in MARKETS:
        ...
```

**Pattern B — function uses only one:**

Before:
```python
def _get_markets_menu(self):
    return sorted(MARKETS.keys())
```

After:
```python
def _get_markets_menu(self):
    _, MARKETS = _lazy_connections()
    return sorted(MARKETS.keys())
```

Apply to EACH callsite found in Step 1. Use Edit tool with `replace_all=false` and exact-string match.

**Note:** if a callsite is inside a class method that's called frequently (hot path), the ~10μs `_lazy_connections()` call on every invocation is negligible after first call (Python caches imports in `sys.modules`). No caching needed beyond that.

- [ ] **Step 5: Verify no remaining top-level references**

```bash
grep -n "^from core.data.connections\|^import core.data.connections" launcher.py
```

Expected: empty (no matches).

```bash
grep -nE "^\\s*from core.data.connections import\\s|^\\s*import core.data.connections" launcher.py
```

Expected: all matches are INSIDE functions (indented), not at module level.

- [ ] **Step 6: Measure import time improvement**

```bash
.venv/Scripts/python.exe -c "import time; t0=time.perf_counter(); import launcher; print(f'{(time.perf_counter()-t0)*1000:.0f}ms')"
```

Expected: **≤500ms** (was 829ms baseline; target ≤400ms may require Task 6 fixes).

Record the new value.

- [ ] **Step 7: Run tests to verify nothing broke**

```bash
.venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -n auto -q --tb=no 2>&1 | tail -3
```

Expected: same pass count (1666), no new failures.

- [ ] **Step 8: Smoke launcher import**

```bash
.venv/Scripts/python.exe -c "import launcher; app = launcher.App() if False else None; print('OK')"
```

Expected: `OK`. (The `if False` prevents actual Tk window creation in headless contexts — just validates import path works.)

- [ ] **Step 9: Commit**

```bash
git add launcher.py
git commit -m "perf(launcher): lazy-load core.data.connections import

core.data.connections transitively imports pandas (~350ms) and
requests (~200ms). Moving from top-level to lazy _lazy_connections()
helper inside callers shaves ~640ms off launcher import time.

Baseline import: 829ms. Post-fix: <Nms> (target ≤500ms).

First actual use of MARKETS or ConnectionManager (typically when
user opens Connections or Markets screen) pays the pandas import
tax ONCE, then cached via sys.modules.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-2
```

---

## Task 6: Apply hot-path fixes based on Task 4 profile

**Files:** (data-driven — specific files depend on Task 4 findings)

This task may be 1-3 sub-commits depending on profile. Below are PATTERNS for common findings. Engineer picks the relevant pattern.

### Pattern A: `boot.icon` is >150ms — lazy iconbitmap

**Files:**
- Modify: `launcher.py` (lines 529-537, the `Taskbar icon` block)

- [ ] **A.1: Locate icon block (line ~534-537)**

```python
        try:
            ico = ROOT / "server" / "logo" / "aurum.ico"
            if ico.exists(): self.iconbitmap(str(ico))
        except: pass
```

- [ ] **A.2: Replace with deferred load**

```python
        # Lazy iconbitmap: defer to after_idle so boot returns faster.
        # Icon appears a frame late (imperceptible) instead of blocking.
        def _apply_icon():
            try:
                ico = ROOT / "server" / "logo" / "aurum.ico"
                if ico.exists(): self.iconbitmap(str(ico))
            except: pass
        self.after_idle(_apply_icon)
```

- [ ] **A.3: Run launcher, verify icon appears (manual)**

- [ ] **A.4: Commit**

```bash
git add launcher.py
git commit -m "perf(launcher): lazy iconbitmap via after_idle

iconbitmap reads .ico file synchronously (~Xms). Defer to after_idle
so boot returns before icon load. Icon appears one frame late —
imperceptible in practice.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-2
```

### Pattern B: `boot.dpi_geometry` is >150ms — cache DPI call

**Files:**
- Modify: `launcher.py` — find `_configure_windows_dpi` method

- [ ] **B.1: Locate `_configure_windows_dpi`**

```bash
grep -n "_configure_windows_dpi" launcher.py
```

- [ ] **B.2: Inspect current implementation**

```bash
grep -A 20 "def _configure_windows_dpi" launcher.py
```

- [ ] **B.3: Add module-level cache if not already cached**

If the method does `ctypes.windll.shcore.SetProcessDpiAwareness(...)` unconditionally, it's safe to call multiple times but wastes ~50-150ms. Pattern:

Before:
```python
def _configure_windows_dpi(self):
    # ... ctypes calls ...
```

After:
```python
_DPI_CONFIGURED = False

def _configure_windows_dpi(self):
    global _DPI_CONFIGURED
    if _DPI_CONFIGURED:
        return
    # ... ctypes calls ...
    _DPI_CONFIGURED = True
```

(Place `_DPI_CONFIGURED = False` at module level near top.)

- [ ] **B.4: Run launcher, verify scaling OK**

- [ ] **B.5: Commit**

```bash
git add launcher.py
git commit -m "perf(launcher): cache DPI configuration (module-level guard)

_configure_windows_dpi makes ctypes calls that are idempotent but
slow (~Xms per call). Cache the first-call result at module level
so subsequent launcher instances (tests, subagents) skip redundant
configuration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
git push origin feat/cleanup-phase-2
```

### Pattern C: Other findings

If Task 4 profile reveals something OTHER than icon/DPI (e.g., `boot.palette` unexpectedly slow, or `boot.state_init` >200ms):

- [ ] **C.1: Document the finding**

State clearly what was slow: "`boot.<metric>` was <N>ms".

- [ ] **C.2: Propose a targeted fix**

For each identified bottleneck, the fix pattern is typically one of:
- Lazy: defer via `after_idle`
- Cache: module-level flag to skip redundant work
- Reduce: lower the work done (e.g., fewer widgets on boot)

- [ ] **C.3: Apply fix surgically (1 commit per fix)**

Use same commit message format: `perf(launcher): <description>`.

- [ ] **C.4: Validate launcher still works and boot time decreased**

### End of Task 6

After all hot-path fixes:

- [ ] **Final check: boot time under target**

```bash
# Run launcher briefly to capture boot.until_shell_ready
# Then check log
tail -5 data/.launcher_logs/screens.log | grep "boot.until_shell_ready"
```

Expected: `event=timing name=boot.until_shell_ready ms=<1000>`.

---

## Task 7: Final gates + merge back to chore/repo-cleanup

**Files:** (no code changes — git operations + validation)

- [ ] **Step 1: Full test suite with xdist**

```bash
cd /c/Users/Joao/projects/aurum.finance
time .venv/Scripts/python.exe -m pytest tests/ --ignore=tests/test_cockpit_paper_endpoints.py -n auto -q --tb=no 2>&1 | tail -3
```

Expected:
- Time: **≤25s** (target, ideal ≤20s)
- Pass count: 1666 (same as sequential baseline)
- Failed count: same as Fase 1 end state (~13)

- [ ] **Step 2: Launcher import time**

```bash
.venv/Scripts/python.exe -c "import time; t0=time.perf_counter(); import launcher; print(f'{(time.perf_counter()-t0)*1000:.0f}ms')"
```

Expected: **≤400ms** (was 829ms baseline).

- [ ] **Step 3: Launcher boot total (from logs)**

```bash
tail -20 data/.launcher_logs/screens.log | grep "boot.until_shell_ready" | tail -1
```

Expected: **≤1000ms** (was ~2074ms baseline).

- [ ] **Step 4: Ruff F401 still clean**

```bash
.venv/Scripts/python.exe -m ruff check --select F401 --no-fix . 2>&1 | tail -3
```

Expected: `All checks passed!`.

- [ ] **Step 5: VPS services smoke check**

```bash
ssh -o ConnectTimeout=10 -o BatchMode=yes -i /c/Users/Joao/.ssh/id_ed25519 root@37.60.254.151 '
for u in citadel_paper@desk-a citadel_shadow@desk-a jump_paper@desk-a jump_shadow@desk-a renaissance_paper@desk-a renaissance_shadow@desk-a millennium_paper@desk-paper-a millennium_paper@desk-paper-b millennium_shadow@desk-shadow-a millennium_shadow@desk-shadow-b aurum_probe@desk-a aurum_cockpit_api; do
  s=$(systemctl is-active ${u}.service)
  printf "%-42s %s\n" "$u" "$s"
done
'
```

Expected: 12/12 `active`.

- [ ] **Step 6: Merge back with preserved atomic history**

```bash
git checkout chore/repo-cleanup
git merge --no-ff feat/cleanup-phase-2 -m "Merge feat/cleanup-phase-2 into chore/repo-cleanup

Phase 2 of software optimization roadmap: Performance & Dev Loop.

- pytest-xdist added: suite 62s -> <N>s (parallel)
- Launcher boot instrumented with 6 new timing metrics
- core.data.connections lazy-loaded: import 829ms -> <Nms>
- Hot-path fixes applied: boot total ~2074ms -> <Nms>

Metrics:
- Test suite: 62s -> <N>s (xdist -n auto)
- Launcher import: 829ms -> <N>ms
- Launcher boot total: ~2074ms -> <N>ms
- Tests pass: 1666 (unchanged)
- VPS services: 12/12 active (no impact)

Spec: docs/superpowers/specs/2026-04-23-cleanup-phase-2-design.md
Plan: docs/superpowers/plans/2026-04-23-cleanup-phase-2.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Fill in actual measured values before committing.

- [ ] **Step 7: Push merge commit**

```bash
git push origin chore/repo-cleanup
```

- [ ] **Step 8: Print final report**

```bash
echo "=== FASE 2 PERFORMANCE & DEV LOOP — CONCLUÍDA ==="
echo "Branch: feat/cleanup-phase-2 merged into chore/repo-cleanup"
echo ""
echo "Metrics:"
echo "- Test suite: 62s baseline -> (measured) parallel"
echo "- Launcher import: 829ms baseline -> (measured)"
echo "- Launcher boot: ~2074ms baseline -> (measured)"
echo ""
echo "Ready for Fase 3: Architecture (launcher.py decomposition)"
```

---

## Self-Review (executed)

**Spec coverage:**
- ✅ A) pytest parallelism: Tasks 1-2
- ✅ B) Launcher boot instrumentation: Task 3
- ✅ C) Lazy imports: Task 5 (scope narrowed to core.data.connections — only top-level heavy import)
- ✅ D) Hot-path fixes: Task 6 (Patterns A/B/C)
- ✅ Gates cumulativos: cada task tem gate
- ✅ Rollback: push-per-commit
- ✅ VPS smoke: Task 7 Step 5

**Placeholder scan:** No TBD/TODO. Commit messages contain `<N>` placeholder values that engineer fills in after measuring — acceptable since they're literal measurement outputs, not unknown logic.

**Type consistency:** N/A (no new types — only import moves and timing instrumentation).

**Risk coverage:**
- ✅ Risk 1 (xdist breaks shared-state): Task 2 Steps 3-6
- ✅ Risk 2 (lazy breaks @patch): pre-survey showed zero @patch("launcher.X") — safe by default
- ✅ Risk 3 (first-click latency): accepted by design, documented in commit msg
- ✅ Risk 4 (metric overhead): negligible (<1ms each)
- ✅ Risk 5 (DPI skip breaks HiDPI): Pattern B requires manual verify
- ✅ Risk 6 (icon lazy flash): Pattern A uses after_idle — imperceptible

---

## Execution options

Plan complete and saved to `docs/superpowers/plans/2026-04-23-cleanup-phase-2.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.
