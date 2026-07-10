"""Memória relacional & temporal (M18) — a linha do tempo da vida do Leo.

Liga os episódios datados (M2) às ENTIDADES do modelo do Leo (M16): pessoas,
projetos e metas. Cada episódio deixa de ser texto solto e passa a saber QUEM,
O QUÊ e QUANDO tocou — o material para responder "o que estava rolando quando
fizemos X", "o que o fulano me pediu", "onde parei no projeto Y".

Tudo determinístico e testável: reusa o overlap de conceitos do grafo
(`src.graph`) e o casamento de nomes próprios, sem LLM.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

from src import graph

# Categorias do profile (M16) que viram entidades rastreáveis na linha do tempo.
_ENTITY_CATEGORIES = ("person", "project", "goal")
# Força mínima (Jaccard de conceitos do grafo) p/ ligar um episódio a uma
# entidade quando não há nome próprio em comum.
_LINK_MIN = 0.08
# Capitalizadas que NÃO são nome próprio — não viram âncora.
_CAP_STOP = {
    "eu", "me", "minha", "meu", "minhas", "meus", "uma", "um", "nao", "sim",
    "de", "do", "da", "dos", "das", "e", "ou", "com", "para", "por", "que",
    "projeto", "meta", "objetivo", "quero", "preciso", "gosto",
}


def _norm(text: str) -> str:
    """Minúsculas sem acento — o mesmo referencial de casamento do src.graph."""
    return "".join(
        c for c in unicodedata.normalize("NFD", (text or "").lower())
        if unicodedata.category(c) != "Mn"
    )


def _anchors(fact: str) -> set[str]:
    """Nomes próprios do fato (tokens capitalizados) — âncoras fortes para casar
    'Maria', 'Apolo' num episódio. Normalizados, sem os capitalizados comuns."""
    out: set[str] = set()
    for tok in re.findall(r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÜÇ][\wÀ-ÿ]+", fact or ""):
        n = _norm(tok)
        if len(n) >= 2 and n not in _CAP_STOP:
            out.add(n)
    return out


def _mentions(event_text: str, anchors: set[str]) -> bool:
    """O episódio cita algum nome próprio da entidade (palavra inteira)?"""
    if not anchors:
        return False
    words = set(re.findall(r"[a-z0-9]+", _norm(event_text)))
    return bool(anchors & words)


def entities(profile) -> list[dict]:
    """Extrai as entidades rastreáveis do profile (pessoa/projeto/meta),
    já com suas âncoras de nome próprio calculadas."""
    if not profile or not hasattr(profile, "by_category"):
        return []
    groups = profile.by_category()
    out: list[dict] = []
    for cat in _ENTITY_CATEGORIES:
        for f in groups.get(cat, []):
            name = (f.get("fact") or "").strip()
            if name:
                out.append({
                    "id": f.get("id"),
                    "category": cat,
                    "name": name,
                    "anchors": _anchors(name),
                })
    return out


def _event_text(ep: dict) -> str:
    return f"{ep.get('title', '')} {ep.get('summary', '')}".strip()


def link_event(ep: dict, ents: list[dict]) -> dict:
    """Anota um episódio com as entidades que ele menciona (nome próprio OU
    conceitos em comum acima do limiar). Retorna o evento da linha do tempo."""
    text = _event_text(ep)
    refs: dict[str, list[str]] = {c: [] for c in _ENTITY_CATEGORIES}
    for e in ents:
        if _mentions(text, e["anchors"]) or graph.strength(text, e["name"]) >= _LINK_MIN:
            refs[e["category"]].append(e["name"])
    return {
        "id": ep.get("id"),
        "date": ep.get("occurred_at"),
        "title": ep.get("title", ""),
        "summary": ep.get("summary", ""),
        "refs": {c: v for c, v in refs.items() if v},
    }


def timeline(episodes: list[dict], profile, *, entity: str | None = None) -> list[dict]:
    """Linha do tempo da vida: cada episódio anotado com suas entidades.

    Os episódios já chegam do DB do mais recente ao mais antigo. `entity` filtra
    por uma entidade (casamento parcial, sem acento) — a base de "o que estava
    rolando em torno de X".
    """
    ents = entities(profile)
    events = [link_event(ep, ents) for ep in (episodes or [])]
    if entity:
        key = _norm(entity)
        events = [
            ev for ev in events
            if any(key in _norm(n) for names in ev["refs"].values() for n in names)
        ]
    return events


def people_overview(episodes: list[dict], profile) -> list[dict]:
    """Quem-é-quem (M18.2): cada pessoa do modelo com seu contexto derivado da
    linha do tempo — quando foi vista por último, em que projetos/metas apareceu
    e com quem coaparece. O grafo leve de relações, sem LLM.

    Pessoas que o Apolo conhece mas nunca surgiram num episódio vêm com
    `mentions: 0` (útil: "você me falou dela, mas não voltamos ao assunto").
    Ordenado por atividade (mais mencionada / mais recente primeiro).
    """
    ents = entities(profile)
    people = [e for e in ents if e["category"] == "person"]
    if not people:
        return []
    events = [link_event(ep, ents) for ep in (episodes or [])]
    out: list[dict] = []
    for p in people:
        name = p["name"]
        seen = [ev for ev in events if name in ev["refs"].get("person", [])]
        projects, goals, others = set(), set(), set()
        for ev in seen:
            projects.update(ev["refs"].get("project", []))
            goals.update(ev["refs"].get("goal", []))
            others.update(n for n in ev["refs"].get("person", []) if n != name)
        out.append({
            "name": name,
            "mentions": len(seen),
            "last_date": seen[0]["date"] if seen else None,   # events já ordenados
            "last_title": seen[0]["title"] if seen else None,
            "projects": sorted(projects),
            "goals": sorted(goals),
            "also_with": sorted(others),
        })
    out.sort(key=lambda x: (x["mentions"], x["last_date"] or ""), reverse=True)
    return out


# ─────────────────────────────────────────────────────────────────────────
# 18.3 — Recall que entende relações
# "o que o fulano me pediu?", "onde parei no projeto Y?" respondidos pela
# memória relacional, sempre DATADOS.
# ─────────────────────────────────────────────────────────────────────────

# (kind, regex). A ordem importa: padrões mais específicos primeiro.
_QUESTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("where_stopped", re.compile(
        r"onde\s+(?:eu\s+|a\s+gente\s+|n[óo]s\s+)?"
        r"(?:parei|paramos|paramos|ficamos|estava|est[aá]vamos|ficou)\s+"
        r"(?:n[oa]s?\s+|em\s+|com\s+)?(?:projeto\s+|meta\s+)?(.+)", re.I)),
    ("where_stopped", re.compile(
        r"(?:como|em\s+que\s+p[ée])\s+(?:est[aá]|anda|vai|ficou)\s+"
        r"(?:o\s+|a\s+)?(?:projeto|meta)\s+(.+)", re.I)),
    ("where_stopped", re.compile(r"status\s+d[oae]s?\s+(?:projeto\s+|meta\s+)?(.+)", re.I)),
    ("asked", re.compile(
        r"o\s+que\s+(?:o|a|os|as)\s+(.+?)\s+(?:me\s+|nos\s+)?"
        r"(?:pediu|pediram|falou|falaram|disse|disseram|mandou|mandaram|"
        r"queria|quer|precisa|precisava|sugeriu|comentou|combinou)\b", re.I)),
    ("about", re.compile(
        r"o\s+que\s+(?:rolou|aconteceu|houve|sei|temos|tem|teve)\s+"
        r"(?:com|sobre|de|d[oa])\s+(.+)", re.I)),
]


def parse_relational_question(text: str) -> dict | None:
    """Extrai {kind, entity} de uma pergunta relacional. None se não casar.

    kind ∈ {'asked' (o que alguém pediu), 'where_stopped' (onde parei em X),
    'about' (o que rolou com X)}.
    """
    t = (text or "").strip().rstrip("?.! ")
    for kind, rx in _QUESTION_PATTERNS:
        m = rx.search(t)
        if m:
            entity = m.group(1).strip(" \"'").rstrip("?.! ")
            if entity:
                return {"kind": kind, "entity": entity}
    return None


def _when(iso: str | None) -> str | None:
    """ISO → data legível 'dd/mm/aaaa'. Devolve o cru se não parsear."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(iso)[:10]


