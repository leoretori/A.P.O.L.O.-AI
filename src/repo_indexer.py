"""Analisador de repositórios GitHub — clona, percorre e indexa no RAG.

Fluxo:
  URL GitHub → git clone --depth=1 (pasta temporária)
             → percorre arquivos de texto filtrados
             → add_example / add_chunked no ChromaDB
             → remove pasta temporária

Arquivos grandes são quebrados em chunks com overlap para preservar contexto.
"""

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Extensões de texto que valem ser indexadas ────────────────────────────────
TEXT_EXT = {
    # Código
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".go", ".java", ".kt", ".scala", ".rb", ".php",
    ".c", ".cpp", ".cc", ".h", ".hpp", ".cs",
    ".rs", ".swift", ".m", ".lua", ".r", ".jl",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    # Web
    ".html", ".htm", ".css", ".scss", ".less", ".svelte", ".vue",
    # Dados / config
    ".json", ".jsonc", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".env.example", ".properties",
    ".xml", ".graphql", ".proto", ".sql",
    # Docs
    ".md", ".mdx", ".txt", ".rst", ".adoc",
    # Infra
    ".tf", ".hcl", ".bicep", ".Makefile",
}

# Nomes de arquivos sem extensão que também valem
TEXT_NAMES = {
    "Dockerfile", "Makefile", "Procfile", "Brewfile",
    ".gitignore", ".gitattributes", ".editorconfig",
    "LICENSE", "NOTICE", "README", "CHANGELOG",
}

# Diretórios a ignorar
SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".pytest_cache",
    "venv", ".venv", "env", "dist", "build", "out", "bin", "obj",
    ".mypy_cache", ".ruff_cache", ".tox", "vendor", "third_party",
    ".idea", ".vscode", ".github", "coverage", ".nyc_output",
    "target", ".gradle", ".mvn", "logs", "tmp", "temp",
}

MAX_FILE_BYTES = 80_000    # 80 KB por arquivo (arquivos maiores são ignorados)
MAX_FILES      = 500       # teto de arquivos indexados por repo
CHUNK_SIZE     = 2000      # chars por chunk em arquivos grandes
CHUNK_OVERLAP  = 300       # sobreposição entre chunks


def _is_text_file(path: Path) -> bool:
    return (
        path.suffix.lower() in TEXT_EXT
        or path.name in TEXT_NAMES
        or (not path.suffix and path.stat().st_size < 4096)  # arquivo sem ext pequeno
    )


def _extract_repo_name(url: str) -> str:
    m = re.search(r"/([^/]+?)(?:\.git)?$", url.rstrip("/"))
    return m.group(1) if m else "repo"


def _extract_owner(url: str) -> str:
    m = re.search(r"github\.com/([^/]+)/", url)
    return m.group(1) if m else "unknown"


# ── Clone ─────────────────────────────────────────────────────────────────────

def clone_repo(url: str, dest: str) -> tuple[bool, str]:
    """git clone --depth=1. Retorna (sucesso, stderr)."""
    try:
        r = subprocess.run(
            ["git", "clone", "--depth=1", "--single-branch", url, dest],
            capture_output=True, text=True, timeout=180,
        )
        return r.returncode == 0, (r.stderr or "").strip()
    except subprocess.TimeoutExpired:
        return False, "Timeout (180s) — repositório muito grande."
    except FileNotFoundError:
        return False, "git não encontrado no PATH. Instale o Git e tente de novo."
    except Exception as e:
        return False, str(e)


# ── Coleta de arquivos ────────────────────────────────────────────────────────

def collect_files(root: str) -> list[tuple[str, str]]:
    """Retorna lista de (rel_path, content) para os arquivos de texto do repo."""
    root_path = Path(root)
    results: list[tuple[str, str]] = []

    for path in sorted(root_path.rglob("*")):
        if len(results) >= MAX_FILES:
            break
        if not path.is_file():
            continue
        # Pula diretórios proibidos em qualquer nível
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        try:
            size = path.stat().st_size
        except Exception:
            continue
        if size == 0 or size > MAX_FILE_BYTES:
            continue
        if not _is_text_file(path):
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore").strip()
            if not content:
                continue
            rel = str(path.relative_to(root_path)).replace("\\", "/")
            results.append((rel, content))
        except Exception:
            continue

    return results


