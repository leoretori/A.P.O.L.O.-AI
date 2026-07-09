"""Extração de candidatos ao modelo do Leo a partir das conversas (M16.2).

Determinístico (regex, sem LLM): varre uma mensagem em busca de sinais sobre o
usuário e devolve CANDIDATOS categorizados — nunca grava direto. O usuário
confirma antes de qualquer coisa entrar no perfil ("nada assumido").

Cada padrão captura a categoria (metas/projetos/hábitos/preferências/valores) e
o TRECHO relevante, que sob o cabeçalho da seção (ver profile.as_context) já lê
naturalmente: "## Preferências\n- respostas diretas".
"""

from __future__ import annotations

import re

MIN_LEN = 3
MAX_LEN = 120

# (categoria, regex). A 1ª captura é o conteúdo. Ordem = prioridade.
# \b no início evita casar no meio de palavra; o conteúdo vai até pontuação forte.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("goal", re.compile(r"\b(?:minha meta|meu objetivo|meu sonho)\s+(?:é|e|de|:)?\s*(.+)", re.I)),
    ("goal", re.compile(r"\b(?:quero|pretendo|planejo|almejo)\s+(.+)", re.I)),
    ("project", re.compile(r"\b(?:estou|tô|to)\s+(?:trabalhando|mexendo)\s+(?:no|na|em)\s+(.+)", re.I)),
    ("project", re.compile(r"\bmeu projeto\s+(?:é|e|se chama|:)?\s*(.+)", re.I)),
    ("habit", re.compile(r"\b(?:todo dia|todos os dias|toda manhã|sempre|costumo|tenho o hábito de)\s+(.+)", re.I)),
    ("preference", re.compile(r"\b(?:prefiro|gosto de|curto|adoro)\s+(.+)", re.I)),
    ("preference", re.compile(r"\bnão gosto de\s+(.+)", re.I)),
    ("value", re.compile(r"\b(?:valorizo|acredito em|pra mim é importante|é importante pra mim)\s+(.+)", re.I)),
]

# Sinais de horizonte para metas.
_LONG = re.compile(r"\b(longo prazo|algum dia|no futuro|um dia)\b", re.I)
_SHORT = re.compile(r"\b(curto prazo|hoje|essa semana|esta semana|agora|amanhã)\b", re.I)

# Negações que invalidam o candidato ("não prefiro", "não gosto de" é preference
# negativa e vale; mas "não quero" NÃO é meta).
_GOAL_NEG = re.compile(r"\bnão\s+(?:quero|pretendo|planejo)\b", re.I)


def _clean(text: str) -> str:
    """Corta o trecho na 1ª pontuação forte e normaliza espaços/rabicho."""
    text = text.strip()
    text = re.split(r"[.!?;\n]", text)[0]  # 1ª oração
    text = re.sub(r"\s+", " ", text).strip(" \"'`,-:")
    return text[:MAX_LEN].rsplit(" ", 1)[0].strip() if len(text) > MAX_LEN else text


def extract_candidates(message: str) -> list[dict]:
    """Devolve candidatos [{text, category, horizon?}] — no máx. 1 por categoria."""
    if not message:
        return []
    out: list[dict] = []
    seen_cats: set[str] = set()
    for category, pat in _PATTERNS:
        if category in seen_cats:
            continue
        if category == "goal" and _GOAL_NEG.search(message):
            continue
        m = pat.search(message)
        if not m:
            continue
        content = _clean(m.group(1))
        if not (MIN_LEN <= len(content) <= MAX_LEN):
            continue
        cand = {"text": content, "category": category}
        if category == "goal":
            if _LONG.search(message):
                cand["horizon"] = "long"
            elif _SHORT.search(message):
                cand["horizon"] = "short"
        out.append(cand)
        seen_cats.add(category)
    return out
