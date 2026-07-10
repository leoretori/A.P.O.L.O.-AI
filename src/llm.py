"""Utilitários de acesso ao Ollama.

Centraliza três otimizações de latência:
  • keep_alive — mantém o modelo residente na VRAM entre as requisições, evitando
    o recarregamento do disco a cada mensagem (a maior causa de "demora pra responder").
  • stream_chat — streama tokens em uma thread, sem bloquear o event loop (o mesmo
    padrão já usado pelo reviewer e pela pesquisa profunda).
  • warmup — pré-carrega o modelo no boot, para que a primeira resposta seja rápida.
"""

import asyncio
import logging
import threading


from src.resilience import CircuitBreaker, retry_call

logger = logging.getLogger(__name__)

# Breaker dedicado ao Ollama. Ele é local, então é menos sujeito a falhas que o
# Supabase — mas um cold-start/descarregamento de modelo pode dar timeout pontual,
# e um retry curto resolve sem incomodar o usuário.
_ollama_breaker = CircuitBreaker(fail_max=4, reset_after=15.0, name="ollama")


def ollama_breaker_state() -> dict:
    return _ollama_breaker.snapshot()


def chat_resilient(model: str, messages: list[dict],
                   keep_alive=None, options: dict | None = None):
    """`ollama.chat` (não-streaming) com retry + circuit breaker.

    Para as chamadas discretas (autocrítica, agente, coder) onde uma falha
    transitória não deve abortar a operação inteira. Streaming continua em
    `stream_chat` (não dá para retentar no meio de um fluxo de tokens)."""
    from src.providers import get_provider
    ka = KEEP_ALIVE if keep_alive is None else keep_alive
    return _ollama_breaker.call(
        retry_call, lambda: get_provider().complete(
            model, messages, options=options, keep_alive=ka),
        attempts=2, base_delay=0.6,
    )


def stream_sync(model: str, messages: list[dict],
                options: dict | None = None, keep_alive=None):
    """Streaming **síncrono** de tokens pelo provedor ativo — para contextos que já
    rodam fora do event loop (pesquisa, reviewer). Produz strings. Use `stream_chat`
    no caminho assíncrono. Não retenta (não dá para retomar no meio do fluxo)."""
    from src.providers import get_provider
    ka = KEEP_ALIVE if keep_alive is None else keep_alive
    yield from get_provider().stream(model, messages, options=options, keep_alive=ka)

# keep_alive derivado do perfil de hardware (src/hardware.py). No perfil 'max'
# (máquina dedicada) o modelo pesado fica quente; no 'balanced' descarrega logo.
from src.hardware import keep_alive_chat as _ka_chat, keep_alive_heavy as _ka_heavy
KEEP_ALIVE: str = _ka_chat()
KEEP_ALIVE_HEAVY: str = _ka_heavy()


async def stream_chat(
    model: str,
    messages: list[dict],
    keep_alive: str | int | None = KEEP_ALIVE,
    options: dict | None = None,
):
    """Streama os tokens do provedor de LLM ativo (Ollama ou motor próprio) sem
    bloquear o event loop.

    Produz (yield) o conteúdo de cada chunk como string. Se o worker falhar,
    a exceção é repropagada para quem consome o gerador."""
    from src.providers import get_provider
    provider = get_provider()
    q: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def worker():
        try:
            for piece in provider.stream(model, messages, options=options, keep_alive=keep_alive):
                loop.call_soon_threadsafe(q.put_nowait, ("token", piece))
        except Exception as e:  # noqa: BLE001 — propagado ao consumidor
            loop.call_soon_threadsafe(q.put_nowait, ("error", e))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, ("end", None))

    threading.Thread(target=worker, daemon=True).start()
    while True:
        kind, val = await q.get()
        if kind == "end":
            break
        if kind == "error":
            raise val
        yield val


async def warmup(model: str) -> None:
    """Pré-carrega o modelo na VRAM para a primeira resposta não pagar o cold start."""
    from src.providers import get_provider
    try:
        await asyncio.to_thread(
            retry_call,
            lambda: get_provider().complete(
                model, [{"role": "user", "content": "ok"}],
                options={"num_predict": 1}, keep_alive=KEEP_ALIVE),
            attempts=3, base_delay=1.0,  # o motor pode estar subindo no boot
        )
        logger.info(f"[warmup] modelo {model} pré-carregado na memória (keep_alive={KEEP_ALIVE})")
    except Exception as e:
        logger.warning(f"[warmup] falhou (modelo carregará na 1ª mensagem): {e}")
