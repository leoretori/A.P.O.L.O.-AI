"""Estado e helpers compartilhados do Coder — vistos pelo loop ReAct (`/api/coder`
em app.py) e pelos routers de ferramentas do Coder, sem import circular.

Duas peças acopladas moram aqui:
1. O CACHE do baseline da guarda de regressão: medir a suíte é caro na CPU, então
   guardamos o resultado por CODER_BASELINE_TTL; qualquer mudança fora do loop
   (terminal, apagar/mover/substituir, undo, troca de pasta) invalida o cache.
2. `gpu_priority`: enquanto a requisição do usuário streama, o learner cede a GPU
   a ela (o Ollama serializa a GPU — o usuário tem prioridade sobre o aprendizado).

Parte da modularização M1 do JARVIS_ROADMAP.
"""
import os

from src import runtime as rt

CODER_BASELINE_TTL = int(os.getenv("CODER_BASELINE_TTL", 900))
baseline_cache: dict[str, tuple[bool, float]] = {}


def invalidate_baseline() -> None:
    """Workspace mudou fora do loop do Coder → baseline de testes não vale mais."""
    baseline_cache.clear()


async def gpu_priority(gen):
    """Enquanto a requisição do usuário streama, o learner cede a GPU a ela.
    O user_exit dispara mesmo se o cliente desconectar (o finally roda no close)."""
    gate = rt.gpu_gate
    if gate:
        gate.user_enter()
    try:
        async for ev in gen:
            yield ev
    finally:
        if gate:
            gate.user_exit()
