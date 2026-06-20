"""Telemetria de latência por endpoint — leve, em memória, thread-safe.

Acumula contagem, soma, máximo e uma janela das últimas amostras por rota para
calcular média e p95. Serve para flagrar regressões de performance (ex.: o painel
Mente voltar a ficar lento) sem nenhuma dependência externa.
"""

import threading
import time
from collections import defaultdict, deque


class LatencyTracker:
    def __init__(self, window: int = 200):
        self._lock = threading.Lock()
        self._count: dict[str, int] = defaultdict(int)
        self._sum_ms: dict[str, float] = defaultdict(float)
        self._max_ms: dict[str, float] = defaultdict(float)
        self._errors: dict[str, int] = defaultdict(int)
        # Janela das últimas N amostras por rota → p95 sem guardar tudo.
        self._samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
        self._slowest: tuple[str, float] = ("", 0.0)

    def record(self, route: str, ms: float, is_error: bool = False) -> None:
        with self._lock:
            self._count[route] += 1
            self._sum_ms[route] += ms
            if ms > self._max_ms[route]:
                self._max_ms[route] = ms
            if is_error:
                self._errors[route] += 1
            self._samples[route].append(ms)
            if ms > self._slowest[1]:
                self._slowest = (route, ms)

    def snapshot(self) -> dict:
        with self._lock:
            routes = []
            for route, count in self._count.items():
                samples = sorted(self._samples[route])
                p95 = samples[min(len(samples) - 1, int(len(samples) * 0.95))] if samples else 0.0
                routes.append({
                    "route": route,
                    "count": count,
                    "avg_ms": round(self._sum_ms[route] / count, 1) if count else 0.0,
                    "p95_ms": round(p95, 1),
                    "max_ms": round(self._max_ms[route], 1),
                    "errors": self._errors[route],
                })
            routes.sort(key=lambda r: r["avg_ms"], reverse=True)
            total = sum(self._count.values())
            return {
                "total_requests": total,
                "routes": routes,
                "slowest": {"route": self._slowest[0], "ms": round(self._slowest[1], 1)},
            }

    def reset(self) -> None:
        with self._lock:
            self._count.clear()
            self._sum_ms.clear()
            self._max_ms.clear()
            self._errors.clear()
            self._samples.clear()
            self._slowest = ("", 0.0)


# Instância global do app.
tracker = LatencyTracker()


class _Timer:
    """Context manager utilitário para medir um bloco e registrar no tracker."""
    def __init__(self, route: str):
        self.route = route
        self.is_error = False

    def __enter__(self):
        self._t = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        ms = (time.perf_counter() - self._t) * 1000
        tracker.record(self.route, ms, is_error=self.is_error or exc_type is not None)
        return False


def timed(route: str) -> _Timer:
    return _Timer(route)
