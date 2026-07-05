"""Router de gestão da base (routers/knowledge.py) — 7º grupo extraído na M1.
Cobre curadoria, esquecer (multi-store), stats, grafo (com cache) e insights.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.knowledge as kn
from routers.knowledge import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/curate/scan", "/api/curate/apply", "/api/knowledge/forget",
        "/api/knowledge/stats", "/api/knowledge/graph", "/api/knowledge/insights",
    } <= paths


def test_curate_scan_sem_curador():
    rt.configure(curator=None)
    r = _client().get("/api/curate/scan")
    assert r.json()["enabled"] is False


def test_curate_scan_com_curador():
    class FakeCurator:
        def scan(self):
            return {"total": 10, "removable": 2}
    rt.configure(curator=FakeCurator())
    r = _client().get("/api/curate/scan")
    assert r.json() == {"enabled": True, "total": 10, "removable": 2}


def test_forget_remove_dos_tres_stores():
    class FakeDB:
        def delete_learned_topic(self, tid):
            return {"topic": "asyncio", "url": "http://x"}

    class FakeKB:
        def delete_by_url(self, url):
            return 1

    class FakeRAG:
        def forget_topic(self, topic):
            return 1

    rt.configure(db=FakeDB(), knowledge_db=FakeKB(), rag=FakeRAG())
    r = _client().post("/api/knowledge/forget", json={"id": 5})
    body = r.json()
    assert body["ok"] is True and body["topic"] == "asyncio"
    assert body["removed"] == {"sqlite": True, "supabase": 1, "rag": 1}


def test_forget_inexistente():
    class FakeDB:
        def delete_learned_topic(self, tid):
            return None
    rt.configure(db=FakeDB())
    r = _client().post("/api/knowledge/forget", json={"id": 999})
    assert r.json()["ok"] is False


def test_graph_usa_cache(monkeypatch):
    chamadas = {"n": 0}

    class FakeDB:
        def get_learning_history(self, limit=400):
            chamadas["n"] += 1
            return [{"topic": "FastAPI streaming"}, {"topic": "Redis pub/sub"}]

    rt.configure(db=FakeDB())
    kn.knowledge_graph._cache = None  # zera o cache entre execuções de teste
    c = _client()
    r1 = c.get("/api/knowledge/graph")
    r2 = c.get("/api/knowledge/graph")   # 2ª vez deve vir do cache (<60s)
    assert r1.status_code == 200 and r2.json() == r1.json()
    assert chamadas["n"] == 1            # _build só rodou uma vez
    assert any(n["id"] == "apolo" for n in r1.json()["nodes"])
