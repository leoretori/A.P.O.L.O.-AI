"""API do Apolo-Nano — a LLM própria servindo o app (Épico 3.2 do plano Nano).

GET  /api/nano/status   — checkpoint/params/ppl do modelo próprio
POST /api/nano/complete — completa texto com o modelo 100% soberano

A geração roda em thread (não bloqueia o loop) e marca atividade de usuário
no GpuGate — o aprendizado de fundo espera, nunca o contrário.
"""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src import runtime as rt

router = APIRouter()


class NanoCompleteRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    max_tokens: int = Field(default=60, ge=1, le=400)
    temperature: float = Field(default=0.8, gt=0, le=2.0)
    top_k: int = Field(default=40, ge=1, le=500)
    seed: int | None = None


@router.get("/api/nano/status")
async def nano_status():
    if not rt.nano:
        return {"available": False, "ready": False}
    return await asyncio.to_thread(rt.nano.info)


@router.get("/api/nano/coverage")
async def nano_coverage():
    """Takeover progressivo (M27): % das tarefas estreitas servidas pelo cérebro
    próprio (Nano) vs. o professor — a métrica-mãe do Ano 3, por tarefa e geral."""
    if not rt.db:
        return {"overall": {"nano": 0, "teacher": 0, "total": 0, "pct": 0.0}, "tasks": {}}
    cov = await asyncio.to_thread(rt.db.nano_coverage)
    from src.nanollm.routing import NANO_TASKS, task_enabled
    cov["candidates"] = {t: task_enabled(t) for t in NANO_TASKS}
    return cov


@router.post("/api/nano/complete")
async def nano_complete(req: NanoCompleteRequest):
    if not rt.nano or not rt.nano.available():
        raise HTTPException(503, "Apolo-Nano sem checkpoint treinado (ver APOLO_NANO_ROADMAP.md)")
    if rt.gpu_gate:
        rt.gpu_gate.user_enter()
    try:
        result = await asyncio.to_thread(
            rt.nano.complete, req.prompt, req.max_tokens, req.temperature,
            req.top_k, req.seed,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        if rt.gpu_gate:
            rt.gpu_gate.user_exit()
    return {"engine": "apolo-nano", "local": True, "soberano": True, **result}
