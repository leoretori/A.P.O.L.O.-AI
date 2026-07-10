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


# ───────────────────────────── M20.1 modo interativo ────────────────────────
class _FakeInteractive:
    def __init__(self):
        self.filled, self.submitted = {}, False

    def _p(self, url="https://example.com/x"):
        return {"url": url, "title": "OK", "text": "x", "links": []}

    def open(self, url):
        return self._p(url)

    def fill(self, selector, value):
        self.filled[selector] = value
        return self._p()

    def submit(self, selector=None):
        self.submitted = True
        return self._p("https://example.com/enviado")

    def close(self):
        pass


_INTERACT_RECIPE = [
    {"op": "open", "url": "https://example.com/form"},
    {"op": "fill", "selector": "input[name=q]", "value": "oi"},
    {"op": "submit", "selector": "button"},
]


def test_interactive_plan_lista_passos_e_efeitos(client):
    rt.db.grant_permission("browser.interact", note="example.com")
    d = client.post("/api/webtask/interactive/plan", json={"steps": _INTERACT_RECIPE}).json()
    assert d["granted"] and d["ok"]
    assert [p["op"] for p in d["plan"]] == ["open", "fill", "submit"]
    assert len(d["effects"]) == 1


def test_interactive_run_para_sem_confirmar(client, monkeypatch):
    rt.db.grant_permission("browser.interact", note="example.com")
    monkeypatch.setattr(browser_tool.webtask, "PlaywrightDriver", lambda *a, **k: _FakeInteractive())
    res = client.post("/api/webtask/interactive/run", json={"steps": _INTERACT_RECIPE}).json()
    assert res["ok"] is False and res["status"] == "needs_confirmation"


def test_interactive_run_confirmado_executa_com_trilha(client, monkeypatch):
    rt.db.grant_permission("browser.interact", note="example.com")
    fake = _FakeInteractive()
    monkeypatch.setattr(browser_tool.webtask, "PlaywrightDriver", lambda *a, **k: fake)
    res = client.post("/api/webtask/interactive/run",
                      json={"steps": _INTERACT_RECIPE, "confirm_effects": True}).json()
    assert res["ok"] and fake.submitted and fake.filled == {"input[name=q]": "oi"}
    assert len(res["ledger"]) == 1


def test_interactive_run_negado_sem_permissao(client):
    res = client.post("/api/webtask/interactive/run",
                      json={"steps": _INTERACT_RECIPE, "confirm_effects": True}).json()
    assert res.get("denied") is True


def test_efeito_vai_para_a_trilha_duravel(client, monkeypatch):
    """M20.2 — cada ação com efeito executada fica registrada na trilha."""
    rt.db.grant_permission("browser.interact", note="example.com")
    monkeypatch.setattr(browser_tool.webtask, "PlaywrightDriver", lambda *a, **k: _FakeInteractive())
    # antes: trilha vazia
    assert client.get("/api/webtask/interactive/trail").json()["trail"] == []
    # roda a receita confirmando o efeito
    client.post("/api/webtask/interactive/run",
                json={"steps": _INTERACT_RECIPE, "confirm_effects": True})
    trail = client.get("/api/webtask/interactive/trail").json()["trail"]
    assert len(trail) == 1 and "enviar" in trail[0]["detail"]


def test_run_sem_efeito_nao_polui_a_trilha(client, monkeypatch):
    rt.db.grant_permission("browser.interact", note="example.com")
    monkeypatch.setattr(browser_tool.webtask, "PlaywrightDriver", lambda *a, **k: _FakeInteractive())
    # receita read-only (só open+extract) → nada na trilha
    client.post("/api/webtask/interactive/run", json={"steps": [
        {"op": "open", "url": "https://example.com"}, {"op": "extract", "what": "title"}]})
    assert client.get("/api/webtask/interactive/trail").json()["trail"] == []
