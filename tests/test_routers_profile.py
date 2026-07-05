"""Router de perfil (routers/profile.py) — 4º grupo extraído na M1.
Valida rotas e a invalidação do cache do system prompt ao mudar o perfil.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.profile as profile_router_mod
from routers.profile import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class FakeProfile:
    def __init__(self):
        self.facts = []

    def list(self):
        return self.facts

    def add(self, fact):
        item = {"id": str(len(self.facts) + 1), "fact": fact}
        self.facts.append(item)
        return item

    def remove(self, fact_id):
        before = len(self.facts)
        self.facts = [f for f in self.facts if f["id"] != fact_id]
        return len(self.facts) < before


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/profile", "/api/profile/{fact_id}"} <= paths


def test_get_lista_fatos():
    p = FakeProfile()
    p.add("gosta de café")
    rt.configure(profile=p)
    r = _client().get("/api/profile")
    assert r.status_code == 200
    assert r.json()["facts"][0]["fact"] == "gosta de café"


def test_add_invalida_cache_do_system_prompt(monkeypatch):
    chamou = {"n": 0}
    monkeypatch.setattr(profile_router_mod, "_syscache_inv", lambda: chamou.__setitem__("n", chamou["n"] + 1))
    rt.configure(profile=FakeProfile())
    r = _client().post("/api/profile", json={"fact": "mora em SP"})
    assert r.json()["ok"] is True
    assert chamou["n"] == 1   # perfil mudou → cache invalidado


def test_add_sem_profile_nao_quebra():
    rt.configure(profile=None)
    r = _client().post("/api/profile", json={"fact": "x"})
    assert r.status_code == 200 and r.json()["ok"] is False


def test_delete_fato():
    p = FakeProfile()
    it = p.add("remover isto")
    rt.configure(profile=p)
    r = _client().delete(f"/api/profile/{it['id']}")
    assert r.json()["ok"] is True
    assert p.facts == []
