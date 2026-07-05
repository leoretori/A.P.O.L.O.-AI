"""Router de sistema (routers/system.py) — 13º grupo extraído na M1.
Cobre perf, history e models (com os getters de modelo do runtime).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.system as sysmod
from routers.system import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/perf", "/api/perf/reset", "/api/history", "/api/models"} <= paths


def test_perf_snapshot():
    r = _client().get("/api/perf")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)


def test_history_le_do_db():
    class FakeDB:
        def get_history(self, limit=50):
            return [{"q": "oi", "a": "olá"}]
    rt.configure(db=FakeDB())
    r = _client().get("/api/history")
    assert r.json()[0]["q"] == "oi"


def test_models_usa_getters_do_runtime(monkeypatch):
    class FakeProvider:
        def list_models(self):
            return ["qwen2.5-coder:3b", "qwen2.5-coder:14b"]

    monkeypatch.setattr("src.providers.get_provider", lambda: FakeProvider())
    rt.configure(model="qwen2.5-coder:14b",
                 get_chat_model=lambda: "qwen2.5-coder:3b",
                 get_vision_model=lambda: "")
    r = _client().get("/api/models")
    body = r.json()
    assert body["chat_model"] == "qwen2.5-coder:3b"
    assert body["heavy_model"] == "qwen2.5-coder:14b"
    assert body["chat_is_fast"] is True          # 3b está em FAST_MODELS
    assert body["suggestion"] == ""              # ja usa modelo rapido


def test_models_sugere_3b_quando_chat_pesado(monkeypatch):
    monkeypatch.setattr(sysmod, "get_provider", lambda: None, raising=False)

    class FakeProvider:
        def list_models(self):
            return []
    monkeypatch.setattr("src.providers.get_provider", lambda: FakeProvider())
    rt.configure(model="qwen2.5-coder:14b",
                 get_chat_model=lambda: "qwen2.5-coder:14b",
                 get_vision_model=lambda: "")
    r = _client().get("/api/models")
    assert r.json()["chat_is_fast"] is False
    assert r.json()["suggestion"] == "qwen2.5-coder:3b"
