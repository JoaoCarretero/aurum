"""AURUM - one-time migration: encrypt config/keys.json."""
from __future__ import annotations

import getpass
import sys
from pathlib import Path


def run_encrypt(
    *,
    plaintext: Path,
    encrypted: Path,
    password: str,
    password_repeat: str,
    key_store_cls=None,
    unavailable_error_cls=None,
) -> int:
    if not plaintext.exists():
        return 1
    if encrypted.exists():
        return 1
    if password != password_repeat:
        return 2
    if len(password) < 8:
        return 2

    if key_store_cls is None or unavailable_error_cls is None:
        try:
            from core.risk.key_store import KeyStore, KeyStoreUnavailableError
        except ImportError:
            return 3
        key_store_cls = KeyStore
        unavailable_error_cls = KeyStoreUnavailableError

    try:
        ks = key_store_cls(plaintext_path=plaintext, encrypted_path=encrypted)
        ks.encrypt_from_plaintext(password)
    except unavailable_error_cls:
        return 3
    except Exception:
        return 1
    return 0


def main() -> int:
    root = Path(__file__).resolve().parent.parent.parent
    plaintext = root / "config" / "keys.json"
    encrypted = root / "config" / "keys.json.enc"

    if not plaintext.exists():
        print(f"  ! {plaintext} does not exist - nothing to encrypt")
        return 1

    try:
        from core.risk.key_store import KeyStore, KeyStoreUnavailableError
    except ImportError as exc:
        print(f"  ! cannot import KeyStore: {exc}")
        return 3

    if encrypted.exists():
        print(f"  ! {encrypted} already exists - aborting to avoid overwrite")
        print("    remove the existing file manually if you want to re-encrypt")
        return 1

    try:
        pw1 = getpass.getpass("  master password:  ")
        pw2 = getpass.getpass("  repeat:           ")
    except (EOFError, KeyboardInterrupt):
        print("\n  ! cancelled")
        return 2

    code = run_encrypt(
        plaintext=plaintext,
        encrypted=encrypted,
        password=pw1,
        password_repeat=pw2,
        key_store_cls=KeyStore,
        unavailable_error_cls=KeyStoreUnavailableError,
    )
    if code == 2:
        if pw1 != pw2:
            print("  ! passwords do not match")
        else:
            print("  ! password must be at least 8 characters")
        return 2
    if code == 3:
        print("  ! cryptography / keystore backend unavailable")
        return 3
    if code == 1:
        print("  ! encryption failed")
        return 1

    print(f"  OK written {encrypted.relative_to(root)}")
    print()
    print("  next steps:")
    print("    1. set AURUM_KEY_PASSWORD in your shell or launcher env")
    print("    2. run the live engine in paper mode once")
    print("    3. confirm the log shows 'Keys loaded from encrypted store'")
    print("    4. delete config/keys.json manually")
    print()
    print("  the plaintext file was NOT removed - verify the encrypted")
    print("  path works before deleting it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