def answer_relational(text: str, episodes: list[dict], profile,
                      *, limit: int = 3) -> dict | None:
    """Responde uma pergunta relacional pela linha do tempo, SEMPRE datada.
    None se a pergunta não for relacional. Se for mas nada casar, retorna
    `found: False` com uma resposta honesta."""
    q = parse_relational_question(text)
    if not q:
        return None
    entity, kind = q["entity"], q["kind"]
    hits = timeline(episodes, profile, entity=entity)  # recente → antigo
    if not hits:
        return {"found": False, "kind": kind, "entity": entity, "episode": None,
                "when": None, "recent": [],
                "answer": f"Não encontrei nada na memória sobre “{entity}”."}
    latest = hits[0]
    when = _when(latest["date"])
    title = (latest["title"] or "").strip()
    summary = (latest["summary"] or "").strip()
    tail = f" {summary}" if summary else ""
    if kind == "asked":
        answer = f"A vez mais recente que “{entity}” aparece foi em {when}: {title}.{tail}"
    elif kind == "where_stopped":
        answer = f"Em “{entity}”, você parou em {when}: {title}.{tail}"
    else:
        answer = f"Sobre “{entity}”, o mais recente foi em {when}: {title}.{tail}"
    return {"found": True, "kind": kind, "entity": entity, "episode": latest,
            "when": when, "recent": hits[:limit], "answer": answer}
