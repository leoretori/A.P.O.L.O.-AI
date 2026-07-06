"""MemoryFabric (Épico 2.1) — a porta única sobre RAG + base + lições.
Usa fakes que imitam as interfaces reais (rag.add_example/recall,
knowledge.save/search, lessons.add/relevant)."""
from src.memory import KINDS, MemoryFabric, MemoryHit


class FakeRag:
    def __init__(self):
        self.added = []
    def add_example(self, content, doc_id, metadata=None):
        self.added.append((content, doc_id, metadata))
    def recall(self, query, n):
        return [{"title": "AsyncIO", "snippet": "corrotinas em python",
                 "source": "doc1", "relevance": 0.8}][:n]


class FakeKnowledge:
    def __init__(self):
        self.saved = []
    def save(self, title, url, content, category="web", tags=None):
        self.saved.append({"title": title, "url": url, "content": content,
                           "category": category, "tags": tags})
    def search(self, query, limit):
        return [{"id": 1, "title": "Kafka", "content": "streaming distribuído",
                 "url": "http://k", "category": "web", "updated_at": "2026-07-05T10:00:00",
                 "tags": '["stream"]'}][:limit]


class FakeLessons:
    def __init__(self):
        self.added = []
    def add(self, task, lesson, kind="reflection"):
        self.added.append((task, lesson, kind))
        return len(self.added)
    def relevant(self, task, limit):
        return [{"id": 1, "task": "refatorar", "lesson": "rode os testes antes",
                 "kind": "regression", "created_at": "2026-07-05T09:00:00"}][:limit]


def _fabric():
    return MemoryFabric(rag=FakeRag(), knowledge=FakeKnowledge(), lessons=FakeLessons())


# ── remember ──────────────────────────────────────────────────
def test_remember_semantic_vai_para_o_rag():
    f = _fabric()
    assert f.remember("corrotinas", kind="semantic", title="AsyncIO", tags=["py"]) is True
    content, doc_id, meta = f.rag.added[0]
    assert content == "corrotinas"
    assert meta["title"] == "AsyncIO" and meta["tags"] == "py"


def test_remember_knowledge_vai_para_a_base():
    f = _fabric()
    assert f.remember("streaming", kind="knowledge", title="Kafka",
                      source="http://k", tags=["stream"]) is True
    assert f.knowledge.saved[0]["title"] == "Kafka"
    assert f.knowledge.saved[0]["url"] == "http://k"


def test_remember_lesson_vai_para_lessons():
    f = _fabric()
    assert f.remember("rode os testes antes", kind="lesson", task="refatorar") is True
    assert f.lessons.added[0] == ("refatorar", "rode os testes antes", "reflection")


def test_remember_ignora_kind_invalido_e_texto_vazio():
    f = _fabric()
    assert f.remember("", kind="semantic") is False
    assert f.remember("algo", kind="inexistente") is False


def test_remember_backend_ausente_retorna_false():
    f = MemoryFabric(rag=None, knowledge=None, lessons=None)
    assert f.remember("x", kind="semantic") is False
    assert f.remember("x", kind="knowledge") is False


def test_doc_id_estavel_por_conteudo_quando_sem_source():
    f = _fabric()
    f.remember("mesmo texto", kind="semantic")
    f.remember("mesmo texto", kind="semantic")
    assert f.rag.added[0][1] == f.rag.added[1][1]   # mesmo id → upsert, sem duplicar


# ── recall ────────────────────────────────────────────────────
def test_recall_por_kind_retorna_so_aquela_memoria():
    f = _fabric()
    hits = f.recall("python", kind="semantic")
    assert all(isinstance(h, MemoryHit) for h in hits)
    assert {h.kind for h in hits} == {"semantic"}
    assert hits[0].title == "AsyncIO" and hits[0].score == 0.8


def test_recall_unificado_consulta_todas_as_memorias():
    f = _fabric()
    hits = f.recall("qualquer", kind=None, limit=2)
    kinds = {h.kind for h in hits}
    assert kinds == set(KINDS)                 # semantic + knowledge + lesson
    # a base normaliza tags de JSON e a lição carimba o kind como tag
    kh = next(h for h in hits if h.kind == "knowledge")
    assert kh.tags == ["stream"] and kh.when == "2026-07-05T10:00:00"
    lh = next(h for h in hits if h.kind == "lesson")
    assert lh.tags == ["regression"]


def test_recall_query_vazia_retorna_vazio():
    assert _fabric().recall("   ") == []


def test_recall_backend_que_explode_nao_derruba_os_outros():
    class BoomRag:
        def recall(self, q, n): raise RuntimeError("índice corrompido")
    f = MemoryFabric(rag=BoomRag(), knowledge=FakeKnowledge(), lessons=FakeLessons())
    hits = f.recall("x")                        # semantic falha, os outros respondem
    assert {h.kind for h in hits} == {"knowledge", "lesson"}


def test_recall_text_formata_bloco_para_prompt():
    f = _fabric()
    txt = f.recall_text("python", kind="semantic")
    assert "AsyncIO" in txt and txt.startswith("🧠")


def test_stats_reporta_backends_conectados():
    assert _fabric().stats() == {"semantic": True, "knowledge": True, "lesson": True}
    assert MemoryFabric().stats() == {"semantic": False, "knowledge": False, "lesson": False}
