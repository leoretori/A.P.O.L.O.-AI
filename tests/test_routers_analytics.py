"""Router de métricas (routers/analytics.py) — 8º grupo extraído na M1.
Cobre reactions, analytics e o benchmark (com get_chat_model do runtime e o
cache em memória do histórico).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.analytics as an
from routers.analytics import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {
        "/api/benchmark/run", "/api/benchmark/history", "/api/benchmark/diff",
        "/api/analytics", "/api/reactions", "/api/reactions/stats",
    } <= paths


def test_save_reaction():
    salvos = []

    class FakeDB:
        def save_reaction(self, h, r, s, src):
            salvos.append((h, r, s, tuple(src)))

    rt.configure(db=FakeDB())
    r = _client().post("/api/reactions", json={
        "message_hash": "abc", "reaction": "up", "session_id": "s1", "sources": ["x"]})
    assert r.json() == {"ok": True}
    assert salvos == [("abc", "up", "s1", ("x",))]


def test_benchmark_diff_precisa_de_2_runs():
    an._benchmark_history.clear()
    r = _client().get("/api/benchmark/diff")
    assert r.json()["ok"] is False


def test_benchmark_run_usa_get_chat_model(monkeypatch):
    usado = {}

    async def fake_run_benchmark(chat_model, keep_alive):
        usado["model"] = chat_model
        return {"score": 0.9}

    class FakeDB:
        def save_benchmark_run(self, result):
            pass

    monkeypatch.setattr(an, "run_benchmark", fake_run_benchmark)
    rt.configure(db=FakeDB(), get_chat_model=lambda: "qwen2.5-coder:3b")
    an._benchmark_history.clear()
    r = _client().post("/api/benchmark/run")
    assert r.status_code == 200 and r.json()["score"] == 0.9
    assert usado["model"] == "qwen2.5-coder:3b"   # leu o modelo atual do runtime
    assert len(an._benchmark_history) == 1         # foi pro cache em memória
