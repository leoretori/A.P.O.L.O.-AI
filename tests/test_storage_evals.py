"""Persistência do harness de avaliação (M9 9.1/9.3): salvar runs canário e
computar a TENDÊNCIA de qualidade ('estou melhorando?')."""
import tempfile
from pathlib import Path

import pytest

from src.storage import DatabaseManager


@pytest.fixture()
def db():
    d = tempfile.mkdtemp()
    yield DatabaseManager(f"sqlite:///{Path(d) / 'evals.db'}")


def _run(score, hall, passed=3, total=4):
    return {"score": score, "passed": passed, "total": total,
            "hallucination_rate": hall, "by_kind": {"chat": {"score": score, "passed": 1, "total": 1}},
            "results": [{"id": "a", "kind": "chat", "score": score, "passed": True}]}


def test_salva_e_le_historico(db):
    rid = db.save_eval_run(_run(0.8, 0.1))
    assert rid > 0
    hist = db.get_eval_history()
    assert len(hist) == 1
    r = hist[0]
    assert r["score"] == 0.8 and r["hallucination_rate"] == 0.1
    assert r["by_kind"]["chat"]["passed"] == 1     # JSON round-trip preservado
    assert db.count_eval_runs() == 1


def test_latest_eval_pega_o_mais_recente(db):
    db.save_eval_run(_run(0.5, 0.3))
    db.save_eval_run(_run(0.9, 0.0))
    assert db.latest_eval()["score"] == 0.9


def test_eval_trend_detecta_melhora(db):
    # janela anterior (piores) primeiro, depois a recente (melhores)
    for _ in range(3):
        db.save_eval_run(_run(0.5, 0.4))
    for _ in range(3):
        db.save_eval_run(_run(0.8, 0.1))
    trend = db.eval_trend(window=3)
    assert trend["recent_score"] == 0.8 and trend["prev_score"] == 0.5
    assert trend["score_trend"] == 0.3          # nota subiu
    # alucinação caiu de 0.4 → 0.1: melhora vira número POSITIVO
    assert trend["hallucination_trend"] == 0.3


def test_eval_trend_sem_historico_suficiente(db):
    db.save_eval_run(_run(0.7, 0.2))
    trend = db.eval_trend(window=3)
    assert trend["prev_score"] is None and trend["score_trend"] is None
