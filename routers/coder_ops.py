"""Operações do Coder sem LLM — cópia isolada (sandbox) de automelhoria, testes
relacionados, abrir no VS Code e navegador de pastas do servidor.

Rotas: /api/coder/sandbox (+ /diff, /file, /apply, /discard), /api/coder/test-for,
/api/coder/vscode, /api/coder/browse.

Extraído de app.py na M1 do JARVIS_ROADMAP. O caminho da cópia isolada ativa
(`_sandbox_path`) é estado DESTE módulo (é reatribuído a cada create/discard).
Commit, exec e o loop ReAct /api/coder seguem em app.py.
"""
import asyncio
import os

from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src.coder import make_diff
from src.coder_state import invalidate_baseline

router = APIRouter()

# Raiz do projeto REAL (este arquivo mora em <projeto>/routers/coder_ops.py).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Caminho da cópia isolada ativa (ou None). Reatribuído nos create/discard.
_sandbox_path: str | None = None


class CoderPathRequest(BaseModel):
    path: str


# ── Sandbox (cópia isolada de automelhoria) ───────────────────────
@router.post("/api/coder/sandbox")
async def coder_sandbox_create():
    """Cria uma CÓPIA isolada do projeto e aponta o Coder para ela. A automelhoria
    acontece na cópia — o projeto ao vivo só muda quando o usuário aplicar."""
    global _sandbox_path
    from src import sandbox
    if _sandbox_path:
        await asyncio.to_thread(sandbox.discard_sandbox, _sandbox_path)
    _sandbox_path = await asyncio.to_thread(sandbox.create_sandbox, PROJECT_ROOT)
    res = await asyncio.to_thread(rt.coder_ws.set_root, _sandbox_path)
    res["sandbox"] = True
    res["tree"] = rt.coder_ws.tree(80)
    return res


@router.get("/api/coder/sandbox/diff")
async def coder_sandbox_diff():
    """Lista as mudanças da cópia em relação ao projeto real."""
    from src import sandbox
    if not _sandbox_path:
        return {"ok": False, "error": "nenhuma cópia ativa"}
    changes = await asyncio.to_thread(sandbox.diff_sandbox, _sandbox_path, PROJECT_ROOT)
    return {"ok": True, "changes": changes, "count": len(changes)}


@router.get("/api/coder/sandbox/file")
async def coder_sandbox_file(path: str):
    """Diff colorido de um arquivo (projeto real → cópia)."""
    from src import sandbox
    if not _sandbox_path:
        return {"ok": False, "error": "nenhuma cópia ativa"}
    old, new = await asyncio.to_thread(sandbox.file_pair, _sandbox_path, PROJECT_ROOT, path)
    return {"ok": True, "diff": make_diff(old, new, path)["text"]}


class SandboxApplyRequest(BaseModel):
    paths: list[str] | None = None


@router.post("/api/coder/sandbox/apply")
async def coder_sandbox_apply(req: SandboxApplyRequest):
    """Aplica as mudanças da cópia ao projeto real (todas, ou só `paths`)."""
    from src import sandbox
    if not _sandbox_path:
        return {"ok": False, "error": "nenhuma cópia ativa"}
    res = await asyncio.to_thread(sandbox.apply_sandbox, _sandbox_path, PROJECT_ROOT, req.paths)
    invalidate_baseline()
    return res


@router.post("/api/coder/sandbox/discard")
async def coder_sandbox_discard():
    """Descarta a cópia e volta o Coder para o workspace isolado padrão."""
    global _sandbox_path
    from src import sandbox
    if _sandbox_path:
        await asyncio.to_thread(sandbox.discard_sandbox, _sandbox_path)
        _sandbox_path = None
    await asyncio.to_thread(rt.coder_ws.set_root, os.path.join(PROJECT_ROOT, "workspace"))
    return {"ok": True}


# ── Testes relacionados / VS Code / navegador de pastas ───────────
@router.post("/api/coder/test-for")
async def coder_test_for(req: CoderPathRequest):
    """Detecta e roda testes relacionados a um arquivo do workspace.
    Retorna {ok, tests_found, total, passed, failed, skipped, results, output}."""
    path = (req.path or "").strip()
    if not path:
        return {"ok": False, "error": "path obrigatório"}
    related = await asyncio.to_thread(rt.coder_ws.find_related_tests, path)
    if not related:
        return {"ok": True, "tests_found": [], "total": 0, "passed": 0,
                "failed": 0, "skipped": 0, "results": [], "output": ""}
    result = await asyncio.to_thread(rt.coder_ws.run_tests_for, related)
    result["tests_found"] = related
    return result


@router.post("/api/coder/vscode")
async def coder_open_vscode(req: CoderPathRequest):
    """Abre o workspace do Coder (ou um arquivo `path`, opcionalmente `arquivo:linha`)
    no VS Code via CLI `code`."""
    return await asyncio.to_thread(rt.coder_ws.open_in_vscode, req.path or "")


@router.get("/api/coder/browse")
async def coder_browse(path: str = ""):
    """Navegador de pastas do servidor — lista os subdiretórios de `path` para o
    usuário escolher o workspace. Só lista nomes de diretórios (read-only)."""
    def _list() -> dict:
        # Sem path → ponto de partida amigável: a pasta do projeto.
        base = path.strip() or PROJECT_ROOT
        try:
            base = os.path.abspath(base)
        except Exception:
            base = PROJECT_ROOT
        if not os.path.isdir(base):
            return {"ok": False, "error": f"não é uma pasta: {base}", "current": base, "dirs": []}
        try:
            _skip = {"__pycache__", "node_modules", ".git", ".venv", "venv"}
            entries = []
            for name in sorted(os.listdir(base), key=str.lower):
                full = os.path.join(base, name)
                if os.path.isdir(full) and not name.startswith(".") and name not in _skip:
                    entries.append({"name": name, "path": full})
        except PermissionError:
            return {"ok": False, "error": "sem permissão para ler esta pasta",
                    "current": base, "dirs": []}
        parent = os.path.dirname(base)
        return {"ok": True, "current": base,
                "parent": parent if parent and parent != base else "",
                "dirs": entries}
    return await asyncio.to_thread(_list)
