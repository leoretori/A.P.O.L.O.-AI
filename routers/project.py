"""Memória de projeto — detecta a stack/dependências de um projeto e a mantém
como contexto ativo (o Coder e o chat passam a conhecer o projeto).

Rotas: /api/project/analyze, /api/project/context, /api/project/clear,
/api/project/list, /api/project/{name} (DELETE).
Extraído de app.py na M1 do JARVIS_ROADMAP.
"""
import asyncio
import os

from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src.project_memory import analyze_project as _analyze_project

router = APIRouter()


class ProjectAnalyzeRequest(BaseModel):
    path: str = ""  # vazio = usa o workspace atual do Coder


@router.post("/api/project/analyze")
async def project_analyze(req: ProjectAnalyzeRequest):
    """Detecta a stack e dependências do projeto e salva como contexto ativo.
    Se `path` estiver vazio, usa o workspace atual do Coder."""
    folder = (req.path or "").strip() or str(rt.coder_ws.root)
    if not os.path.isdir(folder):
        return {"ok": False, "error": f"Pasta não encontrada: {folder}"}
    ctx = await asyncio.to_thread(_analyze_project, folder)
    await asyncio.to_thread(rt.project_mem.set_context, ctx)
    return {"ok": True, "context": ctx}


@router.get("/api/project/context")
async def project_context():
    """Retorna o contexto do projeto ativo (ou null se nenhum estiver ativo)."""
    ctx = rt.project_mem.get_active() if rt.project_mem else None
    return {"active": ctx}


@router.post("/api/project/clear")
async def project_clear():
    """Limpa o projeto ativo (A.P.O.L.O. para de usar o contexto de projeto)."""
    if rt.project_mem:
        await asyncio.to_thread(rt.project_mem.clear_active)
    return {"ok": True}


@router.get("/api/project/list")
async def project_list():
    """Lista todos os contextos de projeto salvos."""
    contexts = rt.project_mem.list_all() if rt.project_mem else []
    return {"contexts": contexts}


@router.delete("/api/project/{name}")
async def project_delete(name: str):
    """Remove um contexto de projeto salvo."""
    ok = await asyncio.to_thread(rt.project_mem.remove, name) if rt.project_mem else False
    return {"ok": ok}
