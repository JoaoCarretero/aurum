"""AURUM — encrypted-at-rest API key store.

Thin wrapper around ``config/keys.json`` that supports two modes:

  **Plaintext mode** (default, matches pre-module behavior)
    Reads ``config/keys.json`` directly. No encryption. Used today by
    the launcher and every existing engine. This is the fallback path
    when ``cryptography`` is not installed, and the safe default for
    paper / demo / testnet runs that never touch real capital.

  **Encrypted mode** (opt-in)
    Reads ``config/keys.json.enc`` and decrypts with a master password
    derived via PBKDF2-HMAC-SHA256. Requires the ``cryptography``
    package. Exposes ``lock()``/``unlock()`` so the decrypted state
    lives only in the current process's memory and only for the
    duration of the session.

Design notes
------------
- **No automatic upgrade.** This module will NEVER silently rewrite
  ``config/keys.json`` to the encrypted form. The user must explicitly
  call ``KeyStore.encrypt_from_plaintext(master_password)`` once they
  decide they want encryption. Same applies to the reverse —
  ``decrypt_to_plaintext`` is an explicit operation.
- **Memory-only decrypted state.** When unlocked, the decrypted dict
  lives in the ``KeyStore`` instance and nowhere else. ``lock()``
  zeroes the reference. There is no persistent session cache.
- **Read-only by default.** ``get`` and ``get_block`` are the only
  public accessors. Writing back into an encrypted store is explicit
  via ``save_encrypted(new_data, master_password)``.
- **Degrades gracefully.** If ``cryptography`` isn't available, the
  encrypted path raises ``KeyStoreUnavailableError`` with a clear
  install hint; every plaintext path still works.

Usage
-----

    from core.key_store import KeyStore

    # Plaintext (legacy behavior)
    ks = KeyStore()
    keys = ks.read()                      # → dict
    binance = keys.get("testnet", {})

    # Encrypted mode
    ks = KeyStore(encrypted=True)
    ks.unlock("my-master-password")       # prompts or pass directly
    keys = ks.read()
    ks.lock()                             # clears in-memory state

    # One-time migration to encrypted
    ks = KeyStore()
    ks.encrypt_from_plaintext("my-master-password")
    # now config/keys.json.enc exists; config/keys.json can be deleted
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path


PLAINTEXT_PATH = Path("config") / "keys.json"
ENCRYPTED_PATH = Path("config") / "keys.json.enc"


class KeyStoreError(Exception):
    """Base class for key store failures — inherit, don't instantiate."""


class KeyStoreUnavailableError(KeyStoreError):
    """Encrypted mode requested but ``cryptography`` package is not
    installed. Install via ``pip install cryptography``."""


class KeyStoreLockedError(KeyStoreError):
    """Caller tried to read from an encrypted store without unlocking."""


class KeyStoreCorruptError(KeyStoreError):
    """The encrypted file exists but could not be parsed or decrypted —
    usually wrong master password or truncated ciphertext."""


# ── Crypto primitives (lazy-imported to keep default path dep-free) ──

