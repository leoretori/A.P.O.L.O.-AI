"""Teste da deduplicação exata do índice de recall (ChromaDB).

Usa uma coleção fake para exercitar a lógica de `RAGManager.dedup_exact` sem
precisar subir o ChromaDB real."""

from src.rag import RAGManager


class _FakeCollection:
    def __init__(self, ids, docs):
        self._ids, self._docs = ids, docs
        self.deleted = []

    def get(self, include=None):
        return {"ids": self._ids, "documents": self._docs}

    def delete(self, ids):
        self.deleted = list(ids)


class _Obj:
    pass


def _with(ids, docs):
    o = _Obj()
    o.collection = _FakeCollection(ids, docs)
    return o


def test_removes_exact_duplicates():
    o = _with(["1", "2", "3"], ["mesmo texto", "mesmo texto", "outro"])
    n = RAGManager.dedup_exact(o)
    assert n == 1
    assert o.collection.deleted == ["2"]


def test_dry_run_counts_but_keeps():
    o = _with(["1", "2"], ["x", "x"])
    n = RAGManager.dedup_exact(o, dry_run=True)
    assert n == 1
    assert o.collection.deleted == []


def test_no_duplicates():
    o = _with(["1", "2"], ["a", "b"])
    assert RAGManager.dedup_exact(o) == 0


def test_forget_topic_remove_docs_do_topico():
    docs = [
        "# Redis Streams\nFonte: u1\n\ncorpo a",
        "# Kafka\nFonte: u2\n\ncorpo b",
        "# Redis Streams\nFonte: u3\n\ncorpo c (re-estudo)",
    ]
    o = _with(["1", "2", "3"], docs)
    n = RAGManager.forget_topic(o, "Redis Streams")
    assert n == 2
    assert set(o.collection.deleted) == {"1", "3"}  # só os do tópico Redis Streams


def test_forget_topic_inexistente():
    o = _with(["1"], ["# Outro\nFonte: u\n\nx"])
    assert RAGManager.forget_topic(o, "Nada") == 0
