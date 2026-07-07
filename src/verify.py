"""Cadeia de verificação anti-alucinação (M7, Épico 7.2).

Para perguntas FACTUAIS, mede se a resposta está ANCORADA na base de conhecimento
(as fontes que o RAG recuperou) e sinaliza incerteza quando não está — em vez de o
A.P.O.L.O. afirmar com confiança algo que não tem lastro.

100% determinístico e testável (sem LLM): sinal por sobreposição léxica entre os
termos significativos da resposta e o conteúdo das fontes. Barato no CPU e honesto
— não decide se é VERDADE, decide se está APOIADO no que ele estudou.
"""
from __future__ import annotations

import re
import unicodedata

# Perguntas que pedem FATO (valem verificação) — interrogativos de conhecimento.
_FACTUAL = re.compile(
    r"\b(o que (é|sao|são|foi|era)|quem (é|foi|era|inventou|criou)|quando|onde|"
    r"quantos|quantas|qual (é|a|o|foi|seria)|quais|como funciona|"
    r"defina|definir|significa|significado de|por que|porque|o que significa)\b",
    re.I)
# Pedidos NÃO-factuais (não faz sentido verificar contra a base): criação/código/opinião.
_NON_FACTUAL = re.compile(
    r"\b(escreva|escrever|crie|criar|gere|gerar|faça|fazer|implemente|implementar|"
    r"corrija|corrigir|refatore|refatorar|traduza|traduzir|resuma|resumir|"
    r"você acha|voce acha|na sua opinião|na sua opiniao|sugira|sugerir|"
    r"me ajude a|desenhe|imagine)\b",
    re.I)

_STOP = {
    "para", "como", "mais", "seu", "sua", "por", "com", "uma", "que", "dos", "das",
    "não", "nao", "sim", "aqui", "esse", "essa", "isso", "este", "esta", "pelo",
    "pela", "são", "sao", "está", "esta", "foi", "ser", "tem", "num", "numa", "sobre",
    "entre", "quando", "onde", "qual", "quais", "quem", "porque", "pois", "então",
    "entao", "muito", "pode", "cada", "todo", "toda", "seus", "suas", "the", "and",
    "for", "with", "que", "você", "voce", "ele", "ela", "eles", "elas", "nos",
}


def _norm_tokens(text: str) -> list[str]:
    s = "".join(c for c in unicodedata.normalize("NFD", (text or "").lower())
                if unicodedata.category(c) != "Mn")
    words = re.findall(r"[a-z0-9]{4,}", s)
    return [w for w in words if w not in _STOP]


def is_factual_question(text: str) -> bool:
    """Pergunta que pede um FATO e não um trabalho criativo/código/opinião."""
    t = text or ""
    if _NON_FACTUAL.search(t):
        return False
    return bool(_FACTUAL.search(t))


def grounding_score(answer: str, sources: list) -> float:
    """Fração dos termos significativos da resposta que aparecem nas fontes. 0..1.
    `sources` pode ser lista de strings ou de dicts com 'content'/'snippet'/'text'."""
    ans_terms = set(_norm_tokens(answer))
    if not ans_terms:
        return 1.0                       # nada a verificar (resposta sem conteúdo)
    src_text = " ".join(_source_text(s) for s in (sources or []))
    src_terms = set(_norm_tokens(src_text))
    if not src_terms:
        return 0.0
    hit = len(ans_terms & src_terms)
    return round(hit / len(ans_terms), 3)


def _source_text(s) -> str:
    if isinstance(s, str):
        return s
    if isinstance(s, dict):
        return " ".join(str(s.get(k, "")) for k in ("content", "snippet", "text", "summary"))
    return str(s)


# Limiares (heurísticos; travados por teste)
_T_HIGH = 0.5
_T_OK = 0.25


def verdict(question: str, answer: str, sources: list) -> dict:
    """Avalia uma resposta. Retorna:
      checked   — se a verificação se aplica (pergunta factual)
      grounded  — se está suficientemente ancorada na base
      score     — sobreposição léxica 0..1
      label     — alta | media | baixa | sem_fonte | nao_factual
      note      — aviso de incerteza p/ mostrar ao usuário (ou None)
    """
    if not is_factual_question(question):
        return {"checked": False, "grounded": True, "score": 1.0,
                "label": "nao_factual", "note": None}
    if not sources:
        return {"checked": True, "grounded": False, "score": 0.0, "label": "sem_fonte",
                "note": ("⚠️ Não encontrei isso na minha base de conhecimento — "
                         "posso estar impreciso; confirme antes de confiar.")}
    score = grounding_score(answer, sources)
    if score >= _T_HIGH:
        label, grounded, note = "alta", True, None
    elif score >= _T_OK:
        label, grounded, note = "media", True, None
    else:
        label, grounded = "baixa", False
        note = ("⚠️ Baixa correspondência com o que estudei sobre isso — "
                "trate como incerto.")
    return {"checked": True, "grounded": grounded, "score": score,
            "label": label, "note": note}
