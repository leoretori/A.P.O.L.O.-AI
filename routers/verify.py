"""Raciocínio confiável (M7): roteamento (7.1) + verificação (7.2) + consistência (7.3).

POST /api/route       {text}            → classifica em tool/heavy/light
POST /api/verify      {question,answer} → mede lastro da resposta factual na base
POST /api/consistency {question, n?}    → amostra N respostas e reconcilia
Determinísticos na reconciliação; a amostragem usa o modelo leve com temperatura.
"""
import asyncio

from fastapi import APIRouter

from src import runtime as rt
from src import verify as V
from src.consistency import self_consistent_answer
from src.routing import route_task

router = APIRouter()


@router.post("/api/consistency")
async def consistency(payload: dict):
    """M7 7.3 — self-consistency: amostra N respostas curtas do modelo leve (com
    temperatura, p/ variar) e reconcilia. Divergência = sinal de alucinação.
    CUSTO: N inferências — use sob demanda em perguntas críticas."""
    question = (payload or {}).get("question", "").strip()
    if not question:
        return {"ok": False, "error": "pergunta vazia"}
    n = (payload or {}).get("n", 3)

    def _sample(q: str) -> str:
        from src.llm import KEEP_ALIVE, chat_resilient
        model = rt.get_chat_model() if callable(getattr(rt, "get_chat_model", None)) else rt.model
        return chat_resilient(
            model,
            [{"role": "user", "content": f"Responda de forma curta e direta: {q}"}],
            keep_alive=KEEP_ALIVE, options={"temperature": 0.9},
        ) or ""

    result = await asyncio.to_thread(self_consistent_answer, question, _sample, n)
    return {"ok": True, **result}


@router.post("/api/route")
async def route_message(payload: dict):
    """M7 7.1 — decide a rota de execução (ferramenta vs modelo leve vs pesado),
    poupando CPU e evitando mandar 'que horas são' para o 14b."""
    return route_task((payload or {}).get("text", ""))


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
