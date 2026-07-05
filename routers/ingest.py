"""Ingestão de conhecimento externo — documentos, URLs, pastas locais e
repositórios GitHub — para dentro da memória (RAG + base).

Rotas: /api/ingest, /api/ingest/url, /api/ingest/folder, /api/repo/analyze,
/api/repo/list. Extraído de app.py na M1 do JARVIS_ROADMAP.
"""
import asyncio
import json
import logging
import os

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src import runtime as rt

router = APIRouter()
logger = logging.getLogger("apolo.routers.ingest")


class IngestRequest(BaseModel):
    filename: str
    content: str
    encoding: str = "text"  # "text" (texto/código) | "base64" (PDF e binários)


@router.post("/api/ingest")
async def ingest_document(req: IngestRequest):
    """Ingere um documento do usuário na memória (ChromaDB + Supabase).
    Depois disso o A.P.O.L.O. responde sobre ele e o cita no chat."""
    if not rt.ingestor:
        return {"ok": False, "error": "Ingestor não inicializado."}
    filename = (req.filename or "documento").strip()[:120]
    try:
        if req.encoding == "base64":
            import base64
            data = base64.b64decode(req.content)
            if filename.lower().endswith(".pdf"):
                try:
                    from src.ingest import extract_pdf_text
                    text = await asyncio.to_thread(extract_pdf_text, data)
                except ModuleNotFoundError:
                    return {"ok": False, "error": "Suporte a PDF requer: pip install pypdf"}
            elif filename.lower().endswith(".docx"):
                try:
                    from src.ingest import extract_docx_text
                    text = await asyncio.to_thread(extract_docx_text, data)
                except ModuleNotFoundError:
                    return {"ok": False, "error": "Suporte a DOCX requer: pip install python-docx"}
            else:
                text = data.decode("utf-8", errors="ignore")
        else:
            text = req.content
    except Exception as e:
        logger.warning(f"Ingest decode error: {e}")
        return {"ok": False, "error": f"Falha ao ler o arquivo: {e}"}

    result = await asyncio.to_thread(rt.ingestor.ingest_text, filename, text)
    return result


class IngestUrlRequest(BaseModel):
    url: str


@router.post("/api/ingest/url")
async def ingest_url(req: IngestUrlRequest):
    """Aprende a partir de um link: busca a página e a ingere como um documento."""
    if not rt.ingestor:
        return {"ok": False, "error": "Ingestor não inicializado."}
    url = (req.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return {"ok": False, "error": "Informe uma URL http(s) válida."}
    try:
        from src.web_search import fetch_page_text
        text = await asyncio.wait_for(fetch_page_text(url), timeout=20.0)
    except Exception as e:
        logger.warning(f"Ingest URL fetch error: {e}")
        return {"ok": False, "error": "Não consegui buscar essa página."}
    if not text or len(text) < 50:
        return {"ok": False, "error": "A página não tem conteúdo de texto suficiente."}

    from urllib.parse import urlparse
    name = (urlparse(url).netloc or url)[:120]
    result = await asyncio.to_thread(rt.ingestor.ingest_text, name, text, url)
    result["source_url"] = url
    return result


class IngestFolderRequest(BaseModel):
    path: str
    extensions: list[str] = [".md", ".txt", ".markdown"]
    max_files: int = 200


@router.post("/api/ingest/folder")
async def ingest_folder(req: IngestFolderRequest):
    """Importa todos os arquivos de texto de uma pasta local (ex.: vault Obsidian).
    Percorre recursivamente, ingere cada arquivo .md/.txt no RAG e retorna o resumo."""
    if not rt.ingestor:
        return {"ok": False, "error": "Ingestor não inicializado."}

    folder = req.path.strip()
    if not os.path.isdir(folder):
        return {"ok": False, "error": f"Pasta não encontrada: {folder}"}

    # Coleta arquivos com as extensões pedidas
    _SKIP = {"__pycache__", ".git", "node_modules", ".obsidian"}
    files: list[str] = []
    for root, dirs, fnames in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
        for fname in sorted(fnames):
            if any(fname.lower().endswith(ext) for ext in req.extensions):
                files.append(os.path.join(root, fname))
                if len(files) >= req.max_files:
                    break
        if len(files) >= req.max_files:
            break

    if not files:
        return {"ok": False, "error": "Nenhum arquivo encontrado com as extensões pedidas."}

    # Ingere cada arquivo
    ok_count = 0
    skip_count = 0
    errors: list[str] = []

    def _ingest_file(fpath: str) -> dict:
        try:
            content = open(fpath, encoding="utf-8", errors="ignore").read()
            filename = os.path.relpath(fpath, folder).replace("\\", "/")
            source = f"obsidian://{filename}"
            return rt.ingestor.ingest_text(filename, content, source)
        except Exception as e:
            return {"ok": False, "error": str(e)[:120]}

    for fpath in files:
        res = await asyncio.to_thread(_ingest_file, fpath)
        if res.get("ok"):
            ok_count += 1
        else:
            skip_count += 1
            if res.get("error"):
                errors.append(res["error"])

    return {
        "ok": True,
        "folder": folder,
        "total_files": len(files),
        "ingested": ok_count,
        "skipped": skip_count,
        "errors": errors[:5],
    }


class RepoRequest(BaseModel):
    url: str


@router.post("/api/repo/analyze")
async def repo_analyze(req: RepoRequest):
    """Clona um repositório GitHub público, percorre todos os arquivos de texto
    e indexa no RAG com metadados (repo, file_path, owner). Streaming SSE com
    progresso em tempo real. Após concluir, o A.P.O.L.O. responde perguntas
    sobre qualquer arquivo do repositório."""
    from src.repo_indexer import analyze_repo as _analyze_repo

    def _ev(d: dict) -> str:
        return f"data: {json.dumps(d)}\n\n"

    async def stream():
        try:
            async for ev in _analyze_repo(req.url.strip(), rt.rag):
                yield _ev(ev)
                if ev.get("type") == "done" and rt.learner:
                    rt.learner.add_user_topic(f"repositório GitHub: {ev.get('repo_name','')}")
        except Exception as e:
            logger.error(f"repo_analyze: {e}", exc_info=True)
            yield _ev({"type": "error", "message": str(e)})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/repo/list")
async def repo_list():
    """Lista os repositórios indexados no RAG (doc_ids que começam com 'repo_')."""
    if not rt.rag:
        return {"repos": []}
    try:
        data = rt.rag.collection.get(where={"type": {"$eq": "repo_file"}},
                                     include=["metadatas"], limit=1000)
        repos: dict[str, dict] = {}
        for meta in (data.get("metadatas") or []):
            if meta and meta.get("repo"):
                name = meta["repo"]
                if name not in repos:
                    repos[name] = {"name": name, "url": meta.get("repo_url", ""),
                                   "files": 0}
                repos[name]["files"] += 1
        return {"repos": list(repos.values())}
    except Exception as e:
        logger.warning(f"repo_list: {e}")
        return {"repos": []}
