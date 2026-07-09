"""Router de embeddings (M11 11.1): info do backend + selftest offline."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.embeddings import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_info_reporta_backend_local(monkeypatch):
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    d = _client().get("/api/embeddings/info").json()
    assert d["local"] is True and d["offline_ready"] is True


def test_info_hashing(monkeypatch):
    monkeypatch.setenv("EMBED_MODEL", "hashing")
    d = _client().get("/api/embeddings/info").json()
    assert d["backend"] == "hashing"


def test_selftest_prova_separacao_semantica():
    d = _client().post("/api/embeddings/selftest", json={}).json()
    assert d["ok"] is True and d["offline"] is True
    assert d["similar_pair"]["cosine"] > d["different_pair"]["cosine"]
