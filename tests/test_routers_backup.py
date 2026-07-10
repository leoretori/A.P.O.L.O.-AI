"""Router de backup cifrado (M11 11.2): criar → restaurar round-trip pelos
endpoints, com DB real. A senha errada não toca o banco."""
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import backup_service, crypto
from src import runtime as rt
from src.storage import DatabaseManager
from routers.backup import router

pytestmark = pytest.mark.skipif(not crypto.is_available(),
                                reason="cryptography não instalado")


@pytest.fixture()
def client(monkeypatch):
    d = Path(tempfile.mkdtemp())
    monkeypatch.setattr(backup_service, "BACKUP_DIR", d / "backups")
    db = DatabaseManager(f"sqlite:///{d / 'app.db'}")
    db.save_learned_topic("Soberania de dados", "http://x", "resumo", "web")
    rt.configure(db=db, knowledge_db=None, sessions={})
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_status_reporta_cripto(client):
    s = client.get("/api/backup/status").json()
    assert s["crypto_available"] is True and s["count"] == 0


def test_criar_e_restaurar_cifrado(client):
    cr = client.post("/api/backup/encrypted", json={"passphrase": "minha-senha"}).json()
    assert cr["ok"] and cr["name"].endswith(".apolobak")
    lst = client.get("/api/backup/status").json()
    assert lst["count"] == 1
    # restaura pelo nome (idempotente — o tópico já existe, mas não deve falhar)
    rs = client.post("/api/backup/restore",
                     json={"name": cr["name"], "passphrase": "minha-senha"}).json()
    assert rs["ok"] and rs["restored_from"] == cr["name"]


def test_restore_senha_errada_nao_decifra(client):
    cr = client.post("/api/backup/encrypted", json={"passphrase": "certa"}).json()
    rs = client.post("/api/backup/restore",
                     json={"name": cr["name"], "passphrase": "errada"}).json()
    assert rs["ok"] is False and "decifrar" in rs["error"]


def test_criar_sem_senha_recusa(client):
    assert client.post("/api/backup/encrypted", json={}).json()["ok"] is False


def test_restore_arquivo_inexistente(client):
    rs = client.post("/api/backup/restore",
                     json={"name": "nao-existe.apolobak", "passphrase": "x"}).json()
    assert rs["ok"] is False and "não encontrado" in rs["error"]


def test_restore_bloqueia_path_traversal(client):
    # nome com traversal → Path(name).name neutraliza → arquivo não existe na pasta
    rs = client.post("/api/backup/restore",
                     json={"name": "../../etc/passwd", "passphrase": "x"}).json()
    assert rs["ok"] is False
