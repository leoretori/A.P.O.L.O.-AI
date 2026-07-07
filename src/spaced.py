"""Repetição espaçada — agendador SM-2 (M8, Épico 8.1).

O A.P.O.L.O. se auto-testa sobre o que estudou: em intervalos crescentes, tenta
LEMBRAR um tópico (força do recall na memória). Se lembra bem, o intervalo cresce
(1d → 6d → ~15d → ~38d…); se esqueceu, o intervalo reseta e o tópico VOLTA para a
fila de estudo. Assim ele reforça o que sabe em vez de só correr atrás do novo.

Núcleo 100% determinístico e testável (algoritmo SM-2 clássico). A "nota" (quality
0–5) vem da força do recall — sem custo de LLM.
"""
from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT_EASE = 2.5
MIN_EASE = 1.3
PASS_THRESHOLD = 3          # quality >= 3 = lembrou


def initial_state() -> dict:
    return {"ease": DEFAULT_EASE, "interval": 0, "reps": 0, "lapses": 0}


def review(state: dict | None, quality: int) -> dict:
    """SM-2: dado o estado atual e a nota (0–5) do auto-teste, devolve o novo
    estado (ease/interval/reps/lapses). quality<3 = esqueceu → reaprende."""
    st = {**initial_state(), **(state or {})}
    q = max(0, min(int(quality), 5))
    ease, reps, interval, lapses = st["ease"], st["reps"], st["interval"], st["lapses"]

    if q < PASS_THRESHOLD:
        reps = 0
        interval = 1                       # reaprende amanhã
        lapses += 1
    else:
        reps += 1
        if reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = max(1, round(interval * ease))
        # ajuste de facilidade do SM-2
        ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))

    ease = max(MIN_EASE, round(ease, 3))
    return {"ease": ease, "interval": interval, "reps": reps, "lapses": lapses}


def next_due(state: dict, now: datetime | None = None) -> datetime:
    now = now or datetime.now()
    return now + timedelta(days=max(1, int(state.get("interval", 1))))


def quality_from_recall(top_score: float | None, has_hit: bool) -> int:
    """Traduz a FORÇA do recall (relevância do melhor acerto, 0..1) numa nota SM-2.
    Sem acerto = esqueceu (2). Recall forte = lembrou muito bem (5)."""
    if not has_hit:
        return 2
    s = top_score if isinstance(top_score, (int, float)) else 0.0
    if s >= 0.75:
        return 5
    if s >= 0.55:
        return 4
    if s >= 0.35:
        return 3
    return 2                               # acerto fraco = quase esqueceu
