"""Briefing diário (M4, Épico 4.1) — o A.P.O.L.O. te aborda de manhã com um
resumo falado do que importa: o que ele aprendeu enquanto você descansava, o que
vocês fizeram, a agenda do dia e pendências.

`build_briefing` compõe um dict com os dados estruturados + um `text` em PT-BR
pronto para ser FALADO (via TTS) ou lido. É determinístico (template, sem LLM) —
confiável e testável; o scheduler o dispara uma vez por manhã como notificação.
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("apolo.briefing")


def _greeting(now: datetime) -> str:
    h = now.hour
    if h < 12:
        return "Bom dia"
    if h < 18:
        return "Boa tarde"
    return "Boa noite"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def build_briefing(db=None, episodic=None, learner=None,
                   hours: int = 12, now: datetime | None = None) -> dict:
    """Monta o briefing. `hours` = janela de 'enquanto você esteve fora'."""
    now = now or datetime.now()
    greeting = _greeting(now)

    # ── O que aprendi (digest por setor) ──
    learned: list[dict] = []
    if db:
        try:
            learned = db.get_learned_since(hours)
        except Exception as e:
            logger.debug(f"briefing learned: {e}")
    from src.topics import classify_sector
    by_sector: dict[str, int] = {}
    for it in learned:
        by_sector[classify_sector(it.get("topic", ""))] = \
            by_sector.get(classify_sector(it.get("topic", "")), 0) + 1
    top_sectors = sorted(by_sector.items(), key=lambda x: x[1], reverse=True)[:3]

    # ── O que fizemos (episódios recentes) ──
    episodes: list[dict] = []
    if episodic:
        try:
            episodes = episodic.recent(3)
        except Exception as e:
            logger.debug(f"briefing episodes: {e}")

    # ── Agenda do dia (estudos agendados ativos) ──
    schedules: list[dict] = []
    if db:
        try:
            schedules = [s for s in db.list_schedules() if s.get("enabled")]
        except Exception as e:
            logger.debug(f"briefing schedules: {e}")

    # ── Pendências (notificações não lidas) ──
    unread = 0
    if db:
        try:
            unread = db.unread_count()
        except Exception as e:
            logger.debug(f"briefing unread: {e}")

    text = _compose_text(greeting, len(learned), top_sectors, episodes, schedules, unread)
    return {
        "greeting": greeting,
        "generated_at": now.isoformat(),
        "learned_count": len(learned),
        "top_sectors": [{"sector": s, "count": c} for s, c in top_sectors],
        "episodes": [{"title": e.get("title"), "occurred_at": e.get("occurred_at")}
                     for e in episodes],
        "schedules_today": [{"topic": s.get("topic"), "time": s.get("time_of_day")}
                            for s in schedules],
        "unread_notifications": unread,
        "text": text,
    }


def _compose_text(greeting: str, learned_count: int, top_sectors: list,
                  episodes: list, schedules: list, unread: int) -> str:
    from src.topics import SECTOR_LABELS
    parts = [f"{greeting}!"]

    if learned_count:
        frase = f"Enquanto você esteve fora, estudei {_plural(learned_count, 'tópico novo', 'tópicos novos')}"
        if top_sectors:
            labels = [SECTOR_LABELS.get(s, s) for s, _ in top_sectors]
            frase += ", principalmente em " + _join_natural(labels)
        parts.append(frase + ".")
    else:
        parts.append("Ainda não estudei nada novo nesta janela.")

    if episodes:
        titles = [e.get("title", "") for e in episodes if e.get("title")]
        if titles:
            parts.append("Recentemente nós: " + _join_natural(titles) + ".")

    if schedules:
        topics = [s.get("topic", "") for s in schedules][:3]
        parts.append(f"Na sua agenda de estudos: " + _join_natural(topics) + ".")

    if unread:
        parts.append(f"Você tem {_plural(unread, 'notificação não lida', 'notificações não lidas')}.")

    if learned_count == 0 and not episodes and not schedules and not unread:
        parts.append("Nada de novo por aqui — estou pronto quando você quiser.")

    return " ".join(parts)


def _join_natural(items: list[str]) -> str:
    """['a','b','c'] → 'a, b e c'."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]
