"""Perfil de hardware / performance da inferência.

Centraliza as decisões de "quanto da máquina usar". Pensado para uma máquina
DEDICADA a rodar o A.P.O.L.O. (CPU-only, sem GPU): mantém o modelo quente, usa
contexto maior e permite fixar o nº de threads.

Controlado por variáveis de ambiente:
    APOLO_PERFORMANCE=balanced  (padrão) | max
        - balanced: libera RAM entre tarefas pesadas (bom p/ uso compartilhado).
        - max: mantém o modelo pesado residente e usa contexto grande (máquina dedicada).
    APOLO_NUM_THREAD=<n>   nº de threads de inferência (vazio = deixa o Ollama decidir;
                           num Ryzen 6c/12t, 6 costuma ser o ideal).
    APOLO_NUM_CTX=<n>      janela de contexto no perfil max (padrão 8192).
    OLLAMA_KEEP_ALIVE / OLLAMA_KEEP_ALIVE_HEAVY  sobrescrevem o keep_alive.
"""

import os


def profile() -> str:
    p = os.getenv("APOLO_PERFORMANCE", "balanced").strip().lower()
    return "max" if p == "max" else "balanced"


def is_max() -> bool:
    return profile() == "max"


def num_threads() -> int | None:
    """Threads de inferência. None = deixa o motor decidir (padrão seguro)."""
    raw = os.getenv("APOLO_NUM_THREAD", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return None


def num_ctx() -> int:
    raw = os.getenv("APOLO_NUM_CTX", "").strip()
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return 8192


def inference_options() -> dict:
    """Opções a injetar em TODA chamada de inferência (o chamador tem prioridade).
    No perfil 'max', usa contexto grande para o modelo enxergar mais de uma vez."""
    opts: dict = {}
    t = num_threads()
    if t:
        opts["num_thread"] = t
    if is_max():
        opts["num_ctx"] = num_ctx()
    return opts


def keep_alive_chat() -> str:
    """Modelo leve do chat: vale manter quente (ocupa pouca RAM)."""
    return (os.getenv("OLLAMA_KEEP_ALIVE", "").strip() or "30m")


def keep_alive_heavy() -> str:
    """Modelo pesado (14b). Em 'balanced' descarrega na hora (libera RAM); em 'max'
    (máquina dedicada) mantém quente para não pagar o recarregamento do disco."""
    v = os.getenv("OLLAMA_KEEP_ALIVE_HEAVY", "").strip()
    if v:
        return v
    return "30m" if is_max() else "0"


def summary() -> dict:
    """Para o painel de Saúde — o que está em vigor."""
    return {
        "profile": profile(),
        "num_thread": num_threads() or "auto",
        "num_ctx": num_ctx() if is_max() else "padrão do modelo",
        "keep_alive_chat": keep_alive_chat(),
        "keep_alive_heavy": keep_alive_heavy(),
        "cpu_count": os.cpu_count(),
    }
