"""Router de aprendizado (routers/learning.py) — 2º grupo extraído do monólito
na M1 do JARVIS_ROADMAP. Valida que as rotas foram registradas e que leem o
estado via src.runtime (singletons publicados no startup), sem import circular.

Os endpoints são exercitados com um learner/db falsos injetados via
runtime.configure — sem subir o app inteiro nem o Ollama.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.learning import router, _clean_topic, StudyRequest


def _app_with_router():
    app = FastAPI()
    app.include_router(router)
    return app


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    esperadas = {
        "/api/learning/start", "/api/learning/stop", "/api/learning/repair",
        "/api/learning/status", "/api/learning/stream", "/api/learning/study-now",
        "/api/learning/history", "/api/learning/timeline", "/api/learning/agents",
        "/api/digest", "/api/knowledge/search", "/api/knowledge/recent",
        "/api/briefing",
    }
    assert esperadas <= paths


def test_briefing_compoe_resumo():
    class FakeDB:
        def get_learned_since(self, hours): return [{"topic": "asyncio em Python"}]
        def list_schedules(self): return []
        def unread_count(self): return 1
    rt.configure(db=FakeDB(), episodic=None, learner=None, knowledge_db=None)
    c = TestClient(_app_with_router())
    r = c.get("/api/briefing?hours=12")
    assert r.status_code == 200
    body = r.json()
    assert body["learned_count"] == 1
    assert body["unread_notifications"] == 1
    assert "text" in body and body["text"].startswith(("Bom dia", "Boa tarde", "Boa noite"))


def test_presence_mode_responde_um_dos_tres_modos():
    c = TestClient(_app_with_router())
    r = c.get("/api/presence/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] in ("descanso", "foco", "trabalho")
    assert body["label"]  # rótulo com emoji, não vazio


def test_status_sem_learner_nao_quebra():
    rt.configure(learner=None, db=None, knowledge_db=None)
    c = TestClient(_app_with_router())
    r = c.get("/api/learning/status")
    assert r.status_code == 200
    assert r.json() == {"running": False}


def test_history_le_do_runtime():
    class FakeDB:
        def get_learning_history(self, limit=200):
            return [{"topic": "asyncio em Python", "summary": "s"}]
    rt.configure(db=FakeDB(), learner=None, knowledge_db=None)
    c = TestClient(_app_with_router())
    r = c.get("/api/learning/history?limit=1")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["topic"] == "asyncio em Python"
    assert "sector" in body[0]   # classify_sector foi aplicado


def test_status_usa_learner_injetado():
    class FakeLearner:
        def get_status(self):
            return {"running": True, "saved": 7}
    rt.configure(learner=FakeLearner(), db=None, knowledge_db=None)
    c = TestClient(_app_with_router())
    r = c.get("/api/learning/status")
    assert r.json() == {"running": True, "saved": 7}


def test_clean_topic_tira_molduras():
    assert _clean_topic("Teoria da relatividade (enciclopédia)") == "Teoria da relatividade"
    assert _clean_topic("Ideias centrais do livro Meditações").startswith("📖 ")


def test_study_request_model():
    assert StudyRequest(topic="grpc").topic == "grpc"
