"""Backup e exportação — vault Obsidian, backup completo (JSON) e importação.

Rotas: /api/export/obsidian, /api/export, /api/import.
Extraído de app.py na M1 do JARVIS_ROADMAP. Lê db/knowledge_db via `src.runtime`;
o /api/import limpa o cache em memória de sessões (rt.sessions, compartilhado).
"""
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src import backup_service
from src import crypto
from src import runtime as rt

router = APIRouter()
logger = logging.getLogger("apolo.routers.backup")


def _gather_backup_data() -> dict:
    """Monta o snapshot completo: export do banco + conhecimento (Supabase/local)."""
    data = rt.db.export_all()
    if rt.knowledge_db:
        try:
            data["knowledge"] = rt.knowledge_db.all_rows(5000)
            data["counts"]["knowledge"] = len(data["knowledge"])
        except Exception as e:
            logger.warning(f"export knowledge: {e}")
            data["knowledge"] = []
    return data


def _apply_import(data: dict) -> dict:
    """Restaura um snapshot no banco (import_all + conhecimento). Idempotente."""
    added = rt.db.import_all(data)
    knowledge_restored = 0
    if rt.knowledge_db and isinstance(data.get("knowledge"), list):
        for r in data["knowledge"]:
            if not r.get("url"):
                continue
            try:
                rt.knowledge_db.save(
                    r.get("title") or "(sem título)", r["url"],
                    r.get("content") or "", r.get("category") or "web", r.get("tags") or [],
                )
                knowledge_restored += 1
            except Exception as e:
                logger.debug(f"import knowledge row: {e}")
    if rt.sessions is not None:
        rt.sessions.clear()
    return {"added": added, "knowledge_restored": knowledge_restored}


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
    data = await asyncio.to_thread(_gather_backup_data)
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
    res = await asyncio.to_thread(_apply_import, data)
    return {"ok": True, **res}


# ── Backup CRIPTOGRAFADO em repouso (M11 11.2) ──────────────────

@router.get("/api/backup/status")
async def backup_status():
    """Estado do backup cifrado: cripto disponível, auto-backup ligado, quantos há."""
    backups = await asyncio.to_thread(backup_service.list_backups)
    return {
        "crypto_available": crypto.is_available(),
        "auto_enabled": bool(os.getenv("BACKUP_PASSPHRASE", "").strip()),
        "dir": str(backup_service.BACKUP_DIR),
        "count": len(backups),
        "backups": backups[:20],
    }


@router.post("/api/backup/encrypted")
async def create_encrypted(payload: dict):
    """Cria um backup LOCAL CIFRADO (.apolobak) com a senha informada. A senha
    nunca é gravada — sem ela, o arquivo é inútil."""
    if not crypto.is_available():
        return {"ok": False, "error": "biblioteca de cifra indisponível (instale 'cryptography')"}
    passphrase = (payload or {}).get("passphrase", "")
    if not passphrase:
        return {"ok": False, "error": "informe uma senha"}
    try:
        data = await asyncio.to_thread(_gather_backup_data)
        info = await asyncio.to_thread(backup_service.write_encrypted, data, passphrase)
        await asyncio.to_thread(backup_service.prune_backups)
        return {"ok": True, **info, "counts": data.get("counts", {})}
    except Exception as e:
        logger.warning(f"backup cifrado: {e}")
        return {"ok": False, "error": str(e)[:200]}


@router.post("/api/backup/restore")
async def restore_encrypted(payload: dict):
    """Restaura um backup cifrado LOCAL pelo nome (dentro da pasta de backups).
    Senha errada ou arquivo adulterado FALHA sem tocar no banco."""
    passphrase = (payload or {}).get("passphrase", "")
    name = (payload or {}).get("name", "")
    if not passphrase or not name:
        return {"ok": False, "error": "informe 'name' e 'passphrase'"}
    # Confinamento: só arquivos dentro da pasta de backups (sem path traversal).
    target = (backup_service.BACKUP_DIR / Path(name).name)
    if not target.is_file():
        return {"ok": False, "error": "backup não encontrado"}
    try:
        data = await asyncio.to_thread(backup_service.read_encrypted, target, passphrase)
    except Exception as e:
        # InvalidToken (senha errada/adulterado) ou formato inválido
        return {"ok": False, "error": f"não foi possível decifrar: {type(e).__name__}"}
    res = await asyncio.to_thread(_apply_import, data)
    return {"ok": True, "restored_from": target.name, **res}
