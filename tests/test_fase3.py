"""Testes da Fase 3 — Percepção e Voz (DOCX, Whisper, chunking)."""

import pytest


# ── DOCX ──────────────────────────────────────────────────────────────────────

def test_extract_docx_sem_python_docx(monkeypatch):
    """Se python-docx não estiver instalado, deve lançar ModuleNotFoundError."""
    import builtins
    real_import = builtins.__import__
    def _block(name, *a, **k):
        if name == "docx":
            raise ModuleNotFoundError("python-docx não instalado")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _block)
    from src.ingest import extract_docx_text
    with pytest.raises(ModuleNotFoundError):
        extract_docx_text(b"qualquer coisa")


def test_extract_pdf_sem_pypdf(monkeypatch):
    """Se pypdf não estiver instalado, deve lançar ModuleNotFoundError."""
    import builtins
    real_import = builtins.__import__
    def _block(name, *a, **k):
        if name == "pypdf":
            raise ModuleNotFoundError("pypdf não instalado")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _block)
    from src.ingest import extract_pdf_text
    with pytest.raises(ModuleNotFoundError):
        extract_pdf_text(b"qualquer coisa")


# ── Whisper STT ───────────────────────────────────────────────────────────────

def test_whisper_is_available_false_sem_modulo(monkeypatch):
    """is_available() retorna False quando faster-whisper não está instalado."""
    import builtins
    real_import = builtins.__import__
    def _block(name, *a, **k):
        if "faster_whisper" in name:
            raise ImportError("faster-whisper não instalado")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _block)
    # Força reimport do módulo para testar a função com o mock ativo
    import importlib, src.whisper_stt as w
    importlib.reload(w)
    assert w.is_available() is False


def test_whisper_transcribe_retorna_none_sem_modulo(monkeypatch):
    """transcribe() retorna None graciosamente quando faster-whisper não existe."""
    import src.whisper_stt as w
    # Garante que _model está None (nenhum modelo carregado)
    w._model = None
    w._model_size = None

    def _fake_load(size):
        raise ImportError("faster-whisper não instalado")
    monkeypatch.setattr(w, "_load", _fake_load)
    result = w.transcribe(b"\x00" * 200)
    assert result is None


def test_whisper_transcribe_bytes_curtos():
    """transcribe() retorna None para bytes insuficientes (< 100)."""
    from src.whisper_stt import transcribe
    assert transcribe(b"\x00" * 50) is None
    assert transcribe(b"") is None
    assert transcribe(None) is None  # type: ignore


# ── Ingestor com chunking ─────────────────────────────────────────────────────

def test_ingest_chunking_overlap():
    """chunk_text divide documentos longos com overlap correto."""
    from src.ingest import chunk_text
    texto = "palavra " * 500  # ~4000 chars
    chunks = chunk_text(texto, size=200, overlap=50)
    assert len(chunks) > 1
    # Verifica overlap: final do chunk i deve aparecer no início do chunk i+1
    for a, b in zip(chunks, chunks[1:]):
        # Pega últimas 30 chars do chunk anterior (sem whitespace)
        tail = a.strip()[-30:]
        assert any(w in b for w in tail.split()[:3]), "overlap ausente entre chunks"


def test_ingest_documento_curto_nao_chunka():
    """Documentos curtos são retornados como chunk único."""
    from src.ingest import chunk_text
    texto = "texto curto"
    chunks = chunk_text(texto, size=200, overlap=50)
    assert len(chunks) == 1
    assert chunks[0] == texto


def test_ingest_document_ingestor_texto(tmp_path):
    """DocumentIngestor.ingest_text indexa no RAG e retorna ok=True."""
    from src.ingest import DocumentIngestor

    class FakeRag:
        docs = []
        def add_example(self, content, doc_id, metadata=None):
            self.docs.append((doc_id, content))

    rag = FakeRag()
    ingestor = DocumentIngestor(rag=rag)
    result = ingestor.ingest_text("teste.py", "def hello():\n    print('hello world')\n" * 5)
    assert result["ok"] is True
    assert result["chunks"] >= 1
    assert len(rag.docs) >= 1
