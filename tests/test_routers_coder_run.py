"""Execução direta do Coder (routers/coder_run.py) — 17º grupo na M1.
Cobre o terminal SSE (/api/coder/exec) e o commit assistido (mensagem gerada
pelo modelo leve quando vazia; nunca faz push).
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.coder_run as run
from routers.coder_run import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/ws/coder/exec", "/api/coder/exec", "/api/coder/commit"} <= paths


def test_exec_streama_saida_e_conclui():
    class FakeWS:
        def run_cmd_stream(self, cmd):
            yield ("line", "linha 1")
            yield ("line", "linha 2")
            yield ("done", True)

    rt.configure(coder_ws=FakeWS(), gpu_gate=None)
    r = _client().post("/api/coder/exec", json={"cmd": "pytest -q"})
    assert r.status_code == 200
    eventos = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    tipos = [e["type"] for e in eventos]
    assert "cmd_line" in tipos and eventos[-1] == {"type": "done", "ok": True}


def test_commit_sem_repo():
    class FakeWS:
        def git_status(self): return {"is_repo": False}
    rt.configure(coder_ws=FakeWS())
    r = _client().post("/api/coder/commit", json={})
    assert r.json()["ok"] is False and "git" in r.json()["error"]


def test_commit_nada_para_commitar():
    class FakeWS:
        def git_status(self): return {"is_repo": True, "dirty": False}
    rt.configure(coder_ws=FakeWS())
    r = _client().post("/api/coder/commit", json={})
    assert r.json()["ok"] is False and "nada" in r.json()["error"]


def test_commit_gera_mensagem_pelo_modelo(monkeypatch):
    commitado = {}

    class FakeWS:
        def git_status(self): return {"is_repo": True, "dirty": True, "status": "M app.py"}
        def git_diff(self): return "diff real aqui"
        def git_commit_all(self, msg):
            commitado["msg"] = msg
            return {"ok": True, "message": msg}

    # modelo leve devolve a 1a linha como mensagem Conventional Commits
    monkeypatch.setattr(run, "chat_resilient",
                        lambda model, msgs, keep_alive=None: "feat: nova rota de saude\n(corpo)")
    rt.configure(coder_ws=FakeWS(), get_chat_model=lambda: "qwen2.5-coder:3b")
    r = _client().post("/api/coder/commit", json={})
    assert r.json()["ok"] is True
    assert commitado["msg"] == "feat: nova rota de saude"


def test_commit_usa_mensagem_dada():
    commitado = {}

    class FakeWS:
        def git_commit_all(self, msg):
            commitado["msg"] = msg
            return {"ok": True}

    rt.configure(coder_ws=FakeWS())
    r = _client().post("/api/coder/commit", json={"message": "fix: algo"})
    assert r.json()["ok"] is True and commitado["msg"] == "fix: algo"
