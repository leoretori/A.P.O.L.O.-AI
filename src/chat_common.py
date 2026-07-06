"""Infra compartilhada dos endpoints de IA (chat, research, agent, orchestrate).

Reúne o que esses endpoints têm em comum, para que possam viver em routers
separados sem import circular com app.py:
- `ChatRequest`: o corpo de requisição comum.
- `mark_request()` / `last_request_at()`: marca de atividade do usuário. O
  scheduler usa isso para saber que houve interação recente (e ceder a GPU ao
  usuário / não competir com o aprendizado).
- `generate_session_title`: gera um título curto para a sessão (background).

Parte da modularização M1 do JARVIS_ROADMAP.
"""
import asyncio
import logging
import time as _time

from pydantic import BaseModel

from src import runtime as rt
from src.llm import chat_resilient, KEEP_ALIVE
from src.prompts import SESSION_TITLE_PROMPT

logger = logging.getLogger("apolo.chat_common")


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    use_web: bool = False
    smart: bool = False  # usa o modelo 14b (raciocínio mais profundo) em vez do leve
    image: str = ""      # imagem em base64 (sem prefixo data:) → roteia p/ modelo de visão


# Marca do último request do usuário (perf_counter). O scheduler lê para detectar
# ociosidade. Módulo-global reatribuído via mark_request() — nunca acesse direto.
_last_request_at: float = 0.0


def mark_request() -> None:
    """Registra que o usuário acabou de interagir (chat/research/agent/orchestrate)."""
    global _last_request_at
    _last_request_at = _time.perf_counter()


def last_request_at() -> float:
    """Perf_counter do último request do usuário (0.0 se nunca houve)."""
    return _last_request_at


async def generate_session_title(session_id: str, first_message: str) -> None:
    """Gera título curto para a sessão usando LLM — roda em background."""
    try:
        prompt = SESSION_TITLE_PROMPT.format(message=first_message[:200])
        title = await asyncio.to_thread(
            chat_resilient,
            rt.get_chat_model(),
            [{"role": "user", "content": prompt}],
            keep_alive=KEEP_ALIVE,
        )
        title = (title or "").strip()[:80]
        if title and rt.db:
            rt.db.save_session_title(session_id, title)
    except Exception as e:
        logger.debug(f"Título de sessão: {e}")
