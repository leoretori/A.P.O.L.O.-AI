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


# Categorias do perfil que representam "no que o Leo está focado agora" (M17.1).
_FOCUS_CATEGORIES = ("project", "goal")
# Só conta como "relevante para você" acima deste Jaccard de conceitos.
_FOCUS_MIN_STRENGTH = 0.06


def _focus_items(profile) -> list[dict]:
    """Metas e projetos ativos do perfil — o que importa PARA VOCÊ agora."""
    if not profile:
        return []
    try:
        groups = profile.by_category()
    except Exception as e:
        logger.debug(f"briefing focus: {e}")
        return []
    items: list[dict] = []
    for cat in _FOCUS_CATEGORIES:
        for f in groups.get(cat, []):
            text = f.get("fact", "")
            if text:
                items.append({"text": text, "category": cat})
    return items


def relevant_learned(learned: list[dict], focus_items: list[dict],
                     limit: int = 3) -> list[dict]:
    """Casa o que foi aprendido com as metas/projetos ativos do Leo.

    Para cada tópico aprendido, acha o foco de MAIOR conexão (Jaccard de
    conceitos via src.graph); mantém só os acima do limiar, os mais fortes
    primeiro. Determinístico e sem LLM.
    """
    if not learned or not focus_items:
        return []
    from src.graph import shared_concepts, strength

    scored: list[dict] = []
    for it in learned:
        topic = it.get("topic", "")
        if not topic:
            continue
        best, best_s, best_shared = None, 0.0, []
        for foc in focus_items:
            s = strength(topic, foc["text"])
            if s > best_s:
                best, best_s = foc, s
                best_shared = shared_concepts(topic, foc["text"], limit=3)
        if best and best_s >= _FOCUS_MIN_STRENGTH:
            scored.append({"topic": topic, "focus": best["text"],
                           "focus_category": best["category"],
                           "strength": best_s, "shared": best_shared})
    scored.sort(key=lambda x: x["strength"], reverse=True)
    # dedup por foco: no máx. 1 destaque por meta/projeto (evita repetir o foco)
    seen_focus: set[str] = set()
    out: list[dict] = []
    for s in scored:
        if s["focus"] in seen_focus:
            continue
        seen_focus.add(s["focus"])
        out.append(s)
        if len(out) >= limit:
            break
    return out


def build_briefing(db=None, episodic=None, learner=None, profile=None,
                   hours: int = 12, now: datetime | None = None) -> dict:
    """Monta o briefing. `hours` = janela de 'enquanto você esteve fora'.

    Com `profile` (M17.1), o briefing PRIORIZA o que se conecta com as suas
    metas e projetos ativos, em vez de um resumo genérico.
    """
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

    # ── Priorização pessoal (M17.1): o que aprendi que toca suas metas/projetos ──
    focus_items = _focus_items(profile)
    relevant = relevant_learned(learned, focus_items)

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

    # ── Lembretes pendentes (follow-ups) ──
    reminders: list[dict] = []
    if db:
        try:
            reminders = db.list_reminders(pending_only=True, limit=5)
        except Exception as e:
            logger.debug(f"briefing reminders: {e}")

    # ── Pendências (notificações não lidas) ──
    unread = 0
    if db:
        try:
            unread = db.unread_count()
        except Exception as e:
            logger.debug(f"briefing unread: {e}")

    text = _compose_text(greeting, len(learned), top_sectors, episodes,
                         schedules, reminders, unread, relevant)
    return {
        "greeting": greeting,
        "generated_at": now.isoformat(),
        "learned_count": len(learned),
        "top_sectors": [{"sector": s, "count": c} for s, c in top_sectors],
        "relevant_to_you": [{"topic": r["topic"], "focus": r["focus"],
                             "focus_category": r["focus_category"],
                             "shared": r["shared"]} for r in relevant],
        "episodes": [{"title": e.get("title"), "occurred_at": e.get("occurred_at")}
                     for e in episodes],
        "schedules_today": [{"topic": s.get("topic"), "time": s.get("time_of_day")}
                            for s in schedules],
        "reminders": [{"text": r.get("text"), "due_at": r.get("due_at")}
                      for r in reminders],
        "unread_notifications": unread,
        "text": text,
    }


def _compose_text(greeting: str, learned_count: int, top_sectors: list,
                  episodes: list, schedules: list, reminders: list, unread: int,
                  relevant: list | None = None) -> str:
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

    # M17.1: destaca o que se conecta com o que VOCÊ está tocando (vem cedo,
    # logo após o resumo do aprendizado — é o que mais importa).
    for r in relevant or []:
        alvo = "seu projeto" if r["focus_category"] == "project" else "sua meta"
        parts.append(f"Isso conecta com {alvo} “{r['focus']}”: {r['topic']}.")

    if episodes:
        titles = [e.get("title", "") for e in episodes if e.get("title")]
        if titles:
            parts.append("Recentemente nós: " + _join_natural(titles) + ".")

    if schedules:
        topics = [s.get("topic", "") for s in schedules][:3]
        parts.append("Na sua agenda de estudos: " + _join_natural(topics) + ".")

    if reminders:
        rtexts = [r.get("text", "") for r in reminders][:3]
        parts.append("Você me pediu para lembrar: " + _join_natural(rtexts) + ".")

    if unread:
        parts.append(f"Você tem {_plural(unread, 'notificação não lida', 'notificações não lidas')}.")

    if learned_count == 0 and not episodes and not schedules and not reminders and not unread:
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
