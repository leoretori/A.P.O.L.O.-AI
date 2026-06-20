"""Testes do reranker híbrido de recall (vetorial + lexical + dedup)."""

from src.rag import _tokenize, _lexical_overlap, _rerank


def test_tokenize_remove_stopwords_e_curtos():
    toks = _tokenize("Como funciona o RAG em Python?")
    assert "funciona" in toks and "rag" in toks and "python" in toks
    assert "como" not in toks  # stopword
    assert "o" not in toks     # curto/stopword
    assert "em" not in toks


def test_lexical_overlap_total_e_parcial():
    q = _tokenize("indexação vetorial chromadb")
    assert _lexical_overlap(q, "ChromaDB faz indexação vetorial") == 1.0
    assert _lexical_overlap(q, "indexação de documentos") == round(1/3, 10) or \
           abs(_lexical_overlap(q, "indexação de documentos") - 1/3) < 1e-9
    assert _lexical_overlap(q, "assunto totalmente diferente") == 0.0


def test_rerank_promove_match_lexical():
    """Dois candidatos com relevância vetorial parecida; o que casa lexicalmente sobe."""
    cands = [
        {"title": "Genérico", "snippet": "texto sobre cebolas e cenouras", "relevance": 0.55},
        {"title": "Kafka streaming", "snippet": "Apache Kafka para streaming de eventos", "relevance": 0.52},
    ]
    out = _rerank("Apache Kafka streaming de eventos", cands, top=2)
    assert out[0]["title"] == "Kafka streaming"
    assert out[0]["score"] > out[1]["score"]


def test_rerank_remove_titulo_duplicado():
    cands = [
        {"title": "Redis", "snippet": "cache em memória A", "relevance": 0.9},
        {"title": "Redis", "snippet": "cache em memória B", "relevance": 0.8},
        {"title": "Postgres", "snippet": "banco relacional", "relevance": 0.7},
    ]
    out = _rerank("redis cache", cands, top=5)
    titles = [c["title"] for c in out]
    assert titles.count("Redis") == 1
    assert "Postgres" in titles


def test_rerank_remove_quase_duplicata_de_conteudo():
    cands = [
        {"title": "A", "snippet": "asyncio permite concorrência cooperativa em python moderno", "relevance": 0.9},
        {"title": "B", "snippet": "asyncio permite concorrência cooperativa em python moderno!", "relevance": 0.85},
        {"title": "C", "snippet": "kubernetes orquestra contêineres em produção", "relevance": 0.6},
    ]
    out = _rerank("python asyncio", cands, top=5)
    snippets = " ".join(c["title"] for c in out)
    # A e B são quase idênticos → só um sobrevive; C entra.
    assert len(out) == 2
    assert "C" in [c["title"] for c in out]


def test_rerank_respeita_top():
    palavras = ["fastapi", "kubernetes", "postgres", "kafka", "redis",
                "terraform", "airflow", "pytest", "asyncio", "graphql"]
    cands = [{"title": f"t{i}", "snippet": f"assunto sobre {p} avançado", "relevance": 0.5 + i / 100}
             for i, p in enumerate(palavras)]
    assert len(_rerank("tecnologia", cands, top=3)) == 3


def test_rerank_lida_com_relevance_none():
    cands = [
        {"title": "Sem dist", "snippet": "fastapi rotas async", "relevance": None},
        {"title": "Outro", "snippet": "tema irrelevante qualquer", "relevance": None},
    ]
    out = _rerank("fastapi rotas async", cands, top=2)
    assert out[0]["title"] == "Sem dist"  # ganhou no lexical, mesmo sem relevância vetorial


# ── Rerank aplicado às linhas do Supabase (knowledge) ─────────
def test_rerank_rows_preserva_campos_e_reordena():
    from src.knowledge import _rerank_rows
    rows = [
        {"title": "Cebolas", "url": "u1", "content": "receita de cebolas caramelizadas", "category": "web"},
        {"title": "Apache Kafka", "url": "u2", "content": "Kafka para streaming de eventos em produção", "category": "tech_trend"},
    ]
    out = _rerank_rows("Apache Kafka streaming eventos", rows, limit=2)
    # O match lexical sobe e os campos originais (url/category) seguem intactos.
    assert out[0]["title"] == "Apache Kafka"
    assert out[0]["url"] == "u2" and out[0]["category"] == "tech_trend"
    # Sem campos auxiliares vazando para o consumidor.
    assert "snippet" not in out[0] and "score" not in out[0]


def test_rerank_rows_vazio():
    from src.knowledge import _rerank_rows
    assert _rerank_rows("qualquer", [], limit=3) == []


# ── Boost por recência ────────────────────────────────────────
def test_rerank_recencia_desempata():
    """Dois itens com mesmo lexical/vetorial; o mais recente vence quando w_recency>0."""
    cands = [
        {"title": "Antigo", "snippet": "fastapi async rotas", "relevance": 0.6, "recency": 0.1},
        {"title": "Recente", "snippet": "fastapi async rotas", "relevance": 0.6, "recency": 0.95},
    ]
    out = _rerank("fastapi async rotas", cands, top=2, w_recency=0.2)
    assert out[0]["title"] == "Recente"


def test_rerank_sem_recencia_ignora_campo():
    """Com w_recency=0 (padrão), o campo recency não altera o score (compat rag.recall)."""
    cands = [
        {"title": "A", "snippet": "kafka streaming em producao com java", "relevance": 0.6, "recency": 0.0},
        {"title": "B", "snippet": "kafka streaming usando python e docker", "relevance": 0.6, "recency": 0.99},
    ]
    out = _rerank("kafka streaming", cands, top=2)  # w_recency=0
    assert len(out) == 2
    assert out[0]["score"] == out[1]["score"]  # recency ignorada sem peso


def test_recency_score_decai_com_idade():
    from src.knowledge import _recency_score
    from datetime import datetime, timezone, timedelta
    agora = datetime.now(timezone.utc).isoformat()
    antigo = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert _recency_score(agora) > 0.9          # recém-atualizado ≈ 1
    assert abs(_recency_score(antigo) - 0.5) < 0.05  # 1 meia-vida ≈ 0.5
    assert _recency_score(None) == 0.0
