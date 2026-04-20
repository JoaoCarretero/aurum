from __future__ import annotations

from tools.maintenance.encrypt_keys import run_encrypt


class FakeUnavailableError(Exception):
    pass


class FakeKeyStore:
    def __init__(self, *, plaintext_path, encrypted_path):
        self.plaintext_path = plaintext_path
        self.encrypted_path = encrypted_path

    def encrypt_from_plaintext(self, password):
        self.encrypted_path.write_text(f"enc:{password}", encoding="utf-8")


class FailingKeyStore(FakeKeyStore):
    def encrypt_from_plaintext(self, password):
        raise FakeUnavailableError("missing backend")


def test_run_encrypt_happy_path(tmp_path):
    plaintext = tmp_path / "keys.json"
    encrypted = tmp_path / "keys.json.enc"
    plaintext.write_text("{}", encoding="utf-8")

    code = run_encrypt(
        plaintext=plaintext,
        encrypted=encrypted,
        password="supersecret",
        password_repeat="supersecret",
        key_store_cls=FakeKeyStore,
        unavailable_error_cls=FakeUnavailableError,
    )

    assert code == 0
    assert encrypted.read_text(encoding="utf-8") == "enc:supersecret"


def test_run_encrypt_requires_plaintext_source(tmp_path):
    code = run_encrypt(
        plaintext=tmp_path / "keys.json",
        encrypted=tmp_path / "keys.json.enc",
        password="supersecret",
        password_repeat="supersecret",
        key_store_cls=FakeKeyStore,
        unavailable_error_cls=FakeUnavailableError,
    )

    assert code == 1


def test_run_encrypt_rejects_existing_encrypted_file(tmp_path):
    plaintext = tmp_path / "keys.json"
    encrypted = tmp_path / "keys.json.enc"
    plaintext.write_text("{}", encoding="utf-8")
    encrypted.write_text("old", encoding="utf-8")

    code = run_encrypt(
        plaintext=plaintext,
        encrypted=encrypted,
        password="supersecret",
        password_repeat="supersecret",
        key_store_cls=FakeKeyStore,
        unavailable_error_cls=FakeUnavailableError,
    )

    assert code == 1
    assert encrypted.read_text(encoding="utf-8") == "old"


def test_run_encrypt_rejects_mismatch_and_short_password(tmp_path):
    plaintext = tmp_path / "keys.json"
    plaintext.write_text("{}", encoding="utf-8")

    mismatch = run_encrypt(
        plaintext=plaintext,
        encrypted=tmp_path / "a.enc",
        password="supersecret",
        password_repeat="different",
        key_store_cls=FakeKeyStore,
        unavailable_error_cls=FakeUnavailableError,
    )
    short = run_encrypt(
        plaintext=plaintext,
        encrypted=tmp_path / "b.enc",
        password="short",
        password_repeat="short",
        key_store_cls=FakeKeyStore,
        unavailable_error_cls=FakeUnavailableError,
    )

    assert mismatch == 2
    assert short == 2


def test_run_encrypt_surfaces_unavailable_backend(tmp_path):
    plaintext = tmp_path / "keys.json"
    plaintext.write_text("{}", encoding="utf-8")

    code = run_encrypt(
        plaintext=plaintext,
        encrypted=tmp_path / "keys.json.enc",
        password="supersecret",
        password_repeat="supersecret",
        key_store_cls=FailingKeyStore,
        unavailable_error_cls=FakeUnavailableError,
    )

    assert code == 3
