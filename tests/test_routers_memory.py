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
    def __init__(self, groups=None):
        self._g = groups or {"project": [{"fact": "Apolo AI",
                                          "category": "project", "id": "pr0"}]}

    def by_category(self):
        return self._g


def _client(episodes, profile=None):
    rt.configure(episodic=FakeEpisodic(episodes), profile=profile or FakeProfile())
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
    c = _client(eps)
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


def test_people_endpoint():
    prof = FakeProfile({"person": [{"fact": "Maria", "category": "person", "id": "p0"}],
                        "project": [{"fact": "Apolo AI", "category": "project", "id": "pr0"}]})
    c = _client([{"id": "a", "title": "Reunião", "summary": "Maria revisou o Apolo AI",
                  "occurred_at": "2026-07-06T09:00:00"}], profile=prof)
    people = c.get("/api/people").json()["people"]
    assert people[0]["name"] == "Maria"
    assert people[0]["projects"] == ["Apolo AI"]


def test_recall_endpoint_datado():
    prof = FakeProfile({"project": [{"fact": "Apolo AI", "category": "project", "id": "pr0"}]})
    c = _client([{"id": "a", "title": "Deploy", "summary": "subimos o Apolo AI",
                  "occurred_at": "2026-07-06T09:00:00"}], profile=prof)
    d = c.get("/api/recall", params={"q": "onde parei no projeto Apolo AI?"}).json()
    assert d["matched"] and d["found"]
    assert d["when"] == "06/07/2026" and "Deploy" in d["answer"]


def test_recall_nao_relacional():
    c = _client([], profile=FakeProfile())
    assert c.get("/api/recall", params={"q": "bom dia"}).json() == {"matched": False}
