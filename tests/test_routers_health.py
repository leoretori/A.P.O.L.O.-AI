"""Agregadores /api/boot e /api/health (routers/health.py) — 18º grupo na M1.
Cobre a agregação em paralelo lendo tudo do runtime, com fakes.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.health import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class FakeLearner:
    def get_status(self):
        return {"running": True, "queue_depth": 2, "total_session": 5,
                "throughput_hour": 10, "gap_count": 1, "agents": [{"active": True, "name": "web"}]}


class FakeDB:
    def unread_count(self): return 4
    def list_sessions(self, a, b): return [{"session_id": "s1"}]
    def get_learning_stats(self): return {"total": 100, "today": 7}
    def count_topic_duplicates(self): return 0
    def get_summary_quality(self): return {"pct_structured": 80}
    def get_learned_since(self, h, n): return [{"topic": "asyncio"}]
    def get_learning_history(self, n): return [{"topic": "redis"}]


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/boot", "/api/health"} <= paths


def test_boot_agrega(monkeypatch):

    class FakeProvider:
        def list_models(self): return ["qwen2.5-coder:3b"]
    monkeypatch.setattr("src.providers.get_provider", lambda: FakeProvider())

    rt.configure(db=FakeDB(), learner=FakeLearner(), knowledge_db=None,
                 project_mem=None, rag=None, model="qwen2.5-coder:14b",
                 get_chat_model=lambda: "qwen2.5-coder:3b", get_vision_model=lambda: "")
    r = _client().get("/api/boot")
    body = r.json()
    assert body["ok"] is True
    assert body["models"]["chat_model"] == "qwen2.5-coder:3b"
    assert body["models"]["heavy_model"] == "qwen2.5-coder:14b"
    assert body["unread_notifications"] == 4
    assert body["learner"]["running"] is True


def test_health_agrega(monkeypatch):
    class FakeProvider:
        name = "ollama"
        def list_models(self): return ["qwen2.5-coder:14b"]
    monkeypatch.setattr("src.providers.get_provider", lambda: FakeProvider())

    rt.configure(db=FakeDB(), learner=FakeLearner(), knowledge_db=None, rag=None,
                 model="qwen2.5-coder:14b", get_chat_model=lambda: "qwen2.5-coder:3b",
                 get_vision_model=lambda: "")
    r = _client().get("/api/health")
    body = r.json()
    assert body["ok"] is True
    assert body["database"]["learned_total"] == 100
    assert body["supabase"] == {"enabled": False}
    assert body["learner"]["running"] is True
    assert body["knowledge_backend"] == "none"
    # Épico 1.3: /api/health expõe versão/uptime/git p/ saber qual código roda.
    assert set(body["build"]) >= {"version", "git_sha", "uptime_seconds", "uptime_human"}
    assert isinstance(body["build"]["uptime_seconds"], int)
