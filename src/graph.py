"""Grafo de conhecimento — conexões explícitas entre tópicos (M8, Épico 8.3).

Fecha o DoD do M8: responder "como X se conecta com Y?" usando o que o A.P.O.L.O.
aprendeu SOZINHO. Dois tópicos se conectam pelos CONCEITOS que compartilham (termos
significativos em comum nas suas sínteses); se não há laço direto, procura-se uma
PONTE (um 3º tópico ligado aos dois). Tudo determinístico e testável, sem LLM.
"""
from __future__ import annotations

import re
import unicodedata

_STOP = {
    "para", "como", "mais", "com", "uma", "que", "dos", "das", "nao", "sim",
    "esse", "essa", "isso", "este", "esta", "pelo", "pela", "são", "sao", "foi",
    "ser", "tem", "sobre", "entre", "the", "and", "for", "with", "você", "voce",
    "seu", "sua", "por", "num", "numa", "pode", "cada", "todo", "toda", "muito",
    "apolo", "insight", "essência", "essencia", "chave", "usar", "conceitos",
}


def _terms(text: str) -> list[str]:
    s = "".join(c for c in unicodedata.normalize("NFD", (text or "").lower())
                if unicodedata.category(c) != "Mn")
    seen, out = set(), []
    for w in re.findall(r"[a-z0-9]{4,}", s):
        if w not in _STOP and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def shared_concepts(text_a: str, text_b: str, limit: int = 8) -> list[str]:
    """Conceitos em comum entre dois tópicos (termos significativos partilhados),
    os mais específicos (longos) primeiro."""
    a, b = set(_terms(text_a)), set(_terms(text_b))
    common = a & b
    return sorted(common, key=lambda w: (-len(w), w))[:limit]


def strength(text_a: str, text_b: str) -> float:
    """Força da conexão = Jaccard dos termos significativos. 0..1."""
    a, b = set(_terms(text_a)), set(_terms(text_b))
    if not a or not b:
        return 0.0
    return round(len(a & b) / len(a | b), 3)


def explain(topic_a: str, text_a: str, topic_b: str, text_b: str,
            bridge: tuple[str, list[str], list[str]] | None = None) -> dict:
    """Monta a resposta 'como A se conecta com B'.
    `bridge` = (tópico_ponte, conceitos_A↔ponte, conceitos_ponte↔B) quando não há
    conexão direta forte."""
    shared = shared_concepts(text_a, text_b)
    s = strength(text_a, text_b)
    if shared:
        top = ", ".join(shared[:5])
        return {"connected": True, "kind": "direct", "strength": s,
                "shared": shared, "bridge": None,
                "answer": f"“{topic_a}” e “{topic_b}” se conectam por conceitos em "
                          f"comum: {top}."}
    if bridge:
        z, a2z, z2b = bridge
        return {"connected": True, "kind": "bridge", "strength": s,
                "shared": [], "bridge": z,
                "answer": f"“{topic_a}” e “{topic_b}” não se tocam direto, mas ambos "
                          f"passam por “{z}” "
                          f"({topic_a}↔{z}: {', '.join(a2z[:3])}; "
                          f"{z}↔{topic_b}: {', '.join(z2b[:3])})."}
    return {"connected": False, "kind": "none", "strength": s, "shared": [],
            "bridge": None,
            "answer": f"Ainda não achei uma conexão clara entre “{topic_a}” e "
                      f"“{topic_b}” no que estudei."}


def parse_connect_question(text: str) -> tuple[str, str] | None:
    """Extrai (X, Y) de 'como X se conecta com Y?' / 'relação entre X e Y'."""
    t = (text or "").strip().rstrip("?.")
    m = re.search(r"como\s+(.+?)\s+(?:se\s+)?(?:conecta|liga|relaciona)\w*\s+"
                  r"(?:com|com o|com a|ao|a|à)\s+(.+)$", t, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    m = re.search(r"(?:rela[çc][ãa]o|conex[ãa]o|liga[çc][ãa]o)\s+entre\s+(.+?)\s+e\s+(.+)$",
                  t, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None
