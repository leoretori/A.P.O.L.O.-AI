"""Projetos autodirigidos (M12, Épico 12.1): propor metas das próprias métricas,
quebrar em passos e medir progresso — tudo determinístico, sem LLM."""
from src import projects as P


# ── propose_goals ───────────────────────────────────────────────
def test_sem_problemas_nao_propoe_nada():
    s = {"pct_structured": 95, "raw_summaries": 0, "coder_success": 90,
         "hallucination_rate": 0.0, "gap_count": 0, "duplicates": 0, "down_votes": 0}
    assert P.propose_goals(s) == []


def test_propoe_qualidade_de_sintese():
    goals = P.propose_goals({"pct_structured": 55, "raw_summaries": 40})
    g = next(x for x in goals if x["kind"] == "summary_quality")
    assert "40 sínteses cruas" in g["why"] and g["priority"] == 3   # <60% = urgente


def test_propoe_reduzir_alucinacao():
    g = P.propose_goals({"hallucination_rate": 0.4})[0]
    assert g["kind"] == "hallucination" and g["priority"] == 3


def test_ordena_por_prioridade():
    s = {"gap_count": 10, "hallucination_rate": 0.5}   # gaps p1, alucinação p3
    goals = P.propose_goals(s)
    assert goals[0]["kind"] == "hallucination"          # urgente primeiro
    assert goals[-1]["kind"] == "gaps"


def test_limiar_conservador():
    # 3 lacunas (<=5) e 10 duplicatas (<=20) não disparam meta
    assert P.propose_goals({"gap_count": 3, "duplicates": 10}) == []


def test_coder_e_feedback():
    goals = P.propose_goals({"coder_success": 40, "down_votes": 5})
    kinds = {g["kind"] for g in goals}
    assert "coder" in kinds and "feedback" in kinds


# ── break_into_tasks ────────────────────────────────────────────
def test_passos_por_tipo():
    tasks = P.break_into_tasks({"kind": "summary_quality"})
    assert len(tasks) == 3 and any("Reparar" in t for t in tasks)


def test_passos_default_para_tipo_desconhecido():
    assert P.break_into_tasks({"kind": "xyz"}) == P._DEFAULT_TASKS


# ── project_progress ────────────────────────────────────────────
def test_progresso():
    assert P.project_progress([]) == 0
    assert P.project_progress([{"done": True}, {"done": False}]) == 50
    assert P.project_progress([{"done": True}, {"done": True}]) == 100
