"""Endpoints de notificações e lembretes — os avisos e follow-ups do A.P.O.L.O.

Rotas: /api/notifications (GET lista + contador, DELETE limpa),
/api/notifications/read (POST marca lidas). Extraído de app.py na M1.
Lembretes (M4 4.2): /api/reminders (GET lista, POST cria),
/api/reminders/{id}/done (POST conclui).
"""
import asyncio
from datetime import datetime

from fastapi import APIRouter

from src import runtime as rt

router = APIRouter()


@router.get("/api/notifications")
async def list_notifications():
    """Avisos do A.P.O.L.O. (autonomia visível) + contador de não-lidas."""
    items = await asyncio.to_thread(rt.db.list_notifications, 30, False)
    unread = await asyncio.to_thread(rt.db.unread_count)
    return {"items": items, "unread": unread}


@router.post("/api/notifications/read")
async def read_notifications():
    n = await asyncio.to_thread(rt.db.mark_notifications_read)
    return {"ok": True, "marked": n}


@router.delete("/api/notifications")
async def clear_notifications():
    n = await asyncio.to_thread(rt.db.clear_notifications)
    return {"ok": True, "cleared": n}


# ── Lembretes / follow-ups (M4, Épico 4.2) ────────────────────
@router.get("/api/reminders")
async def list_reminders(pending: bool = True, limit: int = 50):
    """Lembretes anotados (detectados em conversas ou manuais)."""
    limit = max(1, min(limit, 200))
    items = await asyncio.to_thread(rt.db.list_reminders, pending, limit)
    return {"reminders": items}


@router.post("/api/reminders")
async def create_reminder(payload: dict):
    """Cria um lembrete à mão. `text` obrigatório; `due_at` (ISO) opcional."""
    text = (payload or {}).get("text", "").strip()
    if not text:
        return {"ok": False, "reason": "texto vazio"}
    due = None
    raw = (payload or {}).get("due_at")
    if raw:
        try:
            due = datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            due = None
    rid = await asyncio.to_thread(rt.db.save_reminder, text, due, "")
    return {"ok": rid is not None, "id": rid}


@router.post("/api/reminders/{reminder_id}/done")
async def complete_reminder(reminder_id: int):
    ok = await asyncio.to_thread(rt.db.mark_reminder_done, reminder_id)
    return {"ok": ok}
