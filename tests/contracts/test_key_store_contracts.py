"""Contract tests for core.key_store — plaintext + encrypted modes.

Security-critical module. Testes cobrem:
- Plaintext: read de arquivo existente, missing file, JSON corrompido
- Encrypted lifecycle: lock/unlock, wrong password, in-memory-only state
- Migration: encrypt_from_plaintext, decrypt_to_plaintext roundtrip
- Error taxonomy: KeyStoreLockedError, KeyStoreCorruptError
"""
from __future__ import annotations

import json

import pytest

from core.key_store import (
    KeyStore,
    KeyStoreCorruptError,
    KeyStoreError,
    KeyStoreLockedError,
    KeyStoreUnavailableError,
)


@pytest.fixture
def pt_path(tmp_path):
    return tmp_path / "keys.json"


@pytest.fixture
def enc_path(tmp_path):
    return tmp_path / "keys.json.enc"


SAMPLE_KEYS = {
    "testnet": {"api_key": "TK_abcd1234", "secret": "secret_xyz"},
    "live": {"api_key": "LK_9999", "secret": "live_secret"},
    "telegram": {"bot_token": "123:ABC", "chat_id": "555"},
}


# ────────────────────────────────────────────────────────────
# Plaintext mode
# ────────────────────────────────────────────────────────────

