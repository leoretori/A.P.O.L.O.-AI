"""Visão útil (M22, Épico 22.1) — ler TELA e DOCUMENTOS como entrada rica.

"O que tem nessa tela / nesse documento / nessa imagem?" resolvido reusando o
que já existe: captura de tela (Pillow), extração de texto de PDF/DOCX/texto
(`src.ingest`), o modelo de visão do chat, e a porta da memória (`Ingestor`).

Núcleo determinístico e testável: a captura/decodificação/roteamento por tipo
NÃO chamam LLM. A parte de "entender" (descrever imagem/tela) é opcional e só
roda quando há um modelo de visão disponível — surfaced honestamente em
`capabilities()`.
"""
from __future__ import annotations

import base64
import io

# Tipos de arquivo que sabemos LER como texto direto (sem visão).
_TEXT_EXTS = (".txt", ".md", ".markdown", ".csv", ".json", ".log", ".py",
              ".js", ".ts", ".html", ".css", ".yml", ".yaml", ".xml", ".ini")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
MAX_TEXT_CHARS = 20000
SCREEN_MAX_WIDTH = 1280          # redimensiona a captura p/ um payload de visão sensato

DESCRIBE_SCREEN_PROMPT = ("Descreva de forma útil o que aparece nesta tela: as "
                          "janelas/apps abertos, o texto principal e o que o "
                          "usuário parece estar fazendo. Seja específico e conciso.")
DESCRIBE_IMAGE_PROMPT = "Descreva o que há nesta imagem, de forma específica e concisa."


def _ext(filename: str) -> str:
    name = (filename or "").lower().strip()
    dot = name.rfind(".")
    return name[dot:] if dot >= 0 else ""


def capture_screen(max_width: int = SCREEN_MAX_WIDTH) -> dict:
    """Tira um screenshot da tela e devolve PNG em base64 (redimensionado).
    {ok, image_b64, size:[w,h]} ou {ok:False, error}. Local e soberano."""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
    except Exception as e:
        return {"ok": False, "error": f"captura de tela indisponível: {e}"}
    w, h = img.size
    if w > max_width:
        img = img.resize((max_width, max(1, round(h * max_width / w))))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return {"ok": True, "image_b64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "size": list(img.size)}


def read_document(filename: str, raw: bytes) -> dict:
    """Roteia por tipo e EXTRAI o conteúdo textual (sem LLM). Imagens não têm
    texto → marcadas com `needs_vision` para o caminho de visão.
    {ok, kind, text?, chars?, image_b64?, needs_vision?, error?}."""
    ext = _ext(filename)
    if ext in _IMAGE_EXTS:
        return {"ok": True, "kind": "image", "needs_vision": True,
                "image_b64": base64.b64encode(raw).decode("ascii")}
    if ext == ".pdf":
        try:
            from src.ingest import extract_pdf_text
            text = extract_pdf_text(raw)
        except ImportError:
            return {"ok": False, "kind": "pdf",
                    "error": "leitura de PDF requer: pip install pypdf"}
        except Exception as e:
            return {"ok": False, "kind": "pdf", "error": f"falha ao ler o PDF: {e}"}
        return {"ok": True, "kind": "pdf", "text": text[:MAX_TEXT_CHARS],
                "chars": len(text)}
    if ext == ".docx":
        try:
            from src.ingest import extract_docx_text
            text = extract_docx_text(raw)
        except ImportError:
            return {"ok": False, "kind": "docx",
                    "error": "leitura de DOCX requer: pip install python-docx"}
        except Exception as e:
            return {"ok": False, "kind": "docx", "error": f"falha ao ler o DOCX: {e}"}
        return {"ok": True, "kind": "docx", "text": text[:MAX_TEXT_CHARS],
                "chars": len(text)}
    if ext in _TEXT_EXTS or not ext:
        text = raw.decode("utf-8", errors="replace")
        return {"ok": True, "kind": "text", "text": text[:MAX_TEXT_CHARS],
                "chars": len(text)}
    return {"ok": False, "kind": "unknown", "error": f"tipo não suportado: {ext}"}


def describe_image(image_b64: str, vision_model, complete_fn, *,
                   prompt: str = DESCRIBE_IMAGE_PROMPT) -> dict:
    """Descreve uma imagem/tela via o modelo de VISÃO. `complete_fn(model,
    messages)` é injetável (o provedor do app nos testes/produção). None se não
    houver modelo de visão."""
    if not vision_model:
        return {"ok": False, "error": "sem modelo de visão — baixe um (ex.: ollama pull llava) "
                                      "ou selecione um backend com visão"}
    try:
        out = complete_fn(vision_model,
                          [{"role": "user", "content": prompt, "images": [image_b64]}])
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}
    return {"ok": True, "description": (out or "").strip(), "model": vision_model}


def capabilities(vision_model: str | None) -> dict:
    """O que a visão consegue AGORA (honesto): captura de tela? visão? PDF?"""
    screen_ok = False
    try:
        from PIL import ImageGrab  # noqa: F401
        screen_ok = True
    except Exception:
        pass
    import importlib.util
    pdf_ok = importlib.util.find_spec("pypdf") is not None
    return {"screen": screen_ok, "vision": bool(vision_model),
            "vision_model": vision_model or None, "pdf": pdf_ok,
            "text_docs": True}
