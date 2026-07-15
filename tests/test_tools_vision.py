"""Visão + agência (M22, Épico 22.2) — ver a tela quando o AGENTE decide, com o
mesmo portão de consentimento+auditoria das demais ações do M6 (diferente do
clique manual do usuário no console 👁️, que já é consentimento por si só)."""
import pytest

from src.storage import DatabaseManager
from src.tools import run_tool
from src.tools.registry import SCOPES


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/tools.db")


def test_vision_screen_esta_no_catalogo_de_escopos():
    assert "vision.screen" in SCOPES


def test_vision_screen_negado_sem_grant(db):
    res = run_tool("vision.screen", {}, db)
    assert res["ok"] is False and res["denied"] is True
    assert res["scope"] == "vision.screen"


def test_vision_screen_negado_fica_auditado(db):
    run_tool("vision.screen", {}, db)
    audit = db.list_tool_audit(10)
    assert audit and audit[0]["tool"] == "vision.screen" and audit[0]["allowed"] is False


def test_vision_screen_com_grant_captura_e_descreve(db, monkeypatch):
    db.grant_permission("vision.screen")
    monkeypatch.setattr("src.vision_read.capture_screen",
                        lambda: {"ok": True, "size": [800, 600], "image_b64": "xyz"})
    monkeypatch.setattr("src.tools.vision._describe",
                        lambda image_b64, prompt: {"ok": True, "description": "um terminal aberto"})

    res = run_tool("vision.screen", {}, db)
    assert res["ok"] is True
    result = res["result"]
    assert result["ok"] is True
    assert result["size"] == [800, 600]
    assert result["described"] is True
    assert result["description"] == "um terminal aberto"
    assert "image_b64" not in result  # a imagem crua nunca entra no resultado/auditoria


def test_vision_screen_describe_false_nao_chama_descricao(db, monkeypatch):
    db.grant_permission("vision.screen")
    monkeypatch.setattr("src.vision_read.capture_screen",
                        lambda: {"ok": True, "size": [800, 600], "image_b64": "xyz"})

    def _boom(image_b64, prompt):
        raise AssertionError("não deveria descrever")
    monkeypatch.setattr("src.tools.vision._describe", _boom)

    res = run_tool("vision.screen", {"describe": False}, db)
    assert res["ok"] is True
    assert "described" not in res["result"]


def test_vision_screen_falha_de_captura_propaga_erro(db, monkeypatch):
    db.grant_permission("vision.screen")
    monkeypatch.setattr("src.vision_read.capture_screen",
                        lambda: {"ok": False, "error": "sem display"})

    res = run_tool("vision.screen", {}, db)
    assert res["ok"] is True  # run_tool: executou (não foi negado), o handler que reportou falha
    assert res["result"]["ok"] is False
    assert "sem display" in res["result"]["error"]


def test_vision_screen_sem_modelo_de_visao_ainda_captura(db, monkeypatch):
    db.grant_permission("vision.screen")
    monkeypatch.setattr("src.vision_read.capture_screen",
                        lambda: {"ok": True, "size": [10, 10], "image_b64": "x"})
    monkeypatch.setattr("src.tools.vision._describe",
                        lambda image_b64, prompt: {"ok": False, "error": "sem modelo de visão"})

    res = run_tool("vision.screen", {}, db)
    result = res["result"]
    assert result["described"] is False
    assert "describe_error" in result and "description" not in result
