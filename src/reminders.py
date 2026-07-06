"""Detecção de lembretes/follow-ups em conversas (M4, Épico 4.2).

Quando o usuário pede "me lembra de X", "lembrete: X" ou "não me deixa esquecer
de Y", o A.P.O.L.O. anota um lembrete — e resurfaceia no momento certo. A
extração é DETERMINÍSTICA (regex, sem LLM): confiável, barata e testável.

`extract_reminders(text)` → lista de {text, due_at} (due_at é datetime ou None).
"""
import re
from datetime import datetime, timedelta

# Gatilho principal: "me lembra/lembre/lembrar de ...", "lembrete: ...".
# \b após o radical evita casar 'lembrança'/'lembrado' etc.
_CUE = re.compile(
    r"\b(?:me\s+)?lembr(?:a|e|ar|ete|e-me)\b[\s:,\-]*"
    r"(?:de\s+|que\s+|pra\s+|para\s+|o\s+de\s+)?",
    re.IGNORECASE,
)
# Variante: "não me deixa esquecer (de) ...".
_ESQUECER = re.compile(r"n[ãa]o\s+me\s+deixa?\s+esquecer\s+(?:de\s+)?", re.IGNORECASE)

# Datas relativas simples (a hora padrão do vencimento é 9h).
_DUE_HOUR = 9


def extract_reminders(text: str, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    if not text:
        return []
    content = None
    for rx in (_ESQUECER, _CUE):        # esquecer primeiro (mais específico)
        m = rx.search(text)
        if m:
            content = text[m.end():].strip()
            break
    if content is None:
        return []
    # Corta em quebra de frase e tira pontuação/aspas nas pontas.
    content = re.split(r"[.!?\n]", content, maxsplit=1)[0].strip(" \t\"'.,!?-")
    if len(content) < 2:
        return []
    due = _parse_due(content, now)
    return [{"text": content[:300], "due_at": due}]


def _parse_due(text: str, now: datetime) -> datetime | None:
    """Extrai um vencimento relativo simples do texto do lembrete. None se não
    houver expressão de tempo reconhecida (lembrete sem data — fica pendente)."""
    low = text.lower()

    def at_hour(d: datetime) -> datetime:
        return d.replace(hour=_DUE_HOUR, minute=0, second=0, microsecond=0)

    if "depois de amanhã" in low or "depois de amanha" in low:
        return at_hour(now + timedelta(days=2))
    if "amanhã" in low or "amanha" in low:
        return at_hour(now + timedelta(days=1))
    if "hoje" in low or "mais tarde" in low:
        # Hoje: se já passou das 9h, vence em +2h; senão às 9h.
        return now + timedelta(hours=2) if now.hour >= _DUE_HOUR else at_hour(now)
    if ("semana que vem" in low or "próxima semana" in low
            or "proxima semana" in low or "semana que vem" in low):
        return at_hour(now + timedelta(days=7))
    m = re.search(r"(?:daqui a|em)\s+(\d{1,3})\s+dias?", low)
    if m:
        return at_hour(now + timedelta(days=int(m.group(1))))
    m = re.search(r"(?:daqui a|em)\s+(\d{1,3})\s+horas?", low)
    if m:
        return now + timedelta(hours=int(m.group(1)))
    return None
