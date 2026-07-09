"""Endpoints do perfil do usuário — os fatos que o A.P.O.L.O. sabe sobre o Leo.

Rotas: /api/profile (GET lista, POST adiciona), /api/profile/{fact_id} (DELETE).

Extraído de app.py na M1 do JARVIS_ROADMAP. Ao mudar o perfil, invalida o cache
do system prompt (o perfil entra no prompt de todas as sessões).
"""
from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src.profile import CATEGORIES
from src.system_cache import invalidate as _syscache_inv

router = APIRouter()


class FactRequest(BaseModel):
    fact: str
    category: str | None = None
    horizon: str | None = None  # 'short' | 'long' (só faz sentido em metas)


class FactUpdate(BaseModel):
    fact: str | None = None
    category: str | None = None
    horizon: str | None = None


class ConfirmRequest(BaseModel):
    # edições opcionais na hora de confirmar o candidato
    fact: str | None = None
    category: str | None = None
    horizon: str | None = None


@router.get("/api/profile")
async def get_profile():
    """Lista os fatos que o A.P.O.L.O. sabe sobre o usuário (+ agrupados por seção)."""
    if not rt.profile:
        return {"facts": [], "by_category": {}, "categories": {}}
    labels = {slug: label for slug, (label, _) in CATEGORIES.items()}
    return {
        "facts": rt.profile.list(),
        "by_category": rt.profile.by_category(),
        "categories": labels,
    }


@router.post("/api/profile")
async def add_fact(req: FactRequest):
    if not rt.profile:
        return {"ok": False, "error": "Perfil indisponível."}
    item = rt.profile.add(req.fact, category=req.category, horizon=req.horizon)
    if item:
        _syscache_inv()  # perfil mudou → system prompt stale em todas as sessões
    return {"ok": bool(item), "fact": item}


@router.patch("/api/profile/{fact_id}")
async def edit_fact(fact_id: str, req: FactUpdate):
    """Edita uma entrada — a curadoria do modelo pelo próprio usuário (M16.1)."""
    if not rt.profile:
        return {"ok": False}
    item = rt.profile.update(fact_id, fact=req.fact, category=req.category,
                             horizon=req.horizon)
    if item:
        _syscache_inv()
    return {"ok": bool(item), "fact": item}


@router.delete("/api/profile/{fact_id}")
async def remove_fact(fact_id: str):
    if not rt.profile:
        return {"ok": False}
    ok = rt.profile.remove(fact_id)
    if ok:
        _syscache_inv()  # remoção também deixa o system prompt stale
    return {"ok": ok}


# ------------------------------------------------ candidatos (M16.2)
@router.get("/api/profile/candidates")
async def list_candidates():
    """Candidatos ao modelo, propostos pela extração e aguardando confirmação."""
    if not rt.profile or not hasattr(rt.profile, "pending"):
        return {"candidates": []}
    return {"candidates": rt.profile.pending()}


@router.post("/api/profile/candidates/{cand_id}/confirm")
async def confirm_candidate(cand_id: str, req: ConfirmRequest):
    """Confirma um candidato (com edições opcionais) → entra no perfil."""
    if not rt.profile or not hasattr(rt.profile, "confirm"):
        return {"ok": False}
    item = rt.profile.confirm(cand_id, text=req.fact, category=req.category,
                              horizon=req.horizon)
    if item:
        _syscache_inv()  # perfil mudou → system prompt stale
    return {"ok": bool(item), "fact": item}


@router.post("/api/profile/candidates/{cand_id}/reject")
async def reject_candidate(cand_id: str):
    """Descarta um candidato — nada entra no perfil."""
    if not rt.profile or not hasattr(rt.profile, "reject"):
        return {"ok": False}
    return {"ok": rt.profile.reject(cand_id)}
