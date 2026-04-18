"""AURUM — one-time migration: encrypt config/keys.json.

Reads the existing plaintext ``config/keys.json``, prompts for a
master password twice, encrypts with ``core.key_store.KeyStore``,
and writes ``config/keys.json.enc`` next to the plaintext file.

The plaintext file is **NOT** deleted by this script — the user
verifies the encrypted path works (set AURUM_KEY_PASSWORD, run the
live engine in paper mode once, watch for the "Keys loaded from
encrypted store" log line) and then deletes the plaintext file
manually.

Usage
-----
    python tools/encrypt_keys.py

    $ master password: ***************
    $ repeat:          ***************
    written config/keys.json.enc
    next steps:
      1. set AURUM_KEY_PASSWORD in your shell or launcher env
      2. run python -m engines.live (or via aurum_cli) in paper mode
      3. confirm the log shows "Keys loaded from encrypted store"
      4. delete config/keys.json manually

Exit codes
----------
    0 — encrypted file written
    1 — plaintext source missing
    2 — passwords don't match
    3 — cryptography not installed
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent.parent
    plaintext = root / "config" / "keys.json"
    encrypted = root / "config" / "keys.json.enc"

    if not plaintext.exists():
        print(f"  ! {plaintext} does not exist — nothing to encrypt")
        return 1

    try:
        from core.key_store import KeyStore, KeyStoreUnavailableError
    except ImportError as e:
        print(f"  ! cannot import KeyStore: {e}")
        return 3

    if encrypted.exists():
        print(f"  ! {encrypted} already exists — aborting to avoid overwrite")
        print(f"    remove the existing file manually if you want to re-encrypt")
        return 1

    try:
        pw1 = getpass.getpass("  master password:  ")
        pw2 = getpass.getpass("  repeat:           ")
    except (EOFError, KeyboardInterrupt):
        print("\n  ! cancelled")
        return 2

    if pw1 != pw2:
        print("  ! passwords do not match")
        return 2

    if len(pw1) < 8:
        print("  ! password must be at least 8 characters")
        return 2

    try:
        ks = KeyStore(
            plaintext_path=plaintext,
            encrypted_path=encrypted,
        )
        ks.encrypt_from_plaintext(pw1)
    except KeyStoreUnavailableError as e:
        print(f"  ! {e}")
        return 3
    except Exception as e:
        print(f"  ! encryption failed: {type(e).__name__}: {e}")
        return 1

    print(f"  ✓ written {encrypted.relative_to(root)}")
    print()
    print("  next steps:")
    print("    1. set AURUM_KEY_PASSWORD in your shell or launcher env")
    print("    2. run the live engine in paper mode once")
    print("    3. confirm the log shows 'Keys loaded from encrypted store'")
    print("    4. delete config/keys.json manually")
    print()
    print("  the plaintext file was NOT removed — verify the encrypted")
    print("  path works before deleting it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
