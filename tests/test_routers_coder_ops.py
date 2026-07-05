"""Operações do Coder sem LLM (routers/coder_ops.py) — 16º grupo na M1.
Cobre o ciclo do sandbox (create→diff→apply→discard) com o estado local do
módulo, test-for, e o navegador de pastas.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.coder_ops as ops
from routers.coder_ops import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class FakeWS:
    def set_root(self, p): return {"ok": True}
    def tree(self, n): return "arvore"
    def find_related_tests(self, path): return ["tests/test_x.py"]
    def run_tests_for(self, related): return {"ok": True, "passed": 3, "failed": 0}


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/coder/sandbox", "/api/coder/sandbox/diff", "/api/coder/sandbox/file",
        "/api/coder/sandbox/apply", "/api/coder/sandbox/discard",
        "/api/coder/test-for", "/api/coder/vscode", "/api/coder/browse",
    } <= paths


def test_sandbox_diff_sem_copia_ativa():
    ops._sandbox_path = None
    r = _client().get("/api/coder/sandbox/diff")
    assert r.json()["ok"] is False


def test_sandbox_create_e_discard(monkeypatch):
    # `from src import sandbox` usa o módulo real já importado → patcha as funções nele.
    import src.sandbox as real_sandbox
    monkeypatch.setattr(real_sandbox, "create_sandbox", lambda root: "/tmp/copia")
    monkeypatch.setattr(real_sandbox, "discard_sandbox", lambda p: None)

    rt.configure(coder_ws=FakeWS())
    ops._sandbox_path = None
    c = _client()
    r = c.post("/api/coder/sandbox")
    assert r.json()["sandbox"] is True
    assert ops._sandbox_path == "/tmp/copia"
    # discard limpa o estado local
    r2 = c.post("/api/coder/sandbox/discard")
    assert r2.json()["ok"] is True
    assert ops._sandbox_path is None


def test_test_for_roda_relacionados():
    rt.configure(coder_ws=FakeWS())
    r = _client().post("/api/coder/test-for", json={"path": "src/x.py"})
    body = r.json()
    assert body["passed"] == 3 and body["tests_found"] == ["tests/test_x.py"]


def test_test_for_path_vazio():
    rt.configure(coder_ws=FakeWS())
    r = _client().post("/api/coder/test-for", json={"path": ""})
    assert r.json()["ok"] is False


def test_browse_lista_pastas(tmp_path):
    (tmp_path / "sub1").mkdir()
    (tmp_path / "sub2").mkdir()
    (tmp_path / ".oculta").mkdir()
    r = _client().get(f"/api/coder/browse?path={tmp_path}")
    body = r.json()
    assert body["ok"] is True
    nomes = {d["name"] for d in body["dirs"]}
    assert {"sub1", "sub2"} <= nomes and ".oculta" not in nomes
