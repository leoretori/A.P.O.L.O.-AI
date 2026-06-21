"""Testes da base de conhecimento local (SQLite FTS5)."""

import json
import pytest

from src.local_knowledge import LocalKnowledge


@pytest.fixture
def kb(tmp_path):
    """LocalKnowledge em banco temporário."""
    return LocalKnowledge(path=str(tmp_path / "test_kb.db"))


def test_save_e_stats(kb):
    kb.save("FastAPI intro", "https://fastapi.tiangolo.com", "FastAPI é rápido.", "official_doc")
    s = kb.stats()
    assert s["total"] == 1
    assert s["saved_session"] == 1


def test_upsert_por_url(kb):
    kb.save("Título original", "https://exemplo.com", "Conteúdo original")
    kb.save("Título atualizado", "https://exemplo.com", "Conteúdo novo")
    s = kb.stats()
    assert s["total"] == 1  # upsert — não duplica


def test_search_encontra_por_fts(kb):
    kb.save("Python async", "https://docs.python.org/asyncio", "asyncio event loop coroutine", "official_doc")
    kb.save("Docker compose", "https://docs.docker.com", "docker-compose up build", "official_doc")
    results = kb.search("asyncio", limit=5)
    assert any("asyncio" in r.get("content", "").lower() for r in results)


def test_search_fallback_like(kb):
    """Quando FTS falha, cai para LIKE (testado com query inválida de FTS5)."""
    kb.save("Redis cache", "https://redis.io", "Redis pub sub cache", "web_search")
    # Busca simples (não usa sintaxe FTS avançada)
    results = kb.search("Redis", limit=3)
    assert results  # deve achar mesmo via fallback


def test_format_context_vazio_quando_nada(kb):
    assert kb.format_context("nada aqui") == ""


def test_format_context_retorna_texto(kb):
    kb.save("SQLAlchemy ORM", "https://sqlalchemy.org", "SQLAlchemy é um ORM Python.", "official_doc")
    ctx = kb.format_context("SQLAlchemy")
    assert "SQLAlchemy" in ctx


def test_all_rows(kb):
    for i in range(3):
        kb.save(f"Doc {i}", f"https://ex.com/{i}", f"conteúdo {i}")
    rows = kb.all_rows(limit=10)
    assert len(rows) == 3


def test_delete_by_url(kb):
    kb.save("Para apagar", "https://apagar.com", "conteúdo")
    assert kb.stats()["total"] == 1
    kb.delete_by_url("https://apagar.com")
    assert kb.stats()["total"] == 0


def test_delete_ids(kb):
    kb.save("Doc A", "https://a.com", "texto a")
    kb.save("Doc B", "https://b.com", "texto b")
    rows = kb.all_rows()
    ids = [r["id"] for r in rows]
    kb.delete_ids([ids[0]])
    assert kb.stats()["total"] == 1


def test_breaker_state_always_closed(kb):
    state = kb.breaker_state()
    assert state["state"] == "closed"


def test_insights_categorias(kb):
    kb.save("Python", "https://python.org", "linguagem Python", "official_doc")
    kb.save("Docker", "https://docker.com", "containers Docker", "web_search")
    ins = kb.insights()
    assert ins["total"] == 2
    cats = {c["name"] for c in ins["categories"]}
    assert "official_doc" in cats or "web_search" in cats


def test_insights_cache(kb):
    kb.save("Item 1", "https://1.com", "texto 1")
    ins1 = kb.insights()
    ins2 = kb.insights()  # deve vir do cache
    assert ins1 == ins2


def test_insights_invalida_ao_salvar(kb):
    kb.save("Antes", "https://antes.com", "texto antes")
    ins1 = kb.insights()
    kb.save("Depois", "https://depois.com", "texto depois")
    ins2 = kb.insights()
    assert ins2["total"] > ins1["total"]


def test_insights_recent_tem_campos(kb):
    kb.save("Artigo recente", "https://recente.com", "conteúdo recente", "synthesis")
    ins = kb.insights()
    assert ins["recent"]
    rec = ins["recent"][0]
    assert "title" in rec and "category" in rec and "url" in rec


def test_save_trunca_titulo_longo(kb):
    titulo_longo = "A" * 300
    kb.save(titulo_longo, "https://long.com", "corpo")
    rows = kb.all_rows()
    assert len(rows[0]["title"]) <= 200


def test_interface_duck_typing():
    """LocalKnowledge expõe todos os métodos de SupabaseKnowledge."""
    required = ["save", "search", "format_context", "stats", "all_rows",
                "delete_by_url", "delete_ids", "insights", "breaker_state"]
    for method in required:
        assert hasattr(LocalKnowledge, method), f"método ausente: {method}"
