"""Router de agência (routers/tools.py, M6 6.1): consentimento + tools + auditoria."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src.storage import DatabaseManager
from routers.tools import router


@pytest.fixture
def client(tmp_path):
    rt.configure(db=DatabaseManager(database_url=f"sqlite:///{tmp_path}/t.db"))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/permissions", "/api/permissions/grant", "/api/permissions/revoke",
            "/api/tools", "/api/tools/run", "/api/tools/audit"} <= paths


def test_permissions_lista_catalogo(client):
    body = client.get("/api/permissions").json()
    scopes = {s["scope"]: s for s in body["scopes"]}
    assert "files.read" in scopes and scopes["files.read"]["granted"] is False


def test_grant_e_revoke(client):
    assert client.post("/api/permissions/grant", json={"scope": "files.read"}).json()["ok"]
    granted = {s["scope"]: s["granted"] for s in client.get("/api/permissions").json()["scopes"]}
    assert granted["files.read"] is True
    assert client.post("/api/permissions/revoke", json={"scope": "files.read"}).json()["ok"]


def test_grant_escopo_invalido_rejeitado(client):
    assert client.post("/api/permissions/grant", json={"scope": "hackear.tudo"}).json()["ok"] is False


def test_tools_lista_clock_liberado(client):
    tools = {t["name"]: t for t in client.get("/api/tools").json()["tools"]}
    assert "clock" in tools and tools["clock"]["allowed"] is True


def test_run_clock(client):
    r = client.post("/api/tools/run", json={"name": "clock"}).json()
    assert r["ok"] is True and "time" in r["result"]


def test_run_desconhecida(client):
    assert client.post("/api/tools/run", json={"name": "xpto"}).json()["ok"] is False


def test_audit_registra_a_invocacao(client):
    client.post("/api/tools/run", json={"name": "clock"})
    audit = client.get("/api/tools/audit").json()["audit"]
    assert audit and audit[0]["tool"] == "clock" and audit[0]["allowed"] is True
