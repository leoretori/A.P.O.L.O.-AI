"""Testes da Fase 5 — Multi-agente, Benchmark, Orquestrador."""

import pytest


# ── Benchmark ─────────────────────────────────────────────────────────────────

def test_score_response_todos_keywords():
    from src.benchmark import score_response
    r = score_response("asyncio event loop cpu I/O thread", ["asyncio", "event loop", "cpu", "I/O", "thread"], 30)
    assert r["keyword_score"] == 1.0
    assert r["length_ok"] is True
    assert r["score"] > 0.9


def test_score_response_nenhum_keyword():
    from src.benchmark import score_response
    r = score_response("resposta sem palavras esperadas aqui", ["asyncio", "thread"], 10)
    assert r["keyword_score"] == 0.0
    assert r["keywords_matched"] == 0


def test_score_response_length_fail():
    from src.benchmark import score_response
    r = score_response("curto", ["curto"], 100)  # min_len=100, mas texto tem 5 chars
    assert r["length_ok"] is False
    assert r["score"] < 1.0


def test_score_response_partial_keywords():
    from src.benchmark import score_response
    r = score_response("Python asyncio for loop", ["asyncio", "thread", "cpu", "I/O"], 10)
    assert 0 < r["keyword_score"] < 1.0
    assert r["keywords_matched"] == 1


def test_diff_runs_melhora():
    from src.benchmark import diff_runs
    run_a = {"avg_score": 0.6, "avg_latency_ms": 2000, "results": [
        {"id": "q1", "category": "coding", "score": 0.6, "latency_ms": 2000}
    ]}
    run_b = {"avg_score": 0.8, "avg_latency_ms": 1500, "results": [
        {"id": "q1", "category": "coding", "score": 0.8, "latency_ms": 1500}
    ]}
    diff = diff_runs(run_a, run_b)
    assert diff["improved"] is True
    assert diff["delta_score"] == pytest.approx(0.2, abs=0.001)
    assert diff["delta_latency_ms"] == -500


def test_diff_runs_piora():
    from src.benchmark import diff_runs
    run_a = {"avg_score": 0.9, "avg_latency_ms": 1000, "results": [
        {"id": "q1", "category": "coding", "score": 0.9, "latency_ms": 1000}
    ]}
    run_b = {"avg_score": 0.5, "avg_latency_ms": 3000, "results": [
        {"id": "q1", "category": "coding", "score": 0.5, "latency_ms": 3000}
    ]}
    diff = diff_runs(run_a, run_b)
    assert diff["improved"] is False
    assert diff["delta_score"] < 0


def test_benchmark_questions_tem_campos_obrigatorios():
    from src.benchmark import QUESTIONS
    assert len(QUESTIONS) >= 6
    for q in QUESTIONS:
        assert "id" in q
        assert "question" in q
        assert "expected" in q
        assert "min_len" in q
        assert "category" in q
        assert isinstance(q["expected"], list)
        assert len(q["expected"]) > 0


# ── Orquestrador ──────────────────────────────────────────────────────────────

def test_parse_plan_direto():
    from src.orchestrator import parse_plan
    plan = parse_plan("DIRETO: Aqui está a resposta.")
    assert "direct" in plan
    assert "Aqui está a resposta" in plan["direct"]


def test_parse_plan_especialistas():
    from src.orchestrator import parse_plan
    text = """RESEARCHER: Buscar sobre asyncio
ANALYST: Analisar trade-offs
CODER: Implementar exemplo"""
    plan = parse_plan(text)
    assert "tasks" in plan
    specialists = [sp for sp, _ in plan["tasks"]]
    assert "researcher" in specialists
    assert "analyst" in specialists
    assert "coder" in specialists


def test_parse_plan_apenas_coder():
    from src.orchestrator import parse_plan
    plan = parse_plan("CODER: Implementar uma função de Fibonacci")
    assert "tasks" in plan
    assert plan["tasks"][0][0] == "coder"


def test_parse_plan_fallback_quando_invalido():
    from src.orchestrator import parse_plan
    plan = parse_plan("texto aleatório sem marcadores")
    # Deve retornar direto ou tasks não-vazio
    assert "direct" in plan or "tasks" in plan


def test_orchestrator_specialist_system_prompts():
    from src.orchestrator import _SPECIALIST_SYSTEM
    for sp in ("researcher", "analyst", "coder"):
        assert sp in _SPECIALIST_SYSTEM
        assert len(_SPECIALIST_SYSTEM[sp]) > 50


def test_orchestrator_icons_labels():
    from src.orchestrator import _ICON, _LABEL
    for sp in ("researcher", "analyst", "coder"):
        assert sp in _ICON
        assert sp in _LABEL
