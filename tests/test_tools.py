"""Agência com permissão (M6, Épico 6.1): o run_tool passa SEMPRE pela porteira
(consentimento) e registra tudo na auditoria. Nada toca o mundo sem grant."""
import pytest

from src.storage import DatabaseManager
from src.tools import registry
from src.tools.registry import Tool, register, run_tool, get, all_tools, SCOPES


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/tools.db")


@pytest.fixture
def demo_tool():
    # Ferramenta com escopo, registrada só para o teste.
    register(Tool(name="_test_read", scope="files.read", description="demo",
                  handler=lambda a: {"echo": a.get("x")}))
    yield
    registry._REGISTRY.pop("_test_read", None)


# ── Ferramenta segura (sem escopo) ────────────────────────────
def test_clock_embutido_roda_sem_permissao(db):
    r = run_tool("clock", {}, db)
    assert r["ok"] is True
    assert "time" in r["result"] and "weekday" in r["result"]


def test_ferramenta_desconhecida():
    assert run_tool("inexistente", {}, None)["ok"] is False


# ── Porteira de permissão ─────────────────────────────────────
def test_negado_sem_consentimento(db, demo_tool):
    r = run_tool("_test_read", {"x": 1}, db)
    assert r["ok"] is False and r["denied"] is True
    assert r["scope"] == "files.read"


def test_permitido_apos_grant(db, demo_tool):
    db.grant_permission("files.read", note="pasta X")
    r = run_tool("_test_read", {"x": 42}, db)
    assert r["ok"] is True and r["result"] == {"echo": 42}


def test_negado_apos_revoke(db, demo_tool):
    db.grant_permission("files.read")
    assert run_tool("_test_read", {}, db)["ok"] is True
    db.revoke_permission("files.read")
    assert run_tool("_test_read", {}, db)["denied"] is True


# ── Auditoria (sempre registra) ───────────────────────────────
def test_toda_invocacao_e_auditada(db, demo_tool):
    run_tool("_test_read", {"x": 1}, db)        # negada
    db.grant_permission("files.read")
    run_tool("_test_read", {"x": 2}, db)        # permitida
    run_tool("clock", {}, db)                    # segura
    audit = db.list_tool_audit()
    assert len(audit) == 3
    by_tool = [(a["tool"], a["allowed"]) for a in audit]
    assert ("_test_read", False) in by_tool
    assert ("_test_read", True) in by_tool
    assert ("clock", True) in by_tool


def test_erro_na_ferramenta_e_capturado(db):
    register(Tool(name="_boom", scope="", description="x",
                  handler=lambda a: (_ for _ in ()).throw(ValueError("falhou"))))
    try:
        r = run_tool("_boom", {}, db)
        assert r["ok"] is False and "falhou" in r["error"]
        assert db.list_tool_audit()[0]["tool"] == "_boom"   # auditado mesmo com erro
    finally:
        registry._REGISTRY.pop("_boom", None)


# ── Permissões (storage) ──────────────────────────────────────
def test_grant_revoke_is_granted(db):
    assert db.is_permission_granted("files.read") is False
    assert db.is_permission_granted("") is True             # sem escopo = livre
    db.grant_permission("files.read")
    assert db.is_permission_granted("files.read") is True
    db.revoke_permission("files.read")
    assert db.is_permission_granted("files.read") is False


def test_scopes_catalogo_tem_os_esperados():
    assert {"files.read", "calendar.read", "email.read"} <= set(SCOPES)


def test_clock_registrado_por_padrao():
    assert get("clock") is not None
    assert any(t.name == "clock" for t in all_tools())
