"""Prioriza a GPU para as requisições do usuário sobre o aprendizado de fundo.

O Ollama serializa as gerações de um mesmo modelo: se o learner está sumarizando
quando o usuário pergunta algo, a resposta do usuário fica na fila atrás do learner
(daí a sensação de "demora pra responder" com o aprendizado ligado).

O learner chama `await gate.wait_for_idle()` antes de cada geração; enquanto houver
requisição de usuário ativa, ele espera. Um timeout garante que o aprendizado não
trave para sempre caso algo fique preso.

O flywheel do Nano e a avaliação às cegas (M25/M28) rodam em THREAD comum (via
`asyncio.to_thread`), não no event loop — por isso usam `wait_for_idle_sync`, a
versão síncrona (poll simples, sem asyncio). Sem isso, o professor/juiz (Qwen)
chamava `provider.complete()` sem NUNCA ceder a vez: o treino noturno do Nano
podia segurar o lock do motor e fazer o chat do usuário esperar atrás dele — a
mesma classe de bug já corrigida no learner, só que num caminho diferente.
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class GpuGate:
    def __init__(self):
        self._active = 0
        self._idle = asyncio.Event()
        self._idle.set()

    def user_enter(self) -> None:
        self._active += 1
        self._idle.clear()

    def user_exit(self) -> None:
        self._active = max(0, self._active - 1)
        if self._active == 0:
            self._idle.set()

    @property
    def user_active(self) -> bool:
        return self._active > 0

    async def wait_for_idle(self, timeout: float = 45.0) -> bool:
        """Espera até não haver usuário ativo. Retorna True se ficou ocioso,
        False se estourou o timeout (aprendizado segue mesmo assim)."""
        if self._idle.is_set():
            return True
        logger.debug("[gpu-gate] aprendizado cedendo a GPU ao usuário...")
        try:
            await asyncio.wait_for(self._idle.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    def wait_for_idle_sync(self, timeout: float = 45.0, poll: float = 0.2) -> bool:
        """Igual a `wait_for_idle`, mas para quem roda numa THREAD comum (não no
        event loop) — o flywheel do Nano e a avaliação às cegas, que treinam/avaliam
        via `asyncio.to_thread`. Poll simples (o estado é um int; seguro sob o GIL).
        Retorna True se ficou ocioso, False se estourou o timeout (segue mesmo assim)."""
        if not self.user_active:
            return True
        logger.debug("[gpu-gate] treino/avaliação cedendo a GPU ao usuário...")
        deadline = time.monotonic() + timeout
        while self.user_active:
            if time.monotonic() >= deadline:
                return False
            time.sleep(poll)
        return True
