"""API do Apolo-Nano — a LLM própria servindo o app (Épico 3.2 do plano Nano).

GET  /api/nano/status   — checkpoint/params/ppl do modelo próprio
POST /api/nano/complete — completa texto com o modelo 100% soberano

A geração roda em thread (não bloqueia o loop) e marca atividade de usuário
no GpuGate — o aprendizado de fundo espera, nunca o contrário.
"""
import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src import runtime as rt

router = APIRouter()
logger = logging.getLogger("apolo.routers.nano")

# Uma rodada do flywheel por vez (treino no CPU é pesado; não empilhar).
_flywheel_running = False


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


@router.get("/api/nano/flywheel/log")
async def nano_flywheel_log():
    """Histórico das rodadas do flywheel (promovido/rejeitado/pulado)."""
    from src.nanollm.flywheel import read_flywheel_log
    return {"running": _flywheel_running,
            "rounds": await asyncio.to_thread(read_flywheel_log)}


async def _run_flywheel_bg(steps: int, min_pairs: int):
    """Roda uma volta do flywheel em background e avisa o resultado (M25.3)."""
    global _flywheel_running
    _flywheel_running = True
    try:
        from src.nanollm.flywheel import run_nightly_flywheel
        res = await asyncio.to_thread(run_nightly_flywheel, rt.db,
                                      steps=steps, min_pairs=min_pairs)
        st = res.get("status")
        if st == "promoted":
            if rt.nano:
                rt.nano.reload()
            rt.db.add_notification(
                f"🌀 Nano evoluiu: perplexidade {res['incumbent_val']:.2f} → "
                f"{res['candidate_val']:.2f} (ganho {res.get('gain')}, "
                f"{res.get('pairs')} pares). Já servindo o novo cérebro.", kind="info")
        elif st == "rejected":
            rt.db.add_notification(
                f"🌀 Rodada do Nano: candidato não superou o titular — nada mudou "
                f"({res.get('pairs')} pares).", kind="info")
        else:
            rt.db.add_notification(f"🌀 Rodada do Nano pulada: {res.get('reason')}",
                                   kind="info")
        logger.info(f"[flywheel/manual] {res}")
    except Exception as e:
        logger.warning(f"[flywheel/manual] falhou: {e}")
        if rt.db:
            rt.db.add_notification(f"⚠️ Rodada do Nano falhou: {str(e)[:120]}", kind="info")
    finally:
        _flywheel_running = False


class FlywheelRunRequest(BaseModel):
    steps: int = Field(default=400, ge=20, le=5000)
    min_pairs: int = Field(default=12, ge=1, le=1000)


@router.post("/api/nano/flywheel/run")
async def nano_flywheel_run(req: FlywheelRunRequest | None = None):
    """Dispara AGORA uma rodada do flywheel (sem esperar as 3h). Roda em segundo
    plano — o resultado chega como notificação. Uma rodada por vez."""
    if not rt.db:
        raise HTTPException(503, "banco indisponível")
    if _flywheel_running:
        return {"status": "já rodando", "running": True}
    if not rt.nano or not rt.nano.available():
        raise HTTPException(503, "Apolo-Nano sem checkpoint treinado — nada a evoluir ainda")
    req = req or FlywheelRunRequest()
    asyncio.create_task(_run_flywheel_bg(req.steps, req.min_pairs))
    return {"status": "iniciado", "running": True,
            "aviso": "treino no CPU — pode levar alguns minutos; aviso quando terminar"}


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
