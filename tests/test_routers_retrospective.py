"""Router da retrospectiva (M12 12.2): monta o pacote a partir de um DB fake."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.retrospective import router


def _client():
    class FakeDB:
        def get_learning_stats(self): return {"total": 628}
        def analytics_usage_summary(self): return {"days_active": 40}
        def get_coder_stats(self): return {"total": 30, "success_rate": 80}
        def latest_eval(self): return {"score": 0.85, "hallucination_rate": 0.1}
        def reaction_stats(self): return {"up": 12, "down": 1}
        def list_self_projects(self, status=None): return [{"id": 1}] if status == "done" else []
        # sinais p/ _gather_signals (routers.projects)
        def get_summary_quality(self): return {"pct_structured": 95, "raw": 0}
        def count_topic_duplicates(self): return 0
        # sinais do Ano 2 (M24.3)
        def nano_coverage(self): return {"overall": {"nano": 3, "teacher": 7, "total": 10, "pct": 30.0}}
        def list_project_outcomes(self, kind=None, limit=500):
            return [{"improved": True}, {"improved": False}, {"improved": True}]

    rt.configure(db=FakeDB(), learner=None)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_retrospectiva_traz_texto_falavel_e_highlights():
    d = _client().get("/api/retrospective").json()
    assert d["highlights"]["total_topics"] == 628
    assert d["highlights"]["projects_done"] == 1
    assert "628 tópicos" in d["text"] and "40 dias" in d["text"]
    assert d["year_two_themes"]           # sempre propõe algo p/ o ano 2


def test_retrospectiva_ano2_traz_numeros_do_nano_e_projetos():
    d = _client().get("/api/retrospective2").json()
    assert d["highlights"]["total_topics"] == 628
    assert d["highlights"]["nano"] == {"nano": 3, "teacher": 7, "total": 10, "pct": 30.0}
    assert d["highlights"]["projects_measured"] == {"total": 3, "improved": 2}
    assert "628 tópicos" in d["text"] and "30.0%" in d["text"]
    assert d["year3_themes"]              # sempre propõe algo p/ o ano 3
    assert "Ano 3" in d["text"]
