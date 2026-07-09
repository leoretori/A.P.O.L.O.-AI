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

    def by_category(self):
        groups = {}
        for f in self.facts:
            groups.setdefault(f.get("category", "fact"), []).append(f)
        return groups

    def add(self, fact, source="user", category=None, horizon=None):
        item = {"id": str(len(self.facts) + 1), "fact": fact,
                "category": category or "fact"}
        if horizon:
            item["horizon"] = horizon
        self.facts.append(item)
        return item

    def update(self, fact_id, *, fact=None, category=None, horizon=None):
        for it in self.facts:
            if it["id"] == fact_id:
                if fact is not None:
                    it["fact"] = fact
                if category is not None:
                    it["category"] = category
                return it
        return None

    def remove(self, fact_id):
        before = len(self.facts)
        self.facts = [f for f in self.facts if f["id"] != fact_id]
        return len(self.facts) < before


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/profile", "/api/profile/{fact_id}"} <= paths


def test_get_expoe_categorias_e_agrupamento():
    p = FakeProfile()
    p.add("lançar v2", category="goal")
    rt.configure(profile=p)
    body = _client().get("/api/profile").json()
    assert "goal" in body["by_category"]
    assert body["categories"]["goal"] == "Metas"


def test_add_com_categoria_e_horizonte(monkeypatch):
    monkeypatch.setattr(profile_router_mod, "_syscache_inv", lambda: None)
    p = FakeProfile()
    rt.configure(profile=p)
    r = _client().post("/api/profile",
                       json={"fact": "terminar o Nano", "category": "goal", "horizon": "short"})
    assert r.json()["fact"]["category"] == "goal"
    assert r.json()["fact"]["horizon"] == "short"


def test_patch_edita_e_invalida_cache(monkeypatch):
    chamou = {"n": 0}
    monkeypatch.setattr(profile_router_mod, "_syscache_inv",
                        lambda: chamou.__setitem__("n", chamou["n"] + 1))
    p = FakeProfile()
    it = p.add("uso Postgre")
    rt.configure(profile=p)
    r = _client().patch(f"/api/profile/{it['id']}",
                        json={"fact": "uso PostgreSQL", "category": "preference"})
    assert r.json()["ok"] is True
    assert r.json()["fact"]["fact"] == "uso PostgreSQL"
    assert chamou["n"] == 1


def test_delete_invalida_cache(monkeypatch):
    chamou = {"n": 0}
    monkeypatch.setattr(profile_router_mod, "_syscache_inv",
                        lambda: chamou.__setitem__("n", chamou["n"] + 1))
    p = FakeProfile()
    it = p.add("remover")
    rt.configure(profile=p)
    _client().delete(f"/api/profile/{it['id']}")
    assert chamou["n"] == 1  # remoção também invalida (bug corrigido no M16.1)


# ------------------------------------------------ candidatos (M16.2)
def test_fluxo_candidatos_endpoints(monkeypatch, tmp_path):
    """GET lista pendentes, confirm move p/ perfil (+invalida cache), reject descarta."""
    from src.profile import UserProfile
    monkeypatch.setattr(profile_router_mod, "_syscache_inv", lambda: None)
    prof = UserProfile(path=str(tmp_path / "p.json"))
    prof.propose("respostas diretas", "preference")
    prof.propose("Apolo AI", "project")
    rt.configure(profile=prof)
    cli = _client()

    body = cli.get("/api/profile/candidates").json()
    assert len(body["candidates"]) == 2
    cid = body["candidates"][0]["id"]

    r = cli.post(f"/api/profile/candidates/{cid}/confirm", json={})
    assert r.json()["ok"] is True
    assert len(prof.list()) == 1 and len(prof.pending()) == 1

    other = prof.pending()[0]["id"]
    assert cli.post(f"/api/profile/candidates/{other}/reject").json()["ok"] is True
    assert prof.pending() == []


def test_candidatos_sem_profile_nao_quebra():
    rt.configure(profile=None)
    assert _client().get("/api/profile/candidates").json() == {"candidates": []}


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
