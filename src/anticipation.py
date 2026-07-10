"""Antecipação útil (M17.3): sugere retomar o que o Leo está negligenciando,
no momento certo, conectando metas + projetos + hábitos.

É o COMPLEMENTO do 17.1: lá o briefing destaca o que o Leo TOCOU; aqui nota as
metas/projetos ativos que NÃO se conectam com a atividade recente (via
`src.graph`) e propõe retomá-los, ancorando num hábito quando houver ("você
costuma estudar de manhã — que tal retomar?"). Determinístico, sem LLM,
reversível (some quando o foco volta a ser tocado ou sai do perfil).
"""

from __future__ import annotations

import logging
import unicodedata

logger = logging.getLogger("apolo.anticipation")

_FOCUS_CATEGORIES = ("project", "goal")  # projetos antes de metas (mais acionável)
# Abaixo deste Jaccard de conceitos, o foco NÃO foi tocado pela atividade recente.
_ENGAGED_MIN_STRENGTH = 0.06

# Período do dia a partir do texto de um hábito → dá o "quando" da sugestão.
_PERIODS = (
    ("de manhã", ("manha", "cedo", "amanhecer", "matinal")),
    ("à tarde", ("tarde",)),
    ("à noite", ("noite", "noturno", "anoitecer")),
)


def _norm(text: str) -> str:
    s = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def habit_period(habit_text: str) -> str | None:
    """'estuda IA de manhã' → 'de manhã'. None se não houver pista de horário."""
    low = _norm(habit_text)
    for label, cues in _PERIODS:
        if any(c in low for c in cues):
            return label
    return None


def _focus_items(groups: dict) -> list[dict]:
    items = []
    for cat in _FOCUS_CATEGORIES:
        for f in groups.get(cat, []):
            if f.get("fact"):
                items.append({"text": f["fact"], "category": cat})
    return items


def _first_habit_period(groups: dict) -> str | None:
    for h in groups.get("habit", []):
        p = habit_period(h.get("fact", ""))
        if p:
            return p
    return None


def suggest_anticipations(profile, recent_texts: list[str],
                          limit: int = 2) -> list[dict]:
    """Metas/projetos ativos que a atividade recente NÃO tocou → sugestões.

    `recent_texts` = títulos de episódios recentes + tópicos aprendidos.
    Retorna [{focus, focus_category, habit_period, text}] — projetos primeiro.
    """
    if not profile:
        return []
    try:
        groups = profile.by_category()
    except Exception as e:
        logger.debug(f"anticipation: {e}")
        return []
    focus_items = _focus_items(groups)
    if not focus_items:
        return []
    from src.graph import strength

    period = _first_habit_period(groups)
    out: list[dict] = []
    for foc in focus_items:
        engaged = any(strength(foc["text"], rt) >= _ENGAGED_MIN_STRENGTH
                      for rt in recent_texts)
        if engaged:
            continue
        alvo = "seu projeto" if foc["category"] == "project" else "sua meta"
        text = f"Você não avança {alvo} “{foc['text']}” ultimamente."
        if period:
            text += f" Você costuma se dedicar {period} — que tal retomar?"
        else:
            text += " Que tal reservar um tempo para retomar?"
        out.append({"focus": foc["text"], "focus_category": foc["category"],
                    "habit_period": period, "text": text})
        if len(out) >= limit:
            break
    return out