class TestPlaintextRead:
    def test_missing_file_returns_empty_dict(self, pt_path, enc_path):
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.read() == {}

    def test_reads_json_content(self, pt_path, enc_path):
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.read() == SAMPLE_KEYS

    def test_corrupt_json_returns_empty_dict(self, pt_path, enc_path):
        pt_path.write_text("{not valid json", encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.read() == {}

    def test_get_block_returns_mode_dict(self, pt_path, enc_path):
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.get_block("testnet") == SAMPLE_KEYS["testnet"]

    def test_get_block_missing_returns_empty(self, pt_path, enc_path):
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.get_block("nonexistent") == {}

    def test_get_block_non_dict_value_returns_empty(self, pt_path, enc_path):
        # Se o JSON tem algo que não é dict no mode, get_block retorna {}
        pt_path.write_text(json.dumps({"scalar": "not_a_dict"}), encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.get_block("scalar") == {}


# ────────────────────────────────────────────────────────────
# Encrypted mode — lock/unlock
# ────────────────────────────────────────────────────────────

class TestEncryptedLifecycle:
    def test_init_encrypted_starts_locked(self, pt_path, enc_path):
        # Setup: encrypt some data via helper
        ks_pt = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks_pt.encrypt_from_plaintext("master123")

        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.is_unlocked() is False

    def test_read_locked_raises(self, pt_path, enc_path):
        # Encrypted + locked → raise on read()
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        KeyStore(plaintext_path=pt_path, encrypted_path=enc_path).encrypt_from_plaintext("pw")

        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        with pytest.raises(KeyStoreLockedError):
            ks.read()

    def test_unlock_correct_password_enables_read(self, pt_path, enc_path):
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        KeyStore(plaintext_path=pt_path, encrypted_path=enc_path).encrypt_from_plaintext("pw")

        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        ks.unlock("pw")
        assert ks.is_unlocked() is True
        assert ks.read() == SAMPLE_KEYS

    def test_unlock_wrong_password_raises_corrupt(self, pt_path, enc_path):
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        KeyStore(plaintext_path=pt_path, encrypted_path=enc_path).encrypt_from_plaintext("correct")

        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        with pytest.raises(KeyStoreCorruptError):
            ks.unlock("wrong")

    def test_unlock_missing_file_raises_corrupt(self, pt_path, enc_path):
        # Encrypted path não existe → erro claro
        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        with pytest.raises(KeyStoreCorruptError):
            ks.unlock("anything")

    def test_unlock_malformed_envelope_raises_corrupt(self, pt_path, enc_path):
        enc_path.write_text("{not_a_valid_envelope", encoding="utf-8")
        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        with pytest.raises(KeyStoreCorruptError):
            ks.unlock("pw")

    def test_lock_clears_in_memory_state(self, pt_path, enc_path):
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        KeyStore(plaintext_path=pt_path, encrypted_path=enc_path).encrypt_from_plaintext("pw")

        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        ks.unlock("pw")
        assert ks.is_unlocked()
        ks.lock()
        assert not ks.is_unlocked()
        with pytest.raises(KeyStoreLockedError):
            ks.read()

    def test_lock_is_idempotent(self, pt_path, enc_path):
        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        ks.lock()
        ks.lock()  # não deve crashear

    def test_read_returns_shallow_copy(self, pt_path, enc_path):
        """Caller mutating o retorno de read() NÃO muta o state interno."""
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        KeyStore(plaintext_path=pt_path, encrypted_path=enc_path).encrypt_from_plaintext("pw")

        ks = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        ks.unlock("pw")
        data = ks.read()
        data["MUTATED"] = True
        # Re-read → estado interno preservado
        assert "MUTATED" not in ks.read()


# ────────────────────────────────────────────────────────────
# Save / Roundtrip
# ────────────────────────────────────────────────────────────

class TestSaveEncryptedRoundtrip:
    def test_save_then_unlock_recovers_data(self, pt_path, enc_path):
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        ks.save_encrypted(SAMPLE_KEYS, "roundtrip_pw")

        # Novo KeyStore em modo encrypted lê o mesmo arquivo
        ks2 = KeyStore(encrypted=True, plaintext_path=pt_path, encrypted_path=enc_path)
        ks2.unlock("roundtrip_pw")
        assert ks2.read() == SAMPLE_KEYS

    def test_save_auto_sets_encrypted_mode(self, pt_path, enc_path):
        # save_encrypted atualiza self.encrypted para True e mantém unlocked
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        assert ks.encrypted is False
        ks.save_encrypted(SAMPLE_KEYS, "pw")
        assert ks.encrypted is True
        assert ks.is_unlocked()
        assert ks.read() == SAMPLE_KEYS

    def test_save_creates_file_with_envelope_structure(self, pt_path, enc_path):
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        ks.save_encrypted(SAMPLE_KEYS, "pw")
        envelope = json.loads(enc_path.read_text(encoding="utf-8"))
        assert set(envelope.keys()) == {"version", "salt_b64", "ciphertext"}
        assert envelope["version"] == 1
        # Ciphertext não deve conter plaintext (sanity)
        assert "api_key" not in envelope["ciphertext"]

    def test_save_different_passwords_produce_different_ciphertext(self, pt_path, enc_path, tmp_path):
        enc2 = tmp_path / "keys2.json.enc"
        ks1 = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        ks1.save_encrypted(SAMPLE_KEYS, "password1")
        ks2 = KeyStore(plaintext_path=pt_path, encrypted_path=enc2)
        ks2.save_encrypted(SAMPLE_KEYS, "password2")

        ct1 = json.loads(enc_path.read_text())["ciphertext"]
        ct2 = json.loads(enc2.read_text())["ciphertext"]
        assert ct1 != ct2  # salts + keys diferem

    def test_save_same_password_twice_produces_different_salt(self, pt_path, enc_path):
        """Cada save_encrypted gera um salt novo — mesma senha não
        produz ciphertext determinístico (boa prática crypto)."""
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        ks.save_encrypted(SAMPLE_KEYS, "pw")
        salt1 = json.loads(enc_path.read_text())["salt_b64"]
        ks.save_encrypted(SAMPLE_KEYS, "pw")
        salt2 = json.loads(enc_path.read_text())["salt_b64"]
        assert salt1 != salt2


# ────────────────────────────────────────────────────────────
# Migration: encrypt_from_plaintext / decrypt_to_plaintext
# ────────────────────────────────────────────────────────────

class TestMigration:
    def test_encrypt_from_plaintext_creates_encrypted_file(self, pt_path, enc_path):
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        ks.encrypt_from_plaintext("migration_pw")
        assert enc_path.exists()

    def test_encrypt_from_plaintext_does_not_delete_original(self, pt_path, enc_path):
        """Docstring é explícito: original NÃO é removido — usuário decide."""
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        ks.encrypt_from_plaintext("pw")
        assert pt_path.exists()

    def test_encrypt_from_plaintext_missing_raises(self, pt_path, enc_path):
        # pt_path não existe → erro explícito
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        with pytest.raises(KeyStoreCorruptError):
            ks.encrypt_from_plaintext("pw")

    def test_decrypt_to_plaintext_roundtrip(self, pt_path, enc_path):
        # Encrypt, lock, unlock, decrypt back → plaintext igual
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        ks.encrypt_from_plaintext("pw")
        # Remove plaintext
        pt_path.unlink()
        # Decrypt de volta
        ks.decrypt_to_plaintext()
        assert pt_path.exists()
        assert json.loads(pt_path.read_text(encoding="utf-8")) == SAMPLE_KEYS

    def test_decrypt_to_plaintext_when_locked_raises(self, pt_path, enc_path):
        # Encrypted mode + locked → não pode decrypt
        ks = KeyStore(plaintext_path=pt_path, encrypted_path=enc_path)
        pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
        ks.encrypt_from_plaintext("pw")
        ks.lock()
        with pytest.raises(KeyStoreLockedError):
            ks.decrypt_to_plaintext()


# ────────────────────────────────────────────────────────────
# Exception hierarchy
# ────────────────────────────────────────────────────────────

class TestErrorHierarchy:
    def test_all_errors_inherit_from_base(self):
        for cls in (KeyStoreLockedError, KeyStoreCorruptError, KeyStoreUnavailableError):
            assert issubclass(cls, KeyStoreError)
