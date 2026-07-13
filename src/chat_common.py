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


def get_session(session_id: str) -> list:
    """Retorna a sessão do cache em memória (rt.sessions) ou carrega do banco."""
    if session_id not in rt.sessions:
        loaded = rt.db.load_session(session_id) if rt.db else None
        if loaded:
            rt.sessions[session_id] = loaded
            logger.info(f"Sessão {session_id[:8]}... restaurada do banco ({len(loaded)} msgs)")
    return rt.sessions[session_id]


async def agent_recall(query: str, limit: int = 3) -> str:
    """Memória de longo prazo do agente — soluções/conhecimento já produzidos.
    Passa pelo MemoryFabric (porta única, M2): recupera da memória semântica (RAG).
    Se o fabric ainda não foi injetado, cai para um wrapper direto sobre rt.rag."""
    mem = rt.memory
    if mem is None:
        if not rt.rag:
            return ""
        from src.memory import MemoryFabric
        mem = MemoryFabric(rag=rt.rag)
    try:
        hits = await asyncio.to_thread(mem.recall, query, "semantic", limit)
    except Exception:
        return ""
    parts = []
    for h in hits or []:
        if h.score is not None and h.score < 0.15:
            continue
        parts.append(f"**{h.title or 'memória'}**\n{(h.text or '')[:400]}")
    return "\n\n---\n\n".join(parts)


async def generate_session_title(session_id: str, first_message: str) -> None:
    """Gera título curto para a sessão — roda em background.

    O Apolo-Nano (LLM própria) tenta PRIMEIRO; um portão de qualidade
    determinístico decide se a saída presta, senão cai no LLM grande
    (Épico 3.3 do APOLO_NANO_ROADMAP — fallback garantido).
    """
    try:
        from src.nanollm.routing import task_enabled

        title = None
        used_nano = False
        if rt.nano is not None and task_enabled("title"):
            from src.nanollm.tasks import nano_session_title

            title = await asyncio.to_thread(nano_session_title, rt.nano, first_message)
            used_nano = bool(title)   # None = portão de qualidade do Nano recusou
        if not title:
            # Este título roda em background (create_task, não awaited pelo stream) —
            # se o usuário mandar a 2ª mensagem rápido, o gpu_priority dela já
            # liberou o "user_exit" desta 1ª requisição. Sem ceder aqui, a geração
            # do título disputaria o lock do motor com essa 2ª mensagem.
            def _gen_title():
                if rt.gpu_gate:
                    rt.gpu_gate.wait_for_idle_sync(timeout=10.0)
                prompt = SESSION_TITLE_PROMPT.format(message=first_message[:200])
                return chat_resilient(
                    rt.get_chat_model(), [{"role": "user", "content": prompt}],
                    keep_alive=KEEP_ALIVE,
                )
            title = await asyncio.to_thread(_gen_title)
        title = (title or "").strip()[:80]
        if title and rt.db:
            rt.db.save_session_title(session_id, title)
            # Takeover progressivo (M27): registra quem serviu → % cérebro próprio.
            rt.db.nano_record_serve("title", "nano" if used_nano else "teacher")
    except Exception as e:
        logger.debug(f"Título de sessão: {e}")
