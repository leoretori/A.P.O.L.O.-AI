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
