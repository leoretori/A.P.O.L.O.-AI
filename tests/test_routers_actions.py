"""Router de ações (routers/actions.py, M10 10.1): contrato dos endpoints
preview/confirm/undo + ledger, sobre um DB real em pasta temporária."""
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src.storage import DatabaseManager
from routers.actions import router
import src.tools  # noqa: F401  registra a ação files.write


@pytest.fixture()
def client_root():
    d = Path(tempfile.mkdtemp())
    db = DatabaseManager(f"sqlite:///{d / 'app.db'}")
    db.grant_permission("files.write", note=str(d))     # autoriza a pasta temp
    rt.configure(db=db)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), d


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/actions", "/api/actions/preview",
            "/api/actions/confirm", "/api/actions/undo"} <= paths


def test_fluxo_preview_confirm_undo(client_root):
    client, d = client_root
    alvo = d / "notas.md"
    body = {"kind": "files.write", "args": {"path": str(alvo), "content": "# Notas"}}

    pv = client.post("/api/actions/preview", json=body).json()
    assert pv["ok"] and pv["preview"]["action"] == "create"
    assert not alvo.exists()                             # preview não escreve

    cf = client.post("/api/actions/confirm", json=body).json()
    assert cf["ok"] and cf["reversible"]
    assert alvo.read_text(encoding="utf-8") == "# Notas"
    undo_id = cf["undo_id"]

    ledger = client.get("/api/actions/undo").json()
    assert ledger["count"] == 1 and ledger["items"][0]["id"] == undo_id

    un = client.post("/api/actions/undo", json={"undo_id": undo_id}).json()
    assert un["ok"] and not alvo.exists()                # revertido


def test_confirm_sem_permissao_e_negado(client_root):
    client, d = client_root
    rt.db.revoke_permission("files.write")
    cf = client.post("/api/actions/confirm", json={
        "kind": "files.write", "args": {"path": str(d / "x.txt"), "content": "x"}}).json()
    assert cf["ok"] is False and cf.get("denied") is True


def test_lista_acoes_disponiveis(client_root):
    client, _ = client_root
    kinds = [a["kind"] for a in client.get("/api/actions").json()["actions"]]
    assert "files.write" in kinds


def test_undo_sem_id(client_root):
    client, _ = client_root
    assert client.post("/api/actions/undo", json={}).json()["ok"] is False
