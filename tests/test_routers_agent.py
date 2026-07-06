"""Endpoint do Modo Agente (routers/agent.py) — 20º grupo na M1.
Cobre o loop ReAct executando código real e persistindo a conversa, lendo tudo
do runtime (executor, sessions, db) e do chat_common.
"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.agent as ag
from routers.agent import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rota_registrada():
    assert any(r.path == "/api/agent" for r in router.routes)


def test_agent_executa_codigo_e_persiste(monkeypatch):
    # 1ª resposta do modelo = bloco de código; a 2ª (após ver a saída) = final.
    respostas = iter([
        "vou calcular\n```python\nprint(2+2)\n```",
        "A resposta é 4.",
    ])
    monkeypatch.setattr(ag, "chat_resilient",
                        lambda model, msgs, keep_alive=None: next(respostas))

    class FakeExecResult:
        success = True
        stdout = "4"
        stderr = ""

    class FakeExecutor:
        def run(self, code): return FakeExecResult()

    saved = []

    class FakeDB:
        def save_message(self, sid, role, content): saved.append((role, content))

    sessions = {"s1": []}
    rt.configure(executor=FakeExecutor(), learner=None, profile=None, rag=None,
                 db=FakeDB(), sessions=sessions, gpu_gate=None,
                 get_chat_model=lambda: "qwen2.5-coder:3b")

    r = _client().post("/api/agent", json={"message": "quanto é 2+2?", "session_id": "s1"})
    assert r.status_code == 200
    eventos = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    tipos = [e["type"] for e in eventos]
    assert "token" in tipos and eventos[-1]["type"] == "done"
    assert "4" in eventos[-1]["answer"]
    # conversa persistida
    assert len(sessions["s1"]) == 2
    assert ("assistant", eventos[-1]["answer"]) in saved
