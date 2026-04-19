"""AURUM encrypted-at-rest API key store.

Thin wrapper around ``config/keys.json`` that supports two modes:

  **Plaintext mode** (legacy compatibility path)
    Reads ``config/keys.json`` directly. This remains available for explicit
    migration windows and local testing when the operator intentionally allows
    plaintext fallback.

  **Encrypted mode** (preferred runtime path)
    Reads ``config/keys.json.enc`` and decrypts with a master password derived
    via PBKDF2-HMAC-SHA256. Requires the ``cryptography`` package. Exposes
    ``lock()``/``unlock()`` so the decrypted state lives only in the current
    process's memory and only for the duration of the session.

Design notes
------------
- No automatic upgrade. This module will never silently rewrite
  ``config/keys.json`` to the encrypted form.
- Memory-only decrypted state. ``lock()`` clears the in-memory reference.
- Read-only by default. Persisting encrypted data is always explicit.
- Runtime loading is encrypted-first. If ``keys.json.enc`` exists, callers must
  provide ``AURUM_KEY_PASSWORD`` unless they explicitly allow plaintext
  fallback via ``AURUM_ALLOW_PLAINTEXT_KEYS=1``.
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
    """Base class for key store failures."""


class KeyStoreUnavailableError(KeyStoreError):
    """Encrypted mode requested but ``cryptography`` is not installed."""


class KeyStoreLockedError(KeyStoreError):
    """Caller tried to read from an encrypted store without unlocking."""


class KeyStoreCorruptError(KeyStoreError):
    """The encrypted file exists but could not be parsed or decrypted."""


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_crypto() -> None:
    try:
        from cryptography.fernet import Fernet, InvalidToken  # noqa: F401
        from cryptography.hazmat.primitives import hashes  # noqa: F401
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC  # noqa: F401
    except ImportError as exc:
        raise KeyStoreUnavailableError(
            "encrypted key store requires `cryptography` - install via: pip install cryptography"
        ) from exc


def _derive_key(password: str, salt: bytes) -> bytes:
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
    version: int
    salt_b64: str
    ciphertext: str


class KeyStore:
    def __init__(
        self,
        *,
        encrypted: bool = False,
        plaintext_path: Path = PLAINTEXT_PATH,
        encrypted_path: Path = ENCRYPTED_PATH,
    ) -> None:
        self.encrypted = encrypted
        self.plaintext_path = Path(plaintext_path)
        self.encrypted_path = Path(encrypted_path)
        self._unlocked: dict | None = None

        if encrypted:
            _require_crypto()

    def read(self) -> dict:
        if self.encrypted:
            if self._unlocked is None:
                raise KeyStoreLockedError(
                    "encrypted key store is locked - call unlock(password) first"
                )
            return dict(self._unlocked)

        if not self.plaintext_path.exists():
            return {}
        try:
            return json.loads(self.plaintext_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def get_block(self, mode: str) -> dict:
        data = self.read()
        block = data.get(mode)
        return block if isinstance(block, dict) else {}

    def unlock(self, master_password: str) -> None:
        _require_crypto()
        from cryptography.fernet import Fernet, InvalidToken

        if not self.encrypted_path.exists():
            raise KeyStoreCorruptError(
                f"{self.encrypted_path} does not exist - nothing to unlock"
            )

        try:
            env = json.loads(self.encrypted_path.read_text(encoding="utf-8"))
            salt = base64.urlsafe_b64decode(env["salt_b64"])
            ciphertext = env["ciphertext"].encode("ascii")
        except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
            raise KeyStoreCorruptError(
                f"could not parse {self.encrypted_path}: {exc}"
            ) from exc

        try:
            key = _derive_key(master_password, salt)
            plaintext = Fernet(key).decrypt(ciphertext)
            self._unlocked = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise KeyStoreCorruptError("decrypt failed - wrong password?") from exc

    def lock(self) -> None:
        self._unlocked = None

    def is_unlocked(self) -> bool:
        return self._unlocked is not None

    def save_encrypted(self, data: dict, master_password: str) -> None:
        _require_crypto()
        from cryptography.fernet import Fernet

        salt = os.urandom(16)
        key = _derive_key(master_password, salt)
        plaintext = json.dumps(data, ensure_ascii=False).encode("utf-8")
        ciphertext = Fernet(key).encrypt(plaintext)

        envelope = _EncryptedEnvelope(
            version=1,
            salt_b64=base64.urlsafe_b64encode(salt).decode("ascii"),
            ciphertext=ciphertext.decode("ascii"),
        )
        self.encrypted_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.encrypted_path.with_suffix(".enc.tmp")
        tmp.write_text(
            json.dumps(envelope.__dict__, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self.encrypted_path)

        self._unlocked = dict(data)
        self.encrypted = True

    def encrypt_from_plaintext(self, master_password: str) -> None:
        if not self.plaintext_path.exists():
            raise KeyStoreCorruptError(
                f"{self.plaintext_path} does not exist - nothing to migrate"
            )
        data = json.loads(self.plaintext_path.read_text(encoding="utf-8"))
        self.save_encrypted(data, master_password)

    def decrypt_to_plaintext(self) -> None:
        if self._unlocked is None:
            raise KeyStoreLockedError("unlock(password) before decrypt_to_plaintext")
        self.plaintext_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.plaintext_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._unlocked, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self.plaintext_path)


def load_runtime_keys(
    *,
    plaintext_path: Path = PLAINTEXT_PATH,
    encrypted_path: Path = ENCRYPTED_PATH,
    password_env: str = "AURUM_KEY_PASSWORD",
    allow_plaintext_env: str = "AURUM_ALLOW_PLAINTEXT_KEYS",
) -> dict:
    """Load runtime credentials with encrypted-first semantics."""
    pt_path = Path(plaintext_path)
    enc_path = Path(encrypted_path)
    allow_plaintext = _env_truthy(allow_plaintext_env)
    password = os.environ.get(password_env, "")

    if enc_path.exists():
        if password:
            ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
            ks.unlock(password)
            return ks.read()
        if not allow_plaintext:
            raise KeyStoreLockedError(
                f"{enc_path} exists but {password_env} is not set"
            )

    if allow_plaintext or not enc_path.exists():
        if not pt_path.exists():
            return {}
        try:
            return json.loads(pt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeyStoreCorruptError(f"could not parse {pt_path}: {exc}") from exc

    raise KeyStoreLockedError(
        f"plaintext fallback disabled; set {password_env} for {enc_path}"
    )


__all__ = [
    "KeyStore",
    "KeyStoreError",
    "KeyStoreLockedError",
    "KeyStoreCorruptError",
    "KeyStoreUnavailableError",
    "PLAINTEXT_PATH",
    "ENCRYPTED_PATH",
    "load_runtime_keys",
]
