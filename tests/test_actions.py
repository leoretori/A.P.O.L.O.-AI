"""Ações confirmáveis e reversíveis (M10, Épico 10.1).

Trava o ciclo preview → apply → undo da escrita de arquivo (confinada à
allowlist, à prova de fuga) E o motor genérico de ações (portão de permissão +
ledger de undo). Núcleo determinístico; efeitos em pastas temporárias.
"""
import tempfile
from pathlib import Path

import pytest

from src import actions
from src.tools import files_write as fw


@pytest.fixture()
def root():
    d = Path(tempfile.mkdtemp())
    yield d


# ── funções puras de escrita ────────────────────────────────────
def test_preview_criar_nao_toca_o_disco(root):
    alvo = root / "novo.md"
    pv = fw.preview_write({"path": str(alvo), "content": "olá"}, [root])
    assert pv["action"] == "create" and pv["exists"] is False
    assert pv["new_bytes"] == 4 and pv["reversible"] is True   # á = 2 bytes em UTF-8
    assert not alvo.exists()          # prévia NÃO escreve


def test_preview_overwrite_mostra_trecho_antigo(root):
    alvo = root / "a.txt"
    alvo.write_text("conteúdo velho", encoding="utf-8")
    pv = fw.preview_write({"path": str(alvo), "content": "novo"}, [root])
    assert pv["action"] == "overwrite" and pv["exists"] is True
    assert "velho" in pv["old_preview"] and pv["new_preview"] == "novo"


def test_apply_escreve_e_devolve_undo(root):
    alvo = root / "sub" / "x.txt"
    alvo.parent.mkdir()
    out = fw.apply_write({"path": str(alvo), "content": "primeiro"}, [root])
    assert alvo.read_text(encoding="utf-8") == "primeiro"
    assert out["undo"]["existed"] is False and out["undo"]["old_content"] is None


def test_undo_de_criacao_remove_o_arquivo(root):
    alvo = root / "temp.txt"
    out = fw.apply_write({"path": str(alvo), "content": "abc"}, [root])
    assert alvo.exists()
    fw.undo_write(out["undo"], [root])
    assert not alvo.exists()          # criado do zero → undo apaga


def test_undo_de_overwrite_restaura_conteudo(root):
    alvo = root / "cfg.txt"
    alvo.write_text("ORIGINAL", encoding="utf-8")
    out = fw.apply_write({"path": str(alvo), "content": "MODIFICADO"}, [root])
    assert alvo.read_text(encoding="utf-8") == "MODIFICADO"
    fw.undo_write(out["undo"], [root])
    assert alvo.read_text(encoding="utf-8") == "ORIGINAL"   # revertido


def test_escrita_fora_da_allowlist_e_negada(root):
    fora = Path(tempfile.mkdtemp()) / "hack.txt"
    with pytest.raises(PermissionError):
        fw.preview_write({"path": str(fora), "content": "x"}, [root])
    with pytest.raises(PermissionError):
        fw.apply_write({"path": str(fora), "content": "x"}, [root])


def test_traversal_com_dotdot_bloqueado(root):
    alvo = root / ".." / "escape.txt"
    with pytest.raises(PermissionError):
        fw.apply_write({"path": str(alvo), "content": "x"}, [root])


def test_sem_pasta_autorizada_e_erro(root):
    with pytest.raises(PermissionError):
        fw.preview_write({"path": "qualquer.txt", "content": "x"}, [])


def test_conteudo_acima_do_teto_recusado(root):
    grande = "a" * (fw.MAX_WRITE_BYTES + 1)
    with pytest.raises(ValueError):
        fw.apply_write({"path": str(root / "big.txt"), "content": grande}, [root])


# ── motor de ações (portão + auditoria + undo via db fake) ──────
class FakeDB:
    def __init__(self, granted=True, note=""):
        self._granted, self._note = granted, note
        self.audit, self._undo, self._seq = [], {}, 0

    def is_permission_granted(self, scope): return self._granted
    def permission_note(self, scope): return self._note
    def log_tool(self, *a): self.audit.append(a)

    def save_undo(self, kind, desc, data):
        self._seq += 1
        self._undo[self._seq] = {"id": self._seq, "kind": kind, "description": desc,
                                 "undo_data": data, "undone": False}
        return self._seq

    def get_undo(self, i): return self._undo.get(i)
    def mark_undone(self, i):
        if i in self._undo and not self._undo[i]["undone"]:
            self._undo[i]["undone"] = True
            return True
        return False


def test_engine_ciclo_completo_com_permissao(root):
    db = FakeDB(granted=True, note=str(root))
    alvo = root / "diario.md"

    pv = actions.preview_action("files.write", {"path": str(alvo), "content": "oi"}, db)
    assert pv["ok"] and pv["preview"]["action"] == "create"
    assert not alvo.exists()                     # preview não escreve

    ap = actions.apply_action("files.write", {"path": str(alvo), "content": "oi"}, db)
    assert ap["ok"] and ap["reversible"] and ap["undo_id"] == 1
    assert alvo.read_text(encoding="utf-8") == "oi"

    un = actions.undo_action(ap["undo_id"], db)
    assert un["ok"] and not alvo.exists()
    # auditou preview, apply e undo
    assert {a[0] for a in db.audit} == {"files.write:preview", "files.write:apply", "files.write:undo"}


def test_engine_sem_permissao_nega_e_nao_escreve(root):
    db = FakeDB(granted=False, note=str(root))
    alvo = root / "bloqueado.txt"
    ap = actions.apply_action("files.write", {"path": str(alvo), "content": "x"}, db)
    assert ap["ok"] is False and ap["denied"] is True
    assert not alvo.exists()
    assert db.audit[-1][2] is False              # auditado como negado


def test_engine_undo_idempotente(root):
    db = FakeDB(granted=True, note=str(root))
    alvo = root / "f.txt"
    ap = actions.apply_action("files.write", {"path": str(alvo), "content": "y"}, db)
    assert actions.undo_action(ap["undo_id"], db)["ok"]
    again = actions.undo_action(ap["undo_id"], db)
    assert again["ok"] is False and again.get("already") is True


def test_engine_acao_desconhecida():
    assert actions.preview_action("nope", {}, None)["ok"] is False


def test_engine_undo_negado_apos_revogar_permissao(root):
    """Achado da auditoria de segurança (2026-07-15): revogar a permissão
    DEPOIS de aplicar uma ação não impedia desfazê-la — undo_action não
    checava o grant. `note` (allowlist) sobrevive à revogação, então sem essa
    checagem o undo continuava escrevendo/apagando arquivos sem consentimento."""
    db = FakeDB(granted=True, note=str(root))
    alvo = root / "f.txt"
    ap = actions.apply_action("files.write", {"path": str(alvo), "content": "y"}, db)
    assert ap["ok"] and alvo.exists()

    db._granted = False   # revoga files.write
    un = actions.undo_action(ap["undo_id"], db)
    assert un["ok"] is False and un["denied"] is True
    assert alvo.exists() and alvo.read_text(encoding="utf-8") == "y"   # intacto
    assert db.audit[-1] == ("files.write:undo", "files.write", False,
                            actions._summarize({"undo_id": ap["undo_id"]}),
                            actions._summarize("denied"))
