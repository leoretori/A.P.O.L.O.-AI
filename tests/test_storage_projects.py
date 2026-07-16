"""Persistência dos projetos autodirigidos (M12 12.1)."""
import tempfile
from pathlib import Path

import pytest

from src.storage import DatabaseManager


@pytest.fixture()
def db():
    d = tempfile.mkdtemp()
    yield DatabaseManager(f"sqlite:///{Path(d) / 'p.db'}")


def test_salva_com_tarefas_e_progresso(db):
    p = db.save_self_project("gaps", "Fechar lacunas", "8 lacunas", ["a", "b", "c", "d"])
    assert p["progress"] == 0 and len(p["tasks"]) == 4
    assert p["tasks"][0] == {"text": "a", "done": False}


def test_marcar_tarefas_atualiza_progresso_e_conclui(db):
    p = db.save_self_project("dedup", "Limpar", "x", ["um", "dois"])
    pid = p["id"]
    r = db.set_project_task(pid, 0, True)
    assert r["progress"] == 50 and r["status"] == "active"
    r = db.set_project_task(pid, 1, True)
    assert r["progress"] == 100 and r["status"] == "done"   # todas feitas → done
    # desmarcar reabre
    r = db.set_project_task(pid, 1, False)
    assert r["status"] == "active"


def test_lista_e_filtra_por_status(db):
    a = db.save_self_project("gaps", "A", "", ["x"])
    db.save_self_project("coder", "B", "", ["y"])
    db.set_project_status(a["id"], "dismissed")
    assert len(db.list_self_projects()) == 2
    assert len(db.list_self_projects(status="active")) == 1


def test_has_active_project_evita_duplicar(db):
    db.save_self_project("gaps", "A", "", ["x"])
    assert db.has_active_project("gaps") is True
    assert db.has_active_project("coder") is False


def test_delete(db):
    p = db.save_self_project("gaps", "A", "", ["x"])
    assert db.delete_self_project(p["id"]) is True
    assert db.get_self_project(p["id"]) is None


# ── Curva de resultados (M24.1/24.2) ──────────────────────────────
def test_save_e_list_project_outcomes(db):
    p = db.save_self_project("summary_quality", "Melhorar sínteses", "", ["a"])
    out = db.save_project_outcome(p["id"], "summary_quality", "% estruturadas",
                                  40.0, 55.0, 15.0, True, auto=True)
    assert out["baseline"] == 40.0 and out["current"] == 55.0
    assert out["improved"] is True and out["auto"] is True

    rows = db.list_project_outcomes()
    assert len(rows) == 1 and rows[0]["project_id"] == p["id"]


def test_list_project_outcomes_mais_recente_primeiro(db):
    p = db.save_self_project("dedup", "Limpar", "", ["a"])
    db.save_project_outcome(p["id"], "dedup", "duplicatas", 10, 8, -2, True)
    db.save_project_outcome(p["id"], "dedup", "duplicatas", 8, 5, -3, True)
    rows = db.list_project_outcomes()
    assert len(rows) == 2
    assert rows[0]["current"] == 5 and rows[1]["current"] == 8  # mais recente 1º


def test_list_project_outcomes_filtra_por_kind(db):
    p1 = db.save_self_project("dedup", "A", "", ["x"])
    p2 = db.save_self_project("summary_quality", "B", "", ["y"])
    db.save_project_outcome(p1["id"], "dedup", "duplicatas", 10, 8, -2, True)
    db.save_project_outcome(p2["id"], "summary_quality", "% estruturadas", 40, 55, 15, True)
    assert len(db.list_project_outcomes(kind="dedup")) == 1
    assert len(db.list_project_outcomes()) == 2


def test_outcome_estavel_guarda_improved_none(db):
    p = db.save_self_project("dedup", "A", "", ["x"])
    out = db.save_project_outcome(p["id"], "dedup", "duplicatas", 5, 5, 0, None)
    assert out["improved"] is None
