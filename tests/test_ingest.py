"""Testes da ingestão de documentos (fatiamento + indexação)."""

from src.ingest import DocumentIngestor, chunk_text


def test_chunk_texto_curto_um_pedaco():
    chunks = chunk_text("linha curta de teste")
    assert chunks == ["linha curta de teste"]


def test_chunk_respeita_tamanho_e_overlap():
    text = "x" * 4000
    chunks = chunk_text(text, size=1500, overlap=150)
    assert len(chunks) >= 3
    assert all(len(c) <= 1500 for c in chunks)


def test_chunk_vazio():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


class _FakeRag:
    def __init__(self):
        self.added = []

    def add_example(self, content, doc_id):
        self.added.append((doc_id, content))


class _FakeKnowledge:
    def __init__(self):
        self.saved = []

    def save(self, title, url, content, category="web", tags=None):
        self.saved.append({"title": title, "url": url, "category": category, "tags": tags})


def test_ingest_indexa_chunks_e_salva():
    rag, kb = _FakeRag(), _FakeKnowledge()
    ing = DocumentIngestor(rag=rag, knowledge_db=kb)
    res = ing.ingest_text("notas.md", "Conteúdo de teste do documento. " * 80)

    assert res["ok"] is True
    assert res["filename"] == "notas.md"
    assert res["chunks"] >= 1
    assert len(rag.added) == res["chunks"]
    # Um registro no Supabase, na categoria de documento do usuário, com tag de setor.
    assert len(kb.saved) == 1
    assert kb.saved[0]["category"] == "user_doc"
    assert isinstance(kb.saved[0]["tags"], list) and kb.saved[0]["tags"]


def test_ingest_texto_curto_rejeitado():
    res = DocumentIngestor(rag=_FakeRag()).ingest_text("vazio.txt", "oi")
    assert res["ok"] is False
