"""Instrumento de calibração do limiar de memória semântica (MEMORY_MIN_RELEVANCE)
+ gate de regressão do recall (P2.6).

Item pendente do polish do chat (2026-07-13): o limiar (0.18, hoje) deixou passar
memória-lixo como fonte de uma resposta. Subir o valor no escuro poderia suprimir
memória LEGÍTIMA que o A.P.O.L.O. estudou — pior que mostrar uma fonte fraca. Este
módulo mede a distribuição REAL de scores de recall contra perguntas REAIS do
usuário (não sintéticas), para que a decisão de mudar o limiar seja tomada com
dado, não no escuro.

`calibrate()` não altera nada — é só leitura/relatório. A troca do limiar (se
fizer sentido) é uma linha em .env (MEMORY_MIN_RELEVANCE), decisão do Leo.

P2.6: além de calibrar, agora existe um GATE agendado (`freeze_ground_truth` +
`evaluate_recall_gate`) que testa, contra um conjunto FIXO de tópicos já
estudados, se o recall ainda consegue achar o que já sabe — pega regressão de
índice/embedding antes do Leo perceber no uso real (mesma disciplina do
blind-eval, P1.4, e do gate de qualidade, P2.5)."""
import json
import os
from pathlib import Path

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


# ── Gate de regressão do recall (P2.6) ──────────────────────────────
def freeze_ground_truth(db, path: str | Path, n: int = 30, min_topics: int = 15) -> list[str]:
    """Congela N títulos de tópicos JÁ ESTUDADOS como base de verdade — idempotente
    (rodar de novo não re-sorteia, mesmo espírito do `freeze_questions` do P1.4).
    Reusa `sample_topics_for_quality` (P2.5, amostra aleatória via SQL) só pra
    montar o pool inicial; a partir daí o conjunto fica fixo em disco. Levanta
    ValueError se não houver `min_topics` — não força medição com base pequena
    demais pra significar algo (mesmo espírito do 'poucos pares' do projeto)."""
    p = Path(path)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    rows = db.sample_topics_for_quality(n * 3)
    topics = list(dict.fromkeys(r["topic"] for r in rows if r.get("topic")))[:n]
    if len(topics) < min_topics:
        raise ValueError(
            f"poucos tópicos pra congelar o gate de recall ({len(topics)} < {min_topics}) "
            "— junte mais aprendizado antes de medir")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(topics, indent=2, ensure_ascii=False), encoding="utf-8")
    return topics


def evaluate_recall_gate(rag, ground_truth: list[str], k: int = 5) -> dict:
    """Teste de ida-e-volta: se o Apolo estudou X, buscar X no recall tem que
    trazer X de volta (top-`k`). Cair é regressão REAL de índice/embedding —
    não uma hipótese, um fato observável. `rag` só precisa de
    `.recall(query, n_results=k) -> list[dict com 'title']` (RAGManager real
    ou fake nos testes)."""
    if not ground_truth:
        return {"status": "skipped", "reason": "sem conjunto congelado"}
    hits, misses = 0, []
    for topic in ground_truth:
        try:
            results = rag.recall(topic, n_results=k)
        except Exception:
            results = []
        titles = {(r.get("title") or "").strip().lower() for r in results}
        if topic.strip().lower() in titles:
            hits += 1
        else:
            misses.append(topic)
    n = len(ground_truth)
    return {
        "status": "ok", "n": n, "hits": hits,
        "hit_rate": round(100 * hits / n, 1) if n else None,
        "misses": misses[:10],
    }


def read_recall_gate_history(path: str | Path, limit: int = 50) -> list[dict]:
    """Lê o placar histórico do gate, mais recente por último."""
    from src.jsonl_history import read_entries
    return read_entries(path, limit)


def run_tracked_recall_gate(db, rag, *, ground_truth_path: str | Path,
                            history_path: str | Path, n: int = 30,
                            min_topics: int = 15, k: int = 5) -> dict:
    """`freeze_ground_truth` + `evaluate_recall_gate` + registro no placar
    histórico numa chamada só — o jeito certo de rodar isto a partir de agora."""
    ground_truth = freeze_ground_truth(db, ground_truth_path, n, min_topics)
    result = evaluate_recall_gate(rag, ground_truth, k)
    if result.get("status") == "ok":
        from src.jsonl_history import append_entry
        append_entry(history_path, {
            "n": result["n"], "hits": result["hits"], "hit_rate": result["hit_rate"],
        })
    return result