def _require_crypto():
    try:
        from cryptography.fernet import Fernet, InvalidToken      # noqa: F401
        from cryptography.hazmat.primitives import hashes          # noqa: F401
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: F401
    except ImportError as e:
        raise KeyStoreUnavailableError(
            "encrypted key store requires `cryptography` — "
            "install via: pip install cryptography"
        ) from e


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a Fernet key from ``password`` + ``salt`` via PBKDF2-HMAC-SHA256.

    Iteration count matches the cryptography library's current
    recommendation for interactive use. The derived 32-byte key is
    base64-urlsafe-encoded for Fernet.
    """
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    raw = kdf.derive(password.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


@dataclass
class _EncryptedEnvelope:
    """On-disk structure for the encrypted file.

    JSON-wrapped for easy inspection of non-secret metadata: someone
    opening ``keys.json.enc`` sees a JSON object with a salt + version
    field and one opaque ``ciphertext``. The decryption step still
    requires the password.
    """
    version:    int
    salt_b64:   str
    ciphertext: str   # base64-urlsafe


class KeyStore:
    def __init__(self, *, encrypted: bool = False,
                 plaintext_path: Path = PLAINTEXT_PATH,
                 encrypted_path: Path = ENCRYPTED_PATH) -> None:
        self.encrypted = encrypted
        self.plaintext_path = Path(plaintext_path)
        self.encrypted_path = Path(encrypted_path)
        self._unlocked: dict | None = None

        if encrypted:
            _require_crypto()

    # ── Reading ───────────────────────────────────────────────────────

    def read(self) -> dict:
        """Return the current key dict. Raises if encrypted + locked."""
        if self.encrypted:
            if self._unlocked is None:
                raise KeyStoreLockedError(
                    "encrypted key store is locked — call unlock(password) first")
            return dict(self._unlocked)   # shallow copy so caller can't mutate
        # Plaintext
        if not self.plaintext_path.exists():
            return {}
        try:
            return json.loads(self.plaintext_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get_block(self, mode: str) -> dict:
        """Return the block for a given mode (demo/testnet/live/…).

        Matches the pattern used throughout the launcher and engines:
        ``keys["demo"]["api_key"]`` etc. Missing blocks return ``{}``.
        """
        data = self.read()
        block = data.get(mode)
        return block if isinstance(block, dict) else {}

    # ── Encrypted state lifecycle ────────────────────────────────────

    def unlock(self, master_password: str) -> None:
        """Decrypt the encrypted file with ``master_password``.

        After this succeeds, ``read()`` returns the decrypted dict.
        Call ``lock()`` to clear the in-memory state when done.
        """
        _require_crypto()
        from cryptography.fernet import Fernet, InvalidToken

        if not self.encrypted_path.exists():
            raise KeyStoreCorruptError(
                f"{self.encrypted_path} does not exist — nothing to unlock")

        try:
            env = json.loads(self.encrypted_path.read_text(encoding="utf-8"))
            salt = base64.urlsafe_b64decode(env["salt_b64"])
            ct   = env["ciphertext"].encode("ascii")
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
            raise KeyStoreCorruptError(
                f"could not parse {self.encrypted_path}: {e}") from e

        try:
            key = _derive_key(master_password, salt)
            pt  = Fernet(key).decrypt(ct)
            self._unlocked = json.loads(pt.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError) as e:
            raise KeyStoreCorruptError("decrypt failed — wrong password?") from e

    def lock(self) -> None:
        """Clear the in-memory decrypted dict. Idempotent."""
        self._unlocked = None

    def is_unlocked(self) -> bool:
        return self._unlocked is not None

    # ── Writing / migration ──────────────────────────────────────────

    def save_encrypted(self, data: dict, master_password: str) -> None:
        """Serialize ``data`` and write it encrypted at ``encrypted_path``.

        Overwrites the existing file. Use for rotating a password or
        updating stored credentials. Plaintext file is NOT touched.
        """
        _require_crypto()
        from cryptography.fernet import Fernet

        salt = os.urandom(16)
        key = _derive_key(master_password, salt)
        pt  = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ct  = Fernet(key).encrypt(pt)

        envelope = {
            "version":    1,
            "salt_b64":   base64.urlsafe_b64encode(salt).decode("ascii"),
            "ciphertext": ct.decode("ascii"),
        }
        self.encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file + os.replace
        tmp = self.encrypted_path.with_suffix(".enc.tmp")
        tmp.write_text(json.dumps(envelope, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.encrypted_path)

        # Update unlocked state so .read() still works without a re-unlock
        self._unlocked = dict(data)
        self.encrypted = True

    def encrypt_from_plaintext(self, master_password: str) -> None:
        """One-time migration: read plaintext keys.json and rewrite it
        as keys.json.enc. The original plaintext file is NOT deleted —
        the user decides when (if ever) to remove it."""
        if not self.plaintext_path.exists():
            raise KeyStoreCorruptError(
                f"{self.plaintext_path} does not exist — nothing to migrate")
        data = json.loads(self.plaintext_path.read_text(encoding="utf-8"))
        self.save_encrypted(data, master_password)

    def decrypt_to_plaintext(self) -> None:
        """Inverse of encrypt_from_plaintext — write the current
        unlocked state as plaintext. Requires unlock() first.
        Overwrites the existing plaintext file."""
        if self._unlocked is None:
            raise KeyStoreLockedError(
                "unlock(password) before decrypt_to_plaintext")
        self.plaintext_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.plaintext_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._unlocked, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, self.plaintext_path)


__all__ = [
    "KeyStore",
    "KeyStoreError",
    "KeyStoreLockedError",
    "KeyStoreCorruptError",
    "KeyStoreUnavailableError",
    "PLAINTEXT_PATH",
    "ENCRYPTED_PATH",
]
