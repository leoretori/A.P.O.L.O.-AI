"""Endpoints da Visão útil (M22, Épico 22.1) — ler tela e documentos.

  GET  /api/vision/status              → o que a visão consegue agora (honesto)
  POST /api/vision/screen  {describe?} → captura a tela (opcionalmente descreve)
  POST /api/vision/document {...}      → extrai o conteúdo de um documento/imagem,
                                          opcionalmente guardando na memória

Lê os singletons de `src.runtime` em tempo de requisição.
"""
import asyncio
import base64
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from src import runtime as rt
from src import vision_read as V

router = APIRouter()


def _require_same_origin(request: Request) -> None:
    """Barra CSRF em captura de tela/câmera (achado na auditoria de
    segurança 2026-07-15): esses dois endpoints não têm outro gate — "seu
    clique no botão = consentimento" só vale se a requisição de fato veio da
    própria página do app, não de um `fetch()` disparado por outra aba/site
    (CORS aqui é `allow_origins=["*"]`, então sem isso qualquer página
    conseguia te fotografar/capturar a tela silenciosamente).

    Só bloqueia quando `Origin`/`Referer` EXISTE e aponta pra outro host —
    navegadores sempre mandam `Origin` em POST cross-origin (não dá pra
    a página maliciosa omitir), então isso barra o ataque sem quebrar
    chamadas legítimas de ferramentas locais (curl, apps nativos) que
    tipicamente não mandam esses headers."""
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        return
    if urlparse(origin).netloc != request.headers.get("host", ""):
        raise HTTPException(403, "requisição de origem cruzada bloqueada")


class ScreenRequest(BaseModel):
    describe: bool = True


class DocRequest(BaseModel):
    filename: str
    data: str            # base64 do arquivo
    remember: bool = False


def _describe(image_b64: str, prompt: str) -> dict:
    """Descreve via o modelo de visão do app (pelo provedor ativo)."""
    from src.llm import chat_resilient, KEEP_ALIVE_HEAVY
    vm = rt.get_vision_model() if hasattr(rt, "get_vision_model") else None
    return V.describe_image(
        image_b64, vm,
        lambda m, msgs: chat_resilient(m, msgs, keep_alive=KEEP_ALIVE_HEAVY),
        prompt=prompt)


@router.get("/api/vision/status")
async def vision_status():
    vm = rt.get_vision_model() if hasattr(rt, "get_vision_model") else None
    return V.capabilities(vm)


@router.post("/api/vision/screen")
async def vision_screen(req: ScreenRequest, request: Request):
    """Captura a tela; se `describe` e houver modelo de visão, descreve o que vê."""
    _require_same_origin(request)
    cap = await asyncio.to_thread(V.capture_screen)
    if not cap.get("ok"):
        return cap
    out = {"ok": True, "size": cap["size"], "image_b64": cap["image_b64"]}
    if req.describe:
        desc = await asyncio.to_thread(_describe, cap["image_b64"], V.DESCRIBE_SCREEN_PROMPT)
        out["described"] = desc.get("ok", False)
        out["description"] = desc.get("description")
        out["describe_error"] = desc.get("error")
    return out


@router.post("/api/vision/camera")
async def vision_camera(req: ScreenRequest, request: Request):
    """Tira uma foto da câmera (M22.3); se `describe` e houver modelo de
    visão, descreve o que vê. Clique seu = consentimento, como o 22.1 — mas
    isso só protege quando a requisição vem mesmo da nossa página (ver
    `_require_same_origin`)."""
    _require_same_origin(request)
    cap = await asyncio.to_thread(V.capture_camera)
    if not cap.get("ok"):
        return cap
    out = {"ok": True, "size": cap["size"], "image_b64": cap["image_b64"]}
    if req.describe:
        desc = await asyncio.to_thread(_describe, cap["image_b64"], V.DESCRIBE_IMAGE_PROMPT)
        out["described"] = desc.get("ok", False)
        out["description"] = desc.get("description")
        out["describe_error"] = desc.get("error")
    return out


@router.post("/api/vision/document")
async def vision_document(req: DocRequest):
    """Extrai o conteúdo de um documento (PDF/DOCX/texto) ou marca imagem p/ visão.
    Com `remember`, guarda o texto na memória (RAG + base de conhecimento)."""
    try:
        raw = base64.b64decode(req.data or "")
    except Exception:
        return {"ok": False, "error": "data não é base64 válido"}
    res = await asyncio.to_thread(V.read_document, req.filename, raw)
    if res.get("ok") and res.get("needs_vision"):
        # imagem: descreve via visão em vez de extrair texto
        desc = await asyncio.to_thread(_describe, res["image_b64"], V.DESCRIBE_IMAGE_PROMPT)
        return {"ok": True, "kind": "image", "described": desc.get("ok", False),
                "description": desc.get("description"), "error": desc.get("error")}
    if res.get("ok") and req.remember and res.get("text") and rt.ingestor:
        try:
            saved = await asyncio.to_thread(rt.ingestor.ingest_text, req.filename,
                                            res["text"], "vision")
            res["remembered"] = bool(saved)
        except Exception as e:
            res["remember_error"] = str(e)[:200]
    return res
