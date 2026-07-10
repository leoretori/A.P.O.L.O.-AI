"""Endpoints de IA especializados — Pesquisa Profunda e Code Review.

Rotas: /api/research (pesquisa multi-etapas citada), /api/review (revisão de
código). Extraído de app.py na M1 do JARVIS_ROADMAP. Streaming SSE com prioridade
de GPU (gpu_priority). Os núcleos /api/chat, /api/agent, /api/coder e
/api/orchestrate seguem em app.py.
"""
import asyncio
import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src import runtime as rt
from src import chat_common as cc
from src.coder_state import gpu_priority
from src.llm import KEEP_ALIVE, KEEP_ALIVE_HEAVY
from src.utils import sanitize_request

router = APIRouter()
logger = logging.getLogger("apolo.routers.ai")


@router.post("/api/research")
async def research(req: cc.ChatRequest):
    """Modo Pesquisa Profunda — raciocínio multi-etapas com memória + web, citado."""
    cc.mark_request()
    question = sanitize_request(req.message)
    if rt.learner:
        rt.learner.add_user_topic(question)

    async def stream():
        answer = ""
        try:
            async for ev in rt.researcher.research(question):
                if ev["type"] == "done":
                    answer = ev.get("answer", "")
                # as fontes já vão ao cliente no próprio evento streamado
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            logger.error(f"Erro na pesquisa: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
            return

        # Persiste a conversa (mesmo formato do chat) e salva na base de conhecimento
        if answer:
            sess = rt.sessions[req.session_id]
            is_first = len(sess) == 0
            sess.append({"role": "user", "content": question})
            sess.append({"role": "assistant", "content": answer})
            rt.db.save_message(req.session_id, "user", question)
            rt.db.save_message(req.session_id, "assistant", answer)
            if is_first:
                asyncio.create_task(cc.generate_session_title(req.session_id, question))
            if rt.knowledge_db:
                asyncio.create_task(asyncio.to_thread(
                    rt.knowledge_db.save,
                    f"Pesquisa profunda: {question[:120]}",
                    f"research://apolo/{abs(hash(question)) & 0xFFFFFFFF:08x}",
                    answer, "synthesis",
                ))

    return StreamingResponse(
        gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ReviewRequest(BaseModel):
    code: str
    language: str = "auto"


@router.post("/api/review")
async def review_code(req: ReviewRequest):
    """Code Review — revisa o código com apoio do conhecimento acumulado."""
    async def stream():
        try:
            async for ev in rt.reviewer.review(req.code, req.language):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            logger.error(f"Erro no review: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/orchestrate")
async def orchestrate_endpoint(req: cc.ChatRequest):
    """Orquestrador de sub-agentes — decompõe tarefas complexas, delega a
    especialistas (Researcher / Analyst / Coder) e sintetiza a resposta final.
    Streaming SSE com eventos: step, agent_start, agent_token, done."""
    cc.mark_request()
    task = sanitize_request(req.message)
    if rt.learner:
        rt.learner.add_user_topic(task)

    from src.orchestrator import orchestrate

    async def stream():
        try:
            async for ev in orchestrate(
                task=task,
                chat_model=rt.get_chat_model(),
                heavy_model=rt.model,
                keep_light=KEEP_ALIVE,
                keep_heavy=KEEP_ALIVE_HEAVY,
                rag=rt.rag,
                knowledge_db=rt.knowledge_db,
            ):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:
            logger.error(f"orchestrate: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        gpu_priority(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
