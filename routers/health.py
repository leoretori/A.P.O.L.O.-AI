"""Agregadores de estado — /api/boot (dados de inicialização do frontend) e
/api/health (painel de saúde consolidado). Ambos rodam os blocos independentes
em paralelo (asyncio.gather).

Extraído de app.py na M1 do JARVIS_ROADMAP. Lê todos os singletons via runtime;
os modelos vêm dos getters (CHAT_MODEL/VISION_MODEL são reatribuídos no startup).
"""
import asyncio

from fastapi import APIRouter

from src import runtime as rt
from src.llm import ollama_breaker_state

router = APIRouter()


@router.get("/api/boot")
async def boot_data():
    """Dados de inicialização do frontend — agrega o que antes eram 6+ chamadas separadas.
    Retorna em paralelo: modelos, estado Supabase, status do aprendizado, notificações
    não lidas e sessões recentes. Reduz o tempo de carregamento da UI."""
    from src.providers import get_provider

    chat_model = rt.get_chat_model()
    heavy_model = rt.model
    vision_model = rt.get_vision_model()

    async def _models():
        try:
            installed = get_provider().list_models()
            return {"chat_model": chat_model, "heavy_model": heavy_model,
                    "vision_model": vision_model, "installed": installed}
        except Exception:
            return {"chat_model": chat_model, "heavy_model": heavy_model,
                    "vision_model": vision_model, "installed": []}

    async def _kb_stats():
        if not rt.knowledge_db:
            return {"enabled": False, "total": 0}
        try:
            return {"enabled": True, **await asyncio.to_thread(rt.knowledge_db.stats)}
        except Exception:
            return {"enabled": True, "total": 0}

    async def _learn():
        return rt.learner.get_status() if rt.learner else {"running": False}

    async def _notifs():
        try:
            return await asyncio.to_thread(rt.db.unread_count)
        except Exception:
            return 0

    async def _sessions():
        try:
            return await asyncio.to_thread(rt.db.list_sessions, 0, 100)
        except Exception:
            return []

    models_r, kb_r, learn_r, notifs_r, sess_r = await asyncio.gather(
        _models(), _kb_stats(), _learn(), _notifs(), _sessions()
    )

    proj = rt.project_mem.get_active() if rt.project_mem else None

    from src.system_cache import stats as _sc_stats
    from src.whisper_stt import is_available as _stt_ok
    from src.tts import is_available as _tts_ok

    return {
        "ok": True,
        "models": models_r,
        "knowledge": kb_r,
        "learner": learn_r,
        "unread_notifications": notifs_r,
        "sessions": sess_r,
        "active_project": proj,
        "stt": _stt_ok(),
        "tts_engine": "edge-tts" if _tts_ok() else "browser",
        "system_cache": _sc_stats(),
    }


@router.get("/api/health")
async def health():
    """Painel de saúde — estado consolidado do A.P.O.L.O. num só lugar.
    Os blocos são independentes e fazem I/O de rede (Ollama, Supabase, embeddings),
    então rodam em paralelo (`asyncio.gather`) — antes era tudo sequencial."""
    from src.build_info import build_info
    out: dict = {"ok": True, "build": build_info()}
    chat_model = rt.get_chat_model()
    heavy_model = rt.model
    vision_model = rt.get_vision_model()

    async def _ollama():
        from src.providers import get_provider
        try:
            models = await asyncio.to_thread(get_provider().list_models)
        except Exception as e:
            return {"installed": [], "_error": str(e)[:120], "chat_model": chat_model,
                    "heavy_model": heavy_model, "vision_model": vision_model,
                    "has_vision": bool(vision_model)}
        from src.hardware import summary as _hw_summary
        return {"installed": models, "chat_model": chat_model, "heavy_model": heavy_model,
                "vision_model": vision_model, "has_vision": bool(vision_model),
                "backend": get_provider().name, "breaker": ollama_breaker_state(),
                "hardware": _hw_summary()}

    async def _database():
        try:
            ls = await asyncio.to_thread(rt.db.get_learning_stats)
            dups, sess, quality = await asyncio.gather(
                asyncio.to_thread(rt.db.count_topic_duplicates),
                asyncio.to_thread(rt.db.list_sessions, 0, 1000),
                asyncio.to_thread(rt.db.get_summary_quality),
            )
            return {"learned_total": ls["total"], "learned_today": ls["today"],
                    "duplicates": dups, "sessions": len(sess), "quality": quality}
        except Exception as e:
            return {"error": str(e)[:120]}

    async def _supabase():
        if not rt.knowledge_db:
            return {"enabled": False}
        try:
            stats = await asyncio.to_thread(rt.knowledge_db.stats)
            return {"enabled": True, "breaker": rt.knowledge_db.breaker_state(), **stats}
        except Exception as e:
            return {"enabled": True, "error": str(e)[:120],
                    "breaker": rt.knowledge_db.breaker_state()}

    async def _recall():
        if not rt.rag:
            return None
        try:
            recent = await asyncio.to_thread(rt.db.get_learned_since, 720, 8)  # ~30 dias
            sample = [r["topic"] for r in recent][:6]
            if not sample:
                sample = [r["topic"] for r in await asyncio.to_thread(rt.db.get_learning_history, 6)]
            return await asyncio.to_thread(rt.rag.recall_quality, sample)
        except Exception as e:
            return {"error": str(e)[:120]}

    ollama_r, db_r, supa_r, recall_r = await asyncio.gather(
        _ollama(), _database(), _supabase(), _recall())
    if "_error" in ollama_r:
        out["ollama_error"] = ollama_r.pop("_error")
    out["ollama"] = ollama_r
    out["database"] = db_r
    out["supabase"] = supa_r
    if recall_r is not None:
        out["recall"] = recall_r

    # Aprendizado contínuo (local, rápido)
    if rt.learner:
        st = rt.learner.get_status()
        out["learner"] = {
            "running": st.get("running"),
            "queue_depth": st.get("queue_depth"),
            "total_session": st.get("total_session"),
            "throughput_hour": st.get("throughput_hour"),
            "gap_count": st.get("gap_count"),
            "active_agents": [a for a in st.get("agents", []) if a.get("active")],
        }
    else:
        out["learner"] = {"running": False}

    # STT local (Whisper), TTS (edge-tts) e ingestão de documentos
    from src.whisper_stt import is_available as _stt_available
    from src.tts import is_available as _tts_available, VOICES as _tts_voices
    out["stt"] = _stt_available()
    out["tts_engine"] = "edge-tts" if _tts_available() else "browser"
    out["tts_voices"] = list(_tts_voices.keys()) if _tts_available() else []
    out["features"] = {
        "docx": True,
        "pdf": True,
        "whisper": out["stt"],
        "edge_tts": _tts_available(),
        "hands_free": True,
        "drag_drop": True,
    }

    # Backend de conhecimento (Supabase ou LocalKnowledge)
    kb_backend = "none"
    if rt.knowledge_db is not None:
        from src.local_knowledge import LocalKnowledge
        kb_backend = "local_sqlite" if isinstance(rt.knowledge_db, LocalKnowledge) else "supabase"
    out["knowledge_backend"] = kb_backend

    return out
