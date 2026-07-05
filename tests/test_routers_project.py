"""Router de memória de projeto (routers/project.py) — 12º grupo extraído na M1.
Cobre analyze (com default do workspace do Coder), context, list e delete.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.project as proj
from routers.project import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/project/analyze", "/api/project/context", "/api/project/clear",
        "/api/project/list", "/api/project/{name}",
    } <= paths


def test_context_ativo():
    class FakePM:
        def get_active(self):
            return {"stack": "python", "name": "apolo"}
    rt.configure(project_mem=FakePM())
    r = _client().get("/api/project/context")
    assert r.json()["active"]["stack"] == "python"


def test_analyze_usa_root_do_coder(monkeypatch, tmp_path):
    class FakeWS:
        root = str(tmp_path)   # pasta existente

    ctx_salvo = {}

    class FakePM:
        def set_context(self, ctx):
            ctx_salvo.update(ctx)

    def fake_analyze(folder):
        return {"folder": folder, "stack": "detectada"}

    monkeypatch.setattr(proj, "_analyze_project", fake_analyze)
    rt.configure(coder_ws=FakeWS(), project_mem=FakePM())
    r = _client().post("/api/project/analyze", json={})   # path vazio → usa coder_ws.root
    assert r.json()["ok"] is True
    assert r.json()["context"]["folder"] == str(tmp_path)
    assert ctx_salvo["stack"] == "detectada"


def test_analyze_pasta_inexistente():
    class FakeWS:
        root = "/nao/existe/xyz123"
    rt.configure(coder_ws=FakeWS(), project_mem=None)
    r = _client().post("/api/project/analyze", json={"path": "/tambem/nao/existe"})
    assert r.json()["ok"] is False


def test_delete_projeto():
    removidos = []

    class FakePM:
        def remove(self, name):
            removidos.append(name)
            return True
    rt.configure(project_mem=FakePM())
    r = _client().delete("/api/project/meu-projeto")
    assert r.json()["ok"] is True and removidos == ["meu-projeto"]
