"""Instrumento de calibração do limiar de memória semântica (MEMORY_MIN_RELEVANCE).

Item pendente do polish do chat (2026-07-13): o limiar (0.18, hoje) deixou passar
memória-lixo como fonte de uma resposta. Subir o valor no escuro poderia suprimir
memória LEGÍTIMA que o A.P.O.L.O. estudou — pior que mostrar uma fonte fraca. Este
módulo mede a distribuição REAL de scores de recall contra perguntas REAIS do
usuário (não sintéticas), para que a decisão de mudar o limiar seja tomada com
dado, não no escuro.

Não altera nada — é só leitura/relatório. A troca do limiar (se fizer sentido)
é uma linha em .env (MEMORY_MIN_RELEVANCE), decisão do Leo.
"""
import os

DEFAULT_THRESHOLDS = (0.10, 0.15, 0.18, 0.22, 0.25, 0.30, 0.35)


def _percentile(sorted_scores: list[float], p: float) -> float | None:
    if not sorted_scores:
        return None
    if len(sorted_scores) == 1:
        return round(sorted_scores[0], 3)
    idx = p * (len(sorted_scores) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_scores) - 1)
    frac = idx - lo
    return round(sorted_scores[lo] + (sorted_scores[hi] - sorted_scores[lo]) * frac, 3)


def calibrate(mem, queries: list[str], n: int = 8,
             thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS) -> dict:
    """Roda `mem.recall(query, kind="semantic", limit=n)` para cada pergunta REAL
    e agrega os scores. `mem` é o MemoryFabric (ou qualquer objeto com esse
    `.recall`); injetável para os testes."""
    current = float(os.getenv("MEMORY_MIN_RELEVANCE", "0.18"))
    queries = [q.strip() for q in (queries or []) if (q or "").strip()]
    scores: list[float] = []
    zero_hit_queries = 0
    for q in queries:
        try:
            hits = mem.recall(q, kind="semantic", limit=n)
        except Exception:
            hits = []
        found = [h.score for h in hits if getattr(h, "score", None) is not None]
        if not found:
            zero_hit_queries += 1
        scores.extend(found)

    scores.sort()
    by_threshold = {
        t: sum(1 for s in scores if s >= t) for t in thresholds
    }
    total = len(scores)
    return {
        "queries_amostradas": len(queries),
        "queries_sem_nenhum_resultado": zero_hit_queries,
        "scores_coletados": total,
        "min": round(scores[0], 3) if scores else None,
        "p25": _percentile(scores, 0.25),
        "mediana": _percentile(scores, 0.5),
        "p75": _percentile(scores, 0.75),
        "max": round(scores[-1], 3) if scores else None,
        "limiar_atual": current,
        "passariam_no_limiar_atual": sum(1 for s in scores if s >= current),
        "por_limiar_candidato": {
            f"{t:.2f}": {"passariam": c, "seriam_cortados": total - c}
            for t, c in by_threshold.items()
        },
    }
