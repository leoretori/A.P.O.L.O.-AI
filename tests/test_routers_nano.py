"""Endpoint /api/nano/flywheel/diagnose — funil de sourcing de pares (2026-07-14),
diagnóstico pra dúvida real do Leo ("por que poucos pares mesmo com conversas novas")."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from routers.nano import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_diagnose_sem_db_reporta_desabilitado():
    rt.configure(db=None)
    r = _client().get("/api/nano/flywheel/diagnose")
    assert r.json() == {"enabled": False}


def test_diagnose_repassa_o_funil_do_banco():
    class _FakeDB:
        def diagnose_pair_sourcing(self):
            return {"total_sessoes": 5, "com_1a_mensagem_valida": 3,
                    "descartadas_curtas_demais": 2, "min_len": 8,
                    "amostra_descartadas": ["oi"], "pares_de_reacoes_up": 4, "nota": "..."}
    rt.configure(db=_FakeDB())
    r = _client().get("/api/nano/flywheel/diagnose")
    d = r.json()
    assert d["enabled"] is True
    assert d["total_sessoes"] == 5 and d["com_1a_mensagem_valida"] == 3
    assert d["pares_de_reacoes_up"] == 4


def test_flywheel_run_min_pairs_padrao_usa_env(monkeypatch):
    from routers.nano import FlywheelRunRequest
    monkeypatch.setenv("FLYWHEEL_MIN_PAIRS", "7")
    assert FlywheelRunRequest().min_pairs == 7
