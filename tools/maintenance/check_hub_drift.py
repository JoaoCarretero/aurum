"""Check drift between hub docs (AGENTS/MEMORY/CONTEXT/SKILLS) and repo state.

Warn-only (exit 0 sempre), listando discrepancias pra review humano. Nao
bloqueia commits. Executar manualmente:

    python -m tools.maintenance.check_hub_drift

Ou adicionar a um /schedule semanal via Claude Code.

O que checa:
  1. Engine count em config/engines.py vs numero em MEMORY.md secao 4
  2. CORE files protegidos em pyproject.toml vs MEMORY.md secao 1
  3. Comandos referenciados existem (smoke_test.py, tools/maintenance/*)
  4. Paths de docs referenciados existem
  5. Secoes-chave presentes em cada hub file (LEIA PRIMEIRO no CLAUDE.md)

Output: exit 0 = OK (mesmo com warnings); relatorio em stdout.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def check_engines_count() -> list[str]:
    findings = []
    engines_py = _read(ROOT / "config" / "engines.py")
    memory_md = _read(ROOT / "MEMORY.md")

    # Conta entradas so dentro do dict ENGINES = { ... } (primeira ocorrencia
    # do bloco, termina em } em indent 0)
    match = re.search(r"^ENGINES\s*=\s*\{(.*?)^\}", engines_py, re.DOTALL | re.MULTILINE)
    if not match:
        findings.append("  [config/engines.py] bloco ENGINES = {...} nao encontrado")
        return findings
    engines_block = match.group(1)
    entries = re.findall(r'^\s*"[a-z_]+":\s+\{', engines_block, flags=re.MULTILINE)
    real_count = len(entries)

    # Busca claim em MEMORY.md: "Engines vivos no repo...: 12 (de 16)"
    claim = re.search(r"Engines vivos[^:]*:\*\*\s*(\d+)", memory_md)
    if not claim:
        findings.append(
            f"  [MEMORY.md] nao encontrou claim de engine count (real: {real_count})"
        )
    else:
        claimed = int(claim.group(1))
        if claimed != real_count:
            findings.append(
                f"  [MEMORY.md] claim {claimed} engines != real {real_count} "
                f"em config/engines.py ENGINES dict"
            )
    return findings


def check_core_protection() -> list[str]:
    findings = []
    pyproject = _read(ROOT / "pyproject.toml")
    memory_md = _read(ROOT / "MEMORY.md")

    core_paths = [
        "core/indicators.py",
        "core/signals.py",
        "core/portfolio.py",
        "config/params.py",
    ]

    for path in core_paths:
        if f'"{path}"' not in pyproject:
            findings.append(
                f"  [pyproject.toml] CORE path {path} NAO esta em "
                f"per-file-ignores (protecao estatica quebrada)"
            )
        if path not in memory_md:
            findings.append(
                f"  [MEMORY.md] CORE path {path} nao mencionado"
            )

    return findings


def check_referenced_commands() -> list[str]:
    findings = []
    memory_md = _read(ROOT / "MEMORY.md")
    context_md = _read(ROOT / "CONTEXT.md")
    joined = memory_md + "\n" + context_md

    # Pega comandos "python <something>.py" ou "python -m <module>"
    # e so checa os que apontam pra arquivos do repo (nao engines/backtest)
    critical_paths = [
        ("smoke_test.py", ROOT / "smoke_test.py"),
        (
            "tools/maintenance/verify_keys_intact.py",
            ROOT / "tools" / "maintenance" / "verify_keys_intact.py",
        ),
        (
            "tools/maintenance/backup_keys.py",
            ROOT / "tools" / "maintenance" / "backup_keys.py",
        ),
        (
            "tools/reports/reconcile_runs.py",
            ROOT / "tools" / "reports" / "reconcile_runs.py",
        ),
    ]

    for label, path in critical_paths:
        if label in joined and not path.exists():
            findings.append(f"  [hub docs] referencia {label} mas arquivo nao existe")

    return findings


def check_referenced_docs() -> list[str]:
    findings = []
    memory_md = _read(ROOT / "MEMORY.md")
    agents_md = _read(ROOT / "AGENTS.md")
    joined = memory_md + "\n" + agents_md

    critical_docs = [
        "docs/methodology/anti_overfit_protocol.md",
        "docs/audits/2026-04-17_agent_orchestration.md",
        "docs/audits/2026-04-22_codex_day_audit.md",
        "docs/audits/2026-04-16_oos_verdict.md",
    ]

    for doc in critical_docs:
        if doc in joined and not (ROOT / doc).exists():
            findings.append(f"  [hub docs] referencia {doc} mas arquivo nao existe")

    return findings


def check_hub_sections() -> list[str]:
    findings = []
    claude_md = _read(ROOT / "CLAUDE.md")

    if "LEIA PRIMEIRO" not in claude_md:
        findings.append(
            "  [CLAUDE.md] bloco 'LEIA PRIMEIRO' com pointers pros 4 hub files "
            "nao encontrado (sessoes futuras podem nao saber que existem)"
        )

    for hub in ("AGENTS.md", "MEMORY.md", "CONTEXT.md", "SKILLS.md"):
        if not (ROOT / hub).exists():
            findings.append(f"  [root] hub file {hub} desapareceu")

    return findings


def check_personas() -> list[str]:
    findings = []
    personas_dir = ROOT / "docs" / "agents"
    required = ["scryer.md", "arbiter.md", "artifex.md", "curator.md"]

    for key in required:
        if not (personas_dir / key).exists():
            findings.append(
                f"  [docs/agents/{key}] nao existe — markdown_editor "
                f"vai fallback pra AGENTS.md (risco de edit acidental no hub)"
            )
    return findings


def main() -> int:
    print("=" * 60)
    print("HUB DRIFT CHECK — AURUM Finance")
    print("=" * 60)

    checks = [
        ("Engine count (config/engines.py vs MEMORY.md)", check_engines_count),
        ("CORE protection (pyproject.toml + MEMORY.md)", check_core_protection),
        ("Referenced commands exist", check_referenced_commands),
        ("Referenced docs exist", check_referenced_docs),
        ("Hub files + CLAUDE.md pointer", check_hub_sections),
        ("Persona stubs (docs/agents/)", check_personas),
    ]

    total_findings = 0
    for label, fn in checks:
        findings = fn()
        if findings:
            print(f"\n[WARN] {label}: {len(findings)} drift(s)")
            for line in findings:
                print(line)
            total_findings += len(findings)
        else:
            print(f"\n[OK]   {label}")

    print("\n" + "=" * 60)
    if total_findings == 0:
        print("Zero drift detectado. Hub files em sync com o repo.")
    else:
        print(
            f"{total_findings} drift(s) detectado(s). Review manual + update "
            f"dos hub files recomendado."
        )
    print("=" * 60)

    # Sempre exit 0 — warn-only, nao bloqueia workflow
    return 0


if __name__ == "__main__":
    sys.exit(main())
