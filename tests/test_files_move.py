"""Ação de mover/organizar arquivo — confirmável e reversível (M21.1).

Trava o ciclo preview → apply → undo do MOVE (confinado à allowlist, à prova de
fuga) e a integração no motor de ações. Núcleo determinístico; pastas temporárias.
"""
import tempfile
from pathlib import Path

import pytest

from src import actions
from src.tools import files_move as fm
from tests.test_actions import FakeDB


@pytest.fixture()
def root():
    d = Path(tempfile.mkdtemp())
    (d / "origem").mkdir()
    (d / "destino").mkdir()
    (d / "origem" / "nota.txt").write_text("conteúdo", encoding="utf-8")
    yield d


def test_preview_move_nao_toca_o_disco(root):
    src = root / "origem" / "nota.txt"
    pv = fm.preview_move({"src": str(src), "dst": str(root / "destino")}, [root])
    assert pv["action"] == "move" and pv["reversible"] is True
    assert pv["dst"].endswith("nota.txt") and pv["target_exists"] is False
    assert src.exists()                         # prévia NÃO move


def test_preview_rename_mesma_pasta(root):
    src = root / "origem" / "nota.txt"
    pv = fm.preview_move({"src": str(src), "dst": str(root / "origem" / "nova.txt")}, [root])
    assert pv["action"] == "rename"


def test_apply_move_para_pasta_e_undo_volta(root):
    src = root / "origem" / "nota.txt"
    out = fm.apply_move({"src": str(src), "dst": str(root / "destino")}, [root])
    dst = root / "destino" / "nota.txt"
    assert dst.is_file() and not src.exists()   # moveu
    assert "Moveu" in out["description"]
    fm.undo_move(out["undo"], [root])
    assert src.is_file() and not dst.exists()   # voltou


def test_apply_nao_sobrescreve_destino_existente(root):
    src = root / "origem" / "nota.txt"
    (root / "destino" / "nota.txt").write_text("já existe", encoding="utf-8")
    with pytest.raises(FileExistsError):
        fm.apply_move({"src": str(src), "dst": str(root / "destino")}, [root])
    assert src.exists()                         # nada mudou


def test_undo_recusa_se_origem_reocupada(root):
    src = root / "origem" / "nota.txt"
    out = fm.apply_move({"src": str(src), "dst": str(root / "destino")}, [root])
    src.write_text("reocupado", encoding="utf-8")   # alguém recriou a origem
    with pytest.raises(FileExistsError):
        fm.undo_move(out["undo"], [root])


def test_move_fora_da_allowlist_e_negado(root):
    src = root / "origem" / "nota.txt"
    fora = Path(tempfile.mkdtemp()) / "roubado.txt"
    with pytest.raises(PermissionError):
        fm.preview_move({"src": str(src), "dst": str(fora)}, [root])
    with pytest.raises(PermissionError):
        fm.apply_move({"src": str(src), "dst": str(fora)}, [root])


def test_traversal_dotdot_bloqueado(root):
    src = root / "origem" / "nota.txt"
    with pytest.raises(PermissionError):
        fm.apply_move({"src": str(src), "dst": str(root / ".." / "escape.txt")}, [root])


def test_src_inexistente_falha(root):
    with pytest.raises(FileNotFoundError):
        fm.apply_move({"src": str(root / "origem" / "fantasma.txt"),
                       "dst": str(root / "destino")}, [root])


def test_sem_pasta_autorizada_e_erro(root):
    with pytest.raises(PermissionError):
        fm.preview_move({"src": "a.txt", "dst": "b.txt"}, [])


def test_engine_ciclo_completo_move(root):
    db = FakeDB(granted=True, note=str(root))
    src = root / "origem" / "nota.txt"
    dst = root / "destino" / "nota.txt"

    pv = actions.preview_action("files.move", {"src": str(src), "dst": str(root / "destino")}, db)
    assert pv["ok"] and pv["preview"]["action"] == "move"
    assert src.exists()                         # preview não move

    ap = actions.apply_action("files.move", {"src": str(src), "dst": str(root / "destino")}, db)
    assert ap["ok"] and ap["reversible"] and dst.is_file()

    un = actions.undo_action(ap["undo_id"], db)
    assert un["ok"] and src.is_file() and not dst.exists()
    assert {a[0] for a in db.audit} == {"files.move:preview", "files.move:apply", "files.move:undo"}


def test_engine_sem_permissao_nega(root):
    db = FakeDB(granted=False, note=str(root))
    src = root / "origem" / "nota.txt"
    ap = actions.apply_action("files.move", {"src": str(src), "dst": str(root / "destino")}, db)
    assert ap["ok"] is False and ap["denied"] is True
    assert src.exists()                         # não moveu
