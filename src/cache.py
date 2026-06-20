"""Cache de valor único com expiração por TTL — utilitário compartilhado.

Vários pontos do A.P.O.L.O. (painel Mente, qualidade do recall, mapa) cacheiam um
resultado caro por alguns segundos e o invalidam quando os dados mudam. Antes cada
um reimplementava o par `(valor, timestamp)` à mão; este utilitário centraliza isso.

    cache = TTLCache(ttl=120)
    val = cache.get()              # None se vazio ou expirado
    if val is None:
        val = cache.set(compute()) # grava e devolve
    ...
    cache.invalidate()             # força recálculo na próxima
    cache.peek()                   # último valor mesmo se expirado (fallback em falha)
"""

import time


class TTLCache:
    """Guarda um único valor com tempo de vida `ttl` (segundos)."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._value = None
        self._at = 0.0

    def get(self):
        """Retorna o valor se ainda fresco; senão None."""
        if self._value is not None and (time.time() - self._at) < self.ttl:
            return self._value
        return None

    def set(self, value):
        """Grava o valor, carimba o tempo e o devolve (para uso encadeado)."""
        self._value = value
        self._at = time.time()
        return value

    def peek(self):
        """Último valor gravado, mesmo que expirado (ou None se nunca gravado).
        Útil como fallback quando a fonte está indisponível."""
        return self._value

    def invalidate(self):
        """Descarta o valor — a próxima leitura recalcula."""
        self._value = None