# ── Indexação ─────────────────────────────────────────────────────────────────

def _doc_id(repo_name: str, rel_path: str, chunk_idx: int | None = None) -> str:
    key = f"{repo_name}/{rel_path}"
    h = hash(key) & 0xFFFFFF
    base = f"repo_{h:06x}"
    return f"{base}_c{chunk_idx}" if chunk_idx is not None else base


def index_file(
    rel_path: str, content: str,
    repo_name: str, repo_url: str, rag,
) -> int:
    """Indexa um arquivo no RAG. Retorna o número de chunks criados."""
    owner = _extract_owner(repo_url)
    raw_url = f"{repo_url}/blob/main/{rel_path}"
    meta = {
        "repo": repo_name,
        "repo_url": repo_url,
        "file_path": rel_path,
        "type": "repo_file",
        "owner": owner,
    }

    if len(content) <= CHUNK_SIZE:
        doc = f"# {repo_name}/{rel_path}\nFonte: {raw_url}\n\n{content}"
        rag.add_example(doc, _doc_id(repo_name, rel_path), metadata=meta)
        return 1

    # Arquivo grande → chunks com overlap
    chunks: list[str] = []
    start = 0
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        chunks.append(content[start:end])
        if end == len(content):
            break
        start += step

    for i, chunk in enumerate(chunks):
        header = f"# {repo_name}/{rel_path} (parte {i+1}/{len(chunks)})\nFonte: {raw_url}\n\n"
        rag.add_example(header + chunk, _doc_id(repo_name, rel_path, i), metadata=meta)

    return len(chunks)


# ── Gerador de progresso (async) ──────────────────────────────────────────────

async def analyze_repo(url: str, rag):
    """Gerador assíncrono de eventos de progresso para o endpoint SSE.

    Yields dicts: {type, ...}
    tipos: step | progress | done | error
    """
    url = url.strip().rstrip("/")
    if not url.startswith(("https://github.com/", "http://github.com/",
                            "https://gitlab.com/", "https://bitbucket.org/")):
        yield {"type": "error", "message": "URL deve ser de um repositório público (GitHub, GitLab ou Bitbucket)."}
        return

    repo_name = _extract_repo_name(url)
    yield {"type": "step", "icon": "🔗", "message": f"Clonando {repo_name}..."}

    tmp = tempfile.mkdtemp(prefix="apolo_repo_")
    try:
        ok, err = await asyncio.to_thread(clone_repo, url, tmp)
        if not ok:
            yield {"type": "error", "message": f"Falha no clone: {err}"}
            return

        yield {"type": "step", "icon": "🗂️", "message": "Coletando arquivos de texto..."}
        files = await asyncio.to_thread(collect_files, tmp)
        total = len(files)

        if total == 0:
            yield {"type": "error", "message": "Nenhum arquivo de texto encontrado no repositório."}
            return

        yield {"type": "step", "icon": "📥", "message": f"{total} arquivo(s) encontrado(s) — indexando no RAG..."}

        chunks_total = 0
        for i, (rel_path, content) in enumerate(files):
            n = await asyncio.to_thread(index_file, rel_path, content, repo_name, url, rag)
            chunks_total += n
            # Progresso a cada 5 arquivos ou no último
            if i % 5 == 0 or i == total - 1:
                yield {
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "file": rel_path,
                    "chunks": chunks_total,
                }

        yield {
            "type": "done",
            "repo_name": repo_name,
            "repo_url": url,
            "files_indexed": total,
            "chunks_total": chunks_total,
        }

    finally:
        await asyncio.to_thread(shutil.rmtree, tmp, True)
