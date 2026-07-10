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
