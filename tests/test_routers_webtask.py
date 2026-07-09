"""Router de automação web (routers/webtask.py, M10 10.3): plano (prévia) e run
(via portão do M6). O run usa um driver fake (monkeypatch) — sem rede."""
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src.storage import DatabaseManager
from routers.webtask import router
import src.tools  # noqa: F401  registra browser.run
import src.tools.browser as browser_tool


@pytest.fixture()
def client():
    d = tempfile.mkdtemp()
    db = DatabaseManager(f"sqlite:///{Path(d) / 'app.db'}")
    db.grant_permission("browser.control", note="example.com")
    rt.configure(db=db)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/webtask/example", "/api/webtask/plan", "/api/webtask/run"} <= paths


def test_example_traz_receita(client):
    body = client.get("/api/webtask/example").json()
    assert body["steps"][0]["op"] == "open" and "extract" in body["ops"]


def test_plan_valida_sandbox_sem_navegar(client):
    ok = client.post("/api/webtask/plan", json={
        "steps": [{"op": "open", "url": "https://example.com"}]}).json()
    assert ok["ok"] and ok["granted"] and ok["allowed_domains"] == ["example.com"]
    bad = client.post("/api/webtask/plan", json={
        "steps": [{"op": "open", "url": "https://evil.com"}]}).json()
    assert bad["ok"] is False and bad["errors"]


def test_run_usa_driver_injetado_e_respeita_permissao(client, monkeypatch):
    class FakeDriver:
        def open(self, url):
            return {"url": url, "title": "Exemplo", "text": "conteúdo " * 10, "links": []}

    # injeta o driver fake no handler da tool (sem rede)
    monkeypatch.setattr(browser_tool.webtask, "HttpDriver", lambda *a, **k: FakeDriver())

    res = client.post("/api/webtask/run", json={
        "steps": [{"op": "open", "url": "https://example.com"},
                  {"op": "extract", "what": "title"}]}).json()
    assert res["ok"] and res["results"][0]["value"] == "Exemplo"


def test_run_negado_sem_permissao(client, monkeypatch):
    rt.db.revoke_permission("browser.control")
    res = client.post("/api/webtask/run", json={
        "steps": [{"op": "open", "url": "https://example.com"}]}).json()
    assert res.get("denied") is True
