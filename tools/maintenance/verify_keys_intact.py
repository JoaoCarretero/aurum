"""AURUM — verify config/keys.json is not a fresh placeholder template.

Runs automatically pre-commit (via hook) and can be invoked manually
before any risky operation. Detects the "COLE_AQUI" template-wipe scenario
that happened 2026-04-19 when an agent (Codex or other) reset keys.json
to placeholders silently, costing the shadow/paper cockpit and VPS tunnel.

Exit codes:
    0 — keys.json healthy (no critical placeholders in sections that matter)
    1 — WIPED: keys.json is a template (has placeholders where real secrets
        must live). Refuses to pass.
    2 — MISSING: keys.json does not exist.

Sections checked for placeholder wipe:
    - vps_ssh.host, vps_ssh.key_path
    - cockpit_api.read_token, cockpit_api.admin_token
    - telegram.bot_token, telegram.chat_id

Sections allowed to have placeholders (user may not use them yet):
    - demo.api_key, testnet.api_key, live.api_key, macro_brain.*

Usage:
    python tools/maintenance/verify_keys_intact.py
    python tools/maintenance/verify_keys_intact.py --strict  # check ALL keys
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
KEYS_PATH = ROOT / "config" / "keys.json"

PLACEHOLDER_MARKERS = ("COLE_AQUI", "PASTE_HERE", "REPLACE_ME")

# Sections that CANNOT be placeholder — breaking these breaks operation.
CRITICAL_SECTIONS = {
    "vps_ssh": ("host", "key_path"),
    "cockpit_api": ("read_token", "admin_token"),
    "telegram": ("bot_token", "chat_id"),
}

# Sections checked under --strict (exchange keys, macro_brain)
STRICT_SECTIONS = {
    "demo": ("api_key", "api_secret"),
    "testnet": ("api_key", "api_secret"),
    "live": ("api_key", "api_secret"),
    "macro_brain": ("fred_api_key", "newsapi_key"),
}


def _is_placeholder(value) -> bool:
    if not isinstance(value, str):
        return False
    for marker in PLACEHOLDER_MARKERS:
        if marker in value:
            return True
    return False


def _check_sections(data: dict, sections: dict) -> list[str]:
    problems: list[str] = []
    for section, fields in sections.items():
        block = data.get(section)
        if not isinstance(block, dict):
            problems.append(f"{section}: MISSING or not a dict")
            continue
        for f in fields:
            v = block.get(f)
            if _is_placeholder(v):
                problems.append(f"{section}.{f}: PLACEHOLDER ({v!r})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--strict", action="store_true",
                        help="Also check exchange + macro_brain keys")
    parser.add_argument("--path", type=Path, default=KEYS_PATH,
                        help="Path to keys.json (default config/keys.json)")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"MISSING: {args.path} does not exist.", file=sys.stderr)
        return 2

    try:
        data = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"MISSING: {args.path} unreadable: {exc}", file=sys.stderr)
        return 2

    sections = dict(CRITICAL_SECTIONS)
    if args.strict:
        sections.update(STRICT_SECTIONS)

    problems = _check_sections(data, sections)

    if problems:
        print("KEYS.JSON WIPED OR PLACEHOLDER-ONLY:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
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

    print(f"OK — {args.path} has no placeholder in critical sections.")
    if args.strict:
        print("      (--strict also verified exchange + macro_brain keys)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
