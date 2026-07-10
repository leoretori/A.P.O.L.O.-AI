"""Endpoints da Visão útil (M22, Épico 22.1) — ler tela e documentos.

  GET  /api/vision/status              → o que a visão consegue agora (honesto)
  POST /api/vision/screen  {describe?} → captura a tela (opcionalmente descreve)
  POST /api/vision/document {...}      → extrai o conteúdo de um documento/imagem,
                                          opcionalmente guardando na memória

Lê os singletons de `src.runtime` em tempo de requisição.
"""
import asyncio
import base64

from fastapi import APIRouter
from pydantic import BaseModel

from src import runtime as rt
from src import vision_read as V

router = APIRouter()


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
async def vision_screen(req: ScreenRequest):
    """Captura a tela; se `describe` e houver modelo de visão, descreve o que vê."""
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
