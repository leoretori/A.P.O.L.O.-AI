"""Presença ambiente (M23, Épico 23.1) — o A.P.O.L.O. acompanha a agenda e
avisa ANTES de um compromisso chegar, não só quando perguntado. Evolução do
briefing (M4): de "uma vez por dia" para "no momento certo", sem virar ruído
(cada evento avisa uma vez só).

Determinístico, sem LLM — reusa o parser .ics do M6.3 (`calendar_read`), a
mesma fonte já autorizada em `calendar.read`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT_LOOKAHEAD_MIN = 15
_PRUNE_AFTER = timedelta(days=1)


def _event_key(ev: dict) -> str:
    """Chave estável do evento (resumo+início) — não depende de UID no .ics
    (nem todo gerador de calendário inclui um)."""
    start = ev.get("start")
    return f"{ev.get('summary', '')}|{start.isoformat() if start else ''}"


def heads_up_due(events: list[dict], now: datetime, already_notified: set,
                 lookahead_min: int = DEFAULT_LOOKAHEAD_MIN) -> list[dict]:
    """Eventos que começam dentro de [now, now+lookahead] e ainda não estão em
    `already_notified`. Função PURA — não muta o conjunto; quem chama decide
    quando marcar (só depois de notificar de verdade)."""
    due = []
    for ev in events:
        start = ev.get("start")
        if start is None or _event_key(ev) in already_notified:
            continue
        delta_min = (start - now).total_seconds() / 60
        if 0 <= delta_min <= lookahead_min:
            due.append(ev)
    return due


def format_heads_up(ev: dict) -> str:
    """Texto falável do aviso — o mesmo estilo do briefing/lembretes (M4)."""
    start = ev.get("start")
    when = start.strftime("%H:%M") if start else "?"
    where = f" em {ev['location']}" if ev.get("location") else ""
    return f"⏰ Daqui a pouco ({when}): {ev.get('summary') or '(sem título)'}{where}."


class PresenceMonitor:
    """Guarda o que já foi avisado ENTRE ticks do scheduler (reinicia no
    restart do app, como os outros marcadores de rotina — `_last_briefing_date`
    etc. — consequência aceitável e simples). Poda sozinho entradas de mais
    de 1 dia para não crescer sem limite."""

    def __init__(self) -> None:
        self._notified: dict[str, datetime] = {}

    def check(self, events: list[dict], now: datetime,
             lookahead_min: int = DEFAULT_LOOKAHEAD_MIN) -> list[dict]:
        self._prune(now)
        due = heads_up_due(events, now, set(self._notified), lookahead_min)
        for ev in due:
            self._notified[_event_key(ev)] = now
        return due

    def _prune(self, now: datetime) -> None:
        cutoff = now - _PRUNE_AFTER
        stale = [k for k, t in self._notified.items() if t < cutoff]
        for k in stale:
            del self._notified[k]


# ── Modos de presença (M23.3) — o Apolo se comporta conforme o momento do dia ──
DEFAULT_REST_START_HOUR = 23   # descanso: 23h–7h (atravessa a meia-noite)
DEFAULT_REST_END_HOUR = 7
DEFAULT_FOCUS_START_HOUR = 9   # foco: uma janela do período de trabalho
DEFAULT_FOCUS_END_HOUR = 12

MODE_LABELS = {"descanso": "😴 Descanso", "foco": "🎯 Foco", "trabalho": "💼 Trabalho"}

# Kinds de baixa prioridade que o modo 'descanso' silencia ("sem incomodar").
# O que é sensível a tempo (lembrete/briefing/aviso de agenda do 23.1) SEMPRE
# avisa, não importa o modo — silenciar aquilo seria o oposto de presença útil.
QUIET_KINDS_IN_REST = {"study", "info"}


def current_mode(
    now: datetime, *,
    rest_start: int = DEFAULT_REST_START_HOUR,
    rest_end: int = DEFAULT_REST_END_HOUR,
    focus_start: int = DEFAULT_FOCUS_START_HOUR,
    focus_end: int = DEFAULT_FOCUS_END_HOUR,
) -> str:
    """'descanso' / 'foco' / 'trabalho' pelo horário — determinístico, sem
    LLM nem perfil (o horário sozinho já diz o essencial; personalizar por
    hábito fica para um próximo incremento). `rest` atravessa a meia-noite
    por padrão; fora das janelas configuradas, o padrão é 'trabalho'."""
    h = now.hour
    in_rest = (h >= rest_start or h < rest_end) if rest_start > rest_end \
        else (rest_start <= h < rest_end)
    if in_rest:
        return "descanso"
    if focus_start <= h < focus_end:
        return "foco"
    return "trabalho"


def should_notify(kind: str, mode: str) -> bool:
    """Decide se um aviso deste `kind` deve sair AGORA, dado o modo de
    presença. Só 'descanso' filtra, e só os kinds de baixa prioridade — o
    resto sempre avisa, porque é sensível a tempo."""
    return not (mode == "descanso" and kind in QUIET_KINDS_IN_REST)
