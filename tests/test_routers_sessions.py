"""Router de sessões (routers/sessions.py) — 3º grupo extraído na M1.
Valida rotas registradas e leitura via src.runtime, incluindo o compartilhamento
por referência do dict `sessions` (o DELETE precisa mexer no mesmo dict do chat).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.sessions import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/session/{session_id}", "/api/sessions",
        "/api/session/{session_id}/export", "/api/sessions/search",
        "/api/sessions/reindex",
    } <= paths


def test_get_session_le_do_db():
    class FakeDB:
        def load_session(self, sid):
            return [{"role": "user", "content": "oi"}]
    rt.configure(db=FakeDB())
    r = _client().get("/api/session/abc")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "abc"
    assert body["messages"][0]["content"] == "oi"


def test_delete_remove_do_dict_compartilhado():
    # O dict `sessions` é o MESMO que o chat muta — o DELETE tem que removê-lo dele.
    shared = {"s1": ["msg"], "s2": ["x"]}
    deleted = {}

    class FakeDB:
        def delete_session(self, sid):
            deleted["id"] = sid

    rt.configure(db=FakeDB(), sessions=shared)
    r = _client().delete("/api/session/s1")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "s1" not in shared          # removido do dict compartilhado
    assert deleted["id"] == "s1"        # e do banco


def test_reindex_sem_rag_falha_graciosamente():
    rt.configure(rag=None, db=None)
    r = _client().post("/api/sessions/reindex")
    assert r.status_code == 200
    assert r.json()["ok"] is False


def test_search_sessions():
    class FakeDB:
        def search_messages(self, q, n):
            return [{"snippet": f"achei {q}"}]
    rt.configure(db=FakeDB())
    r = _client().get("/api/sessions/search?q=redis")
    assert r.json()["query"] == "redis"
    assert "redis" in r.json()["results"][0]["snippet"]
