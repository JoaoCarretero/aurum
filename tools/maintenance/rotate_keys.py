"""AURUM — rotate API keys for a given mode in config/keys.json.

Replaces the ``api_key`` and ``api_secret`` for a single mode block
(``demo``, ``testnet``, or ``live``) after backing up the existing file
with a timestamp. Never touches other blocks (macro_brain, telegram,
etc.).

Why a CLI tool instead of editing keys.json by hand?
- Editing JSON manually is error-prone: a misplaced quote or trailing
  comma silently breaks every engine on next start.
- Hand-editing skips the backup step, so a typo loses the previous key.
- A scripted path is auditable and works over SSH without a GUI.

Usage
-----
    python tools/maintenance/rotate_keys.py testnet
    # prompts: api_key:    ****
    #          api_secret: ****
    # writes:  config/keys.json.bak.YYYY-MM-DD_HHMMSS
    #          config/keys.json   (atomic)

Exit codes
----------
    0 — rotated, backup written
    1 — input aborted / validation failed
    2 — IO / write error
    3 — unknown mode
"""
from __future__ import annotations

import getpass
import json
import sys
from datetime import datetime
from pathlib import Path

from core.fs import atomic_write


_VALID_MODES = ("demo", "testnet", "live")
_MIN_LEN = 20   # Binance API keys are 64 chars; 20 is a generous floor.


def _validate(field: str, value: str) -> str | None:
    """Return error message if invalid, else None."""
    if not value:
        return f"{field} cannot be empty"
    if value != value.strip():
        return f"{field} has leading/trailing whitespace"
    if len(value) < _MIN_LEN:
        return f"{field} is suspiciously short ({len(value)} < {_MIN_LEN})"
    return None


def rotate(mode: str,
           api_key: str,
           api_secret: str,
           keys_path: Path) -> tuple[int, Path | None]:
    """Rotate api_key/api_secret for ``mode`` in ``keys_path``.

    Creates a timestamped backup before writing. Returns
    ``(exit_code, backup_path)``. ``backup_path`` is None unless a
    backup was written.
    """
    if mode not in _VALID_MODES:
        print(f"  ! unknown mode '{mode}' — valid: {list(_VALID_MODES)}")
        return 3, None

    for field, value in (("api_key", api_key), ("api_secret", api_secret)):
        err = _validate(field, value)
        if err:
            print(f"  ! {err}")
            return 1, None

    try:
        data = json.loads(keys_path.read_text(encoding="utf-8")) \
            if keys_path.exists() else {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"  ! could not read {keys_path}: {e}")
        return 2, None

    # Backup: only if the file existed AND had content
    backup_path: Path | None = None
    if keys_path.exists():
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        backup_path = keys_path.with_suffix(f".json.bak.{ts}")
        try:
            backup_path.write_bytes(keys_path.read_bytes())
        except OSError as e:
            print(f"  ! backup failed: {e}")
            return 2, None

    data.setdefault(mode, {})
    data[mode]["api_key"] = api_key
    data[mode]["api_secret"] = api_secret

    try:
        atomic_write(keys_path, json.dumps(data, indent=4, ensure_ascii=False))
    except OSError as e:
        print(f"  ! write failed: {e}")
        return 2, None

    return 0, backup_path


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 1:
        print(__doc__)
        return 1

    mode = argv[0].strip().lower()
    if mode not in _VALID_MODES:
        print(f"  ! unknown mode '{mode}' — valid: {list(_VALID_MODES)}")
        return 3

    root = Path(__file__).resolve().parent.parent.parent
    keys_path = root / "config" / "keys.json"

    print(f"  rotating '{mode}' in {keys_path.relative_to(root)}")
    print(f"  (input is hidden — paste and press Enter)")

    try:
        api_key    = getpass.getpass("  api_key:    ")
        api_secret = getpass.getpass("  api_secret: ")
    except (EOFError, KeyboardInterrupt):
        print("\n  ! cancelled")
        return 1

    code, backup = rotate(mode, api_key, api_secret, keys_path)
    if code == 0:
        print(f"  ✓ rotated '{mode}'")
        if backup is not None:
            print(f"  ✓ backup: {backup.relative_to(root)}")
        print()
        print("  next steps:")
        print("    1. revoke the OLD key in the Binance dashboard")
        print("    2. restart any running engine / reload launcher")
        print("    3. verify with a paper/testnet run before going live")
        print("    4. delete the backup once the new key is confirmed working")
    return code


if __name__ == "__main__":
    sys.exit(main())
