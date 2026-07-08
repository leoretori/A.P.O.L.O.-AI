"""Ledger de undo (M10 10.1): persistência das ações reversíveis."""
import tempfile
from pathlib import Path

import pytest

from src.storage import DatabaseManager


@pytest.fixture()
def db():
    d = tempfile.mkdtemp()
    yield DatabaseManager(f"sqlite:///{Path(d) / 'undo.db'}")


def test_salva_e_le_undo(db):
    uid = db.save_undo("files.write", "Criou notas.md", {"path": "/x/notas.md", "existed": False})
    e = db.get_undo(uid)
    assert e["kind"] == "files.write" and e["undone"] is False
    assert e["undo_data"]["path"] == "/x/notas.md"     # JSON round-trip


def test_mark_undone_idempotente(db):
    uid = db.save_undo("files.write", "x", {})
    assert db.mark_undone(uid) is True
    assert db.mark_undone(uid) is False                # já desfeito
    assert db.get_undo(uid)["undone"] is True


def test_list_e_filtro_de_pendentes(db):
    a = db.save_undo("files.write", "a", {})
    db.save_undo("files.write", "b", {})
    db.mark_undone(a)
    assert len(db.list_undo()) == 2                     # inclui desfeitos
    pend = db.list_undo(include_undone=False)
    assert len(pend) == 1 and pend[0]["description"] == "b"
    assert db.count_undo(pending_only=True) == 1
