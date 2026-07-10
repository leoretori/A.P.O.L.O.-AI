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


@router.get("/api/memory/recall")
async def memory_recall(q: str, kind: str = "", limit: int = 4):
    """Porta única de recuperação de memória (MemoryFabric — Épico 2.1). Consulta
    a memória semântica (RAG), a base de conhecimento e/ou as lições do Coder num
    formato único. `kind` vazio = todas; senão 'semantic'|'knowledge'|'lesson'.
    Torna o tecido de memória inspecionável e reutilizável pelos call-sites."""
    if not rt.memory:
        return {"hits": [], "backends": {}}
    limit = max(1, min(limit, 20))
    hits = await asyncio.to_thread(rt.memory.recall, q, kind or None, limit)
    return {"query": q, "kind": kind or "all",
            "backends": rt.memory.stats(),
            "hits": [h.to_dict() for h in hits]}


@router.get("/api/memory/episodes")
async def memory_episodes(when: str = "", limit: int = 20):
    """Memória episódica/autobiográfica (M2, Épico 2.2). Com `when` (frase
    temporal: 'ontem', 'semana passada', 'últimos 7 dias') recupera os episódios
    daquela janela — responde 'o que a gente fez ...?'. Sem `when`, os recentes."""
    if not rt.episodic:
        return {"episodes": [], "when": when}
    limit = max(1, min(limit, 100))
    if when.strip():
        eps = await asyncio.to_thread(rt.episodic.recall_phrase, when, limit)
        if eps is None:                       # frase não-temporal → busca textual
            eps = await asyncio.to_thread(rt.episodic.search, when, limit)
    else:
        eps = await asyncio.to_thread(rt.episodic.recent, limit)
    return {"when": when or "recentes", "count": len(eps), "episodes": eps}


@router.post("/api/memory/episodes/record")
async def memory_record_episode(payload: dict):
    """Resume uma sessão de conversa num episódio datado. `session_id` obrigatório;
    as mensagens vêm do banco. Base do Épico 2.3 (consolidação noturna) chamará
    isto automaticamente; aqui fica exposto para registro manual/verificação."""
    session_id = (payload or {}).get("session_id", "")
    if not rt.episodic or not session_id:
        return {"ok": False, "reason": "sem memória episódica ou session_id"}
    messages = await asyncio.to_thread(rt.db.load_session, session_id) if rt.db else []
    ep = await asyncio.to_thread(rt.episodic.record, session_id, messages or [])
    return {"ok": ep is not None, "episode": ep}


@router.post("/api/memory/consolidate")
async def memory_consolidate(payload: dict | None = None):
    """Dispara a consolidação de memória ("sono", Épico 2.3): resume conversas já
    encerradas em episódios datados. O scheduler faz isso sozinho a cada ~30 min;
    aqui fica exposto para rodar sob demanda. `inactive_minutes` opcional."""
    if not rt.episodic:
        return {"consolidated": 0, "titles": []}
    kw = {}
    if payload and isinstance(payload.get("inactive_minutes"), int):
        kw["inactive_minutes"] = max(1, payload["inactive_minutes"])
    return await asyncio.to_thread(lambda: rt.episodic.consolidate(**kw))


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
        "backend": get_provider().name,
        "chat_is_fast": chat_is_fast,
        # Sugere um 3B do Ollama só se ainda estiver no Ollama e sem modelo rápido.
        # No motor próprio (llama.cpp) a troca é por GGUF no .env — sem "ollama pull".
        "suggestion": "" if (chat_is_fast or get_provider().name == "llamacpp") else "qwen2.5-coder:3b",
    }
