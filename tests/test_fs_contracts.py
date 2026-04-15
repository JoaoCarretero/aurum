"""Contract tests for core.fs — robust_rmtree + atomic_write."""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

import pytest

from core.fs import atomic_write, robust_rmtree


@pytest.fixture
def tmp_dir(tmp_path) -> Path:
    return tmp_path / "target"


class TestRobustRmtree:
    def test_removes_empty_directory(self, tmp_dir):
        tmp_dir.mkdir()
        assert robust_rmtree(tmp_dir) is True
        assert not tmp_dir.exists()

    def test_removes_nested_tree(self, tmp_dir):
        (tmp_dir / "a" / "b" / "c").mkdir(parents=True)
        (tmp_dir / "a" / "file.txt").write_text("hello")
        (tmp_dir / "a" / "b" / "deep.txt").write_text("world")
        assert robust_rmtree(tmp_dir) is True
        assert not tmp_dir.exists()

    def test_returns_true_when_target_missing(self, tmp_dir):
        # Ausente já = sucesso (idempotente)
        assert not tmp_dir.exists()
        assert robust_rmtree(tmp_dir) is True

    def test_handles_readonly_files(self, tmp_dir):
        tmp_dir.mkdir()
        readonly = tmp_dir / "locked.txt"
        readonly.write_text("protected")
        os.chmod(readonly, stat.S_IREAD)
        try:
            assert robust_rmtree(tmp_dir) is True
            assert not tmp_dir.exists()
        finally:
            # Se falhar, restaura perm pra que o tmp_path cleanup do pytest consiga remover
            if readonly.exists():
                os.chmod(readonly, stat.S_IWRITE)

    def test_never_raises(self, tmp_dir):
        # Mesmo passando path inválido, não deve explodir
        result = robust_rmtree(Path("/nonexistent/path/that/does/not/exist"))
        assert result is True  # path ausente = sucesso

    def test_accepts_path_object(self, tmp_dir):
        tmp_dir.mkdir()
        (tmp_dir / "f.txt").write_text("x")
        # Assinatura exige Path, não str — confirma
        robust_rmtree(tmp_dir)
        assert not tmp_dir.exists()


class TestAtomicWrite:
    def test_writes_file_content(self, tmp_path):
        target = tmp_path / "out.txt"
        atomic_write(target, "hello world")
        assert target.read_text(encoding="utf-8") == "hello world"

    def test_overwrites_existing_file(self, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("original", encoding="utf-8")
        atomic_write(target, "replaced")
        assert target.read_text(encoding="utf-8") == "replaced"

    def test_tmp_file_cleaned_up(self, tmp_path):
        target = tmp_path / "out.txt"
        atomic_write(target, "data")
        # The .tmp sibling should not remain
        tmp_sibling = target.with_suffix(target.suffix + ".tmp")
        assert not tmp_sibling.exists()

    def test_utf8_content(self, tmp_path):
        # Acentos + emoji-like unicode devem preservar
        target = tmp_path / "out.txt"
        content = "ção — ñ — 日本"
        atomic_write(target, content)
        assert target.read_text(encoding="utf-8") == content

    def test_atomic_preserves_original_on_content_type_error(self, tmp_path):
        # atomic_write espera str; passar bytes deve falhar antes do rename
        target = tmp_path / "out.txt"
        target.write_text("original", encoding="utf-8")
        with pytest.raises((TypeError, AttributeError)):
            atomic_write(target, b"not a string")  # type: ignore[arg-type]
        # Original sobrevive
        assert target.read_text(encoding="utf-8") == "original"
