"""Router da memória relacional & temporal (M18): /api/timeline."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.memory import router


class FakeEpisodic:
    def __init__(self, episodes):
        self._eps = episodes

    def recent(self, limit=20):
        return self._eps[:limit]

    def recall_phrase(self, phrase, limit=50, now=None):
        # simula "ontem" reconhecendo só a palavra; senão None (não temporal)
        return self._eps if "ontem" in (phrase or "") else None


class FakeProfile:
    def by_category(self):
        return {"project": [{"fact": "Apolo AI", "category": "project", "id": "pr0"}]}


def _client(episodes):
    rt.configure(episodic=FakeEpisodic(episodes), profile=FakeProfile())
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_timeline_anota_entidades():
    c = _client([{"id": "a", "title": "Deploy", "summary": "subimos o Apolo AI",
                  "occurred_at": "2026-07-06T09:00:00"}])
    d = c.get("/api/timeline").json()
    assert d["events"][0]["refs"]["project"] == ["Apolo AI"]


def test_timeline_filtra_por_entidade():
    eps = [
        {"id": "a", "title": "Deploy", "summary": "Apolo AI no ar",
         "occurred_at": "2026-07-06T09:00:00"},
        {"id": "b", "title": "Bolo", "summary": "receita de cenoura",
         "occurred_at": "2026-07-05T09:00:00"},
    ]
    d = c = _client(eps)
    got = c.get("/api/timeline", params={"entity": "apolo"}).json()
    assert [e["id"] for e in got["events"]] == ["a"]


def test_timeline_janela_temporal():
    c = _client([{"id": "a", "title": "x", "summary": "Apolo AI",
                  "occurred_at": "2026-07-06T09:00:00"}])
    # "ontem" é temporal → usa recall_phrase; devolve os episódios da janela
    d = c.get("/api/timeline", params={"when": "ontem"}).json()
    assert len(d["events"]) == 1


def test_timeline_sem_episodic():
    rt.configure(episodic=None, profile=None)
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/api/timeline").json() == {"events": []}
