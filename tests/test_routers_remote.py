"""Acesso remoto: endpoint de info + o GATE de verdade no app (M11 11.3).

O gate é testado contra o app real forçando um cliente 'de fora' (monkeypatch do
is_loopback) — sem token dá 401; com o token no header, passa.
"""
from fastapi.testclient import TestClient

from src import remote_access
import app as app_module
from routers.remote import router


def test_info_reporta_url_e_dicas(monkeypatch):
    from fastapi import FastAPI
    monkeypatch.setattr(remote_access, "lan_ip", lambda: "192.168.0.42")
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv("REMOTE_TOKEN", "s3nha")
    app = FastAPI()
    app.include_router(router)
    d = TestClient(app).get("/api/remote/info").json()
    assert d["lan_ip"] == "192.168.0.42" and d["lan_exposed"] is True
    assert d["auth_required"] is True
    assert d["url_with_token"] == "http://192.168.0.42:8000/?token=s3nha"


def test_info_sem_token_da_dicas(monkeypatch):
    from fastapi import FastAPI
    monkeypatch.setattr(remote_access, "lan_ip", lambda: "10.0.0.5")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.delenv("REMOTE_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)
    d = TestClient(app).get("/api/remote/info").json()
    assert d["auth_required"] is False and d["url_with_token"] is None
    assert d["hints"]["token"] and d["hints"]["bind"]      # avisa o que falta


def test_gate_bloqueia_de_fora_sem_token(monkeypatch):
    """Com REMOTE_TOKEN e cliente 'de fora' (não-loopback), a requisição é barrada."""
    monkeypatch.setattr(app_module, "REMOTE_TOKEN", "s3nha")
    monkeypatch.setattr(remote_access, "is_loopback", lambda h: False)
    client = TestClient(app_module.app)
    r = client.get("/api/remote/info")
    assert r.status_code == 401
    # com o token no header, passa
    ok = client.get("/api/remote/info", headers={"X-Apolo-Token": "s3nha"})
    assert ok.status_code == 200


def test_gate_desligado_nao_atrapalha(monkeypatch):
    """Sem REMOTE_TOKEN, o gate é transparente (comportamento atual preservado)."""
    monkeypatch.setattr(app_module, "REMOTE_TOKEN", "")
    client = TestClient(app_module.app)
    assert client.get("/api/remote/info").status_code == 200
