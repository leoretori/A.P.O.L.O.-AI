"""Router de rotinas (routers/routines.py, M10 10.2): CRUD + rodar-agora.
Rodar-agora aplica a ação de verdade → arquivo escrito numa pasta autorizada."""
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src.storage import DatabaseManager
from routers.routines import router
import src.tools  # noqa: F401  registra files.write


@pytest.fixture()
def client_root():
    d = Path(tempfile.mkdtemp())
    db = DatabaseManager(f"sqlite:///{d / 'app.db'}")
    db.grant_permission("files.write", note=str(d))
    rt.configure(db=db)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), d


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/routines", "/api/routines/kinds",
            "/api/routines/{routine_id}/run"} <= paths


def test_kinds_lista_weekly_digest(client_root):
    client, _ = client_root
    kinds = [k["kind"] for k in client.get("/api/routines/kinds").json()["kinds"]]
    assert "weekly_digest" in kinds


def test_criar_valida_tipo(client_root):
    client, _ = client_root
    bad = client.post("/api/routines", json={"kind": "inexistente"}).json()
    assert bad["ok"] is False


def test_criar_listar_e_agendamento_humano(client_root):
    client, d = client_root
    r = client.post("/api/routines", json={
        "name": "Resumo sexta", "kind": "weekly_digest", "freq": "weekly",
        "weekday": 4, "time_of_day": "18:00", "config": {"path": str(d / "s.md")}}).json()
    assert r["ok"] and r["routine"]["schedule_human"] == "toda sexta às 18:00"
    lst = client.get("/api/routines").json()
    assert lst["count"] == 1


def test_toggle(client_root):
    client, _ = client_root
    rid = client.post("/api/routines", json={"kind": "weekly_digest"}).json()["routine"]["id"]
    assert client.post(f"/api/routines/{rid}/toggle").json()["enabled"] is False
    assert client.post(f"/api/routines/{rid}/toggle").json()["enabled"] is True


def test_run_now_escreve_e_entra_no_ledger(client_root):
    client, d = client_root
    alvo = d / "resumo.md"
    rid = client.post("/api/routines", json={
        "kind": "weekly_digest", "config": {"path": str(alvo)}}).json()["routine"]["id"]
    res = client.post(f"/api/routines/{rid}/run").json()
    assert res["ok"] and res["reversible"]
    assert alvo.exists() and alvo.read_text(encoding="utf-8").startswith("# Resumo da semana")
    # a execução virou uma ação reversível
    assert rt.db.count_undo() == 1


def test_delete(client_root):
    client, _ = client_root
    rid = client.post("/api/routines", json={"kind": "weekly_digest"}).json()["routine"]["id"]
    assert client.delete(f"/api/routines/{rid}").json()["ok"] is True
