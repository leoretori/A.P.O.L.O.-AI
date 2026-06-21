"""Benchmark contínuo do A.P.O.L.O. — avalia e rastreia qualidade ao longo do tempo.

Executa um conjunto fixo de perguntas de referência, mede latência e presença
de termos esperados, salva no banco para comparar antes/depois de melhorias.

/api/benchmark/run  → executa e salva
/api/benchmark/history → histórico de runs (N mais recentes)
/api/benchmark/diff → compara os 2 últimos runs
"""

from __future__ import annotations
import logging
import time
import re

logger = logging.getLogger(__name__)

# ── Perguntas de referência ────────────────────────────────────────────────────
# Cada item: id, question, expected_keywords (case-insensitive, tokenizados),
# min_length (chars), category

QUESTIONS: list[dict] = [
    {
        "id": "py_list_comp",
        "question": "Escreva uma list comprehension Python que filtra números pares de 1 a 20.",
        "expected": ["for", "if", "range", "2"],
        "min_len": 20,
        "category": "coding",
    },
    {
        "id": "async_await",
        "question": "Qual a diferença entre async/await e threads em Python? Quando usar cada um?",
        "expected": ["asyncio", "thread", "event loop", "I/O", "cpu"],
        "min_len": 150,
        "category": "explanation",
    },
    {
        "id": "fastapi_deps",
        "question": "Como funciona a injeção de dependências do FastAPI? Dê um exemplo.",
        "expected": ["Depends", "dependency", "injec"],
        "min_len": 80,
        "category": "coding",
    },
    {
        "id": "docker_compose",
        "question": "Para que serve o docker-compose.yml? Quais campos principais ele tem?",
        "expected": ["services", "image", "ports", "volumes", "container"],
        "min_len": 100,
        "category": "devops",
    },
    {
        "id": "sql_index",
        "question": "O que é um índice em banco de dados e quando ele prejudica a performance?",
        "expected": ["índice", "index", "busca", "insert", "update", "tabela"],
        "min_len": 100,
        "category": "database",
    },
    {
        "id": "big_o_on",
        "question": "Qual é a complexidade de tempo de um loop nested dentro de outro loop for em O(n)?",
        "expected": ["O(n²)", "O(n^2)", "quadrático", "n ao quadrado", "nested"],
        "min_len": 40,
        "category": "algorithms",
    },
    {
        "id": "jwt_auth",
        "question": "Como funciona autenticação JWT? Cite as 3 partes do token.",
        "expected": ["header", "payload", "signature", "base64", "secret"],
        "min_len": 100,
        "category": "security",
    },
    {
        "id": "rag_explain",
        "question": "Explique RAG (Retrieval-Augmented Generation) em 3 tópicos.",
        "expected": ["retrieval", "embedding", "geração", "contexto", "vector"],
        "min_len": 120,
        "category": "ai",
    },
]


# ── Scoring ────────────────────────────────────────────────────────────────────

def score_response(response: str, expected: list[str], min_len: int) -> dict:
    """Avalia uma resposta por presença de termos esperados e comprimento mínimo."""
    text = response.lower()
    matched = [kw for kw in expected if kw.lower() in text]
    keyword_score = round(len(matched) / max(1, len(expected)), 3)
    length_ok = len(response) >= min_len
    return {
        "keyword_score": keyword_score,
        "keywords_matched": len(matched),
        "keywords_total": len(expected),
        "length_ok": length_ok,
        "response_len": len(response),
        "score": round((keyword_score * 0.7 + (1.0 if length_ok else 0.0) * 0.3), 3),
    }


# ── Runner ────────────────────────────────────────────────────────────────────

async def run_benchmark(chat_model: str, keep_alive: str, questions: list[dict] | None = None) -> dict:
    """Executa todas as perguntas e devolve resultados + métricas agregadas."""
    from src.llm import chat_resilient
    import asyncio

    qs = questions or QUESTIONS
    results = []
    started_at = time.time()

    for q in qs:
        t0 = time.perf_counter()
        try:
            response = await asyncio.to_thread(
                chat_resilient,
                chat_model,
                [{"role": "user", "content": q["question"]}],
                keep_alive=keep_alive,
                options={"num_predict": 400},
            ) or ""
        except Exception as e:
            logger.warning(f"[benchmark] '{q['id']}' falhou: {e}")
            response = ""
        latency_ms = round((time.perf_counter() - t0) * 1000)
        s = score_response(response, q["expected"], q["min_len"])
        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "response": response[:500],
            "latency_ms": latency_ms,
            **s,
        })

    scores = [r["score"] for r in results]
    avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    avg_latency = round(sum(r["latency_ms"] for r in results) / max(1, len(results)))
    total_ms = round((time.time() - started_at) * 1000)

    return {
        "model": chat_model,
        "questions": len(qs),
        "avg_score": avg_score,
        "avg_latency_ms": avg_latency,
        "total_ms": total_ms,
        "results": results,
    }


def diff_runs(run_a: dict, run_b: dict) -> dict:
    """Compara dois runs: run_b - run_a (positivo = melhorou)."""
    delta_score = round(run_b["avg_score"] - run_a["avg_score"], 3)
    delta_latency = run_b["avg_latency_ms"] - run_a["avg_latency_ms"]
    by_id_a = {r["id"]: r for r in run_a.get("results", [])}
    by_id_b = {r["id"]: r for r in run_b.get("results", [])}
    per_question = []
    for qid in by_id_b:
        a = by_id_a.get(qid, {})
        b = by_id_b[qid]
        per_question.append({
            "id": qid,
            "category": b["category"],
            "score_before": a.get("score"),
            "score_after": b["score"],
            "delta": round(b["score"] - (a.get("score") or 0), 3),
            "latency_before_ms": a.get("latency_ms"),
            "latency_after_ms": b["latency_ms"],
        })
    return {
        "delta_score": delta_score,
        "delta_latency_ms": delta_latency,
        "improved": delta_score > 0,
        "per_question": sorted(per_question, key=lambda x: x["delta"]),
    }
