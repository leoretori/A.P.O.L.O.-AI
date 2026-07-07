"""Leitura de arquivos com permissão (M6, Épico 6.2).

O grant `files.read` abre a capacidade; a note do grant é a ALLOWLIST de pastas.
Regra de ouro: nada fora das pastas autorizadas é lido — nem com `..`, nem por
symlink, nem com o grant concedido. E sem grant, o run_tool nega antes de tocar
o disco. Tudo read-only.
"""
import os

import pytest

from src.storage import DatabaseManager
from src.tools import registry, run_tool
from src.tools.files import parse_roots, search_files, read_file


@pytest.fixture
def db(tmp_path):
    return DatabaseManager(database_url=f"sqlite:///{tmp_path}/tools.db")


@pytest.fixture
def sandbox(tmp_path):
    """Cria uma pasta autorizada com arquivos + uma pasta PROIBIDA fora dela."""
    allowed = tmp_path / "autorizada"
    allowed.mkdir()
    (allowed / "notas.md").write_text("conteúdo de notas", encoding="utf-8")
    (allowed / "config.json").write_text('{"k": 1}', encoding="utf-8")
    sub = allowed / "sub"
    sub.mkdir()
    (sub / "diario.txt").write_text("querido diário", encoding="utf-8")
    # ruído que a busca deve ignorar
    noise = allowed / ".git"
    noise.mkdir()
    (noise / "HEAD").write_text("ref", encoding="utf-8")

    secret = tmp_path / "proibida"
    secret.mkdir()
    (secret / "segredo.txt").write_text("SENHA=1234", encoding="utf-8")
    return {"allowed": allowed, "secret": secret}


# ── Funções puras: allowlist ──────────────────────────────────
def test_parse_roots_multiplas_e_inexistentes(sandbox, tmp_path):
    note = f"{sandbox['allowed']}\n{tmp_path / 'nao_existe'};{sandbox['secret']}"
    roots = parse_roots(note)
    assert sandbox["allowed"] in roots and sandbox["secret"] in roots
    assert all(r.is_dir() for r in roots)          # pastas inexistentes caem fora


def test_search_encontra_e_ignora_ruido(sandbox):
    roots = [sandbox["allowed"]]
    nomes = {h["name"] for h in search_files("", roots)}
    assert {"notas.md", "config.json", "diario.txt"} <= nomes
    assert "HEAD" not in nomes                      # .git podado
    # filtro por nome
    so_json = search_files("config", roots)
    assert [h["name"] for h in so_json] == ["config.json"]


def test_read_dentro_da_allowlist(sandbox):
    roots = [sandbox["allowed"]]
    out = read_file(str(sandbox["allowed"] / "notas.md"), roots)
    assert out["content"] == "conteúdo de notas"
    assert out["truncated"] is False


def test_read_fora_da_allowlist_e_negado(sandbox):
    roots = [sandbox["allowed"]]
    with pytest.raises(PermissionError):
        read_file(str(sandbox["secret"] / "segredo.txt"), roots)


def test_read_traversal_com_dotdot_e_negado(sandbox):
    """`../proibida/segredo.txt` a partir da pasta autorizada não pode escapar."""
    roots = [sandbox["allowed"]]
    escape = str(sandbox["allowed"] / ".." / "proibida" / "segredo.txt")
    with pytest.raises(PermissionError):
        read_file(escape, roots)


def test_read_trunca_arquivo_grande(sandbox):
    big = sandbox["allowed"] / "grande.txt"
    big.write_text("x" * 5000, encoding="utf-8")
    out = read_file(str(big), [sandbox["allowed"]], max_bytes=1000)
    assert out["truncated"] is True and len(out["content"]) == 1000


# ── Via run_tool: porteira + allowlist juntos ─────────────────
def test_run_tool_files_read_negado_sem_grant(db, sandbox):
    r = run_tool("files.read", {"path": str(sandbox["allowed"] / "notas.md")}, db)
    assert r["ok"] is False and r.get("denied") is True
    assert r["scope"] == "files.read"


def test_run_tool_files_read_ok_com_grant_e_pasta(db, sandbox):
    db.grant_permission("files.read", note=str(sandbox["allowed"]))
    r = run_tool("files.read", {"path": str(sandbox["allowed"] / "notas.md")}, db)
    assert r["ok"] is True
    assert r["result"]["content"] == "conteúdo de notas"


def test_run_tool_files_read_fora_da_pasta_vira_erro_nao_denied(db, sandbox):
    """Grant existe, mas o caminho está fora da allowlist → erro (não 'denied')
    e a tentativa fica auditada."""
    db.grant_permission("files.read", note=str(sandbox["allowed"]))
    r = run_tool("files.read", {"path": str(sandbox["secret"] / "segredo.txt")}, db)
    assert r["ok"] is False and not r.get("denied")
    assert "autorizada" in r["error"]
    assert db.list_tool_audit()[0]["tool"] == "files.read"   # auditado


def test_run_tool_files_search_sem_pasta_na_note(db, sandbox):
    """Grant sem note (nenhuma pasta) → capacidade aberta mas nada a ler."""
    db.grant_permission("files.read")            # sem note
    r = run_tool("files.search", {"query": "notas"}, db)
    assert r["ok"] is False and "nenhuma pasta autorizada" in r["error"]


def test_run_tool_files_search_lista_arquivos(db, sandbox):
    db.grant_permission("files.read", note=str(sandbox["allowed"]))
    r = run_tool("files.search", {"query": "diario"}, db)
    assert r["ok"] is True
    assert r["result"]["count"] == 1
    assert r["result"]["results"][0]["name"] == "diario.txt"


def test_ferramentas_de_arquivo_registradas():
    names = {t.name for t in registry.all_tools()}
    assert {"files.search", "files.read"} <= names
