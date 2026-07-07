"""Verificação anti-alucinação (M7, Épico 7.2).

POST /api/verify {question, answer} → recupera fontes da base (RAG/MemoryFabric)
e mede se a resposta está ANCORADA nelas, sinalizando incerteza. Determinístico.
"""
import asyncio

from fastapi import APIRouter

from src import runtime as rt
from src import verify as V

router = APIRouter()


def _recall_sources(question: str, limit: int = 4) -> list[dict]:
    """Fontes da base para a pergunta — via MemoryFabric (semantic) ou RAG direto."""
    try:
        if rt.memory is not None:
            hits = rt.memory.recall(question, kind="semantic", limit=limit)
            return [{"title": h.title, "content": h.text} for h in hits]
    except Exception:
        pass
    try:
        if rt.rag is not None:
            return rt.rag.recall(question, limit)
    except Exception:
        pass
    return []


@router.post("/api/verify")
async def verify_answer(payload: dict):
    question = (payload or {}).get("question", "").strip()
    answer = (payload or {}).get("answer", "").strip()
    if not question or not answer:
        return {"checked": False, "grounded": True, "label": "nao_factual", "note": None}
    # Só busca fontes se a pergunta for factual (economiza recall em conversa trivial).
    if not V.is_factual_question(question):
        return {**V.verdict(question, answer, []), "sources_count": 0}
    sources = await asyncio.to_thread(_recall_sources, question)
    return {**V.verdict(question, answer, sources), "sources_count": len(sources)}
