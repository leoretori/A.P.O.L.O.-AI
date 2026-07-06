"""Sistema — telemetria de performance, histórico e modelos disponíveis.

Rotas: /api/perf, /api/perf/reset, /api/history, /api/models.
Extraído de app.py na M1 do JARVIS_ROADMAP. Os agregadores grandes (/api/boot,
/api/health) seguem em app.py por enquanto (muito estado).
"""
import asyncio
import logging

from fastapi import APIRouter

from src import runtime as rt
from src.telemetry import tracker as perf_tracker

router = APIRouter()
logger = logging.getLogger("apolo.routers.system")

# Modelos leves (3B) que dão respostas rápidas na CPU — o chat ideal do dia a dia.
FAST_MODELS = {"qwen2.5-coder:3b", "qwen2.5:3b", "llama3.2:3b", "phi3:mini", "gemma2:2b"}


@router.get("/api/perf")
async def perf_metrics():
    """Telemetria de latência por endpoint (média, p95, máximo, contagem, erros).
    Para flagrar regressões de performance — ex.: se a Mente voltar a ficar lenta."""
    return perf_tracker.snapshot()


@router.post("/api/perf/reset")
async def perf_reset():
    perf_tracker.reset()
    return {"ok": True}


@router.get("/api/history")
async def history():
    return rt.db.get_history(limit=50)


@router.get("/api/audit")
async def audit(hours: int = 24, limit: int = 100):
    """Auditoria de autonomia — 'o que a IA fez nas últimas N horas'. Junta
    aprendizado, tarefas do Coder, execuções, notificações e autoavaliações num
    fluxo único. Torna a autonomia do A.P.O.L.O. visível e inspecionável (Épico
    1.3 / observabilidade). I/O de banco → roda fora do event loop."""
    hours = max(1, min(hours, 720))          # teto de 30 dias
    limit = max(1, min(limit, 500))
    summary, events = await asyncio.gather(
        asyncio.to_thread(rt.db.activity_summary, hours),
        asyncio.to_thread(rt.db.get_activity_since, hours, limit),
    )
    return {"summary": summary, "events": events}


@router.get("/api/models")
async def models_info():
    """Modelos disponíveis no provedor ativo (Ollama ou motor próprio) + qual o
    A.P.O.L.O. usa no chat. Orienta a baixar um modelo leve (3B) p/ respostas rápidas."""
    from src.providers import get_provider
    try:
        installed = await asyncio.to_thread(get_provider().list_models)
    except Exception as e:
        logger.warning(f"models list: {e}")
        installed = []
    chat_model = rt.get_chat_model()
    vision_model = rt.get_vision_model()
    chat_is_fast = chat_model in FAST_MODELS
    return {
        "chat_model": chat_model,
        "heavy_model": rt.model,
        "vision_model": vision_model,
        "has_vision": bool(vision_model),
        "installed": installed,
        "chat_is_fast": chat_is_fast,
        # Sugere um 3B só se o chat ainda não usa um modelo rápido.
        "suggestion": "" if chat_is_fast else "qwen2.5-coder:3b",
    }
