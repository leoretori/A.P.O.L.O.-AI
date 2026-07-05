"""Endpoints de notificações — os avisos do A.P.O.L.O. (autonomia visível).

Rotas: /api/notifications (GET lista + contador, DELETE limpa),
/api/notifications/read (POST marca lidas). Extraído de app.py na M1.
"""
import asyncio

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
