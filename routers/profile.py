"""Endpoints do perfil do usuário — os fatos que o A.P.O.L.O. sabe sobre o Leo.

Rotas: /api/profile (GET lista, POST adiciona), /api/profile/{fact_id} (DELETE).

Extraído de app.py na M1 do JARVIS_ROADMAP. Ao mudar o perfil, invalida o cache
do system prompt (o perfil entra no prompt de todas as sessões).
"""
from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src.system_cache import invalidate as _syscache_inv

router = APIRouter()


class FactRequest(BaseModel):
    fact: str


@router.get("/api/profile")
async def get_profile():
    """Lista os fatos que o A.P.O.L.O. sabe sobre o usuário."""
    return {"facts": rt.profile.list() if rt.profile else []}


@router.post("/api/profile")
async def add_fact(req: FactRequest):
    if not rt.profile:
        return {"ok": False, "error": "Perfil indisponível."}
    item = rt.profile.add(req.fact)
    if item:
        _syscache_inv()  # perfil mudou → system prompt stale em todas as sessões
    return {"ok": bool(item), "fact": item}


@router.delete("/api/profile/{fact_id}")
async def remove_fact(fact_id: str):
    if not rt.profile:
        return {"ok": False}
    return {"ok": rt.profile.remove(fact_id)}
