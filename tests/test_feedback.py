"""Loop de feedback do Leo (M9, Épico 9.2): 👍/👎 + 'por quê' viram dado
acionável (o que ele achou ruim e por quê) + tendência de satisfação."""
import tempfile
import time
from pathlib import Path

import pytest

from src.storage import DatabaseManager


@pytest.fixture()
def db():
    d = tempfile.mkdtemp()
    yield DatabaseManager(f"sqlite:///{Path(d) / 'fb.db'}")


def test_salva_motivo_e_par_pergunta_resposta(db):
    db.save_reaction("h1", "down", "s1", ["u"], reason="inventou data",
                     question="quando foi?", answer="foi em 1987")
    neg = db.negative_feedback()
    assert len(neg) == 1
    assert neg[0]["reason"] == "inventou data"
    assert neg[0]["question"] == "quando foi?" and neg[0]["answer"] == "foi em 1987"


def test_upvote_nao_aparece_no_feedback_negativo(db):
    db.save_reaction("h2", "up", "s1", [])
    assert db.negative_feedback() == []


def test_reclique_sem_motivo_nao_apaga_motivo_anterior(db):
    """Re-emitir o 👎 (upsert pelo mesmo hash) sem 'por quê' não deve zerar o
    motivo já registrado."""
    db.save_reaction("h3", "down", "s1", [], reason="alucinou", question="q", answer="a")
    db.save_reaction("h3", "down", "s1", [])   # segundo clique, sem motivo
    neg = db.negative_feedback()
    assert neg[0]["reason"] == "alucinou"


def test_feedback_trend_mede_satisfacao(db):
    # janela anterior: 2 down; janela recente: 2 up → satisfação subiu
    db.save_reaction("a", "down", "", []); time.sleep(0.01)
    db.save_reaction("b", "down", "", []); time.sleep(0.01)
    db.save_reaction("c", "up", "", []); time.sleep(0.01)
    db.save_reaction("d", "up", "", [])
    t = db.feedback_trend(window=2)
    assert t["recent_rate"] == 1.0 and t["prev_rate"] == 0.0 and t["trend"] == 1.0


def test_feedback_trend_vazio(db):
    t = db.feedback_trend()
    assert t["recent_rate"] is None and t["trend"] is None
