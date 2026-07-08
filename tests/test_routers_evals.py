"""Router do harness de avaliação (routers/evals.py, M9 9.1).

Trava o contrato dos endpoints SEM tocar o Ollama: o runner de produção é
substituído por um fake. Garante que /run persiste o placar e /history devolve
histórico + tendência.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
import routers.evals as ev
from routers.evals import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_rotas_registradas():
    paths = {r.path for r in router.routes}
    assert {"/api/evals/run", "/api/evals/history", "/api/improving"} <= paths


def test_run_roda_a_suite_e_persiste(monkeypatch):
    salvos = []

    class FakeDB:
        def save_eval_run(self, run):
            salvos.append(run)
            return 42

    # runner fake: acerta tudo (inclusive admitir incerteza nas armadilhas)
    def fake_make_runner():
        async def runner(task):
            return "ok" if task["kind"] != "trap" else "Não existe, é fictício."
        return runner

    monkeypatch.setattr(ev, "_make_runner", fake_make_runner)
    rt.configure(db=FakeDB(), learner=None, gpu_gate=None)

    r = _client().post("/api/evals/run")
    body = r.json()
    assert r.status_code == 200
    assert body["total"] == len(ev.evals.CANARY)
    assert body["hallucination_rate"] == 0.0        # nenhuma armadilha mordida
    assert body["saved_id"] == 42 and len(salvos) == 1


def test_history_devolve_runs_e_tendencia():
    class FakeDB:
        def get_eval_history(self, limit):
            return [{"id": 2, "score": 0.9}, {"id": 1, "score": 0.5}]

        def eval_trend(self):
            return {"score_trend": 0.4, "hallucination_trend": 0.2}

    rt.configure(db=FakeDB())
    body = _client().get("/api/evals/history").json()
    assert body["runs"] == 2
    assert body["trend"]["score_trend"] == 0.4


def test_improving_funde_tendencias_num_veredito():
    class FakeDB:
        def eval_trend(self):
            return {"score_trend": 0.2, "hallucination_trend": 0.1}

        def feedback_trend(self):
            return {"trend": 0.1}

        def get_coder_stats(self):
            return {"trend": 8}

        def latest_eval(self):
            return {"score": 0.8, "hallucination_rate": 0.1}

        def get_eval_history(self, limit):
            return [{"score": 0.8, "hallucination_rate": 0.1, "ran_at": "t2"},
                    {"score": 0.6, "hallucination_rate": 0.3, "ran_at": "t1"}]

    rt.configure(db=FakeDB())
    body = _client().get("/api/improving").json()
    assert body["report"]["verdict"] == "melhorando"
    assert body["latest"]["score"] == 0.8
    # série vem cronológica (antigo → recente): reverte a history (recente primeiro)
    assert [p["ran_at"] for p in body["series"]] == ["t1", "t2"]
