"""Testes dos endpoints da Visão útil (M22, Épico 22.1) — /api/vision/*.
Adiados a pedido do Leo ("testes fazemos depois") e fechados agora (2026-07-15)."""
import base64

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.vision import router
from src import runtime as rt


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def teardown_function(_fn):
    rt.configure(get_vision_model=lambda: None, ingestor=None)


# ── GET /api/vision/status ──────────────────────────────────────
def test_status_sem_modelo_de_visao():
    rt.configure(get_vision_model=lambda: None)
    r = _client().get("/api/vision/status")
    assert r.status_code == 200
    body = r.json()
    assert body["vision"] is False and body["vision_model"] is None


def test_status_com_modelo_de_visao():
    rt.configure(get_vision_model=lambda: "llava")
    r = _client().get("/api/vision/status")
    body = r.json()
    assert body["vision"] is True and body["vision_model"] == "llava"


# ── POST /api/vision/screen ─────────────────────────────────────
def test_screen_sem_descrever_nao_chama_modelo(monkeypatch):
    from PIL import Image
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: Image.new("RGB", (100, 60)))
    rt.configure(get_vision_model=lambda: "llava")

    r = _client().post("/api/vision/screen", json={"describe": False})
    body = r.json()
    assert body["ok"] is True
    assert body["size"] == [100, 60]
    assert "described" not in body


def test_screen_com_descricao_sucesso(monkeypatch):
    from PIL import Image
    monkeypatch.setattr("PIL.ImageGrab.grab", lambda: Image.new("RGB", (100, 60)))
    rt.configure(get_vision_model=lambda: "llava")
    monkeypatch.setattr("src.llm.chat_resilient",
                        lambda model, msgs, **kw: "uma tela de terminal")

    r = _client().post("/api/vision/screen", json={"describe": True})
    body = r.json()
    assert body["ok"] is True
    assert body["described"] is True
    assert body["description"] == "uma tela de terminal"


def test_screen_falha_de_captura_nao_tenta_descrever(monkeypatch):
    monkeypatch.setattr("PIL.ImageGrab.grab",
                        lambda: (_ for _ in ()).throw(RuntimeError("sem display")))
    called = []
    monkeypatch.setattr("src.llm.chat_resilient",
                        lambda *a, **kw: called.append(1) or "nunca deveria chamar")

    r = _client().post("/api/vision/screen", json={"describe": True})
    body = r.json()
    assert body["ok"] is False
    assert called == []


# ── POST /api/vision/document ───────────────────────────────────
def test_document_texto_simples():
    data = base64.b64encode(b"conteudo do arquivo").decode("ascii")
    r = _client().post("/api/vision/document",
                       json={"filename": "notas.txt", "data": data})
    body = r.json()
    assert body["ok"] is True and body["kind"] == "text"
    assert body["text"] == "conteudo do arquivo"


def test_document_data_invalida_em_base64():
    r = _client().post("/api/vision/document",
                       json={"filename": "notas.txt", "data": "###nao-e-base64###"})
    body = r.json()
    assert body["ok"] is False
    assert "base64" in body["error"]


def test_document_imagem_aciona_descricao(monkeypatch):
    raw = b"\x89PNG\r\n\x1a\nfake"
    data = base64.b64encode(raw).decode("ascii")
    rt.configure(get_vision_model=lambda: "llava")
    monkeypatch.setattr("src.llm.chat_resilient",
                        lambda model, msgs, **kw: "uma captura de tela")

    r = _client().post("/api/vision/document",
                       json={"filename": "foto.png", "data": data})
    body = r.json()
    assert body["ok"] is True and body["kind"] == "image"
    assert body["described"] is True
    assert body["description"] == "uma captura de tela"


def test_document_remember_grava_na_memoria_quando_pedido():
    saved_calls = []

    class _FakeIngestor:
        def ingest_text(self, filename, text, source):
            saved_calls.append((filename, text, source))
            return True

    rt.configure(ingestor=_FakeIngestor())
    data = base64.b64encode(b"texto para lembrar").decode("ascii")

    r = _client().post("/api/vision/document",
                       json={"filename": "notas.txt", "data": data, "remember": True})
    body = r.json()
    assert body["ok"] is True
    assert body["remembered"] is True
    assert saved_calls == [("notas.txt", "texto para lembrar", "vision")]


def test_document_remember_falso_nao_toca_ingestor():
    class _FakeIngestor:
        def ingest_text(self, *a, **kw):
            raise AssertionError("não deveria ser chamado")

    rt.configure(ingestor=_FakeIngestor())
    data = base64.b64encode(b"texto qualquer").decode("ascii")

    r = _client().post("/api/vision/document",
                       json={"filename": "notas.txt", "data": data, "remember": False})
    body = r.json()
    assert body["ok"] is True
    assert "remembered" not in body


def test_document_remember_sem_ingestor_nao_quebra():
    rt.configure(ingestor=None)
    data = base64.b64encode(b"texto qualquer").decode("ascii")

    r = _client().post("/api/vision/document",
                       json={"filename": "notas.txt", "data": data, "remember": True})
    body = r.json()
    assert body["ok"] is True
    assert "remembered" not in body


def test_document_tipo_desconhecido():
    data = base64.b64encode(b"\x00\x01\x02").decode("ascii")
    r = _client().post("/api/vision/document",
                       json={"filename": "arquivo.xyz", "data": data})
    body = r.json()
    assert body["ok"] is False and body["kind"] == "unknown"
