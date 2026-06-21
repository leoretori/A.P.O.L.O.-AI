"""Testes da memória episódica (src/episodic.py)."""

import pytest
from src.episodic import make_episodic_doc, index_session, _condense


MSGS = [
    {"role": "user", "content": "Como usar FastAPI com SQLAlchemy?"},
    {"role": "assistant", "content": "Você pode usar o SQLAlchemy com FastAPI via depends..."},
    {"role": "user", "content": "E como configurar o Alembic?"},
    {"role": "assistant", "content": "Para o Alembic, crie alembic.ini e rode alembic init..."},
]


def test_make_doc_tem_header_correto():
    doc_id, body, meta = make_episodic_doc("abc123", "Chat sobre FastAPI", MSGS)
    assert doc_id == "episodic_abc123"
    assert body.startswith("# Conversa: Chat sobre FastAPI\n")


def test_make_doc_com_resumo_inclui_resumo():
    _, body, _ = make_episodic_doc("x", "Título", MSGS, summary="Resumo da conversa.")
    assert "Resumo: Resumo da conversa." in body


def test_make_doc_metadata_tem_campos_obrigatorios():
    _, _, meta = make_episodic_doc("sid1", "Título", MSGS)
    assert meta["session_id"] == "sid1"
    assert meta["type"] == "episodic"
    assert meta["title"] == "Título"


def test_make_doc_titulo_longo_truncado():
    titulo_longo = "A" * 200
    _, body, meta = make_episodic_doc("s", titulo_longo, MSGS)
    assert len(meta["title"]) <= 80


def test_make_doc_id_usa_apenas_24_chars_do_session_id():
    sid = "a" * 40
    doc_id, _, _ = make_episodic_doc(sid, "t", MSGS)
    assert doc_id == f"episodic_{'a'*24}"


def test_condense_inclui_papeis():
    text = _condense(MSGS)
    assert "Usuário:" in text
    assert "A.P.O.L.O.:" in text


def test_condense_respeita_max_chars():
    msgs = [{"role": "user", "content": "x" * 5000}] * 10
    text = _condense(msgs)
    from src.episodic import MAX_SESSION_CHARS
    assert len(text) <= MAX_SESSION_CHARS


def test_index_session_ignora_sessao_curta():
    class FakeRag:
        called = False
        def add_example(self, *a, **k): self.called = True

    rag = FakeRag()
    result = index_session("s", "t", MSGS[:2], rag)  # só 2 msgs
    assert result is False
    assert not rag.called


def test_index_session_indexa_sessao_suficiente():
    class FakeRag:
        called = False
        def add_example(self, content, doc_id, metadata=None):
            self.called = True

    rag = FakeRag()
    result = index_session("sess1", "FastAPI", MSGS, rag)
    assert result is True
    assert rag.called


def test_index_session_captura_excecao_do_rag():
    class BrokenRag:
        def add_example(self, *a, **k): raise RuntimeError("falha")

    result = index_session("s", "t", MSGS, BrokenRag())
    assert result is False


def test_index_session_mensagens_vazias():
    class FakeRag:
        def add_example(self, *a, **k): pass

    assert index_session("s", "t", [], FakeRag()) is False
    assert index_session("s", "t", None, FakeRag()) is False
