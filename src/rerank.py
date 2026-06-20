"""Reranker híbrido (vetorial + lexical) com corte de quase-duplicatas.

Usado pela memória semântica (ChromaDB, `rag.recall`) e pela base de conhecimento
(Supabase FTS, `knowledge.search`). Funções puras — sem IO, fáceis de testar.
"""

import re

# Palavras muito comuns (PT/EN) que não ajudam a discriminar relevância.
_STOPWORDS = {
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "ou", "em", "no", "na",
    "nos", "nas", "um", "uma", "uns", "umas", "para", "por", "com", "que", "se", "ao",
    "aos", "à", "às", "the", "of", "to", "and", "or", "in", "on", "for", "is", "are",
    "como", "qual", "quais", "quanto", "quem", "onde", "what", "how", "why",
}


def tokenize(text: str) -> set[str]:
    """Tokens significativos (minúsculos, sem stopwords, ≥3 chars)."""
    toks = re.findall(r"[a-zà-ÿ0-9]+", (text or "").lower())
    return {t for t in toks if len(t) >= 3 and t not in _STOPWORDS}


def lexical_overlap(query_tokens: set[str], text: str) -> float:
    """Fração dos tokens da consulta presentes no texto (0..1)."""
    if not query_tokens:
        return 0.0
    text_tokens = tokenize(text)
    if not text_tokens:
        return 0.0
    return len(query_tokens & text_tokens) / len(query_tokens)


def rerank(query: str, candidates: list[dict], top: int,
           text_keys: tuple[str, ...] = ("title", "snippet"),
           w_vector: float = 0.65, w_lexical: float = 0.35,
           w_recency: float = 0.0) -> list[dict]:
    """Reordena candidatos por score híbrido (vetorial + lexical [+ recência]) e
    remove quase-duplicatas (mesmo título ou alta sobreposição de tokens).

    Cada candidato é um dict; o texto avaliado é a junção de `text_keys`. Se houver
    'relevance' numérico, entra como sinal vetorial; senão usa 0.5 de base. Se
    `w_recency` > 0, usa o campo 'recency' (0..1, mais recente → mais perto de 1)
    para dar leve preferência a conhecimento recém-estudado. Os dicts originais são
    preservados (com um campo 'score' adicionado)."""
    qtokens = tokenize(query)
    scored: list[tuple[float, dict]] = []
    for c in candidates:
        rel = c.get("relevance")
        vec = rel if isinstance(rel, (int, float)) else 0.5
        text = " ".join(str(c.get(k, "")) for k in text_keys)
        lex = lexical_overlap(qtokens, text)
        score = w_vector * vec + w_lexical * lex
        if w_recency > 0:
            rec = c.get("recency")
            score += w_recency * (rec if isinstance(rec, (int, float)) else 0.0)
        c = {**c, "score": round(score, 4)}
        scored.append((c["score"], c))
    scored.sort(key=lambda x: x[0], reverse=True)

    out: list[dict] = []
    seen_titles: set[str] = set()
    kept_tokens: list[set[str]] = []
    for _, c in scored:
        title_key = str(c.get("title") or "").strip().lower()
        if title_key and title_key in seen_titles:
            continue
        body = " ".join(str(c.get(k, "")) for k in text_keys if k != "title")
        ctoks = tokenize(body)
        if any(ctoks and kt and len(ctoks & kt) / len(ctoks | kt) > 0.8 for kt in kept_tokens):
            continue
        out.append(c)
        if title_key:
            seen_titles.add(title_key)
        kept_tokens.append(ctoks)
        if len(out) >= top:
            break
    return out
