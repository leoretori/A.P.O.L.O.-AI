"""Roteamento do takeover progressivo (M27): o cérebro próprio assume por família.

Cada tarefa estreita (título, setor, …) tenta PRIMEIRO o Nano; um portão decide
se ele pode assumir aquela família (gate deliberado) e, dentro dela, o próprio
Nano valida a saída (retorna None se ruim) — senão cai no professor (Qwen). Toda
decisão é registrada, então o painel mostra a **% do dia servida pelos pesos do
Leo** subir. Núcleo puro e determinístico: `recorder`/funções são injetáveis.
"""
from __future__ import annotations

import os
from typing import Callable

# Famílias estreitas candidatas ao Nano (alta frequência, baixo risco).
NANO_TASKS = ("title", "sector", "tags")


def task_enabled(task: str) -> bool:
    """Portão deliberado por família: `NANO_TASKS_OFF=sector,tags` desliga
    famílias específicas (o professor volta a servi-las) sem mexer no código.
    Vazio = todas ligadas (o Nano tenta, com fallback garantido)."""
    off = {t.strip() for t in os.getenv("NANO_TASKS_OFF", "").split(",") if t.strip()}
    return task not in off


def route_task(
    task: str,
    nano_fn: Callable[[], object],
    fallback_fn: Callable[[], object],
    *,
    recorder: Callable[[str, str], None] | None = None,
    nano_available: bool = True,
) -> tuple[object, str]:
    """Roteia UMA tarefa: Nano primeiro (se ligado+disponível), senão professor.

    `nano_fn()` devolve o resultado ou **None** (o portão de qualidade do próprio
    Nano rejeitou). Qualquer exceção do Nano também cai no fallback — nunca
    derruba a tarefa. Registra quem serviu via `recorder(task, served_by)`.
    Retorna `(resultado, served_by)` com `served_by ∈ {"nano","teacher"}`."""
    result = None
    if nano_available and task_enabled(task):
        try:
            result = nano_fn()
        except Exception:
            result = None
    served_by = "nano" if result else "teacher"
    if not result:
        result = fallback_fn()
    if recorder is not None:
        try:
            recorder(task, served_by)
        except Exception:
            pass
    return result, served_by
