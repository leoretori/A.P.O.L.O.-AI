"""Ferramentas de leitura de arquivos do sistema (M6, Épico 6.2).

EXIGEM o grant `files.read` E ficam CONFINADAS às pastas que o usuário autorizou
(guardadas em Permission.note, uma por linha ou separadas por ';'). Tudo é
read-only. O grant abre a capacidade; a note delimita ONDE — um caminho fora da
allowlist é NEGADO mesmo com o grant. `resolve()` neutraliza `..` e symlinks que
tentem escapar da pasta autorizada.

As funções puras (parse_roots/search_files/read_file) não dependem de DB nem do
registry — são testáveis isoladamente. Os handlers só resolvem a allowlist a
partir do ctx.note e delegam.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from src.tools.registry import Tool, register

MAX_READ_BYTES = 200_000          # teto por arquivo (não carrega binário gigante)
MAX_SEARCH_HITS = 100
# Diretórios de ruído que nunca interessam numa busca de arquivos do usuário.
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env",
              ".claude", "dist", "build", ".next", ".cache", ".mypy_cache",
              ".pytest_cache", ".idea", ".vscode"}


def parse_roots(note: str) -> list[Path]:
    """Converte a note do grant numa lista de pastas absolutas existentes.
    Aceita várias pastas separadas por quebra de linha ou ';'."""
    roots: list[Path] = []
    for raw in (note or "").replace(";", "\n").splitlines():
        p = raw.strip().strip('"').strip("'")
        if not p:
            continue
        try:
            rp = Path(p).expanduser().resolve()
        except Exception:
            continue
        if rp.is_dir() and rp not in roots:
            roots.append(rp)
    return roots


def _within(path: Path, roots: list[Path]) -> bool:
    """True se `path`, já resolvido (sem `..`/symlink de fuga), está DENTRO de
    alguma pasta autorizada."""
    try:
        rp = path.resolve()
    except Exception:
        return False
    for root in roots:
        if rp == root:
            return True
        try:
            if rp.is_relative_to(root):
                return True
        except Exception:
            pass
    return False


def search_files(query: str, roots: list[Path], limit: int = 50) -> list[dict]:
    """Busca arquivos cujo NOME contém `query` (case-insensitive) nas pastas
    autorizadas. query vazia lista tudo. Read-only, pula diretórios de ruído."""
    q = (query or "").strip().lower()
    cap = max(1, min(int(limit or 50), MAX_SEARCH_HITS))
    hits: list[dict] = []
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            # poda in-place: não desce em ruído nem em ocultos
            dirnames[:] = [d for d in dirnames
                           if d not in _SKIP_DIRS and not d.startswith(".")]
            for fn in sorted(filenames):
                if fn.startswith("."):
                    continue
                if q and q not in fn.lower():
                    continue
                full = Path(dirpath) / fn
                if not _within(full, roots):     # segurança contra symlink de fuga
                    continue
                try:
                    st = full.stat()
                except OSError:
                    continue
                hits.append({
                    "path": str(full),
                    "name": fn,
                    "size": st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                })
                if len(hits) >= cap:
                    return hits
    return hits


def read_file(path_str: str, roots: list[Path], max_bytes: int = MAX_READ_BYTES) -> dict:
    """Lê um arquivo de texto DENTRO das pastas autorizadas. Fora da allowlist →
    PermissionError. Não é arquivo → FileNotFoundError. Decodifica como UTF-8
    (com replace) e trunca em max_bytes."""
    p = Path(path_str or "").expanduser()
    if not _within(p, roots):
        raise PermissionError("caminho fora das pastas autorizadas")
    rp = p.resolve()
    if not rp.is_file():
        raise FileNotFoundError("arquivo não encontrado")
    size = rp.stat().st_size
    with open(rp, "rb") as fh:
        data = fh.read(max_bytes)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-8", errors="replace")
    return {"path": str(rp), "content": text,
            "bytes": size, "truncated": size > max_bytes}


# ── Handlers (recebem args + ctx; a allowlist vem de ctx.note) ──
_NO_ROOTS = ("nenhuma pasta autorizada — abra 🔐 Permissões, autorize 'files.read' "
             "e informe a pasta que o A.P.O.L.O. pode ler")


def _tool_search(args: dict, ctx) -> dict:
    roots = parse_roots(getattr(ctx, "note", ""))
    if not roots:
        raise PermissionError(_NO_ROOTS)
    query = (args or {}).get("query", "")
    results = search_files(query, roots, (args or {}).get("limit", 50))
    return {"query": query, "count": len(results), "results": results,
            "roots": [str(r) for r in roots]}


def _tool_read(args: dict, ctx) -> dict:
    roots = parse_roots(getattr(ctx, "note", ""))
    if not roots:
        raise PermissionError(_NO_ROOTS)
    path = (args or {}).get("path", "")
    if not path:
        raise ValueError("informe 'path' do arquivo a ler")
    return read_file(path, roots)


register(Tool(name="files.search", scope="files.read",
              description="Busca arquivos por nome nas pastas autorizadas",
              handler=_tool_search))
register(Tool(name="files.read", scope="files.read",
              description="Lê o conteúdo de um arquivo de texto autorizado",
              handler=_tool_read))
