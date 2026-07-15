"""Ferramenta de agência para VISÃO (M22, Épico 22.2) — ver a tela para agir
sobre ela, pelo caminho seguro do M6 (`run_tool` → consentimento + auditoria).

Diferente do endpoint manual `/api/vision/screen` (M22.1 — um clique seu no
console 👁️ já É o consentimento), esta ferramenta é o que o AGENTE usa quando
decide, sozinho, olhar a tela para responder (ex.: via `/api/agency/ask` ou o
chat). Por tocar algo sensível (a tela pode mostrar senhas, mensagens
privadas), passa pelo MESMO portão de permissão das demais ações do M6 —
negada por padrão até você autorizar o escopo `vision.screen`.
"""
from __future__ import annotations

from src import vision_read
from src.tools.registry import Tool, register


def _describe(image_b64: str, prompt: str) -> dict:
    """Descreve via o modelo de visão do app (import preguiçoso — só quem
    chama paga o custo do motor; testável via monkeypatch de `src.llm`)."""
    from src import runtime as rt
    from src.llm import KEEP_ALIVE_HEAVY, chat_resilient

    vm = rt.get_vision_model() if hasattr(rt, "get_vision_model") else None
    return vision_read.describe_image(
        image_b64, vm,
        lambda m, msgs: chat_resilient(m, msgs, keep_alive=KEEP_ALIVE_HEAVY),
        prompt=prompt)


def _tool_vision_screen(args: dict, ctx) -> dict:
    """Captura a tela e, se houver modelo de visão, descreve o que vê.
    `describe=False` só captura (sem gastar o modelo de visão). O base64 da
    imagem NUNCA entra no resultado — evita despejar a captura crua na
    auditoria; só o tamanho e a descrição textual voltam."""
    cap = vision_read.capture_screen()
    if not cap.get("ok"):
        return cap
    out: dict = {"ok": True, "size": cap["size"]}
    if (args or {}).get("describe", True):
        desc = _describe(cap["image_b64"], vision_read.DESCRIBE_SCREEN_PROMPT)
        out["described"] = desc.get("ok", False)
        if desc.get("ok"):
            out["description"] = desc.get("description")
        else:
            out["describe_error"] = desc.get("error")
    return out


register(Tool(
    name="vision.screen", scope="vision.screen",
    description="Vê sua tela (captura + descrição) para responder perguntas sobre o que está nela",
    handler=_tool_vision_screen,
))
