"""Ferramentas de escrita do Coder (routers/coder_write.py) + o estado
compartilhado src/coder_state.py — 15º grupo/refactor da M1.
Foco: cada operação de escrita invalida o cache do baseline.
"""
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src import coder_state
from routers.coder_write import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class FakeWS:
    def __init__(self):
        self.calls = []

    def delete_file(self, p): self.calls.append(("del", p)); return "OK apagado"

    def search_replace(self, f, r): return {"files_changed": 1}

    def rename_file(self, s, d): return "OK movido"

    def undo_all(self): return {"reverted": 3}

    def undo_last(self): return {"reverted": 1}

    def set_root(self, p): self.calls.append(("root", p)); return {"ok": True}

    def tree(self, n): return "arvore"


# ── coder_state ───────────────────────────────────────────────────
def test_invalidate_baseline_limpa_cache():
    coder_state.baseline_cache["/proj"] = (True, 123.0)
    coder_state.invalidate_baseline()
    assert coder_state.baseline_cache == {}


def test_gpu_priority_passa_eventos_e_libera(monkeypatch):
    eventos = []

    class FakeGate:
        def __init__(self): self.entered = self.exited = False
        def user_enter(self): self.entered = True
        def user_exit(self): self.exited = True

    gate = FakeGate()
    rt.configure(gpu_gate=gate)

    async def gen():
        yield "a"
        yield "b"

    async def run():
        async for ev in coder_state.gpu_priority(gen()):
            eventos.append(ev)

    asyncio.run(run())
    assert eventos == ["a", "b"]
    assert gate.entered and gate.exited   # cedeu e devolveu a GPU


# ── coder_write ───────────────────────────────────────────────────
def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/coder/delete", "/api/coder/replace", "/api/coder/move",
        "/api/coder/undo", "/api/coder/workspace", "/api/coder/self",
    } <= paths


def test_delete_invalida_baseline():
    coder_state.baseline_cache["/x"] = (True, 1.0)
    rt.configure(coder_ws=FakeWS())
    r = _client().post("/api/coder/delete", json={"path": "a.py"})
    assert r.json()["ok"] is True
    assert coder_state.baseline_cache == {}   # foi invalidado


def test_undo_all():
    rt.configure(coder_ws=FakeWS())
    r = _client().post("/api/coder/undo", json={"all": True})
    assert r.json()["reverted"] == 3


def test_workspace_seta_root_e_retorna_arvore():
    ws = FakeWS()
    rt.configure(coder_ws=ws)
    r = _client().post("/api/coder/workspace", json={"path": "/proj"})
    assert r.json()["ok"] is True and r.json()["tree"] == "arvore"
    assert ("root", "/proj") in ws.calls
