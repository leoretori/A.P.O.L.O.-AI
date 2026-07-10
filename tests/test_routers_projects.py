"""Router de projetos autodirigidos (M12 12.1): sugerir → adotar → progredir,
com DB real e sinais injetados via um fake mínimo."""
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import runtime as rt
from src.storage import DatabaseManager
import routers.projects as pr
from routers.projects import router


def _client(signals):
    d = tempfile.mkdtemp()
    db = DatabaseManager(f"sqlite:///{Path(d) / 'app.db'}")
    rt.configure(db=db, learner=None)
    # injeta os sinais (evita depender das dezenas de métricas reais)
    pr._gather_signals = lambda: signals
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_suggest_deriva_metas():
    c = _client({"raw_summaries": 30, "pct_structured": 50, "hallucination_rate": 0.4})
    d = c.get("/api/projects/suggest").json()
    kinds = {g["kind"] for g in d["goals"]}
    assert "hallucination" in kinds and "summary_quality" in kinds
    assert all("tasks" in g for g in d["goals"])       # já vem com os passos


def test_adotar_e_omitir_da_proxima_sugestao():
    c = _client({"gap_count": 20})
    # adota a meta de lacunas
    ad = c.post("/api/projects/adopt", json={"kind": "gaps", "title": "Fechar lacunas", "why": "20 lacunas"}).json()
    assert ad["ok"] and ad["project"]["progress"] == 0
    # agora suggest NÃO repete a meta já adotada
    goals = c.get("/api/projects/suggest").json()["goals"]
    assert all(g["kind"] != "gaps" for g in goals)


def test_progresso_via_endpoint():
    c = _client({"duplicates": 30})
    pid = c.post("/api/projects/adopt", json={"kind": "dedup", "title": "Limpar"}).json()["project"]["id"]
    r = c.post(f"/api/projects/{pid}/task", json={"index": 0, "done": True}).json()
    assert r["ok"] and r["project"]["progress"] > 0


def test_status_e_delete():
    c = _client({})
    pid = c.post("/api/projects/adopt", json={"kind": "coder", "title": "X"}).json()["project"]["id"]
    assert c.post(f"/api/projects/{pid}/status", json={"status": "dismissed"}).json()["ok"]
    assert c.request("DELETE", f"/api/projects/{pid}").json()["ok"]


def test_adopt_valida():
    c = _client({})
    assert c.post("/api/projects/adopt", json={"title": "sem kind"}).json()["ok"] is False


# ───────────────────────────── M19.1 execução supervisionada ─────────────────
def test_plan_lista_passos_executaveis():
    c = _client({"duplicates": 30})
    pid = c.post("/api/projects/adopt", json={"kind": "dedup", "title": "Limpar"}).json()["project"]["id"]
    d = c.get(f"/api/projects/{pid}/plan").json()
    assert d["ok"]
    keys = [s["key"] for s in d["plan"]]
    assert "dedup_topics" in keys and all(s["executable"] for s in d["plan"])


def test_preview_nao_muta_e_run_remede_e_avanca():
    c = _client({"duplicates": 30})
    pid = c.post("/api/projects/adopt", json={"kind": "dedup", "title": "Limpar"}).json()["project"]["id"]
    # prévia da medição (read-only): dois passos, sem efeito
    pv = c.post(f"/api/projects/{pid}/steps/measure_duplicates/preview").json()
    assert pv["ok"] and "count" in pv["preview"]
    # executa e marca o passo 0 do checklist → o projeto avança
    run = c.post(f"/api/projects/{pid}/steps/measure_duplicates/run",
                 json={"task_index": 0}).json()
    assert run["ok"] and "measure" in run
    assert run["project"]["tasks"][0]["done"] is True


def test_plan_projeto_inexistente():
    c = _client({})
    assert c.get("/api/projects/9999/plan").json()["ok"] is False


def test_step_desconhecido():
    c = _client({"duplicates": 30})
    pid = c.post("/api/projects/adopt", json={"kind": "dedup", "title": "L"}).json()["project"]["id"]
    assert c.post(f"/api/projects/{pid}/steps/nao_existe/run").json()["ok"] is False
