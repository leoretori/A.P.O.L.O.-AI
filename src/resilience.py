"""Resiliência para chamadas externas: retry com backoff + circuit breaker.

Sem dependências (não usa tenacity) para manter o projeto leve. Tudo é síncrono —
os chamadores já rodam estas funções dentro de `asyncio.to_thread`.

- `retry_call` repete uma função em falhas transitórias com backoff exponencial
  e jitter, até `attempts` tentativas.
- `CircuitBreaker` evita martelar um serviço que está claramente fora do ar:
  após `fail_max` falhas consecutivas ele "abre" e rejeita rápido por `reset_after`
  segundos; depois entra em "half-open" e deixa uma tentativa passar para testar.
"""

import logging
import random
import time

logger = logging.getLogger(__name__)


class CircuitOpenError(Exception):
    """Levantada quando o circuito está aberto (serviço considerado fora do ar)."""


def retry_call(
    fn,
    *args,
    attempts: int = 3,
    base_delay: float = 0.4,
    max_delay: float = 4.0,
    exceptions: tuple = (Exception,),
    on_retry=None,
    **kwargs,
):
    """Executa `fn(*args, **kwargs)` repetindo em falha transitória.

    Backoff exponencial com jitter: ~base_delay, 2×, 4×… (limitado a max_delay).
    Repropaga a última exceção se todas as tentativas falharem."""
    last_exc = None
    for i in range(1, attempts + 1):
        try:
            return fn(*args, **kwargs)
        except exceptions as e:
            last_exc = e
            if i >= attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (i - 1)))
            delay += random.uniform(0, delay * 0.25)  # jitter p/ evitar thundering herd
            if on_retry:
                try:
                    on_retry(i, e, delay)
                except Exception:  # noqa: BLE001 — callback não pode quebrar o retry
                    pass
            logger.debug(f"retry {i}/{attempts} após erro: {e!r} — aguardando {delay:.2f}s")
            time.sleep(delay)
    raise last_exc


class CircuitBreaker:
    """Circuit breaker simples e thread-safe-o-suficiente para uso single-process.

    Estados: 'closed' (normal), 'open' (rejeita rápido), 'half_open' (testando)."""

    def __init__(self, fail_max: int = 5, reset_after: float = 30.0, name: str = ""):
        self.fail_max = fail_max
        self.reset_after = reset_after
        self.name = name or "circuit"
        self._fails = 0
        self._opened_at = 0.0
        self.state = "closed"

    def _allow(self) -> bool:
        if self.state == "open":
            if (time.time() - self._opened_at) >= self.reset_after:
                self.state = "half_open"
                return True
            return False
        return True

    def record_success(self) -> None:
        self._fails = 0
        if self.state != "closed":
            logger.info(f"[{self.name}] circuito fechado (serviço recuperado)")
        self.state = "closed"

    def record_failure(self) -> None:
        self._fails += 1
        if self._fails >= self.fail_max and self.state != "open":
            self.state = "open"
            self._opened_at = time.time()
            logger.warning(f"[{self.name}] circuito ABERTO após {self._fails} falhas "
                           f"— rejeitando por {self.reset_after:.0f}s")
        elif self.state == "half_open":
            # Falhou no teste → reabre o circuito.
            self.state = "open"
            self._opened_at = time.time()

    def call(self, fn, *args, **kwargs):
        """Chama `fn` protegido pelo breaker. Levanta CircuitOpenError se aberto."""
        if not self._allow():
            raise CircuitOpenError(f"{self.name} indisponível (circuito aberto)")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()
            return result

    def snapshot(self) -> dict:
        return {"name": self.name, "state": self.state, "fails": self._fails}
