"""Sandbox de automelhoria — uma CÓPIA isolada do projeto.

O Coder trabalha na cópia (em uma pasta temporária), não nos arquivos ao vivo.
Depois o usuário revisa o diff e decide **aplicar** ou **descartar**. Assim o
servidor em execução nunca é afetado por estados intermediários, e nada muda no
projeto real sem revisão explícita.

Exclui da cópia: dados de runtime (data/, logs/), caches, ambientes virtuais, .git
e — crucialmente — o `.env` (segredos nunca vão para a cópia).
"""

import os
import shutil
import tempfile

_EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", ".venv",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".claude",
    "logs", "data", "dist", "build",
}
_EXCLUDE_FILES = {".env"}
_EXCLUDE_SUFFIXES = (".db", ".pyc", ".pyo", ".log")
_SANDBOX_PREFIX = "apolo_sandbox_"


def _ignore(_dir, names):
    out = set()
    for n in names:
        if n in _EXCLUDE_DIRS or n in _EXCLUDE_FILES:
            out.add(n)
        elif n.endswith(_EXCLUDE_SUFFIXES):
            out.add(n)
    return out


def create_sandbox(project_root: str) -> str:
    """Copia o projeto (sem runtime/segredos) para uma pasta temporária. Devolve o caminho."""
    project_root = os.path.abspath(project_root)
    dst = tempfile.mkdtemp(prefix=_SANDBOX_PREFIX)
    # copytree exige que o destino não exista; mkdtemp já criou — então copiamos dentro.
    target = os.path.join(dst, "project")
    shutil.copytree(project_root, target, ignore=_ignore)
    return target


def _iter_files(root: str):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        for f in files:
            if f in _EXCLUDE_FILES or f.endswith(_EXCLUDE_SUFFIXES):
                continue
            full = os.path.join(base, f)
            yield os.path.relpath(full, root).replace("\\", "/")


def _read(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def diff_sandbox(sandbox: str, project_root: str) -> list[dict]:
    """Compara a sandbox com o projeto real. Retorna mudanças: added/modified/deleted."""
    project_root = os.path.abspath(project_root)
    sb_files = set(_iter_files(sandbox))
    pr_files = set(_iter_files(project_root))
    changes: list[dict] = []
    for rel in sorted(sb_files - pr_files):
        changes.append({"path": rel, "status": "added"})
    for rel in sorted(pr_files - sb_files):
        changes.append({"path": rel, "status": "deleted"})
    for rel in sorted(sb_files & pr_files):
        if _read(os.path.join(sandbox, rel)) != _read(os.path.join(project_root, rel)):
            changes.append({"path": rel, "status": "modified"})
    return changes


def file_pair(sandbox: str, project_root: str, rel: str) -> tuple[str, str]:
    """Conteúdo (antigo do projeto, novo da sandbox) de um arquivo — para mostrar o diff."""
    old = _read(os.path.join(os.path.abspath(project_root), rel))
    new = _read(os.path.join(sandbox, rel))
    dec = lambda b: b.decode("utf-8", "replace") if b is not None else ""
    return dec(old), dec(new)


def apply_sandbox(sandbox: str, project_root: str, paths: list[str] | None = None) -> dict:
    """Aplica as mudanças da sandbox de volta ao projeto real. Se `paths` for dado,
    aplica só esses; senão, aplica TODAS as mudanças detectadas. Retorna o resumo."""
    project_root = os.path.abspath(project_root)
    changes = diff_sandbox(sandbox, project_root)
    wanted = set(paths) if paths else None
    applied, deleted = [], []
    for ch in changes:
        rel = ch["path"]
        if wanted is not None and rel not in wanted:
            continue
        dst = os.path.join(project_root, rel)
        if ch["status"] in ("added", "modified"):
            os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
            shutil.copy2(os.path.join(sandbox, rel), dst)
            applied.append(rel)
        elif ch["status"] == "deleted":
            try:
                os.remove(dst)
                deleted.append(rel)
            except OSError:
                pass
    return {"ok": True, "applied": applied, "deleted": deleted,
            "count": len(applied) + len(deleted)}


def discard_sandbox(sandbox: str) -> bool:
    """Apaga a sandbox. Só remove se for mesmo uma pasta temporária de sandbox (segurança)."""
    real = os.path.abspath(sandbox)
    if _SANDBOX_PREFIX not in real:
        return False
    parent = os.path.dirname(real) if os.path.basename(real) == "project" else real
    shutil.rmtree(parent, ignore_errors=True)
    return True
