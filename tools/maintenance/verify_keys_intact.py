"""AURUM - verify config/keys.json is not a fresh placeholder template.

Runs automatically pre-commit (via hook) and can be invoked manually
before any risky operation. Detects the "COLE_AQUI" template-wipe scenario
that happened 2026-04-19 when an agent reset keys.json to placeholders,
costing the shadow/paper cockpit and VPS tunnel.

Exit codes:
    0 - keys.json healthy (no critical placeholders in sections that matter)
    1 - WIPED: keys.json is a template (has placeholders where real secrets
        must live). Refuses to pass.
    2 - MISSING: keys.json does not exist or is unreadable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KEYS_PATH = ROOT / "config" / "keys.json"

PLACEHOLDER_MARKERS = ("COLE_AQUI", "PASTE_HERE", "REPLACE_ME")

CRITICAL_SECTIONS = {
    "vps_ssh": ("host", "key_path"),
    "cockpit_api": ("read_token", "admin_token"),
    "telegram": ("bot_token", "chat_id"),
}

STRICT_SECTIONS = {
    "demo": ("api_key", "api_secret"),
    "testnet": ("api_key", "api_secret"),
    "live": ("api_key", "api_secret"),
    "macro_brain": ("fred_api_key", "newsapi_key"),
}


def _is_placeholder(value) -> bool:
    return isinstance(value, str) and any(marker in value for marker in PLACEHOLDER_MARKERS)


def _check_sections(data: dict, sections: dict) -> list[str]:
    problems: list[str] = []
    for section, fields in sections.items():
        block = data.get(section)
        if not isinstance(block, dict):
            problems.append(f"{section}: MISSING or not a dict")
            continue
        for field in fields:
            value = block.get(field)
            if _is_placeholder(value):
                problems.append(f"{section}.{field}: PLACEHOLDER ({value!r})")
    return problems


def run_check(*, path: Path = KEYS_PATH, strict: bool = False) -> tuple[int, list[str]]:
    if not path.exists():
        return 2, [f"MISSING: {path} does not exist."]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return 2, [f"MISSING: {path} unreadable: {exc}"]

    sections = dict(CRITICAL_SECTIONS)
    if strict:
        sections.update(STRICT_SECTIONS)
    problems = _check_sections(data, sections)
    if problems:
        return 1, problems
    return 0, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true", help="Also check exchange + macro_brain keys")
    parser.add_argument("--path", type=Path, default=KEYS_PATH, help="Path to keys.json (default config/keys.json)")
    args = parser.parse_args()

    code, problems = run_check(path=args.path, strict=args.strict)
    if code == 2:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 2
    if code == 1:
        print("KEYS.JSON WIPED OR PLACEHOLDER-ONLY:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "INCIDENT: Critical sections of config/keys.json have placeholder\n"
            "values where real secrets must live. This usually means an agent\n"
            "(Codex, Claude, or a setup script) reset the file to the template.\n"
            "Recover via OneDrive version history (right-click keys.json in\n"
            "File Explorer > Version history > pick a version before the wipe)\n"
            "or via your password manager. Do not commit in this state.",
            file=sys.stderr,
        )
        return 1

    print(f"OK - {args.path} has no placeholder in critical sections.")
    if args.strict:
        print("      (--strict also verified exchange + macro_brain keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
