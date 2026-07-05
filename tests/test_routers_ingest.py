"""Router de ingestão (routers/ingest.py) — 9º grupo extraído na M1.
Cobre validações (sem ingestor, URL inválida, pasta inexistente) e o caminho
feliz de ingestão de texto.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.ingest import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class FakeIngestor:
    def ingest_text(self, filename, text, source=None):
        return {"ok": True, "filename": filename, "chars": len(text)}


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/ingest", "/api/ingest/url", "/api/ingest/folder",
        "/api/repo/analyze", "/api/repo/list",
    } <= paths


def test_ingest_texto():
    rt.configure(ingestor=FakeIngestor())
    r = _client().post("/api/ingest", json={"filename": "nota.md", "content": "olá mundo"})
    body = r.json()
    assert body["ok"] is True and body["filename"] == "nota.md"


def test_ingest_sem_ingestor():
    rt.configure(ingestor=None)
    r = _client().post("/api/ingest", json={"filename": "x", "content": "y"})
    assert r.json()["ok"] is False


def test_ingest_url_invalida():
    rt.configure(ingestor=FakeIngestor())
    r = _client().post("/api/ingest/url", json={"url": "ftp://nope"})
    assert r.json()["ok"] is False
    assert "URL" in r.json()["error"]


def test_ingest_folder_inexistente():
    rt.configure(ingestor=FakeIngestor())
    r = _client().post("/api/ingest/folder", json={"path": "/pasta/que/nao/existe/xyz"})
    assert r.json()["ok"] is False


def test_repo_list_sem_rag():
    rt.configure(rag=None)
    r = _client().get("/api/repo/list")
    assert r.json() == {"repos": []}
