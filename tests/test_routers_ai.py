"""Router de IA especializada (routers/ai.py) + src/chat_common.py — 19º grupo/
refactor da M1. Cobre review, research (com persistência) e os helpers comuns.
"""
import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src import chat_common as cc
from routers.ai import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ── chat_common ───────────────────────────────────────────────────
def test_mark_e_last_request():
    cc.mark_request()
    t1 = cc.last_request_at()
    assert t1 > 0


def test_generate_session_title(monkeypatch):
    salvo = {}

    class FakeDB:
        def save_session_title(self, sid, title):
            salvo[sid] = title

    monkeypatch.setattr(cc, "chat_resilient",
                        lambda model, msgs, keep_alive=None: "Título Gerado")
    rt.configure(db=FakeDB(), get_chat_model=lambda: "m")
    asyncio.run(cc.generate_session_title("s1", "olá mundo"))
    assert salvo["s1"] == "Título Gerado"


# ── review ────────────────────────────────────────────────────────
def test_review_streama():
    class FakeReviewer:
        async def review(self, code, lang):
            yield {"type": "step", "message": "analisando"}
            yield {"type": "done", "issues": 0}

    rt.configure(reviewer=FakeReviewer(), gpu_gate=None)
    r = _client().post("/api/review", json={"code": "print(1)"})
    assert r.status_code == 200
    eventos = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    assert eventos[-1]["type"] == "done"


# ── research ──────────────────────────────────────────────────────
def test_research_persiste_conversa():
    saved_msgs = []

    class FakeResearcher:
        async def research(self, q):
            yield {"type": "step", "message": "buscando"}
            yield {"type": "done", "answer": "a resposta", "sources": []}

    class FakeDB:
        def save_message(self, sid, role, content):
            saved_msgs.append((role, content))

    sessions = {"s1": []}
    rt.configure(researcher=FakeResearcher(), learner=None, db=FakeDB(),
                 knowledge_db=None, sessions=sessions, gpu_gate=None,
                 get_chat_model=lambda: "m")
    r = _client().post("/api/research", json={"message": "o que é RAG?", "session_id": "s1"})
    assert r.status_code == 200
    eventos = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    assert eventos[-1]["answer"] == "a resposta"
    # conversa foi persistida (user + assistant) no dict de sessão e no banco
    assert len(sessions["s1"]) == 2
    assert ("assistant", "a resposta") in saved_msgs


# ── orchestrate ───────────────────────────────────────────────────
def test_orchestrate_streama(monkeypatch):

    async def fake_orchestrate(**kwargs):
        yield {"type": "agent_start", "agent": "researcher"}
        yield {"type": "done", "answer": "sintese final"}

    # o endpoint faz `from src.orchestrator import orchestrate` → patcha lá
    monkeypatch.setattr("src.orchestrator.orchestrate", fake_orchestrate)
    rt.configure(learner=None, rag=None, knowledge_db=None, gpu_gate=None,
                 model="qwen2.5-coder:14b", get_chat_model=lambda: "qwen2.5-coder:3b")
    r = _client().post("/api/orchestrate", json={"message": "planeje um app"})
    assert r.status_code == 200
    eventos = [json.loads(l[6:]) for l in r.text.splitlines() if l.startswith("data: ")]
    assert eventos[-1]["answer"] == "sintese final"
