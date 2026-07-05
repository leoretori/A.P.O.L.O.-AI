"""Endpoints de sessões de conversa.

Rotas: /api/session/{id} (GET carrega, DELETE apaga), /api/sessions (lista),
/api/session/{id}/export (Markdown), /api/sessions/search, /api/sessions/reindex.

Extraído de app.py na M1 do JARVIS_ROADMAP. Lê os singletons via `src.runtime`.
Os dicts `sessions`/`session_summaries` são a MESMA referência que o chat muta
in-place — leituras aqui refletem o estado atual das conversas.
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src import runtime as rt
from src.episodic import index_session as _index_episodic

router = APIRouter()


@router.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    if rt.sessions is not None:
        rt.sessions.pop(session_id, None)
    rt.db.delete_session(session_id)
    return {"ok": True}


@router.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Carrega conversa completa de uma sessão para restaurar no front."""
    msgs = rt.db.load_session(session_id)
    return {"session_id": session_id, "messages": msgs}


@router.get("/api/sessions")
async def list_sessions():
    """Lista todas as sessões (chats antigos inclusos) para a sidebar."""
    return rt.db.list_sessions(days=0, limit=100)


@router.get("/api/session/{session_id}/export")
async def export_session_md(session_id: str):
    """Baixa a conversa como arquivo Markdown."""
    md = await asyncio.to_thread(rt.db.export_session_markdown, session_id)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([md]), media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="apolo_conversa_{stamp}.md"'},
    )


@router.get("/api/sessions/search")
async def search_sessions(q: str = ""):
    """Busca no histórico de conversas (todos os chats) por trecho de texto."""
    results = await asyncio.to_thread(rt.db.search_messages, q, 30)
    return {"query": q, "results": results}


@router.post("/api/sessions/reindex")
async def reindex_sessions():
    """Indexa (ou re-indexa) todas as conversas históricas na memória episódica
    (ChromaDB). Use para aproveitar chats antigos no recall semântico do chat."""
    if not rt.rag:
        return {"ok": False, "error": "RAG não inicializado"}
    sessions_list = await asyncio.to_thread(rt.db.list_sessions, 0, 500)
    indexed, skipped = 0, 0
    summaries = rt.session_summaries or {}
    for sess in sessions_list:
        sid = sess["session_id"]
        title = sess.get("title") or sess.get("first_message", "")[:60]
        messages = await asyncio.to_thread(rt.db.load_session, sid)
        summ = summaries.get(sid, {}).get("text", "")
        ok = await asyncio.to_thread(_index_episodic, sid, title, messages, rt.rag, summ)
        if ok:
            indexed += 1
        else:
            skipped += 1
    return {"ok": True, "indexed": indexed, "skipped": skipped,
            "total": len(sessions_list)}
