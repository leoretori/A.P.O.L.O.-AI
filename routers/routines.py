"""Rotinas automatizadas (M10, Épico 10.2).

  GET    /api/routines            → lista as rotinas + agendamento humano
  GET    /api/routines/kinds      → tipos disponíveis (ex.: weekly_digest)
  POST   /api/routines            → cria {name, kind, freq, weekday?, time_of_day, config}
  POST   /api/routines/{id}/toggle→ liga/desliga
  POST   /api/routines/{id}/run   → roda AGORA (aplica a ação; entra no ledger/undo)
  DELETE /api/routines/{id}       → remove

Rodar uma rotina passa pelo motor de ações do 10.1 → auditado e reversível.
"""
import asyncio

from fastapi import APIRouter

from src import routines as R
from src import runtime as rt

router = APIRouter()


def _with_schedule(r: dict) -> dict:
    return {**r, "schedule_human": R.describe_schedule(r)}


@router.get("/api/routines")
async def list_routines():
    items = await asyncio.to_thread(rt.db.list_routines)
    return {"count": len(items), "routines": [_with_schedule(r) for r in items]}


@router.get("/api/routines/kinds")
async def routine_kinds():
    return {"kinds": [{"kind": k, "description": d} for k, d in R.KINDS.items()]}


@router.post("/api/routines")
async def create_routine(payload: dict):
    p = payload or {}
    kind = (p.get("kind") or "").strip()
    if kind not in R.KINDS:
        return {"ok": False, "error": f"tipo de rotina inválido: {kind}"}
    freq = p.get("freq", "weekly")
    if freq not in R.FREQS:
        return {"ok": False, "error": f"frequência inválida: {freq}"}
    r = await asyncio.to_thread(
        rt.db.save_routine, p.get("name") or R.KINDS[kind], kind, freq,
        int(p.get("weekday", 4)), int(p.get("day_of_month", 1)),
        p.get("time_of_day", "18:00"), p.get("config") or {},
    )
    return {"ok": True, "routine": _with_schedule(r)}


@router.post("/api/routines/{routine_id}/toggle")
async def toggle_routine(routine_id: int, payload: dict | None = None):
    r = await asyncio.to_thread(rt.db.get_routine, routine_id)
    if not r:
        return {"ok": False, "error": "rotina não encontrada"}
    enabled = (payload or {}).get("enabled")
    enabled = (not r["enabled"]) if enabled is None else bool(enabled)
    await asyncio.to_thread(rt.db.set_routine_enabled, routine_id, enabled)
    return {"ok": True, "enabled": enabled}


@router.post("/api/routines/{routine_id}/run")
async def run_routine_now(routine_id: int):
    """Dispara a rotina AGORA (não espera o horário). Aplica a ação → ledger/undo."""
    r = await asyncio.to_thread(rt.db.get_routine, routine_id)
    if not r:
        return {"ok": False, "error": "rotina não encontrada"}
    res = await asyncio.to_thread(R.run_routine, r, rt.db)
    if res.get("ok"):
        await asyncio.to_thread(rt.db.mark_routine_run, routine_id)
    return res


@router.delete("/api/routines/{routine_id}")
async def delete_routine(routine_id: int):
    ok = await asyncio.to_thread(rt.db.delete_routine, routine_id)
    return {"ok": ok}
