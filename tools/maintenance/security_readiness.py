"""Operational security readiness check for hardened AURUM environments.

Checks only local prerequisites; it does not generate or mutate secrets.
Exit code 0 means the environment is ready enough to start with the hardened
defaults. Any finding returns exit code 1.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def run_check(*, root: Path = ROOT) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    plaintext_path = root / "config" / "keys.json"
    encrypted_path = root / "config" / "keys.json.enc"
    allow_plaintext = _env_truthy("AURUM_ALLOW_PLAINTEXT_KEYS")
    key_password = os.environ.get("AURUM_KEY_PASSWORD", "").strip()
    mt5_password = os.environ.get("MT5_VNC_PASSWORD", "").strip()

    if encrypted_path.exists():
        if not key_password:
            errors.append("config/keys.json.enc exists but AURUM_KEY_PASSWORD is not set")
    elif plaintext_path.exists():
        if not allow_plaintext:
            errors.append(
                "config/keys.json exists without config/keys.json.enc; set AURUM_ALLOW_PLAINTEXT_KEYS=1 only for controlled migration"
            )
        else:
            warnings.append("plaintext key fallback enabled via AURUM_ALLOW_PLAINTEXT_KEYS")
    else:
        errors.append("no key store found; expected config/keys.json.enc or config/keys.json")

    if not mt5_password:
        warnings.append("MT5_VNC_PASSWORD is not set")

    if not (root / "config" / "keys.json").exists() and not encrypted_path.exists():
        warnings.append("VPS known_hosts path cannot be validated until keys are provisioned")

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-warnings", action="store_true")
    args = parser.parse_args(argv)

    errors, warnings = run_check()
    for line in errors:
        print(f"ERROR: {line}")
    for line in warnings:
        print(f"WARN:  {line}")

    if errors:
        return 1
    if warnings and args.strict_warnings:
        return 1
    print("OK: security readiness check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
