"""Ferramentas de LEITURA do Coder — painel do workspace, memória de lições,
diário de tarefas, visualizador de arquivos e status/diff do git.

Rotas: /api/coder/files, /api/coder/lessons, /api/coder/lessons/{id} (DELETE),
/api/coder/tasks, /api/coder/read, /api/coder/git, /api/coder/git/diff.

Extraído de app.py na M1 do JARVIS_ROADMAP. Só depende de coder_ws/lesson_mem/db
(via runtime). As ferramentas de ESCRITA (delete/replace/move/undo/exec/commit/
sandbox) e o loop ReAct /api/coder ficam em app.py até o helper de baseline
(_invalidate_baseline) e o _gpu_priority serem compartilhados num módulo comum.
"""
import asyncio

from fastapi import APIRouter

from src import runtime as rt

router = APIRouter()


@router.get("/api/coder/files")
async def coder_files():
    """Árvore, lista plana e raiz do workspace do Coder (para o painel)."""
    ws = rt.coder_ws
    return {"root": str(ws.root), "tree": ws.tree(80),
            "files": ws.list_files(200), "changes": ws.list_changes()}


@router.get("/api/coder/lessons")
async def coder_lessons():
    """Memória de lições do Coder — o que ele aprendeu com as próprias tarefas."""
    if not rt.lesson_mem:
        return {"count": 0, "lessons": []}
    return {"count": rt.lesson_mem.count(), "lessons": rt.lesson_mem.recent(30)}


@router.delete("/api/coder/lessons/{lesson_id}")
async def coder_lesson_delete(lesson_id: int):
    """Curadoria: remove uma lição errada/obsoleta da memória do Coder."""
    ok = rt.lesson_mem.delete(lesson_id) if rt.lesson_mem else False
    return {"ok": ok}


@router.get("/api/coder/tasks")
async def coder_tasks(limit: int = 20):
    """Diário de bordo do Coder — tarefas executadas + taxa de sucesso."""
    if not rt.db:
        return {"stats": {"total": 0}, "tasks": []}
    stats, tasks = await asyncio.gather(
        asyncio.to_thread(rt.db.get_coder_stats),
        asyncio.to_thread(rt.db.get_coder_tasks, limit),
    )
    return {"stats": stats, "tasks": tasks}


@router.get("/api/coder/read")
async def coder_read(path: str):
    """Conteúdo de um arquivo do workspace (para o visualizador do painel)."""
    content = await asyncio.to_thread(rt.coder_ws.read_file, path, 20000)
    return {"path": path, "content": content}


@router.get("/api/coder/git")
async def coder_git():
    """Status do git no workspace (se for um repositório)."""
    return await asyncio.to_thread(rt.coder_ws.git_status)


@router.get("/api/coder/git/diff")
async def coder_git_diff(path: str = ""):
    """Diff do git (todo o workspace ou um arquivo)."""
    diff = await asyncio.to_thread(rt.coder_ws.git_diff, path)
    return {"path": path, "diff": diff}
