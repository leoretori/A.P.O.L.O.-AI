"""Contadores do takeover (M27): registrar quem serviu e computar a cobertura."""
import pytest

from src.storage import DatabaseManager


@pytest.fixture()
def db(tmp_path):
    return DatabaseManager(f"sqlite:///{tmp_path/'t.db'}")


def test_record_incrementa_agregado(db):
    db.nano_record_serve("title", "nano")
    db.nano_record_serve("title", "nano")
    db.nano_record_serve("title", "teacher")
    cov = db.nano_coverage()
    assert cov["tasks"]["title"] == {"nano": 2, "teacher": 1, "total": 3, "pct": 66.7}


def test_coverage_geral_soma_tarefas(db):
    db.nano_record_serve("title", "nano")
    db.nano_record_serve("title", "nano")
    db.nano_record_serve("title", "nano")
    db.nano_record_serve("sector", "teacher")
    ov = db.nano_coverage()["overall"]
    assert ov == {"nano": 3, "teacher": 1, "total": 4, "pct": 75.0}


def test_coverage_vazia(db):
    cov = db.nano_coverage()
    assert cov["overall"]["total"] == 0 and cov["overall"]["pct"] == 0.0
    assert cov["tasks"] == {}


def test_served_by_invalido_vira_teacher(db):
    db.nano_record_serve("title", "qualquer_coisa")   # só nano|teacher são válidos
    cov = db.nano_coverage()
    assert cov["tasks"]["title"]["teacher"] == 1 and cov["tasks"]["title"]["nano"] == 0


def test_task_vazia_e_ignorada(db):
    db.nano_record_serve("", "nano")
    assert db.nano_coverage()["overall"]["total"] == 0
