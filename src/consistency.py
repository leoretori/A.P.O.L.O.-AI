"""Self-consistency barata (M7, Épico 7.3).

Em perguntas críticas, amostrar 2–3 respostas e RECONCILIAR: se elas concordam, a
confiança é alta; se divergem, sinaliza incerteza (o modelo "não sabe" e chuta
diferente a cada vez — sinal clássico de alucinação).

A reconciliação é DETERMINÍSTICA e testável (concordância = sobreposição léxica
entre as amostras). A amostragem (chamar o LLM N vezes) é um wrapper fino com o
sampler INJETÁVEL — nos testes é um fake, em produção é o modelo leve com
temperatura. Barato: só roda sob demanda, não em toda resposta.
"""
from __future__ import annotations

import re
import unicodedata
from itertools import combinations

_STOP = {
    "para", "como", "mais", "com", "uma", "que", "dos", "das", "nao", "sim",
    "esse", "essa", "isso", "este", "esta", "pelo", "pela", "são", "sao", "foi",
    "ser", "tem", "sobre", "entre", "the", "and", "for", "with", "você", "voce",
}


def _tokens(text: str) -> set[str]:
    s = "".join(c for c in unicodedata.normalize("NFD", (text or "").lower())
                if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z0-9]{4,}", s) if w not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def pairwise_agreement(answers: list[str]) -> float:
    """Concordância média entre todos os pares de respostas (Jaccard). 0..1."""
    toks = [_tokens(a) for a in answers if a and a.strip()]
    if len(toks) < 2:
        return 1.0
    scores = [_jaccard(x, y) for x, y in combinations(toks, 2)]
    return round(sum(scores) / len(scores), 3)


def _medoid(answers: list[str]) -> str:
    """A resposta mais 'central' — a que mais concorda com as outras."""
    toks = [_tokens(a) for a in answers]
    best_i, best_sum = 0, -1.0
    for i in range(len(answers)):
        total = sum(_jaccard(toks[i], toks[j]) for j in range(len(answers)) if j != i)
        if total > best_sum:
            best_i, best_sum = i, total
    return answers[best_i]


def reconcile(answers: list[str], threshold: float = 0.35) -> dict:
    """Reconcilia amostras → {n, agreement, agreed, consensus, note}."""
    clean = [a for a in (answers or []) if a and a.strip()]
    if len(clean) < 2:
        return {"n": len(clean), "agreement": 1.0, "agreed": True,
                "consensus": clean[0] if clean else "", "note": None}
    score = pairwise_agreement(clean)
    agreed = score >= threshold
    return {
        "n": len(clean),
        "agreement": score,
        "agreed": agreed,
        "consensus": _medoid(clean),
        "note": None if agreed else
        ("⚠️ Gerei respostas diferentes para isto a cada tentativa — a confiança é "
         "baixa; trate como incerto e confirme."),
    }


def self_consistent_answer(question: str, sampler, n: int = 3) -> dict:
    """Amostra `n` respostas via `sampler(question) -> str` e reconcilia.
    `sampler` é injetável (fake nos testes; LLM leve com temperatura em produção)."""
    n = max(2, min(int(n or 3), 5))
    samples = []
    for _ in range(n):
        try:
            s = sampler(question)
        except Exception:
            s = ""
        if s and s.strip():
            samples.append(s.strip())
    result = reconcile(samples)
    result["samples"] = samples
    return result
