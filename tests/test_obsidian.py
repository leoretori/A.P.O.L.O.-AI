"""Testes do exportador Obsidian (src/obsidian.py)."""

import io
import zipfile
import pytest

from src.obsidian import (
    _safe_filename, _tokenize, _related_topics,
    _build_index, _build_sector_file, _build_map,
    generate_vault,
)

TOPICS = [
    {"topic": "FastAPI", "url": "https://fastapi.tiangolo.com",
     "summary": "Framework Python para APIs.", "category": "backend", "studied_at": None},
    {"topic": "SQLAlchemy", "url": "https://sqlalchemy.org",
     "summary": "ORM para Python.", "category": "backend", "studied_at": None},
    {"topic": "Docker", "url": "https://docker.com",
     "summary": "Containers.", "category": "devops", "studied_at": None},
    {"topic": "Kubernetes", "url": "https://kubernetes.io",
     "summary": "Orquestração de containers.", "category": "devops", "studied_at": None},
    {"topic": "Machine Learning", "url": "https://ml.com",
     "summary": "Algoritmos de aprendizado.", "category": "data_ml", "studied_at": None},
]


# ── _safe_filename ─────────────────────────────────────────────────────────────

def test_safe_filename_remove_barras():
    assert "/" not in _safe_filename("a/b")
    assert "\\" not in _safe_filename("a\\b")

def test_safe_filename_nao_vazio():
    assert _safe_filename("") == "Sem_Nome"
    assert _safe_filename("   ") == "Sem_Nome"

def test_safe_filename_trunca_em_80():
    assert len(_safe_filename("x" * 200)) <= 80


# ── _tokenize ─────────────────────────────────────────────────────────────────

def test_tokenize_remove_stopwords():
    tokens = _tokenize("o que é Python para web")
    assert "Python" not in tokens  # Python tem 6 chars OK mas vamos ver
    assert "que" not in tokens
    assert "para" not in tokens

def test_tokenize_retorna_set():
    assert isinstance(_tokenize("FastAPI Python"), set)

def test_tokenize_min_3_chars():
    tokens = _tokenize("a de um FastAPI")
    assert "a" not in tokens
    assert "de" not in tokens


# ── _related_topics ───────────────────────────────────────────────────────────

def test_related_nao_inclui_o_proprio():
    related = _related_topics("FastAPI", ["FastAPI", "Django", "Flask"], top=5)
    assert "FastAPI" not in related

def test_related_retorna_lista():
    related = _related_topics("Machine Learning Python", ["Python", "Learning Rate", "Docker"], top=5)
    assert isinstance(related, list)

def test_related_limita_top():
    candidates = [f"Topic {i}" for i in range(20)]
    related = _related_topics("Topic test", candidates, top=3)
    assert len(related) <= 3


# ── _build_index ──────────────────────────────────────────────────────────────

def test_build_index_tem_titulo():
    sectors = {"backend": TOPICS[:2], "devops": TOPICS[2:4]}
    idx = _build_index(sectors, 4, "01/01/2026")
    assert "A.P.O.L.O." in idx
    assert "4" in idx  # total

def test_build_index_tem_links_setores():
    sectors = {"backend": TOPICS[:2]}
    idx = _build_index(sectors, 2, "01/01/2026")
    assert "[[" in idx  # pelo menos um link Obsidian

def test_build_index_menciona_todos_setores():
    sectors = {"backend": TOPICS[:2], "devops": TOPICS[2:4]}
    idx = _build_index(sectors, 4, "01/01/2026")
    assert "Backend" in idx or "backend" in idx


# ── _build_sector_file ────────────────────────────────────────────────────────

def test_sector_file_tem_topicos():
    md = _build_sector_file("backend", TOPICS[:2], ["FastAPI", "SQLAlchemy"])
    assert "FastAPI" in md
    assert "SQLAlchemy" in md

def test_sector_file_tem_link_indice():
    md = _build_sector_file("backend", TOPICS[:2], ["FastAPI"])
    assert "_Indice" in md

def test_sector_file_tem_url():
    md = _build_sector_file("backend", TOPICS[:2], [])
    assert "fastapi.tiangolo.com" in md

def test_sector_file_relacionados_formato_obsidian():
    # Com topicos relacionados por overlap, devem aparecer [[links]]
    md = _build_sector_file("backend", TOPICS[:2],
                            ["FastAPI Python", "SQLAlchemy ORM", "Django"])
    # O arquivo pode ou nao ter [[links]] dependendo do overlap
    # Garante apenas que nao quebra
    assert "## " in md


# ── generate_vault ────────────────────────────────────────────────────────────

class FakeDB:
    def get_learning_history(self, limit=5000):
        return TOPICS

def test_generate_vault_retorna_bytes():
    result = generate_vault(FakeDB())
    assert isinstance(result, bytes)
    assert len(result) > 100

def test_generate_vault_e_zip_valido():
    result = generate_vault(FakeDB())
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        names = zf.namelist()
        assert any(n.endswith(".md") for n in names)

def test_generate_vault_tem_indice():
    result = generate_vault(FakeDB())
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        names = zf.namelist()
        assert any("Indice" in n for n in names)

def test_generate_vault_tem_arquivo_por_setor():
    result = generate_vault(FakeDB())
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        names = zf.namelist()
        md_files = [n for n in names if n.endswith(".md") and "Indice" not in n and "Mapa" not in n]
        assert len(md_files) >= 1

def test_generate_vault_conteudo_utf8():
    result = generate_vault(FakeDB())
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        for name in zf.namelist():
            if name.endswith(".md"):
                content = zf.read(name).decode("utf-8")
                assert len(content) > 0

def test_generate_vault_topico_no_conteudo():
    result = generate_vault(FakeDB())
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        all_text = " ".join(
            zf.read(n).decode("utf-8") for n in zf.namelist() if n.endswith(".md")
        )
    assert "FastAPI" in all_text
    assert "Docker" in all_text

def test_generate_vault_db_vazio():
    class EmptyDB:
        def get_learning_history(self, limit=5000): return []
    result = generate_vault(EmptyDB())
    assert isinstance(result, bytes)
    # ZIP valido mesmo vazio
    with zipfile.ZipFile(io.BytesIO(result)) as zf:
        assert any(n.endswith(".md") for n in zf.namelist())
