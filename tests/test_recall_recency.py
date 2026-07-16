"""Recência no recall semântico (ChromaDB): memória recém-estudada pesa mais."""

from datetime import datetime, timezone, timedelta
from src.rag import RAGManager, _recency_from_iso


class _FakeCollection:
    """Coleção fake que devolve dois docs com mesma distância mas datas diferentes."""
    def __init__(self, docs, dists, metas):
        self._docs, self._dists, self._metas = docs, dists, metas

    def count(self):
        return len(self._docs)

    def query(self, query_texts=None, n_results=4, include=None):
        return {
            "documents": [self._docs],
            "distances": [self._dists],
            "metadatas": [self._metas],
        }


class _Obj:
    pass


def _rag_with(docs, dists, metas):
    o = _Obj()
    o.collection = _FakeCollection(docs, dists, metas)
    return o


def test_recall_recencia_desempata():
    agora = datetime.now(timezone.utc).isoformat()
    antigo = (datetime.now(timezone.utc) - timedelta(days=300)).isoformat()
    docs = [
        "# Redis antigo\nFonte: u1\n\nredis cache mensageria",
        "# Redis novo\nFonte: u2\n\nredis cache stream dados",
    ]
    dists = [0.4, 0.4]  # mesma relevância vetorial
    metas = [{"studied_at": antigo}, {"studied_at": agora}]
    out = RAGManager.recall(_rag_with(docs, dists, metas), "redis", n_results=2)
    # Mesma relevância e lexical equivalente → o mais recente sobe.
    assert out[0]["title"] == "Redis novo"


def test_recall_sem_metadata_nao_quebra():
    docs = ["# Tema\nFonte: u\n\ncorpo qualquer sobre python"]
    out = RAGManager.recall(_rag_with(docs, [0.3], [None]), "python", n_results=1)
    assert out and out[0]["title"] == "Tema"
    assert out[0]["recency"] == 0.0


def test_recency_from_iso():
    agora = datetime.now(timezone.utc).isoformat()
    assert _recency_from_iso(agora) > 0.9
    assert _recency_from_iso(None) == 0.0
    assert _recency_from_iso("lixo-invalido") == 0.0


# ── Fidelidade à fonte no recall (P2.1) ─────────────────────────
def test_recall_propaga_verified_do_metadata():
    docs = [
        "# Reprovado\nFonte: u1\n\nredis cache mensageria distribuida em cluster",
        "# Verificado\nFonte: u2\n\nredis cache mensageria pubsub replicado",
    ]
    dists = [0.4, 0.4]
    metas = [{"verified": "failed"}, {"verified": "verified"}]
    out = RAGManager.recall(_rag_with(docs, dists, metas), "redis cache mensageria",
                            n_results=2)
    # Mesma relevância/lexical → o verificado sobe por causa do w_verified fixo em recall().
    assert out[0]["title"] == "Verificado"
    assert {c["title"]: c["verified"] for c in out} == \
        {"Verificado": "verified", "Reprovado": "failed"}


def test_recall_sem_verified_no_metadata_fica_none():
    docs = ["# Tema\nFonte: u\n\ncorpo qualquer sobre python"]
    out = RAGManager.recall(_rag_with(docs, [0.3], [None]), "python", n_results=1)
    assert out[0]["verified"] is None
