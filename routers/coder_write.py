"""Ferramentas de ESCRITA do Coder que mexem no workspace (fora do loop ReAct):
apagar, buscar-e-substituir, mover, desfazer, trocar de workspace e apontar para
o próprio projeto (automelhoria).

Rotas: /api/coder/delete, /replace, /move, /undo, /workspace, /self.
Cada operação invalida o cache do baseline (o workspace mudou). Extraído de
app.py na M1 do JARVIS_ROADMAP; usa coder_ws (runtime) + invalidate_baseline
(coder_state). As ferramentas com mais dependências (commit, exec, sandbox*)
seguem em app.py por enquanto.
"""
import asyncio
import os

from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src.coder_state import invalidate_baseline

router = APIRouter()


class CoderPathRequest(BaseModel):
    path: str


@router.post("/api/coder/delete")
async def coder_delete(req: CoderPathRequest):
    """Apaga um arquivo do workspace (reversível via histórico)."""
    out = await asyncio.to_thread(rt.coder_ws.delete_file, req.path)
    invalidate_baseline()
    return {"ok": out.startswith("OK"), "message": out}


class CoderReplaceRequest(BaseModel):
    find: str
    replace: str = ""


@router.post("/api/coder/replace")
async def coder_replace(req: CoderReplaceRequest):
    """Busca-e-substitui em massa no workspace (cada arquivo vira snapshot reversível)."""
    res = await asyncio.to_thread(rt.coder_ws.search_replace, req.find, req.replace)
    invalidate_baseline()
    return res


class CoderMoveRequest(BaseModel):
    src: str
    dst: str


@router.post("/api/coder/move")
async def coder_move(req: CoderMoveRequest):
    """Renomeia/move um arquivo no workspace (reversível)."""
    out = await asyncio.to_thread(rt.coder_ws.rename_file, req.src, req.dst)
    invalidate_baseline()
    return {"ok": out.startswith("OK"), "message": out}


class CoderUndoRequest(BaseModel):
    path: str = ""
    all: bool = False


@router.post("/api/coder/undo")
async def coder_undo(req: CoderUndoRequest):
    """Desfaz/descarta alterações feitas pelo Coder (snapshots da sessão)."""
    invalidate_baseline()
    if req.all:
        return await asyncio.to_thread(rt.coder_ws.undo_all)
    if req.path:
        return await asyncio.to_thread(rt.coder_ws.undo_file, req.path)
    return await asyncio.to_thread(rt.coder_ws.undo_last)


class CoderWorkspaceRequest(BaseModel):
    path: str


@router.post("/api/coder/workspace")
async def coder_set_workspace(req: CoderWorkspaceRequest):
    """Aponta o Coder para um diretório existente (projeto real)."""
    res = await asyncio.to_thread(rt.coder_ws.set_root, req.path)
    invalidate_baseline()
    if res.get("ok"):
        res["tree"] = rt.coder_ws.tree(80)
    return res


@router.post("/api/coder/self")
async def coder_self_improve():
    """Aponta o Coder para o **próprio código do A.P.O.L.O.** (a pasta deste projeto),
    para que ele possa se automelhorar. Guiado pela doutrina em A.P.O.L.O._Code.md."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    res = await asyncio.to_thread(rt.coder_ws.set_root, project_root)
    invalidate_baseline()
    if res.get("ok"):
        res["tree"] = rt.coder_ws.tree(80)
        res["self"] = True
    return res
