"""Ações confirmáveis e reversíveis (M10, Épico 10.1).

O contrato do fluxo em DOIS passos (nunca modifica o mundo num clique só):

  POST /api/actions/preview  {kind, args}      → prévia SEM efeito
  POST /api/actions/confirm  {kind, args}      → aplica + grava undo → {undo_id}
  POST /api/actions/undo     {undo_id}         → desfaz
  GET  /api/actions/undo?limit=                → ledger (trilha reversível)
  GET  /api/actions                            → ações disponíveis + escopos

O preview e o confirm recebem os MESMOS args (o cliente reenvia no confirm) — sem
estado pendente no servidor, robusto ao --reload. A confirmação é garantida pela
UI, que só habilita o confirmar depois de mostrar a prévia.
"""
import asyncio

from fastapi import APIRouter

from src import actions
from src import runtime as rt

router = APIRouter()


@router.get("/api/actions")
async def list_actions():
    """Catálogo de ações que modificam o mundo (kind + escopo exigido)."""
    return {"actions": [{"kind": a.kind, "scope": a.scope, "description": a.description}
                        for a in actions.all_actions()]}


@router.post("/api/actions/preview")
async def preview(payload: dict):
    """Fase 1 — prévia sem efeito colateral (o que vai mudar)."""
    kind = (payload or {}).get("kind", "")
    args = (payload or {}).get("args", {})
    return await asyncio.to_thread(actions.preview_action, kind, args, rt.db)


@router.post("/api/actions/confirm")
async def confirm(payload: dict):
    """Fase 2 — aplica de fato e grava o undo. Requer os mesmos args da prévia."""
    kind = (payload or {}).get("kind", "")
    args = (payload or {}).get("args", {})
    return await asyncio.to_thread(actions.apply_action, kind, args, rt.db)


@router.post("/api/actions/undo")
async def undo(payload: dict):
    """Desfaz uma ação aplicada, pelo id do ledger."""
    undo_id = (payload or {}).get("undo_id")
    if undo_id is None:
        return {"ok": False, "error": "informe 'undo_id'"}
    return await asyncio.to_thread(actions.undo_action, int(undo_id), rt.db)


@router.get("/api/actions/undo")
async def undo_ledger(limit: int = 30, pending: bool = False):
    """Trilha de ações reversíveis (para o painel), mais recentes primeiro.

    NÃO devolve `undo_data` — pra `files.write` isso inclui `old_content`, o
    conteúdo ANTERIOR do arquivo (achado na auditoria de segurança
    2026-07-15: essa listagem vazava conteúdo de arquivo sem checar escopo
    nenhum). O painel só usa description/kind/created_at/undone; quem
    precisa mesmo do undo_data é o próprio `undo_action`, que já lê pelo id
    direto (`db.get_undo`), não por aqui."""
    items = await asyncio.to_thread(rt.db.list_undo, limit, not pending)
    items = [{k: v for k, v in it.items() if k != "undo_data"} for it in items]
    return {"count": len(items), "items": items}
