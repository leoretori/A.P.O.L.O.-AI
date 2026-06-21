"""Testes do analisador de repositórios (src/repo_indexer.py)."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from src.repo_indexer import (
    _extract_repo_name, _extract_owner, _is_text_file,
    _doc_id, collect_files, index_file,
)


# ── _extract_repo_name ────────────────────────────────────────────────────────

def test_extract_repo_name_https():
    assert _extract_repo_name("https://github.com/usuario/meu-repo") == "meu-repo"

def test_extract_repo_name_com_git():
    assert _extract_repo_name("https://github.com/x/proj.git") == "proj"

def test_extract_repo_name_trailing_slash():
    assert _extract_repo_name("https://github.com/x/proj/") == "proj"


# ── _extract_owner ────────────────────────────────────────────────────────────

def test_extract_owner():
    assert _extract_owner("https://github.com/fastapi/fastapi") == "fastapi"

def test_extract_owner_unknown():
    assert _extract_owner("https://exemplo.com/repo") == "unknown"


# ── _is_text_file ─────────────────────────────────────────────────────────────

def test_is_text_file_python(tmp_path):
    f = tmp_path / "main.py"
    f.write_text("print('hi')")
    assert _is_text_file(f) is True

def test_is_text_file_markdown(tmp_path):
    f = tmp_path / "README.md"
    f.write_text("# Hello")
    assert _is_text_file(f) is True

def test_is_text_file_dockerfile(tmp_path):
    f = tmp_path / "Dockerfile"
    f.write_text("FROM python:3.12")
    assert _is_text_file(f) is True

def test_is_text_file_binary_skipped(tmp_path):
    f = tmp_path / "image.png"
    f.write_bytes(b"\x89PNG\r\n")
    assert _is_text_file(f) is False

def test_is_text_file_exe_skipped(tmp_path):
    f = tmp_path / "app.exe"
    f.write_bytes(b"MZ\x90\x00")
    assert _is_text_file(f) is False


# ── _doc_id ───────────────────────────────────────────────────────────────────

def test_doc_id_sem_chunk():
    doc_id = _doc_id("fastapi", "main.py")
    assert doc_id.startswith("repo_")
    assert not doc_id.endswith(("_c0","_c1","_c2","_c3"))  # sem sufixo de chunk

def test_doc_id_com_chunk():
    doc_id = _doc_id("fastapi", "main.py", chunk_idx=3)
    assert doc_id.endswith("_c3")

def test_doc_id_estavel():
    assert _doc_id("repo", "a.py") == _doc_id("repo", "a.py")


# ── collect_files ─────────────────────────────────────────────────────────────

@pytest.fixture
def sample_repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass")
    (tmp_path / "src" / "utils.py").write_text("def util(): pass")
    (tmp_path / "README.md").write_text("# Projeto")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("ignored")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "c.pyc").write_bytes(b"\x00")
    (tmp_path / "app.exe").write_bytes(b"MZ")
    return tmp_path

def test_collect_files_pega_codigo(sample_repo):
    files = collect_files(str(sample_repo))
    paths = [f[0] for f in files]
    assert "src/main.py" in paths
    assert "src/utils.py" in paths

def test_collect_files_pega_readme(sample_repo):
    files = collect_files(str(sample_repo))
    paths = [f[0] for f in files]
    assert "README.md" in paths

def test_collect_files_ignora_node_modules(sample_repo):
    files = collect_files(str(sample_repo))
    paths = [f[0] for f in files]
    assert not any("node_modules" in p for p in paths)

def test_collect_files_ignora_binarios(sample_repo):
    files = collect_files(str(sample_repo))
    paths = [f[0] for f in files]
    assert not any(".exe" in p or ".pyc" in p for p in paths)

def test_collect_files_retorna_conteudo(sample_repo):
    files = collect_files(str(sample_repo))
    by_path = {f[0]: f[1] for f in files}
    assert "def main(): pass" in by_path.get("src/main.py", "")


# ── index_file ────────────────────────────────────────────────────────────────

class FakeRag:
    def __init__(self):
        self.docs = []
    def add_example(self, content, doc_id, metadata=None):
        self.docs.append({"content": content, "id": doc_id, "meta": metadata})

def test_index_file_arquivo_pequeno():
    rag = FakeRag()
    n = index_file("src/main.py", "def hello(): pass", "myrepo",
                   "https://github.com/x/myrepo", rag)
    assert n == 1
    assert len(rag.docs) == 1
    assert "myrepo/src/main.py" in rag.docs[0]["content"]
    assert "def hello()" in rag.docs[0]["content"]

def test_index_file_tem_url_no_doc():
    rag = FakeRag()
    index_file("app.py", "x = 1", "proj", "https://github.com/u/proj", rag)
    assert "github.com/u/proj" in rag.docs[0]["content"]

def test_index_file_metadata_correta():
    rag = FakeRag()
    index_file("main.py", "pass", "repo", "https://github.com/u/repo", rag)
    meta = rag.docs[0]["meta"]
    assert meta["repo"] == "repo"
    assert meta["file_path"] == "main.py"
    assert meta["type"] == "repo_file"

def test_index_file_arquivo_grande_chunka():
    rag = FakeRag()
    content = "x = 1\n" * 1000  # ~6000 chars
    n = index_file("big.py", content, "repo", "https://github.com/u/repo", rag)
    assert n > 1
    assert len(rag.docs) == n
    # Todos os chunks têm referência ao arquivo
    for doc in rag.docs:
        assert "big.py" in doc["content"]
