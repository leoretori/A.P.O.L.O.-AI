"""Backup e exportação — vault Obsidian, backup completo (JSON) e importação.

Rotas: /api/export/obsidian, /api/export, /api/import.
Extraído de app.py na M1 do JARVIS_ROADMAP. Lê db/knowledge_db via `src.runtime`;
o /api/import limpa o cache em memória de sessões (rt.sessions, compartilhado).
"""
import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src import runtime as rt

router = APIRouter()
logger = logging.getLogger("apolo.routers.backup")


@router.get("/api/export/obsidian")
async def export_obsidian():
    """Exporta todo o conhecimento acumulado como vault Obsidian (ZIP de .md).

    Gera um arquivo por setor com todos os tópicos aprendidos, links internos
    entre tópicos relacionados e um índice geral. Abra o ZIP descompactado
    como vault no Obsidian para navegar pelo conhecimento do A.P.O.L.O."""
    from src.obsidian import generate_vault
    zip_bytes = await asyncio.to_thread(generate_vault, rt.db, rt.knowledge_db)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    return StreamingResponse(
        iter([zip_bytes]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="APOLO_Obsidian_{stamp}.zip"'},
    )


@router.get("/api/export")
async def export_all():
    """Backup completo: conhecimento (Supabase) + sessões e tópicos (SQLite) em JSON."""
    data = await asyncio.to_thread(rt.db.export_all)
    if rt.knowledge_db:
        try:
            data["knowledge"] = await asyncio.to_thread(rt.knowledge_db.all_rows, 5000)
            data["counts"]["knowledge"] = len(data["knowledge"])
        except Exception as e:
            logger.warning(f"export knowledge: {e}")
            data["knowledge"] = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f'attachment; filename="apolo_backup_{stamp}.json"'},
    )


@router.post("/api/import")
async def import_backup(request: Request):
    """Restaura um backup do /api/export (idempotente). Recria sessões, mensagens,
    tópicos aprendidos e — se o Supabase estiver ativo — o conhecimento."""
    try:
        data = await request.json()
    except Exception:
        return {"ok": False, "error": "JSON inválido"}
    if not isinstance(data, dict):
        return {"ok": False, "error": "formato inesperado"}

    added = await asyncio.to_thread(rt.db.import_all, data)

    knowledge_restored = 0
    if rt.knowledge_db and isinstance(data.get("knowledge"), list):
        def _restore_knowledge(rows):
            n = 0
            for r in rows:
                if not r.get("url"):
                    continue
                rt.knowledge_db.save(
                    r.get("title") or "(sem título)", r["url"],
                    r.get("content") or "", r.get("category") or "web", r.get("tags") or [],
                )
                n += 1
            return n
        try:
            knowledge_restored = await asyncio.to_thread(_restore_knowledge, data["knowledge"])
        except Exception as e:
            logger.warning(f"import knowledge: {e}")

    # Limpa o cache em memória para refletir o que foi importado.
    if rt.sessions is not None:
        rt.sessions.clear()
    return {"ok": True, "added": added, "knowledge_restored": knowledge_restored}
