"""Endpoints de estudos agendados (o A.P.O.L.O. estuda um tópico todo dia no
horário marcado).

Rotas: /api/schedules (GET lista, POST agenda), /api/schedules/{id} (DELETE),
/api/schedules/{id}/toggle. Extraído de app.py na M1 do JARVIS_ROADMAP.
"""
import asyncio
import re

from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt

router = APIRouter()


class ScheduleRequest(BaseModel):
    topic: str
    time_of_day: str = "08:00"


@router.get("/api/schedules")
async def list_schedules():
    """Lista os estudos agendados."""
    return rt.db.list_schedules()


@router.post("/api/schedules")
async def add_schedule(req: ScheduleRequest):
    """Agenda um estudo diário: o A.P.O.L.O. estuda `topic` todo dia às `time_of_day`."""
    topic = (req.topic or "").strip()
    t = (req.time_of_day or "").strip()
    # Validação simples de HH:MM
    if len(topic) < 3:
        return {"ok": False, "error": "tópico muito curto"}
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", t):
        return {"ok": False, "error": "horário inválido (use HH:MM)"}
    row = await asyncio.to_thread(rt.db.add_schedule, topic, t)
    return {"ok": True, "schedule": row}


@router.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    ok = await asyncio.to_thread(rt.db.delete_schedule, schedule_id)
    return {"ok": ok}


@router.post("/api/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int):
    ok = await asyncio.to_thread(rt.db.toggle_schedule, schedule_id)
    return {"ok": ok}
